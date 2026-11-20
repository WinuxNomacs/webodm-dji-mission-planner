"""
Geometric routes of the mission planner: missions/geometric.py, checked against the roof and the walls of the
geometric route Pilot 2 exported (tests/fixtures/dji-kmz/m4t-test-geo.kmz), the plugin's API for them
(api.py), and their import from Pilot 2 (missions/kmz_import.py).
"""
import json
import re
from unittest import mock
from xml.etree import ElementTree as ET

import numpy as np
from django.contrib.auth.models import User
from django.contrib.gis.geos import Point, Polygon
from pyproj import Transformer
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase

from .. import surface
from ..missions import geometric
from ..missions.cameras import M4T_THERMAL, M4T_WIDE
from ..missions.kmz_import import KmzImportError, read_kmz_route
from ..missions.planning import PlanError
from ..missions.wpml import GEOD
from app.models import Project, Task

from .. import routes
from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase
from .test_mission_kmz_import import edited, element, files, sample
from .test_mission_slope import NS, NOW, dsm_extent, tags, value

API = "/api/plugins/mission_planner/"
from .. import api as mission_planner_api

# The sample's block: a 6-corner outline (one corner turned in) on ground 214.47 m high, 4.5 m tall (WGS84-ellipsoidal)
OUTLINE = [(-85.0204778615549, 42.1034694739055), (-85.0202918815305, 42.1034579575324),
           (-85.0203112126116, 42.1033088535657), (-85.0204646355264, 42.1033220367196),
           (-85.0204581241322, 42.1033834057391), (-85.0204900703479, 42.1033894668811)]
BASE = 214.471572575547
TOP = BASE + 4.5
# The sample's walls: its points after the roof's
WALLS = 253
# The sample's roof lines: the first point of each (its points after a line's last are the next's)
ROOF_LINES = [0, 6, 12, 18, 24, 32, 40, 48, 60, 70, 80, 90, 98, 106, 114, 122, 130, 138, 146, 154, 162, 170, 178, 186,
              194, 204, 212, 220, 228, 234, 240, 246, 252]
POSE_NAMES = {(-90, 0): "down", (-60, -45): "forward left", (-120, -45): "backward left", (-120, 45): "backward right",
              (-60, 45): "forward right"}


def route(**over):
    """The sample's settings"""
    kw = dict(outline=OUTLINE, base=BASE, top=TOP, cameras=[M4T_WIDE, M4T_THERMAL], height=6.2, overlap_h=80,
              overlap_w=80, speed=0.7, takeoff_security_height=20, rth_height=100, transitional_speed=4,
              takeoff_ref_point=(42.103439, -85.020555, 208.645348), author="pilot@example.com")
    kw.update(over)
    return geometric.settings(**kw)


def placemarks(wpml):
    """Each Placemark of a waylines.wpml: (lon, lat), height, speed, heading, turn, damping, straight line, and the
    Smart Oblique poses it starts ((pitch, yaw), ...)"""
    out = []
    for pm in ET.fromstring(wpml).iter("{%s}Placemark" % NS["k"]):
        text = lambda tag: pm.find(".//w:" + tag, NS).text
        lon, lat = map(float, pm.find("k:Point/k:coordinates", NS).text.split(","))
        poses = tuple((round(float(point.find("w:smartObliqueEulerPitch", NS).text)), round(float(point.find("w:smartObliqueEulerYaw", NS).text)))
                      for point in pm.iter("{%s}smartObliquePoint" % NS["w"]))
        out.append(dict(at=(lon, lat), height=float(text("executeHeight")), speed=float(text("waypointSpeed")),
                        mode=text("waypointHeadingMode"), heading=float(text("waypointHeadingAngle")),
                        turn=text("waypointTurnMode"), damping=float(text("waypointTurnDampingDist")),
                        straight=text("useStraightLine"), poses=poses))
    return out


def sample_files():
    return {name: content.decode() for name, content in files(sample("m4t-test-geo.kmz")).items()}


def export(s=None):
    s = s or route()
    return {name: content.decode() for name, content in files(geometric.build_kmz(geometric.plan(s), s, now=NOW)).items()}


def turned(angle):
    return (angle + 180) % 360 - 180


