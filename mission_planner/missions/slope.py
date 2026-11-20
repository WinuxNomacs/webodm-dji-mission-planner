"""
Export of a slope route (a steep face: an embankment, a dam, a quarry wall, mapped square-on) as a DJI WPML mission
(.kmz) for an aircraft of drones.json, in the format Pilot 2 imports (templateType mapping2d with facadeWaylineEnable 1).

The face is the outline drawn on the map, each corner with its height; a plane is fitted through the corners. The
aircraft flies horizontal lines across the face, `height` meters out from it, back and forth from the top down,
stepped along the face for the overlap between the lines; the gimbal is tilted square-on to the face and the heading
faces it. The structure, the element order and the rules for the values below were taken from a slope route exported
by Pilot 2 (tests/fixtures/dji-kmz/m4t-test-slope.kmz). What it shares with an area mission (missionConfig, the
payload, the start actions) comes from missions/wpml.py.

Heights: the corners' heights and the waypoints' executeHeight are WGS84-ellipsoidal, as Pilot 2's takeoff point is
(208.6 m in every sample, about 243 m above sea level less the 34 m of the geoid there). The template's `height` is
the distance from the face, and its ellipsoidHeight that distance plus the geoid undulation at the face, as Pilot 2
writes them.
"""
import io
import math
import time
import zipfile
from collections import namedtuple
from xml.etree import ElementTree as ET

import numpy as np
from pyproj import Transformer

from . import wpml
from .cameras import footprint
from .planning import MAX_HEIGHT, MAX_OVERLAP, MIN_HEIGHT, MIN_OVERLAP, MIN_SHOT_INTERVAL, PlanError
from .wpml import (ExportError, action_group, add, check_cameras, check_choices, check_flight,
                   coordinate, is_number, k, kml_root, lens_index, mission_config, simple_action, start_action_group, to_xml)

STOP = "toPointAndStopWithDiscontinuityCurvature"
MAX_CORNERS = 50
MIN_SLOPE = 1.0             # degrees: a flatter face is an area route
# Seconds Pilot 2 adds to a slope route's duration for each point it turns at (the sample: 145 s for 90 points)
TURN_TIME = 1.6
EGM96_GRID = "/usr/share/proj/egm96_15.gtx"

Settings = namedtuple("Settings", "corners height cameras overlap_h overlap_w speed takeoff_security_height rth_height "
                                  "finish_action exit_on_rc_lost takeoff_ref_point transitional_speed author "
                                  "takeoff_mode avoid_limit_area model")

Plan = namedtuple("Plan", "lines waypoints legs slope heading pitch spacing interval max_speed distance duration "
                          "photos profile")
# lines: the lines flown across the face, [[(lon, lat, h), (lon, lat, h)], ...], in the order flown
# waypoints: every point of the route, (lon, lat, h), h WGS84-ellipsoidal; legs: the 3D meters between them
# slope: degrees from level; heading: the bearing the aircraft faces (the face's downhill bearing turned round);
# pitch: the gimbal's, square-on to the face
# profile: the route seen from the side, across the face: {"face": its top and bottom, "lines": the middle of each line},
# each as [out, h], `out` the meters out from the face's top on the level (towards the aircraft), h WGS84-ellipsoidal


