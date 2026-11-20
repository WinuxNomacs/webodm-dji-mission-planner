"""
Tests of the route's heights in the air (missions/air.py) that the 3D view draws the route at, and of the plan's
"air" through the API. The geoid's undulation is the real grid's (tests/fixtures/geoid, see tests/__init__.py).
"""
import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client

from .. import api as mission_planner_api
from .. import routes
from ..missions import air, geoid, geometric, linear, slope, wpml
from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase
from .test_mission_planner_plugin import API, body, terrain_info, terrain_tif
from .test_mission_planning import LAT0, LON0
from . import test_mission_geometric, test_mission_linear, test_mission_slope, test_mission_waypoints

TAKEOFF = [LAT0, LON0, 215.5]


def area(**over):
    s = mission_planner_api.parse_settings(body(**over))
    return wpml.plan_from_settings(s), s


def heights(result):
    return [p[2] for path in result["paths"] for p in path] + [p[2] for p in result["drops"]]


def middle(points):
    return geoid.undulation(sum(p[1] for p in points) / len(points), sum(p[0] for p in points) / len(points))


class TestAreaRoute(BootTestCase):
    def test_above_sea_level_every_point_is_at_the_takeoff_ground_plus_the_height_as_exported(self):
        plan, s = area(height_mode="EGM96", takeoff_ref_point=TAKEOFF, takeoff_ellipsoidal_height=181.8)
        result = air.area(plan, s)
        self.assertEqual(result["reference"], "sea")
        self.assertEqual(set(heights(result)), {wpml.asl_heights(s)[0]})
        self.assertEqual(set(heights(result)), {245.5})

    def test_the_path_is_each_pass_s_waypoints_and_the_drops_the_ends_of_its_lines(self):
        plan, s = area(height_mode="EGM96", takeoff_ref_point=TAKEOFF, takeoff_ellipsoidal_height=181.8)
        result = air.area(plan, s)
        self.assertEqual([[p[:2] for p in path] for path in result["paths"]],
                         [[[round(x, 7), round(y, 7)] for x, y in plan.nadir.waypoints]])
        ends = [pt for line in plan.nadir.lines for pt in (line[0], line[-1])]
        self.assertEqual([p[:2] for p in result["drops"]], [[round(x, 7), round(y, 7)] for x, y in ends])

    def test_an_oblique_route_has_a_path_for_each_of_its_five_passes(self):
        plan, s = area(height_mode="EGM96", takeoff_ref_point=TAKEOFF, takeoff_ellipsoidal_height=181.8,
                       collection_mode="oblique", gimbal_pitch=-45)
        self.assertEqual(len(air.area(plan, s)["paths"]), 5)

    def test_relative_to_the_takeoff_point_it_is_above_sea_level_with_the_takeoff_height(self):
        plan, s = area(height_mode="relativeToStartPoint", takeoff_ref_point=TAKEOFF)
        result = air.area(plan, s)
        self.assertEqual(result["reference"], "sea")
        self.assertEqual(set(heights(result)), {245.5})

    def test_relative_to_the_takeoff_point_without_its_height_it_is_above_the_takeoff_point(self):
        plan, s = area(height_mode="relativeToStartPoint")
        result = air.area(plan, s)
        self.assertEqual(result["reference"], "takeoff")
        self.assertEqual(set(heights(result)), {30.0})

    def test_agl_followed_in_real_time_is_above_the_surface(self):
        plan, s = area(height_mode="realTimeFollowSurface")
        result = air.area(plan, s, terrain_tif())
        self.assertEqual(result["reference"], "surface")
        self.assertEqual(set(heights(result)), {30.0})

    def test_agl_over_the_route_s_terrain_is_above_sea_level_as_the_export_flies_it(self):
        plan, s = area(height_mode="realTimeFollowSurface", surface_follow="dsm")
        result = air.area(plan, s, terrain_tif(ground=180.0))
        n = middle(plan.nadir.waypoints)
        self.assertEqual(result["reference"], "sea")
        for h in heights(result):
            self.assertAlmostEqual(h, 180.0 + 30.0 - n, places=2)
        self.assertAlmostEqual(n, -34.2, delta=0.1)        # where the samples were flown

    def test_agl_over_the_terrain_follows_its_highest_ground_near_each_point(self):
        plan, s = area(height_mode="realTimeFollowSurface", surface_follow="dsm")
        dsm = wpml.dsm_of(plan, s, terrain_tif(ground=180.0), "t.tif")
        result = air.area(plan, s, terrain_tif(ground=180.0))
        n = middle(plan.nadir.waypoints)
        self.assertEqual([p[2] for p in result["paths"][0]], [round(h - n, 2) for h in dsm.heights[0]])

    def test_agl_over_the_terrain_without_the_terrain_is_above_the_surface(self):
        plan, s = area(height_mode="realTimeFollowSurface", surface_follow="dsm")
        self.assertEqual(air.area(plan, s, None)["reference"], "surface")

    def test_agl_over_the_terrain_without_the_geoid_grid_is_above_the_surface(self):
        plan, s = area(height_mode="realTimeFollowSurface", surface_follow="dsm")
        with mock.patch.object(geoid, "undulation", side_effect=geoid.GeoidError("no grid")):
            result = air.area(plan, s, terrain_tif())
        self.assertEqual(result["reference"], "surface")
        self.assertEqual(set(heights(result)), {30.0})

    def test_agl_over_a_terrain_that_does_not_cover_the_route_is_above_the_surface(self):
        plan, s = area(height_mode="realTimeFollowSurface", surface_follow="dsm")
        far = terrain_tif(west=LON0 + 1.0, north=LAT0 + 1.0)
        self.assertEqual(air.area(plan, s, far)["reference"], "surface")