def without_roof(data):
    """A Pilot 2 geometric file with its top face turned off"""
    return edited(data, element("shootTopFaceEnable", 0))


class TestGeometricSettings(SimpleTestCase):
    def test_a_block_needs_an_outline_and_a_top_above_its_base(self):
        with self.assertRaisesRegex(PlanError, "between 3 and 50 corners"):
            route(outline=OUTLINE[:2])
        for top in (BASE, BASE - 1, BASE + 600):
            with self.subTest(top=top):
                with self.assertRaisesRegex(PlanError, "top must be between"):
                    route(top=top)
        with self.assertRaisesRegex(PlanError, "heights of the base"):
            route(base=float("nan"))
        with self.assertRaisesRegex(PlanError, "distance from the walls"):
            route(height=1)

    def test_an_outline_that_crosses_itself_is_refused(self):
        a, b, c, d = OUTLINE[:4]
        with self.assertRaisesRegex(PlanError, "crosses itself"):
            geometric.plan(route(outline=[a, c, b, d]))


class TestGeometricPlan(SimpleTestCase):
    def test_the_walls_are_flown_as_pilot_2_flies_them(self):
        ours = placemarks(export()["wpmz/waylines.wpml"])[geometric.plan(route()).roof_points:]
        theirs = placemarks(sample_files()["wpmz/waylines.wpml"])[WALLS:]
        self.assertEqual(len(ours), len(theirs))
        for i, (a, b) in enumerate(zip(ours, theirs)):
            with self.subTest(i=i):
                # Pilot 2 offsets the walls on a sphere: up to 6 cm from the true distance here
                self.assertLess(GEOD.inv(a["at"][0], a["at"][1], b["at"][0], b["at"][1])[2], 0.07)
                self.assertAlmostEqual(a["height"], b["height"], delta=0.002)
                self.assertAlmostEqual(turned(a["heading"] - b["heading"]), 0, delta=0.01)
                self.assertEqual((a["mode"], a["turn"], a["straight"]), (b["mode"], b["turn"], b["straight"]))
                self.assertAlmostEqual(a["damping"], b["damping"], delta=0.02)

    def test_the_roof_is_flown_as_pilot_2_flies_it(self):
        p = geometric.plan(route())
        ours = placemarks(export()["wpmz/waylines.wpml"])[:p.roof_points]
        theirs = placemarks(sample_files()["wpmz/waylines.wpml"])[:WALLS]
        self.assertEqual(len(p.roof), len(ROOF_LINES) - 1)
        starts = np.cumsum([0] + [len(line) for line in p.roof])
        mismatched, errors, dampings = [], [], []
        for i, (ours_at, theirs_at, theirs_end) in enumerate(zip(starts, ROOF_LINES, ROOF_LINES[1:])):
            a, b = ours[ours_at:starts[i + 1]], theirs[theirs_at:theirs_end]
            if len(a) != len(b):
                mismatched.append(i)
                continue
            for x, y in zip(a, b):
                errors.append(GEOD.inv(x["at"][0], x["at"][1], y["at"][0], y["at"][1])[2])
                self.assertEqual([POSE_NAMES[q] for q in x["poses"]], [POSE_NAMES[q] for q in y["poses"]])
                self.assertAlmostEqual(x["speed"], y["speed"], delta=y["speed"] * 0.001)
                self.assertAlmostEqual(x["height"], y["height"], delta=0.001)
                # A third of the shorter leg on either side: at the end of a line, the short turn to the next one
                self.assertAlmostEqual(x["damping"], y["damping"], delta=0.35)
                dampings.append(abs(x["damping"] - y["damping"]))
                self.assertEqual((x["mode"], x["turn"], x["straight"]), (y["mode"], y["turn"], y["straight"]))
        # Where a view runs along an edge of the roof (its notch, 1.5 degrees off the lines) Pilot 2's sphere and
        # the true distances part, and one line changes its poses once less; elsewhere the pose changes are
        # Pilot 2's within half a meter, a few centimeters on average
        self.assertEqual(mismatched, [10])
        self.assertLess(max(errors), 0.5)
        self.assertLess(np.mean(errors), 0.07)
        self.assertLess(np.mean(dampings), 0.03)
        # The aircraft then goes over the walls' first point, and down to it
        self.assertLess(GEOD.inv(*ours[-1]["at"], *theirs[-1]["at"])[2], 0.07)
        self.assertEqual((ours[-1]["turn"], ours[-1]["heading"]), (theirs[-1]["turn"], 0))

    def test_the_roof_lines_run_the_way_the_outline_is_narrowest(self):
        s = route()
        _, outline = geometric.frame(s)
        self.assertEqual(geometric.roof_direction(outline), 6)
        p = geometric.plan(s)
        self.assertAlmostEqual(GEOD.inv(*p.roof[0][0][:2], *p.roof[0][-1][:2])[0], -174, delta=0.01)
        self.assertAlmostEqual(p.roof_speed, float(value("topFaceFlightSpeed", sample_files()["wpmz/template.kml"])), delta=0.001)
        # Each line runs on 30 m past the roof, 6.2 m above its top
        self.assertTrue(all(abs(GEOD.inv(*line[0][:2], *line[1][:2])[2] - 30) < 1e-6 for line in p.roof))
        self.assertTrue(all(abs(h - TOP - 6.2) < 1e-9 for line in p.roof for _, _, h in line))

    def test_without_the_roof_only_the_walls_are_flown(self):
        p = geometric.plan(route(roof=False))
        self.assertEqual((p.roof, p.roof_points, p.roof_photos), ([], 0, 0))
        self.assertEqual(len(p.waypoints), 196)
        self.assertEqual(p.waypoints, geometric.plan(route()).waypoints[geometric.plan(route()).roof_points:])

    def test_the_loops_are_level_from_just_under_the_top_to_just_over_the_base(self):
        p = geometric.plan(route())
        heights = [loop[0][2] for loop in p.loops]
        self.assertEqual(len(heights), 7)
        self.assertAlmostEqual(p.spacing, 0.63488, delta=1e-6)      # the thermal photos' height, 80% overlapped
        self.assertAlmostEqual(TOP - heights[0], heights[-1] - BASE, delta=1e-9)
        self.assertTrue(all(abs(h - loop[0][2]) < 1e-9 for loop in p.loops for _, _, h in loop))
        self.assertTrue(all(abs(a - b - p.spacing) < 1e-9 for a, b in zip(heights, heights[1:])))

    def test_the_loops_are_flown_back_and_forth_dropping_from_one_to_the_next(self):
        p = geometric.plan(route())
        for a, b in zip(p.loops, p.loops[1:]):
            self.assertEqual(a[-1][:2], b[0][:2])
        self.assertEqual(p.loops[1][1:-1], [pt[:2] + (p.loops[1][0][2],) for pt in reversed(p.loops[0][1:-1])])

    def test_the_block_is_on_the_left_however_the_outline_was_drawn(self):
        for outline in (OUTLINE, OUTLINE[::-1]):
            loop = np.array([pt[:2] for pt in geometric.plan(route(outline=outline)).loops[0]])
            loop = (loop - loop.mean(axis=0)) * [np.cos(np.radians(42.1)), 1]
            self.assertGreater(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(loop, np.roll(loop, -1, axis=0))), 0)

    def test_the_photos_and_speed_are_those_of_the_walls(self):
        p = geometric.plan(route())
        self.assertAlmostEqual(p.interval, float(re.search(r"multipleDistance</wpml:actionTriggerType>\s*<wpml:actionTriggerParam>([^<]+)",
                                                           sample_files()["wpmz/waylines.wpml"]).group(1)), delta=1e-6)
        self.assertAlmostEqual(p.max_speed, p.interval / 1.25)
        self.assertEqual(geometric.speed_of(p, route(speed=None)), 0.6)
        walls = geometric.plan(route(roof=False))
        self.assertAlmostEqual(walls.duration, walls.distance / 0.7)
        # Over the roof, as slowly as its poses need: in all, close to the time and distance Pilot 2 gives
        theirs = sample_files()["wpmz/waylines.wpml"]
        self.assertAlmostEqual(p.distance, float(value("distance", theirs)), delta=2)
        self.assertAlmostEqual(p.duration, float(value("duration", theirs)), delta=20)

    def test_the_warnings_say_when_the_photos_cannot_keep_up_or_a_corner_is_close(self):
        s = route(roof=False)
        warnings = geometric.mission_warnings(geometric.plan(s), s)
        self.assertEqual(len(warnings), 2)
        self.assertIn("more than the 0.6 m/s", warnings[0])
        # A sharp corner: the bevel passes closer to it than the distance from the walls
        sharp = route(outline=[(-85.020428, 42.1033), (-85.020028, 42.1034), (-85.020428, 42.10335)], speed=None)
        self.assertTrue(any("sharp corner" in w for w in geometric.mission_warnings(geometric.plan(sharp), sharp)))
        low = route(rth_height=10, speed=None)
        self.assertTrue(any("return height" in w for w in geometric.mission_warnings(geometric.plan(low), low)))

    def test_the_warnings_say_the_roof_runs_on_past_it_and_needs_more_than_a_battery(self):
        s = route()
        warnings = geometric.mission_warnings(geometric.plan(s), s)
        self.assertTrue(any("run on 30 m past it each way, 6.2 m above its top" in w for w in warnings))
        self.assertTrue(any("about 107 minutes, more than one battery" in w for w in warnings))


