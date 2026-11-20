"""
Linear routes of the mission planner: missions/linear.py, checked against the two linear routes Pilot 2 exported
(tests/fixtures/dji-kmz/m4t-test-linear-single.kmz and m4t-test-linear-zigzag.kmz), and the plugin's API for them
(api.py), and their import from Pilot 2 (missions/kmz_import.py).
"""
import json
import re
from xml.etree import ElementTree as ET

from unittest import mock

import numpy as np
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase

from ..missions import linear, terrain
from ..missions.kmz_import import KmzImportError, read_kmz_dsm, read_kmz_route
from ..missions.cameras import M4T_THERMAL, M4T_WIDE
from ..missions.planning import PlanError
from ..missions.wpml import GEOD, ExportError
from .. import routes
from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase
from .test_mission_kmz_import import edited, element, files, sample
from .test_mission_terrain import geotiff

API = "/api/plugins/mission_planner/"
from .. import api as mission_planner_api

NOW = 1700000000
NS = {"k": "http://www.opengis.net/kml/2.2", "w": "http://www.dji.com/wpmz/1.0.6"}
# The center line of both samples
LINE = [(-85.020416690383, 42.1031663348524), (-85.0203936565203, 42.1033610736102),
        (-85.0201768652846, 42.1036668032605)]
# The zigzag sample's height (the single line's comes from the strip's width)
ZIGZAG_HEIGHT = 120.595050812216


def terrain_tif(ground=180.0):
    """A flat terrain around the center line, `ground` m high, as fetch_terrain returns it"""
    return geotiff(np.full((72, 72), ground), dtype="int16", west=LINE[0][0] - 0.01, north=LINE[0][1] + 0.01)


TERRAIN_INFO = {"dataset": "COP30", "undulation": -33.5, "bounds": [-85.033728, 42.09, -85.003728, 42.11],
                "name": "wgs84_COP30_N42W086_dem.tif"}


def route(**over):
    """The samples' settings"""
    kw = dict(line=LINE, cameras=[M4T_WIDE, M4T_THERMAL], left_extend=50, right_extend=50, height=ZIGZAG_HEIGHT,
              overlap_h=80, overlap_w=80, speed=5, takeoff_security_height=40, rth_height=100,
              takeoff_ref_point=(42.103449, -85.020558, 208.611125), author="pilot@example.com")
    kw.update(over)
    return linear.settings(**kw)


def waypoints(wpml):
    """Each Placemark of a waylines.wpml: (lon, lat), heading, heading enabled, turn mode, damping, action groups"""
    out = []
    for pm in ET.fromstring(wpml).iter("{%s}Placemark" % NS["k"]):
        value = lambda tag: pm.find(".//w:" + tag, NS).text
        groups = [(int(g.find("w:actionGroupStartIndex", NS).text), int(g.find("w:actionGroupEndIndex", NS).text),
                   g.find("w:actionTrigger/w:actionTriggerType", NS).text,
                   [a.find("w:actionActuatorFunc", NS).text for a in g.findall("w:action", NS)])
                  for g in pm.findall("w:actionGroup", NS)]
        lon, lat = map(float, pm.find("k:Point/k:coordinates", NS).text.split(","))
        out.append(dict(at=(lon, lat), heading=float(value("waypointHeadingAngle")),
                        enabled=value("waypointHeadingAngleEnable"), turn=value("waypointTurnMode"),
                        damping=float(value("waypointTurnDampingDist")), groups=groups))
    return out


def folder_value(wpml, tag):
    return float(re.search(r"<wpml:%s>([^<]*)</wpml:%s>" % (tag, tag), wpml).group(1))


def sample_wpml(name):
    return files(sample("m4t-test-linear-%s.kmz" % name))["wpmz/waylines.wpml"].decode()