class TestLinearRoute(BootTestCase):
    def test_the_path_is_its_waypoints_and_the_drops_the_ends_of_its_lines_and_of_the_bend(self):
        s = test_mission_linear.route(height_mode="EGM96", takeoff_ellipsoidal_height=175.0)
        plan = linear.plan(s)
        result = air.linear_route(plan, s)
        self.assertEqual(len(result["paths"]), 1)
        self.assertEqual(len(result["paths"][0]), len(plan.waypoints))
        expected = len(plan.lines) * 2 + (2 if plan.bend is not None else 0)
        self.assertEqual(len(result["drops"]), expected)
        self.assertEqual(set(heights(result)), {round(wpml.asl_heights(s)[0], 2)})

    def test_relative_to_the_takeoff_point_it_is_above_sea_level_with_the_takeoff_height(self):
        s = test_mission_linear.route(height_mode="relativeToStartPoint")
        result = air.linear_route(linear.plan(s), s)
        self.assertEqual(result["reference"], "sea")
        self.assertEqual(set(heights(result)), {round(208.611125 + s.height, 2)})

    def test_agl_over_the_route_s_terrain_is_above_sea_level(self):
        s = test_mission_linear.route(height_mode="realTimeFollowSurface", surface_follow="dsm")
        plan = linear.plan(s)
        result = air.linear_route(plan, s, test_mission_linear.terrain_tif(ground=180.0))
        n = middle(plan.waypoints)
        self.assertEqual(result["reference"], "sea")
        for h in heights(result):
            self.assertAlmostEqual(h, 180.0 + s.height - n, places=2)


class TestWaypointRoute(BootTestCase):
    def test_alt_with_the_takeoff_height_is_above_sea_level_and_each_point_keeps_its_own_height(self):
        points = test_mission_waypoints.square()
        points[1]["height"] = 80
        s = test_mission_waypoints.route(points=points, takeoff_ref_point=TAKEOFF)
        result = air.waypoint_route(s)
        self.assertEqual(result["reference"], "sea")
        self.assertEqual([p[2] for p in result["paths"][0]], [275.5, 295.5, 275.5, 275.5])

    def test_every_point_has_a_line_down_to_the_surface(self):
        s = test_mission_waypoints.route(takeoff_ref_point=TAKEOFF)
        result = air.waypoint_route(s)
        self.assertEqual(result["drops"], result["paths"][0])

    def test_alt_without_the_takeoff_height_is_above_the_takeoff_point(self):
        result = air.waypoint_route(test_mission_waypoints.route())
        self.assertEqual(result["reference"], "takeoff")
        self.assertEqual(set(heights(result)), {60.0})

    def test_asl_is_above_sea_level(self):
        s = test_mission_waypoints.route(height_mode="asl", height=260, takeoff_ref_point=TAKEOFF,
                                         takeoff_ellipsoidal_height=181.8)
        result = air.waypoint_route(s)
        self.assertEqual(result["reference"], "sea")
        self.assertEqual(set(heights(result)), {260.0})

    def test_agl_with_every_point_s_ground_is_above_sea_level(self):
        points = [dict(p, ground=180.0 + i) for i, p in enumerate(test_mission_waypoints.square())]
        s = test_mission_waypoints.route(points=points, height_mode="agl")
        result = air.waypoint_route(s)
        n = middle([(p["lon"], p["lat"]) for p in points])
        self.assertEqual(result["reference"], "sea")
        for i, h in enumerate(p[2] for p in result["paths"][0]):
            self.assertAlmostEqual(h, 180.0 + i + 60.0 - n, places=2)

    def test_agl_with_a_point_without_its_ground_is_above_the_surface(self):
        points = [dict(p, ground=180.0) for p in test_mission_waypoints.square()]
        del points[2]["ground"]
        result = air.waypoint_route(test_mission_waypoints.route(points=points, height_mode="agl"))
        self.assertEqual(result["reference"], "surface")
        self.assertEqual(set(heights(result)), {60.0})

    def test_agl_without_the_geoid_grid_is_above_the_surface(self):
        points = [dict(p, ground=180.0) for p in test_mission_waypoints.square()]
        with mock.patch.object(geoid, "undulation", side_effect=geoid.GeoidError("no grid")):
            result = air.waypoint_route(test_mission_waypoints.route(points=points, height_mode="agl"))
        self.assertEqual(result["reference"], "surface")


