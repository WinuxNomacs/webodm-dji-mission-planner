"""
Waypoint routes of the mission planner: missions/waypoints.py, their import from Pilot 2
(missions/kmz_import.py) and the plugin's API for them (api.py).
"""
import json
import re
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase
import numpy as np

from ..missions import terrain, waypoints
from ..missions.kmz_import import KmzImportError, read_kmz_route
from ..missions.wpml import ExportError
from .. import routes
from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase
from .test_mission_kmz_import import files, sample
from .test_mission_planner_plugin import terrain_info
from .test_mission_planning import LAT0, LON0
from .test_mission_terrain import geotiff

API = "/api/plugins/mission_planner/"
from .. import api as mission_planner_api
NOW = 1700000000


def square(n=4, step=0.0005):
    """n points around a square near (LAT0, LON0)"""
    corners = [(0, 0), (0, 1), (1, 1), (1, 0)]
    # To 9 decimals, as an imported point is kept
    return [{"lat": round(LAT0 + corners[i % 4][0] * step, 9), "lon": round(LON0 + corners[i % 4][1] * step, 9)}
            for i in range(n)]


def body(**over):
    b = {"route_type": "waypoint", "model": "m4t", "name": "luxodm-waypoints", "cameras": ["visable", "ir"],
         "points": square(), "height": 60, "height_mode": "alt", "speed": 5, "turn_mode": "stop",
         "rth_height": 100, "takeoff_security_height": 20}
    b.update(over)
    return b


def route(**over):
    return mission_planner_api.parse_waypoint_settings(body(**over))


def wpml_values(data, tag, name="wpmz/waylines.wpml"):
    return re.findall(r"<wpml:%s>([^<]*)</wpml:%s>" % (tag, tag), files(data)[name].decode())


class TestWaypointSettings(SimpleTestCase):
    def test_a_route_needs_at_least_2_points_and_has_no_upper_limit(self):
        with self.assertRaisesRegex(ExportError, "at least 2 points"):
            route(points=square(1))
        self.assertEqual(len(route(points=square(500)).points), 500)

    def test_a_point_with_settings_the_planner_does_not_know_is_refused(self):
        points = square()
        points[1]["zoom"] = 24
        with self.assertRaisesRegex(ExportError, "Point 2 has unknown settings: zoom"):
            route(points=points)

    def test_the_hover_and_the_gimbal_pitch_of_a_point_are_kept_within_their_limits(self):
        points = square()
        points[2]["hover"] = 901
        with self.assertRaisesRegex(ExportError, "hover at point 3"):
            route(points=points)
        points[2] = dict(square()[2], pitch=-91)
        with self.assertRaisesRegex(ExportError, "gimbal pitch of point 3"):
            route(points=points)

    def test_the_asl_mode_needs_both_ground_heights_at_the_takeoff_point(self):
        with self.assertRaisesRegex(ExportError, "ground height at the takeoff point"):
            route(height_mode="asl", height=300)
        with self.assertRaisesRegex(ExportError, "ellipsoidal ground height"):
            route(height_mode="asl", height=300, takeoff_ref_point=[LAT0, LON0, 210])
        with self.assertRaisesRegex(ExportError, "only applies to the ASL"):
            route(takeoff_ellipsoidal_height=176)

    def test_asl_heights_are_flown_with_the_takeoff_points_ellipsoid_offset(self):
        s = route(height_mode="asl", height=300, takeoff_ref_point=[LAT0, LON0, 210], takeoff_ellipsoidal_height=176)
        self.assertEqual(waypoints.execute_heights(s), [266.0] * 4)

    def test_agl_heights_add_the_ground_under_each_point_and_need_it_to_export(self):
        s = route(height_mode="agl")
        self.assertEqual(waypoints.execute_heights(s, strict=False), [60.0] * 4)
        with self.assertRaisesRegex(ExportError, "fetch the elevations first"):
            waypoints.build_kmz(s, now=NOW)
        s = route(height_mode="agl", points=[dict(p, ground=150 + i) for i, p in enumerate(square())])
        self.assertEqual(waypoints.execute_heights(s), [210.0, 211.0, 212.0, 213.0])
        self.assertEqual(wpml_values(waypoints.build_kmz(s, now=NOW), "executeHeight"), ["210", "211", "212", "213"])