def settings(corners, cameras, height=30.0, overlap_h=80.0, overlap_w=80.0, speed=None, takeoff_security_height=20.0,
             rth_height=100.0, finish_action="goHome", exit_on_rc_lost="goContinue", takeoff_ref_point=None,
             transitional_speed=15.0, author=None, takeoff_mode="safe", avoid_limit_area=False, model="m4t"):
    """
    The settings of the route, checked.

    :param corners: the face's outline, [(lon, lat, h), ...], at least 3 corners, h WGS84-ellipsoidal meters
    :param cameras: [Camera, ...], all of them cameras of the model (cameras.CAMERAS_BY_MODEL)
    :param height: meters flown out from the face, square to it
    :param speed: m/s; None for the fastest speed the photos allow (Plan.max_speed)
    :param takeoff_ref_point: (lat, lon, altitude) of the takeoff point, as for an area (wpml.settings)
    """
    check_choices(model, takeoff_mode, finish_action, exit_on_rc_lost)
    if not isinstance(avoid_limit_area, bool):
        raise ExportError("The geo zone bypassing must be on or off")
    check_flight(takeoff_security_height, rth_height, speed, transitional_speed, takeoff_ref_point)
    check_cameras(model, cameras, optional=True)

    if not cameras:
        raise PlanError("Choose at least one camera")
    if not (3 <= len(corners) <= MAX_CORNERS) or any(len(c) != 3 or not all(is_number(v) for v in c) for c in corners):
        raise PlanError("The face needs between 3 and %d corners, each with its height" % MAX_CORNERS)
    if not (is_number(height) and MIN_HEIGHT <= height <= MAX_HEIGHT):
        raise PlanError("The distance from the face must be between %g and %g meters" % (MIN_HEIGHT, MAX_HEIGHT))
    for name, value in (("along", overlap_h), ("across", overlap_w)):
        if not (is_number(value) and MIN_OVERLAP <= value <= MAX_OVERLAP):
            raise PlanError("The overlap %s the lines must be between %g and %g%%" % (name, MIN_OVERLAP, MAX_OVERLAP))

    return Settings(corners=[tuple(float(v) for v in c) for c in corners], height=float(height), cameras=list(cameras),
                    overlap_h=float(overlap_h), overlap_w=float(overlap_w),
                    speed=None if speed is None else float(speed),
                    takeoff_security_height=float(takeoff_security_height), rth_height=float(rth_height),
                    finish_action=finish_action, exit_on_rc_lost=exit_on_rc_lost,
                    takeoff_ref_point=None if takeoff_ref_point is None else tuple(float(v) for v in takeoff_ref_point),
                    transitional_speed=float(transitional_speed), author=author, takeoff_mode=takeoff_mode,
                    avoid_limit_area=avoid_limit_area, model=model)


# -- The plan ----------------------------------------------------------------------------------------------------

def spacing_of(s):
    """Between the lines, along the face: the photos' height (they are taken landscape, square-on to the face)"""
    return min(footprint(c, s.height)[1] for c in s.cameras) * (1.0 - s.overlap_w / 100.0)


def interval_of(s):
    """Between the photos, along a line: the photos' width"""
    return min(footprint(c, s.height)[0] for c in s.cameras) * (1.0 - s.overlap_h / 100.0)


speed_of = wpml.route_speed


def leg_lengths(points):
    """3D, in meters, between points in the face's metric frame"""
    return [float(np.linalg.norm(b - a)) for a, b in zip(points, points[1:])]


