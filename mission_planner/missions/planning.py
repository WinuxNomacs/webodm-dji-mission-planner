"""
Survey flight lines: back-and-forth lines over an area with the photo spacing that gives the requested overlaps.

The conventions follow DJI Pilot 2 area missions (mapping2d): with several cameras, the one with the
smallest footprint sets the spacing; the overlap across the lines sets the distance between them and the
overlap along them sets the distance between photos. Lines are spread evenly over the width of the area,
centered on it, as Pilot 2 does. Pilot 2 sometimes flies one line fewer than this planner where the footprint
reaches well beyond the area's edges (3 lines against 4 in one of its samples); this planner never flies fewer
lines than the area's width needs.
"""
import math
from collections import namedtuple

from django.contrib.gis.geos import LineString, Polygon
from pyproj import Transformer

from .cameras import footprint, oblique_footprint

MIN_HEIGHT, MAX_HEIGHT = 2.0, 500.0
MIN_OVERLAP, MAX_OVERLAP = 10.0, 95.0
# The range Pilot 2 offers for the M4T's oblique gimbal tilt (a dial from -40 to -85 degrees; -90 would be nadir)
MIN_GIMBAL_PITCH, MAX_GIMBAL_PITCH = -85.0, -40.0
MIN_AREA = 0.01      # square meters

# Slowest a photo can be taken after the previous one, for the speed limit. DJI does not publish it: two
# Pilot 2 missions imply 1.0 to 1.2 seconds for the M4T, so the planner assumes a little more.
MIN_SHOT_INTERVAL = 1.25

Plan = namedtuple("Plan", "lines waypoints spacing interval across along max_speed distance photos duration area warnings")


class PlanError(ValueError):
    pass


def local_transformers(lon, lat):
    """(to_metric, to_lonlat): transformers between WGS84 and an azimuthal equidistant frame centered on a location,
    the y axis true north there. Its metres are ground metres to under 1e-7 within a few km of the center (the
    distortion grows with the square of the distance), where UTM's are off by up to 0.1% across a zone."""
    proj = "+proj=aeqd +lat_0=%r +lon_0=%r +ellps=WGS84" % (lat, lon)
    return Transformer.from_crs(4326, proj, always_xy=True), Transformer.from_crs(proj, 4326, always_xy=True)


def check_inputs(polygon, direction, height, overlap_h, overlap_w, margin, cameras, route_start=None):
    if not cameras:
        raise PlanError("Choose at least one camera")
    if not (MIN_HEIGHT <= height <= MAX_HEIGHT):
        raise PlanError("The height must be between %g and %g meters" % (MIN_HEIGHT, MAX_HEIGHT))
    for name, value in (("along", overlap_h), ("across", overlap_w)):
        if not (MIN_OVERLAP <= value <= MAX_OVERLAP):
            raise PlanError("The overlap %s the lines must be between %g and %g%%" % (name, MIN_OVERLAP, MAX_OVERLAP))
    if not (isinstance(direction, (int, float)) and math.isfinite(direction)):
        raise PlanError("The direction must be a number of degrees")
    if not (isinstance(margin, (int, float)) and math.isfinite(margin) and margin >= 0):
        raise PlanError("The margin cannot be negative")
    if len(polygon) < 3 or any(len(p) < 2 or not all(math.isfinite(v) for v in p[:2]) for p in polygon):
        raise PlanError("The area needs at least 3 corners")
    if route_start is not None and (len(route_start) < 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in route_start[:2])):
        raise PlanError("The route start must be [longitude, latitude]")


def check_gimbal_pitch(gimbal_pitch):
    if not (isinstance(gimbal_pitch, (int, float)) and math.isfinite(gimbal_pitch)):
        raise PlanError("The gimbal tilt angle must be a number of degrees")
    if not (MIN_GIMBAL_PITCH <= gimbal_pitch <= MAX_GIMBAL_PITCH):
        raise PlanError("The gimbal tilt angle must be between %g and %g degrees" % (MIN_GIMBAL_PITCH, MAX_GIMBAL_PITCH))


