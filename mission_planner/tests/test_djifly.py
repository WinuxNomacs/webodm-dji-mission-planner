"""
Tests of the DJI Fly missions (missions/djifly.py, Phase 15d): the consumer drones, the file DJI Fly reads (as FlyPath
learnt it), area and linear routes as one waypoint per photo, heights above the takeoff point, the split into
missions of at most 200 points, and what DJI Fly cannot fly.
"""
import io
import json
import re
import zipfile

from django.test import Client, SimpleTestCase

from .. import api as mission_planner_api
from ..missions import djifly, drones, linear, terrain, wpml
from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase
from . import test_mission_kmz_import as area_kmz
from . import test_mission_linear as linear_kmz
from . import test_mission_waypoints as waypoint_kmz

API = "/api/plugins/mission_planner/"
DJIFLY = ("mini4pro", "mini3pro", "mini5pro", "air3", "air3s", "mavic3classic", "mavic4pro", "litox1")
NOW = 1700000000000


def area(**over):
    b = area_kmz.body(model="mini4pro", cameras=["visable"], height_mode="relativeToStartPoint", speed=5)
    b.update(over)
    s = mission_planner_api.parse_settings(b)
    return wpml.plan_from_settings(s), s


def files(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n).decode() for n in z.namelist()}


def values(text, tag):
    return re.findall(r"<wpml:%s>([^<]*)</wpml:%s>" % (tag, tag), text)


def placemarks(text):
    return re.findall(r"<Placemark>.*?</Placemark>", text, re.S)


class TestRegistry(SimpleTestCase):
    def test_the_eight_dji_fly_drones_carry_flypath_s_enums_and_no_payload(self):
        for model in DJIFLY:
            d = drones.DRONES[model]
            self.assertEqual((d.app, d.payload, d.drone), ("djifly", None, (97 if model == "mini3pro" else 68, 0)), model)
            self.assertEqual((d.route_types, d.realtime_follow), (("area", "linear", "waypoint"), False), model)
            self.assertIn(d.max_speed, (12.0, 15.0), model)

    def test_a_pilot_2_drone_still_needs_a_payload(self):
        data = json.loads(json.dumps(drones.DATA))
        data["m30"]["payload"] = None
        with self.assertRaises(drones.RegistryError):
            drones.parse(data)
        data = json.loads(json.dumps(drones.DATA))
        data["air3"]["max_speed"] = 0
        with self.assertRaises(drones.RegistryError):
            drones.parse(data)


