"""
Export of a survey plan as a DJI WPML mission (.kmz) for an aircraft of drones.json, in the format DJI Pilot 2 imports.

A .kmz is a zip with two files: wpmz/template.kml (the mission as the user set it: area, direction, overlaps...) and
wpmz/waylines.wpml (what the aircraft flies: the waypoints and what to do at them). The structure, the element
order and the rules for the values below were taken from mission files exported by Pilot 2 for a Matrice 4T (an
area mission with terrain following, and one with heights relative to the takeoff point).

Only what has been checked against such files is exported. In particular the aircraft and payload numbers are those
Pilot 2 wrote for each model (AIRCRAFT, from drones.json), and only camera choices that Pilot 2 was seen to write are accepted: a mission
with a number that the aircraft does not know is rejected by it, or worse.
"""
import io
import logging
import math
import time
import zipfile
from collections import namedtuple
from xml.etree import ElementTree as ET

from pyproj import Geod

from . import geoid, terrain
from .cameras import CAMERAS_BY_MODEL
from .drones import DRONES
from .planning import plan_oblique_survey, plan_survey

logger = logging.getLogger('app.logger')

KML_NS = "http://www.opengis.net/kml/2.2"
WPML_NS = "http://www.dji.com/wpmz/1.0.6"

# What Pilot 2 writes for each aircraft model: droneEnumValue / droneSubEnumValue, payloadEnumValue, and
# payloadSubEnumValue by the cameras of the mission (drones.json has them, with where each number comes from).
AIRCRAFT = DRONES

HEIGHT_MODES = ("realTimeFollowSurface", "relativeToStartPoint", "EGM96")
# "oblique" flies 4 extra passes (see cameras.oblique_footprint and OBLIQUE_HEADINGS below) with the gimbal tilted.
# Its AGL (realTimeFollowSurface) is not the real-time follow but heights over a DSM embedded in the mission, as
# Pilot 2 exports it (m4t-testkmz-oblique-AGL.kmz; see uses_dsm and Dsm). relativeToStartPoint (ALT) and EGM96 (ASL)
# work for oblique too - checked directly against a real Pilot 2 oblique+ASL export (testkmz-oblique-asl.kmz).
COLLECTION_MODES = ("ortho", "oblique")
# How an ortho mission follows the ground in AGL: the aircraft's real-time follow, or heights over an embedded DSM, as
# Pilot 2's TestAreaKMZ-*.kmz have them. Oblique AGL is always flown over a DSM.
SURFACE_FOLLOWS = ("realtime", "dsm")
OBLIQUE_HEADINGS = (0.0, 90.0, 180.0, 270.0)
FINISH_ACTIONS = ("goHome", "noAction", "autoLand", "gotoFirstWaypoint")
RC_LOST = ("goContinue", "executeLostAction")

# How the aircraft gets to the first waypoint: up to the takeoff security height first (FlightHub: "Safe Takeoff"), or
# straight there ("Direct Ascent"). The values are those of DJI's WPML reference; Pilot 2's files were seen with "safely".
TAKEOFF_MODES = {"safe": "safely", "direct": "pointToPoint"}

# Photos every so many meters. Photos every so many seconds (WPML: multipleTiming) has been seen only in a waypoint
# route (m4t-test-poi-waypoint.kmz, written by waypoints.py), not in an area mission.
PHOTO_MODES = ("distance",)

MAX_SPEED = 15.0      # m/s, the mission's global transitional speed in Pilot 2's exports

GEOD = Geod(ellps="WGS84")

Settings = namedtuple("Settings", "polygon direction height cameras overlap_h overlap_w margin speed height_mode "
                                  "takeoff_security_height rth_height finish_action exit_on_rc_lost takeoff_ref_point "
                                  "takeoff_ellipsoidal_height transitional_speed author takeoff_mode elevation_optimize "
                                  "avoid_limit_area photo_mode route_start model "
                                  "collection_mode gimbal_pitch inclined_overlap_h inclined_overlap_w inclined_speed "
                                  "surface_follow")