class TestLinearSettings(SimpleTestCase):
    def test_a_center_line_needs_at_least_2_points(self):
        with self.assertRaisesRegex(PlanError, "center line needs between 2"):
            route(line=LINE[:1])

    def test_the_strip_needs_a_width_and_no_negative_side(self):
        with self.assertRaisesRegex(PlanError, "cannot be negative"):
            route(left_extend=-1)
        with self.assertRaisesRegex(PlanError, "needs a width"):
            route(left_extend=0, right_extend=0)

    def test_a_single_line_is_flown_high_enough_for_one_photo_to_cover_the_strip(self):
        # The thermal camera is the narrower: 7.68 mm over 12 mm
        self.assertAlmostEqual(route(single_line=True).height, 100 / 0.64)
        with self.assertRaisesRegex(PlanError, "height must be between"):
            route(single_line=True, left_extend=200, right_extend=200)

    def test_the_settings_shared_with_an_area_are_checked_with_its_messages(self):
        with self.assertRaisesRegex(ExportError, "Unknown height mode"):
            route(height_mode="AGL")
        with self.assertRaisesRegex(ExportError, "ground height at the takeoff point"):
            route(height_mode="EGM96", takeoff_ref_point=None)
        with self.assertRaisesRegex(PlanError, "overlap across the lines"):
            route(overlap_w=99)
        with self.assertRaisesRegex(PlanError, "Choose at least one camera"):
            route(cameras=[])


class TestLinearPlan(SimpleTestCase):
    def assertMatchesSample(self, name, s):
        p = linear.plan(s)
        ours, theirs = waypoints(linear.waylines_wpml(p, s)), waypoints(sample_wpml(name))
        self.assertEqual(len(ours), len(theirs))
        for i, (a, b) in enumerate(zip(ours, theirs)):
            with self.subTest(point=i):
                self.assertLess(GEOD.inv(*a["at"], *b["at"])[2], 0.5)
                self.assertAlmostEqual((a["heading"] - b["heading"] + 180) % 360 - 180, 0, delta=0.5)
                self.assertAlmostEqual(a["damping"], b["damping"], delta=0.3)
                for key in ("enabled", "turn", "groups"):
                    self.assertEqual(a[key], b[key])
        return p

    def test_a_line_that_turns_back_on_itself_is_planned_near_it(self):
        a, b = LINE[0], LINE[1]
        for line in ([a, b, a], [a, b, (a[0] + 1e-7, a[1])]):
            with self.subTest(line=line):
                p = linear.plan(route(line=list(line), speed=None))
                for lon, lat in p.waypoints:
                    # every waypoint within the strip's width (and a margin) of the line's two points
                    self.assertLess(min(GEOD.inv(lon, lat, q[0], q[1])[2] for q in (a, b)) - GEOD.inv(*a, *b)[2], 200)

    def test_a_low_slow_survey_still_gets_a_speed(self):
        p = linear.plan(route(height=4, overlap_h=95, speed=None))
        self.assertGreater(linear.speed_of(p, route(height=4, overlap_h=95, speed=None)), 0)
        self.assertGreater(p.duration, 0)

    def test_the_single_line_is_flown_as_pilot_2_flies_it_with_its_bend_pass(self):
        p = self.assertMatchesSample("single", route(single_line=True))
        self.assertEqual((p.stop, p.bend, len(p.lines)), (2, 3, 1))

    def test_the_zigzag_is_flown_as_pilot_2_flies_it_with_its_bend_pass(self):
        p = self.assertMatchesSample("zigzag", route())
        self.assertEqual((p.stop, p.bend, len(p.lines)), (26, 27, 8))

    def test_the_length_and_time_are_those_pilot_2_gives(self):
        for name, s in (("single", route(single_line=True)), ("zigzag", route())):
            with self.subTest(name):
                p, theirs = linear.plan(s), sample_wpml(name)
                self.assertAlmostEqual(p.distance / folder_value(theirs, "distance"), 1, delta=0.002)
                self.assertAlmostEqual(p.duration, folder_value(theirs, "duration"), delta=1.5)
                interval = float(re.search(r"multipleDistance<[^>]*>\s*<wpml:actionTriggerParam>([^<]*)<", theirs).group(1))
                self.assertAlmostEqual(p.interval / interval, 1, delta=0.005)

    def test_lines_are_spaced_for_the_overlap_and_cover_the_whole_strip(self):
        p = linear.plan(route())
        self.assertAlmostEqual(p.spacing, ZIGZAG_HEIGHT * 7.68 / 12 * 0.2)
        self.assertGreaterEqual((len(p.lines) - 1) * p.spacing, 100)

    def test_a_straight_center_line_has_no_bend_pass(self):
        p = linear.plan(route(line=LINE[:2]))
        groups = [g for w in waypoints(linear.waylines_wpml(p, route(line=LINE[:2]))) for g in w["groups"]]
        self.assertEqual((p.stop, p.bend), (None, None))
        self.assertEqual(len(p.waypoints), 2 * len(p.lines))
        last = len(p.waypoints) - 1
        self.assertEqual([g[:3] for g in groups], [(0, last, "betweenAdjacentPoints"), (0, last, "multipleDistance"),
                                                   (last, last, "reachPoint")])

    def test_a_strip_wider_on_one_side_moves_the_lines_to_that_side(self):
        p = linear.plan(route(line=LINE[:2], left_extend=80, right_extend=20))
        start, first = LINE[0], p.lines[0][0]
        # Line 0 is the leftmost: west of a line heading north
        self.assertLess(first[0], start[0])
        self.assertGreater(GEOD.inv(*start, *first)[2], GEOD.inv(*start, *p.lines[-1][-1])[2])

    def test_without_a_speed_the_route_is_flown_as_fast_as_the_photos_allow(self):
        s = route(speed=None)
        p = linear.plan(s)
        self.assertLessEqual(linear.speed_of(p, s), p.max_speed)
        self.assertEqual(linear.mission_warnings(p, s)[0][:20], "The height is measur")

    def test_the_warnings_say_when_the_photos_cannot_keep_up_and_when_the_return_height_is_too_low(self):
        s = route(speed=15, rth_height=50)
        warnings = linear.mission_warnings(linear.plan(s), s)
        self.assertEqual(len(warnings), 3)
        self.assertIn("some may be missed", warnings[0])
        self.assertIn("not well above", warnings[2])


