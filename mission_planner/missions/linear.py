"""
Export of a linear route (a strip along a center line: a road, a river, a power line) as a DJI WPML mission (.kmz)
for an aircraft of drones.json, in the format Pilot 2 imports (templateType mappingStrip).

The strip runs leftExtend meters to the left of the center line and rightExtend meters to its right. In single-line
mode the aircraft flies the center line once, high enough for one photo to cover the strip's width; otherwise it flies
back and forth along lines parallel to the center line, spaced for the overlap across them, at the route's height.
Where the center line bends (3 points or more), Pilot 2 adds a pass along the center line with the gimbal tilted to
-45 degrees, from the middle of the segment nearest to where the lines end to the middle of the one at the other end:
this does the same. The structure, the element order and the rules for the values below were taken from linear routes
exported by Pilot 2 (tests/fixtures/dji-kmz: m4t-test-linear-single.kmz and m4t-test-linear-zigzag.kmz). What the two
files share with an area mission (missionConfig, the payload, the start actions) comes from missions/wpml.py.

In AGL a route can fly heights over an embedded DSM in place of the real-time follow (surface_follow "dsm"), written
as an area mission's DSM follow is (wpml.py, after Pilot 2's TestAreaKMZ-*.kmz): there is no linear sample with a DSM,
so it is untested against Pilot 2 and the export says so.

Not built: Pilot 2's cuttingDistance, which splits a long route into several (it is written as Pilot 2's default,
1000 m, and the route is never split).
"""
import io
import math
import time
import zipfile
from collections import namedtuple
from xml.etree import ElementTree as ET

from . import wpml
from .cameras import footprint
from .planning import MAX_HEIGHT, MAX_OVERLAP, MIN_HEIGHT, MIN_OVERLAP, MIN_SHOT_INTERVAL, PlanError, local_transformers
from .wpml import (known, GEOD, HEIGHT_MODES, ExportError, Dsm, action_group, add, asl_heights,
                   check_cameras, check_choices, check_flight, check_realtime_follow, coordinate, is_number, k, kml_root, lens_index,
                   mission_config, simple_action, start_action_group, surface_follow_of, to_xml)
from . import terrain

STOP = "toPointAndStopWithDiscontinuityCurvature"
BEND_PITCH = -45            # the gimbal's pitch on the pass along a bent center line
STOP_BEFORE_END = 0.2       # meters: where the photos of the lines stop before a bend pass, as in Pilot 2's files
# An outside corner of a line is cut by two points, unless they would be closer than this (meters): then one is
# enough. Pilot 2's zigzag sample cuts at 6 m and not at 2.5 m.
MIN_CHAMFER = 4.0
# Seconds Pilot 2 adds to a linear route's duration (both samples: the stops and the hover at the bend pass)
EXTRA_TIME = 6.0
MAX_POINTS = 500

Settings = namedtuple("Settings", "line left_extend right_extend single_line height cameras overlap_h overlap_w speed "
                                  "height_mode takeoff_security_height rth_height finish_action exit_on_rc_lost "
                                  "takeoff_ref_point takeoff_ellipsoidal_height transitional_speed author takeoff_mode "
                                  "elevation_optimize avoid_limit_area model surface_follow")

Plan = namedtuple("Plan", "lines waypoints stop bend spacing interval max_speed distance duration photos")
# lines: the lines flown along the strip, [[(lon, lat), ...], ...], in the order flown (the bend pass is not one)
# waypoints: every point of the route, (lon, lat), lines and bend pass together
# stop: index of the point where the photos of the lines stop before the bend pass; bend: index of the bend pass's
# first point (the end of the last line); both None without a bend pass


def single_line_height(cameras, left_extend, right_extend):
    """The height at which one photo of every camera covers the strip's width"""
    return (left_extend + right_extend) / min(c.sensor_w_mm / c.focal_mm for c in cameras)