class TestGeometricExport(SimpleTestCase):
    def test_the_template_has_the_block_as_pilot_2_writes_it(self):
        ours, theirs = export()["wpmz/template.kml"], sample_files()["wpmz/template.kml"]
        self.assertEqual(tags(ours), tags(theirs))
        for tag in ("templateType", "heightMode", "globalShootHeight", "height", "trajectoryType", "startPositionType",
                    "orthoCameraOverlapH", "orthoCameraOverlapW", "imageFormat", "payloadSubEnumValue", "takeOffRefPoint",
                    "autoFlightSpeed", "scanExtent", "scanOffset", "shootTopFaceEnable"):
            self.assertEqual(value(tag, ours), value(tag, theirs), tag)
        self.assertAlmostEqual(float(value("topFaceFlightSpeed", ours)), float(value("topFaceFlightSpeed", theirs)), delta=0.001)
        self.assertEqual(value("shootTopFaceEnable", export(route(roof=False))["wpmz/template.kml"]), "0")
        coordinates = lambda xml: re.search(r"<coordinates>(.*?)</coordinates>", xml, re.S).group(1)
        self.assertEqual(coordinates(ours), coordinates(theirs))

    def test_the_waylines_have_the_elements_of_pilot_2s_roof_and_walls(self):
        ours, theirs = export()["wpmz/waylines.wpml"], sample_files()["wpmz/waylines.wpml"]
        header = lambda xml: tags(xml[:xml.index("<Placemark>")])
        self.assertEqual(header(ours), header(theirs))
        self.assertEqual(value("gimbalPitchRotateAngle", ours), "-90")
        walls = geometric.plan(route()).roof_points
        ours_at, theirs_at = ours.split("<Placemark>")[1:], theirs.split("<Placemark>")[1:]
        # The roof's start, a stretch with one pose and one with two, the end of the poses, the turn to the next line
        for i in range(7):
            self.assertEqual(tags(ours_at[i]), tags(theirs_at[i]), i)
        # Over the walls' start, the walls' start (the gimbal levelled and focused, the photos started), a point on a
        # wall, and a corner
        for i in (-1, 0, 1, 2):
            self.assertEqual(tags(ours_at[walls + i]), tags(theirs_at[WALLS + i]), i)
        self.assertEqual(len(re.findall("<wpml:actionGroupId>", ours)), len(set(re.findall(r"<wpml:actionGroupId>(\d+)<", ours))))
        last = ours_at[-1]
        self.assertIn("stopContinuousShooting", last)
        self.assertNotIn("payloadLensIndex", ours)

    def test_the_waylines_without_the_roof_start_at_the_walls(self):
        ours = export(route(roof=False))["wpmz/waylines.wpml"]
        self.assertNotIn("SmartOblique", ours)
        self.assertEqual(value("gimbalPitchRotateAngle", ours), "0")
        self.assertIn("startContinuousShooting", ours.split("<Placemark>")[1])

    def test_the_same_route_exports_the_same_file_again(self):
        s = route()
        p = geometric.plan(s)
        self.assertEqual(geometric.build_kmz(p, s, now=NOW), geometric.build_kmz(p, s, now=NOW))