class TestLinearExport(SimpleTestCase):
    def test_the_template_has_the_strip_as_pilot_2_writes_it(self):
        s = route(single_line=True)
        template = files(linear.build_kmz(linear.plan(s), s, now=NOW))["wpmz/template.kml"].decode()
        theirs = files(sample("m4t-test-linear-single.kmz"))["wpmz/template.kml"].decode()
        tags = lambda xml: re.findall(r"<wpml:(\w+)>", xml)
        self.assertEqual(tags(template), tags(theirs))
        value = lambda tag, xml: re.search(r"<wpml:%s>([^<]*)<" % tag, xml).group(1)
        for tag in ("templateType", "singleLineEnable", "leftExtend", "rightExtend"):
            self.assertEqual(value(tag, template), value(tag, theirs))
        # Pilot 2 writes the height it flies, about 1 m under the one it computes; this writes the computed one
        for tag in ("globalShootHeight", "height"):
            self.assertAlmostEqual(float(value(tag, template)) / float(value(tag, theirs)), 1, delta=0.01)

    def test_the_waylines_have_the_elements_of_pilot_2s_in_the_same_order(self):
        for name, s in (("single", route(single_line=True)), ("zigzag", route())):
            with self.subTest(name):
                ours = linear.waylines_wpml(linear.plan(s), s).decode()
                tags = lambda xml: re.findall(r"<wpml:(\w+)>", xml)
                self.assertEqual(tags(ours), tags(sample_wpml(name)))

    def test_every_height_mode_exports_the_same_file_again(self):
        for mode, extra in (("relativeToStartPoint", {}), ("realTimeFollowSurface", {}),
                            ("EGM96", {"takeoff_ellipsoidal_height": 175.0})):
            with self.subTest(mode):
                s = route(height_mode=mode, **extra)
                p = linear.plan(s)
                self.assertEqual(linear.build_kmz(p, s, now=NOW), linear.build_kmz(p, s, now=NOW))


