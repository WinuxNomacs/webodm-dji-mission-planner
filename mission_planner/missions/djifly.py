"""
Export of a route as a DJI Fly waypoint mission (.kmz), for the consumer drones of drones.json whose app is "djifly".

DJI does not publish DJI Fly's format. What it takes was learnt from FlyPath (github.com/dronnix-io/FlyPath, commit
a6f92c0, 2026-11-17; its writer wpml/consumer.py, matched by its authors to a mission dumped from a DJI RC 2 for a
Mini 4 Pro), cross-checked against DJI's user manuals (the "Waypoint Flight" sections); no DJI Fly file was at hand.
This code is our own; FlyPath is cited for the facts only.

What differs from Pilot 2's files (wpml.py):
- The namespace is http://www.uav.com/wpmz/1.0.2 and the template is a waypoint mission only: an area or linear route
  is written as its waypoints, one per photo, since DJI Fly ignores photos every so many meters or seconds (FlyPath's
  field reports, its issue #3). The first point turns the gimbal and hovers 3 s before its photo, so that it is
  taken straight down (FlyPath's issue #8).
- No payload, lens, takeoff point, takeoff security or return height: the drone uses the camera active at the time.
- Heights are above the takeoff point only (relativeToStartPoint). AGL becomes a height per waypoint: the height plus
  the ground there minus the ground at the takeoff point (the route's terrain; or, for a waypoint route, each point's
  fetched ground). With no takeoff point set, the route's first point is taken as the takeoff point.
- Points are flown on curves (useStraightLine 0): straight legs are reshuffled when DJI Fly saves the mission again
  (FlyPath's issue #13).
- A mission holds at most MAX_WAYPOINTS points (FlyPath's limit: "DJI allows about 200"; DJI states none); a longer
  route is split into several missions that share the point where one ends and the next begins, at most MAX_MISSIONS
  (decided 2026-11-19: a larger route takes seconds to write and many flights to fly; it is refused).
- DJI Fly lists only missions it made: one is put on the controller by replacing the file of a mission made there
  (README).
"""
import io
import math
import zipfile
from xml.etree import ElementTree as ET

from . import geoid, terrain, waypoints
from .drones import DRONES
from .wpml import GEOD, ExportError

NS = "http://www.uav.com/wpmz/1.0.2"
KML = "http://www.opengis.net/kml/2.2"
MAX_WAYPOINTS = 200
MAX_MISSIONS = 20
MAX_POINTS = MAX_MISSIONS * (MAX_WAYPOINTS - 1) + 1     # the missions share their seams
ADVICE = {"area": "Split the area into smaller routes, or fly higher", "linear": "Split the line into shorter routes, or fly higher",
          "waypoint": "Split it into smaller routes"}
GIMBAL_SETTLE = 3.0                 # seconds the first point hovers for the gimbal to reach its pitch
TRANSITIONAL_SPEED = 5.0            # m/s, at most, from the takeoff to the first point (FlyPath)
# DJI Fly's end of flight (its manual: Hover, RTH, Land): the planner's finish actions it takes
FINISH_ACTIONS = {"goHome": "goHome", "noAction": "hover", "autoLand": "autoLand"}
MIN_SEGMENT = 1.0                   # meters: a line's end closer than this to its last photo is not a point of its own

def is_djifly(model):
    return DRONES[model].app == "djifly"


def check(kind, s):
    """ExportError when the route asks what a DJI Fly mission cannot do"""
    drone = DRONES[s.model]
    if kind == "area" and s.collection_mode == "oblique":
        raise ExportError("DJI Fly missions take ortho photos only: choose Ortho collection")
    if s.finish_action not in FINISH_ACTIONS:
        raise ExportError("DJI Fly ends a mission by returning home, hovering or landing: choose one of those")
    if drone.max_speed is not None and s.speed is not None and s.speed > drone.max_speed:
        raise ExportError("The %s flies a mission at %g m/s at most" % (drone.name, drone.max_speed))
    if kind == "waypoint":
        if s.heading_mode == "towardPOI" or s.poi is not None:
            raise ExportError("DJI Fly missions cannot face a point of interest from this planner yet")
        if s.video or s.photo_interval_mode:
            raise ExportError("DJI Fly ignores video and photos every so many meters or seconds: take photos at points")