def settings(polygon, direction, height, cameras, overlap_h, overlap_w, margin=0.0, speed=None,
             height_mode="realTimeFollowSurface", takeoff_security_height=20.0, rth_height=100.0,
             finish_action="goHome", exit_on_rc_lost="goContinue", takeoff_ref_point=None,
             takeoff_ellipsoidal_height=None, transitional_speed=15.0,
             author=None, takeoff_mode="safe", elevation_optimize=True, avoid_limit_area=False, photo_mode="distance",
             route_start=None, collection_mode="ortho", gimbal_pitch=None, inclined_overlap_h=None,
             inclined_overlap_w=None, inclined_speed=None, model="m4t", surface_follow=None):
    """
    The settings of the mission, checked.

    :param cameras: [Camera, ...] as used for the plan, all of them cameras of the model (cameras.CAMERAS_BY_MODEL)
    :param speed: m/s along the survey lines; None for the fastest speed the photos allow (Plan.max_speed)
    :param height_mode: realTimeFollowSurface: the aircraft keeps `height` above the ground it sees;
        relativeToStartPoint: `height` above the takeoff point (only right on level ground);
        EGM96: `height` above sea level - a flat target altitude for the whole mission (see takeoff_ellipsoidal_height)
    :param takeoff_ref_point: (lat, lon, altitude) of the takeoff point, if known. altitude is the ground height
        above sea level (the same value the "Ground height at the takeoff point" field collects) - required when
        height_mode is "EGM96", used as the base for the mission's target altitude
    :param takeoff_ellipsoidal_height: WGS84-ellipsoidal ground height at the takeoff point, meters; required when
        height_mode is "EGM96" (the aircraft flies a WGS84-ellipsoidal altitude, not the sea-level one directly -
        see missions/elevation.py, which fetches both this and takeoff_ref_point's altitude together)
    :param takeoff_mode: "safe" (up to the takeoff security height first) or "direct" (straight to the first waypoint)
    :param elevation_optimize: Pilot 2's "Elevation Optimization" (written to the template)
    :param avoid_limit_area: FlightHub's "Custom GEO Zone Obstacle Bypassing" (WPML waylineAvoidLimitAreaMode)
    :param photo_mode: "distance": a photo every so many meters ("time" is not supported yet)
    :param route_start: (lon, lat) where the route should begin: the waypoints start at the nearest end of a line. Pilot 2
        and FlightHub may plan the route again from the area when they open the mission, and then choose their own start.
    :param collection_mode: "ortho" (straight down) or "oblique" (also flies 4 tilted passes - see OBLIQUE_HEADINGS).
        Oblique AGL ("realTimeFollowSurface") is flown over an embedded DSM (see surface_follow).
    :param gimbal_pitch: degrees from straight down for the 4 oblique passes (required, -85 to -40, when collection_mode
        is "oblique"; checked properly - along with inclined_overlap_h/w and inclined_speed - in plan_oblique_survey,
        the same as height/overlap/speed are checked in plan_survey, not here)
    :param inclined_overlap_h: percent overlap along an oblique line; None (the default) mirrors overlap_h
    :param inclined_overlap_w: percent overlap between neighboring oblique lines; None (the default) mirrors overlap_w
    :param inclined_speed: m/s along the oblique passes; None (the default) is the fastest the oblique photos allow
        (the same as speed=None does for the nadir pass, independently - the two passes have different footprints)
    :param model: the aircraft, a key of AIRCRAFT
    :param surface_follow: in AGL, "realtime" (the aircraft follows the ground it sees) or "dsm" (heights over an
        embedded DSM: build_kmz needs the terrain). Oblique AGL is always "dsm"; other height modes ignore it.
        None: "realtime" where the model has it (drones.json realtime_follow), else "dsm".
    """
    check_choices(model, takeoff_mode, finish_action, exit_on_rc_lost)
    if photo_mode == "time":
        raise ExportError("Photos every so many seconds cannot be exported yet: none has been checked against a Pilot 2 or "
                          "FlightHub file. Use photos every so many meters")
    if not known(photo_mode, PHOTO_MODES):
        raise ExportError("Unknown photo mode %r" % (photo_mode,))
    for name, value in (("elevation optimization", elevation_optimize), ("geo zone bypassing", avoid_limit_area)):
        if not isinstance(value, bool):
            raise ExportError("The %s must be on or off" % name)
    if not known(height_mode, HEIGHT_MODES):
        raise ExportError("Unknown height mode %r" % (height_mode,))
    if height_mode == "EGM96":
        if takeoff_ref_point is None:
            raise ExportError("The ASL height mode needs the ground height at the takeoff point")
        if not (isinstance(takeoff_ellipsoidal_height, (int, float)) and math.isfinite(takeoff_ellipsoidal_height)):
            raise ExportError("The ASL height mode needs the ellipsoidal ground height at the takeoff point")
    elif takeoff_ellipsoidal_height is not None:
        raise ExportError("The ellipsoidal ground height only applies when height_mode is \"EGM96\"")
    check_flight(takeoff_security_height, rth_height, speed, transitional_speed, takeoff_ref_point)
    if route_start is not None and (len(route_start) != 2 or not all(is_number(v) for v in route_start)):
        raise ExportError("The route start is (longitude, latitude)")

    check_cameras(model, cameras)

    surface_follow = surface_follow_of(model, surface_follow)
    if not known(collection_mode, COLLECTION_MODES):
        raise ExportError("Unknown photo collection mode %r" % (collection_mode,))
    if height_mode == "realTimeFollowSurface" and collection_mode != "oblique":
        check_realtime_follow(model, surface_follow)
    if collection_mode == "oblique":
        if gimbal_pitch is None or not (isinstance(gimbal_pitch, (int, float)) and math.isfinite(gimbal_pitch)):
            raise ExportError("The gimbal tilt angle must be a number of degrees")
        if inclined_speed is not None and not (isinstance(inclined_speed, (int, float)) and math.isfinite(inclined_speed) and 0 < inclined_speed <= MAX_SPEED):
            raise ExportError("The oblique speed must be more than 0 and at most %g m/s" % MAX_SPEED)
    elif gimbal_pitch is not None or inclined_overlap_h is not None or inclined_overlap_w is not None or inclined_speed is not None:
        raise ExportError("The oblique settings only apply when collection_mode is \"oblique\"")

    return Settings(polygon=list(polygon), direction=float(direction), height=float(height), cameras=list(cameras),
                    overlap_h=float(overlap_h), overlap_w=float(overlap_w), margin=float(margin), speed=speed,
                    height_mode=height_mode, takeoff_security_height=float(takeoff_security_height),
                    rth_height=float(rth_height), finish_action=finish_action, exit_on_rc_lost=exit_on_rc_lost,
                    takeoff_ref_point=takeoff_ref_point,
                    takeoff_ellipsoidal_height=None if takeoff_ellipsoidal_height is None else float(takeoff_ellipsoidal_height),
                    transitional_speed=float(transitional_speed), author=author,
                    takeoff_mode=takeoff_mode, elevation_optimize=elevation_optimize, avoid_limit_area=avoid_limit_area,
                    photo_mode=photo_mode, route_start=None if route_start is None else tuple(float(v) for v in route_start),
                    collection_mode=collection_mode, gimbal_pitch=None if gimbal_pitch is None else float(gimbal_pitch),
                    inclined_overlap_h=float(overlap_h if inclined_overlap_h is None else inclined_overlap_h) if collection_mode == "oblique" else None,
                    inclined_overlap_w=float(overlap_w if inclined_overlap_w is None else inclined_overlap_w) if collection_mode == "oblique" else None,
                    inclined_speed=None if inclined_speed is None else float(inclined_speed), model=model,
                    surface_follow=surface_follow)


