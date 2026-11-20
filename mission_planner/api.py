"""
The API of the mission planner: plan the flight lines of an area, a linear, a slope or a geometric route or the legs of
a waypoint route, and export the mission as a DJI .kmz file. Also saved routes (list/create/retrieve/update/delete) - the persistence
backing the routes list and per-route editor.

Both plan/export take the same JSON body; its route_type ("area" when missing) says which kind of route it is. The
planning code is in missions/; this only checks the request, calls it and turns the result into JSON. The saved routes
are kept by routes.py.
"""
import math
import re
import time

import numpy as np
from django.contrib.gis.geos import MultiPoint, Point, Polygon
from django.http import Http404, HttpResponse
from rest_framework import permissions, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from guardian.shortcuts import get_objects_for_user
from pyproj import Transformer

from .missions import air, djifly, geometric, kml, linear, slope, terrain, waypoints, wpml
from .missions.kmz_import import KmzImportError, read_kmz_dsm, read_kmz_route, read_template, route_name
from .missions.drones import DRONES
from .missions.cameras import CAMERAS_BY_MODEL, footprint, ground_sample_distance, oblique_footprint, oblique_ground_sample_distance
from .missions.elevation import ElevationError, fetch_ground_elevation
from .missions.planning import PlanError
from app.models import Project, Task
from . import lidar, lidar_terrain, routes, surface
from .routes import AIRCRAFT_MODELS, ROUTE_TYPES, RouteGone

# The route types that can be created and planned (routes.ROUTE_TYPES lists the same ones today)
SUPPORTED_ROUTE_TYPES = ('area', 'linear', 'waypoint', 'slope', 'geometric')

# The lowest and highest height a route can have (the planner's LIMITS): a copy to another model stays within them
MIN_HEIGHT, MAX_HEIGHT = 2.0, 500.0

MAX_VERTICES = 200

DEFAULTS = {
    "direction": 0.0, "height": 50.0, "overlap_h": 80.0, "overlap_w": 70.0, "margin": 0.0, "speed": None,
    "height_mode": "realTimeFollowSurface", "takeoff_security_height": 20.0, "rth_height": 100.0,
    "finish_action": "goHome", "exit_on_rc_lost": "goContinue", "takeoff_ref_point": None,
    "takeoff_ellipsoidal_height": None, "cameras": ["visable", "ir"],
    "transitional_speed": 15.0, "takeoff_mode": "safe", "elevation_optimize": True, "avoid_limit_area": False,
    "photo_mode": "distance", "route_start": None,
    "collection_mode": "ortho", "gimbal_pitch": None, "inclined_overlap_h": None, "inclined_overlap_w": None, "inclined_speed": None,
}


class RequestError(ValueError):
    pass


def number(body, name, allow_none=False):
    value = body.get(name, DEFAULTS[name])
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RequestError("%s must be a number" % name)
    return float(value)


def flag(body, name):
    value = body.get(name, DEFAULTS[name])
    if not isinstance(value, bool):
        raise RequestError("%s must be true or false" % name)
    return value


def parse_route_start(body):
    start = body.get("route_start", None)
    if start is None:
        return None
    if (not isinstance(start, list) or len(start) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in start)
            or not (-180 <= start[0] <= 180 and -85 <= start[1] <= 85)):
        raise RequestError("route_start must be [longitude, latitude]")
    return (float(start[0]), float(start[1]))


def parse_polygon(body):
    polygon = body.get("polygon")
    if not isinstance(polygon, list) or len(polygon) < 3:
        raise RequestError("The area needs at least 3 corners")
    if len(polygon) > MAX_VERTICES:
        raise RequestError("The area has too many corners (at most %d)" % MAX_VERTICES)

    result = []
    for p in polygon:
        if (not isinstance(p, (list, tuple)) or len(p) < 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p[:2])
                or not (-180 <= p[0] <= 180 and -85 <= p[1] <= 85)):
            raise RequestError("The corners of the area must be [longitude, latitude]")
        result.append((float(p[0]), float(p[1])))
    if len(result) > 3 and result[0] == result[-1]:       # drawn as a closed ring
        result = result[:-1]
    return result


def parse_aircraft(body):
    """(model, cameras, takeoff_ref_point) of a request body"""
    model = body.get("model", "m4t")
    if not wpml.known(model, CAMERAS_BY_MODEL):
        raise RequestError("model must be one of %s" % ", ".join(sorted(CAMERAS_BY_MODEL)))
    cameras_of_model = CAMERAS_BY_MODEL[model]
    cameras = body.get("cameras", [c for c in DEFAULTS["cameras"] if c in cameras_of_model])
    if not isinstance(cameras, list) or not cameras or any(not isinstance(c, str) or c not in cameras_of_model for c in cameras):
        raise RequestError("cameras must be a list of %s" % ", ".join(sorted(cameras_of_model)))

    ref = body.get("takeoff_ref_point", None)
    if ref is not None:
        if not isinstance(ref, list) or len(ref) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in ref):
            raise RequestError("takeoff_ref_point must be [latitude, longitude, altitude]")
        ref = tuple(float(v) for v in ref)
    return model, [cameras_of_model[c] for c in cameras], ref


def check_route_type(kind, model):
    """A RequestError when the model is not offered routes of this type (drones.json route_types)"""
    drone = DRONES.get(model)
    if drone is not None and kind not in drone.route_types:
        raise RequestError("The %s is not offered %s routes: its app's documents do not say it flies them"
                           % (drone.name, kind))


def route_type(body):
    if not isinstance(body, dict):
        raise RequestError("The request must be a JSON object")
    kind = body.get("route_type", "area")
    if kind not in SUPPORTED_ROUTE_TYPES:
        raise RequestError("route_type must be one of %s" % ", ".join(SUPPORTED_ROUTE_TYPES))
    return kind


def parse_waypoint_settings(body):
    """The waypoint route of a request body (missions/waypoints.py checks the values)"""
    model, cameras, ref = parse_aircraft(body)
    points = body.get("points")
    if not isinstance(points, list):
        raise RequestError("points must be a list")
    names = ("height", "height_mode", "speed", "gimbal_pitch", "heading_mode", "turn_mode", "takeoff_mode",
             "finish_action", "exit_on_rc_lost", "takeoff_security_height", "takeoff_ellipsoidal_height",
             "transitional_speed", "rth_height", "avoid_limit_area", "poi", "video", "photo_interval_mode",
             "photo_interval")
    return waypoints.settings(points=points, cameras=cameras, takeoff_ref_point=ref, model=model,
                              **{name: body[name] for name in names if name in body})