class TestLinearDSMFollow(SimpleTestCase):
    """The DSM follow of a linear route, written as the area mission's: Pilot 2 has not given a linear sample of it"""

    def export(self, ground=180.0):
        s = route(height_mode="realTimeFollowSurface", surface_follow="dsm")
        p = linear.plan(s)
        return s, p, files(linear.build_kmz(p, s, now=NOW, dsm=(terrain_tif(ground), TERRAIN_INFO["name"])))

    def test_the_template_names_the_embedded_terrain_and_does_not_follow_in_real_time(self):
        s, p, f = self.export()
        template = f["wpmz/template.kml"].decode()
        self.assertEqual(f["wpmz/res/dsm/" + TERRAIN_INFO["name"]], terrain_tif())
        for tag, value in (("heightMode", "EGM96"), ("isRealtimeSurfaceFollow", "0"),
                           ("dsmFile", "wpmz/res/dsm/" + TERRAIN_INFO["name"])):
            self.assertIn("<wpml:%s>%s<" % (tag, value), template)
        # The takeoff point is on the terrain's ground
        self.assertEqual(float(re.search(r"<wpml:takeOffRefPoint>[^,]*,[^,]*,([^<]*)<", template).group(1)), 180.0)

    def test_each_waypoint_flies_the_height_over_the_ground_in_wgs84(self):
        s, p, f = self.export()
        wpml = f["wpmz/waylines.wpml"].decode()
        self.assertIn("<wpml:executeHeightMode>WGS84<", wpml)
        heights = {float(h) for h in re.findall(r"<wpml:executeHeight>([^<]*)<", wpml)}
        self.assertEqual(heights, {round(180.0 + ZIGZAG_HEIGHT, 3)})

    def test_the_warnings_say_the_dsm_follow_is_untested(self):
        s = route(height_mode="realTimeFollowSurface", surface_follow="dsm")
        warnings = linear.mission_warnings(linear.plan(s), s)
        self.assertTrue(any("public elevation data" in w for w in warnings))
        self.assertTrue(any("not been checked against a file from Pilot 2" in w for w in warnings))
        s = route(height_mode="realTimeFollowSurface")
        self.assertFalse(any("Pilot 2" in w for w in linear.mission_warnings(linear.plan(s), s)))

    def test_the_export_needs_the_terrain(self):
        s = route(height_mode="realTimeFollowSurface", surface_follow="dsm")
        with self.assertRaisesRegex(ExportError, "needs the terrain"):
            linear.build_kmz(linear.plan(s), s, now=NOW)

    def test_terrain_that_does_not_cover_the_route_is_refused(self):
        s = route(height_mode="realTimeFollowSurface", surface_follow="dsm")
        far = geotiff(np.full((10, 10), 180.0), dtype="int16", west=-87.0, north=41.0)
        with self.assertRaisesRegex(ExportError, "does not cover"):
            linear.dsm_of(linear.plan(s), s, far, "x.tif")

    def test_an_unknown_surface_follow_is_refused(self):
        with self.assertRaisesRegex(ExportError, "Unknown surface follow"):
            route(height_mode="realTimeFollowSurface", surface_follow="lidar")


def body(**over):
    b = {"route_type": "linear", "model": "m4t", "name": "luxodm-linear", "cameras": ["visable", "ir"],
         "line": [list(p) for p in LINE], "left_extend": 50, "right_extend": 50, "height": ZIGZAG_HEIGHT,
         "overlap_h": 80, "overlap_w": 80, "speed": 5, "takeoff_security_height": 40, "rth_height": 100}
    b.update(over)
    return b


def export(b, dsm=None):
    s = mission_planner_api.parse_linear_settings(b)
    return linear.build_kmz(linear.plan(s), s, now=NOW, dsm=dsm)