class ExportError(ValueError):
    pass


def surface_follow_of(model, surface_follow):
    """The surface follow asked for, or the model's default when None (see settings)"""
    if surface_follow is None:
        return "realtime" if AIRCRAFT[model].realtime_follow else "dsm"
    if not known(surface_follow, SURFACE_FOLLOWS):
        raise ExportError("Unknown surface follow %r" % (surface_follow,))
    return surface_follow


def check_realtime_follow(model, surface_follow):
    """An AGL route's real-time follow only for a model whose documents say it has it (drones.json realtime_follow)"""
    if surface_follow == "realtime" and not AIRCRAFT[model].realtime_follow:
        raise ExportError("The %s cannot follow the ground in real time (DJI documents it only for some aircraft): "
                          "choose the terrain model" % AIRCRAFT[model].name)


def uses_dsm(s):
    """Whether the mission flies heights over an embedded DSM (oblique AGL, or ortho AGL with the DSM follow), not
    the aircraft's real-time follow"""
    return s.height_mode == "realTimeFollowSurface" and (s.collection_mode == "oblique" or s.surface_follow == "dsm")


# The embedded DSM and the heights taken from it (see dsm_of): path in the kmz (wpmz/res/dsm/<name>), the GeoTIFF's
# bytes, the executeHeight of every waypoint by pass (nadir first), the startPositionRef (lat, lon, height) and the
# takeoff point's (lat, lon, ground), or None without a takeoff point.
Dsm = namedtuple("Dsm", "path content heights start takeoff")


MissionPlan = namedtuple("MissionPlan", "nadir oblique")
# nadir: the Plan flown straight down (always present - it is the whole mission for collection_mode "ortho").
# oblique: None for "ortho"; for "oblique", the 4 extra Plans flown tilted, one per OBLIQUE_HEADINGS entry, in order.


def plan_from_settings(s):
    """The flight lines for the settings: the plan(s) and the file always come from the same numbers"""
    nadir = plan_survey(s.polygon, s.direction, s.height, s.cameras, overlap_h=s.overlap_h, overlap_w=s.overlap_w,
                        margin=s.margin, route_start=s.route_start)
    if s.collection_mode != "oblique":
        return MissionPlan(nadir=nadir, oblique=None)

    oblique = [plan_oblique_survey(s.polygon, (s.direction + heading) % 360.0, s.height, s.cameras, s.gimbal_pitch,
                                   overlap_h=s.inclined_overlap_h, overlap_w=s.inclined_overlap_w, margin=s.margin,
                                   route_start=s.route_start)
              for heading in OBLIQUE_HEADINGS]
    return MissionPlan(nadir=nadir, oblique=oblique)


# -- XML ---------------------------------------------------------------------------------------------------------

def q(tag):
    """wpml:tag"""
    return "{%s}%s" % (WPML_NS, tag)


def k(tag):
    return "{%s}%s" % (KML_NS, tag)


def num(v):
    """A number as Pilot 2 writes them: as many digits as it takes, no exponent"""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    text = repr(float(v))
    if "e" in text or "E" in text:
        text = ("%.15f" % v).rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def coordinate(v):
    return ("%.13f" % v).rstrip("0").rstrip(".")


def add(parent, tag, value=None, ns=q):
    """Adds <wpml:tag>value</wpml:tag> (or an empty element) under parent and returns it"""
    element = ET.SubElement(parent, ns(tag))
    if value is not None:
        element.text = num(value) if isinstance(value, (int, float)) else str(value)
    return element