def settings(line, cameras, left_extend=50.0, right_extend=50.0, single_line=False, height=100.0, overlap_h=80.0,
             overlap_w=70.0, speed=None, height_mode="relativeToStartPoint", takeoff_security_height=20.0,
             rth_height=100.0, finish_action="goHome", exit_on_rc_lost="goContinue", takeoff_ref_point=None,
             takeoff_ellipsoidal_height=None, transitional_speed=15.0, author=None, takeoff_mode="safe",
             elevation_optimize=True, avoid_limit_area=False, model="m4t", surface_follow=None):
    """
    The settings of the route, checked.

    :param line: the center line, [(lon, lat), ...], at least 2 points
    :param cameras: [Camera, ...], all of them cameras of the model (cameras.CAMERAS_BY_MODEL)
    :param left_extend, right_extend: meters the strip reaches to the left and to the right of the center line
    :param single_line: fly the center line once; the height is then the one that covers the strip
        (single_line_height) and `height` is ignored
    :param height: meters, in the height mode (wpml.HEIGHT_MODES, as for an area)
    :param speed: m/s; None for the fastest speed the photos allow (Plan.max_speed)
    :param takeoff_ref_point: (lat, lon, altitude) of the takeoff point, as for an area (wpml.settings)
    :param surface_follow: in AGL, "realtime" or "dsm" (heights over an embedded DSM: build_kmz needs the terrain);
        None: the model's default (wpml.surface_follow_of)
    """
    check_choices(model, takeoff_mode, finish_action, exit_on_rc_lost)
    for name, value in (("elevation optimization", elevation_optimize), ("geo zone bypassing", avoid_limit_area),
                        ("single line", single_line)):
        if not isinstance(value, bool):
            raise ExportError("The %s must be on or off" % name)
    if not known(height_mode, HEIGHT_MODES):
        raise ExportError("Unknown height mode %r" % (height_mode,))
    surface_follow = surface_follow_of(model, surface_follow)
    if height_mode == "realTimeFollowSurface":
        check_realtime_follow(model, surface_follow)
    if height_mode == "EGM96":
        if takeoff_ref_point is None:
            raise ExportError("The ASL height mode needs the ground height at the takeoff point")
        if not is_number(takeoff_ellipsoidal_height):
            raise ExportError("The ASL height mode needs the ellipsoidal ground height at the takeoff point")
    elif takeoff_ellipsoidal_height is not None:
        raise ExportError("The ellipsoidal ground height only applies when height_mode is \"EGM96\"")
    check_flight(takeoff_security_height, rth_height, speed, transitional_speed, takeoff_ref_point)
    check_cameras(model, cameras, optional=True)

    # What the planner checks for an area (planning.check_inputs), with the same messages
    if not cameras:
        raise PlanError("Choose at least one camera")
    if not (2 <= len(line) <= MAX_POINTS) or any(len(p) < 2 or not all(is_number(v) for v in p[:2]) for p in line):
        raise PlanError("The center line needs between 2 and %d points" % MAX_POINTS)
    if not (is_number(left_extend) and is_number(right_extend) and left_extend >= 0 and right_extend >= 0):
        raise PlanError("The strip's widths to the left and to the right of the center line cannot be negative")
    if left_extend + right_extend <= 0:
        raise PlanError("The strip needs a width")
    if single_line:
        height = single_line_height(cameras, left_extend, right_extend)
    if not (is_number(height) and MIN_HEIGHT <= height <= MAX_HEIGHT):
        raise PlanError("The height must be between %g and %g meters" % (MIN_HEIGHT, MAX_HEIGHT))
    for name, value in (("along", overlap_h), ("across", overlap_w)):
        if not (is_number(value) and MIN_OVERLAP <= value <= MAX_OVERLAP):
            raise PlanError("The overlap %s the lines must be between %g and %g%%" % (name, MIN_OVERLAP, MAX_OVERLAP))

    return Settings(line=[(float(p[0]), float(p[1])) for p in line], left_extend=float(left_extend),
                    right_extend=float(right_extend), single_line=single_line, height=float(height),
                    cameras=list(cameras), overlap_h=float(overlap_h), overlap_w=float(overlap_w),
                    speed=None if speed is None else float(speed), height_mode=height_mode,
                    takeoff_security_height=float(takeoff_security_height), rth_height=float(rth_height),
                    finish_action=finish_action, exit_on_rc_lost=exit_on_rc_lost,
                    takeoff_ref_point=None if takeoff_ref_point is None else tuple(float(v) for v in takeoff_ref_point),
                    takeoff_ellipsoidal_height=None if takeoff_ellipsoidal_height is None else float(takeoff_ellipsoidal_height),
                    transitional_speed=float(transitional_speed), author=author, takeoff_mode=takeoff_mode,
                    elevation_optimize=elevation_optimize, avoid_limit_area=avoid_limit_area, model=model,
                    surface_follow=surface_follow)


