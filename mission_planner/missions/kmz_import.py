"""
Import of an area, linear, slope, geometric or waypoint mission exported by DJI Pilot 2 (.kmz) as a saved route of the
mission planner.

Only what the planner can export again exactly is imported: an area mission (straight down, or with the 4 oblique
passes) of an aircraft of drones.json, with photos every so many meters and heights in one of the planner's height modes, a
linear (strip) mission with the same options, a slope mission (Pilot 2's facade option on an area, heights above sea
level), a geometric (prism) mission round a block, its top face (the roof) mapped or not, or a waypoint mission whose
actions are those the planner writes (turning, tilting the gimbal, hovering, taking photos). An area or linear mission that follows the terrain from an
elevation model (DSM) in the file is imported above the ground with the DSM follow, and its DSM (read_kmz_dsm) becomes
the route's terrain.
Everything else (Smart Oblique, facade, video, panoramas, other route types...) is refused with the reason, so that a
route never silently flies something other than the file did.

The settings are read from wpmz/template.kml (the mission as set in Pilot 2): wpmz/waylines.wpml is what Pilot 2
computed from them, and the planner computes its own.
"""
import io
import logging
import math
import os
import re
import zipfile
import zlib
from xml.etree import ElementTree as ET

import rasterio
from rasterio.io import MemoryFile

from . import geoid, geometric, linear, slope, waypoints, wpml
from .cameras import CAMERAS_BY_MODEL

logger = logging.getLogger('app.logger')

TEMPLATE = "wpmz/template.kml"
MAX_TEMPLATE_SIZE = 10 * 1024 * 1024
MAX_DSM_SIZE = 50 * 1024 * 1024
MAX_VERTICES = 200
MAX_NAME = 255

TEMPLATE_TYPES = {"mapping2d": "ortho", "mapping3d": "oblique"}
OTHER_TEMPLATE_TYPES = {
    "mappingObject": "a Smart 3D (object) route", "targetdetection": "a patrol route",
}
ALTITUDE_MODES = {"realTimeFollowSurface": "agl", "relativeToStartPoint": "alt", "EGM96": "asl"}
TAKEOFF_MODES = {v: k for k, v in wpml.TAKEOFF_MODES.items()}
WAYPOINT_HEIGHT_MODES = {v: k for k, v in waypoints.HEIGHT_MODES.items()}
WAYPOINT_INTERVAL_MODES = {v: k for k, v in waypoints.PHOTO_INTERVAL_MODES.items()}
# The actions of a waypoint mission the planner can write again (zoom only sets the wide camera's focal length, which
# the planner leaves to the aircraft; gimbalEvenlyRotate eases a steady gimbal between points, from their pitches)
WAYPOINT_ACTIONS = ("rotateYaw", "gimbalRotate", "zoom", "takePhoto", "hover", "startRecord", "stopRecord",
                    "gimbalEvenlyRotate")

# Pilot 2 options the planner cannot reproduce: a mission with one of them on is refused (smartObliqueEnable is
# checked first, as a Smart Oblique mission also has its own shootType and heights)
UNSUPPORTED_OPTIONS = (
    ("facadeWaylineEnable", "facade"), ("quickOrthoMappingEnable", "quick ortho mapping"),
    ("doubleGridWaylineEnable", "double grid"), ("efficiencyFlightModeEnable", "efficiency flight mode"),
    ("caliFlightEnable", "calibration flight"),
)

# The planner's limits (planner_core.js LIMITS and parseForm)
LIMITS = {
    "globalShootHeight": (2, 500, "height"), "orthoCameraOverlapH": (10, 95, "overlap along the lines"),
    "orthoCameraOverlapW": (10, 95, "overlap between lines"), "takeOffSecurityHeight": (2, 1500, "takeoff security height"),
    "globalRTHHeight": (2, 1500, "return height"),
}


class KmzImportError(ValueError):
    pass


def read_corners(placemark, what="slope"):
    """The corners of a slope (or of a block's base), [[lon, lat, h], ...], h WGS84-ellipsoidal"""
    coordinates = placemark.find("/".join(wpml.k(t) for t in ("Polygon", "outerBoundaryIs", "LinearRing", "coordinates")))
    if coordinates is None or not coordinates.text:
        raise KmzImportError("The mission has no %s" % what)
    corners = []
    for point in coordinates.text.split():
        try:
            lon, lat, h = (float(v) for v in point.split(","))
        except ValueError:
            raise KmzImportError("The corners of the %s, each with its height, cannot be read" % what)
        if not (all(math.isfinite(v) for v in (lon, lat, h)) and -180 <= lon <= 180 and -85 <= lat <= 85):
            raise KmzImportError("The corners of the %s, each with its height, cannot be read" % what)
        corners.append([round(lon, 9), round(lat, 9), h])
    if len(corners) > 3 and corners[0] == corners[-1]:
        corners.pop()
    if not 3 <= len(corners) <= slope.MAX_CORNERS:
        raise KmzImportError("The %s needs between 3 and %d corners" % (what, slope.MAX_CORNERS))
    return corners


def read_slope_route(config, folder, placemark, name):
    """The route of a Pilot 2 slope mission: read_kmz_route for an area with the facade option"""
    check_options(placemark, allowed=("facadeWaylineEnable",))
    system = find(folder, "waylineCoordinateSysParam")
    if text(system, "coordinateMode") != "WGS84":
        raise KmzImportError("The mission's coordinates are not WGS84")
    if text(system, "heightMode") != "EGM96":
        raise KmzImportError("The slope's heights are in %s: Pilot 2 writes them above sea level (EGM96)" % text(system, "heightMode"))
    lenses, model = read_lenses(config, folder)
    values = read_values(config, folder, placemark)
    speed = number(folder, "autoFlightSpeed")
    check_speed(speed, "speed")
    transitional_speed, takeoff_mode, finish_action, exit_on_rc_lost = read_mission_actions(config)
    ref = read_takeoff_point(config)
    takeoff = None if ref is None else [ref[0], ref[1]]

    corners = read_corners(placemark)
    name = route_title(name)
    avoid_limit_area = is_on(config, "waylineAvoidLimitAreaMode")
    settings = {
        "name": name, "lens_visible": "true" if "visable" in lenses else "false", "lens_ir": "true" if "ir" in lenses else "false",
        "height": form_number(values["globalShootHeight"]), "overlap_h": form_number(values["orthoCameraOverlapH"]),
        "overlap_w": form_number(values["orthoCameraOverlapW"]), "speed": form_number(speed), "takeoff_mode": takeoff_mode,
        "takeoff_security_height": form_number(values["takeOffSecurityHeight"]),
        "rth_height": form_number(values["globalRTHHeight"]), "transitional_speed": form_number(transitional_speed),
        "avoid_limit_area": "true" if avoid_limit_area else "false",
        "takeoff_altitude": "" if ref is None else altitude_text(ref[2]), "finish_action": finish_action,
        "exit_on_rc_lost": exit_on_rc_lost, "corners": corners, "takeoff": takeoff,
    }

    def n(key):
        return float(settings[key])

    body = {
        "route_type": "slope", "model": model, "corners": corners, "height": n("height"),
        "cameras": [c for c in ("visable", "ir") if c in lenses], "overlap_h": n("overlap_h"), "overlap_w": n("overlap_w"),
        "speed": n("speed"), "takeoff_security_height": n("takeoff_security_height"), "rth_height": n("rth_height"),
        "finish_action": finish_action, "exit_on_rc_lost": exit_on_rc_lost,
        "takeoff_ref_point": None if ref is None else [ref[0], ref[1], n("takeoff_altitude")],
        "transitional_speed": n("transitional_speed"), "takeoff_mode": takeoff_mode,
        "avoid_limit_area": avoid_limit_area, "name": name,
    }
    return model, settings, body