def parse_linear_settings(body):
    """The linear route of a request body (missions/linear.py checks the values)"""
    model, cameras, ref = parse_aircraft(body)
    line = body.get("line")
    if (not isinstance(line, list) or len(line) > linear.MAX_POINTS
            or any(not isinstance(p, list) or len(p) != 2 or not all(wpml.is_number(v) for v in p)
                   or not (-180 <= p[0] <= 180 and -85 <= p[1] <= 85) for p in line)):
        raise RequestError("line must be a list of at most %d [longitude, latitude]" % linear.MAX_POINTS)
    for name in ("height_mode", "finish_action", "exit_on_rc_lost", "takeoff_mode", "surface_follow"):
        if name in body and not isinstance(body[name], str):
            raise RequestError("%s must be text" % name)
    names = ("left_extend", "right_extend", "single_line", "height", "overlap_h", "overlap_w", "speed", "height_mode",
             "takeoff_security_height", "rth_height", "finish_action", "exit_on_rc_lost", "takeoff_ellipsoidal_height",
             "transitional_speed", "takeoff_mode", "elevation_optimize", "avoid_limit_area", "surface_follow")
    return linear.settings(line=line, cameras=cameras, takeoff_ref_point=ref, model=model,
                           **{name: body[name] for name in names if name in body})


def parse_slope_settings(body):
    """The slope route of a request body (missions/slope.py checks the values)"""
    model, cameras, ref = parse_aircraft(body)
    corners = body.get("corners")
    if (not isinstance(corners, list) or len(corners) > slope.MAX_CORNERS
            or any(not isinstance(c, list) or len(c) != 3 or not all(wpml.is_number(v) for v in c)
                   or not (-180 <= c[0] <= 180 and -85 <= c[1] <= 85) for c in corners)):
        raise RequestError("corners must be a list of at most %d [longitude, latitude, height]" % slope.MAX_CORNERS)
    for name in ("finish_action", "exit_on_rc_lost", "takeoff_mode"):
        if name in body and not isinstance(body[name], str):
            raise RequestError("%s must be text" % name)
    names = ("height", "overlap_h", "overlap_w", "speed", "takeoff_security_height", "rth_height", "finish_action",
             "exit_on_rc_lost", "transitional_speed", "takeoff_mode", "avoid_limit_area")
    return slope.settings(corners=corners, cameras=cameras, takeoff_ref_point=ref, model=model,
                          **{name: body[name] for name in names if name in body})


def parse_outline(body):
    """The [[longitude, latitude], ...] of a block's outline in a request body (or a RequestError)"""
    outline = body.get("outline") if isinstance(body, dict) else None
    if (not isinstance(outline, list) or not (1 <= len(outline) <= slope.MAX_CORNERS)
            or any(not isinstance(c, list) or len(c) != 2 or not all(wpml.is_number(v) for v in c)
                   or not (-180 <= c[0] <= 180 and -85 <= c[1] <= 85) for c in outline)):
        raise RequestError("outline must be a list of at most %d [longitude, latitude]" % slope.MAX_CORNERS)
    return outline


def parse_geometric_settings(body):
    """The geometric route of a request body (missions/geometric.py checks the values)"""
    model, cameras, ref = parse_aircraft(body)
    outline = parse_outline(body)
    for name in ("finish_action", "exit_on_rc_lost", "takeoff_mode"):
        if name in body and not isinstance(body[name], str):
            raise RequestError("%s must be text" % name)
    for name in ("base", "top"):
        if not wpml.is_number(body.get(name)):
            raise RequestError("%s must be a height in meters" % name)
    names = ("height", "overlap_h", "overlap_w", "speed", "takeoff_security_height", "rth_height", "finish_action",
             "exit_on_rc_lost", "transitional_speed", "takeoff_mode", "avoid_limit_area", "roof")
    return geometric.settings(outline=outline, base=body["base"], top=body["top"], cameras=cameras, takeoff_ref_point=ref,
                              model=model, **{name: body[name] for name in names if name in body})


def parse_settings(body):
    """The mission settings of a request body, or a RequestError / PlanError / ExportError saying what is wrong"""
    if not isinstance(body, dict):
        raise RequestError("The request must be a JSON object")

    model, cameras, ref = parse_aircraft(body)

    for name in ("height_mode", "finish_action", "exit_on_rc_lost", "takeoff_mode", "photo_mode", "collection_mode"):
        if not isinstance(body.get(name, DEFAULTS[name]), str):
            raise RequestError("%s must be text" % name)
    if "surface_follow" in body and not isinstance(body["surface_follow"], str):
        raise RequestError("surface_follow must be text")

    return wpml.settings(
        polygon=parse_polygon(body), direction=number(body, "direction"), height=number(body, "height"),
        cameras=cameras, overlap_h=number(body, "overlap_h"), overlap_w=number(body, "overlap_w"),
        margin=number(body, "margin"), speed=number(body, "speed", allow_none=True),
        height_mode=body.get("height_mode", DEFAULTS["height_mode"]),
        takeoff_security_height=number(body, "takeoff_security_height"), rth_height=number(body, "rth_height"),
        finish_action=body.get("finish_action", DEFAULTS["finish_action"]),
        exit_on_rc_lost=body.get("exit_on_rc_lost", DEFAULTS["exit_on_rc_lost"]), takeoff_ref_point=ref,
        takeoff_ellipsoidal_height=number(body, "takeoff_ellipsoidal_height", allow_none=True),
        transitional_speed=number(body, "transitional_speed"), takeoff_mode=body.get("takeoff_mode", DEFAULTS["takeoff_mode"]),
        elevation_optimize=flag(body, "elevation_optimize"), avoid_limit_area=flag(body, "avoid_limit_area"),
        photo_mode=body.get("photo_mode", DEFAULTS["photo_mode"]), route_start=parse_route_start(body),
        collection_mode=body.get("collection_mode", DEFAULTS["collection_mode"]),
        gimbal_pitch=number(body, "gimbal_pitch", allow_none=True),
        inclined_overlap_h=number(body, "inclined_overlap_h", allow_none=True),
        inclined_overlap_w=number(body, "inclined_overlap_w", allow_none=True),
        inclined_speed=number(body, "inclined_speed", allow_none=True), model=model,
        surface_follow=body.get("surface_follow"))


