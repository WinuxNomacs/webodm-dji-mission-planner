"""
Export of a geometric route (a building or other block, mapped all round: an outline extruded upwards, a prism) as a
DJI WPML mission (.kmz) for an aircraft of drones.json, in the format Pilot 2 imports (templateType mappingPrism).

The block is the outline drawn on the map, with the height of its base and of its top. The aircraft flies level loops
round it, `height` meters out from its walls, from just under the top down to just above the base, the loops as far
apart as the overlap between them asks and flown back and forth; the gimbal is level and the aircraft faces the wall.
Before the walls it maps the roof (Pilot 2's top face, unless turned off) from `height` meters above the top, with
Smart Oblique. The structure, the element order and the rules for the values below were taken from a geometric route
exported by Pilot 2 (tests/fixtures/dji-kmz/m4t-test-geo.kmz), whose walls this reproduces to a few centimeters and
its roof to a few tens. What it shares with an area mission (missionConfig, the payload, the start actions) comes
from missions/wpml.py.

The roof is flown in straight lines, back and forth, along the whole degree across which the outline is narrowest,
from the end of the outermost line nearest the outline's first corner. On each stretch of a line the gimbal cycles
through the poses (POSES: straight down, and 30 degrees off it forwards and backwards, 45 degrees to each side) that
see the roof there, the aircraft slowing down for each pose more (POSE_TIME); a pose sees the roof while the center
of its view is within SEEN of half a photo's width from the roof's outline, the center VIEW_OUT out. The line is cut
where the set of poses changes (changes closer than MERGE made at the later one), and runs on RUN_ON meters past the
first and the last change, as Pilot 2's do. SEEN, VIEW_OUT and MERGE were fitted to the sample's 32 lines, one
height and one camera: its pose changes are reproduced within 33 cm (6 cm on average).

Each loop follows the outline offset by `height` with bevelled corners (GEOS's bevel join): the aircraft turns at each
corner of that offset outline (coordinateTurn), and passes a point a third of the shorter side before and after it
(toPointAndPassWithContinuityCurvature), which rounds the turn. A loop starts at a corner of the offset outline and
ends SEAM meters before it, where the aircraft drops to the next loop and flies it the other way.

Pilot 2 converts its offsets to longitude and latitude on a sphere, so its 6.2 m from the walls are 6.19 to 6.25 m;
the route here keeps the true distance.

Heights: the base and the top, and the waypoints' executeHeight, are WGS84-ellipsoidal, as in a slope route
(missions/slope.py).
"""
import io
import math
import time
import zipfile
from collections import namedtuple
from xml.etree import ElementTree as ET

import numpy as np
from django.contrib.gis.geos import LineString, Polygon
from pyproj import Transformer

from . import wpml
from .cameras import footprint
from .planning import MAX_HEIGHT, MAX_OVERLAP, MIN_HEIGHT, MIN_OVERLAP, MIN_SHOT_INTERVAL, PlanError
from .slope import MAX_CORNERS, STOP
from .wpml import (ExportError, action_group, add, check_cameras, check_choices, check_flight,
                   coordinate, is_number, k, kml_root, lens_index, mission_config, simple_action, start_action_group, to_xml)

PASS = "toPointAndPassWithContinuityCurvature"
SEAM = 0.5                  # meters before its first corner that a loop ends (Pilot 2's sample)
MAX_BLOCK = 500.0           # meters from the base to the top
MIN_BLOCK = 0.5
CLOSE = 0.6                 # a route closer to the outline than this share of the distance is warned about

