"""
Export of a waypoint route as a DJI WPML mission (.kmz) for an aircraft of drones.json, in the format Pilot 2 imports.

A waypoint route is a list of points the aircraft flies to in order, with what to do at each: turn to a heading, tilt
the gimbal, hover, take a photo. The structure, the element order and the rules for the values below were taken from
waypoint missions exported by Pilot 2 (tests/fixtures/dji-kmz: m4e-test-waypoint.kmz, m4t-test-waypoint.kmz and
TestWaypointRoute.kmz; a Toward-POI route, the curve, video and interval photos from m4t-test-poi-waypoint.kmz).
What the two files share with an area mission (missionConfig, the payload) comes from missions/wpml.py.

Only these actions are written: rotateYaw, gimbalRotate (pitch only), hover and takePhoto at points; startRecord /
stopRecord and interval photos over the whole route; gimbalEvenlyRotate between points for a steady gimbal.
"""
import io
import math
import time
import zipfile
from collections import namedtuple
from xml.etree import ElementTree as ET

from .wpml import (known, GEOD, ExportError, action_group, add, check_cameras, check_choices,
                   check_flight, coordinate, is_number, k, kml_root, lens_index, mission_config, signed_degrees, simple_action, to_xml)

# The template's heightMode for each of the route's height modes. ASL and AGL are both flown as WGS84-ellipsoidal
# heights (executeHeightMode WGS84), ALT as heights above the takeoff point.
HEIGHT_MODES = {"alt": "relativeToStartPoint", "asl": "EGM96", "agl": "aboveGroundLevel"}
# towardPOI: the aircraft faces the route's POI all the way (Pilot 2 writes it per point, the global heading
# following the route)
HEADING_MODES = ("followWayline", "manually", "towardPOI")
# stop: the aircraft stops at each point; pass: it rounds the corners without stopping (the ends still stop); curve:
# the same, flown on a curve through the points rather than straight legs (useStraightLine 0)
TURN_MODES = {"stop": "toPointAndStopWithDiscontinuityCurvature", "pass": "toPointAndPassWithContinuityCurvature",
              "curve": "toPointAndPassWithContinuityCurvature"}
STOP = TURN_MODES["stop"]
# Photos every so many meters or seconds, from the first point to the last
PHOTO_INTERVAL_MODES = {"distance": "multipleDistance", "time": "multipleTiming"}
MIN_INTERVAL, MAX_INTERVAL = 0.5, 900.0     # meters or seconds

MIN_HEIGHT, MAX_HEIGHT = 2.0, 1500.0        # ALT and AGL heights, meters
MIN_ASL, MAX_ASL = -1000.0, 10000.0
MIN_PITCH, MAX_PITCH = -90.0, 35.0
MAX_HOVER = 900.0                           # seconds
# The time a stop or the actions at a point add to the flight, seconds: close to what Pilot 2 estimates for a route
# that stops or acts at every point (m4e-test-waypoint.kmz)
POINT_TIME = 3.0
# What each point passed on a curve adds to the flight, seconds: what Pilot 2's estimate for m4t-test-poi-waypoint.kmz
# (62.8 s for 6 such points) needs beyond the legs and the two stops
CURVE_TIME = 1.44

Point = namedtuple("Point", "lat lon height heading pitch photo hover ground")
# height: meters, in the route's height mode, or None for the route's height
# heading: the aircraft's heading at the point (degrees from north, -180 to 180), or None to leave it
# pitch: the gimbal's pitch from there on (degrees, -90 straight down), or None to leave it
# photo: take a photo at the point; hover: seconds to hover there (0 for none)
# ground: WGS84-ellipsoidal ground height under the point (missions/elevation.py), for AGL; None until fetched

Settings = namedtuple("Settings", "points cameras height_mode height speed gimbal_pitch heading_mode turn_mode "
                                  "takeoff_mode finish_action exit_on_rc_lost takeoff_security_height takeoff_ref_point "
                                  "takeoff_ellipsoidal_height transitional_speed rth_height author avoid_limit_area model "
                                  "poi video photo_interval_mode photo_interval")

Plan = namedtuple("Plan", "length duration photos")