class TestWaypointPlan(SimpleTestCase):
    def test_the_plan_counts_the_photos_the_hovers_and_the_time_at_each_stop(self):
        points = square()
        points[1].update(photo=True, hover=10)
        points[2].update(photo=True)
        stop, passing = route(points=points), route(points=points, turn_mode="pass")
        self.assertEqual(stop.points[1].hover, 10)
        p = waypoints.plan(stop)
        self.assertEqual(p.photos, 2)
        # 4 stops, and the hover at point 2
        self.assertAlmostEqual(p.duration, p.length / 5 + 4 * waypoints.POINT_TIME + 10)
        # Passing, only the ends and the points with actions take time
        q = waypoints.plan(passing)
        self.assertAlmostEqual(q.length, p.length)
        self.assertAlmostEqual(q.duration, p.duration)
        self.assertAlmostEqual(waypoints.plan(route(points=square(), turn_mode="pass")).duration,
                               p.length / 5 + 2 * waypoints.POINT_TIME)

    def test_a_passing_route_rounds_its_corners_by_a_third_of_the_shorter_leg_and_stops_at_its_ends(self):
        points = square(3)
        points[2]["lat"] += 0.0005          # a second leg twice as long as the first
        data = waypoints.build_kmz(route(points=points, turn_mode="pass"), now=NOW)
        damping = [float(v) for v in wpml_values(data, "waypointTurnDampingDist")]
        first = waypoints.legs(route(points=points), [60.0] * 3)[0]
        self.assertEqual(damping[0], 0)
        self.assertAlmostEqual(damping[1], first / 3, places=6)
        self.assertEqual(damping[2], 0)
        modes = wpml_values(data, "waypointTurnMode")
        self.assertEqual(modes, [waypoints.STOP, waypoints.TURN_MODES["pass"], waypoints.STOP])

    def test_the_gimbal_is_tilted_only_at_the_first_point_and_where_a_point_has_its_own_pitch(self):
        points = square()
        points[2]["pitch"] = -45
        data = waypoints.build_kmz(route(points=points, gimbal_pitch=-90), now=NOW)
        self.assertEqual(wpml_values(data, "gimbalPitchRotateAngle"), ["-90", "-45"])
        self.assertEqual(wpml_values(waypoints.build_kmz(route(), now=NOW), "gimbalPitchRotateAngle"), [])

    def test_the_warnings_say_how_the_height_is_measured_and_when_the_return_height_is_too_low(self):
        self.assertEqual(len(waypoints.mission_warnings(route())), 1)
        warnings = waypoints.mission_warnings(route(rth_height=65))
        self.assertIn("return height (65 m) is not well above the flight height (60 m)", warnings[1])
        self.assertIn("public elevation data", waypoints.mission_warnings(route(height_mode="agl"))[0])