# The roof's poses, Pilot 2's (gimbal pitch, yaw from the heading) in its order: straight down, then forwards to the
# left, backwards to the left, backwards to the right and forwards to the right (-120 is past straight down, backwards)
POSES = ((-90, 0), (-60, -45), (-120, -45), (-120, 45), (-60, 45))
RUN_ON = 30.0               # meters a roof line runs on past its first and its last pose change
MERGE = 0.9                 # pose changes closer than this along a line are made at the later one
SEEN = 1.019                # a pose sees the roof while its view's center is within this many half photo widths of it
VIEW_OUT = 0.6174           # the center of an oblique view is this many times the height out from the aircraft
STAY = 1.001                # seconds per photo with one pose (Pilot 2's smartObliqueStayTime)
POSE_TIME = 0.6             # seconds per pose when the gimbal cycles through several
BATTERY = 40 * 60           # seconds of flying on one battery, with a margin

Settings = namedtuple("Settings", "outline base top height cameras overlap_h overlap_w speed takeoff_security_height "
                                  "rth_height finish_action exit_on_rc_lost takeoff_ref_point transitional_speed author "
                                  "takeoff_mode avoid_limit_area model roof")

Plan = namedtuple("Plan", "loops waypoints kinds headings dampings legs spacing interval max_speed distance duration "
                          "photos closest profile roof roof_points poses speeds roof_speed roof_photos")
# loops: the loops flown round the block, [[(lon, lat, h), ...], ...], in the order flown
# waypoints: every point of the route, (lon, lat, h), h WGS84-ellipsoidal; kinds: each point's "corner" (where the
# aircraft turns), "pass" (rounding a corner), "seam" (where a loop ends and the next starts) or "stop" (the first and
# the last); headings: the bearing each faces; dampings: how far before each corner the turn starts; legs: the 3D
# meters between the points
# closest: the least meters from the outline to the route, on the level
# profile: the route seen from the side, {"face": the wall's top and bottom, "lines": each loop, "roof": the roof's
# lines from the wall inwards, or None}, each as [out, h], `out` the meters out from the wall, h WGS84-ellipsoidal
# roof: the lines flown over the roof, [[(lon, lat, h), ...], ...], the run-ons included ([] when the roof is not flown);
# roof_points: how many of the waypoints are the roof's (they come first: its lines, then a point over the walls' start)
# poses: for each of those, the poses (POSES) of the stretch from it to the next, () for none; speeds: the speed there
# roof_speed: the roof's speed with one pose or none; roof_photos: the photos taken over the roof


def settings(outline, base, top, cameras, height=10.0, overlap_h=80.0, overlap_w=80.0, speed=None,
             takeoff_security_height=20.0, rth_height=100.0, finish_action="goHome", exit_on_rc_lost="goContinue",
             takeoff_ref_point=None, transitional_speed=15.0, author=None, takeoff_mode="safe", avoid_limit_area=False,
             model="m4t", roof=True):
    """
    The settings of the route, checked.

    :param outline: the block's outline, [(lon, lat), ...], at least 3 corners
    :param base: the height of its base, top: of its top, WGS84-ellipsoidal meters
    :param cameras: [Camera, ...], all of them cameras of the model (cameras.CAMERAS_BY_MODEL)
    :param height: meters flown out from the walls
    :param speed: m/s; None for the fastest speed the photos allow (Plan.max_speed)
    :param takeoff_ref_point: (lat, lon, altitude) of the takeoff point, as for an area (wpml.settings)
    :param roof: whether the roof is mapped too, from `height` meters above the top
    """
    check_choices(model, takeoff_mode, finish_action, exit_on_rc_lost)
    if not isinstance(avoid_limit_area, bool):
        raise ExportError("The geo zone bypassing must be on or off")
    if not isinstance(roof, bool):
        raise ExportError("Mapping the roof must be on or off")
    check_flight(takeoff_security_height, rth_height, speed, transitional_speed, takeoff_ref_point)
    check_cameras(model, cameras, optional=True)

    if not cameras:
        raise PlanError("Choose at least one camera")
    if not (3 <= len(outline) <= MAX_CORNERS) or any(len(c) != 2 or not all(is_number(v) for v in c) for c in outline):
        raise PlanError("The outline needs between 3 and %d corners" % MAX_CORNERS)
    if not (is_number(base) and is_number(top)):
        raise PlanError("Give the heights of the base and of the top")
    if not MIN_BLOCK <= top - base <= MAX_BLOCK:
        raise PlanError("The top must be between %g and %g meters above the base" % (MIN_BLOCK, MAX_BLOCK))
    if not (is_number(height) and MIN_HEIGHT <= height <= MAX_HEIGHT):
        raise PlanError("The distance from the walls must be between %g and %g meters" % (MIN_HEIGHT, MAX_HEIGHT))
    for name, value in (("along", overlap_h), ("between", overlap_w)):
        if not (is_number(value) and MIN_OVERLAP <= value <= MAX_OVERLAP):
            raise PlanError("The overlap %s the loops must be between %g and %g%%" % (name, MIN_OVERLAP, MAX_OVERLAP))

    return Settings(outline=[tuple(float(v) for v in c) for c in outline], base=float(base), top=float(top),
                    height=float(height), cameras=list(cameras), overlap_h=float(overlap_h), overlap_w=float(overlap_w),
                    speed=None if speed is None else float(speed),
                    takeoff_security_height=float(takeoff_security_height), rth_height=float(rth_height),
                    finish_action=finish_action, exit_on_rc_lost=exit_on_rc_lost,
                    takeoff_ref_point=None if takeoff_ref_point is None else tuple(float(v) for v in takeoff_ref_point),
                    transitional_speed=float(transitional_speed), author=author, takeoff_mode=takeoff_mode,
                    avoid_limit_area=avoid_limit_area, model=model, roof=roof)