def form_number(v):
    """A number as the planner's form keeps it: the shortest text that gives it back to float32 precision"""
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    for p in range(1, 18):
        text = "%.*g" % (p, v)
        if abs(float(text) - v) <= abs(v) * 2 ** -24:
            return text
    return repr(v)


def altitude_text(v):
    """An altitude as the export writes the takeoff point's: to the micrometre"""
    if v is None:
        return ""
    return ("%.6f" % v).rstrip("0").rstrip(".") if round(v, 6) else "0"


def blank(v):
    return "" if v is None else form_number(v)


# What reading an entry of a damaged or encrypted zip raises: a failed CRC or a short file, a password needed, a
# compression method Python does not have (AES), a broken deflate stream
ZIP_READ_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, RuntimeError, NotImplementedError, zlib.error)


def read_entry(z, name):
    """The bytes of an entry of an open zip; KmzImportError when it cannot be read"""
    try:
        return z.read(name)
    except ZIP_READ_ERRORS:
        raise KmzImportError("%s in the file cannot be read (the file is damaged or encrypted)" % name)


def read_template(data):
    """(root, names): the template's XML and the names of the files in the .kmz; KmzImportError when it has none
    that reads. Read once by an import and handed to read_kmz_route and read_kmz_dsm."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if TEMPLATE not in names:
                raise KmzImportError("This is not a Pilot 2 mission file: it has no %s" % TEMPLATE)
            if z.getinfo(TEMPLATE).file_size > MAX_TEMPLATE_SIZE:
                raise KmzImportError("The mission file is too large")
            template = read_entry(z, TEMPLATE)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError):
        raise KmzImportError("This is not a .kmz file (not a zip archive)")
    try:
        # ElementTree does not expand external entities; a DOCTYPE has no place in a mission file
        if b"<!DOCTYPE" in template or b"<!ENTITY" in template:
            raise ET.ParseError("DOCTYPE")
        root = ET.fromstring(template)
    except ET.ParseError:
        raise KmzImportError("The mission in the file cannot be read (%s is not valid XML)" % TEMPLATE)
    return root, names


def find(parent, tag):
    return None if parent is None else parent.find(wpml.q(tag))


def text(parent, tag, default=None):
    element = find(parent, tag)
    if element is None or element.text is None or not element.text.strip():
        return default
    return element.text.strip()


def number(parent, tag, default=None):
    value = text(parent, tag)
    if value is None:
        if default is None:
            raise KmzImportError("The mission has no %s" % tag)
        return default
    try:
        n = float(value)
    except ValueError:
        n = float("nan")
    if not math.isfinite(n):
        raise KmzImportError("The mission's %s is not a number: %r" % (tag, value))
    return n


def is_on(parent, tag):
    return text(parent, tag, "0") == "1"


def read_polygon(placemark):
    coordinates = placemark.find("/".join(wpml.k(t) for t in ("Polygon", "outerBoundaryIs", "LinearRing", "coordinates")))
    if coordinates is None or not coordinates.text:
        raise KmzImportError("The mission has no area")
    corners = []
    for point in coordinates.text.split():
        try:
            lon, lat = (float(v) for v in point.split(",")[:2])
        except ValueError:
            raise KmzImportError("The corners of the area cannot be read")
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -85 <= lat <= 85):
            raise KmzImportError("The corners of the area cannot be read")
        # To 0.1 mm, as the planner's drawing keeps them: its map refuses corners with more decimals
        corners.append([round(lon, 9), round(lat, 9)])
    if len(corners) > 3 and corners[0] == corners[-1]:
        corners.pop()
    if len(corners) < 3:
        raise KmzImportError("The area needs at least 3 corners")
    if len(corners) > MAX_VERTICES:
        raise KmzImportError("The area has too many corners (at most %d)" % MAX_VERTICES)
    return corners


def read_aircraft(config, names):
    """(model, cameras): the model whose drone, payload and payload sub enums are those of the file, and the cameras
    (their keys, "visable" and "ir") its lens names (imageFormat) are for that model"""
    drone = find(config, "droneInfo")
    payload = find(config, "payloadInfo")
    try:
        enums = (int(text(drone, "droneEnumValue", "")), int(text(drone, "droneSubEnumValue", "")))
        payload_enum = int(text(payload, "payloadEnumValue", ""))
        payload_sub = int(text(payload, "payloadSubEnumValue", ""))
    except ValueError:
        raise KmzImportError("The mission does not say which aircraft and camera it is for")
    for model, aircraft in wpml.AIRCRAFT.items():
        if aircraft.drone == enums and aircraft.payload == payload_enum:
            by_name = {c.lens or c.key: c.key for c in aircraft.cameras.values()}
            lenses = frozenset(by_name.get(name, name) for name in names)
            if lenses not in aircraft.payload_sub:
                raise KmzImportError("The mission's cameras (%s) cannot be planned for the %s yet: only the wide camera, "
                                     "or the thermal and wide cameras together" % (", ".join(sorted(names)), aircraft.name))
            # The cameras are read from imageFormat; the payload sub enum is only checked to be one the aircraft writes,
            # as Pilot 2 wrote 0 for an M4T waypoint route with both cameras (m4t-test-poi-waypoint.kmz), where every
            # other file with both says 2.
            if payload_sub not in aircraft.payload_sub.values():
                raise KmzImportError("The mission's camera settings do not match its cameras (%s)" % ", ".join(sorted(names)))
            return model, lenses
    raise KmzImportError("The mission is for an aircraft or camera the planner does not know yet (only the %s)"
                         % " and ".join(d.name for d in wpml.AIRCRAFT.values()))


def check_limits(values):
    for tag, (low, high, label) in LIMITS.items():
        if not low <= values[tag] <= high:
            raise KmzImportError("The %s (%g) must be between %g and %g" % (label, values[tag], low, high))


def check_speed(value, label):
    if not 0 < value <= wpml.MAX_SPEED:
        raise KmzImportError("The %s (%g m/s) must be more than 0 and at most %g m/s" % (label, value, wpml.MAX_SPEED))


def read_mission_actions(config):
    """(transitional speed, takeoff mode, finish action, signal-lost action) of the missionConfig"""
    transitional_speed = number(config, "globalTransitionalSpeed", 15.0)
    check_speed(transitional_speed, "speed to the first waypoint")
    takeoff_mode = TAKEOFF_MODES.get(text(config, "flyToWaylineMode", "safely"))
    finish_action = text(config, "finishAction", "goHome")
    exit_on_rc_lost = text(config, "exitOnRCLost", "goContinue")
    if takeoff_mode is None or finish_action not in wpml.FINISH_ACTIONS or exit_on_rc_lost not in wpml.RC_LOST:
        raise KmzImportError("The mission's takeoff, finish or signal-lost action is not one the planner offers")
    return transitional_speed, takeoff_mode, finish_action, exit_on_rc_lost


def read_takeoff_point(config):
    """(lat, lon, altitude) of the takeoff point, or None if the mission has none"""
    ref = text(config, "takeOffRefPoint")
    if ref is None:
        return None
    try:
        lat, lon, alt = (float(v) for v in ref.split(","))
    except ValueError:
        raise KmzImportError("The mission's takeoff point cannot be read")
    if not all(math.isfinite(v) for v in (lat, lon, alt)) or not (-85 <= lat <= 85 and -180 <= lon <= 180):
        raise KmzImportError("The mission's takeoff point cannot be read")
    return lat, lon, alt


def read_geometric_route(config, folder, name):
    """The route of a Pilot 2 geometric (prism) mission: the block's outline, base and height, and whether its roof (top
    face) is mapped"""
    placemark = folder.find(wpml.k("Placemark"))
    if placemark is None:
        raise KmzImportError("The mission has no block")
    system = find(folder, "waylineCoordinateSysParam")
    if text(system, "coordinateMode") != "WGS84":
        raise KmzImportError("The mission's coordinates are not WGS84")
    if text(system, "heightMode") != "EGM96":
        raise KmzImportError("The block's heights are in %s: Pilot 2 writes them above sea level (EGM96)" % text(system, "heightMode"))
    if text(placemark, "shootType", "distance") != "distance":
        raise KmzImportError("The mission takes photos every so many seconds: the planner only takes them every so many meters")
    if text(placemark, "trajectoryType", "horiz") != "horiz":
        raise KmzImportError("The mission flies up and down the walls: the planner only flies level loops round the block")
    if text(placemark, "startPositionType", "top") != "top":
        raise KmzImportError("The mission starts at the bottom of the block: the planner only starts at the top")
    lenses, model = read_lenses(config, folder)
    values = read_values(config, folder, placemark)
    speed = number(folder, "autoFlightSpeed")
    check_speed(speed, "speed")
    transitional_speed, takeoff_mode, finish_action, exit_on_rc_lost = read_mission_actions(config)
    ref = read_takeoff_point(config)
    takeoff = None if ref is None else [ref[0], ref[1]]

    corners = read_corners(placemark, "block")
    base = min(c[2] for c in corners)
    height = number(placemark, "height")
    if height is None or not geometric.MIN_BLOCK <= height <= geometric.MAX_BLOCK:
        raise KmzImportError("The block's height must be between %g and %g m" % (geometric.MIN_BLOCK, geometric.MAX_BLOCK))
    outline = [c[:2] for c in corners]
    roof = is_on(placemark, "shootTopFaceEnable")
    name = route_title(name)
    avoid_limit_area = is_on(config, "waylineAvoidLimitAreaMode")
    settings = {
        "name": name, "lens_visible": "true" if "visable" in lenses else "false", "lens_ir": "true" if "ir" in lenses else "false",
        "height": form_number(values["globalShootHeight"]), "overlap_h": form_number(values["orthoCameraOverlapH"]),
        "overlap_w": form_number(values["orthoCameraOverlapW"]), "speed": form_number(speed), "takeoff_mode": takeoff_mode,
        "takeoff_security_height": form_number(values["takeOffSecurityHeight"]),
        "rth_height": form_number(values["globalRTHHeight"]), "transitional_speed": form_number(transitional_speed),
        "avoid_limit_area": "true" if avoid_limit_area else "false",
        "takeoff_altitude": "" if ref is None else altitude_text(ref[2]), "finish_action": finish_action,
        "exit_on_rc_lost": exit_on_rc_lost, "base": form_number(base), "top": form_number(base + height),
        "outline": outline, "takeoff": takeoff, "roof": "true" if roof else "false",
    }

    def n(key):
        return float(settings[key])

    body = {
        "route_type": "geometric", "model": model, "outline": outline, "base": n("base"), "top": n("top"),
        "height": n("height"), "cameras": [c for c in ("visable", "ir") if c in lenses], "overlap_h": n("overlap_h"),
        "overlap_w": n("overlap_w"), "speed": n("speed"), "takeoff_security_height": n("takeoff_security_height"),
        "rth_height": n("rth_height"), "finish_action": finish_action, "exit_on_rc_lost": exit_on_rc_lost,
        "takeoff_ref_point": None if ref is None else [ref[0], ref[1], n("takeoff_altitude")],
        "transitional_speed": n("transitional_speed"), "takeoff_mode": takeoff_mode,
        "avoid_limit_area": avoid_limit_area, "roof": roof, "name": name,
    }
    return model, settings, body


def check_options(placemark, allowed=()):
    """Refuses the Pilot 2 options of an area, linear or slope mission that the planner cannot fly (but the `allowed`
    ones)"""
    if is_on(placemark, "smartObliqueEnable"):
        raise KmzImportError("This is a Smart Oblique mission: the planner cannot fly Smart Oblique yet. Export the "
                             "area without Smart Oblique in Pilot 2 to import it")
    for tag, label in UNSUPPORTED_OPTIONS:
        if tag not in allowed and is_on(placemark, tag):
            raise KmzImportError("The mission uses Pilot 2's %s option, which the planner cannot fly" % label)
    if text(placemark, "shootType", "distance") != "distance":
        raise KmzImportError("The mission takes photos every so many seconds: the planner only takes them every so many meters")


def dsm_file(folder, names):
    """The path in the file of the elevation model (DSM) an area or linear mission follows the terrain from, or None
    when it follows it in real time or not at all"""
    system = find(folder, "waylineCoordinateSysParam")
    if not is_on(system, "surfaceFollowModeEnable") or is_on(system, "isRealtimeSurfaceFollow"):
        return None
    path = text(system, "dsmFile")
    if not path or path not in names:
        raise KmzImportError("The mission follows the terrain from an elevation model (DSM) that is not in the file")
    return path


def read_height_mode(root, names, folder):
    """(height mode, altitude mode of the form, surface follow) of an area or linear mission; the surface follow is
    "dsm" for a mission over the elevation model in the file (Pilot 2 writes EGM96 with the terrain following on),
    "realtime" above the ground otherwise, None in the other height modes"""
    system = find(folder, "waylineCoordinateSysParam")
    if text(system, "coordinateMode") != "WGS84":
        raise KmzImportError("The mission's coordinates are not WGS84")
    height_mode = text(system, "heightMode")
    if dsm_file(folder, names):
        if height_mode != "EGM96":
            raise KmzImportError("The mission follows an elevation model (DSM) with heights in %s: Pilot 2 writes EGM96" % height_mode)
        return "realTimeFollowSurface", "agl", "dsm"
    if height_mode not in ALTITUDE_MODES:
        raise KmzImportError("The mission's height mode (%s) is not one the planner offers" % height_mode)
    return height_mode, ALTITUDE_MODES[height_mode], "realtime" if height_mode == "realTimeFollowSurface" else None


def read_lenses(config, folder):
    """(lenses, model) of an area or linear mission"""
    names = frozenset(l.strip() for l in text(find(folder, "payloadParam"), "imageFormat", "").split(",") if l.strip())
    model, lenses = read_aircraft(config, names)
    return lenses, model


def read_values(config, folder, placemark):
    """The values of an area or linear mission that have the planner's limits (LIMITS), checked"""
    system = find(folder, "waylineCoordinateSysParam")
    overlap = find(placemark, "overlap")
    values = {
        "globalShootHeight": number(system, "globalShootHeight"),
        "orthoCameraOverlapH": number(overlap, "orthoCameraOverlapH"), "orthoCameraOverlapW": number(overlap, "orthoCameraOverlapW"),
        "takeOffSecurityHeight": number(config, "takeOffSecurityHeight"), "globalRTHHeight": number(config, "globalRTHHeight", 100.0),
    }
    check_limits(values)
    return values