def summary(plan, s):
    """The nadir pass's numbers, at the same keys as before oblique existed (so the ortho UI/tests are unaffected),
    plus an "oblique" key (present only for collection_mode "oblique") with the same numbers for the 4 tilted
    passes - photos/distance/duration there are already totals across all 4, since they share one footprint/interval.
    """
    nadir = plan.nadir
    speed = wpml.speed_of(plan, s)
    result = {
        "lines": len(nadir.lines), "waypoints": len(nadir.waypoints), "photos": nadir.photos, "area": nadir.area,
        "spacing": nadir.spacing, "interval": nadir.interval, "across": nadir.across, "along": nadir.along,
        "max_speed": nadir.max_speed, "speed": speed, "distance": nadir.distance, "duration": nadir.distance / speed,
        "gsd": {c.key: ground_sample_distance(c, s.height) for c in s.cameras},
        # meters of ground per pixel for each meter of height: the height for a ground sample distance is gsd / gsd_per_m
        "gsd_per_m": {c.key: ground_sample_distance(c, 1.0) for c in CAMERAS_BY_MODEL[s.model].values()},
        "footprint": {c.key: footprint(c, s.height) for c in s.cameras},
    }
    if s.collection_mode == "oblique":
        inclined_speed = wpml.inclined_speed_of(plan, s)
        distance = sum(p.distance for p in plan.oblique)
        result["oblique"] = {
            "lines": sum(len(p.lines) for p in plan.oblique), "waypoints": sum(len(p.waypoints) for p in plan.oblique),
            "photos": sum(p.photos for p in plan.oblique), "spacing": plan.oblique[0].spacing, "interval": plan.oblique[0].interval,
            "across": plan.oblique[0].across, "along": plan.oblique[0].along, "max_speed": min(p.max_speed for p in plan.oblique),
            "speed": inclined_speed, "distance": distance, "duration": distance / inclined_speed,
            "gsd": {c.key: oblique_ground_sample_distance(c, s.height, s.gimbal_pitch) for c in s.cameras},
            "footprint": {c.key: oblique_footprint(c, s.height, s.gimbal_pitch) for c in s.cameras},
        }
    return result


def geojson(plan):
    """Every pass's lines/waypoints, concatenated into one pair of FeatureCollections (properties.pass tells them
    apart: "nadir", or the oblique heading in degrees) - the map draws them all regardless of collection_mode."""
    passes = [("nadir", plan.nadir)]
    if plan.oblique:
        passes += [(str(heading), p) for heading, p in zip(wpml.OBLIQUE_HEADINGS, plan.oblique)]

    lines, waypoints = [], []
    for name, p in passes:
        lines += [{"type": "Feature", "properties": {"index": i, "pass": name},
                   "geometry": {"type": "LineString", "coordinates": [list(pt) for pt in line]}} for i, line in enumerate(p.lines)]
        waypoints += [{"type": "Feature", "properties": {"index": i, "pass": name},
                      "geometry": {"type": "Point", "coordinates": list(pt)}} for i, pt in enumerate(p.waypoints)]
    return {"lines": {"type": "FeatureCollection", "features": lines}, "waypoints": {"type": "FeatureCollection", "features": waypoints}}


def waypoint_summary(plan, s):
    return {"length": plan.length, "duration": plan.duration, "photos": plan.photos, "speed": s.speed,
            "points": len(s.points)}


def waypoint_geojson(s):
    """The route as one line, and its points numbered from 1, as the same pair of FeatureCollections as geojson()"""
    coordinates = [[p.lon, p.lat] for p in s.points]
    return {
        "lines": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"index": 0, "pass": "waypoint"},
             "geometry": {"type": "LineString", "coordinates": coordinates}}]},
        "waypoints": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"index": i, "number": i + 1, "pass": "waypoint"},
             "geometry": {"type": "Point", "coordinates": c}} for i, c in enumerate(coordinates)]},
    }


def linear_summary(plan, s):
    speed = linear.speed_of(plan, s)
    return {
        "lines": len(plan.lines), "waypoints": len(plan.waypoints), "photos": plan.photos, "spacing": plan.spacing,
        "interval": plan.interval, "max_speed": plan.max_speed, "speed": speed, "distance": plan.distance,
        "duration": plan.duration, "height": s.height, "bend_pass": plan.bend is not None,
        "gsd": {c.key: ground_sample_distance(c, s.height) for c in s.cameras},
        "gsd_per_m": {c.key: ground_sample_distance(c, 1.0) for c in CAMERAS_BY_MODEL[s.model].values()},
        "footprint": {c.key: footprint(c, s.height) for c in s.cameras},
    }


def linear_geojson(plan):
    """The lines along the strip (pass "linear"), the pass along a bent center line (pass "bend") and every point
    of the route, as the same pair of FeatureCollections as geojson()"""
    lines = [{"type": "Feature", "properties": {"index": i, "pass": "linear"},
              "geometry": {"type": "LineString", "coordinates": [list(pt) for pt in line]}} for i, line in enumerate(plan.lines)]
    if plan.bend is not None:
        lines.append({"type": "Feature", "properties": {"index": len(lines), "pass": "bend"},
                      "geometry": {"type": "LineString", "coordinates": [list(pt) for pt in plan.waypoints[plan.bend:]]}})
    return {
        "lines": {"type": "FeatureCollection", "features": lines},
        "waypoints": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"index": i, "pass": "bend" if plan.bend is not None and i >= plan.bend else "linear"},
             "geometry": {"type": "Point", "coordinates": list(pt)}} for i, pt in enumerate(plan.waypoints)]},
    }


def slope_summary(plan, s):
    speed = slope.speed_of(plan, s)
    lon = sum(c[0] for c in s.corners) / len(s.corners)
    lat = sum(c[1] for c in s.corners) / len(s.corners)
    return {
        "lines": len(plan.lines), "waypoints": len(plan.waypoints), "photos": plan.photos, "spacing": plan.spacing,
        "interval": plan.interval, "max_speed": plan.max_speed, "speed": speed, "distance": plan.distance,
        "duration": plan.duration, "height": s.height, "slope": plan.slope, "heading": plan.heading,
        "pitch": plan.pitch, "profile": plan.profile, "undulation": slope.geoid_undulation(lon, lat),
        "gsd": {c.key: ground_sample_distance(c, s.height) for c in s.cameras},
        "gsd_per_m": {c.key: ground_sample_distance(c, 1.0) for c in CAMERAS_BY_MODEL[s.model].values()},
        "footprint": {c.key: footprint(c, s.height) for c in s.cameras},
    }


def slope_geojson(plan):
    """The lines across the face (pass "slope") and every point of the route, each with its height as a third
    coordinate, as the same pair of FeatureCollections as geojson()"""
    return {
        "lines": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"index": i, "pass": "slope"},
             "geometry": {"type": "LineString", "coordinates": [list(pt) for pt in line]}} for i, line in enumerate(plan.lines)]},
        "waypoints": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"index": i, "pass": "slope"},
             "geometry": {"type": "Point", "coordinates": list(pt)}} for i, pt in enumerate(plan.waypoints)]},
    }


