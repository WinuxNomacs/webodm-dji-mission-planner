"""
Slope routes of the mission planner: missions/slope.py, checked against the slope route Pilot 2 exported
(tests/fixtures/dji-kmz/m4t-test-slope.kmz), the plugin's API for them (api.py), and their
import from Pilot 2 (missions/kmz_import.py).
"""
import json
import re
from unittest import mock
from xml.etree import ElementTree as ET

import numpy as np
from django.contrib.auth.models import User
from django.contrib.gis.geos import Polygon
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase

from .. import surface
from ..missions import slope
from ..missions.cameras import M4T_THERMAL, M4T_WIDE
from ..missions.kmz_import import KmzImportError, read_kmz_route
from ..missions.planning import PlanError
from ..missions.wpml import GEOD, ExportError
from app.models import Project, Task

from .. import routes
from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase
from .test_mission_kmz_import import edited, element, files, sample

API = "/api/plugins/mission_planner/"


def dsm_extent(bbox):
    """A task's DSM extent over bbox (west, south, east, north) as WebODM keeps it: GeoJSON"""
    polygon = Polygon.from_bbox(bbox)
    return {"type": "Polygon", "coordinates": [[list(c) for c in polygon.coords[0]]]}
from .. import api as mission_planner_api

NOW = 1700000000
NS = {"k": "http://www.opengis.net/kml/2.2", "w": "http://www.dji.com/wpmz/1.0.6"}
# The sample's face: its top 209 m high, its bottom 79 m, about 34 m apart to the north (WGS84-ellipsoidal heights)
CORNERS = [(-85.0206060946086, 42.1032754629821, 209.243712836247),
           (-85.0201803776386, 42.1032628751597, 209.006095442237),
           (-85.0201747378405, 42.1035673188521, 79.0862059599245),
           (-85.0206004655048, 42.1035799069404, 79.3238282158348)]
HEIGHT = 28.1098342541436


def route(**over):
    """The sample's settings"""
    kw = dict(corners=CORNERS, cameras=[M4T_WIDE, M4T_THERMAL], height=HEIGHT, overlap_h=80, overlap_w=80, speed=3.5,
              takeoff_security_height=20, rth_height=100, takeoff_ref_point=(42.103439, -85.020559, 208.648261),
              author="pilot@example.com")
    kw.update(over)
    return slope.settings(**kw)


def waypoints(wpml):
    """Each Placemark of a waylines.wpml: (lon, lat), height, heading mode and angle, enabled, turn, damping, groups"""
    out = []
    for pm in ET.fromstring(wpml).iter("{%s}Placemark" % NS["k"]):
        value = lambda tag: pm.find(".//w:" + tag, NS).text
        groups = [(int(g.find("w:actionGroupStartIndex", NS).text), int(g.find("w:actionGroupEndIndex", NS).text),
                   g.find("w:actionTrigger/w:actionTriggerType", NS).text,
                   [a.find("w:actionActuatorFunc", NS).text for a in g.findall("w:action", NS)])
                  for g in pm.findall("w:actionGroup", NS)]
        lon, lat = map(float, pm.find("k:Point/k:coordinates", NS).text.split(","))
        out.append(dict(at=(lon, lat), height=float(value("executeHeight")), mode=value("waypointHeadingMode"),
                        heading=float(value("waypointHeadingAngle")), enabled=value("waypointHeadingAngleEnable"),
                        turn=value("waypointTurnMode"), damping=float(value("waypointTurnDampingDist")),
                        groups=groups))
    return out


def sample_files():
    return {name: content.decode() for name, content in files(sample("m4t-test-slope.kmz")).items()}


def value(tag, xml):
    return re.search(r"<wpml:%s>([^<]*)<" % tag, xml).group(1)


def tags(xml):
    return re.findall(r"<wpml:(\w+)>", xml)