def sea_level(lat, lon, ellipsoidal):
    """An ellipsoidal height (takeOffRefPoint's) above sea level (EGM96, missions/geoid.py), None when the geoid grid
    cannot be had: the editor's field then stays blank, to be fetched"""
    try:
        return ellipsoidal - geoid.undulation(lat, lon)
    except geoid.GeoidError as e:
        logger.warning("DJI Mission Planner: the imported takeoff point's height above sea level is unknown: %s", e)
        return None


def read_takeoff(config, placemark, altitude_mode, height):
    """(takeoff [lat, lon] or None, ground height there above sea level, ellipsoidal ground height there) of an area
    or linear mission flown at that height. takeOffRefPoint's height is ellipsoidal (DJI's WPML reference)."""
    takeoff, takeoff_altitude, ellipsoidal = None, None, None
    ref = read_takeoff_point(config)
    if ref is not None:
        lat, lon, alt = ref
        takeoff = [lat, lon]
        if altitude_mode == "asl":
            # The mission's altitudes are the ground's plus the height (wpml.asl_heights)
            takeoff_altitude = number(placemark, "height") - height
            ellipsoidal = number(placemark, "ellipsoidHeight") - height
        else:
            takeoff_altitude, ellipsoidal = sea_level(lat, lon, alt), alt
        if takeoff_altitude is not None and not -500 <= takeoff_altitude <= 9000:
            raise KmzImportError("The ground height at the takeoff point (%g m) must be between -500 and 9000 m" % takeoff_altitude)
    elif altitude_mode == "asl":
        raise KmzImportError("The mission's heights are above sea level but it has no takeoff point")
    return takeoff, takeoff_altitude, ellipsoidal