def to_xml(root):
    ET.register_namespace("", KML_NS)
    ET.register_namespace("wpml", WPML_NS)
    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8") + b"\n"


def kml_root():
    root = ET.Element(k("kml"))
    return root, ET.SubElement(root, k("Document"))


def takeoff_ref_point(s, dsm=None, ellipsoidal=False):
    """
    (lat, lon, height) of wpml:takeOffRefPoint, whose height Pilot 2 reads as WGS84-ellipsoidal (DJI's WPML reference,
    and every Pilot 2 export: 33-39 m below the sea-level ground where the samples were flown): the DSM's ground over a DSM; else the
    route's own (ellipsoidal=True: slope and geometric routes keep it ellipsoidal); else, above sea level (ASL), the
    ellipsoidal ground height the mission's heights are made with (fetched with the sea-level one, or Pilot 2's own);
    else its sea-level ground converted (missions/geoid.py). None when there is none, or when the conversion cannot
    be had: the point is not required (the aircraft takes its actual takeoff point), so the mission goes out without
    it.
    """
    if s.takeoff_ref_point is None:
        return None
    if dsm:
        return tuple(dsm.takeoff)
    lat, lon, height = s.takeoff_ref_point
    if ellipsoidal:
        return (lat, lon, height)
    if getattr(s, "takeoff_ellipsoidal_height", None) is not None:
        return (lat, lon, s.takeoff_ellipsoidal_height)
    try:
        return (lat, lon, geoid.to_ellipsoidal(lat, lon, height))
    except geoid.GeoidError as e:
        logger.warning("DJI Mission Planner: the takeoff point was left out of the mission: %s", e)
        return None


def mission_config(document, s, template, reroute=True, dsm=None, start=None, ellipsoidal_ref=False):
    """The <wpml:missionConfig> shared by both files (the template adds the takeoff point (takeoff_ref_point), and over
    a DSM, or for a slope route, the start of the route: `start`, (lat, lon, height)). Pilot 2 leaves out the
    rerouting for a linear or slope route (m4t-test-linear-*.kmz, m4t-test-slope.kmz): reroute=False."""
    config = add(document, "missionConfig")
    add(config, "flyToWaylineMode", TAKEOFF_MODES[s.takeoff_mode])
    add(config, "finishAction", s.finish_action)
    add(config, "exitOnRCLost", s.exit_on_rc_lost)
    add(config, "executeRCLostAction", "goBack")
    add(config, "takeOffSecurityHeight", s.takeoff_security_height)
    ref = takeoff_ref_point(s, dsm, ellipsoidal_ref) if template else None
    if ref is not None:
        add(config, "takeOffRefPoint", "%.6f,%.6f,%.6f" % ref)
    if template and (start or (dsm and dsm.start)):
        add(config, "startPositionRef", "%.6f,%.6f,%.6f" % (start or dsm.start))
    if ref is not None:
        add(config, "takeOffRefPointAGLHeight", 0)
    add(config, "globalTransitionalSpeed", s.transitional_speed)
    add(config, "globalRTHHeight", s.rth_height)
    drone = add(config, "droneInfo")
    aircraft = AIRCRAFT[s.model]
    add(drone, "droneEnumValue", aircraft.drone[0])
    add(drone, "droneSubEnumValue", aircraft.drone[1])
    if reroute:
        info = add(config, "autoRerouteInfo")
        add(info, "transitionalAutoRerouteMode", 1)
        add(info, "missionAutoRerouteMode", 1)
    add(config, "waylineAvoidLimitAreaMode", 1 if s.avoid_limit_area else 0)
    payload = add(config, "payloadInfo")
    add(payload, "payloadEnumValue", aircraft.payload)
    add(payload, "payloadSubEnumValue", aircraft.payload_sub[frozenset(c.key for c in s.cameras)])
    add(payload, "payloadPositionIndex", 0)


def lens_index(s):
    """The cameras by the names the mission file uses (drones.json: a camera's lens, else its key)"""
    return ",".join(c.lens or c.key for c in s.cameras)


def asl_heights(s):
    """(height, ellipsoidHeight) for EGM96 mode: the mission's flat target altitude above sea level, and its
    WGS84-ellipsoidal equivalent (what the aircraft actually flies - see wayline_folder). Matches Pilot 2's own
    ASL exports: one target altitude for the whole mission, not per-waypoint terrain following."""
    return s.takeoff_ref_point[2] + s.height, s.takeoff_ellipsoidal_height + s.height