def body(**over):
    b = {"route_type": "geometric", "model": "m4t", "name": "luxodm-geometric", "cameras": ["visable", "ir"],
         "outline": [list(c) for c in OUTLINE], "base": BASE, "top": TOP, "height": 6.2, "overlap_h": 80,
         "overlap_w": 80, "speed": 0.7, "takeoff_security_height": 20, "rth_height": 100, "transitional_speed": 4,
         "takeoff_ref_point": [42.103439, -85.020555, 208.645348]}
    b.update(over)
    return b


def exported(b):
    s = mission_planner_api.parse_geometric_settings(b)
    return geometric.build_kmz(geometric.plan(s), s, now=NOW)


class TestGeometricImport(SimpleTestCase):
    def test_pilot_2s_block_imports_with_its_roof(self):
        model, s, b = read_kmz_route(sample("m4t-test-geo.kmz"), "x")
        self.assertEqual((model, b["route_type"], s["height"], s["speed"]), ("m4t", "geometric", "6.2", "0.7"))
        self.assertEqual(s["outline"], [[round(c[0], 9), round(c[1], 9)] for c in OUTLINE])
        self.assertEqual((s["base"], s["top"]), ("214.47157", "218.97157"))
        self.assertEqual((s["roof"], b["roof"]), ("true", True))
        p = geometric.plan(mission_planner_api.parse_geometric_settings(b))
        self.assertEqual((len(p.loops), len(p.roof)), (7, 32))

    def test_pilot_2s_block_imports_without_its_roof(self):
        model, s, b = read_kmz_route(without_roof(sample("m4t-test-geo.kmz")), "x")
        self.assertEqual((s["roof"], b["roof"]), ("false", False))
        self.assertEqual(geometric.plan(mission_planner_api.parse_geometric_settings(b)).roof, [])

    def test_a_route_the_planner_exported_imports_as_the_same_file(self):
        data = exported(body(outline=[[round(c[0], 9), round(c[1], 9)] for c in OUTLINE], base=214.5, top=219, height=7))
        model, s, again = read_kmz_route(data, "luxodm-geometric")
        self.assertEqual(files(exported(again)), files(data))
        walls = exported(body(outline=[[round(c[0], 9), round(c[1], 9)] for c in OUTLINE], base=214.5, top=219, height=7,
                              roof=False))
        self.assertEqual(files(exported(read_kmz_route(walls, "luxodm-geometric")[2])), files(walls))

    def test_what_the_planner_cannot_fly_is_refused(self):
        data = exported(body())
        for replacement, reason in ((element("heightMode", "relativeToStartPoint"), "above sea level"),
                                    (element("trajectoryType", "vert"), "up and down"),
                                    (element("startPositionType", "bottom"), "bottom"),
                                    (element("shootType", "time"), "seconds"),
                                    (element("height", 0), "height must be between"),
                                    (element("globalShootHeight", 600), "between 2 and 500")):
            with self.subTest(reason):
                with self.assertRaisesRegex(KmzImportError, reason):
                    read_kmz_route(edited(data, replacement), "x")