# -- The plan ----------------------------------------------------------------------------------------------------

def spacing_of(s):
    """Between the loops: the photos' height (they are taken landscape, the gimbal level)"""
    return min(footprint(c, s.height)[1] for c in s.cameras) * (1.0 - s.overlap_w / 100.0)


def interval_of(s):
    """Between the photos, along a loop: the photos' width"""
    return min(footprint(c, s.height)[0] for c in s.cameras) * (1.0 - s.overlap_h / 100.0)


speed_of = wpml.route_speed


def loop_heights(s, spacing):
    """The loops' heights, from the top down, centered between the base and the top"""
    count = max(1, int(math.floor((s.top - s.base) / spacing + 1e-9)))
    first = s.top - ((s.top - s.base) - (count - 1) * spacing) / 2.0
    return [first - i * spacing for i in range(count)]


def frame(s):
    """(to_lonlat, outline): an azimuthal equidistant projection on the outline's middle, and the outline in it"""
    lon0 = sum(c[0] for c in s.outline) / len(s.outline)
    lat0 = sum(c[1] for c in s.outline) / len(s.outline)
    proj = "+proj=aeqd +lat_0=%r +lon_0=%r +ellps=WGS84" % (lat0, lon0)
    to_metric = Transformer.from_crs(4326, proj, always_xy=True)
    to_lonlat = Transformer.from_crs(proj, 4326, always_xy=True)
    return to_lonlat, np.array([to_metric.transform(lon, lat) for lon, lat in s.outline])


def unit(v):
    return v / np.linalg.norm(v)


def cross(a, b):
    return float(a[0] * b[1] - a[1] * b[0])


def facing(a, b):
    """The bearing towards the block from the side a -> b of the offset outline (counterclockwise: the block on the left)"""
    d = b - a
    return math.degrees(math.atan2(-d[1], d[0]))


def between(a, b):
    """The bearing halfway from a to b, the short way round"""
    return wpml.signed_degrees(a + wpml.signed_degrees(b - a) / 2.0)