def check_height(value, height_mode, label):
    if height_mode == "asl":
        if not (is_number(value) and MIN_ASL <= value <= MAX_ASL):
            raise ExportError("The %s must be between %g and %g meters above sea level" % (label, MIN_ASL, MAX_ASL))
    elif not (is_number(value) and MIN_HEIGHT <= value <= MAX_HEIGHT):
        raise ExportError("The %s must be between %g and %g meters" % (label, MIN_HEIGHT, MAX_HEIGHT))


def point(n, lat, lon, height=None, heading=None, pitch=None, photo=False, hover=0, ground=None, height_mode="alt"):
    """A Point, checked; n is its number for the messages (from 1)"""
    if not (is_number(lat) and -90 <= lat <= 90 and is_number(lon) and -180 <= lon <= 180):
        raise ExportError("Point %d is not a latitude and longitude" % n)
    if height is not None:
        check_height(height, height_mode, "height of point %d" % n)
    if heading is not None and not is_number(heading):
        raise ExportError("The heading of point %d must be a number of degrees" % n)
    if pitch is not None and not (is_number(pitch) and MIN_PITCH <= pitch <= MAX_PITCH):
        raise ExportError("The gimbal pitch of point %d must be between %g and %g degrees" % (n, MIN_PITCH, MAX_PITCH))
    if not isinstance(photo, bool):
        raise ExportError("The photo at point %d must be on or off" % n)
    if not (is_number(hover) and 0 <= hover <= MAX_HOVER):
        raise ExportError("The hover at point %d must be between 0 and %g seconds" % (n, MAX_HOVER))
    if ground is not None and not is_number(ground):
        raise ExportError("The ground height under point %d must be a number" % n)
    return Point(lat=float(lat), lon=float(lon), height=None if height is None else float(height),
                 heading=None if heading is None else round(signed_degrees(float(heading)), 9),
                 pitch=None if pitch is None else float(pitch), photo=photo, hover=float(hover),
                 ground=None if ground is None else float(ground))