def face(s):
    """
    The face's plane in a local metric frame: (to_lonlat, origin, n, u, v, corners), where the frame is an azimuthal
    equidistant projection on the corners' middle with the heights as z, origin the corners' mean in it, n the plane's
    normal (pointing up, out of the face), u level along the face, v up the face, and corners the corners in the
    frame, less the origin.
    """
    lon0 = sum(c[0] for c in s.corners) / len(s.corners)
    lat0 = sum(c[1] for c in s.corners) / len(s.corners)
    proj = "+proj=aeqd +lat_0=%r +lon_0=%r +ellps=WGS84" % (lat0, lon0)
    to_metric = Transformer.from_crs(4326, proj, always_xy=True)
    to_lonlat = Transformer.from_crs(proj, 4326, always_xy=True)
    points = np.array([(*to_metric.transform(lon, lat), h) for lon, lat, h in s.corners])
    origin = points.mean(axis=0)
    points = points - origin

    # z = a x + b y + c, through the corners
    # (the corners' spread across their line on the map, root mean square, under 10 cm: in a line)
    if np.linalg.svd(points[:, :2], compute_uv=False)[-1] / math.sqrt(len(points)) < 0.1:
        raise PlanError("The face's corners are in a line on the map")
    a_matrix = np.c_[points[:, 0], points[:, 1], np.ones(len(points))]
    a, b, _ = np.linalg.lstsq(a_matrix, points[:, 2], rcond=None)[0]
    if math.degrees(math.atan(math.hypot(a, b))) < MIN_SLOPE:
        raise PlanError("The face is level: map it with an area route")
    n = np.array([-a, -b, 1.0])
    n /= np.linalg.norm(n)
    u = np.cross([0.0, 0.0, 1.0], n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return to_lonlat, origin, n, u, v, points


def line_ends(outline, y):
    """Where the line at `y` (up the face) crosses the outline [(x, y), ...]: its lowest and highest x, or None"""
    xs = []
    for (x1, y1), (x2, y2) in zip(outline, outline[1:] + outline[:1]):
        if (y1 <= y < y2) or (y2 <= y < y1):
            xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    return (min(xs), max(xs)) if len(xs) >= 2 else None


def plan(s):
    """The lines and the waypoints of the route"""
    to_lonlat, origin, n, u, v, corners = face(s)
    outline = [(float(c @ u), float(c @ v)) for c in corners]
    top, bottom = max(y for _, y in outline), min(y for _, y in outline)
    spacing = spacing_of(s)
    count = max(1, int(math.floor((top - bottom) / spacing + 1e-9)))
    first = top - ((top - bottom) - (count - 1) * spacing) / 2.0

    # The first line starts at its end nearest the first corner; the next one back, and so on
    lines = []
    for i in range(count):
        y = first - i * spacing
        ends = line_ends(outline, y)
        if ends is None:
            continue
        if not lines:
            backwards = abs(ends[1] - outline[0][0]) < abs(ends[0] - outline[0][0])
        line = ends[::-1] if backwards != (len(lines) % 2 == 1) else ends
        lines.append([u * x + v * y + n * s.height for x in line])
    if not lines:
        raise PlanError("The face is too small for one line")

    points = [p for line in lines for p in line]

    def lonlat(p):
        q = p + origin
        return tuple(to_lonlat.transform(q[0], q[1])) + (float(q[2]),)

    lengths = leg_lengths(points)
    distance = sum(lengths)
    interval = interval_of(s)
    slope = math.degrees(math.acos(n[2]))
    level_out = np.array([n[0], n[1], 0.0]) / math.hypot(n[0], n[1])
    face_top, face_bottom = v * top, v * bottom
    side = lambda q: [round(float((q - face_top) @ level_out), 3), round(float(q[2] + origin[2]), 3)]
    profile = {"face": [side(face_top), side(face_bottom)], "lines": [side((a + b) / 2.0) for a, b in lines]}
    heading = wpml.signed_degrees(math.degrees(math.atan2(n[0], n[1])) + 180.0)
    p = Plan(lines=[[lonlat(q) for q in line] for line in lines], waypoints=[lonlat(q) for q in points], legs=lengths,
             slope=slope, heading=heading, pitch=int(slope - 90.0), spacing=spacing, interval=interval,
             max_speed=interval / MIN_SHOT_INTERVAL, distance=distance, duration=None,
             photos=int(distance // interval) + 1, profile=profile)
    return p._replace(duration=distance / speed_of(p, s) + TURN_TIME * max(0, len(points) - 2))


def geoid_undulation(lon, lat):
    """EGM96's height above the WGS84 ellipsoid, in meters, or None without the grid"""
    try:
        t = Transformer.from_pipeline("+proj=vgridshift +grids=%s +multiplier=1" % EGM96_GRID)
        n = t.transform(lon, lat, 0.0)[2]
    except Exception:  # noqa: BLE001 (no grid, or PROJ cannot use it: no undulation shown)
        return None
    return n if math.isfinite(n) else None


# -- XML ---------------------------------------------------------------------------------------------------------

def template_kml(p, s, now_ms):
    root, document = kml_root()
    if s.author:
        add(document, "author", s.author)
    add(document, "createTime", now_ms)
    add(document, "updateTime", now_ms)
    lon, lat, h = p.waypoints[0]
    mission_config(document, s, template=True, reroute=False, start=(lat, lon, h), ellipsoidal_ref=True)

    folder = ET.SubElement(document, k("Folder"))
    add(folder, "templateType", "mapping2d")
    add(folder, "templateId", 0)
    system = add(folder, "waylineCoordinateSysParam")
    add(system, "coordinateMode", "WGS84")
    add(system, "heightMode", "EGM96")
    add(system, "globalShootHeight", s.height)
    add(folder, "autoFlightSpeed", speed_of(p, s))

    placemark = ET.SubElement(folder, k("Placemark"))
    for tag, value in (("caliFlightEnable", 0), ("elevationOptimizeEnable", 0), ("smartObliqueEnable", 0),
                       ("quickOrthoMappingEnable", 0), ("facadeWaylineEnable", 1), ("isLookAtSceneSet", 0),
                       ("shootType", "distance"), ("direction", 0), ("margin", 0), ("efficiencyFlightModeEnable", 0),
                       ("doubleGridWaylineEnable", 0)):
        add(placemark, tag, value)
    overlap = add(placemark, "overlap")
    add(overlap, "orthoCameraOverlapH", s.overlap_h)
    add(overlap, "orthoCameraOverlapW", s.overlap_w)
    polygon = ET.SubElement(placemark, k("Polygon"))
    ring = ET.SubElement(ET.SubElement(polygon, k("outerBoundaryIs")), k("LinearRing"))
    ET.SubElement(ring, k("coordinates")).text = "\n" + "\n".join(
        "                %s,%s,%s" % (coordinate(lon), coordinate(lat), wpml.num(h)) for lon, lat, h in s.corners) + \
        "\n              "
    undulation = geoid_undulation(sum(c[0] for c in s.corners) / len(s.corners),
                                  sum(c[1] for c in s.corners) / len(s.corners))
    add(placemark, "ellipsoidHeight", s.height + (undulation or 0.0))
    add(placemark, "height", s.height)

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


def waylines_wpml(p, s):
    root, document = kml_root()
    mission_config(document, s, template=False, reroute=False)

    speed = speed_of(p, s)
    folder = ET.SubElement(document, k("Folder"))
    add(folder, "templateId", 0)
    add(folder, "executeHeightMode", "WGS84")
    add(folder, "waylineId", 0)
    add(folder, "distance", p.distance)
    add(folder, "duration", p.duration)
    add(folder, "autoFlightSpeed", speed)
    start_action_group(folder, p.pitch)
    add(folder, "realTimeFollowSurfaceByFov", 0)

    points = p.waypoints
    last = len(points) - 1
    for i, (lon, lat, h) in enumerate(points):
        placemark = ET.SubElement(folder, k("Placemark"))
        ET.SubElement(ET.SubElement(placemark, k("Point")), k("coordinates")).text = \
            "\n            %s,%s\n          " % (coordinate(lon), coordinate(lat))
        add(placemark, "index", i)
        add(placemark, "executeHeight", h)
        add(placemark, "waypointSpeed", speed)

        # Every point but the last faces the slope; the last one just stops
        heading = add(placemark, "waypointHeadingParam")
        add(heading, "waypointHeadingMode", "fixed" if i < last else "followWayline")
        add(heading, "waypointHeadingAngle", round(p.heading, 9) if i < last else 0)
        add(heading, "waypointPoiPoint", "0.000000,0.000000,0.000000")
        add(heading, "waypointHeadingAngleEnable", 1 if i < last else 0)
        add(heading, "waypointHeadingPathMode", "followBadArc")
        add(heading, "waypointHeadingPoiIndex", 0)

        # The ends stop; elsewhere the aircraft rounds the corner, starting to turn a third of the shorter leg before it
        turn = add(placemark, "waypointTurnParam")
        stops = i in (0, last)
        add(turn, "waypointTurnMode", STOP if stops else "coordinateTurn")
        add(turn, "waypointTurnDampingDist", 0 if stops else round(min(p.legs[i - 1], p.legs[i]) / 3.0, 9))
        add(placemark, "useStraightLine", 1)

        # Photos all the way, the gimbal square-on to the face (Pilot 2 does not lock it here)
        if i == 0:
            group = action_group(placemark, 0, 0, last, "multipleDistance", p.interval)
            wpml.gimbal_rotate(group, 0, p.pitch)
            simple_action(group, 1, "startContinuousShooting", payloadPositionIndex=0, useGlobalPayloadLensIndex=0,
                          payloadLensIndex=lens_index(s))
        if i == last:
            group = action_group(placemark, 1, last, last, "reachPoint")
            simple_action(group, 0, "stopContinuousShooting", payloadPositionIndex=0, payloadLensIndex=lens_index(s))

        gimbal = add(placemark, "waypointGimbalHeadingParam")
        add(gimbal, "waypointGimbalPitchAngle", 0)
        add(gimbal, "waypointGimbalYawAngle", 0)
        add(placemark, "isRisky", 0)
        add(placemark, "waypointWorkType", 0)

    return to_xml(root)


def mission_warnings(p, s):
    """Things to check before flying that the file itself cannot say"""
    warnings = []
    speed = speed_of(p, s)
    if speed > p.max_speed + 1e-9:
        warnings.append("The speed of %.1f m/s is more than the %.1f m/s that leaves 1.25 s between photos: some may be "
                        "missed" % (speed, p.max_speed))
    warnings.append("The route flies the face's corner heights: check them, and the distance from the face, before "
                    "flying")
    top = max(h for _, _, h in p.waypoints)
    bottom = min(c[2] for c in s.corners)
    if s.rth_height < top - bottom + 10:
        warnings.append("The return height (%g m) is not well above the top of the route (%.0f m above the bottom of "
                        "the face)" % (s.rth_height, top - bottom))
    return warnings


def build_kmz(p, s, now=None):
    """
    The route as the bytes of a .kmz file.

    :param p: plan(s)
    :param s: settings(...)
    :param now: time.time() at creation, for repeatable output (default: now)
    """
    now_ms = int(round((time.time() if now is None else now) * 1000))
    files = [("wpmz/template.kml", template_kml(p, s, now_ms)), ("wpmz/waylines.wpml", waylines_wpml(p, s))]

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))     # same bytes for the same route
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, content)
    return out.getvalue()
