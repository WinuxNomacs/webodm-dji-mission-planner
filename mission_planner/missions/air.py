"""
Where a route flies, in the air: the heights the 3D view draws the route at (public/route_3d.js).

The plan sends the browser the route's lines and points without their heights (the 2D map drapes them on the
ground). air() adds the path the aircraft flies, each point with its height, and the points to draw a line down to the
surface from (every point of a waypoint route, the ends of each line of the others), with what the heights are
measured from:

- "sea": above sea level (EGM96), where the route knows it: ALT with the takeoff point's ground height, ASL (an
  area or linear route's at the takeoff point's ground plus the height), AGL over
  the route's terrain (the heights the export gives each waypoint, terrain.flown_ground_heights, the aircraft flying
  straight between them), a
  waypoint route's AGL with every point's ground, slope and building routes (their ellipsoidal heights);
- "surface": above the 3D view's surface under each point (AGL without the route's terrain yet, or without the geoid
  grid): the browser adds the surface;
- "takeoff": above the takeoff point's ground, unknown here (ALT without the takeoff height): the browser adds the
  surface at the takeoff point, or at the route's first point when it has none.

The geoid's undulation is taken once, at the route's middle: it changes by centimetres over a route.
"""
import logging

from . import geoid, linear, terrain, wpml
from .waypoints import height_of

logger = logging.getLogger('app.logger')


def _middle(points):
    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lat, lon


def _ends(lines):
    """The first and last point of each line"""
    out = []
    for line in lines:
        if line:
            out.append(tuple(line[0]))
            if len(line) > 1:
                out.append(tuple(line[-1]))
    return out


def _with(points, heights):
    return [[round(float(p[0]), 7), round(float(p[1]), 7), round(float(h), 2)] for p, h in zip(points, heights)]


def _result(reference, paths, drops, heights):
    """paths: [[(lon, lat), ...], ...]; drops: [(lon, lat), ...]; heights(points) -> [height, ...]"""
    return {"reference": reference, "paths": [_with(path, heights(path)) for path in paths],
            "drops": _with(drops, heights(drops))}


def _flat(height):
    return lambda points: [height] * len(points)


def _over_terrain(paths, drops, height, tif, name):
    """Heights above sea level over the route's terrain (ellipsoidal, its file `name`): each path's waypoints over their
    ground plus the height, as the export gives them (terrain.flown_ground_heights), and the drops from the same heights
    (they are the ends of the paths' lines); None when the terrain or the geoid cannot be had"""
    if tif is None:
        return None
    try:
        n = geoid.undulation(*_middle([p for path in paths for p in path]))
        out, at = [], {}
        for path in paths:
            grounds = terrain.flown_ground_heights(tif, path, name)
            out.append(_with(path, [g + height - n for g in grounds]))
            for p, g in zip(path, grounds):
                at.setdefault(tuple(p), g)
        for d in drops:
            if tuple(d) not in at:
                at[tuple(d)] = terrain.flown_ground_heights(tif, [d], name)[0]
        return {"reference": "sea", "paths": out, "drops": _with(drops, [at[tuple(d)] + height - n for d in drops])}
    except (geoid.GeoidError, terrain.TerrainError) as e:
        logger.info("The route's heights in 3D fall back on the surface: %s", e)
        return None


def _area_like(paths, drops, s, mode, uses_dsm, tif, name):
    """Area and linear routes: one height for the route, in one of wpml's height modes"""
    if mode in ("EGM96", "relativeToStartPoint"):
        # ASL flies one altitude, the takeoff point's ground plus the height (wpml.asl_heights), as ALT does; its
        # settings always have the takeoff point's ground height
        if s.takeoff_ref_point is not None:
            return _result("sea", paths, drops, _flat(s.takeoff_ref_point[2] + s.height))
        return _result("takeoff", paths, drops, _flat(s.height))
    if uses_dsm:
        over = _over_terrain(paths, drops, s.height, tif, name)
        if over is not None:
            return over
    return _result("surface", paths, drops, _flat(s.height))


def area(plan, s, tif=None, name=None):
    passes = [plan.nadir] + list(plan.oblique or [])
    paths = [list(p.waypoints) for p in passes]
    drops = _ends([line for p in passes for line in p.lines])
    return _area_like(paths, drops, s, s.height_mode, wpml.uses_dsm(s), tif, name)


def linear_route(plan, s, tif=None, name=None):
    lines = list(plan.lines)
    if plan.bend is not None:
        lines.append(plan.waypoints[plan.bend:])
    return _area_like([list(plan.waypoints)], _ends(lines), s, s.height_mode, linear.uses_dsm(s), tif, name)


def waypoint_route(s):
    points = [(p.lon, p.lat) for p in s.points]
    heights = [height_of(p, s) for p in s.points]
    reference = "surface"
    if s.height_mode == "asl":
        reference = "sea"
    elif s.height_mode == "alt":
        if s.takeoff_ref_point is not None:
            reference, heights = "sea", [h + s.takeoff_ref_point[2] for h in heights]
        else:
            reference = "takeoff"
    elif all(p.ground is not None for p in s.points):
        try:
            n = geoid.undulation(*_middle(points))
            reference, heights = "sea", [h + p.ground - n for h, p in zip(heights, s.points)]
        except geoid.GeoidError as e:
            logger.info("The route's heights in 3D fall back on the surface: %s", e)
    path = _with(points, heights)
    return {"reference": reference, "paths": [path], "drops": [list(p) for p in path]}


def ellipsoidal(waypoints, lines):
    """Slope and building routes, whose points and lines have their WGS84-ellipsoidal heights: None without the geoid
    grid (the 3D view then drapes the route, as before)"""
    try:
        n = geoid.undulation(*_middle(waypoints))
    except geoid.GeoidError as e:
        logger.info("The route is not drawn in the air: %s", e)
        return None
    drops = _ends(lines)
    return {"reference": "sea", "paths": [_with(waypoints, [p[2] - n for p in waypoints])],
            "drops": _with(drops, [p[2] - n for p in drops])}