class TestLinearImport(SimpleTestCase):
    def test_pilot_2s_single_line_imports_with_the_height_it_flies(self):
        model, s, b = read_kmz_route(sample("m4t-test-linear-single.kmz"), "x")
        self.assertEqual((model, s["single_line"], s["height"], s["left_extend"], s["right_extend"]),
                         ("m4t", "true", "155.17929", "50", "50"))
        self.assertEqual(s["line"], [[round(v, 9) for v in p] for p in LINE])
        self.assertEqual(len(linear.plan(mission_planner_api.parse_linear_settings(b)).lines), 1)

    def test_pilot_2s_zigzag_imports_with_the_height_it_flies(self):
        model, s, b = read_kmz_route(sample("m4t-test-linear-zigzag.kmz"), "x")
        self.assertEqual((s["single_line"], s["height"], s["overlap_w"], s["speed"]), ("false", "119.52434", "80", "5"))
        self.assertEqual((b["route_type"], b["cameras"]), ("linear", ["visable", "ir"]))
        self.assertEqual(len(linear.plan(mission_planner_api.parse_linear_settings(b)).lines), 8)

    def test_a_route_the_planner_exported_imports_as_the_same_file(self):
        for over in ({}, {"single_line": True}, {"height_mode": "realTimeFollowSurface"},
                     {"height_mode": "EGM96", "takeoff_ref_point": [42.103449, -85.020558, 208.5],
                      "takeoff_ellipsoidal_height": 175.25}):
            with self.subTest(over):
                # The editor's points have 9 decimals, and its heights fewer than the file keeps
                data = export(body(line=[[round(v, 9) for v in p] for p in LINE], height=120.5, **over))
                model, s, again = read_kmz_route(data, "luxodm-linear")
                self.assertEqual(files(export(again)), files(data))

    def test_a_route_over_its_elevation_model_imports_as_the_same_file_with_its_dsm(self):
        terrain = (terrain_tif(), TERRAIN_INFO["name"])
        data = export(body(line=[[round(v, 9) for v in p] for p in LINE], height=120.5, height_mode="realTimeFollowSurface", surface_follow="dsm",
                           takeoff_ref_point=[42.103449, -85.020558, 208.5]), dsm=terrain)
        model, s, again = read_kmz_route(data, "luxodm-linear")
        self.assertEqual((s["altitude_mode"], s["surface_follow"], again["surface_follow"]), ("agl", "dsm", "dsm"))
        tif, info = read_kmz_dsm(data)
        self.assertEqual((tif, info["name"], info["dataset"], info["undulation"]), (terrain[0], terrain[1], "COP30", None))
        self.assertEqual(files(export(again, dsm=(tif, info["name"]))), files(data))

    def test_what_the_planner_cannot_fly_is_refused(self):
        data = export(body())
        for replacement, reason in ((element("includeCenterEnable", 1), "include the center line"),
                                    (element("efficiencyFlightModeEnable", 1), "efficiency"),
                                    (element("leftExtend", -5), "cannot be negative"),
                                    (element("height", 600), "between 2 and 500"),
                                    ((r"<coordinates>[^<]*</coordinates>", "<coordinates>-88,42,0</coordinates>"),
                                     "between 2 and %d points" % linear.MAX_POINTS)):
            with self.subTest(reason):
                with self.assertRaisesRegex(KmzImportError, reason):
                    read_kmz_route(edited(data, replacement), "x")