class TestSlopeSettings(SimpleTestCase):
    def test_a_face_needs_at_least_3_corners_each_with_its_height(self):
        for corners in (CORNERS[:2], [c[:2] for c in CORNERS], CORNERS[:3] + [(1.0, 2.0, float("nan"))]):
            with self.subTest(corners=corners):
                with self.assertRaisesRegex(PlanError, "between 3 and 50 corners"):
                    route(corners=corners)

    def test_a_level_face_is_refused_for_an_area_route(self):
        s = route(corners=[(lon, lat, 200.0) for lon, lat, _ in CORNERS])
        with self.assertRaisesRegex(PlanError, "area route"):
            slope.plan(s)

    def test_corners_in_a_line_on_the_map_are_refused(self):
        s = route(corners=[(-85.020528, 42.1032, 200.0), (-85.020428, 42.1033, 150.0), (-85.020328, 42.1034, 100.0)])
        with self.assertRaisesRegex(PlanError, "in a line"):
            slope.plan(s)

    def test_the_settings_shared_with_an_area_are_checked_with_its_messages(self):
        for over, error, message in (({"cameras": []}, PlanError, "at least one camera"),
                                     ({"height": 1}, PlanError, "distance from the face"),
                                     ({"overlap_w": 99}, PlanError, "overlap across"),
                                     ({"speed": 16}, ExportError, "at most 15"),
                                     ({"rth_height": 1}, ExportError, "return height"),
                                     ({"model": "m5t"}, ExportError, "Unknown aircraft"),
                                     ({"cameras": [M4T_THERMAL]}, ExportError, "cannot be exported yet")):
            with self.subTest(over=over):
                with self.assertRaisesRegex(error, message):
                    route(**over)


class TestSlopePlan(SimpleTestCase):
    def test_the_face_is_flown_as_pilot_2_flies_it(self):
        s = route()
        ours, theirs = waypoints(slope.waylines_wpml(slope.plan(s), s)), waypoints(sample_files()["wpmz/waylines.wpml"])
        self.assertEqual(len(ours), 92)
        self.assertEqual(len(ours), len(theirs))
        for i, (a, b) in enumerate(zip(ours, theirs)):
            with self.subTest(point=i):
                self.assertLess(GEOD.inv(*a["at"], *b["at"])[2], 0.1)
                self.assertAlmostEqual(a["height"], b["height"], delta=0.1)
                self.assertAlmostEqual(a["heading"], b["heading"], delta=0.001)
                self.assertAlmostEqual(a["damping"], b["damping"], delta=0.01)
                for key in ("mode", "enabled", "turn", "groups"):
                    self.assertEqual(a[key], b[key])

    def test_the_gimbal_is_square_on_to_the_face_and_the_aircraft_faces_it(self):
        p = slope.plan(route())
        self.assertAlmostEqual(p.slope, 75.4, delta=0.05)
        self.assertEqual(p.pitch, -14)
        self.assertAlmostEqual(p.heading, -177.6258, delta=0.001)

    def test_the_lines_run_across_the_face_from_the_top_down_starting_at_the_first_corner(self):
        p = slope.plan(route())
        self.assertEqual(len(p.lines), 46)
        heights = [line[0][2] for line in p.lines]
        self.assertEqual(heights, sorted(heights, reverse=True))
        for line in p.lines:
            self.assertAlmostEqual(line[0][2], line[1][2], delta=0.5)        # level
        self.assertLess(GEOD.inv(*p.waypoints[0][:2], *CORNERS[0][:2])[2], GEOD.inv(*p.waypoints[1][:2], *CORNERS[0][:2])[2])
        self.assertAlmostEqual(p.spacing, HEIGHT * 6.144 / 12 * 0.2, places=9)

    def test_the_length_time_and_photo_interval_are_those_pilot_2_gives(self):
        p, theirs = slope.plan(route()), sample_files()["wpmz/waylines.wpml"]
        self.assertAlmostEqual(p.distance / float(value("distance", theirs)), 1, delta=0.005)
        self.assertAlmostEqual(p.duration, float(value("duration", theirs)), delta=2)
        self.assertAlmostEqual(p.interval, float(value("actionTriggerParam", theirs)), delta=1e-6)

    def test_without_a_speed_the_route_is_flown_as_fast_as_the_photos_allow(self):
        s = route(speed=None)
        p = slope.plan(s)
        self.assertLessEqual(slope.speed_of(p, s), p.max_speed)
        self.assertNotIn("some may be missed", " ".join(slope.mission_warnings(p, s)))

    def test_the_warnings_say_when_the_photos_cannot_keep_up_and_when_the_return_height_is_too_low(self):
        s = route()
        warnings = slope.mission_warnings(slope.plan(s), s)
        self.assertEqual(len(warnings), 3)
        self.assertIn("some may be missed", warnings[0])
        self.assertIn("corner heights", warnings[1])
        self.assertIn("not well above the top of the route", warnings[2])
        s = route(rth_height=200)
        self.assertEqual(len(slope.mission_warnings(slope.plan(s), s)), 2)