def offset_ring(s, outline):
    """The corners of the outline offset by the distance from the walls, bevelled, counterclockwise from the one at the
    end of the outline's first side"""
    polygon = Polygon([tuple(p) for p in outline] + [tuple(outline[0])])
    if not polygon.valid:
        raise PlanError("The outline crosses itself")
    if polygon.area < 1.0:
        raise PlanError("The outline is too small")
    ring = np.array(polygon.buffer_with_style(s.height, end_cap_style=1, join_style=3).exterior_ring.coords[:-1])

    # Leaving out repeated corners (within a centimeter of the one before) and those in a line with their neighbours
    kept = []
    for p in ring:
        if not kept or np.linalg.norm(p - kept[-1]) > 0.01:
            kept.append(p)
    if len(kept) > 1 and np.linalg.norm(kept[0] - kept[-1]) <= 0.01:
        kept.pop()
    ring = [p for i, p in enumerate(kept)
            if abs(cross(unit(p - kept[i - 1]), unit(kept[(i + 1) % len(kept)] - p))) > 1e-4]
    if len(ring) < 3:
        raise PlanError("The outline is too small")
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))
    if area < 0:
        ring = ring[::-1]

    a, b = outline[0], outline[1]
    d = unit(b - a)
    side = 1.0 if sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(outline, np.roll(outline, -1, axis=0))) < 0 else -1.0
    start = b + s.height * side * np.array([-d[1], d[0]])
    first = min(range(len(ring)), key=lambda i: np.linalg.norm(ring[i] - start))
    return ring[first:] + ring[:first]


def loop_points(ring, damping):
    """
    One loop's points in the plane: (forward, backward), each [(point, kind, heading, damping), ...] without its ends,
    the ends, ((point, heading) of the start, of the end of a forward loop = the start of a backward one, of the end of
    a backward loop), and the route's last point after a forward loop and after a backward one
    """
    m = len(ring)
    lengths = [float(np.linalg.norm(ring[(i + 1) % m] - ring[i])) for i in range(m)]
    facings = [facing(ring[i], ring[(i + 1) % m]) for i in range(m)]
    seam = min(SEAM, lengths[-1] / 4.0)
    room = list(lengths)
    room[-1] = max(lengths[-1] - seam - damping, 0.0)

    # Each corner but the first, with a point a third of its shorter side before and after it; none on the last side,
    # where the loop ends
    inner = []
    for i in range(1, m):
        d = min(room[i - 1], room[i]) / 3.0
        before, after = unit(ring[i] - ring[i - 1]), unit(ring[(i + 1) % m] - ring[i])
        # Facing halfway between the two sides, but at an inner corner of the block (where the loop turns away from it)
        # the way the side before faces, as Pilot 2 writes it
        concave = cross(before, after) < 0
        inner.append((ring[i] - d * before, "pass", facings[i - 1], 0.0))
        inner.append((ring[i], "corner", facings[i - 1] if concave else between(facings[i - 1], facings[i]), d))
        if i < m - 1:
            inner.append((ring[i] + d * after, "pass", facings[i], 0.0))

    v0 = ring[0]
    forward_end = v0 - seam * unit(v0 - ring[-1])
    first_side = unit(ring[1] - v0)
    backward_end = v0 + float((forward_end - v0) @ first_side) * first_side
    # The route's last point, where the turn at the end of its last loop would have started
    last = (forward_end - damping * unit(v0 - ring[-1]), backward_end + damping * first_side)
    ends = ((v0, facings[0]), (forward_end, facings[-1]), (backward_end, facings[0]))
    backward = [(p, kind, h, d) for p, kind, h, d in reversed(inner)]
    return inner, backward, ends, last


def roof_spacing_of(s):
    """Between the roof's lines: the photos' width, as over an area"""
    return min(footprint(c, s.height)[0] for c in s.cameras) * (1.0 - s.overlap_w / 100.0)


def roof_interval_of(s):
    """Between the photos of one pose along a roof line: the photos' height"""
    return min(footprint(c, s.height)[1] for c in s.cameras) * (1.0 - s.overlap_h / 100.0)


def roof_direction(outline):
    """The bearing of the roof's lines: the whole degree across which the outline is narrowest"""
    def width(bearing):
        t = math.radians(bearing)
        across = outline @ np.array([math.cos(t), -math.sin(t)])
        return round(float(across.max() - across.min()), 9)
    return min(range(180), key=lambda b: (width(b), b))