def settings(points, cameras, height=50.0, height_mode="alt", speed=5.0, gimbal_pitch=None,
             heading_mode="followWayline", turn_mode="stop", takeoff_mode="safe", finish_action="goHome",
             exit_on_rc_lost="goContinue", takeoff_security_height=20.0, takeoff_ref_point=None,
             takeoff_ellipsoidal_height=None, transitional_speed=15.0, rth_height=100.0, author=None,
             avoid_limit_area=False, model="m4t", poi=None, video=False, photo_interval_mode=None,
             photo_interval=None):
    """
    The settings of the route, checked.

    :param points: [{lat, lon, height?, heading?, pitch?, photo?, hover?, ground?}, ...] in flying order (see Point)
    :param cameras: [Camera, ...], all of them cameras of the model (cameras.CAMERAS_BY_MODEL)
    :param height: the height of the points that have none of their own, in the height mode
    :param height_mode: "alt": above the takeoff point; "asl": above sea level (needs takeoff_ref_point and
        takeoff_ellipsoidal_height); "agl": above the ground under each point (needs each point's ground to export)
    :param gimbal_pitch: the gimbal's pitch from the first point on, degrees; None to leave the gimbal as it is
    :param heading_mode: "followWayline" (the aircraft faces where it flies) or "manually" (it keeps its heading)
    :param turn_mode: "stop", "pass" or "curve" (see TURN_MODES)
    :param poi: (lat, lon) the aircraft faces on a "towardPOI" route (kept only there)
    :param video: record a video from the first point to the last
    :param photo_interval_mode: None, or photos every photo_interval meters ("distance") or seconds ("time") from
        the first point to the last
    :param takeoff_ref_point: (lat, lon, altitude above sea level) of the takeoff point, if known
    :param takeoff_ellipsoidal_height: WGS84-ellipsoidal ground height at the takeoff point (ASL only)
    """
    check_choices(model, takeoff_mode, finish_action, exit_on_rc_lost)
    if not known(height_mode, HEIGHT_MODES):
        raise ExportError("Unknown height mode %r" % (height_mode,))
    if not known(heading_mode, HEADING_MODES):
        raise ExportError("Unknown heading mode %r" % (heading_mode,))
    if not known(turn_mode, TURN_MODES):
        raise ExportError("Unknown turn mode %r" % (turn_mode,))
    if not isinstance(avoid_limit_area, bool):
        raise ExportError("The geo zone bypassing must be on or off")
    if heading_mode == "towardPOI":
        if (not isinstance(poi, (list, tuple)) or len(poi) != 2 or not all(is_number(v) for v in poi)
                or not (-90 <= poi[0] <= 90 and -180 <= poi[1] <= 180)):
            raise ExportError("The Toward POI heading needs the POI's latitude and longitude")
        poi = (float(poi[0]), float(poi[1]))
    else:
        poi = None
    if not isinstance(video, bool):
        raise ExportError("The video must be on or off")
    if photo_interval_mode is None:
        photo_interval = None
    elif not known(photo_interval_mode, PHOTO_INTERVAL_MODES):
        raise ExportError("Unknown interval photo mode %r" % (photo_interval_mode,))
    elif not (is_number(photo_interval) and MIN_INTERVAL <= photo_interval <= MAX_INTERVAL):
        raise ExportError("The photo interval must be between %g and %g %s" % (
            MIN_INTERVAL, MAX_INTERVAL, "meters" if photo_interval_mode == "distance" else "seconds"))
    check_flight(takeoff_security_height, rth_height, speed, transitional_speed, takeoff_ref_point, transit="route",
                 need_speed=True)
    if height_mode == "asl":
        if takeoff_ref_point is None:
            raise ExportError("The ASL height mode needs the ground height at the takeoff point")
        if not is_number(takeoff_ellipsoidal_height):
            raise ExportError("The ASL height mode needs the ellipsoidal ground height at the takeoff point")
    elif takeoff_ellipsoidal_height is not None:
        raise ExportError("The ellipsoidal ground height at the takeoff point only applies to the ASL height mode")
    check_height(height, height_mode, "route's height")
    if gimbal_pitch is not None and not (is_number(gimbal_pitch) and MIN_PITCH <= gimbal_pitch <= MAX_PITCH):
        raise ExportError("The gimbal pitch must be between %g and %g degrees" % (MIN_PITCH, MAX_PITCH))

    check_cameras(model, cameras)

    if len(points) < 2:
        raise ExportError("A waypoint route needs at least 2 points")
    checked = []
    for n, p in enumerate(points, start=1):
        if not isinstance(p, dict):
            raise ExportError("Point %d is not a latitude and longitude" % n)
        unknown = set(p) - set(Point._fields)
        if unknown:
            raise ExportError("Point %d has unknown settings: %s" % (n, ", ".join(sorted(unknown))))
        if "lat" not in p or "lon" not in p:
            raise ExportError("Point %d is not a latitude and longitude" % n)
        checked.append(point(n, height_mode=height_mode, **p))
    if heading_mode == "towardPOI":
        turning = [n for n, p in enumerate(checked, start=1) if p.heading is not None]
        if turning:
            raise ExportError("A Toward POI route cannot turn the aircraft at a point (%s)" % points_text(turning))
        if gimbal_pitch is None and checked[0].pitch is None and any(p.pitch is not None for p in checked):
            raise ExportError("A Toward POI route that sets the gimbal pitch at a point needs a pitch from the first "
                              "point on")

    return Settings(points=checked, cameras=list(cameras), height_mode=height_mode, height=float(height),
                    speed=float(speed), gimbal_pitch=None if gimbal_pitch is None else float(gimbal_pitch),
                    heading_mode=heading_mode, turn_mode=turn_mode, takeoff_mode=takeoff_mode,
                    finish_action=finish_action, exit_on_rc_lost=exit_on_rc_lost,
                    takeoff_security_height=float(takeoff_security_height),
                    takeoff_ref_point=None if takeoff_ref_point is None else tuple(float(v) for v in takeoff_ref_point),
                    takeoff_ellipsoidal_height=None if takeoff_ellipsoidal_height is None else float(takeoff_ellipsoidal_height),
                    transitional_speed=float(transitional_speed), rth_height=float(rth_height), author=author,
                    avoid_limit_area=avoid_limit_area, model=model, poi=poi, video=video,
                    photo_interval_mode=photo_interval_mode,
                    photo_interval=None if photo_interval is None else float(photo_interval))


def points_text(numbers):
    return ("point %s" if len(numbers) == 1 else "points %s") % ", ".join(str(n) for n in numbers)


# -- Heights and the plan ------------------------------------------------------------------------------------------