def route_title(name):
    return (name or "").strip()[:MAX_NAME] or "imported-route"


def read_kmz_route(data, name, template=None):
    """
    The route of a Pilot 2 .kmz file.

    :param data: the bytes of the file
    :param name: the route's name (the file's name without .kmz)
    :param template: read_template(data), when the caller has it already
    :return: (model, settings, body): the aircraft model, the planner's saved form (as Route.settings) and the
        plan request body the form gives (planner_core.js requestBody)
    :raises KmzImportError: why the file cannot be imported
    """
    root, names = template or read_template(data)
    document = root.find(wpml.k("Document"))
    config = find(document, "missionConfig")
    folder = None if document is None else document.find(wpml.k("Folder"))
    if config is None or folder is None:
        raise KmzImportError("This is not a Pilot 2 mission file: it has no mission settings")

    template_type = text(folder, "templateType")
    if template_type == "waypoint":
        return read_waypoint_route(config, folder, name)
    if template_type == "mappingStrip":
        return read_linear_route(root, names, config, folder, name)
    if template_type == "mappingPrism":
        return read_geometric_route(config, folder, name)
    if template_type not in TEMPLATE_TYPES:
        what = OTHER_TEMPLATE_TYPES.get(template_type, "a %r route" % template_type)
        raise KmzImportError("This is %s: only area, linear, slope, geometric and waypoint routes can be imported" % what)
    collection_mode = TEMPLATE_TYPES[template_type]

    placemark = folder.find(wpml.k("Placemark"))
    if placemark is None:
        raise KmzImportError("The mission has no area")
    if template_type == "mapping2d" and is_on(placemark, "facadeWaylineEnable"):
        return read_slope_route(config, folder, placemark, name)
    check_options(placemark)
    height_mode, altitude_mode, surface_follow = read_height_mode(root, names, folder)
    lenses, model = read_lenses(config, folder)

    if collection_mode == "oblique" and surface_follow == "realtime":
        raise KmzImportError("The oblique mission follows the ground in real time: the planner flies oblique missions "
                             "above the ground over an elevation model (DSM), as Pilot 2 does")

    values = read_values(config, folder, placemark)
    height = values["globalShootHeight"]
    if altitude_mode != "asl":
        # Pilot 2 measures the height from a ground height it keeps for the area, and flies the difference from the
        # takeoff point's: the planner flies the height itself
        flown = number(placemark, "height", height)
        if abs(flown - height) > 0.001:
            raise KmzImportError("The mission flies %g m above the takeoff point for a height of %g m: Pilot 2 measured "
                                 "it from a ground height for the area, which the planner does not keep" % (flown, height))
    margin = number(placemark, "margin", 0.0)
    if margin < 0:
        raise KmzImportError("The margin (%g) must be 0 or more" % margin)
    direction = number(placemark, "direction", 0.0) % 360
    speed = number(folder, "autoFlightSpeed")
    check_speed(speed, "speed")
    transitional_speed, takeoff_mode, finish_action, exit_on_rc_lost = read_mission_actions(config)
    takeoff, takeoff_altitude, ellipsoidal = read_takeoff(config, placemark, altitude_mode, height)
    overlap = find(placemark, "overlap")

    gimbal_pitch = inclined_overlap_h = inclined_overlap_w = inclined_speed = None
    if collection_mode == "oblique":
        gimbal_pitch = number(placemark, "inclinedGimbalPitch")
        if not -85 <= gimbal_pitch <= -40:
            raise KmzImportError("The gimbal tilt angle (%g) must be between -85 and -40 degrees" % gimbal_pitch)
        inclined_overlap_h = number(overlap, "inclinedCameraOverlapH", values["orthoCameraOverlapH"])
        inclined_overlap_w = number(overlap, "inclinedCameraOverlapW", values["orthoCameraOverlapW"])
        for v in (inclined_overlap_h, inclined_overlap_w):
            if not 10 <= v <= 95:
                raise KmzImportError("The oblique overlap (%g) must be between 10 and 95" % v)
        inclined_speed = number(placemark, "inclinedFlightSpeed")
        check_speed(inclined_speed, "oblique speed")

    polygon = read_polygon(placemark)
    name = route_title(name)
    elevation_optimize = text(placemark, "elevationOptimizeEnable", "1") == "1"
    avoid_limit_area = is_on(config, "waylineAvoidLimitAreaMode")

    settings = {
        "name": name, "lens_visible": "true" if "visable" in lenses else "false", "lens_ir": "true" if "ir" in lenses else "false",
        "height": form_number(height), "overlap_h": form_number(values["orthoCameraOverlapH"]),
        "overlap_w": form_number(values["orthoCameraOverlapW"]), "margin": form_number(margin), "direction": form_number(direction),
        "speed": form_number(speed), "altitude_mode": altitude_mode, "takeoff_mode": takeoff_mode,
        "takeoff_security_height": form_number(values["takeOffSecurityHeight"]), "rth_height": form_number(values["globalRTHHeight"]),
        "transitional_speed": form_number(transitional_speed), "elevation_optimize": "true" if elevation_optimize else "false",
        "avoid_limit_area": "true" if avoid_limit_area else "false", "photo_mode": "distance",
        "takeoff_altitude": altitude_text(takeoff_altitude), "finish_action": finish_action, "exit_on_rc_lost": exit_on_rc_lost,
        "collection_mode": collection_mode, "gimbal_pitch": blank(gimbal_pitch), "inclined_overlap_h": blank(inclined_overlap_h),
        "inclined_overlap_w": blank(inclined_overlap_w), "inclined_speed": blank(inclined_speed),
        "takeoff_ellipsoidal_height": altitude_text(ellipsoidal), "surface_follow": surface_follow or "realtime",
        "polygon": polygon, "takeoff": takeoff, "route_start": None,
    }

    # What the planner sends for that form (requestBody): its numbers are those of the form's text
    def n(key):
        return float(settings[key])

    def optional(key):
        return None if settings[key] == "" else float(settings[key])

    body = {
        "model": model, "polygon": polygon, "direction": n("direction"), "height": n("height"),
        "cameras": [c for c in ("visable", "ir") if c in lenses], "overlap_h": n("overlap_h"), "overlap_w": n("overlap_w"),
        "margin": n("margin"), "speed": n("speed"), "height_mode": height_mode,
        "takeoff_security_height": n("takeoff_security_height"), "rth_height": n("rth_height"),
        "finish_action": finish_action, "exit_on_rc_lost": exit_on_rc_lost,
        "takeoff_ref_point": None if takeoff is None or takeoff_altitude is None else [takeoff[0], takeoff[1], n("takeoff_altitude")],
        "transitional_speed": n("transitional_speed"), "takeoff_mode": takeoff_mode, "elevation_optimize": elevation_optimize,
        "avoid_limit_area": avoid_limit_area, "photo_mode": "distance", "route_start": None, "name": name,
        "collection_mode": collection_mode, "route_type": "area", "surface_follow": settings["surface_follow"],
    }
    if altitude_mode == "asl":
        body["takeoff_ellipsoidal_height"] = n("takeoff_ellipsoidal_height")
    if collection_mode == "oblique":
        body.update(gimbal_pitch=n("gimbal_pitch"), inclined_overlap_h=optional("inclined_overlap_h"),
                    inclined_overlap_w=optional("inclined_overlap_w"), inclined_speed=optional("inclined_speed"))
    return model, settings, body