def view_offset(heading, pose, out):
    """Where the center of a pose's view is, from an aircraft flying `heading`: (east, north) meters"""
    pitch, yaw = pose
    if pitch == -90:
        return np.zeros(2)
    bearing = math.radians(heading + yaw + (180 if pitch == -120 else 0))
    return out * np.array([math.sin(bearing), math.cos(bearing)])


def pieces(geometry):
    """The lines of the intersection of a polygon and a line"""
    if geometry.empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    return [g for g in geometry if g.geom_type == "LineString"] if geometry.geom_type in ("MultiLineString", "GeometryCollection") else []


def roof_lines(s, outline):
    """
    The lines flown over the roof, in the plane, in the order flown: [[(point, poses), ...], ...], `poses` those of the
    stretch from that point to the next (POSES, () for none)
    """
    bearing = roof_direction(outline)
    t = math.radians(bearing)
    u, n = np.array([math.sin(t), math.cos(t)]), np.array([math.cos(t), -math.sin(t)])
    along, across = outline @ u, outline @ n
    spacing = roof_spacing_of(s)
    seen = SEEN * min(footprint(c, s.height)[0] for c in s.cameras) / 2.0
    out = VIEW_OUT * s.height
    reach = out * math.sqrt(0.5) + seen

    # As many lines as see the roof, centered on it, from the side and the end nearest the outline's first corner
    count = int(math.floor((across.max() - across.min() + 2 * reach) / spacing + 1e-9)) + 1
    middle = (across.max() + across.min()) / 2.0
    offsets = [middle + (i - (count - 1) / 2.0) * spacing for i in range(count)]
    if across[0] - across.min() > across.max() - across[0]:
        offsets.reverse()
    direction = -1.0 if along.max() - along[0] < along[0] - along.min() else 1.0

    seen_area = Polygon([tuple(p) for p in outline] + [tuple(outline[0])]).buffer(seen, quadsegs=32)
    far = float(np.abs(along).max()) + out + seen + 1.0
    lines = []
    for offset in offsets:
        heading = bearing if direction > 0 else bearing + 180
        # Where along the line each pose sees the roof: [(from, to), ...]
        spans = {}
        for pose in POSES:
            center = offset * n + view_offset(heading, pose, out)
            cut = seen_area.intersection(LineString([tuple(center - far * u), tuple(center + far * u)]))
            spans[pose] = [sorted(float((np.array(q) - center) @ u) for q in (g.coords[0], g.coords[-1])) for g in pieces(cut)]
        changes = sorted({x for span in spans.values() for piece in span for x in piece}, key=lambda x: direction * x)
        if not changes:
            continue
        groups = []
        for x in changes:
            if groups and direction * (x - groups[-1][-1]) < MERGE:
                groups[-1].append(x)
            else:
                groups.append([x])
        at = [g[-1] for g in groups]
        stretches = [tuple(p for p in POSES if any(lo <= (a + b) / 2.0 <= hi for lo, hi in spans[p]))
                     for a, b in zip(at, at[1:])]
        xs = [at[0] - direction * RUN_ON] + at + [at[-1] + direction * RUN_ON]
        lines.append([(offset * n + x * u, poses) for x, poses in zip(xs, [()] + stretches + [(), ()])])
        direction = -direction
    return lines