def height_of(p, s):
    """The point's height in the route's height mode"""
    return s.height if p.height is None else p.height


def asl_offset(s):
    """What turns a height above sea level into a WGS84-ellipsoidal one: the difference between the two ground heights
    at the takeoff point (Pilot 2: m4e-test-waypoint.kmz)"""
    return s.takeoff_ellipsoidal_height - s.takeoff_ref_point[2]


def execute_heights(s, strict=True):
    """
    The height the aircraft flies at each point: above the takeoff point (ALT), or WGS84-ellipsoidal (ASL, AGL).

    :param strict: raise ExportError when an AGL point has no ground height yet; otherwise use its height above the
        ground alone (for an estimate of the length)
    """
    if s.height_mode == "alt":
        return [height_of(p, s) for p in s.points]
    if s.height_mode == "asl":
        offset = asl_offset(s)
        return [height_of(p, s) + offset for p in s.points]
    if strict and any(p.ground is None for p in s.points):
        raise ExportError("The AGL height mode needs the ground height under every point: fetch the elevations first")
    return [height_of(p, s) + (p.ground or 0.0) for p in s.points]


def legs(s, heights):
    """The 3D length of each leg between two points, meters"""
    out = []
    for a, b, ha, hb in zip(s.points, s.points[1:], heights, heights[1:]):
        flat = GEOD.inv(a.lon, a.lat, b.lon, b.lat)[2]
        out.append(math.hypot(flat, hb - ha))
    return out


def pitches(s):
    """The gimbal pitch set at each point (None where it is not set): the route's pitch at the first point, unless
    that point has its own, and each point's own pitch"""
    out = [p.pitch for p in s.points]
    if out[0] is None:
        out[0] = s.gimbal_pitch
    return out


def held_pitches(s):
    """The gimbal pitch the aircraft holds at each point: the last one set at or before it (None before the first)"""
    out, held = [], None
    for pitch in pitches(s):
        held = held if pitch is None else pitch
        out.append(held)
    return out


def toward_poi(s):
    return s.heading_mode == "towardPOI"


def steady_gimbal(s):
    """A Toward-POI route holds its gimbal pitch from point to point, as Pilot 2 writes it (m4t-test-poi-waypoint.kmz):
    the pitch on each point of the template, eased to between each pair of points rather than set on reaching them"""
    return toward_poi(s) and pitches(s)[0] is not None


def pilot2_form(s):
    """Whether the template is written in the form of Pilot 2's Toward-POI export (m4t-test-poi-waypoint.kmz):
    positioningType GPS, the global turn and speed only on the points, the shorter payloadParam. The other routes keep
    the form of the older exports."""
    return toward_poi(s)


def straight_line(s):
    return 0 if s.turn_mode == "curve" else 1


def action_pitches(s):
    """The gimbal pitch set by a gimbalRotate on reaching each point (None for none): none with a steady gimbal"""
    return [None] * len(s.points) if steady_gimbal(s) else pitches(s)


def stops(s, i):
    return s.turn_mode == "stop" or i in (0, len(s.points) - 1)


def has_actions(s, i, pitch):
    p = s.points[i]
    return p.heading is not None or pitch is not None or p.hover > 0 or p.photo