class TestSlopeExport(SimpleTestCase):
    def export(self, s=None):
        s = s or route()
        return {name: content.decode() for name, content in files(slope.build_kmz(slope.plan(s), s, now=NOW)).items()}

    def test_the_template_has_the_face_as_pilot_2_writes_it(self):
        ours, theirs = self.export()["wpmz/template.kml"], sample_files()["wpmz/template.kml"]
        self.assertEqual(tags(ours), tags(theirs))
        for tag in ("templateType", "facadeWaylineEnable", "heightMode", "globalShootHeight", "height",
                    "orthoCameraOverlapH", "orthoCameraOverlapW", "imageFormat", "payloadSubEnumValue", "takeOffRefPoint"):
            self.assertEqual(value(tag, ours), value(tag, theirs), tag)
        coordinates = lambda xml: re.search(r"<coordinates>(.*?)</coordinates>", xml, re.S).group(1)
        self.assertEqual(coordinates(ours), coordinates(theirs))
        self.assertAlmostEqual(float(value("ellipsoidHeight", ours)), float(value("ellipsoidHeight", theirs)), delta=0.01)
        start, start_theirs = (list(map(float, value("startPositionRef", xml).split(","))) for xml in (ours, theirs))
        self.assertAlmostEqual(start[0], start_theirs[0], delta=1e-6)
        self.assertAlmostEqual(start[1], start_theirs[1], delta=1e-6)
        self.assertAlmostEqual(start[2], start_theirs[2], delta=0.1)

    def test_the_waylines_have_the_elements_of_pilot_2s_in_the_same_order(self):
        ours, theirs = self.export()["wpmz/waylines.wpml"], sample_files()["wpmz/waylines.wpml"]
        self.assertEqual(tags(ours), tags(theirs))
        for tag in ("executeHeightMode", "gimbalPitchRotateAngle", "autoFlightSpeed"):
            self.assertEqual(value(tag, ours), value(tag, theirs), tag)

    def test_the_same_route_exports_the_same_file_again(self):
        s = route()
        p = slope.plan(s)
        self.assertEqual(slope.build_kmz(p, s, now=NOW), slope.build_kmz(p, s, now=NOW))

    def test_without_the_geoid_grid_the_ellipsoid_height_is_the_height(self):
        with mock.patch.object(slope, "EGM96_GRID", "/nonexistent.gtx"):
            template = self.export()["wpmz/template.kml"]
        self.assertEqual(value("ellipsoidHeight", template), value("height", template))


def body(**over):
    b = {"route_type": "slope", "model": "m4t", "name": "luxodm-slope", "cameras": ["visable", "ir"],
         "corners": [list(c) for c in CORNERS], "height": HEIGHT, "overlap_h": 80, "overlap_w": 80, "speed": 3.5,
         "takeoff_security_height": 20, "rth_height": 150, "takeoff_ref_point": [42.103439, -85.020559, 208.648261]}
    b.update(over)
    return b