def uses_dsm(s):
    """Whether the route flies heights over an embedded DSM, not the aircraft's real-time follow"""
    return s.height_mode == "realTimeFollowSurface" and s.surface_follow == "dsm"


# -- The plan ----------------------------------------------------------------------------------------------------

def unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return dx / length, dy / length


def left_normal(u):
    return -u[1], u[0]


# 1 + cos(turn) below which the inside corner is not mitred: a turn of about 150 degrees, the miter 3.9 times the offset
MAX_TURN = math.radians(150)
MITER_LIMIT = 1.0 + math.cos(MAX_TURN)


def offset_line(center, directions, d):
    """The line `d` meters to the left of the center line (to the right when d < 0), in meters. Inside a bend the
    two offset segments meet at a point; outside it the corner is cut by two points, as Pilot 2 does."""
    def shifted(p, u, f=1.0):
        n = left_normal(u)
        return p[0] + f * d * n[0], p[1] + f * d * n[1]

    points = [shifted(center[0], directions[0])]
    for v, a, b in zip(center[1:-1], directions, directions[1:]):
        cross = a[0] * b[1] - a[1] * b[0]
        dot = a[0] * b[0] + a[1] * b[1]
        if abs(cross) < 1e-9 and dot > 0:
            continue                                    # no bend
        if d * cross >= 0:
            if 1.0 + dot < MITER_LIMIT:
                # inside a turn sharper than about 150 degrees (or a line that doubles back): the ends of the two
                # offset segments, as the point where they cross runs off far from the line (or does not exist)
                points.extend([shifted(v, a), shifted(v, b)])
                continue
            # inside: where the two offset segments cross
            na, nb = left_normal(a), left_normal(b)
            f = d / (1.0 + dot)
            points.append((v[0] + f * (na[0] + nb[0]), v[1] + f * (na[1] + nb[1])))
            continue
        # outside: halfway between the ends of the offset segments and the point where they would meet
        # (the turn taken as at most 150 degrees: past it the corner would run off far from the line)
        t = abs(d) * math.tan(min(math.atan2(abs(cross), dot), MAX_TURN) / 2.0) / 2.0
        c1 = shifted(v, a)
        c1 = c1[0] + a[0] * t, c1[1] + a[1] * t
        c2 = shifted(v, b)
        c2 = c2[0] - b[0] * t, c2[1] - b[1] * t
        points.extend([c1] if math.hypot(c2[0] - c1[0], c2[1] - c1[1]) < MIN_CHAMFER else [c1, c2])
    points.append(shifted(center[-1], directions[-1]))
    return points


def spacing_of(s):
    across = min(footprint(c, s.height)[0] for c in s.cameras)
    return across * (1.0 - s.overlap_w / 100.0)


def interval_of(s):
    along = min(footprint(c, s.height)[1] for c in s.cameras)
    return along * (1.0 - s.overlap_h / 100.0)


speed_of = wpml.route_speed


def leg_lengths(points):
    return [GEOD.inv(a[0], a[1], b[0], b[1])[2] for a, b in zip(points, points[1:])]