def read_line(placemark):
    """The center line of a linear mission, [[lon, lat], ...], as precise as the planner's drawing keeps it"""
    coordinates = placemark.find("/".join(wpml.k(t) for t in ("LineString", "coordinates")))
    if coordinates is None or not coordinates.text:
        raise KmzImportError("The mission has no center line")
    points = []
    for point in coordinates.text.split():
        try:
            lon, lat = (float(v) for v in point.split(",")[:2])
        except ValueError:
            raise KmzImportError("The points of the center line cannot be read")
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -85 <= lat <= 85):
            raise KmzImportError("The points of the center line cannot be read")
        points.append([round(lon, 9), round(lat, 9)])
    if not 2 <= len(points) <= linear.MAX_POINTS:
        raise KmzImportError("The center line needs between 2 and %d points" % linear.MAX_POINTS)
    return points


def read_linear_route(root, names, config, folder, name):
    """The route of a Pilot 2 linear mission: read_kmz_route for a template of type mappingStrip"""
    placemark = folder.find(wpml.k("Placemark"))
    if placemark is None:
        raise KmzImportError("The mission has no center line")
    check_options(placemark)
    if is_on(placemark, "includeCenterEnable"):
        raise KmzImportError("The mission uses Pilot 2's option to include the center line, which the planner cannot fly")
    height_mode, altitude_mode, surface_follow = read_height_mode(root, names, folder)
    lenses, model = read_lenses(config, folder)

    values = read_values(config, folder, placemark)
    height = values["globalShootHeight"]
    if altitude_mode != "asl":
        # Pilot 2 measures the height from a ground height it keeps for the strip, and flies the difference from the
        # takeoff point's: the planner flies that difference as the route's height
        height = number(placemark, "height", height)
        if not 2 <= height <= 500:
            raise KmzImportError("The height (%g) must be between 2 and 500" % height)
    single_line = is_on(placemark, "singleLineEnable")
    left_extend = number(placemark, "leftExtend")
    right_extend = number(placemark, "rightExtend")
    if left_extend < 0 or right_extend < 0 or left_extend + right_extend <= 0:
        raise KmzImportError("The strip's widths to the left and to the right of the center line (%g and %g m) cannot be "
                             "negative, and the strip needs a width" % (left_extend, right_extend))
    speed = number(folder, "autoFlightSpeed")
    check_speed(speed, "speed")
    transitional_speed, takeoff_mode, finish_action, exit_on_rc_lost = read_mission_actions(config)
    takeoff, takeoff_altitude, ellipsoidal = read_takeoff(config, placemark, altitude_mode, height)

    line = read_line(placemark)
    name = route_title(name)
    elevation_optimize = text(placemark, "elevationOptimizeEnable", "1") == "1"
    avoid_limit_area = is_on(config, "waylineAvoidLimitAreaMode")

    settings = {
        "name": name, "lens_visible": "true" if "visable" in lenses else "false", "lens_ir": "true" if "ir" in lenses else "false",
        "height": form_number(height), "overlap_h": form_number(values["orthoCameraOverlapH"]),
        "overlap_w": form_number(values["orthoCameraOverlapW"]), "speed": form_number(speed), "altitude_mode": altitude_mode,
        "takeoff_mode": takeoff_mode, "takeoff_security_height": form_number(values["takeOffSecurityHeight"]),
        "rth_height": form_number(values["globalRTHHeight"]), "transitional_speed": form_number(transitional_speed),
        "elevation_optimize": "true" if elevation_optimize else "false",
        "avoid_limit_area": "true" if avoid_limit_area else "false", "takeoff_altitude": altitude_text(takeoff_altitude),
        "finish_action": finish_action, "exit_on_rc_lost": exit_on_rc_lost,
        "takeoff_ellipsoidal_height": altitude_text(ellipsoidal), "left_extend": form_number(left_extend),
        "right_extend": form_number(right_extend), "single_line": "true" if single_line else "false",
        "surface_follow": surface_follow or "realtime", "line": line, "takeoff": takeoff,
    }

    def n(key):
        return float(settings[key])

    body = {
        "route_type": "linear", "model": model, "line": line, "left_extend": n("left_extend"),
        "right_extend": n("right_extend"), "single_line": single_line, "height": n("height"),
        "cameras": [c for c in ("visable", "ir") if c in lenses], "overlap_h": n("overlap_h"), "overlap_w": n("overlap_w"),
        "speed": n("speed"), "height_mode": height_mode, "takeoff_security_height": n("takeoff_security_height"),
        "rth_height": n("rth_height"), "finish_action": finish_action, "exit_on_rc_lost": exit_on_rc_lost,
        "takeoff_ref_point": None if takeoff is None or takeoff_altitude is None else [takeoff[0], takeoff[1], n("takeoff_altitude")],
        "transitional_speed": n("transitional_speed"), "takeoff_mode": takeoff_mode, "elevation_optimize": elevation_optimize,
        "avoid_limit_area": avoid_limit_area, "name": name, "surface_follow": settings["surface_follow"],
    }
    if altitude_mode == "asl":
        body["takeoff_ellipsoidal_height"] = n("takeoff_ellipsoidal_height")
    return model, settings, body