class TestLinearApi(BootTestCase):
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

    def test_the_plan_of_a_linear_route_has_its_lines_its_bend_pass_and_its_points(self):
        res = self.post("plan", body())
        self.assertEqual(res.status_code, 200, res.content[:300])
        data = res.json()
        self.assertEqual((data["summary"]["lines"], data["summary"]["waypoints"], data["summary"]["bend_pass"]),
                         (8, 31, True))
        self.assertEqual([f["properties"]["pass"] for f in data["lines"]["features"]], ["linear"] * 8 + ["bend"])
        passes = [f["properties"]["pass"] for f in data["waypoints"]["features"]]
        self.assertEqual((passes.index("bend"), len(passes)), (27, 31))

    def test_a_single_line_plans_its_own_height(self):
        data = self.post("plan", body(single_line=True, height=None)).json()
        self.assertAlmostEqual(data["summary"]["height"], 100 / 0.64)
        self.assertEqual(data["summary"]["lines"], 1)

    def test_a_linear_route_exports_as_a_pilot_2_strip(self):
        res = self.post("export", body())
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res["Content-Disposition"], 'attachment; filename="luxodm-linear.kmz"')
        self.assertIn("<wpml:templateType>mappingStrip<", files(res.content)["wpmz/template.kml"].decode())

    def test_a_bad_center_line_is_refused(self):
        for line in (None, "line", [[1, 2, 3], [1, 2]], [["a", 1], [1, 2]], [[200, 1], [1, 2]], [[True, 1], [1, 2]],
                     [[-88, 42]] * (linear.MAX_POINTS + 1)):
            with self.subTest(line=str(line)[:30]):
                res = self.post("plan", body(line=line))
                self.assertEqual(res.status_code, 400)
                self.assertIn("line must be", res.json()["error"])
        res = self.post("plan", body(line=[[-88, 42]]))
        self.assertEqual(res.status_code, 400)
        self.assertIn("center line needs between 2", res.json()["error"])
        self.assertIn("must be text", self.post("plan", body(height_mode=1)).json()["error"])

    def test_a_linear_route_with_the_dsm_follow_fetches_the_terrain_and_embeds_it(self):
        route = routes.create(owner=self.user, name="Fence", route_type="linear")
        b = body(height_mode="realTimeFollowSurface", surface_follow="dsm", route_id=route.id)
        try:
            self.assertEqual(self.post("export", b).status_code, 409)
            with mock.patch.object(terrain, "fetch_terrain", return_value=(terrain_tif(), TERRAIN_INFO)) as fetch:
                res = self.post("routes/%d/terrain" % route.id, b)
            self.assertEqual(res.status_code, 200, res.content[:300])
            self.assertIn(LINE[1], fetch.call_args.args[0])
            res = self.post("export", b)
            self.assertEqual(res.status_code, 200, res.content[:300])
            self.assertIn("wpmz/res/dsm/" + TERRAIN_INFO["name"], files(res.content))
        finally:
            route.delete()

    def test_a_linear_route_is_saved_with_its_type(self):
        res = self.post("routes", {"name": "Fence", "route_type": "linear", "model": "m4t", "settings": {"left_extend": "50"}})
        self.assertEqual(res.status_code, 201, res.content[:300])
        self.assertEqual(routes.get(res.json()["id"]).route_type, "linear")

    def copy(self, settings):
        source = routes.create(owner=self.user, name="Fence", route_type="linear", model="m4t", settings=settings)
        res = self.post("routes/%d/copy" % source.id, {"model": "m4e"})
        self.assertEqual(res.status_code, 201, res.content[:300])
        self.assertEqual(res.json()["route_type"], "linear")
        return res.json()["settings"]

    def test_a_copy_for_another_model_keeps_the_ground_sample_distance_of_a_zigzag(self):
        self.assertEqual(self.copy({"height": "50", "single_line": "false"})["height"], "66.6")

    def test_a_copy_of_a_single_line_keeps_its_height(self):
        self.assertEqual(self.copy({"height": "50", "single_line": "true"}),
                         {"height": "50", "single_line": "true", "lens_visible": "true", "lens_ir": "false"})

    def test_a_pilot_2_linear_route_is_imported_with_its_plan_summary(self):
        res = self.client.post(API + "routes/import", {"file": SimpleUploadedFile("Fence.kmz", sample("m4t-test-linear-zigzag.kmz"))})
        self.assertEqual(res.status_code, 201, res.content[:300])
        route = routes.get(res.json()["id"])
        self.assertEqual((route.name, route.route_type, route.settings["height"]), ("Fence", "linear", "119.52434"))
        self.assertEqual(res.json()["summary"]["lines"], 8)