class TestBlockHeightsGrid(SimpleTestCase):
    def test_a_long_thin_outline_across_its_box_is_tested_at_a_bounded_number_of_cells(self):
        # 2 m wide and 300 m long, from corner to corner of its box: its area allows a 0.5 m grid, its box 360,000 cells
        to_lonlat = Transformer.from_crs(32616, 4326, always_xy=True)
        x, y = 663700.0, 4663000.0
        outline = [list(to_lonlat.transform(*c)) for c in ((x, y), (x + 1.4, y - 1.4), (x + 213.5, y + 210.7), (x + 212.1, y + 212.1))]
        view = mission_planner_api.BlockHeightsView()
        with mock.patch.object(mission_planner_api, "Point", wraps=Point) as tested:
            ring, inside = view.sample_points(outline, 32616)
        self.assertLessEqual(tested.call_count, view.MAX_POINTS * 1.05)
        self.assertLessEqual(len(ring), view.MAX_POINTS)
        self.assertGreater(len(inside), 0)

    def test_a_long_outline_s_ring_is_read_at_a_bounded_number_of_points(self):
        to_lonlat = Transformer.from_crs(32616, 4326, always_xy=True)
        x, y = 663700.0, 4663000.0
        outline = [list(to_lonlat.transform(*c)) for c in ((x, y), (x + 20000, y), (x + 20000, y + 2), (x, y + 2))]
        ring, _ = mission_planner_api.BlockHeightsView().sample_points(outline, 32616)
        self.assertLessEqual(len(ring), mission_planner_api.BlockHeightsView.MAX_POINTS)