def waypoint_turn_mode(turn, straight_line):
    """The planner's turn mode for Pilot 2's: passing the points is a curve when the legs are not flown straight"""
    if turn == waypoints.STOP:
        return "stop"
    if turn == waypoints.TURN_MODES["pass"]:
        return "pass" if straight_line else "curve"
    return None


def read_route_group(group, trigger, n, last, route):
    """Note in route a group run over the whole route (interval photos, easing a steady gimbal between points),
    started at point n of last; False for a group of the point itself"""
    actions = [text(a, "actionActuatorFunc") for a in group.findall(wpml.q("action"))]
    if trigger in WAYPOINT_INTERVAL_MODES:
        if (n != 1 or actions != ["takePhoto"] or number(group, "actionGroupStartIndex", 0.0) != 0
                or number(group, "actionGroupEndIndex", 0.0) != last - 1):
            raise KmzImportError("The interval photos at point %d do not run from the first point to the last with "
                                 "only photos: the planner only takes them over the whole route" % n)
        route["photo_interval_mode"] = WAYPOINT_INTERVAL_MODES[trigger]
        route["photo_interval"] = number(find(group, "actionTrigger"), "actionTriggerParam")
        return True
    if trigger == "betweenAdjacentPoints":
        if actions != ["gimbalEvenlyRotate"]:
            raise KmzImportError("The actions between point %d and the next do more than ease the gimbal: the planner "
                                 "only does that" % n)
        return True
    return False


def read_point_actions(placemark, n, last, route):
    """(heading, pitch, photo, hover) of the actions at a waypoint; n is its number for the messages (from 1), last
    the number of the last point. The groups of the whole route (the video, interval photos) are noted in route."""
    heading = pitch = None
    photo, hover = False, 0.0
    for group in placemark.findall(wpml.q("actionGroup")):
        trigger = text(find(group, "actionTrigger"), "actionTriggerType")
        if read_route_group(group, trigger, n, last, route):
            continue
        if trigger != "reachPoint":
            raise KmzImportError("The actions at point %d run %s: the planner only runs them when the aircraft reaches "
                                 "the point" % (n, "on a %r trigger" % trigger if trigger else "without a trigger"))
        for action in group.findall(wpml.q("action")):
            func = text(action, "actionActuatorFunc")
            param = find(action, "actionActuatorFuncParam")
            if func == "rotateYaw":
                heading = number(param, "aircraftHeading")
            elif func == "gimbalRotate":
                if is_on(param, "gimbalYawRotateEnable") or is_on(param, "gimbalRollRotateEnable"):
                    raise KmzImportError("The gimbal at point %d turns sideways: the planner only tilts it" % n)
                if text(param, "gimbalRotateMode", "absoluteAngle") != "absoluteAngle":
                    raise KmzImportError("The gimbal at point %d turns by an angle from where it is: the planner only "
                                         "sets the angle itself" % n)
                if is_on(param, "gimbalPitchRotateEnable"):
                    pitch = number(param, "gimbalPitchRotateAngle")
            elif func == "hover":
                hover += number(param, "hoverTime")
            elif func == "takePhoto":
                photo = True
            elif func in ("startRecord", "stopRecord"):
                if n != (1 if func == "startRecord" else last):
                    raise KmzImportError("The video %s at point %d: the planner records it from the first point to "
                                         "the last" % ("starts" if func == "startRecord" else "stops", n))
                route[func] = True
    return heading, pitch, photo, hover