def geometric_summary(plan, s):
    speed = geometric.speed_of(plan, s)
    lon = sum(c[0] for c in s.outline) / len(s.outline)
    lat = sum(c[1] for c in s.outline) / len(s.outline)
    return {
        "loops": len(plan.loops), "waypoints": len(plan.waypoints), "photos": plan.photos, "spacing": plan.spacing,
        "interval": plan.interval, "max_speed": plan.max_speed, "speed": speed, "distance": plan.distance,
        "duration": plan.duration, "height": s.height, "base": s.base, "top": s.top, "closest": plan.closest,
        "profile": plan.profile, "undulation": slope.geoid_undulation(lon, lat), "roof": s.roof,
        "roof_lines": len(plan.roof), "roof_photos": plan.roof_photos, "roof_spacing": geometric.roof_spacing_of(s),
        "roof_speed": plan.roof_speed,
        "gsd": {c.key: ground_sample_distance(c, s.height) for c in s.cameras},
        "gsd_per_m": {c.key: ground_sample_distance(c, 1.0) for c in CAMERAS_BY_MODEL[s.model].values()},
        "footprint": {c.key: footprint(c, s.height) for c in s.cameras},
    }


def geometric_geojson(plan):
    """The lines over the roof (pass "roof"), the loops round the block (pass "walls") and every point of the route,
    each with its height as a third coordinate, as the same pair of FeatureCollections as geojson()"""
    lines = [("roof", line) for line in plan.roof] + [("walls", loop) for loop in plan.loops]
    return {
        "lines": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"index": i, "pass": kind},
             "geometry": {"type": "LineString", "coordinates": [list(pt) for pt in line]}} for i, (kind, line) in enumerate(lines)]},
        "waypoints": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"index": i, "pass": "roof" if i < plan.roof_points else "walls"},
             "geometry": {"type": "Point", "coordinates": list(pt)}} for i, pt in enumerate(plan.waypoints)]},
    }


class MissionView(APIView):
    """The plan of the route of the request: (route_type, plan, settings)"""
    permission_classes = (permissions.IsAuthenticated,)

    def load(self, request, strict=False):
        kind, plan, s = self.planned(request, strict)
        check_route_type(kind, s.model)     # what the editors cannot ask for, a hand-made request can
        if djifly.is_djifly(s.model):
            djifly.check(kind, s)       # what DJI Fly cannot fly is said when the route is planned, not only on export
        return kind, plan, s

    def planned(self, request, strict):
        kind = route_type(request.data)
        if kind == "waypoint":
            s = parse_waypoint_settings(request.data)
            return kind, waypoints.plan(s, strict=strict), s
        if kind == "linear":
            s = parse_linear_settings(request.data)
            return kind, linear.plan(s), s
        if kind == "slope":
            s = parse_slope_settings(request.data)
            return kind, slope.plan(s), s
        if kind == "geometric":
            s = parse_geometric_settings(request.data)
            return kind, geometric.plan(s), s
        s = parse_settings(request.data)
        return kind, wpml.plan_from_settings(s), s