def plan(s):
    """The loops and the waypoints of the route"""
    to_lonlat, outline = frame(s)
    spacing = spacing_of(s)
    heights = loop_heights(s, spacing)
    ring = offset_ring(s, outline)
    seam_damping = spacing / 2.0
    forward, backward, (start, forward_end, backward_end), last = loop_points(ring, seam_damping)

    # (x, y, h, kind, heading, damping), loop by loop: the first from the start, then back and forth
    points, loops = [], []
    for i, h in enumerate(heights):
        if i % 2 == 0:
            first = start if i == 0 else backward_end
            loop = [(first[0], "seam", first[1], seam_damping)] + forward + [(forward_end[0], "seam", forward_end[1], seam_damping)]
        else:
            loop = ([(forward_end[0], "seam", forward_end[1], seam_damping)] + backward +
                    [(backward_end[0], "seam", backward_end[1], seam_damping)])
        rows = [(float(p[0]), float(p[1]), h, kind, heading, d) for p, kind, heading, d in loop]
        loops.append(rows)
        points.extend(rows)
    end = last[(len(heights) - 1) % 2]
    points[0] = points[0][:3] + ("stop", points[0][4], 0.0)
    points[-1] = (float(end[0]), float(end[1]), points[-1][2], "stop", points[-1][4], 0.0)
    loops[-1][-1] = points[-1]

    # The roof first: its lines, then over the walls' start, at the roof's height; the aircraft stops at each end
    roof_interval = roof_interval_of(s)
    roof_speed = roof_interval / STAY
    lines = roof_lines(s, outline) if s.roof else []
    above = s.top + s.height
    roof = [(float(q[0]), float(q[1]), above, poses) for line in lines for q, poses in line]
    if roof:
        roof.append((points[0][0], points[0][1], above, ()))
    flat = [np.array(r[:2]) for r in roof]
    roof_rows = []
    for i, (x, y, h, _) in enumerate(roof):
        ends = i == 0 or i >= len(roof) - 2
        heading = 0.0 if i >= len(roof) - 2 else math.degrees(math.atan2(*(flat[i + 1] - flat[i])))
        damping = 0.0 if ends else min(np.linalg.norm(flat[i] - flat[i - 1]), np.linalg.norm(flat[i + 1] - flat[i])) / 3.0
        roof_rows.append((x, y, h, "stop" if ends else "turn", wpml.signed_degrees(heading), float(damping)))
    poses = [r[3] for r in roof]
    speeds = [roof_speed if len(p) <= 1 else roof_interval / (POSE_TIME * len(p)) for p in poses]
    points = roof_rows + points

    def lonlat(x, y, h):
        return tuple(to_lonlat.transform(x, y)) + (float(h),)

    xyz = np.array([(x, y, h) for x, y, h, _, _, _ in points])
    legs = [float(np.linalg.norm(b - a)) for a, b in zip(xyz, xyz[1:])]
    distance = sum(legs)
    roof_legs = legs[:len(roof)]
    roof_time = sum(leg / speed for leg, speed in zip(roof_legs, speeds))
    roof_photos = int(sum(len(p) * leg / roof_interval for p, leg in zip(poses, roof_legs)))
    walls_distance = sum(legs[len(roof):])
    interval = interval_of(s)
    walls = Polygon([tuple(p) for p in outline] + [tuple(outline[0])]).exterior_ring
    closest = walls.distance(LineString([(x, y) for x, y, _, _, _, _ in loops[min(1, len(loops) - 1)]]))
    profile = {"face": [[0.0, round(s.top, 3)], [0.0, round(s.base, 3)]],
               "lines": [[round(s.height, 3), round(h, 3)] for h in heights],
               "roof": [[round(-s.height, 3), round(above, 3)], [0.0, round(above, 3)]] if roof else None}
    p = Plan(loops=[[lonlat(x, y, h) for x, y, h, _, _, _ in loop] for loop in loops],
             waypoints=[lonlat(x, y, h) for x, y, h, _, _, _ in points], kinds=[row[3] for row in points],
             headings=[row[4] for row in points], dampings=[row[5] for row in points], legs=legs, spacing=spacing,
             interval=interval, max_speed=interval / MIN_SHOT_INTERVAL, distance=distance, duration=None,
             photos=int(walls_distance // interval) + 1 + roof_photos, closest=closest, profile=profile,
             roof=[[lonlat(q[0], q[1], above) for q, _ in line] for line in lines], roof_points=len(roof), poses=poses,
             speeds=speeds, roof_speed=roof_speed, roof_photos=roof_photos)
    return p._replace(duration=roof_time + walls_distance / speed_of(p, s))


# -- XML ---------------------------------------------------------------------------------------------------------

def template_kml(p, s, now_ms):
    root, document = kml_root()
    if s.author:
        add(document, "author", s.author)
    add(document, "createTime", now_ms)
    add(document, "updateTime", now_ms)
    mission_config(document, s, template=True, reroute=False, ellipsoidal_ref=True)

    folder = ET.SubElement(document, k("Folder"))
    add(folder, "templateType", "mappingPrism")
    add(folder, "templateId", 0)
    system = add(folder, "waylineCoordinateSysParam")
    add(system, "coordinateMode", "WGS84")
    add(system, "heightMode", "EGM96")
    add(system, "globalShootHeight", s.height)
    add(folder, "autoFlightSpeed", speed_of(p, s))

    placemark = ET.SubElement(folder, k("Placemark"))
    for tag, value in (("shootTopFaceEnable", 1 if s.roof else 0), ("shootType", "distance"), ("trajectoryType", "horiz"),
                       ("startPositionType", "top")):
        add(placemark, tag, value)
    overlap = add(placemark, "overlap")
    add(overlap, "orthoCameraOverlapH", s.overlap_h)
    add(overlap, "orthoCameraOverlapW", s.overlap_w)
    polygon = ET.SubElement(placemark, k("Polygon"))
    ring = ET.SubElement(ET.SubElement(polygon, k("outerBoundaryIs")), k("LinearRing"))
    ET.SubElement(ring, k("coordinates")).text = "\n" + "\n".join(
        "                %s,%s,%s" % (coordinate(lon), coordinate(lat), wpml.num(s.base)) for lon, lat in s.outline) + \
        "\n              "
    add(placemark, "height", round(s.top - s.base, 6))
    add(placemark, "topFaceFlightSpeed", p.roof_speed)
    add(placemark, "scanExtent", 100)
    add(placemark, "scanOffset", 0)

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
    start_action_group(folder, -90 if p.roof_points else 0)
    add(folder, "realTimeFollowSurfaceByFov", 0)

    last = len(p.waypoints) - 1
    walls = p.roof_points
    group_id = 0
    for i, (lon, lat, h) in enumerate(p.waypoints):
        kind = p.kinds[i]
        on_roof = i < walls
        placemark = ET.SubElement(folder, k("Placemark"))
        ET.SubElement(ET.SubElement(placemark, k("Point")), k("coordinates")).text = \
            "\n            %s,%s\n          " % (coordinate(lon), coordinate(lat))
        add(placemark, "index", i)
        add(placemark, "executeHeight", h)
        add(placemark, "waypointSpeed", p.speeds[i] if on_roof else speed)

        # Over the roof heading along the line; then facing the wall all the way, turning smoothly from one point's
        # heading to the next's
        heading = add(placemark, "waypointHeadingParam")
        add(heading, "waypointHeadingMode", "followWayline" if on_roof else "smoothTransition")
        add(heading, "waypointHeadingAngle", round(p.headings[i], 9))
        add(heading, "waypointPoiPoint", "0.000000,0.000000,0.000000")
        add(heading, "waypointHeadingAngleEnable", 1)
        add(heading, "waypointHeadingPathMode", "followBadArc")
        add(heading, "waypointHeadingPoiIndex", 0)

        turn = add(placemark, "waypointTurnParam")
        add(turn, "waypointTurnMode", STOP if kind == "stop" else PASS if kind == "pass" else "coordinateTurn")
        add(turn, "waypointTurnDampingDist", round(p.dampings[i], 9))
        add(placemark, "useStraightLine", 0 if kind == "pass" else 1)

        # Over the roof, the gimbal cycling through the poses of each stretch (Smart Oblique), stopped where they end
        if on_roof and p.poses[i]:
            group = action_group(placemark, group_id, i, i + 1, "betweenAdjacentPoints")
            group_id += 1
            simple_action(group, 0, "gimbalAngleLock", payloadPositionIndex=0)
            smart_oblique(group, 1, p.poses[i])
        elif on_roof and i > 0 and p.poses[i - 1]:
            group = action_group(placemark, group_id, i, i, "reachPoint")
            group_id += 1
            simple_action(group, 0, "stopSmartOblique", payloadPositionIndex=0)
            simple_action(group, 1, "gimbalAngleUnlock")

        # Round the walls, photos all the way, the gimbal level (as Pilot 2 writes them here, without the lenses); after
        # the roof, the gimbal levelled and focused first, as before the survey
        if i == walls:
            if walls:
                group = action_group(placemark, group_id, i, i, "reachPoint")
                group_id += 1
                wpml.gimbal_rotate(group, 0, 0)
                simple_action(group, 1, "hover", hoverTime=0.5)
                simple_action(group, 2, "setFocusType", cameraFocusType="manual", payloadPositionIndex=0)
                simple_action(group, 3, "focus", focusX=0, focusY=0, focusRegionWidth=0, focusRegionHeight=0,
                              isPointFocus=0, isInfiniteFocus=1, payloadPositionIndex=0, isCalibrationFocus=0)
                simple_action(group, 4, "hover", hoverTime=1)
            group = action_group(placemark, group_id, i, last, "multipleDistance", p.interval)
            group_id += 1
            wpml.gimbal_rotate(group, 0, 0)
            simple_action(group, 1, "startContinuousShooting", payloadPositionIndex=0, useGlobalPayloadLensIndex=0)
        if i == last:
            group = action_group(placemark, group_id, last, last, "reachPoint")
            simple_action(group, 0, "stopContinuousShooting", payloadPositionIndex=0)

        gimbal = add(placemark, "waypointGimbalHeadingParam")
        add(gimbal, "waypointGimbalPitchAngle", 0)
        add(gimbal, "waypointGimbalYawAngle", 0)
        add(placemark, "isRisky", 0)
        add(placemark, "waypointWorkType", 0)

    return to_xml(root)


def smart_oblique(group, action_id, poses):
    """Smart Oblique through the poses, each held STAY seconds when it is the only one"""
    action = add(group, "action")
    add(action, "actionId", action_id)
    add(action, "actionActuatorFunc", "startSmartOblique")
    param = add(action, "actionActuatorFuncParam")
    add(param, "smartObliqueCycleMode", "unlimited")
    add(param, "payloadPositionIndex", 0)
    for pitch, yaw in poses:
        point = add(param, "smartObliquePoint")
        add(point, "smartObliqueRunningTime", 0)
        add(point, "smartObliqueStayTime", STAY if len(poses) == 1 else 0)
        add(point, "smartObliqueEulerPitch", pitch)
        add(point, "smartObliqueEulerRoll", 0)
        add(point, "smartObliqueEulerYaw", yaw)


def mission_warnings(p, s):
    """Things to check before flying that the file itself cannot say"""
    warnings = []
    speed = speed_of(p, s)
    if speed > p.max_speed + 1e-9:
        warnings.append("The speed of %.1f m/s is more than the %.1f m/s that leaves 1.25 s between photos: some may be "
                        "missed" % (speed, p.max_speed))
    warnings.append("The route flies the heights of the base and of the top, and the outline as drawn: check them, and "
                    "anything standing out from the walls, before flying")
    if p.closest < CLOSE * s.height:
        warnings.append("At a sharp corner the route passes %.1f m from the outline, closer than the %g m from the "
                        "walls" % (p.closest, s.height))
    if p.roof_points:
        warnings.append("Over the roof the lines run on %g m past it each way, %g m above its top: check that nothing "
                        "around stands that high" % (RUN_ON, s.height))
    if p.duration > BATTERY:
        warnings.append("The route takes about %d minutes, more than one battery (about %d minutes of flying): plan to "
                        "change batteries and resume it" % (round(p.duration / 60.0), BATTERY // 60))
    if s.rth_height < s.top - s.base + 10:
        warnings.append("The return height (%g m) is not well above the top of the block (%.0f m above its base)"
                        % (s.rth_height, s.top - s.base))
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