class TestTheFile(SimpleTestCase):
    def test_an_area_is_a_dji_fly_waypoint_mission_with_one_point_a_photo(self):
        plan, s = area()
        [(name, data)] = djifly.build("area", plan, s, NOW, "Field")
        self.assertEqual(name, "Field.kmz")
        f = files(data)
        self.assertEqual(sorted(f), ["wpmz/template.kml", "wpmz/waylines.wpml"])
        template, waylines = f["wpmz/template.kml"], f["wpmz/waylines.wpml"]
        for text in (template, waylines):
            self.assertIn('xmlns:wpml="http://www.uav.com/wpmz/1.0.2"', text)
            self.assertNotIn("payloadInfo", text)
            self.assertNotIn("takeOffSecurityHeight", text)
            self.assertEqual(values(text, "droneEnumValue") + values(text, "droneSubEnumValue"), ["68", "0"])
        self.assertEqual(values(template, "templateType"), ["waypoint"])
        self.assertEqual(values(template, "heightMode"), ["relativeToStartPoint"])
        self.assertEqual(values(waylines, "executeHeightMode"), ["relativeToStartPoint"])
        self.assertEqual(set(values(waylines, "useStraightLine")), {"0"})
        self.assertEqual(values(waylines, "actionActuatorFunc").count("takePhoto"), plan.nadir.photos)
        self.assertEqual(placemarks(template), placemarks(waylines))
        first = placemarks(waylines)[0]
        self.assertEqual(values(first, "actionActuatorFunc"), ["gimbalRotate", "hover", "takePhoto"])
        self.assertEqual((values(first, "gimbalPitchRotateAngle"), values(first, "hoverTime")), (["-90"], ["3"]))
        self.assertEqual(set(values(waylines, "executeHeight")), {"40"})
        self.assertEqual(values(waylines, "finishAction"), ["goHome"])

    def test_the_photos_are_spaced_as_the_plan_s_interval(self):
        plan, s = area()
        points = djifly.route_points("area", plan, s)
        line = [p for p in points][:3]
        gap = wpml.GEOD.inv(line[0]["lon"], line[0]["lat"], line[1]["lon"], line[1]["lat"])[2]
        self.assertAlmostEqual(gap, plan.nadir.interval, delta=0.01)
        self.assertTrue(all(p["photo"] for p in points[:2]))

    def test_a_linear_route_is_its_photo_points(self):
        s = mission_planner_api.parse_linear_settings(linear_kmz.body(model="air3", cameras=["visable"], height_mode="relativeToStartPoint"))
        plan = linear.plan(s)
        [(_, data)] = djifly.build("linear", plan, s, NOW, "Canal", speed=5)
        self.assertEqual(values(files(data)["wpmz/waylines.wpml"], "actionActuatorFunc").count("takePhoto"), plan.photos)

    def test_agl_heights_follow_the_terrain_from_the_takeoff_point(self):
        plan, s = area(height_mode="realTimeFollowSurface")
        tif = area_kmz.dsm()[0]
        points = djifly.route_points("area", plan, s, tif)
        takeoff = (s.takeoff_ref_point[1], s.takeoff_ref_point[0])
        grounds = terrain.ground_heights(tif, [(p["lon"], p["lat"]) for p in points] + [takeoff])
        self.assertEqual([round(p["height"], 6) for p in points], [round(40 + g - grounds[-1], 6) for g in grounds[:-1]])
        self.assertGreater(len({round(p["height"]) for p in points}), 1)       # the ground rises to the east
        with self.assertRaisesRegex(wpml.ExportError, "Fetch the terrain"):
            djifly.route_points("area", plan, s)

    def test_a_long_route_is_split_into_missions_that_meet(self):
        points = [{"lon": i * 1e-4, "lat": 0.0, "height": 50.0, "photo": True, "pitch": -90.0, "heading": None, "hover": 0}
                  for i in range(450)]
        parts = djifly.split(points)
        self.assertEqual([len(p) for p in parts], [200, 200, 52])
        self.assertIs(parts[0][-1], parts[1][0])
        self.assertIs(parts[1][-1], parts[2][0])
        self.assertEqual(len(djifly.split(points[:200])), 1)
        self.assertEqual([len(p) for p in djifly.split(points[:201])], [200, 2])

    def test_a_route_needing_more_than_20_missions_is_refused(self):
        points = [{"lon": i * 1e-5, "lat": 0.0, "height": 50.0, "photo": True, "pitch": -90.0, "heading": None, "hover": 0}
                  for i in range(3982)]
        self.assertEqual(len(djifly.split(points[:3981])), 20)
        with self.assertRaisesRegex(wpml.ExportError, "3982 points.*at most 3981.*20 DJI Fly missions"):
            djifly.split(points)

    def test_a_large_area_is_refused_saying_to_split_it_or_fly_higher(self):
        big = [[round(v, 9) for v in p] for p in area_kmz.rectangle(3000, 3000)]
        plan, s = area(polygon=big)
        with self.assertRaisesRegex(wpml.ExportError, "Split the area into smaller routes, or fly higher"):
            djifly.build("area", plan, s, NOW, "Farm")

    def test_a_waypoint_route_keeps_its_photos_hovers_and_heights_from_the_takeoff_point(self):
        s = waypoint_kmz.route(model="mini4pro", cameras=["visable"], height_mode="alt", turn_mode="curve",
                               points=[dict(p, photo=i == 1, hover=5 if i == 2 else 0, height=70 if i == 3 else None)
                                       for i, p in enumerate(waypoint_kmz.square())])
        [(_, data)] = djifly.build("waypoint", None, s, NOW, "Square")
        waylines = files(data)["wpmz/waylines.wpml"]
        self.assertEqual(values(waylines, "executeHeight"), ["60", "60", "60", "70"])
        marks = placemarks(waylines)
        self.assertEqual(values(marks[1], "actionActuatorFunc"), ["takePhoto"])
        self.assertEqual((values(marks[2], "actionActuatorFunc"), values(marks[2], "hoverTime")), (["hover"], ["5"]))

    def test_an_agl_waypoint_route_is_flown_from_the_first_point_s_ground_without_a_takeoff_point(self):
        pts = [dict(p, ground=200.0 + 3 * i) for i, p in enumerate(waypoint_kmz.square())]
        s = waypoint_kmz.route(model="air3", cameras=["visable"], height_mode="agl", points=pts)
        self.assertEqual([p["height"] for p in djifly.route_points("waypoint", None, s)], [60.0, 63.0, 66.0, 69.0])

    def test_what_dji_fly_cannot_fly_is_refused(self):
        cases = [
            (lambda: area(collection_mode="oblique", gimbal_pitch=-45), "ortho photos only"),
            (lambda: area(finish_action="gotoFirstWaypoint"), "returning home, hovering or landing"),
            (lambda: area(speed=14), "13 m/s|12 m/s at most"),
        ]
        for make, message in cases:
            with self.subTest(message=message):
                plan, s = make()
                with self.assertRaisesRegex(wpml.ExportError, message):
                    djifly.build("area", plan, s, NOW, "x")
        s = waypoint_kmz.route(model="mini4pro", cameras=["visable"], video=True)
        with self.assertRaisesRegex(wpml.ExportError, "ignores video"):
            djifly.check("waypoint", s)