class TestGeometricApi(BootTestCase):
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

    def test_the_plan_of_a_geometric_route_has_its_loops_points_and_side_view(self):
        res = self.post("plan", body())
        self.assertEqual(res.status_code, 200, res.content[:300])
        data = res.json()
        summary = data["summary"]
        self.assertEqual((summary["loops"], summary["waypoints"], summary["roof_lines"]), (7, 448, 32))
        self.assertTrue(summary["roof"])
        self.assertAlmostEqual(summary["roof_spacing"], 0.7936, delta=1e-4)
        self.assertAlmostEqual(summary["undulation"], -34.2, delta=0.1)
        passes = [f["properties"]["pass"] for f in data["lines"]["features"]]
        self.assertEqual(passes, ["roof"] * 32 + ["walls"] * 7)
        self.assertEqual([f["properties"]["pass"] for f in data["waypoints"]["features"]][251:253], ["roof", "walls"])
        self.assertEqual(len(data["waypoints"]["features"][0]["geometry"]["coordinates"]), 3)
        profile = summary["profile"]
        self.assertEqual(profile["face"], [[0, round(TOP, 3)], [0, round(BASE, 3)]])
        self.assertEqual([out for out, _ in profile["lines"]], [6.2] * 7)
        self.assertEqual(profile["roof"], [[-6.2, round(TOP + 6.2, 3)], [0, round(TOP + 6.2, 3)]])
        walls = self.post("plan", body(roof=False)).json()
        self.assertEqual((walls["summary"]["waypoints"], walls["summary"]["roof_lines"], walls["summary"]["profile"]["roof"]),
                         (196, 0, None))
        self.assertIn("on or off", self.post("plan", body(roof="yes")).json()["error"])

    def test_a_geometric_route_exports_as_pilot_2s_prism(self):
        res = self.post("export", body())
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res["Content-Disposition"], 'attachment; filename="luxodm-geometric.kmz"')
        self.assertIn("<wpml:templateType>mappingPrism<", files(res.content)["wpmz/template.kml"].decode())

    def test_a_bad_outline_or_height_is_refused(self):
        for outline in (None, "outline", [["a", 1]] * 3, [[200, 1]] * 3, [[True, 1]] * 3, [[-88, 42, 1]] * 3,
                        [[-88, 42]] * 51):
            with self.subTest(outline=str(outline)[:30]):
                res = self.post("plan", body(outline=outline))
                self.assertEqual(res.status_code, 400)
                self.assertIn("outline must be", res.json()["error"])
        for name in ("base", "top"):
            res = self.post("plan", body(**{name: "high"}))
            self.assertIn("%s must be a height" % name, res.json()["error"])

    def test_a_geometric_route_is_saved_and_copied_with_its_type(self):
        res = self.post("routes", {"name": "Barn", "route_type": "geometric", "model": "m4t", "settings": {"height": "6.2"}})
        self.assertEqual(res.status_code, 201, res.content[:300])
        res = self.post("routes/%d/copy" % res.json()["id"], {"model": "m4e"})
        self.assertEqual(res.json()["route_type"], "geometric")

    def test_a_pilot_2_geometric_route_is_imported_with_its_plan_summary(self):
        res = self.client.post(API + "routes/import", {"file": SimpleUploadedFile("Barn.kmz", sample("m4t-test-geo.kmz"))})
        self.assertEqual(res.status_code, 201, res.content[:300])
        route = routes.get(res.json()["id"])
        self.assertEqual((route.name, route.route_type, len(route.settings["outline"])), ("Barn", "geometric", 6))
        self.assertEqual(route.settings["roof"], "true")
        self.assertEqual((res.json()["summary"]["loops"], res.json()["summary"]["roof_lines"]), (7, 32))

    def test_only_tasks_with_an_elevation_raster_are_looked_in_and_with_the_fields_read(self):
        extent = dsm_extent([-85.021728, 42.103, -85.019728, 42.104])
        project = Project.objects.get(name="User Test Project")
        dsm = Task.objects.create(project=project, name="DSM", epsg=32616, available_assets=["dsm.tif"], dsm_extent=extent)
        dtm = Task.objects.create(project=project, name="DTM", epsg=32616, available_assets=["dtm.tif"], dsm_extent=extent)
        Task.objects.create(project=project, name="Photos only", epsg=32616, available_assets=["orthophoto.tif"], dsm_extent=extent)
        area = Polygon([(-85.020928, 42.1034), (-85.020528, 42.1034), (-85.020528, 42.1036), (-85.020928, 42.1036), (-85.020928, 42.1034)])
        found = mission_planner_api.tasks_covering(self.user, area, 20)
        self.assertEqual({t.name for t in found}, {"DSM", "DTM"})
        self.assertEqual({t.id for t in found}, {dsm.id, dtm.id})
        with self.assertNumQueries(0):              # all a caller reads, without a query each
            for task in found:
                (task.epsg, task.name, task.project.id, task.project.name, task.get_check_file_asset_path("dsm.tif"))
        self.assertLessEqual({"options", "orthophoto_extent", "potree_scene", "crop"}, found[0].get_deferred_fields())

    def test_the_base_and_top_come_from_the_dsm_of_the_tasks_the_user_can_see(self):
        extent = dsm_extent([-85.021728, 42.103, -85.019728, 42.104])
        mine = Task.objects.create(project=Project.objects.get(name="User Test Project"), name="Barn survey",
                                   epsg=32616, available_assets=["dsm.tif"], dsm_extent=extent)
        Task.objects.create(project=Project.objects.get(name="User 2 Test Project"), name="Not mine", epsg=32616,
                            available_assets=["dsm.tif"], dsm_extent=extent)
        Task.objects.create(project=Project.objects.get(name="User Test Project"), name="Too small", epsg=32616,
                            available_assets=["dsm.tif"], dsm_extent=dsm_extent([-85.020488, 42.10331, -85.020288, 42.10347]))
        outline = [list(c) for c in OUTLINE]

        def heights(task, points, cloud=True):
            # The ground round the block 214 m and up (lowest 213.9), the roof up to 219.2
            ring = len(points) - sum(1 for x, y in points if inside.contains(Point(x, y, srid=32616)))
            return np.concatenate([np.linspace(213.9, 214.6, ring), np.linspace(218.0, 219.2, len(points) - ring)]), "dsm"

        # In UTM with pyproj, longitude first, as the API transforms
        to_utm = Transformer.from_crs(4326, 32616, always_xy=True)
        corners = [to_utm.transform(lon, lat) for lon, lat in OUTLINE]
        inside = Polygon(corners + [corners[0]], srid=32616)
        with mock.patch.object(surface, "surface_heights", side_effect=heights) as read:
            res = self.post("block-heights", {"outline": outline})
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res.json()["tasks"], [{"id": str(mine.id), "project": mine.project.id,
                                                "project_name": "User Test Project", "name": "Barn survey",
                                                "base": 213.9, "top": 219.2, "source": "dsm"}])
        # In the task's UTM zone, the ring 1.5 m outside the outline
        points = read.call_args.args[1]
        self.assertAlmostEqual(points[0][0], 663700, delta=10000)
        ring = points[:-sum(1 for x, y in points if inside.contains(Point(x, y, srid=32616)))]
        distances = [inside.exterior_ring.distance(Point(x, y)) for x, y in ring]
        self.assertAlmostEqual(min(distances), 1.5, delta=0.03)
        self.assertAlmostEqual(max(distances), 1.5, delta=0.03)
        # Too little of the ground in the DSM
        with mock.patch.object(surface, "surface_heights", return_value=(np.full(len(points), np.nan), "dsm")):
            self.assertEqual(self.post("block-heights", {"outline": outline}).json()["tasks"], [])
        self.assertEqual(self.post("block-heights", {"outline": outline[:2]}).status_code, 400)
        self.assertEqual(self.post("block-heights", {"outline": [[1, 2, 3]]}).status_code, 400)