def read_waypoint_route(config, folder, name):
    """The route of a Pilot 2 waypoint mission: read_kmz_route for a template of type waypoint"""
    placemarks = folder.findall(wpml.k("Placemark"))
    if len(placemarks) < 2:
        raise KmzImportError("The mission needs at least 2 waypoints")

    # The actions the planner cannot write, all of them at once, with the points where they are
    unsupported = {}
    for n, placemark in enumerate(placemarks, start=1):
        for action in placemark.iter(wpml.q("action")):
            func = text(action, "actionActuatorFunc", "an unnamed action")
            if func not in WAYPOINT_ACTIONS:
                unsupported.setdefault(func, []).append(n)
    if unsupported:
        raise KmzImportError("The mission uses actions the planner cannot write yet: %s. Only turning, tilting the "
                             "gimbal, hovering and taking photos can be imported" % "; ".join(
                                 "%s (point%s %s)" % (func, "s" if len(at) > 1 else "", ", ".join(str(n) for n in sorted(set(at))))
                                 for func, at in unsupported.items()))

    system = find(folder, "waylineCoordinateSysParam")
    if text(system, "coordinateMode") != "WGS84":
        raise KmzImportError("The mission's coordinates are not WGS84")
    height_mode = WAYPOINT_HEIGHT_MODES.get(text(system, "heightMode"))
    if height_mode is None:
        raise KmzImportError("The mission's height mode (%s) is not one the planner offers" % text(system, "heightMode"))
    if is_on(folder, "caliFlightEnable"):
        raise KmzImportError("The mission uses Pilot 2's calibration flight option, which the planner cannot fly")

    heading_mode = text(find(folder, "globalWaypointHeadingParam"), "waypointHeadingMode", "followWayline")
    first_heading = find(placemarks[0], "waypointHeadingParam")
    if not is_on(placemarks[0], "useGlobalHeadingParam") and text(first_heading, "waypointHeadingMode") == "towardPOI":
        # Pilot 2 writes a Toward-POI route as following the route, with each point facing the POI
        heading_mode = "towardPOI"
    if heading_mode not in waypoints.HEADING_MODES:
        raise KmzImportError("The aircraft's heading mode (%s) is not one the planner offers: only following the route, "
                             "set by hand or toward a POI" % heading_mode)
    poi = None
    if heading_mode == "towardPOI":
        poi = read_poi(first_heading if first_heading is not None else find(folder, "globalWaypointHeadingParam"))
    turn_mode = waypoint_turn_mode(text(folder, "globalWaypointTurnMode"), text(folder, "globalUseStraightLine", "1") == "1")
    if turn_mode is None:
        raise KmzImportError("The mission's turn mode (%s) is not one the planner offers: only stopping at each point "
                             "or passing it in a curve" % text(folder, "globalWaypointTurnMode"))
    pitch_mode = text(folder, "gimbalPitchMode", "manual")
    if pitch_mode not in ("manual", "usePointSetting"):
        raise KmzImportError("The mission's gimbal pitch mode (%s) is not one the planner offers" % pitch_mode)

    height = number(folder, "globalHeight")
    speed = number(folder, "autoFlightSpeed")
    check_speed(speed, "speed")
    names = frozenset(l.strip() for l in text(find(folder, "payloadParam"), "imageFormat", "").split(",") if l.strip())
    model, lenses = read_aircraft(config, names)
    transitional_speed, takeoff_mode, finish_action, exit_on_rc_lost = read_mission_actions(config)

    points, route = [], {}
    gimbal_pitch = pitch_in_effect = None
    for n, placemark in enumerate(placemarks, start=1):
        coordinates = placemark.find(wpml.k("Point") + "/" + wpml.k("coordinates"))
        try:
            lon, lat = (float(v) for v in coordinates.text.split(",")[:2])
        except (AttributeError, ValueError):
            raise KmzImportError("Point %d is not a latitude and longitude" % n)
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -85 <= lat <= 85):
            raise KmzImportError("Point %d is not a latitude and longitude" % n)
        if not is_on(placemark, "useGlobalSpeed") and abs(number(placemark, "waypointSpeed", speed) - speed) > 0.001:
            raise KmzImportError("Point %d has a speed of its own: the planner flies the whole route at one speed" % n)
        if (not is_on(placemark, "useGlobalHeadingParam")
                and text(find(placemark, "waypointHeadingParam"), "waypointHeadingMode", heading_mode) != heading_mode):
            raise KmzImportError("Point %d has a heading mode of its own: the planner has one for the whole route" % n)
        if (not is_on(placemark, "useGlobalTurnParam")
                and text(find(placemark, "waypointTurnParam"), "waypointTurnMode") != waypoints.TURN_MODES[turn_mode]):
            raise KmzImportError("Point %d has a turn mode of its own: the planner has one for the whole route" % n)
        if heading_mode == "towardPOI" and read_poi(find(placemark, "waypointHeadingParam"), n) != poi:
            raise KmzImportError("Point %d faces a POI of its own: the planner has one for the whole route" % n)

        heading, pitch, photo, hover = read_point_actions(placemark, n, len(placemarks), route)
        if pitch is None and pitch_mode == "usePointSetting":
            # Pilot 2 writes 0 for the points whose pitch was not set
            pitch = number(placemark, "gimbalPitchAngle", 0.0) or None
        # The gimbal keeps its pitch from one point to the next: only the changes are kept
        if n == 1:
            gimbal_pitch = pitch_in_effect = pitch
            pitch = None
        elif pitch is not None and pitch == pitch_in_effect:
            pitch = None
        elif pitch is not None:
            pitch_in_effect = pitch

        points.append({
            "lat": round(lat, 9), "lon": round(lon, 9),
            "height": None if is_on(placemark, "useGlobalHeight") else number(placemark, "height"),
            "heading": heading, "pitch": pitch, "photo": photo, "hover": hover, "ground": None,
        })

    takeoff, takeoff_altitude, ellipsoidal = None, None, None
    ref = read_takeoff_point(config)
    if ref is not None:
        lat, lon, ellipsoidal = ref                 # takeOffRefPoint's height is ellipsoidal (DJI's WPML reference)
        takeoff = [lat, lon]
        if height_mode == "asl":
            # Pilot 2 flies each height above sea level plus the same offset, the undulation (waypoints.asl_offset)
            first = placemarks[0]
            takeoff_altitude = ellipsoidal - (number(first, "ellipsoidHeight") - number(first, "height", height))
        else:
            takeoff_altitude = sea_level(lat, lon, ellipsoidal)
        if takeoff_altitude is not None and not -500 <= takeoff_altitude <= 9000:
            raise KmzImportError("The ground height at the takeoff point (%g m) must be between -500 and 9000 m" % takeoff_altitude)
    elif height_mode == "asl":
        raise KmzImportError("The mission's heights are above sea level but it has no takeoff point")

    if route.get("startRecord") != route.get("stopRecord"):
        raise KmzImportError("The video %s: the planner records it from the first point to the last" % (
            "never stops" if route.get("startRecord") else "stops without starting"))
    video = bool(route.get("startRecord"))
    interval_mode, interval = route.get("photo_interval_mode"), route.get("photo_interval")

    name = route_title(name)
    avoid_limit_area = is_on(config, "waylineAvoidLimitAreaMode")
    cameras = [c for c in ("visable", "ir") if c in lenses]
    body = {
        "route_type": "waypoint", "model": model, "name": name, "cameras": cameras, "points": points,
        "height": height, "height_mode": height_mode, "speed": speed, "gimbal_pitch": gimbal_pitch,
        "heading_mode": heading_mode, "turn_mode": turn_mode, "takeoff_mode": takeoff_mode,
        "finish_action": finish_action, "exit_on_rc_lost": exit_on_rc_lost,
        "takeoff_security_height": number(config, "takeOffSecurityHeight"),
        "rth_height": number(config, "globalRTHHeight", 100.0),
        "takeoff_ref_point": None if takeoff is None or takeoff_altitude is None else [takeoff[0], takeoff[1], takeoff_altitude],
        "transitional_speed": transitional_speed, "avoid_limit_area": avoid_limit_area,
        "poi": None if poi is None else list(poi), "video": video, "photo_interval_mode": interval_mode,
        "photo_interval": interval,
    }
    if height_mode == "asl":
        body["takeoff_ellipsoidal_height"] = ellipsoidal
    try:
        waypoints.settings(**{key: value for key, value in body.items() if key not in ("route_type", "name")}
                           | {"cameras": [CAMERAS_BY_MODEL[model][c] for c in cameras]})
    except wpml.ExportError as e:
        raise KmzImportError(str(e))

    settings = {
        "name": name, "lens_visible": "true" if "visable" in lenses else "false", "lens_ir": "true" if "ir" in lenses else "false",
        "height": form_number(height), "height_mode": height_mode, "speed": form_number(speed),
        "gimbal_pitch": blank(gimbal_pitch), "heading_mode": heading_mode, "turn_mode": turn_mode,
        "takeoff_mode": takeoff_mode, "takeoff_security_height": form_number(body["takeoff_security_height"]),
        "rth_height": form_number(body["rth_height"]), "transitional_speed": form_number(transitional_speed),
        "finish_action": finish_action, "exit_on_rc_lost": exit_on_rc_lost,
        "avoid_limit_area": "true" if avoid_limit_area else "false",
        "takeoff_altitude": altitude_text(takeoff_altitude), "takeoff_ellipsoidal_height": altitude_text(ellipsoidal),
        "takeoff": takeoff, "points": points, "poi": body["poi"], "video": "true" if video else "false",
        "photo_interval_mode": interval_mode or "", "photo_interval": blank(interval),
    }
    return model, settings, body