def plan(s):
    """The lines and the waypoints of the route"""
    # A frame centered on the middle of the center line's extent
    lons, lats = [p[0] for p in s.line], [p[1] for p in s.line]
    to_metric, to_lonlat = local_transformers((min(lons) + max(lons)) / 2.0, (min(lats) + max(lats)) / 2.0)
    center = [to_metric.transform(lon, lat) for lon, lat in s.line]
    center = [p for i, p in enumerate(center) if i == 0 or math.hypot(p[0] - center[i - 1][0], p[1] - center[i - 1][1]) > 1e-6]
    if len(center) < 2:
        raise PlanError("The center line needs between 2 and %d points" % MAX_POINTS)
    directions = [unit(a, b) for a, b in zip(center, center[1:])]

    spacing = spacing_of(s)
    width = s.left_extend + s.right_extend
    n = 1 if s.single_line else math.ceil(width / spacing - 1e-9) + 1
    shift = 0.0 if s.single_line else (s.left_extend - s.right_extend) / 2.0
    # line 0 is the leftmost, flown along the center line; the next one back, and so on
    lines = []
    for i in range(n):
        line = offset_line(center, directions, (n - 1) / 2.0 * spacing - i * spacing + shift)
        lines.append(line[::-1] if i % 2 else line)

    waypoints = [p for line in lines for p in line]
    stop = bend = None
    if len(center) >= 3:
        # The photos of the lines stop just before the end, the aircraft tilts the gimbal there and flies the center
        # line from the middle of the segment nearest to it to the middle of the one at the other end
        end, before = waypoints[-1], waypoints[-2]
        u = unit(before, end)
        waypoints[-1:] = [(end[0] - u[0] * STOP_BEFORE_END, end[1] - u[1] * STOP_BEFORE_END), end]
        stop, bend = len(waypoints) - 2, len(waypoints) - 1
        middles = [((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0) for a, b in zip(center, center[1:])]
        along = [middles[0]] + center[1:-1] + [middles[-1]]
        waypoints.extend(along if (n - 1) % 2 else along[::-1])

    lonlat = [tuple(to_lonlat.transform(x, y)) for x, y in waypoints]
    lines_lonlat = [[tuple(to_lonlat.transform(x, y)) for x, y in line] for line in lines]
    interval = interval_of(s)
    distance = sum(leg_lengths(lonlat))
    shooting = [lonlat[:(len(lonlat) if stop is None else stop + 1)]] + ([] if bend is None else [lonlat[bend:]])
    photos = sum(int(sum(leg_lengths(part)) // interval) + 1 for part in shooting)
    p = Plan(lines=lines_lonlat, waypoints=lonlat, stop=stop, bend=bend, spacing=spacing, interval=interval,
             max_speed=interval / MIN_SHOT_INTERVAL, distance=distance, duration=None, photos=photos)
    return p._replace(duration=distance / speed_of(p, s) + EXTRA_TIME)


# -- XML ---------------------------------------------------------------------------------------------------------

def template_kml(p, s, now_ms, dsm=None):
    root, document = kml_root()
    if s.author:
        add(document, "author", s.author)
    add(document, "createTime", now_ms)
    add(document, "updateTime", now_ms)
    mission_config(document, s, template=True, reroute=False, dsm=dsm)

    folder = ET.SubElement(document, k("Folder"))
    add(folder, "templateType", "mappingStrip")
    add(folder, "templateId", 0)
    system = add(folder, "waylineCoordinateSysParam")
    add(system, "coordinateMode", "WGS84")
    # Over a DSM as an area mission's (wpml.template_kml)
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
    add(folder, "autoFlightSpeed", speed_of(p, s))

    placemark = ET.SubElement(folder, k("Placemark"))
    for tag, value in (("caliFlightEnable", 0), ("elevationOptimizeEnable", 1 if s.elevation_optimize else 0),
                       ("quickOrthoMappingEnable", 0), ("shootType", "distance"), ("direction", 0),
                       ("singleLineEnable", 1 if s.single_line else 0), ("cuttingDistance", 1000),
                       ("boundaryOptimEnable", 1), ("leftExtend", s.left_extend), ("rightExtend", s.right_extend),
                       ("includeCenterEnable", 0), ("efficiencyFlightModeEnable", 0)):
        add(placemark, tag, value)
    overlap = add(placemark, "overlap")
    add(overlap, "orthoCameraOverlapH", s.overlap_h)
    add(overlap, "orthoCameraOverlapW", s.overlap_w)
    ET.SubElement(ET.SubElement(placemark, k("LineString")), k("coordinates")).text = "\n" + "\n".join(
        "            %s,%s,0" % (coordinate(lon), coordinate(lat)) for lon, lat in s.line) + "\n          "
    height, ellipsoid_height = asl_heights(s) if s.height_mode == "EGM96" else (s.height, s.height)
    add(placemark, "ellipsoidHeight", ellipsoid_height)
    add(placemark, "height", height)
    add(placemark, "stripMergedRegions", "[]")
    add(placemark, "stripUseTemplateAltitude", 0)

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


def start_shooting(placemark, s, group_id, first, last, interval, pitch):
    """Photos every `interval` meters from point `first` to point `last`, with the gimbal at `pitch` and kept there"""
    group = action_group(placemark, group_id, first, last, "multipleDistance", interval)
    wpml.gimbal_rotate(group, 0, pitch)
    simple_action(group, 1, "startContinuousShooting", payloadPositionIndex=0, useGlobalPayloadLensIndex=0,
                  payloadLensIndex=lens_index(s))


def lock_gimbal(placemark, group_id, first, last):
    group = action_group(placemark, group_id, first, last, "betweenAdjacentPoints")
    simple_action(group, 0, "gimbalAngleLock", payloadPositionIndex=0)


def stop_shooting(placemark, s, group_id, i):
    group = action_group(placemark, group_id, i, i, "reachPoint")
    simple_action(group, 0, "stopContinuousShooting", payloadPositionIndex=0, payloadLensIndex=lens_index(s))
    simple_action(group, 1, "gimbalAngleUnlock")


def waylines_wpml(p, s, dsm=None):
    root, document = kml_root()
    mission_config(document, s, template=False, reroute=False)

    speed = speed_of(p, s)
    folder = ET.SubElement(document, k("Folder"))
    add(folder, "templateId", 0)
    add(folder, "executeHeightMode", "WGS84" if s.height_mode == "EGM96" or dsm else s.height_mode)
    add(folder, "waylineId", 0)
    add(folder, "distance", p.distance)
    add(folder, "duration", p.duration)
    add(folder, "autoFlightSpeed", speed)
    start_action_group(folder, -90)
    add(folder, "realTimeFollowSurfaceByFov", 0)

    execute_height = asl_heights(s)[1] if s.height_mode == "EGM96" else s.height
    points = p.waypoints
    last = len(points) - 1
    lines_end = last if p.bend is None else p.bend
    lengths = leg_lengths(points)
    for i, (lon, lat) in enumerate(points):
        placemark = ET.SubElement(folder, k("Placemark"))
        ET.SubElement(ET.SubElement(placemark, k("Point")), k("coordinates")).text = \
            "\n            %s,%s\n          " % (coordinate(lon), coordinate(lat))
        add(placemark, "index", i)
        add(placemark, "executeHeight", dsm.heights[0][i] if dsm else execute_height)
        add(placemark, "waypointSpeed", speed)

        h = add(placemark, "waypointHeadingParam")
        heading = GEOD.inv(lon, lat, points[i + 1][0], points[i + 1][1])[0] if i < last else 0.0
        add(h, "waypointHeadingMode", "followWayline")
        add(h, "waypointHeadingAngle", round(heading, 9))
        add(h, "waypointPoiPoint", "0.000000,0.000000,0.000000")
        add(h, "waypointHeadingAngleEnable", 1 if i < last else 0)
        add(h, "waypointHeadingPathMode", "followBadArc")
        add(h, "waypointHeadingPoiIndex", 0)

        # The ends of the route and of the lines' photos stop; elsewhere the aircraft rounds the corner, starting to
        # turn a third of the shorter leg before it
        turn = add(placemark, "waypointTurnParam")
        stops = i in (0, last, p.stop, p.bend)
        add(turn, "waypointTurnMode", STOP if stops else "coordinateTurn")
        add(turn, "waypointTurnDampingDist", 0 if stops else round(min(lengths[i - 1], lengths[i]) / 3.0, 9))
        add(placemark, "useStraightLine", 1)

        if i == 0:
            lock_gimbal(placemark, 0, 0, lines_end)
            start_shooting(placemark, s, 1, 0, lines_end, p.interval, -90)
        if i == (last if p.stop is None else p.stop):
            stop_shooting(placemark, s, 2, i)
        if i == p.bend:
            group = action_group(placemark, 3, i, i, "reachPoint")
            wpml.gimbal_rotate(group, 0, BEND_PITCH)
            simple_action(group, 1, "hover", hoverTime=0.5)
            start_shooting(placemark, s, 4, i, last, p.interval, BEND_PITCH)
            lock_gimbal(placemark, 5, i, last)
        if p.bend is not None and i == last:
            stop_shooting(placemark, s, 6, i)

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
    if uses_dsm(s):
        warnings.append(wpml.terrain_warning())
        warnings.append("The DSM follow of a linear route has not been checked against a file from Pilot 2: check the "
                        "route in Pilot 2 before flying")
    if s.height_mode == "relativeToStartPoint":
        warnings.append("The height is measured from the takeoff point: the aircraft will not follow the terrain")
    elif s.height_mode == "EGM96":
        warnings.append("The height is measured above sea level, from public elevation data that can differ from "
                        "the real ground by a few meters: check the height before flying")
    if s.rth_height < s.height + 10:
        warnings.append("The return height (%g m) is not well above the flight height (%g m)" % (s.rth_height, s.height))
    return warnings


def terrain_points(p, s):
    """The (lon, lat) points the terrain must cover for the route: its waypoints, center line and takeoff point"""
    points = list(p.waypoints) + list(s.line)
    if s.takeoff_ref_point is not None:
        points.append((s.takeoff_ref_point[1], s.takeoff_ref_point[0]))
    return points


def dsm_of(p, s, tif, name):
    """The Dsm of the route: each waypoint flies `s.height` above its ground (terrain.flown_ground_heights: along its
    legs over a lidar terrain, else the highest within terrain.RADIUS of it)"""
    try:
        heights = [[round(g + s.height, 3) for g in terrain.flown_ground_heights(tif, p.waypoints, name)]]
        takeoff = None
        if s.takeoff_ref_point is not None:
            lat, lon = s.takeoff_ref_point[:2]
            takeoff = (lat, lon, terrain.ground_at(tif, lon, lat))
    except terrain.TerrainError as e:
        raise ExportError(str(e))
    return Dsm(path="wpmz/res/dsm/" + name, content=tif, heights=heights, start=None, takeoff=takeoff)


def build_kmz(p, s, now=None, dsm=None):
    """
    The route as the bytes of a .kmz file.

    :param p: plan(s)
    :param s: settings(...)
    :param now: time.time() at creation, for repeatable output (default: now)
    :param dsm: the (GeoTIFF bytes, name) of the terrain (missions.terrain), required when uses_dsm(s)
    """
    if uses_dsm(s) and dsm is None:
        raise ExportError("AGL over the terrain needs the terrain under the route")
    dsm = dsm_of(p, s, *dsm) if uses_dsm(s) else None
    now_ms = int(round((time.time() if now is None else now) * 1000))
    files = [("wpmz/template.kml", template_kml(p, s, now_ms, dsm)), ("wpmz/waylines.wpml", waylines_wpml(p, s, dsm))]
    if dsm:
        files.append((dsm.path, dsm.content))

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))     # same bytes for the same route
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, content)
    return out.getvalue()