class PlanView(MissionView):
    def post(self, request):
        try:
            kind, plan, s = self.load(request)
        except (RequestError, PlanError, wpml.ExportError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(plan_result(request, kind, plan, s))


class KmlView(MissionView):
    """POST kml, the body of a plan request: the route as plain KML (missions/kml.py), its shape and flight path"""

    def post(self, request):
        try:
            kind, plan, s = self.load(request)
        except (RequestError, PlanError, wpml.ExportError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        shape = (("line", s.line) if kind == "linear" else ("points", [(p.lon, p.lat) for p in s.points]) if kind == "waypoint"
                 else ("polygon", s.corners) if kind == "slope" else ("polygon", s.outline) if kind == "geometric"
                 else ("polygon", s.polygon))
        name = str(request.data.get("name") or "Route")
        response = HttpResponse(kml.write_kml(name, shape, plan_result(request, kind, plan, s)["air"]),
                                content_type="application/vnd.google-earth.kml+xml")
        response["Content-Disposition"] = 'attachment; filename="%s.kml"' % kml.file_name(name)
        return response


def plan_result(request, kind, plan, s):
    """What the plan endpoint answers: the summary, warnings, the lines and points to draw and the path in the air"""
    if kind == "waypoint":
        result = {"summary": waypoint_summary(plan, s), "warnings": waypoints.mission_warnings(s)}
        result.update(waypoint_geojson(s))
        result["air"] = air.waypoint_route(s)
    elif kind == "linear":
        result = {"summary": linear_summary(plan, s), "warnings": linear.mission_warnings(plan, s)}
        result.update(linear_geojson(plan))
        result["air"] = air.linear_route(plan, s, plan_terrain(request, kind, plan, s))
    elif kind == "slope":
        result = {"summary": slope_summary(plan, s), "warnings": slope.mission_warnings(plan, s)}
        result.update(slope_geojson(plan))
        result["air"] = air.ellipsoidal(plan.waypoints, plan.lines)
    elif kind == "geometric":
        result = {"summary": geometric_summary(plan, s), "warnings": geometric.mission_warnings(plan, s)}
        result.update(geometric_geojson(plan))
        result["air"] = air.ellipsoidal(plan.waypoints, list(plan.roof) + list(plan.loops))
    else:
        result = {"summary": summary(plan, s), "warnings": wpml.mission_warnings(plan, s)}
        result.update(geojson(plan))
        result["air"] = air.area(plan, s, plan_terrain(request, kind, plan, s))
    if djifly.is_djifly(s.model):
        result["warnings"] = result["warnings"] + djifly.warnings(kind, s)
    return result


class ExportView(MissionView):
    def post(self, request):
        try:
            kind, plan, s = self.load(request, strict=True)
            if djifly.is_djifly(s.model):
                return self.djifly(request, kind, plan, s)
            if kind == "waypoint":
                data, warnings = waypoints.build_kmz(s), waypoints.mission_warnings(s)
            elif kind == "slope":
                data, warnings = slope.build_kmz(plan, s), slope.mission_warnings(plan, s)
            elif kind == "geometric":
                data, warnings = geometric.build_kmz(plan, s), geometric.mission_warnings(plan, s)
            else:
                dsm = None
                if uses_dsm(kind, s):
                    dsm = route_terrain(request, kind, plan, s, source=terrain_source(request, required=False))
                    if dsm is None:
                        return Response({"error": "Fetch the terrain under the route first", "needs_terrain": True},
                                        status=status.HTTP_409_CONFLICT)
                if kind == "linear":
                    data, warnings = linear.build_kmz(plan, s, dsm=dsm), linear.mission_warnings(plan, s)
                else:
                    data, warnings = wpml.build_kmz(plan, s, dsm=dsm), wpml.mission_warnings(plan, s)
        except (RequestError, PlanError, wpml.ExportError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(request.data.get("name") or "luxodm-mission"))[:60].strip("._") or "luxodm-mission"
        response = HttpResponse(data, content_type="application/vnd.google-earth.kmz")
        response["Content-Disposition"] = 'attachment; filename="%s.kmz"' % name
        response["X-Mission-Warnings"] = " | ".join(warnings)[:900].encode("ascii", "replace").decode()
        return response

    def djifly(self, request, kind, plan, s):
        """The route as DJI Fly missions (missions/djifly.py): one .kmz, or a .zip of them when it was split"""
        tif = None
        if kind in ("area", "linear") and uses_dsm(kind, s):
            dsm = route_terrain(request, kind, plan, s, source=terrain_source(request, required=False))
            if dsm is None:
                return Response({"error": "Fetch the terrain under the route first", "needs_terrain": True},
                                status=status.HTTP_409_CONFLICT)
            tif = dsm[0]
        speed = (summary(plan, s)["speed"] if kind == "area" else linear_summary(plan, s)["speed"] if kind == "linear"
                 else s.speed)
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(request.data.get("name") or "mission"))[:60].strip("._") or "mission"
        try:
            files = djifly.build(kind, plan, s, int(time.time() * 1000), name, tif=tif, speed=speed)
        except wpml.ExportError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        data, file_name, content_type = djifly.bundle(files, name)
        response = HttpResponse(data, content_type=content_type)
        response["Content-Disposition"] = 'attachment; filename="%s"' % file_name
        notes = djifly.warnings(kind, s) + (["Split into %d DJI Fly missions of at most %d points" % (len(files), djifly.MAX_WAYPOINTS)]
                                            if len(files) > 1 else [])
        response["X-Mission-Warnings"] = " | ".join(notes)[:900].encode("ascii", "replace").decode()
        return response


def uses_dsm(kind, s):
    """Whether an area or linear route flies over the route's terrain (AGL with the DSM follow, or oblique AGL)"""
    return linear.uses_dsm(s) if kind == "linear" else wpml.uses_dsm(s)


def terrain_points(kind, plan, s):
    """The (lon, lat) points the terrain of an area or linear route must cover: its waypoints and takeoff point, and
    its area or center line"""
    if kind == "linear":
        return linear.terrain_points(plan, s)
    return wpml.terrain_points(plan, s) + [tuple(p[:2]) for p in s.polygon]


def terrain_source(request, required=True):
    """The request's terrain_source: "lidar" (the default) or "cop30"; None when left out and not required (an older
    page: the kept terrain is taken whatever it was made from)"""
    source = request.data.get("terrain_source") if isinstance(request.data, dict) else None
    if source is None:
        return "lidar" if required else None
    if source not in lidar_terrain.SOURCES:
        raise RequestError("terrain_source must be lidar or cop30")
    return source


def building_response(e):
    """202 while the lidar units a terrain needs are built: the editor shows their progress and asks again"""
    done = sum(1 for st in e.states if st["state"] in ("done", "none"))
    return Response({"building": True, "states": e.states, "done": done, "units": len(e.states)},
                    status=status.HTTP_202_ACCEPTED)


def route_terrain(request, kind, plan, s, source=None):
    """The (GeoTIFF bytes, name) of the terrain cached on the request's route (its route_id), or None when the route
    has none, it does not cover the plan, or it was made for another terrain source than `source` (when given)"""
    route_id = request.data.get("route_id")
    if isinstance(route_id, bool) or not isinstance(route_id, int):
        raise RequestError("route_id must be the id of the route: AGL over the terrain embeds the route's terrain")
    route = own_route(request, route_id)
    tif = route.read_terrain()
    if tif is None or not terrain.covers(tif, terrain_points(kind, plan, s)):
        return None
    if source is not None and not lidar_terrain.satisfies(route.terrain_info, source):
        return None
    return tif, route.terrain_info["name"]


def plan_terrain(request, kind, plan, s):
    """The GeoTIFF bytes of the route's cached terrain for the 3D view's heights of an AGL route over it, or None:
    not over a DSM, no route_id, no terrain yet, or one that does not cover the plan (the 3D view then draws the route
    above its own surface)"""
    if not uses_dsm(kind, s) or isinstance(request.data.get("route_id"), bool) or not isinstance(request.data.get("route_id"), int):
        return None
    try:
        found = route_terrain(request, kind, plan, s)
    except Http404:
        return None
    return found[0] if found else None


def own_route(request, pk, route_types=None):
    """The request's user's route of that id (of one of route_types if given), or a 404: a route of someone else's is
    not found, not forbidden"""
    route = routes.get_for(request.user, pk)
    if route is None or (route_types is not None and route.route_type not in route_types):
        raise Http404("No such route")
    return route


class RouteSerializer(serializers.Serializer):
    """A route as the API shows it and the fields a client sets (never its owner)"""
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255)
    route_type = serializers.ChoiceField(choices=ROUTE_TYPES, default="area")
    model = serializers.ChoiceField(choices=AIRCRAFT_MODELS, default="m4t")
    settings = serializers.JSONField(default=dict)
    terrain_info = serializers.JSONField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def validate_settings(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("The settings must be a JSON object")
        return value


def create_route(owner, data):
    """A new route of owner's from a request's fields, or a ValidationError (400)"""
    serializer = RouteSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    if serializer.validated_data["route_type"] not in SUPPORTED_ROUTE_TYPES:
        raise ValidationError({"route_type": "%s is not available yet" % serializer.validated_data["route_type"]})
    try:
        check_route_type(serializer.validated_data["route_type"], serializer.validated_data["model"])
    except RequestError as e:
        raise ValidationError({"route_type": str(e)})
    return routes.create(owner, **serializer.validated_data)


class RouteListCreateView(APIView):
    """GET: this user's routes, most recently updated first. POST: create one (a route type of SUPPORTED_ROUTE_TYPES)."""
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        return Response(RouteSerializer(routes.list_for(request.user), many=True).data)

    def post(self, request):
        route = create_route(request.user, request.data)
        return Response(RouteSerializer(route).data, status=status.HTTP_201_CREATED)


class RouteDetailView(APIView):
    """GET/PATCH/PUT/DELETE a single route. 404s (not 403) for a route owned by someone else."""
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk):
        return Response(RouteSerializer(own_route(request, pk)).data)

    def put(self, request, pk):
        return self.update(request, pk, partial=False)

    def patch(self, request, pk):
        return self.update(request, pk, partial=True)

    def update(self, request, pk, partial):
        route = own_route(request, pk)
        serializer = RouteSerializer(route, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        # only the fields the request sends: on a PUT the serializer fills in its defaults (an area route, the M4T,
        # empty settings) for the others, which would wipe the route
        sent = request.data if isinstance(request.data, dict) else {}
        fields = {name: value for name, value in serializer.validated_data.items() if name in sent}
        # The aircraft model drives the flight lines, camera footprint and exported file - changing it on an
        # existing route would silently mix settings planned for two different aircraft. Start a new route instead.
        if fields.get("model", route.model) != route.model:
            raise ValidationError({"model": "The aircraft model cannot be changed after the route is created"})
        # the type chooses the editor and the shape of the settings: a route of another type is a new route
        if fields.get("route_type", route.route_type) != route.route_type:
            raise ValidationError({"route_type": "The route type cannot be changed after the route is created"})
        for name, value in fields.items():
            setattr(route, name, value)
        try:
            route.save(tuple(fields))
        except RouteGone:
            raise Http404("No such route")
        return Response(RouteSerializer(route).data)

    def delete(self, request, pk):
        own_route(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def is_on(value):
    """A checkbox of the saved form ("true"/"false", as route_form.js writes them)"""
    return value is True or value in ("true", "1")


def copied_settings(settings, source_model, model, route_type="area"):
    """
    A route's saved settings (the planner's form, metric) for a copy flown by another aircraft model.

    The copy keeps the visible ground sample distance: its height is the source's times the ratio of the two wide
    cameras' GSD per meter (kept within MIN_HEIGHT..MAX_HEIGHT). A route without the visible camera (thermal only on
    an M4T) keeps its height. The cameras follow the model: the copy takes photos with the wide camera only, and on
    an M4T the thermal camera is offered but left off. Real-time follow becomes the terrain model on a model without
    it. Everything else (overlaps, direction, speed...) is kept.

    A waypoint route keeps its heights: its points are where to fly, not a ground sample distance. A linear route
    flown as a single line has no height of its own (the strip's width sets it): only the cameras change.
    """
    settings = dict(settings)
    if model == source_model:
        return settings
    visible = (is_on(settings.get("lens_visible", True)) and route_type != "waypoint"
               and not (route_type == "linear" and is_on(settings.get("single_line", False))))
    try:
        height = float(settings.get("height", DEFAULTS["height"]))
    except (TypeError, ValueError):
        height = None
    if visible and height is not None and math.isfinite(height):
        ratio = (ground_sample_distance(CAMERAS_BY_MODEL[source_model]["visable"], 1.0) /
                 ground_sample_distance(CAMERAS_BY_MODEL[model]["visable"], 1.0))
        settings["height"] = "%g" % round(min(MAX_HEIGHT, max(MIN_HEIGHT, height * ratio)), 2)
    settings["lens_visible"] = "true"
    settings["lens_ir"] = "false"
    if not DRONES[model].realtime_follow and settings.get("surface_follow", "realtime") == "realtime":
        settings["surface_follow"] = "dsm"      # the model flies AGL over the terrain model only
    if djifly.is_djifly(model) and settings.get("collection_mode") == "oblique":
        settings["collection_mode"] = "ortho"   # DJI Fly takes ortho photos only (djifly.check)
    return settings


class RouteCopyView(APIView):
    """POST routes/<pk>/copy {model}: create a new route from an existing one, for the given aircraft.
    Same model as the original: an exact copy. A different model: re-planned for that aircraft's cameras
    (see copied_settings)."""
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, pk):
        source = own_route(request, pk)
        model = request.data.get('model', source.model)
        if not wpml.known(model, CAMERAS_BY_MODEL):
            raise ValidationError({"model": "Unknown aircraft model %r" % (model,)})

        try:
            check_route_type(source.route_type, model)
        except RequestError as e:
            raise ValidationError({"model": str(e)})
        if djifly.is_djifly(model) and source.route_type == "waypoint" and (source.settings or {}).get("shape"):
            raise ValidationError({"model": "DJI Fly missions cannot face a point of interest from this planner yet"})
        settings = copied_settings(source.settings, source.model, model, source.route_type)
        route = create_route(request.user, {"name": source.name + " (copy)", "route_type": source.route_type,
                                            "model": model, "settings": settings})
        return Response(RouteSerializer(route).data, status=status.HTTP_201_CREATED)


class RouteImportView(APIView):
    """POST routes/import, multipart with "file": a Pilot 2 area, linear, slope, geometric or waypoint mission (.kmz) as a
    new route
    (missions/kmz_import.py). 201 with the route and its plan summary, or 400 with why the file cannot be
    imported, in which case nothing is created. A mission over the elevation model (DSM) in the file keeps that DSM
    as the route's terrain."""
    permission_classes = (permissions.IsAuthenticated,)
    MAX_SIZE = 50 * 1024 * 1024

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"error": "No file was sent"}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > self.MAX_SIZE:
            return Response({"error": "The file is too large for a mission"}, status=status.HTTP_400_BAD_REQUEST)
        data = upload.read()
        if kml.is_kml(data):
            return self.plain_kml(request, data, route_name(upload.name))
        try:
            template = read_template(data)
            model, settings, body = read_kmz_route(data, route_name(upload.name), template)
            kind = body["route_type"]
            check_route_type(kind, model)
            if kind == "waypoint":
                s = parse_waypoint_settings(body)
                plan_summary = waypoint_summary(waypoints.plan(s), s)
            elif kind == "linear":
                s = parse_linear_settings(body)
                plan_summary = linear_summary(linear.plan(s), s)
            elif kind == "slope":
                s = parse_slope_settings(body)
                plan_summary = slope_summary(slope.plan(s), s)
            elif kind == "geometric":
                s = parse_geometric_settings(body)
                plan_summary = geometric_summary(geometric.plan(s), s)
            else:
                s = parse_settings(body)
                plan_summary = summary(wpml.plan_from_settings(s), s)
            dsm = read_kmz_dsm(data, template) if kind in ("area", "linear") and uses_dsm(kind, s) else None
        except (KmzImportError, RequestError, PlanError, wpml.ExportError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        route = create_route(request.user, {"name": settings["name"], "route_type": kind, "model": model,
                                            "settings": settings})
        if dsm is not None:
            route.save_terrain(*dsm)
        return Response(dict(RouteSerializer(route).data, summary=plan_summary), status=status.HTTP_201_CREATED)


    def plain_kml(self, request, data, name):
        """A plain KML or KMZ (not a DJI mission): its first shape as a new route of the model the request names"""
        model = request.data.get("model", "m4t")
        if not wpml.known(model, CAMERAS_BY_MODEL):
            return Response({"error": "Unknown aircraft model %r" % (model,)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            kind, settings = kml.read_kml(data, name)
            check_route_type(kind, model)
        except (KmzImportError, RequestError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        settings = dict(settings, lens_visible="true", lens_ir="true" if "ir" in CAMERAS_BY_MODEL[model] else "false")
        route = create_route(request.user, {"name": settings["name"], "route_type": kind, "model": model, "settings": settings})
        return Response(dict(RouteSerializer(route).data, summary=None), status=status.HTTP_201_CREATED)


class RouteElevationView(APIView):
    """The ground elevation at a route's takeoff point, for the ASL height mode (missions/elevation.py).

    GET routes/<pk>/elevation: the last successfully fetched value for this route, or 404 if none yet - lets the
    frontend know whether "use cached" can be offered without fetching again.
    POST routes/<pk>/elevation {lat, lon}: fetch a fresh value from OpenTopography and cache it on the route
    (overwriting any previous one - see upcoming-changes.md: a single latest cache per route, by design). A fetch
    failure (network, rate limit, bad key) leaves the existing cache untouched and returns 502, so the frontend can
    still fall back to GET's cached value.
    """
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk):
        route = own_route(request, pk)
        cached = route.takeoff_elevation
        if cached is None:
            return Response({"error": "No cached elevation for this route yet"}, status=status.HTTP_404_NOT_FOUND)
        return Response(cached)

    def post(self, request, pk):
        route = own_route(request, pk)
        lat, lon = request.data.get("lat"), request.data.get("lon")
        if (isinstance(lat, bool) or isinstance(lon, bool) or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float))
                or not math.isfinite(lat) or not math.isfinite(lon) or not (-85 <= lat <= 85) or not (-180 <= lon <= 180)):
            return Response({"error": "lat/lon must be numbers (lat between -85 and 85, lon between -180 and 180)"},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            elevation = fetch_ground_elevation(lat, lon)
        except ElevationError as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        cached = {"lat": lat, "lon": lon, "orthometric": elevation["orthometric"], "ellipsoidal": elevation["ellipsoidal"],
                  "fetched_at": time.time()}
        route.takeoff_elevation = cached
        try:
            route.save(("takeoff_elevation",))         # only this field: a Save made during the fetch stays as it is
        except RouteGone:
            raise Http404("No such route")
        return Response(cached)


class RoutePointElevationsView(APIView):
    """POST routes/<pk>/point-elevations {points: [[lat, lon], ...]}: the WGS84-ellipsoidal ground height under each
    point of a waypoint route flown above the ground (AGL), {elevations: [...]} in the same order: the cell of the
    route's terrain each point falls in. When the route has no terrain covering the points (or one made for another
    terrain_source), it is fetched around them first (lidar_terrain.py: the lidar surface or COP30, at most 10 km on a
    side) and kept on the route; 202 while its lidar units are built. The editor asks only for the points it has no
    ground height for yet, and keeps them in the route's points. 502 when the terrain cannot be fetched."""
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, pk):
        route = own_route(request, pk, ("waypoint",))
        points = request.data.get("points") if isinstance(request.data, dict) else None
        if (not isinstance(points, list) or not points
                or any(not isinstance(p, list) or len(p) != 2 or not all(wpml.is_number(v) for v in p)
                       or not (-85 <= p[0] <= 85 and -180 <= p[1] <= 180) for p in points)):
            return Response({"error": "points must be [latitude, longitude] pairs"}, status=status.HTTP_400_BAD_REQUEST)
        points = [(lon, lat) for lat, lon in points]
        try:
            source = terrain_source(request)
        except RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        tif = route.read_terrain()
        if tif is not None and (not terrain.covers(tif, points, radius=0)
                                or not lidar_terrain.satisfies(route.terrain_info, source)):
            tif = None
        try:
            if tif is None:
                tif, info = lidar_terrain.fetch(points, source)
                route.save_terrain(tif, info)
            elevations = terrain.grounds_at(tif, points)
        except lidar_terrain.Building as e:
            return building_response(e)
        except terrain.TerrainError as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        except RouteGone:
            raise Http404("No such route")
        return Response({"elevations": elevations})


class RouteTerrainView(MissionView):
    """POST routes/<pk>/terrain, with the body of plan/export: fetch the ground under an area or linear route flown
    over the terrain (uses_dsm)
    (lidar_terrain.py: the lidar surface or COP30, as terrain_source says) and keep it on the route, replacing the one
    before; returns the route's terrain_info, or 202 while its lidar units are built (the editor asks again). A
    failed fetch leaves the cached terrain as it was and returns 502, with cached_covers saying whether the cached
    terrain still covers the plan (so the export can go on with it)."""

    def post(self, request, pk):
        route = own_route(request, pk, ("area", "linear"))
        try:
            kind, plan, s = self.load(request, strict=True)
        except (RequestError, PlanError, wpml.ExportError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if kind != route.route_type:
            return Response({"error": "The route is a %s route" % route.route_type}, status=status.HTTP_400_BAD_REQUEST)
        if not uses_dsm(kind, s):
            return Response({"error": "Only an AGL route with the DSM follow (or oblique) flies over the terrain"},
                            status=status.HTTP_400_BAD_REQUEST)

        points = terrain_points(kind, plan, s)
        try:
            source = terrain_source(request)
        except RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            tif, info = lidar_terrain.fetch(points, source)
        except lidar_terrain.Building as e:
            return building_response(e)
        except terrain.TerrainError as e:
            cached = route.read_terrain()
            cached_covers = cached is not None and terrain.covers(cached, points)
            return Response({"error": str(e), "cached_covers": cached_covers}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            route.save_terrain(tif, info)
        except RouteGone:
            raise Http404("No such route")
        return Response(route.terrain_info)


class FaceHeightsView(APIView):
    """POST face-heights {corners: [[longitude, latitude], ...]}: the height of a slope's corners in each processed
    task the user can see whose DSM covers them all, {tasks: [{id, project, name, heights, source}, ...]}, the most
    recent first. The heights are those of the task's DSM (or DTM), as ODM writes them from the photos' GPS: for a
    Matrice 4T, WGS84-ellipsoidal, the heights a slope route's corners have (checked on tasks flown where Pilot 2's
    samples were)."""
    permission_classes = (permissions.IsAuthenticated,)
    MAX_TASKS = 20

    def post(self, request):
        corners = request.data.get("corners") if isinstance(request.data, dict) else None
        if (not isinstance(corners, list) or not (1 <= len(corners) <= slope.MAX_CORNERS)
                or any(not isinstance(c, list) or len(c) != 2 or not all(wpml.is_number(v) for v in c)
                       or not (-180 <= c[0] <= 180 and -85 <= c[1] <= 85) for c in corners)):
            return Response({"error": "corners must be a list of at most %d [longitude, latitude]" % slope.MAX_CORNERS},
                            status=status.HTTP_400_BAD_REQUEST)

        outline = MultiPoint([Point(lon, lat) for lon, lat in corners]).envelope
        found = []
        for task in tasks_covering(request.user, outline, self.MAX_TASKS):
            if not task.epsg:
                continue
            to_utm = Transformer.from_crs(4326, task.epsg, always_xy=True)
            heights, source = surface.surface_heights(task, np.array([to_utm.transform(lon, lat) for lon, lat in corners]))
            if heights is None or not np.isfinite(heights).all():
                continue
            found.append({"id": str(task.id), "project": task.project.id, "project_name": task.project.name,
                          "name": task.name or str(task.id), "heights": [round(float(h), 3) for h in heights],
                          "source": source})
        return Response({"tasks": found})


class BlockHeightsView(APIView):
    """POST block-heights {outline: [[longitude, latitude], ...]}: the heights of a block's base and top in each
    processed task the user can see whose DSM covers it and the ground round it, {tasks: [{id, project, name, base, top,
    source}, ...]}, the most recent first. The base is the lowest ground on a ring RING meters outside the outline, the
    top the highest point inside it, both WGS84-ellipsoidal as FaceHeightsView's."""
    permission_classes = (permissions.IsAuthenticated,)
    MAX_TASKS = 20
    RING = 1.5          # meters outside the outline
    STEP = 0.5          # meters between the points read, along the ring and inside the outline
    MAX_POINTS = 20000

    def post(self, request):
        try:
            outline = parse_outline(request.data)
        except RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if len(outline) < 3:
            return Response({"error": "The outline needs at least 3 corners"}, status=status.HTTP_400_BAD_REQUEST)
        area = Polygon([tuple(c) for c in outline] + [tuple(outline[0])])
        if not area.valid:
            return Response({"error": "The outline crosses itself"}, status=status.HTTP_400_BAD_REQUEST)

        # The DSM must reach past the ring: 5e-5 degrees is 5.5 m of latitude, and more than 2 m of longitude up to 65 degrees
        reach = area.envelope.buffer(5e-5)
        found = []
        for task in tasks_covering(request.user, reach, self.MAX_TASKS):
            if not task.epsg:
                continue
            ring, inside = self.sample_points(outline, task.epsg)
            heights, source = surface.surface_heights(task, np.concatenate([ring, inside]))
            if heights is None:
                continue
            ground, roof = heights[:len(ring)], heights[len(ring):]
            if not (np.isfinite(ground).mean() >= 0.9 and np.isfinite(roof).any()):
                continue
            found.append({"id": str(task.id), "project": task.project.id, "project_name": task.project.name,
                          "name": task.name or str(task.id), "base": round(float(np.nanmin(ground)), 3),
                          "top": round(float(np.nanmax(roof)), 3), "source": source})
        return Response({"tasks": found})

    def sample_points(self, outline, epsg):
        """(ring, inside): UTM points every STEP meters on the ring RING meters outside the outline (a list of
        [longitude, latitude]), and on a grid inside it, each at most MAX_POINTS (wider apart for a large outline). The
        grid is spaced by the outline's box, not its area: a long thin outline across its box would have millions of
        cells tested."""
        to_utm = Transformer.from_crs(4326, epsg, always_xy=True)
        corners = [to_utm.transform(lon, lat) for lon, lat in outline]
        utm = Polygon(corners + [corners[0]])
        ring = utm.buffer(self.RING).exterior_ring
        count = min(self.MAX_POINTS, max(8, int(ring.length / self.STEP)))
        ring_points = np.array([ring.interpolate(ring.length * i / count).coords for i in range(count)])
        xmin, ymin, xmax, ymax = utm.extent
        step = max(self.STEP, math.sqrt((xmax - xmin) * (ymax - ymin) / self.MAX_POINTS))
        xs, ys = np.meshgrid(np.arange(xmin + step / 2, xmax, step), np.arange(ymin + step / 2, ymax, step))
        prepared = utm.prepared
        inside = np.array([(x, y) for x, y in zip(xs.ravel(), ys.ravel()) if prepared.contains(Point(x, y))])
        if not len(inside):
            inside = np.array([utm.point_on_surface.coords])
        return ring_points, inside


def tasks_covering(user, area, limit):
    """The processed tasks the user can see whose DSM covers area (a GEOS geometry in longitude and latitude), the
    most recent first, at most limit. The DSM's extent is compared here, not in the query: WebODM keeps it as
    GeoJSON, without PostGIS. Only the tasks with a DSM or DTM to read (surface.surface_heights), and only the fields
    the callers read."""
    projects = get_objects_for_user(user, "view_project", Project, accept_global_perms=False)
    tasks = (Task.objects.filter(project__in=projects, project__deleting=False, dsm_extent__isnull=False,
                                 available_assets__overlap=["dsm.tif", "dtm.tif"])
             .select_related("project").only("id", "name", "epsg", "dsm_extent", "project__id", "project__name")
             .order_by("-created_at"))
    found = []
    for task in tasks.iterator():
        extent = dsm_extent(task)
        if extent is not None and extent.contains(area):
            found.append(task)
            if len(found) == limit:
                break
    return found


def dsm_extent(task):
    """A task's DSM extent as a GEOS polygon (longitude and latitude), None when it has none that reads"""
    extent = task.dsm_extent
    try:                                            # a GeoJSON polygon
        if extent.get("type") != "Polygon":
            return None
        return Polygon(*[[(float(x), float(y)) for x, y, *_ in ring] for ring in extent["coordinates"]])
    except (AttributeError, KeyError, TypeError, ValueError, IndexError):
        return None


def parse_lidar_bounds(value):
    """[west, south, east, north] from a list of 4 numbers or "w,s,e,n"; RequestError otherwise"""
    if isinstance(value, str):
        value = value.split(",")
    try:
        if not isinstance(value, (list, tuple)) or len(value) != 4 or any(isinstance(v, bool) for v in value):
            raise ValueError
        out = [float(v) for v in value]
        if not all(math.isfinite(v) for v in out):
            raise ValueError
    except (TypeError, ValueError):
        raise RequestError("bounds must be [west, south, east, north]") from None
    return out


class LidarSurfaceView(APIView):
    """The lidar surface of the 3D view (lidar.py), shared by place. POST lidar/surface {"bounds": [w, s, e, n]} (what
    the route covers, in degrees) queues the units around it that need a build; GET lidar/surface?bounds=w,s,e,n
    answers their states. Both answer {"units": [{"x", "y", "state", "message"}]}; 400 when the area is too large."""
    permission_classes = (permissions.IsAuthenticated,)

    def units(self, raw):
        try:
            return lidar.units_for(parse_lidar_bounds(raw)), None
        except (RequestError, lidar.LidarError) as e:
            return None, Response({"error": str(e), "too_large": isinstance(e, lidar.TooLarge)}, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request):
        units, refused = self.units(request.query_params.get("bounds"))
        return refused or Response({"units": lidar.states(units)})

    def post(self, request):
        units, refused = self.units(request.data.get("bounds") if isinstance(request.data, dict) else None)
        return refused or Response({"units": lidar.request(units)})


class LidarTileView(APIView):
    """GET lidar/tiles/<z>/<x>/<y>.png: a tile of the lidar surface (Terrarium), 404 where none is built"""
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, z, x, y):
        path = lidar.tile_path(int(z), int(x), int(y))
        if path is None:
            raise Http404("No lidar tile here")
        try:
            with open(path, "rb") as f:
                response = HttpResponse(f.read(), content_type="image/png")
        except FileNotFoundError:
            raise Http404("No lidar tile here")     # removed by the lidar folder's cap since it was found
        response["Cache-Control"] = "private, max-age=3600"
        return response