def read_poi(heading_param, n=None):
    """(lat, lon) of the POI a waypointHeadingParam faces"""
    try:
        lat, lon = (float(v) for v in text(heading_param, "waypointPoiPoint").split(",")[:2])
    except (AttributeError, ValueError):
        lat = lon = float("nan")
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise KmzImportError("The POI %sis not a latitude and longitude" % ("of point %d " % n if n else ""))
    return lat, lon


def route_name(filename):
    """The route name for an uploaded file: its name without the folder or .kmz (or .kml)"""
    base = os.path.basename((filename or "").replace("\\", "/"))
    stem, ext = os.path.splitext(base)
    return (stem if ext.lower() in (".kmz", ".kml") else base)[:MAX_NAME]


def read_kmz_dsm(data, template=None):
    """
    The elevation model (DSM) an area or linear mission of a Pilot 2 .kmz file follows the terrain from, to keep as
    the route's terrain.

    :param data: the bytes of the file
    :param template: read_template(data), when the caller has it already
    :return: (tif, info) as terrain.fetch_terrain gives them, the dataset taken from the file's name (Pilot 2 names
        it wgs84_<dataset>_<tile>_dem_<n>.tif) and no undulation (Pilot 2's DSM is above the ellipsoid already), or
        None when the mission follows no DSM
    :raises KmzImportError: why the DSM cannot be used
    """
    root, names = template or read_template(data)
    document = root.find(wpml.k("Document"))
    folder = None if document is None else document.find(wpml.k("Folder"))
    path = dsm_file(folder, names) if folder is not None else None
    if path is None:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.getinfo(path).file_size > MAX_DSM_SIZE:
                raise KmzImportError("The elevation model (DSM) in the file is too large")
            tif = read_entry(z, path)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError):
        raise KmzImportError("This is not a .kmz file (not a zip archive)")
    try:
        with MemoryFile(tif) as f, f.open() as src:
            if src.crs is None or src.crs.to_epsg() != 4326:
                raise KmzImportError("The elevation model (DSM) in the file is not in WGS84 longitude and latitude")
            b = src.bounds
    except (rasterio.errors.RasterioError, rasterio.errors.RasterioIOError):
        raise KmzImportError("The elevation model (DSM) in the file cannot be read")
    file_name = os.path.basename(path)
    dataset = re.match(r"wgs84_([A-Za-z0-9]+)_", file_name)
    return tif, {"dataset": dataset.group(1) if dataset else "unknown", "undulation": None,
                 "bounds": [round(v, 7) for v in (b.left, b.bottom, b.right, b.top)], "name": file_name, "imported": True}