class TestApi(BootTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")

    def tearDown(self):
        disable_plugin("mission_planner")

    def post(self, path, body):
        return self.client.post(API + path, json.dumps(body), content_type="application/json")

    def test_a_dji_fly_drone_s_route_downloads_as_a_dji_fly_mission(self):
        body = dict(area_kmz.body(model="mavic3classic", cameras=["visable"], height_mode="relativeToStartPoint", speed=None),
                    route_type="area", name="Back field")
        res = self.post("export", body)
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res["Content-Disposition"], 'attachment; filename="Back_field.kmz"')
        self.assertIn("uav.com/wpmz/1.0.2", files(res.content)["wpmz/waylines.wpml"])

    def test_a_route_too_long_for_one_mission_downloads_as_a_zip_of_missions(self):
        big = [[round(v, 9) for v in p] for p in area_kmz.rectangle(1000, 600)]
        body = dict(area_kmz.body(model="mini4pro", cameras=["visable"], height_mode="relativeToStartPoint", polygon=big, height=60),
                    route_type="area", name="Farm")
        res = self.post("export", body)
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res["Content-Type"], "application/zip")
        names = sorted(zipfile.ZipFile(io.BytesIO(res.content)).namelist())
        self.assertGreater(len(names), 1)
        self.assertTrue(all(re.fullmatch(r"Farm_\d+_of_%d\.kmz" % len(names), n) for n in names), names)
        self.assertIn("Split into", res["X-Mission-Warnings"])

    def test_oblique_on_a_dji_fly_drone_is_refused_when_planned(self):
        body = dict(area_kmz.oblique(model="air3s", cameras=["visable"], height_mode="relativeToStartPoint"), route_type="area")
        res = self.post("plan", body)
        self.assertEqual(res.status_code, 400)
        self.assertIn("ortho photos only", res.json()["error"])