def template_kml(plan, s, now_ms, dsm=None):
    root, document = kml_root()
    if s.author:
        add(document, "author", s.author)
    add(document, "createTime", now_ms)
    add(document, "updateTime", now_ms)
    mission_config(document, s, template=True, dsm=dsm)

    oblique = s.collection_mode == "oblique"

    folder = ET.SubElement(document, k("Folder"))
    add(folder, "templateType", "mapping3d" if oblique else "mapping2d")
    add(folder, "templateId", 0)
    system = add(folder, "waylineCoordinateSysParam")
    add(system, "coordinateMode", "WGS84")
    # Over a DSM Pilot 2 writes the EGM96 height mode, with the follow not real-time and the DSM's path
    add(system, "heightMode", "EGM96" if dsm else s.height_mode)
    add(system, "globalShootHeight", s.height)
    if dsm:
        add(system, "surfaceFollowModeEnable", 1)
        add(system, "isRealtimeSurfaceFollow", 0)
        add(system, "surfaceRelativeHeight", s.height)
        add(system, "dsmFile", dsm.path)
    elif s.height_mode == "realTimeFollowSurface":
        add(system, "surfaceFollowModeEnable", 1)
        add(system, "isRealtimeSurfaceFollow", 1)
        add(system, "surfaceRelativeHeight", s.height)
    add(folder, "autoFlightSpeed", speed_of(plan, s))

    placemark = ET.SubElement(folder, k("Placemark"))
    add(placemark, "caliFlightEnable", 0)
    if oblique:
        add(placemark, "inclinedGimbalPitch", s.gimbal_pitch)
    else:
        for tag, value in (("elevationOptimizeEnable", 1 if s.elevation_optimize else 0), ("smartObliqueEnable", 0),
                           ("quickOrthoMappingEnable", 0), ("facadeWaylineEnable", 0), ("isLookAtSceneSet", 0)):
            add(placemark, tag, value)
    for tag, value in (("shootType", "distance"), ("direction", s.direction), ("margin", s.margin)):
        add(placemark, tag, value)
    if oblique:
        add(placemark, "inclinedFlightSpeed", inclined_speed_of(plan, s))
    add(placemark, "efficiencyFlightModeEnable", 0)
    if not oblique:
        add(placemark, "doubleGridWaylineEnable", 0)
    overlap = add(placemark, "overlap")
    for tag, value in (("orthoCameraOverlapH", s.overlap_h), ("orthoCameraOverlapW", s.overlap_w),
                       ("inclinedCameraOverlapH", s.inclined_overlap_h if oblique else s.overlap_h),
                       ("inclinedCameraOverlapW", s.inclined_overlap_w if oblique else s.overlap_w)):
        add(overlap, tag, value)
    polygon = ET.SubElement(placemark, k("Polygon"))
    ring = ET.SubElement(ET.SubElement(polygon, k("outerBoundaryIs")), k("LinearRing"))
    corners = list(s.polygon) + [s.polygon[0]]
    ET.SubElement(ring, k("coordinates")).text = "\n" + "\n".join(
        "                %s,%s,0" % (coordinate(lon), coordinate(lat)) for lon, lat, *_ in corners) + "\n              "
    height, ellipsoid_height = asl_heights(s) if s.height_mode == "EGM96" else (s.height, s.height)
    add(placemark, "ellipsoidHeight", ellipsoid_height)
    add(placemark, "height", height)

    param = add(folder, "payloadParam")
    add(param, "payloadPositionIndex", 0)
    add(param, "focusMode", "firstPoint")
    add(param, "meteringMode", "average")
    add(param, "returnMode", "singleReturnStrongest")
    add(param, "samplingRate", 240000)
    add(param, "scanningMode", "repetitive")
    add(param, "imageFormat", lens_index(s))
    add(param, "photoSize", "default_l")
    return to_xml(root)


def known(value, choices):
    """Whether value is one of the choices' names: text only, as a request's JSON may hold a list or an object
    where a name is expected (and a list cannot be looked up in a dict)"""
    return isinstance(value, str) and value in choices


def is_number(v):
    """A finite number: not a bool, though Python counts one as an int"""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check_choices(model, takeoff_mode, finish_action, exit_on_rc_lost):
    """What every route type's settings choose alike: the aircraft, its takeoff, what it does at the end and when the
    remote's signal is lost"""
    for value, choices, what in ((model, AIRCRAFT, "aircraft model"), (takeoff_mode, TAKEOFF_MODES, "takeoff mode"),
                                 (finish_action, FINISH_ACTIONS, "finish action")):
        if not known(value, choices):
            raise ExportError("Unknown %s %r" % (what, value))
    if not known(exit_on_rc_lost, RC_LOST):
        raise ExportError("Unknown behaviour when remote signal is lost: %r" % (exit_on_rc_lost,))


def check_flight(takeoff_security_height, rth_height, speed, transitional_speed, takeoff_ref_point, transit="survey",
                 need_speed=False):
    """The heights, speeds and takeoff point every route type's settings share; speed None (the fastest the photos
    allow) unless need_speed"""
    for name, value in (("takeoff security height", takeoff_security_height), ("return height", rth_height)):
        if not (is_number(value) and 2 <= value <= 1500):
            raise ExportError("The %s must be between 2 and 1500 meters" % name)
    if (speed is not None or need_speed) and not (is_number(speed) and 0 < speed <= MAX_SPEED):
        raise ExportError("The speed must be more than 0 and at most %g m/s" % MAX_SPEED)
    if not (is_number(transitional_speed) and 0 < transitional_speed <= MAX_SPEED):
        raise ExportError("The speed between the takeoff and the %s must be more than 0 and at most %g m/s" % (transit, MAX_SPEED))
    if takeoff_ref_point is not None and (len(takeoff_ref_point) != 3 or not all(is_number(v) for v in takeoff_ref_point)):
        raise ExportError("The takeoff point is (latitude, longitude, altitude)")