def export(b):
    s = mission_planner_api.parse_slope_settings(b)
    return slope.build_kmz(slope.plan(s), s, now=NOW)


class TestSlopeImport(SimpleTestCase):
    def test_pilot_2s_slope_imports_with_its_corners_heights(self):
        model, s, b = read_kmz_route(sample("m4t-test-slope.kmz"), "x")
        self.assertEqual((model, b["route_type"], s["height"], s["overlap_w"], s["speed"]), ("m4t", "slope", "28.109834", "80", "3.5"))
        self.assertEqual(s["corners"], [[round(c[0], 9), round(c[1], 9), c[2]] for c in CORNERS])
        self.assertEqual(s["takeoff"], [42.103439, -85.020559])
        self.assertEqual(len(slope.plan(mission_planner_api.parse_slope_settings(b)).lines), 46)

    def test_a_route_the_planner_exported_imports_as_the_same_file(self):
        # The editor's corners have 9 decimals, and its heights fewer than the file keeps
        data = export(body(corners=[[round(c[0], 9), round(c[1], 9), c[2]] for c in CORNERS], height=28.5))
        model, s, again = read_kmz_route(data, "luxodm-slope")
        self.assertEqual(files(export(again)), files(data))

    def test_what_the_planner_cannot_fly_is_refused(self):
        data = export(body())
        for replacement, reason in ((element("heightMode", "relativeToStartPoint"), "above sea level"),
                                    (element("doubleGridWaylineEnable", 1), "double grid"),
                                    (element("globalShootHeight", 600), "between 2 and 500"),
                                    ((r"<coordinates>[^<]*</coordinates>", "<coordinates>-88,42 -88.1,42 -88,42.1</coordinates>"),
                                     "each with its height"),
                                    ((r"<coordinates>[^<]*</coordinates>", "<coordinates>-88,42,1 -88.1,42,1</coordinates>"),
                                     "between 3 and 50 corners")):
            with self.subTest(reason):
                with self.assertRaisesRegex(KmzImportError, reason):
                    read_kmz_route(edited(data, replacement), "x")