class TestEllipsoidalRoutes(BootTestCase):
    def test_a_slope_route_is_above_sea_level_its_ellipsoidal_heights_less_the_undulation(self):
        plan = slope.plan(test_mission_slope.route())
        result = air.ellipsoidal(plan.waypoints, plan.lines)
        n = middle(plan.waypoints)
        self.assertEqual(result["reference"], "sea")
        self.assertEqual([p[2] for p in result["paths"][0]], [round(p[2] - n, 2) for p in plan.waypoints])
        self.assertEqual(len(result["drops"]), 2 * len(plan.lines))

    def test_a_building_route_has_lines_down_from_the_ends_of_its_roof_lines_and_loops(self):
        plan = geometric.plan(test_mission_geometric.route(roof=True))
        result = air.ellipsoidal(plan.waypoints, list(plan.roof) + list(plan.loops))
        self.assertEqual(len(result["drops"]), 2 * (len(plan.roof) + len(plan.loops)))
        self.assertEqual(len(result["paths"][0]), len(plan.waypoints))

    def test_without_the_geoid_grid_there_is_no_route_in_the_air(self):
        plan = slope.plan(test_mission_slope.route())
        with mock.patch.object(geoid, "undulation", side_effect=geoid.GeoidError("no grid")):
            self.assertIsNone(air.ellipsoidal(plan.waypoints, plan.lines))


class TestPlanApi(BootTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.user = User.objects.get(username="testuser")
        self.route = routes.create(owner=self.user, name="Mine", route_type="area")

    def tearDown(self):
        for route in routes.all():
            route.delete()
        disable_plugin("mission_planner")

    def plan(self, data):
        res = self.client.post(API + "plan", json.dumps(data), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content[:300])
        return res.json()

    def keep_terrain(self, route):
        with mock.patch.object(mission_planner_api.terrain, "fetch_terrain", return_value=(terrain_tif(), terrain_info())):
            res = self.client.post(API + "routes/%d/terrain" % route.id,
                                   json.dumps(body(height_mode="realTimeFollowSurface", surface_follow="dsm", route_id=route.id)),
                                   content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content[:300])

    def test_the_plan_of_each_route_type_has_its_route_in_the_air(self):
        self.assertEqual(self.plan(body())["air"]["reference"], "surface")
        self.assertEqual(self.plan(test_mission_waypoints.body())["air"]["reference"], "takeoff")
        self.assertEqual(self.plan(test_mission_slope.body())["air"]["reference"], "sea")
        self.assertEqual(self.plan(test_mission_geometric.body())["air"]["reference"], "sea")
        self.assertEqual(self.plan(test_mission_linear.body())["air"]["reference"], "takeoff")

    def test_agl_over_the_route_s_kept_terrain_is_above_sea_level(self):
        self.keep_terrain(self.route)
        data = self.plan(body(height_mode="realTimeFollowSurface", surface_follow="dsm", route_id=self.route.id))
        self.assertEqual(data["air"]["reference"], "sea")
        self.assertAlmostEqual(data["air"]["paths"][0][0][2], 180.0 + 30.0 - middle(
            [tuple(p) for p in data["air"]["paths"][0]]), delta=0.05)

    def test_agl_without_the_route_id_or_its_terrain_is_above_the_surface(self):
        agl = body(height_mode="realTimeFollowSurface", surface_follow="dsm")
        self.assertEqual(self.plan(agl)["air"]["reference"], "surface")
        self.assertEqual(self.plan(dict(agl, route_id=self.route.id))["air"]["reference"], "surface")

    def test_agl_with_someone_else_s_route_is_above_the_surface_and_says_nothing_of_it(self):
        other = routes.create(owner=User.objects.create_user("other", password="x1234567"), name="Theirs", route_type="area")
        self.client.logout()
        self.client.login(username="other", password="x1234567")
        self.keep_terrain(other)
        self.client.logout()
        self.client.login(username="testuser", password="test1234")
        data = self.plan(body(height_mode="realTimeFollowSurface", surface_follow="dsm", route_id=other.id))
        self.assertEqual(data["air"]["reference"], "surface")