def check_cameras(model, cameras, optional=False):
    """The cameras are the model's, in a combination Pilot 2's files were checked with; none at all passes when
    optional (the route's own check then asks for one)"""
    if any(CAMERAS_BY_MODEL[model].get(c.key) != c for c in cameras):
        raise ExportError("The cameras %s are not those of the %s" % (", ".join(sorted(c.label for c in cameras)), AIRCRAFT[model].name))
    if (cameras or not optional) and frozenset(c.key for c in cameras) not in AIRCRAFT[model].payload_sub:
        raise ExportError("The cameras %s cannot be exported yet: only the wide camera, or the thermal and wide cameras "
                          "together, have been checked against Pilot 2" % ", ".join(sorted(c.label for c in cameras)))


def auto_speed(max_speed):
    """The speed when none is asked: the fastest the photos allow, in steps of 0.1 m/s, at most MAX_SPEED. Below
    0.1 m/s (a low height with a high overlap) the allowed speed itself, never 0."""
    stepped = math.floor(max_speed * 10) / 10.0
    return min(MAX_SPEED, stepped if stepped > 0 else max_speed)


def route_speed(p, s):
    """The speed of a route type whose plan has one max_speed (linear, slope, geometric): the requested one, or the
    fastest that leaves the photos enough time"""
    if s.speed is not None:
        return float(s.speed)
    return auto_speed(p.max_speed)


def speed_of(plan, s):
    """The speed along the nadir survey lines: the requested one, or the fastest that leaves the photos enough time"""
    return route_speed(plan.nadir, s)


def inclined_speed_of(plan, s):
    """The speed along the 4 oblique passes: the requested one, or the fastest that leaves the photos enough time
    (the 4 passes share the same footprint/interval, so any one of them gives the same answer)"""
    if s.inclined_speed is not None:
        return float(s.inclined_speed)
    return auto_speed(plan.oblique[0].max_speed)


def gimbal_rotate(parent, action_id, pitch=-90):
    """The gimbal is set to `pitch` degrees from straight down (-90), in the direction of the aircraft. Nadir
    passes and oblique passes both use this, the only difference is the pitch."""
    action = add(parent, "action")
    add(action, "actionId", action_id)
    add(action, "actionActuatorFunc", "gimbalRotate")
    param = add(action, "actionActuatorFuncParam")
    for tag, value in (("gimbalHeadingYawBase", "aircraft"), ("gimbalRotateMode", "absoluteAngle"),
                       ("gimbalPitchRotateEnable", 1), ("gimbalPitchRotateAngle", pitch), ("gimbalRollRotateEnable", 0),
                       ("gimbalRollRotateAngle", 0), ("gimbalYawRotateEnable", 1), ("gimbalYawRotateAngle", 0),
                       ("gimbalRotateTimeEnable", 0), ("gimbalRotateTime", 10), ("payloadPositionIndex", 0)):
        add(param, tag, value)


def simple_action(parent, action_id, func, **params):
    action = add(parent, "action")
    add(action, "actionId", action_id)
    add(action, "actionActuatorFunc", func)
    if params:      # some actions (gimbalAngleUnlock) have none
        param = add(action, "actionActuatorFuncParam")
        for tag, value in params.items():
            add(param, tag, value)


def start_action_group(folder, pitch=-90):
    """What the aircraft does before the survey: set the gimbal, hover, focus at infinity (as Pilot 2 does)"""
    group = add(folder, "startActionGroup")
    gimbal_rotate(group, 0, pitch)
    simple_action(group, 1, "hover", hoverTime=0.5)
    simple_action(group, 2, "setFocusType", cameraFocusType="manual", payloadPositionIndex=0)
    simple_action(group, 3, "focus", focusX=0, focusY=0, focusRegionWidth=0, focusRegionHeight=0, isPointFocus=0,
                  isInfiniteFocus=1, payloadPositionIndex=0, isCalibrationFocus=0)
    simple_action(group, 4, "hover", hoverTime=1)


def action_group(placemark, group_id, first, last, trigger, trigger_param=None):
    group = add(placemark, "actionGroup")
    add(group, "actionGroupId", group_id)
    add(group, "actionGroupStartIndex", first)
    add(group, "actionGroupEndIndex", last)
    add(group, "actionGroupMode", "sequence")
    t = add(group, "actionTrigger")
    add(t, "actionTriggerType", trigger)
    if trigger_param is not None:
        add(t, "actionTriggerParam", trigger_param)
    return group


def signed_degrees(angle):
    """A bearing normalized to (-180, 180], the range GEOD.inv returns and Pilot 2's own files use"""
    return ((angle + 180.0) % 360.0) - 180.0