class TestSlopeApi(BootTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.user = User.objects.get(username="testuser")

    def tearDown(self):
        disable_plugin("mission_planner")

    def post(self, path, data):
        return self.client.post(API + path, json.dumps(data), content_type="application/json")

    def test_the_plan_of_a_slope_route_has_its_lines_points_and_side_profile(self):
        res = self.post("plan", body())
        self.assertEqual(res.status_code, 200, res.content[:300])
        data = res.json()
        summary = data["summary"]
        self.assertEqual((summary["lines"], summary["waypoints"], summary["pitch"]), (46, 92, -14))
        self.assertAlmostEqual(summary["slope"], 75.4, delta=0.05)
        self.assertAlmostEqual(summary["undulation"], -34.2, delta=0.01)
        self.assertEqual(len(data["lines"]["features"]), 46)
        self.assertEqual(len(data["waypoints"]["features"][0]["geometry"]["coordinates"]), 3)
        profile = summary["profile"]
        (top_out, top_h), (bottom_out, bottom_h) = profile["face"]
        self.assertEqual(top_out, 0)
        self.assertGreater(bottom_out, 30)              # the bottom is 34 m out from the top: towards the aircraft
        self.assertGreater(top_h - bottom_h, 120)
        self.assertEqual(len(profile["lines"]), 46)
        # Each line is the distance from the face out from it
        for out, h in profile["lines"]:
            distance = abs((h - top_h) * (bottom_out - top_out) - out * (bottom_h - top_h)) / np.hypot(bottom_out, bottom_h - top_h)
            self.assertAlmostEqual(distance, HEIGHT, delta=0.01)

    def test_a_slope_route_exports_as_pilot_2s_facade(self):
        res = self.post("export", body())
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res["Content-Disposition"], 'attachment; filename="luxodm-slope.kmz"')
        self.assertIn("<wpml:facadeWaylineEnable>1<", files(res.content)["wpmz/template.kml"].decode())

    def test_bad_corners_are_refused(self):
        for corners in (None, "corners", [[1, 2], [1, 2], [1, 2]], [["a", 1, 2]] * 3, [[200, 1, 2]] * 3,
                        [[True, 1, 2]] * 3, [[-88, 42, 1]] * (slope.MAX_CORNERS + 1)):
            with self.subTest(corners=str(corners)[:30]):
                res = self.post("plan", body(corners=corners))
                self.assertEqual(res.status_code, 400)
                self.assertIn("corners must be", res.json()["error"])
        res = self.post("plan", body(corners=[list(c) for c in CORNERS[:2]]))
        self.assertIn("between 3 and 50 corners", res.json()["error"])

    def test_a_slope_route_is_saved_and_copied_with_its_type(self):
        res = self.post("routes", {"name": "Dam", "route_type": "slope", "model": "m4t", "settings": {"height": "30"}})
        self.assertEqual(res.status_code, 201, res.content[:300])
        res = self.post("routes/%d/copy" % res.json()["id"], {"model": "m4e"})
        self.assertEqual((res.json()["route_type"], res.json()["settings"]["height"]), ("slope", "39.96"))

    def test_a_pilot_2_slope_route_is_imported_with_its_plan_summary(self):
        res = self.client.post(API + "routes/import", {"file": SimpleUploadedFile("Dam.kmz", sample("m4t-test-slope.kmz"))})
        self.assertEqual(res.status_code, 201, res.content[:300])
        route = routes.get(res.json()["id"])
        self.assertEqual((route.name, route.route_type, len(route.settings["corners"])), ("Dam", "slope", 4))
        self.assertEqual(res.json()["summary"]["lines"], 46)

    def test_the_corners_heights_come_from_the_dsm_of_the_tasks_the_user_can_see(self):
        extent = dsm_extent([-85.021728, 42.103, -85.019728, 42.104])
        mine = Task.objects.create(project=Project.objects.get(name="User Test Project"), name="Dam survey",
                                   epsg=32616, available_assets=["dsm.tif"], dsm_extent=extent)
        Task.objects.create(project=Project.objects.get(name="User 2 Test Project"), name="Not mine", epsg=32616,
                            available_assets=["dsm.tif"], dsm_extent=extent)
        Task.objects.create(project=Project.objects.get(name="User Test Project"), name="Elsewhere", epsg=32616,
                            available_assets=["dsm.tif"], dsm_extent=dsm_extent([-87.0, 41.0, -86.9, 41.1]))
        corners = [list(c[:2]) for c in CORNERS]
        with mock.patch.object(surface, "surface_heights",
                               return_value=(np.array([209.2, 209.0, 79.1, 79.3]), "dsm")) as heights:
            res = self.post("face-heights", {"corners": corners})
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res.json()["tasks"], [{"id": str(mine.id), "project": mine.project.id,
                                                "project_name": "User Test Project", "name": "Dam survey",
                                                "heights": [209.2, 209.0, 79.1, 79.3], "source": "dsm"}])
        # In the task's UTM zone
        points = heights.call_args.args[1]
        self.assertAlmostEqual(points[0][0], 663700, delta=10000)
        with mock.patch.object(surface, "surface_heights", return_value=(np.array([209.2, np.nan, 79.1, 79.3]), "dsm")):
            self.assertEqual(self.post("face-heights", {"corners": corners}).json()["tasks"], [])
        self.assertEqual(self.post("face-heights", {"corners": [[1, 2, 3]]}).status_code, 400)