def _survey_plan(polygon, direction, across, along, overlap_h, overlap_w, margin, min_shot_interval, route_start):
    """The flight lines that give the requested photo spacing (across, along - the footprint of whichever camera
    sets it) over an area. Shared by plan_survey (a nadir footprint) and plan_oblique_survey (a tilted one) -
    everything from here on only cares about the spacing/interval that footprint implies, not how it was computed."""
    spacing = (1 - overlap_w / 100.0) * across
    interval = (1 - overlap_h / 100.0) * along

    # A frame centered on the middle of the area
    center = (sum(p[0] for p in polygon) / len(polygon), sum(p[1] for p in polygon) / len(polygon))
    to_metric, to_lonlat = local_transformers(*center)
    metric = [to_metric.transform(p[0], p[1]) for p in polygon]

    # Work in a frame where a is the distance along the flight lines and c the distance across them:
    # every flight line is then c = constant
    # The direction is a true bearing, and the frame's y axis is true north at its center
    theta = math.radians(direction)
    u = (math.sin(theta), math.cos(theta))     # along
    v = (math.cos(theta), -math.sin(theta))    # across (to the right)
    frame = [(x * u[0] + y * u[1], x * v[0] + y * v[1]) for x, y in metric]

    area = Polygon(frame + [frame[0]])
    # (an area smaller than a few square decimeters is a line: rounding noise can leave it a tiny positive area)
    if not area.valid or area.area < MIN_AREA:
        raise PlanError("The area is not a valid polygon (its sides cross, or it has no area)")

    a_min, c_min, a_max, c_max = area.extent
    width = c_max - c_min
    count = max(1, int(math.ceil(width / spacing - 1e-9)))
    # Spread the lines evenly over the width of the area, centered
    c_first = c_min + (width - (count - 1) * spacing) / 2.0

    # The pieces of every line (a line has several where the area is notched), from low to high a, with the margin
    pieces = []
    for i in range(count):
        c = c_first + i * spacing
        cut = area.intersection(LineString([(a_min - 1.0, c), (a_max + 1.0, c)]))
        segments = [cut] if cut.geom_type == "LineString" else [g for g in cut if g.geom_type == "LineString"]
        segments = sorted(sorted([s.coords[0][0], s.coords[-1][0]]) for s in segments if s.length > 0)
        pieces.append((c, [(a0 - margin, a1 + margin) for a0, a1 in segments]))

    def ordered(last_line_first, high_end_first):
        """The lines in flying order: back and forth, starting at the first or the last line, at its low or high end"""
        result = []
        for k, (c, segments) in enumerate(reversed(pieces) if last_line_first else pieces):
            forward = (k % 2 == 0) != high_end_first
            for a0, a1 in (segments if forward else reversed(segments)):
                ends = [(a0, c), (a1, c)] if forward else [(a1, c), (a0, c)]
                result.append([(a * u[0] + cc * v[0], a * u[1] + cc * v[1]) for a, cc in ends])
        return result

    routes = ordered(False, False)
    if route_start is not None:
        sx, sy = to_metric.transform(*route_start[:2])
        candidates = [routes] + [ordered(last, high) for last, high in ((False, True), (True, False), (True, True))]
        # (min keeps the first of equal distances: the default order)
        routes = min(candidates, key=lambda r: math.hypot(r[0][0][0] - sx, r[0][0][1] - sy))
    lines = [[to_lonlat.transform(x, y) for x, y in line] for line in routes]

    waypoints = [p for line in lines for p in line]

    def length(line):
        (x0, y0), (x1, y1) = [to_metric.transform(*p) for p in line]
        return math.hypot(x1 - x0, y1 - y0)

    survey = sum(length(l) for l in lines)
    transitions = sum(math.hypot(*[a - b for a, b in zip(to_metric.transform(*l0[1]), to_metric.transform(*l1[0]))])
                      for l0, l1 in zip(lines, lines[1:]))
    max_speed = interval / min_shot_interval
    photos = sum(int(length(l) // interval) + 1 for l in lines)
    distance = survey + transitions

    warnings = []
    if count == 1 and width < spacing:
        warnings.append("The area is narrower than the distance between lines: a single line covers it")
    if max_speed < 0.5:
        warnings.append("The photos need a speed of %.2f m/s or less; the mission will be slow" % max_speed)

    return Plan(lines=lines, waypoints=waypoints, spacing=spacing, interval=interval, across=across, along=along,
                max_speed=max_speed, distance=distance, photos=photos,
                duration=distance / max_speed, area=area.area, warnings=warnings)


def plan_survey(polygon, direction, height, cameras, overlap_h=80.0, overlap_w=70.0, margin=0.0,
                min_shot_interval=MIN_SHOT_INTERVAL, route_start=None):
    """
    Flight lines over an area.

    :param polygon: corners as [(lon, lat), ...], not closed
    :param direction: bearing in degrees (clockwise from north) of the flight lines
    :param height: meters above the ground; the ground is assumed level around the survey (the aircraft follows
        the terrain by itself when the mission asks it to)
    :param cameras: [Camera, ...] that take photos; the one with the smallest footprint sets the spacing
    :param overlap_h: percent of overlap between photos along a line
    :param overlap_w: percent of overlap between neighboring lines
    :param margin: meters the lines are extended beyond the area at both ends
    :param route_start: (lon, lat) where the route should begin: it starts at the end of a line nearest to it (the
        first or last line, at either end). Without it the route starts at the first line, at its low end.
    :return: Plan(lines=[[(lon, lat), (lon, lat)], ...] in flying order, waypoints=[(lon, lat), ...] (the ends of the
        lines, in flying order), spacing and interval in meters, across/along footprint in meters, max_speed in m/s,
        distance in meters, photos, duration in seconds, area in square meters, warnings=[str])
    """
    check_inputs(polygon, direction, height, overlap_h, overlap_w, margin, cameras, route_start)
    across = min(footprint(c, height)[0] for c in cameras)
    along = min(footprint(c, height)[1] for c in cameras)
    return _survey_plan(polygon, direction, across, along, overlap_h, overlap_w, margin, min_shot_interval, route_start)


def plan_oblique_survey(polygon, direction, height, cameras, gimbal_pitch, overlap_h=80.0, overlap_w=70.0, margin=0.0,
                        min_shot_interval=MIN_SHOT_INTERVAL, route_start=None):
    """
    One oblique pass over an area: the same shape of result as plan_survey, but flown with the camera tilted
    gimbal_pitch degrees from straight down (see cameras.oblique_footprint) instead of straight down. A full
    oblique mission flies this at 4 headings 90 degrees apart plus one plan_survey() nadir pass - building that
    mission is missions.wpml's job; this only plans one of those 5 passes.

    height is above the takeoff point (ALT mode) - real-time terrain following for oblique passes is not
    supported yet, unlike plan_survey's nadir passes.
    """
    check_inputs(polygon, direction, height, overlap_h, overlap_w, margin, cameras, route_start)
    check_gimbal_pitch(gimbal_pitch)
    across = min(oblique_footprint(c, height, gimbal_pitch)[0] for c in cameras)
    along = min(oblique_footprint(c, height, gimbal_pitch)[1] for c in cameras)
    return _survey_plan(polygon, direction, across, along, overlap_h, overlap_w, margin, min_shot_interval, route_start)