def wayline_folder(document, wayline_id, plan, speed, s, pitch, fixed_heading, heights=None):
    """
    One flown pass (one <Folder> of waylines.wpml): the nadir pass when fixed_heading is None (the heading of each
    waypoint follows the line it is on, as a single survey normally does), or one of the 4 oblique passes when it
    is a bearing in degrees (every waypoint but the last is locked to that one heading instead - see wayml.py's
    module docstring and OBLIQUE_HEADINGS: an oblique pass keeps the gimbal, and so the camera, aimed the same
    absolute direction for the whole pass, which the M4T achieves by translating sideways/backwards as needed
    rather than turning, unlike the nadir pass's ordinary back-and-forth flying).

    :param heights: the executeHeight of each waypoint, over a DSM (Dsm.heights); None for one height for all
    """
    folder = ET.SubElement(document, k("Folder"))
    add(folder, "templateId", wayline_id)
    # EGM96 (ASL) is flown as an absolute WGS84-ellipsoidal altitude, not a sea-level one - the aircraft's own
    # field name/value differ from the template's heightMode here (checked against testkmz-oblique-asl.kmz).
    # Over a DSM the heights are WGS84-ellipsoidal too, and the coordinates are said to be WGS84 (as in
    # m4t-testkmz-oblique-AGL.kmz)
    add(folder, "executeHeightMode", "WGS84" if s.height_mode == "EGM96" or heights else s.height_mode)
    if heights and s.collection_mode == "oblique":      # not in the ortho ones (TestAreaKMZ-*.kmz)
        add(folder, "executeCoordinateMode", "WGS84")
    add(folder, "waylineId", wayline_id)
    add(folder, "distance", plan.distance)
    add(folder, "duration", plan.distance / speed)
    add(folder, "autoFlightSpeed", speed)
    start_action_group(folder, pitch)
    add(folder, "realTimeFollowSurfaceByFov", 0)

    execute_height = asl_heights(s)[1] if s.height_mode == "EGM96" else s.height

    points = plan.waypoints
    last = len(points) - 1
    for i, (lon, lat) in enumerate(points):
        placemark = ET.SubElement(folder, k("Placemark"))
        ET.SubElement(ET.SubElement(placemark, k("Point")), k("coordinates")).text = \
            "\n            %s,%s\n          " % (coordinate(lon), coordinate(lat))
        add(placemark, "index", i)
        add(placemark, "executeHeight", heights[i] if heights else execute_height)
        add(placemark, "waypointSpeed", speed)

        h = add(placemark, "waypointHeadingParam")
        if i < last and fixed_heading is not None:
            add(h, "waypointHeadingMode", "fixed")
            add(h, "waypointHeadingAngle", round(signed_degrees(fixed_heading), 9))
        else:
            # The last waypoint always just stops; a nadir waypoint's heading follows the leg to the next one
            heading = GEOD.inv(lon, lat, points[i + 1][0], points[i + 1][1])[0] if i < last else 0.0
            add(h, "waypointHeadingMode", "followWayline")
            add(h, "waypointHeadingAngle", round(heading, 9))
        add(h, "waypointPoiPoint", "0.000000,0.000000,0.000000")
        add(h, "waypointHeadingAngleEnable", 1)
        add(h, "waypointHeadingPathMode", "followBadArc")
        add(h, "waypointHeadingPoiIndex", 0)

        # The ends stop; in between the aircraft rounds the corners, starting to turn a third of the distance
        # between the lines before them
        turn = add(placemark, "waypointTurnParam")
        stops = i in (0, last)
        add(turn, "waypointTurnMode", "toPointAndStopWithDiscontinuityCurvature" if stops else "coordinateTurn")
        add(turn, "waypointTurnDampingDist", 0 if stops else round(plan.spacing / 3.0, 9))
        add(placemark, "useStraightLine", 1)

        if i == 0:
            # One continuous run of photos over the whole pass: keep the gimbal angle, take a photo every
            # `interval` meters, and stop at the last waypoint
            group = action_group(placemark, 0, 0, last, "betweenAdjacentPoints")
            simple_action(group, 0, "gimbalAngleLock", payloadPositionIndex=0)
            group = action_group(placemark, 1, 0, last, "multipleDistance", plan.interval)
            gimbal_rotate(group, 0, pitch)
            simple_action(group, 1, "startContinuousShooting", payloadPositionIndex=0, useGlobalPayloadLensIndex=0,
                          payloadLensIndex=lens_index(s))
        if i == last:
            group = action_group(placemark, 2, last, last, "reachPoint")
            simple_action(group, 0, "stopContinuousShooting", payloadPositionIndex=0, payloadLensIndex=lens_index(s))
            simple_action(group, 1, "gimbalAngleUnlock")

        gimbal = add(placemark, "waypointGimbalHeadingParam")
        add(gimbal, "waypointGimbalPitchAngle", 0)
        add(gimbal, "waypointGimbalYawAngle", 0)
        add(placemark, "isRisky", 0)
        add(placemark, "waypointWorkType", 0)