class TestWaypointPilot2Samples(SimpleTestCase):
    def test_the_m4e_sample_imports_with_its_points_and_settings(self):
        model, settings, b = read_kmz_route(sample("m4e-test-waypoint.kmz"), "m4e-test-waypoint")
        self.assertEqual(model, "m4e")
        self.assertEqual((b["route_type"], b["height_mode"], b["turn_mode"], b["heading_mode"]),
                         ("waypoint", "asl", "pass", "manually"))
        self.assertEqual((settings["height"], settings["speed"], settings["lens_visible"], settings["lens_ir"]),
                         ("309", "5", "true", "false"))
        self.assertEqual(len(b["points"]), 7)
        self.assertEqual([p["heading"] is not None for p in b["points"]], [True] * 7)
        self.assertFalse(any(p["photo"] or p["hover"] or p["pitch"] is not None for p in b["points"]))

    def test_the_m4e_sample_plans_the_length_and_time_pilot_2_gives_it(self):
        _, _, b = read_kmz_route(sample("m4e-test-waypoint.kmz"), "m4e-test-waypoint")
        data = sample("m4e-test-waypoint.kmz")
        p = waypoints.plan(mission_planner_api.parse_waypoint_settings(b), strict=True)
        self.assertAlmostEqual(p.length, float(wpml_values(data, "distance")[0]), delta=0.5)
        self.assertAlmostEqual(p.duration, float(wpml_values(data, "duration")[0]), delta=2)

    def test_the_m4e_sample_is_flown_at_the_heights_pilot_2_writes(self):
        _, _, b = read_kmz_route(sample("m4e-test-waypoint.kmz"), "m4e-test-waypoint")
        theirs = [float(v) for v in wpml_values(sample("m4e-test-waypoint.kmz"), "executeHeight")]
        ours = waypoints.execute_heights(mission_planner_api.parse_waypoint_settings(b))
        for a, e in zip(ours, theirs):
            self.assertAlmostEqual(a, e, places=3)

    def test_missions_with_actions_the_planner_cannot_write_are_refused_with_the_points(self):
        with self.assertRaisesRegex(KmzImportError, "The video starts at point 2: the planner records it from the first "
                                                    "point to the last"):
            read_kmz_route(sample("m4t-test-waypoint.kmz"), "x")
        with self.assertRaisesRegex(KmzImportError, r"panoShot \(points 1, 3\); orientedShoot \(point 1\)"):
            read_kmz_route(sample("TestWaypointRoute.kmz"), "x")


POI = [round(LAT0 + 0.00025, 6), round(LON0 + 0.00025, 6)]


def poi_body(**over):
    return body(**dict(dict(heading_mode="towardPOI", poi=POI, gimbal_pitch=-45, turn_mode="curve"), **over))


def poi_reference():
    return read_kmz_route(sample("m4t-test-poi-waypoint.kmz"), "m4t-test-poi-waypoint")


def actions(data, name="wpmz/waylines.wpml"):
    """Each action group of the file: (trigger, start, end, its actions)"""
    groups = re.findall(r"<wpml:actionGroup>(.*?)</wpml:actionGroup>", files(data)[name].decode(), re.S)
    return [(re.search(r"<wpml:actionTriggerType>([^<]*)", g).group(1),
             int(re.search(r"<wpml:actionGroupStartIndex>([^<]*)", g).group(1)),
             int(re.search(r"<wpml:actionGroupEndIndex>([^<]*)", g).group(1)),
             re.findall(r"<wpml:actionActuatorFunc>([^<]*)", g)) for g in groups]