def _along(line, spacing):
    """The points every `spacing` meters along a polyline [(lon, lat), ...] from its start, then its end (no photo)
    when it is farther than MIN_SEGMENT from the last: [((lon, lat), photo), ...]"""
    out, carried = [], 0.0          # carried: meters walked since the last photo
    out.append((tuple(line[0][:2]), True))
    for a, b in zip(line, line[1:]):
        azimuth, _, length = GEOD.inv(a[0], a[1], b[0], b[1])
        walked = spacing - carried
        while walked <= length + 1e-9:
            lon, lat, _ = GEOD.fwd(a[0], a[1], azimuth, walked)
            out.append(((lon, lat), True))
            walked += spacing
        carried = length - (walked - spacing)
    if carried >= MIN_SEGMENT:
        out.append((tuple(line[-1][:2]), False))
    return out


def survey_points(lines, spacing):
    """An area or linear route's lines as waypoints, one per photo: [((lon, lat), photo), ...]"""
    if not spacing or spacing <= 0:
        raise ExportError("The photos need a spacing")
    points = []
    for line in lines:
        if len(line) >= 2:
            points += _along(line, spacing)
    return points


def _relative_survey(points, s, kind, tif):
    """The height above the takeoff point of each survey waypoint"""
    if s.height_mode != "realTimeFollowSurface":
        return [s.height] * len(points)         # ALT, and ASL: one altitude, the takeoff point's ground plus the height
    if tif is None:
        raise ExportError("Fetch the terrain under the route first")
    at = [p for p, _ in points]
    takeoff = (s.takeoff_ref_point[1], s.takeoff_ref_point[0]) if s.takeoff_ref_point else at[0]
    try:
        grounds = terrain.ground_heights(tif, at + [takeoff])
    except terrain.TerrainError as e:
        raise ExportError("The route's terrain does not cover it: %s" % e)
    base = grounds[-1]
    return [s.height + g - base for g in grounds[:-1]]


def _relative_waypoints(s):
    """The height above the takeoff point of each point of a waypoint route"""
    heights = [waypoints.height_of(p, s) for p in s.points]
    if s.height_mode == "alt":
        return heights
    if s.height_mode == "asl":
        if s.takeoff_ref_point is None:
            raise ExportError("The ASL height mode needs the ground height at the takeoff point")
        return [h - s.takeoff_ref_point[2] for h in heights]
    if any(p.ground is None for p in s.points):
        raise ExportError("The AGL height mode needs the ground height under every point: fetch the elevations first")
    if s.takeoff_ref_point is not None:
        try:
            base = geoid.to_ellipsoidal(s.takeoff_ref_point[0], s.takeoff_ref_point[1], s.takeoff_ref_point[2])
        except geoid.GeoidError as e:
            raise ExportError("The takeoff point's ground height cannot be made ellipsoidal: %s" % e)
    else:
        base = s.points[0].ground
    return [h + p.ground - base for h, p in zip(heights, s.points)]


def route_points(kind, plan, s, tif=None):
    """The mission's points: [{lon, lat, height, photo, pitch, heading, hover}], heights above the takeoff point"""
    if kind == "waypoint":
        heights = _relative_waypoints(s)
        pitch = s.gimbal_pitch
        points = []
        for p, h in zip(s.points, heights):
            pitch = p.pitch if p.pitch is not None else pitch
            points.append({"lon": p.lon, "lat": p.lat, "height": h, "photo": bool(p.photo), "pitch": pitch,
                           "heading": p.heading if s.heading_mode == "manually" else None, "hover": p.hover or 0})
        return points
    if kind == "linear":
        # photos along the path Pilot 2 shoots (linear.plan): the strip's lines and the turns between them, then the
        # center line from its bend on, as the plan's photo count has it
        w = plan.waypoints
        lines = [w[:len(w) if plan.stop is None else plan.stop + 1]] + ([] if plan.bend is None else [w[plan.bend:]])
        found = survey_points(lines, plan.interval)
    else:
        found = survey_points(plan.nadir.lines, plan.nadir.interval)
    heights = _relative_survey(found, s, kind, tif)
    return [{"lon": p[0], "lat": p[1], "height": h, "photo": photo, "pitch": -90.0, "heading": None, "hover": 0}
            for (p, photo), h in zip(found, heights)]


def split(points, kind=None):
    """The points in missions of at most MAX_WAYPOINTS, each beginning where the last ended, at most MAX_MISSIONS"""
    if len(points) < 2:
        raise ExportError("A DJI Fly mission needs at least 2 points")
    if len(points) > MAX_POINTS:
        raise ExportError("This route needs %d points, and a download holds at most %d (%d DJI Fly missions). %s"
                          % (len(points), MAX_POINTS, MAX_MISSIONS, ADVICE.get(kind, "Split it into smaller routes")))
    parts, start = [], 0
    while True:
        parts.append(points[start:start + MAX_WAYPOINTS])
        start += MAX_WAYPOINTS - 1
        if start >= len(points) - 1:
            return parts