def waylines_wpml(plan, s, dsm=None):
    root, document = kml_root()
    mission_config(document, s, template=False)

    wayline_folder(document, 0, plan.nadir, speed_of(plan, s), s, -90, None, dsm.heights[0] if dsm else None)
    if s.collection_mode == "oblique":
        inclined_speed = inclined_speed_of(plan, s)
        for i, heading in enumerate(OBLIQUE_HEADINGS, start=1):
            wayline_folder(document, i, plan.oblique[i - 1], inclined_speed, s, s.gimbal_pitch, s.direction + heading,
                           dsm.heights[i] if dsm else None)

    return to_xml(root)


def mission_warnings(plan, s):
    """Things to check before flying that the file itself cannot say"""
    warnings = list(plan.nadir.warnings)
    speed = speed_of(plan, s)
    if speed > plan.nadir.max_speed + 1e-9:
        warnings.append("The speed of %.1f m/s is more than the %.1f m/s that leaves 1.25 s between photos: some may be "
                        "missed" % (speed, plan.nadir.max_speed))
    if s.collection_mode == "oblique":
        for p in plan.oblique:
            for w in p.warnings:
                if w not in warnings:
                    warnings.append(w)
        inclined_speed = inclined_speed_of(plan, s)
        max_oblique_speed = min(p.max_speed for p in plan.oblique)
        if inclined_speed > max_oblique_speed + 1e-9:
            warnings.append("The oblique speed of %.1f m/s is more than the %.1f m/s that leaves 1.25 s between photos: "
                            "some may be missed" % (inclined_speed, max_oblique_speed))
    if uses_dsm(s):
        warnings.append(terrain_warning())
    if s.height_mode == "relativeToStartPoint":
        warnings.append("The height is measured from the takeoff point: the aircraft will not follow the terrain")
    elif s.height_mode == "EGM96":
        warnings.append("The height is measured above sea level, from public elevation data that can differ from "
                        "the real ground by a few meters: check the height before flying")
    if s.rth_height < s.height + 10:
        warnings.append("The return height (%g m) is not well above the flight height (%g m)" % (s.rth_height, s.height))
    return warnings


def terrain_warning():
    return ("The heights follow the route's terrain, the highest point within %g m of each waypoint: the lidar surface "
            "(trees and roofs, 10 m) where the terrain was made from lidar, else public elevation data (30 m) that can "
            "differ from the real surface and miss single trees, roofs and masts: check the height before flying"
            % terrain.RADIUS)


def terrain_points(plan, s):
    """The (lon, lat) points the terrain must cover for the mission: the waypoints of every pass and the takeoff point"""
    points = list(plan.nadir.waypoints) + [p for o in (plan.oblique or []) for p in o.waypoints]
    if s.takeoff_ref_point is not None:
        points.append((s.takeoff_ref_point[1], s.takeoff_ref_point[0]))
    return points


def dsm_of(plan, s, tif, name):
    """The Dsm of the mission: each waypoint flies `s.height` above the highest ground within terrain.RADIUS of it,
    the start of the route `s.height` above the ground under it (as Pilot 2's oblique file has them; its ortho ones
    have no start)"""
    try:
        heights = [[round(g + s.height, 3) for g in terrain.ground_heights(tif, p.waypoints)]
                   for p in [plan.nadir] + list(plan.oblique or [])]
        start = None
        if s.collection_mode == "oblique":
            lon, lat = plan.nadir.waypoints[0]
            start = (lat, lon, terrain.ground_at(tif, lon, lat) + s.height)
        takeoff = None
        if s.takeoff_ref_point is not None:
            lat, lon = s.takeoff_ref_point[:2]
            takeoff = (lat, lon, terrain.ground_at(tif, lon, lat))
    except terrain.TerrainError as e:
        raise ExportError(str(e))
    return Dsm(path="wpmz/res/dsm/" + name, content=tif, heights=heights, start=start, takeoff=takeoff)


def build_kmz(plan, s, now=None, dsm=None):
    """
    The mission as the bytes of a .kmz file.

    :param plan: a MissionPlan (see plan_from_settings) for the same area, direction, height, cameras and overlaps as `s`
    :param s: settings(...)
    :param now: time.time() at creation, for repeatable output (default: now)
    :param dsm: the (GeoTIFF bytes, name) of the terrain (missions.terrain), required when uses_dsm(s)
    """
    if len(plan.nadir.waypoints) < 2 or (s.collection_mode == "oblique" and any(len(p.waypoints) < 2 for p in plan.oblique)):
        raise ExportError("The plan has no flight lines")
    if uses_dsm(s) and dsm is None:
        raise ExportError("AGL over the terrain needs the terrain under the route")
    dsm = dsm_of(plan, s, *dsm) if uses_dsm(s) else None
    now_ms = int(round((time.time() if now is None else now) * 1000))

    files = [("wpmz/template.kml", template_kml(plan, s, now_ms, dsm)), ("wpmz/waylines.wpml", waylines_wpml(plan, s, dsm))]
    if dsm:
        files.append((dsm.path, dsm.content))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))     # same bytes for the same mission
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, content)
    return out.getvalue()