class TestPoiRoutes(SimpleTestCase):
    def test_a_toward_poi_route_needs_its_poi_and_cannot_turn_the_aircraft_at_a_point(self):
        with self.assertRaisesRegex(ExportError, "needs the POI's latitude and longitude"):
            route(heading_mode="towardPOI")
        points = square()
        points[2]["heading"] = 90
        with self.assertRaisesRegex(ExportError, r"cannot turn the aircraft at a point \(point 3\)"):
            route(heading_mode="towardPOI", poi=POI, points=points)
        self.assertIsNone(route(poi=POI).poi)

    def test_interval_photos_are_every_half_a_second_or_meter_to_900(self):
        for mode in ("distance", "time"):
            for bad in (0.4, 901, None):
                with self.subTest(mode=mode, interval=bad), self.assertRaisesRegex(ExportError, "photo interval"):
                    route(photo_interval_mode=mode, photo_interval=bad)
        with self.assertRaisesRegex(ExportError, "interval photo mode"):
            route(photo_interval_mode="every", photo_interval=2)

    def test_a_smooth_curve_takes_a_moment_at_each_point_it_flies_through(self):
        stop, passing, curve = (waypoints.plan(route(turn_mode=t)) for t in ("stop", "pass", "curve"))
        self.assertAlmostEqual(curve.length, passing.length)
        self.assertAlmostEqual(curve.duration, passing.duration + 2 * waypoints.CURVE_TIME)
        self.assertAlmostEqual(stop.duration, passing.duration + 2 * waypoints.POINT_TIME)

    def test_interval_photos_are_counted_from_the_first_point_over_the_length_or_the_time(self):
        p = waypoints.plan(route())
        by_distance = waypoints.plan(route(photo_interval_mode="distance", photo_interval=10))
        by_time = waypoints.plan(route(photo_interval_mode="time", photo_interval=2))
        self.assertEqual(by_distance.photos, int(p.length // 10) + 1)
        self.assertEqual(by_time.photos, int(p.duration // 2) + 1)

    def test_a_smooth_curve_flies_through_the_middle_points_on_a_curved_line(self):
        data = waypoints.build_kmz(route(turn_mode="curve"), now=NOW)
        self.assertEqual(wpml_values(data, "waypointTurnMode"),
                         [waypoints.STOP, waypoints.TURN_MODES["curve"], waypoints.TURN_MODES["curve"], waypoints.STOP])
        self.assertEqual(set(wpml_values(data, "useStraightLine")), {"0"})
        self.assertEqual(wpml_values(data, "globalUseStraightLine", "wpmz/template.kml"), ["0"])
        self.assertEqual(set(wpml_values(waypoints.build_kmz(route(turn_mode="pass"), now=NOW), "useStraightLine")), {"1"})

    def test_the_video_and_the_interval_photos_run_from_the_first_point_to_the_last(self):
        data = waypoints.build_kmz(route(video=True, photo_interval_mode="distance", photo_interval=5), now=NOW)
        self.assertEqual(actions(data), [("reachPoint", 0, 0, ["startRecord"]),
                                         ("multipleDistance", 0, 3, ["takePhoto"]),
                                         ("reachPoint", 3, 3, ["stopRecord"])])
        self.assertEqual(wpml_values(data, "actionTriggerParam"), ["5"])
        timed = waypoints.build_kmz(route(photo_interval_mode="time", photo_interval=2), now=NOW)
        self.assertEqual(actions(timed), [("multipleTiming", 0, 3, ["takePhoto"])])

    def test_a_toward_poi_route_holds_its_gimbal_and_eases_it_between_points(self):
        points = square()
        points[2]["pitch"] = -30
        data = waypoints.build_kmz(route(**dict(heading_mode="towardPOI", poi=POI, gimbal_pitch=-45, points=points)),
                                   now=NOW)
        self.assertEqual(wpml_values(data, "waypointHeadingMode"), ["towardPOI"] * 4)
        self.assertEqual(set(wpml_values(data, "waypointPoiPoint")), {"%.6f,%.6f,0.000000" % tuple(POI)})
        self.assertEqual(wpml_values(data, "gimbalPitchAngle", "wpmz/template.kml"), ["-45", "-45", "-30", "-30"])
        self.assertEqual(actions(data), [("reachPoint", 0, 0, ["gimbalRotate"])] +
                         [("betweenAdjacentPoints", i, i + 1, ["gimbalEvenlyRotate"]) for i in range(3)])
        self.assertEqual(wpml_values(data, "gimbalPitchRotateAngle"), ["-45", "-45", "-30", "-30"])
        self.assertIn("GPS", " ".join(waypoints.mission_warnings(route(heading_mode="towardPOI", poi=POI))))

    def test_stacked_loops_climb_on_the_spot_between_them_with_a_pitch_each(self):
        loop = square(5)
        points = [dict(p, height=h, pitch=pitch) for h, pitch in ((40, -20), (50, 0)) for p in loop]
        s = route(heading_mode="towardPOI", poi=POI, points=points)
        data = waypoints.build_kmz(s, now=NOW)
        self.assertEqual(wpml_values(data, "executeHeight"), ["40"] * 5 + ["50"] * 5)
        self.assertEqual(wpml_values(data, "gimbalPitchAngle", "wpmz/template.kml"), ["-20"] * 5 + ["0"] * 5)
        one_loop = waypoints.plan(route(heading_mode="towardPOI", poi=POI, points=[dict(p, height=40) for p in loop]))
        self.assertAlmostEqual(waypoints.plan(s).length, 2 * one_loop.length + 10)

    def test_the_pilot_2_poi_route_imports_with_its_poi_video_and_interval_photos(self):
        model, settings, b = poi_reference()
        self.assertEqual(model, "m4t")
        self.assertEqual((b["heading_mode"], b["turn_mode"], b["poi"], b["gimbal_pitch"], b["video"],
                          b["photo_interval_mode"], b["photo_interval"]),
                         ("towardPOI", "curve", [42.103394, -85.020373], -45, True, "time", 2))
        self.assertEqual((settings["video"], settings["photo_interval_mode"], settings["photo_interval"]),
                         ("true", "time", "2"))
        self.assertEqual(len(b["points"]), 8)

    def test_the_pilot_2_poi_route_plans_the_length_and_time_pilot_2_gives_it(self):
        data = sample("m4t-test-poi-waypoint.kmz")
        p = waypoints.plan(mission_planner_api.parse_waypoint_settings(poi_reference()[2]), strict=True)
        self.assertAlmostEqual(p.length, float(wpml_values(data, "distance")[0]), delta=0.5)
        self.assertAlmostEqual(p.duration, float(wpml_values(data, "duration")[0]), delta=0.5)

    def test_the_pilot_2_poi_route_exports_the_actions_and_the_gimbal_pilot_2_writes(self):
        theirs = sample("m4t-test-poi-waypoint.kmz")
        ours = waypoints.build_kmz(mission_planner_api.parse_waypoint_settings(poi_reference()[2]), now=NOW)
        for name in ("wpmz/template.kml", "wpmz/waylines.wpml"):
            with self.subTest(name):
                self.assertEqual(actions(ours, name), actions(theirs, name))
                for tag in ("waypointHeadingMode", "waypointPoiPoint", "waypointTurnMode", "useStraightLine",
                            "gimbalPitchAngle", "gimbalPitchRotateAngle", "gimbalRotateTime", "gimbalHeadingYawBase",
                            "actionTriggerParam", "fileSuffix", "payloadLensIndex", "positioningType"):
                    self.assertEqual(wpml_values(ours, tag, name), wpml_values(theirs, tag, name), tag)


class TestWaypointRoundTrip(SimpleTestCase):
    def round_trip(self, b):
        data = waypoints.build_kmz(mission_planner_api.parse_waypoint_settings(b), now=NOW)
        model, _, again = read_kmz_route(data, "luxodm-waypoints")
        self.assertEqual(model, b["model"])
        # The ground heights are not in the file: an imported AGL route fetches them again
        for p, original in zip(again["points"], b["points"]):
            p["ground"] = original.get("ground")
        self.assertEqual(files(waypoints.build_kmz(mission_planner_api.parse_waypoint_settings(again), now=NOW)),
                         files(data))
        return again

    def test_every_model_height_mode_and_turn_mode_exports_the_same_file_again(self):
        points = square()
        points[1].update(heading=45, pitch=-30, photo=True, hover=5, height=70)
        points[3].update(photo=True)
        for model, cameras in (("m4t", ["visable", "ir"]), ("m4t", ["visable"]), ("m4e", ["visable"])):
            for mode in ("alt", "asl", "agl"):
                for turn in ("stop", "pass"):
                    b = body(model=model, cameras=cameras, height_mode=mode, turn_mode=turn, gimbal_pitch=-90,
                             points=[dict(p) for p in points], heading_mode="manually" if turn == "pass" else "followWayline")
                    if mode == "asl":
                        b.update(height=300, takeoff_ref_point=[LAT0, LON0, 210], takeoff_ellipsoidal_height=176)
                        b["points"][1]["height"] = 310
                    if mode == "agl":
                        b["points"] = [dict(p, ground=150.5 + i) for i, p in enumerate(b["points"])]
                    with self.subTest(model=model, mode=mode, turn=turn):
                        again = self.round_trip(b)
                        self.assertEqual(again["points"][1]["photo"], True)
                        self.assertEqual(again["points"][1]["hover"], 5)

    def test_poi_curve_video_and_interval_routes_export_the_same_file_again(self):
        for turn in ("stop", "pass", "curve"):
            for interval in ((None, None), ("distance", 7.5), ("time", 2)):
                for b in (poi_body(turn_mode=turn), body(turn_mode=turn)):
                    b.update(video=True, photo_interval_mode=interval[0], photo_interval=interval[1])
                    with self.subTest(heading=b.get("heading_mode"), turn=turn, interval=interval[0]):
                        again = self.round_trip(b)
                        self.assertEqual((again["video"], again["photo_interval_mode"], again["poi"]),
                                         (True, interval[0], b.get("poi")))

    def test_the_pilot_2_poi_route_exports_and_imports_again_unchanged(self):
        self.round_trip(poi_reference()[2])

    def test_the_m4e_sample_exports_and_imports_again_unchanged(self):
        _, _, b = read_kmz_route(sample("m4e-test-waypoint.kmz"), "m4e-test-waypoint")
        self.round_trip(b)


class TestWaypointApi(BootTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.user = User.objects.get(username="testuser")
        self.other = User.objects.get(username="testuser2")

    def tearDown(self):
        for route in routes.all():
            route.delete()          # with its terrain folder
        disable_plugin("mission_planner")

    def post(self, path, data):
        return self.client.post(API + path, json.dumps(data), content_type="application/json")

    def test_the_plan_of_a_waypoint_route_has_its_summary_line_and_numbered_points(self):
        res = self.post("plan", body(height_mode="agl"))
        self.assertEqual(res.status_code, 200, res.content[:300])
        data = res.json()
        self.assertEqual((data["summary"]["points"], data["summary"]["photos"], data["summary"]["speed"]), (4, 0, 5))
        self.assertGreater(data["summary"]["length"], 100)
        self.assertEqual(len(data["lines"]["features"]), 1)
        self.assertEqual([f["properties"]["number"] for f in data["waypoints"]["features"]], [1, 2, 3, 4])

    def test_a_waypoint_route_exports_once_it_has_every_ground_height(self):
        res = self.post("export", body(height_mode="agl"))
        self.assertEqual(res.status_code, 400)
        self.assertIn("fetch the elevations first", res.json()["error"])
        res = self.post("export", body(points=[dict(p, ground=150) for p in square()], height_mode="agl"))
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res["Content-Disposition"], 'attachment; filename="luxodm-waypoints.kmz"')
        self.assertIn("wpmz/waylines.wpml", files(res.content))

    def test_malformed_values_are_refused_with_a_message_not_a_server_error(self):
        square_points = square()
        for bad in ({"model": [1]}, {"height_mode": []}, {"turn_mode": {}}, {"takeoff_mode": ["safe"]},
                    {"photo_interval_mode": [], "photo_interval": 5},
                    {"points": [{"lon": square_points[0]["lon"]}] + square_points[1:]}):
            with self.subTest(bad=bad):
                for path in ("plan", "export"):
                    res = self.post(path, body(**bad))
                    self.assertEqual(res.status_code, 400, (path, res.content[:200]))
                    self.assertIn("error", res.json())

    def test_an_unknown_route_type_is_refused(self):
        res = self.post("plan", body(route_type="mapping3d"))
        self.assertEqual(res.status_code, 400)
        self.assertIn("route_type", res.json()["error"])

    def test_a_pilot_2_waypoint_mission_is_imported_as_a_waypoint_route(self):
        res = self.client.post(API + "routes/import", {"file": SimpleUploadedFile("Tower.kmz", sample("m4e-test-waypoint.kmz"))})
        self.assertEqual(res.status_code, 201, res.content[:300])
        data = res.json()
        saved = routes.get(data["id"])
        self.assertEqual((saved.owner, saved.name, saved.route_type, saved.model), (self.user, "Tower", "waypoint", "m4e"))
        self.assertEqual(data["summary"]["points"], 7)

    def test_a_copy_of_a_waypoint_route_for_another_model_keeps_its_height(self):
        source = routes.create(owner=self.user, name="Tower", route_type="waypoint", model="m4t",
                                      settings={"height": "60", "lens_visible": "true", "lens_ir": "true"})
        res = self.post("routes/%d/copy" % source.id, {"model": "m4e"})
        self.assertEqual(res.status_code, 201, res.content[:300])
        data = res.json()
        self.assertEqual((data["route_type"], data["model"]), ("waypoint", "m4e"))
        self.assertEqual(data["settings"], {"height": "60", "lens_visible": "true", "lens_ir": "false"})

    def point_elevations(self, route_id, points):
        return self.post("routes/%d/point-elevations" % route_id, {"points": points, "terrain_source": "cop30"})

    def test_the_ground_under_each_point_is_the_cell_of_the_fetched_terrain_it_falls_in(self):
        mine = routes.create(owner=self.user, name="Tower", route_type="waypoint")
        # Heights rising 1 m a cell from west to east, from 200 m, around (LAT0, LON0)
        tif = geotiff(np.tile(200.0 + np.arange(72), (72, 1)), west=LON0 - 0.01, north=LAT0 + 0.01)
        points = [[LAT0, LON0 - 0.01 + 10.5 / 3600], [LAT0, LON0 - 0.01 + 3.5 / 3600]]
        with mock.patch.object(terrain, "fetch_terrain", return_value=(tif, terrain_info())) as fetch:
            res = self.point_elevations(mine.id, points)
            self.assertEqual(res.status_code, 200, res.content[:300])
            self.assertEqual(res.json(), {"elevations": [210, 203]})
            self.assertEqual(fetch.call_args[0][0], [(p[1], p[0]) for p in points])
            mine.refresh_from_db()
            self.assertEqual(mine.terrain_info["dataset"], "COP30")

            # The route's terrain answers the next points it covers, without a fetch
            res = self.point_elevations(mine.id, [[LAT0, LON0 - 0.01 + 20.5 / 3600]])
            self.assertEqual(res.json(), {"elevations": [220]})
            self.assertEqual(fetch.call_count, 1)

            # and is fetched again for a point outside it
            self.point_elevations(mine.id, [[LAT0 + 0.05, LON0]])
            self.assertEqual(fetch.call_count, 2)

    def test_point_elevations_are_refused_for_bad_points_other_routes_and_terrain_errors(self):
        mine = routes.create(owner=self.user, name="Tower", route_type="waypoint")
        area = routes.create(owner=self.user, name="Roof", route_type="area")
        theirs = routes.create(owner=self.other, name="Theirs", route_type="waypoint")
        with mock.patch.object(terrain, "fetch_terrain") as fetch:
            for points in ([], [[45]], [[95, 7]], [["45", 7]], "45,7"):
                with self.subTest(points=points[:2]):
                    self.assertEqual(self.point_elevations(mine.id, points).status_code, 400)
            self.assertEqual(self.point_elevations(area.id, [[45, 7]]).status_code, 404)
            self.assertEqual(self.point_elevations(theirs.id, [[45, 7]]).status_code, 404)
            fetch.assert_not_called()
        too_large = terrain.TerrainError("The route is too large to fetch its terrain: 12.0 by 0.4 km, at most 10 km on a side")
        with mock.patch.object(terrain, "fetch_terrain", side_effect=too_large):
            res = self.point_elevations(mine.id, [[45, 7], [45, 7.15]])
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.json(), {"error": str(too_large)})
        mine.refresh_from_db()
        self.assertFalse(mine.terrain)