def plan(s, strict=False):
    """The route's length (m), an estimate of its flight time (s, from the first point to the last) and its photos"""
    lengths = legs(s, execute_heights(s, strict=strict))
    length = sum(lengths)
    pitch = action_pitches(s)
    duration = length / s.speed
    for i, p in enumerate(s.points):
        if stops(s, i) or has_actions(s, i, pitch[i]):
            duration += POINT_TIME
        elif s.turn_mode == "curve":
            duration += CURVE_TIME
        duration += p.hover
    photos = sum(1 for p in s.points if p.photo)
    if s.photo_interval_mode == "distance":
        photos += int(length // s.photo_interval) + 1
    elif s.photo_interval_mode == "time":
        photos += int(duration // s.photo_interval) + 1
    return Plan(length=length, duration=duration, photos=photos)


def damping(s, lengths, i):
    """How far before point i the aircraft starts to round the corner when it passes: a third of the shorter leg on
    either side, as Pilot 2 writes it (m4e-test-waypoint.kmz, within 0.3%)"""
    return round(min(lengths[i - 1], lengths[i]) / 3.0, 9)


# -- XML -----------------------------------------------------------------------------------------------------------

def poi_point(s):
    return "%.6f,%.6f,0.000000" % s.poi if toward_poi(s) else "0.000000,0.000000,0.000000"


def heading_param(placemark, s, flown):
    h = add(placemark, "waypointHeadingParam")
    add(h, "waypointHeadingMode", s.heading_mode)
    add(h, "waypointHeadingAngle", 0)
    add(h, "waypointPoiPoint", poi_point(s))
    if flown:
        add(h, "waypointHeadingAngleEnable", 0)
    add(h, "waypointHeadingPathMode", "followBadArc")
    add(h, "waypointHeadingPoiIndex", 0)
    return h


def gimbal_rotate(parent, action_id, pitch, base="north", rotate_time=0):
    """The gimbal's pitch, measured from the horizon, as Pilot 2 writes it in a waypoint route (unlike
    wpml.gimbal_rotate for an area): to the north at a point, to the aircraft for a steady gimbal"""
    action = add(parent, "action")
    add(action, "actionId", action_id)
    add(action, "actionActuatorFunc", "gimbalRotate")
    param = add(action, "actionActuatorFuncParam")
    for tag, value in (("gimbalHeadingYawBase", base), ("gimbalRotateMode", "absoluteAngle"),
                       ("gimbalPitchRotateEnable", 1), ("gimbalPitchRotateAngle", pitch), ("gimbalRollRotateEnable", 0),
                       ("gimbalRollRotateAngle", 0), ("gimbalYawRotateEnable", 0), ("gimbalYawRotateAngle", 0),
                       ("gimbalRotateTimeEnable", 0), ("gimbalRotateTime", rotate_time), ("payloadPositionIndex", 0)):
        add(param, tag, value)


def group_ids(s):
    """The ids of the groups run over the route, in Pilot 2's order (m4t-test-poi-waypoint.kmz): the start (video,
    the steady gimbal), the end of the video, the interval photos, then one between each pair of points for a steady
    gimbal (the first of them). "points" is the id of point 0's own group: a route with none of these keeps its ids."""
    ids, next_id = {}, 0
    for name, present in (("start", s.video or steady_gimbal(s)), ("stop", s.video),
                          ("interval", s.photo_interval_mode is not None), ("between", steady_gimbal(s))):
        ids[name] = next_id if present else None
        if present:
            next_id += len(s.points) - 1 if name == "between" else 1
    ids["points"] = next_id
    return ids


def route_actions(placemark, s, i, ids, flown):
    """The groups of the route run from point i: the start and the interval photos at the first point, easing the
    gimbal to the next point's pitch (the flown file only), the end of the video at the last point"""
    last = len(s.points) - 1
    held = held_pitches(s)
    if i == 0 and ids["start"] is not None and (flown or s.video):
        group = action_group(placemark, ids["start"], 0, 0, "reachPoint")
        action_id = 0
        if s.video:
            record = {"fileSuffix": "Waypoint1", "payloadPositionIndex": 0, "useGlobalPayloadLensIndex": 1}
            if flown:
                record["payloadLensIndex"] = lens_index(s)
            simple_action(group, action_id, "startRecord", **record)
            action_id += 1
        if flown and steady_gimbal(s):
            gimbal_rotate(group, action_id, held[0], base="aircraft", rotate_time=10)
    if i == 0 and ids["interval"] is not None:
        group = action_group(placemark, ids["interval"], 0, last, PHOTO_INTERVAL_MODES[s.photo_interval_mode],
                             s.photo_interval)
        simple_action(group, 0, "takePhoto", payloadPositionIndex=0, useGlobalPayloadLensIndex=1,
                      payloadLensIndex=lens_index(s))
    if flown and ids["between"] is not None and i < last:
        group = action_group(placemark, ids["between"] + i, i, i + 1, "betweenAdjacentPoints")
        simple_action(group, 0, "gimbalEvenlyRotate", gimbalPitchRotateAngle=held[i + 1], gimbalRollRotateAngle=0,
                      payloadPositionIndex=0)
    if i == last and s.video:
        group = action_group(placemark, ids["stop"], last, last, "reachPoint")
        simple_action(group, 0, "stopRecord", payloadPositionIndex=0)


def point_actions(placemark, s, i, pitch, flown, ids):
    """The point's actions, in one group run when the aircraft reaches it"""
    p = s.points[i]
    if not has_actions(s, i, pitch):
        return
    group = action_group(placemark, ids["points"] + i, i, i, "reachPoint")
    action_id = 0
    if p.heading is not None:
        simple_action(group, action_id, "rotateYaw", aircraftHeading=p.heading, aircraftPathMode="counterClockwise")
        action_id += 1
    if pitch is not None:
        gimbal_rotate(group, action_id, pitch)
        action_id += 1
    if p.hover > 0:
        simple_action(group, action_id, "hover", hoverTime=p.hover)
        action_id += 1
    if p.photo:
        if flown:
            simple_action(group, action_id, "takePhoto", payloadPositionIndex=0, useGlobalPayloadLensIndex=1,
                          payloadLensIndex=lens_index(s))
        else:
            simple_action(group, action_id, "takePhoto", payloadPositionIndex=0, useGlobalPayloadLensIndex=1)


def coordinates(placemark, p):
    ET.SubElement(ET.SubElement(placemark, k("Point")), k("coordinates")).text = \
        "\n            %s,%s\n          " % (coordinate(p.lon), coordinate(p.lat))


def template_kml(s, now_ms):
    root, document = kml_root()
    if s.author:
        add(document, "author", s.author)
    add(document, "createTime", now_ms)
    add(document, "updateTime", now_ms)
    mission_config(document, s, template=True)

    folder = ET.SubElement(document, k("Folder"))
    add(folder, "templateType", "waypoint")
    add(folder, "templateId", 0)
    system = add(folder, "waylineCoordinateSysParam")
    add(system, "coordinateMode", "WGS84")
    add(system, "heightMode", HEIGHT_MODES[s.height_mode])
    if pilot2_form(s):
        add(system, "positioningType", "GPS")
    add(folder, "autoFlightSpeed", s.speed)
    add(folder, "globalHeight", s.height)
    add(folder, "caliFlightEnable", 0)
    add(folder, "gimbalPitchMode", "usePointSetting" if steady_gimbal(s) else "manual")
    heading = add(folder, "globalWaypointHeadingParam")
    if toward_poi(s):       # Pilot 2: the route follows the wayline, each point faces the POI
        add(heading, "waypointHeadingMode", "followWayline")
        add(heading, "waypointHeadingAngle", 0)
        add(heading, "waypointPoiPoint", poi_point(s))
    else:
        add(heading, "waypointHeadingMode", s.heading_mode)
        add(heading, "waypointHeadingAngle", 0)
        add(heading, "waypointPoiPoint", poi_point(s))
        add(heading, "waypointHeadingPathMode", "followBadArc")
    add(heading, "waypointHeadingPoiIndex", 0)
    add(folder, "globalWaypointTurnMode", TURN_MODES[s.turn_mode])
    add(folder, "globalUseStraightLine", straight_line(s))

    heights = execute_heights(s)
    pitch = action_pitches(s)
    held = held_pitches(s)
    ids = group_ids(s)
    for i, p in enumerate(s.points):
        placemark = ET.SubElement(folder, k("Placemark"))
        coordinates(placemark, p)
        add(placemark, "index", i)
        add(placemark, "ellipsoidHeight", heights[i])
        add(placemark, "height", height_of(p, s))
        if pilot2_form(s):
            heading_param(placemark, s, flown=False)
            if p.height is None:
                add(placemark, "useGlobalHeight", 1)
            add(placemark, "useGlobalSpeed", 1)
            add(placemark, "useGlobalTurnParam", 1)
            if steady_gimbal(s):
                add(placemark, "gimbalPitchAngle", held[i])
            add(placemark, "useStraightLine", straight_line(s))
        else:
            add(placemark, "waypointSpeed", s.speed)
            heading_param(placemark, s, flown=False)
            turn = add(placemark, "waypointTurnParam")
            add(turn, "waypointTurnMode", TURN_MODES[s.turn_mode])
            add(turn, "waypointTurnDampingDist", 0.2)
            if p.height is None:
                add(placemark, "useGlobalHeight", 1)
            for tag in ("useGlobalSpeed", "useGlobalHeadingParam", "useGlobalTurnParam"):
                add(placemark, tag, 1)
            add(placemark, "useStraightLine", straight_line(s))
        route_actions(placemark, s, i, ids, flown=False)
        point_actions(placemark, s, i, pitch[i], flown=False, ids=ids)
        add(placemark, "isRisky", 0)

    param = add(folder, "payloadParam")
    add(param, "payloadPositionIndex", 0)
    if pilot2_form(s):
        add(param, "imageFormat", lens_index(s))
        add(param, "photoSize")
        return to_xml(root)
    add(param, "focusMode", "firstPoint")
    add(param, "meteringMode", "average")
    add(param, "returnMode", "singleReturnStrongest")
    add(param, "samplingRate", 240000)
    add(param, "scanningMode", "repetitive")
    add(param, "imageFormat", lens_index(s))
    add(param, "photoSize", "default_l")
    return to_xml(root)


def waylines_wpml(s):
    root, document = kml_root()
    mission_config(document, s, template=False)

    heights = execute_heights(s)
    lengths = legs(s, heights)
    route = plan(s, strict=True)
    pitch = action_pitches(s)
    ids = group_ids(s)

    folder = ET.SubElement(document, k("Folder"))
    add(folder, "templateId", 0)
    add(folder, "executeHeightMode", "relativeToStartPoint" if s.height_mode == "alt" else "WGS84")
    add(folder, "waylineId", 0)
    add(folder, "distance", route.length)
    add(folder, "duration", route.duration)
    add(folder, "autoFlightSpeed", s.speed)
    add(folder, "realTimeFollowSurfaceByFov", 0)

    for i, p in enumerate(s.points):
        placemark = ET.SubElement(folder, k("Placemark"))
        coordinates(placemark, p)
        add(placemark, "index", i)
        add(placemark, "executeHeight", heights[i])
        add(placemark, "waypointSpeed", s.speed)
        heading_param(placemark, s, flown=True)
        turn = add(placemark, "waypointTurnParam")
        if stops(s, i):
            add(turn, "waypointTurnMode", STOP)
            add(turn, "waypointTurnDampingDist", 0)
        else:
            add(turn, "waypointTurnMode", TURN_MODES["pass"])
            add(turn, "waypointTurnDampingDist", damping(s, lengths, i))
        add(placemark, "useStraightLine", straight_line(s))
        route_actions(placemark, s, i, ids, flown=True)
        point_actions(placemark, s, i, pitch[i], flown=True, ids=ids)
        gimbal = add(placemark, "waypointGimbalHeadingParam")
        add(gimbal, "waypointGimbalPitchAngle", 0)
        add(gimbal, "waypointGimbalYawAngle", 0)
        add(placemark, "isRisky", 0)
        add(placemark, "waypointWorkType", 0)

    return to_xml(root)


def mission_warnings(s):
    """Things to check before flying that the file itself cannot say"""
    warnings = []
    highest = max(height_of(p, s) for p in s.points)
    if s.height_mode == "alt":
        warnings.append("The height is measured from the takeoff point: the aircraft will not follow the terrain")
    elif s.height_mode == "asl":
        warnings.append("The height is measured above sea level, from public elevation data that can differ from "
                        "the real ground by a few meters: check the height before flying")
        highest -= s.takeoff_ref_point[2]
    else:
        warnings.append("The height above the ground at each point comes from public elevation data that can differ "
                        "from the real ground by a few meters, and does not include buildings or trees: check the "
                        "heights before flying")
    if pilot2_form(s):
        warnings.append("The route is flown on GPS positioning, without RTK: the aircraft can be a meter or more from "
                        "the points, and its height off by more; keep a margin from what it circles")
    if s.rth_height < highest + 10:
        warnings.append("The return height (%g m) is not well above the flight height (%g m)" % (s.rth_height, highest))
    return warnings


def build_kmz(s, now=None):
    """
    The route as the bytes of a .kmz file.

    :param s: settings(...)
    :param now: time.time() at creation, for repeatable output (default: now)
    """
    now_ms = int(round((time.time() if now is None else now) * 1000))
    files = (("wpmz/template.kml", template_kml(s, now_ms)), ("wpmz/waylines.wpml", waylines_wpml(s)))

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))     # same bytes for the same route
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, content)
    return out.getvalue()