def _add(parent, tag, value=None):
    e = ET.SubElement(parent, "{%s}%s" % (NS, tag))
    if value is not None:
        e.text = _text(value)
    return e


def _text(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return ("%.6f" % value).rstrip("0").rstrip(".") if value != int(value) else str(int(value))
    return str(value)


def _mission_config(document, s, speed):
    config = _add(document, "missionConfig")
    _add(config, "flyToWaylineMode", "safely")
    _add(config, "finishAction", FINISH_ACTIONS[s.finish_action])
    _add(config, "exitOnRCLost", s.exit_on_rc_lost)
    _add(config, "executeRCLostAction", "goBack")
    _add(config, "globalTransitionalSpeed", round(min(speed, TRANSITIONAL_SPEED), 1))
    drone = _add(config, "droneInfo")
    _add(drone, "droneEnumValue", DRONES[s.model].drone[0])
    _add(drone, "droneSubEnumValue", DRONES[s.model].drone[1])


def _gimbal_rotate(group, action_id, pitch):
    action = _add(group, "action")
    _add(action, "actionId", action_id)
    _add(action, "actionActuatorFunc", "gimbalRotate")
    param = _add(action, "actionActuatorFuncParam")
    for tag, value in (("gimbalHeadingYawBase", "aircraft"), ("gimbalRotateMode", "absoluteAngle"),
                       ("gimbalPitchRotateEnable", 1), ("gimbalPitchRotateAngle", float(pitch)),
                       ("gimbalRollRotateEnable", 0), ("gimbalRollRotateAngle", 0), ("gimbalYawRotateEnable", 0),
                       ("gimbalYawRotateAngle", 0), ("gimbalRotateTimeEnable", 0), ("gimbalRotateTime", 0),
                       ("payloadPositionIndex", 0)):
        _add(param, tag, value)


def _simple(group, action_id, func, **params):
    action = _add(group, "action")
    _add(action, "actionId", action_id)
    _add(action, "actionActuatorFunc", func)
    param = _add(action, "actionActuatorFuncParam")
    for tag, value in params.items():
        _add(param, tag, value)


def _placemark(folder, i, p, speed, first, last_pitch, group_id):
    placemark = ET.SubElement(folder, "{%s}Placemark" % KML)
    point = ET.SubElement(placemark, "{%s}Point" % KML)
    ET.SubElement(point, "{%s}coordinates" % KML).text = "%.8f,%.8f" % (p["lon"], p["lat"])
    _add(placemark, "index", i)
    _add(placemark, "executeHeight", round(float(p["height"]), 1))
    _add(placemark, "waypointSpeed", speed)
    heading = _add(placemark, "waypointHeadingParam")
    turned = p["heading"] is not None
    _add(heading, "waypointHeadingMode", "smoothTransition" if turned else "followWayline")
    _add(heading, "waypointHeadingAngle", float(p["heading"]) if turned else 0)
    _add(heading, "waypointPoiPoint", "0.000000,0.000000,0.000000")
    _add(heading, "waypointHeadingAngleEnable", 1 if turned else 0)
    _add(heading, "waypointHeadingPathMode", "followBadArc")
    _add(heading, "waypointHeadingPoiIndex", 0)
    turn = _add(placemark, "waypointTurnParam")
    _add(turn, "waypointTurnMode", "toPointAndPassWithContinuityCurvature")
    _add(turn, "waypointTurnDampingDist", 0)
    _add(placemark, "useStraightLine", 0)
    pitch = p["pitch"]
    actions = []
    if pitch is not None and (first or pitch != last_pitch):
        actions.append(("gimbal", pitch))
        if first:
            actions.append(("hover", GIMBAL_SETTLE))
    if p["hover"]:
        actions.append(("hover", float(p["hover"])))
    if p["photo"]:
        actions.append(("photo", None))
    if actions:
        group = _add(placemark, "actionGroup")
        _add(group, "actionGroupId", group_id)
        _add(group, "actionGroupStartIndex", i)
        _add(group, "actionGroupEndIndex", i)
        _add(group, "actionGroupMode", "sequence")
        trigger = _add(group, "actionTrigger")
        _add(trigger, "actionTriggerType", "reachPoint")
        for action_id, (kind, value) in enumerate(actions):
            if kind == "gimbal":
                _gimbal_rotate(group, action_id, value)
            elif kind == "hover":
                _simple(group, action_id, "hover", hoverTime=value)
            else:
                _simple(group, action_id, "takePhoto", payloadPositionIndex=0)
    gimbal = _add(placemark, "waypointGimbalHeadingParam")
    _add(gimbal, "waypointGimbalPitchAngle", float(pitch if pitch is not None else last_pitch or 0))
    _add(gimbal, "waypointGimbalYawAngle", 0)
    return bool(actions), pitch if pitch is not None else last_pitch


def _placemarks(folder, points, speed):
    last_pitch, group_id = None, 1
    for i, p in enumerate(points):
        grouped, last_pitch = _placemark(folder, i, p, speed, i == 0, last_pitch, group_id)
        group_id += 1 if grouped else 0


def _xml(root):
    # the prefixes are ElementTree's, shared with wpml.py (whose "wpml" is Pilot 2's namespace): set them each time
    ET.register_namespace("", KML)
    ET.register_namespace("wpml", NS)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8", short_empty_elements=False)


def mission_files(points, s, speed, now_ms, author):
    """(template.kml, waylines.wpml) of one mission"""
    root = ET.Element("{%s}kml" % KML)
    document = ET.SubElement(root, "{%s}Document" % KML)
    _add(document, "author", author)
    _add(document, "createTime", now_ms)
    _add(document, "updateTime", now_ms)
    _mission_config(document, s, speed)
    folder = ET.SubElement(document, "{%s}Folder" % KML)
    _add(folder, "templateType", "waypoint")
    _add(folder, "templateId", 0)
    system = _add(folder, "waylineCoordinateSysParam")
    _add(system, "coordinateMode", "WGS84")
    _add(system, "heightMode", "relativeToStartPoint")
    _add(system, "positioningType", "GPS")
    _add(folder, "autoFlightSpeed", speed)
    _add(folder, "globalHeight", round(float(points[0]["height"]), 1))
    _add(folder, "caliFlightEnable", 0)
    _add(folder, "gimbalPitchMode", "usePointSetting")
    _placemarks(folder, points, speed)
    template = _xml(root)

    root = ET.Element("{%s}kml" % KML)
    document = ET.SubElement(root, "{%s}Document" % KML)
    _mission_config(document, s, speed)
    folder = ET.SubElement(document, "{%s}Folder" % KML)
    _add(folder, "templateId", 0)
    _add(folder, "executeHeightMode", "relativeToStartPoint")
    _add(folder, "waylineId", 0)
    _add(folder, "distance", 0)
    _add(folder, "duration", 0)
    _add(folder, "autoFlightSpeed", speed)
    _placemarks(folder, points, speed)
    return template, _xml(root)


def build(kind, plan, s, now_ms, name, tif=None, speed=None):
    """
    The route as DJI Fly missions: [(file name, kmz bytes), ...], one, or several when it has more than MAX_WAYPOINTS
    points (name_1_of_3.kmz ...).

    :param speed: m/s, the route's flight speed (the plan's when the settings leave it automatic)
    """
    check(kind, s)
    speed = round(float(speed if speed is not None else s.speed or 5.0), 2)
    drone = DRONES[s.model]
    if drone.max_speed is not None:
        speed = min(speed, drone.max_speed)
    parts = split(route_points(kind, plan, s, tif), kind)
    for part in parts:
        if any(not math.isfinite(p["height"]) for p in part):
            raise ExportError("A point's height cannot be worked out")
        low = min(p["height"] for p in part)
        if low < -500:
            raise ExportError("A point lies %d m below the takeoff point" % -low)
    out = []
    for n, part in enumerate(parts, start=1):
        template, waylines = mission_files(part, s, speed, now_ms, name)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("wpmz/template.kml", template)
            z.writestr("wpmz/waylines.wpml", waylines)
        suffix = "" if len(parts) == 1 else "_%d_of_%d" % (n, len(parts))
        out.append((name + suffix + ".kmz", buffer.getvalue()))
    return out


def bundle(files, name):
    """One file to download: the mission itself, or a zip of the missions when the route was split"""
    if len(files) == 1:
        return files[0][1], files[0][0], "application/vnd.google-earth.kmz"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for file_name, data in files:
            z.writestr(file_name, data)
    return buffer.getvalue(), name + ".zip", "application/zip"
