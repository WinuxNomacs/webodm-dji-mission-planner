"""
Tests of the mission planner plugin (mission_planner): its API and its page. The planning itself is tested in
test_mission_planning and test_mission_wpml; here it is the request checking, the JSON and the file that come out.
"""
import io
import json
import os
import re
import zipfile
from unittest import mock

import numpy as np
from xml.etree import ElementTree as ET

from django.contrib.auth.models import User
from django.test import Client
from rest_framework import status

from ..missions import terrain
from ..missions.cameras import M4E_WIDE, M4T_THERMAL, M4T_WIDE, ground_sample_distance
from ..missions.elevation import ElevationError
from ..missions.planning import plan_survey
from .. import routes
from app.plugins import enable_plugin, disable_plugin, get_plugin_by_name
from app.tests.classes import BootTestCase
from .test_mission_planning import LON0, LAT0, NS, bearing, distance, parse_kmz, rectangle
from .test_mission_terrain import geotiff

API = "/api/plugins/mission_planner/"
PUBLIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public") + os.sep

# The route editor's elements that only a linear route has, the ones only an area route has, the ones only a slope route
# has, and those of the height modes (which a slope route has not: it flies its corners' heights)
SLOPE_ONLY_IDS = ("mp-corners", "mp-face-heights", "mp-face-status", "mp-face-tasks", "mp-profile", "mp-profile-svg",
                  "mp-undulation-note")
# A geometric route has the side view and the undulation note too (SIDE_VIEW_IDS), and the block's heights
SIDE_VIEW_IDS = ("mp-profile", "mp-profile-svg", "mp-undulation-note")
GEOMETRIC_ONLY_IDS = ("mp-base", "mp-top", "mp-block-heights", "mp-block-status", "mp-block-tasks", "mp-roof")
HEIGHT_MODE_IDS = ("mp-terrain-row", "mp-surface-follow", "mp-surface-follow-row", "mp-dsm-row", "mp-terrain-source", "mp-fetch-terrain",
                   "mp-terrain-status", "mp-elevation")
LINEAR_ONLY_IDS = ("mp-left-extend", "mp-left-extend-label", "mp-right-extend", "mp-right-extend-label", "mp-single-line")
AREA_ONLY_IDS = ("mp-direction", "mp-direction-slider", "mp-margin", "mp-margin-label", "mp-photo-mode",
                 "mp-collection-mode", "mp-oblique-fields", "mp-start-button", "mp-start-text", "mp-longest",
                 "mp-gimbal-pitch", "mp-inclined-overlap-h", "mp-inclined-overlap-w", "mp-inclined-speed",
                 "mp-inclined-speed-label", "mp-inclined-speed-toggle")

# Patched with mock.patch.object: the module's dotted name is coreplugins.mission_planner.api in dev and
# plugins.mission_planner.api when installed from the zip
from .. import api as mission_planner_api


def body(**over):
    b = {"polygon": [list(p) for p in rectangle(60, 40)], "direction": 0, "height": 30, "cameras": ["visable", "ir"],
         "overlap_h": 80, "overlap_w": 70, "margin": 0}
    b.update(over)
    return b


def route_url(route):
    # No trailing slash: matches the MountPoint regex in plugin.py and every link routes_list.js generates.
    return "/plugins/mission_planner/route/%d" % route.id


class TestPlannerPlugin(BootTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.route = routes.create(owner=User.objects.get(username="testuser"), name="Test route", route_type="area")

    def tearDown(self):
        disable_plugin("mission_planner")

    def post(self, path, data, client=None):
        return (client or self.client).post(API + path, json.dumps(data), content_type="application/json")

    def error(self, data, expect=400):
        res = self.post("plan", data)
        self.assertEqual(res.status_code, expect, res.content[:200])
        return res.json().get("error", "")

    def test_the_plugin_is_disabled_by_default_and_loads(self):
        disable_plugin("mission_planner")
        self.assertIsNone(get_plugin_by_name("mission_planner"))
        self.assertIsNotNone(get_plugin_by_name("mission_planner", only_active=False))

    # -- who can use it ---------------------------------------------------------------------------------------------

    def test_anonymous_users_cannot_plan_or_export(self):
        for path in ("plan", "export"):
            res = self.post(path, body(), client=Client())
            self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN), path)

    def test_the_page_needs_a_login(self):
        res = Client().get("/plugins/mission_planner/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login/", res["Location"])

    def test_only_post_is_accepted(self):
        self.assertEqual(self.client.get(API + "plan").status_code, 405)
        self.assertEqual(self.client.get(API + "export").status_code, 405)

    # -- plan ---------------------------------------------------------------------------------------------------------

    def test_a_model_that_is_not_a_name_is_refused_with_a_message(self):
        for path in ("plan", "export"):
            res = self.post(path, body(model=[1]))
            self.assertEqual(res.status_code, 400, (path, res.content[:200]))
        res = self.post("routes/%d/copy" % self.route.id, {"model": {"m4e": 1}})
        self.assertEqual(res.status_code, 400, res.content[:200])

    def test_a_survey_whose_photos_need_under_a_tenth_of_a_meter_a_second_is_planned(self):
        res = self.post("plan", body(height=4, overlap_h=95, polygon=[list(p) for p in rectangle(20, 20)]))
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertGreater(res.json()["summary"]["speed"], 0)

    def test_the_plan_is_what_the_planner_computes(self):
        res = self.post("plan", body())
        self.assertEqual(res.status_code, 200, res.content[:300])
        data = res.json()
        plan = plan_survey([tuple(p) for p in rectangle(60, 40)], 0, 30.0, [M4T_WIDE, M4T_THERMAL], overlap_h=80, overlap_w=70)

        s = data["summary"]
        self.assertEqual(s["lines"], len(plan.lines))
        self.assertEqual(s["waypoints"], len(plan.waypoints))
        self.assertEqual(s["photos"], plan.photos)
        self.assertAlmostEqual(s["spacing"], plan.spacing, places=9)
        self.assertAlmostEqual(s["interval"], plan.interval, places=9)
        self.assertAlmostEqual(s["distance"], plan.distance, places=6)
        self.assertLessEqual(s["speed"], s["max_speed"] + 1e-9)
        self.assertAlmostEqual(s["duration"], plan.distance / s["speed"], places=6)
        self.assertAlmostEqual(s["gsd"]["ir"], 0.03, places=6)                 # 30 m: 3 cm thermal pixels
        self.assertEqual(sorted(s["gsd"]), ["ir", "visable"])

    def test_the_lines_and_waypoints_come_as_geojson(self):
        data = self.post("plan", body()).json()
        lines, points = data["lines"], data["waypoints"]
        self.assertEqual(lines["type"], "FeatureCollection")
        self.assertEqual(len(lines["features"]), data["summary"]["lines"])
        for f in lines["features"]:
            self.assertEqual(f["geometry"]["type"], "LineString")
            a, b = f["geometry"]["coordinates"]
            self.assertAlmostEqual(distance(a, b), 40.0, delta=0.25)
        self.assertEqual(len(points["features"]), 2 * len(lines["features"]))
        self.assertEqual([f["properties"]["index"] for f in points["features"]], list(range(len(points["features"]))))

    def test_a_closed_ring_is_the_same_area(self):
        ring = [list(p) for p in rectangle(60, 40)]
        open_plan = self.post("plan", body(polygon=ring)).json()
        closed_plan = self.post("plan", body(polygon=ring + [ring[0]])).json()
        self.assertEqual(open_plan["summary"], closed_plan["summary"])

    def test_defaults_fill_what_is_left_out(self):
        res = self.post("plan", {"polygon": [list(p) for p in rectangle(60, 40)]})
        self.assertEqual(res.status_code, 200, res.content[:200])
        self.assertEqual(sorted(res.json()["summary"]["gsd"]), ["ir", "visable"])

    def test_warnings_are_passed_on(self):
        data = self.post("plan", body(speed=15)).json()
        self.assertTrue(any("missed" in w for w in data["warnings"]))
        data = self.post("plan", body(height_mode="relativeToStartPoint")).json()
        self.assertTrue(any("terrain" in w for w in data["warnings"]))

    def test_the_direction_is_a_true_bearing(self):
        data = self.post("plan", body(direction=45, polygon=[list(p) for p in rectangle(80, 80)])).json()
        for f in data["lines"]["features"]:
            a, b = f["geometry"]["coordinates"]
            self.assertLess(abs(((bearing(a, b) - 45 + 90) % 180) - 90), 0.05)

    # -- what is refused ----------------------------------------------------------------------------------------------

    def test_refuses_a_request_that_is_not_json_object(self):
        res = self.client.post(API + "plan", json.dumps([1, 2, 3]), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        res = self.client.post(API + "plan", "not json", content_type="application/json")
        self.assertEqual(res.status_code, 400)

    def test_refuses_bad_areas(self):
        self.assertIn("3 corners", self.error(body(polygon=[[1, 2], [3, 4]])))
        self.assertIn("3 corners", self.error({"height": 30}))
        self.assertIn("3 corners", self.error(body(polygon="square")))
        self.assertIn("too many", self.error(body(polygon=[[LON0 + i * 1e-6, LAT0 + (i % 2) * 1e-6] for i in range(201)])))
        self.assertIn("longitude, latitude", self.error(body(polygon=[[1, 2], [3, 4], ["a", 5]])))
        self.assertIn("longitude, latitude", self.error(body(polygon=[[1, 2], [3, 4], [500, 5]])))
        self.assertIn("longitude, latitude", self.error(body(polygon=[[1, 2], [3, 4], [5, 95]])))
        self.assertIn("longitude, latitude", self.error(body(polygon=[[1, 2], [3, 4], [True, 5]])))
        self.assertIn("longitude, latitude", self.error(body(polygon=[[1, 2], [3, 4], 5])))

    def test_refuses_areas_that_cannot_be_flown(self):
        bowtie = [[LON0, LAT0], [LON0 + 1e-3, LAT0 + 1e-3], [LON0 + 1e-3, LAT0], [LON0, LAT0 + 1e-3]]
        self.assertIn("not a valid polygon", self.error(body(polygon=bowtie)))
        flat = [[LON0, LAT0], [LON0 + 1e-4, LAT0], [LON0 + 2e-4, LAT0]]
        self.assertIn("not a valid polygon", self.error(body(polygon=flat)))

    def test_refuses_numbers_that_are_not_numbers_or_out_of_range(self):
        self.assertIn("height must be a number", self.error(body(height="tall")))
        self.assertIn("height must be a number", self.error(body(height=True)))
        self.assertIn("height must be a number", self.error(body(height=None)))
        self.assertIn("height must be between", self.error(body(height=1)))
        self.assertIn("height must be between", self.error(body(height=501)))
        self.assertIn("overlap along", self.error(body(overlap_h=5)))
        self.assertIn("overlap across", self.error(body(overlap_w=99)))
        self.assertIn("margin", self.error(body(margin=-3)))
        self.assertIn("speed", self.error(body(speed=0)))
        self.assertIn("speed", self.error(body(speed=30)))
        self.assertIn("return height", self.error(body(rth_height=1)))

    def test_refuses_unknown_choices(self):
        self.assertIn("cameras must be", self.error(body(cameras=["thermal"])))
        self.assertIn("cameras must be", self.error(body(cameras=[])))
        self.assertIn("cameras must be", self.error(body(cameras="ir")))
        self.assertIn("cannot be exported yet", self.error(body(cameras=["ir"])))          # never seen in a Pilot 2 file
        self.assertIn("height mode", self.error(body(height_mode="sky")))
        self.assertIn("must be text", self.error(body(height_mode=3)))
        self.assertIn("finish action", self.error(body(finish_action="crash")))
        self.assertIn("remote signal", self.error(body(exit_on_rc_lost="panic")))
        self.assertIn("takeoff_ref_point", self.error(body(takeoff_ref_point=[1, 2])))
        self.assertIn("takeoff_ref_point", self.error(body(takeoff_ref_point="here")))

    # -- export -------------------------------------------------------------------------------------------------------

    def test_the_export_is_a_kmz_of_the_same_mission(self):
        res = self.post("export", body(name="Field 12", direction=181, height=100.5, speed=8))
        self.assertEqual(res.status_code, 200, res.content[:200])
        self.assertEqual(res["Content-Type"], "application/vnd.google-earth.kmz")
        self.assertEqual(res["Content-Disposition"], 'attachment; filename="Field_12.kmz"')

        z = zipfile.ZipFile(io.BytesIO(res.content))
        self.assertEqual(sorted(z.namelist()), ["wpmz/template.kml", "wpmz/waylines.wpml"])
        back = parse_kmz(res.content)
        self.assertEqual((back["direction"], back["height"]), (181, 100.5))
        self.assertEqual([c.key for c in back["cameras"]], ["visable", "ir"])
        plan = self.post("plan", body(direction=181, height=100.5, speed=8)).json()
        self.assertEqual(len(back["waypoints"]), plan["summary"]["waypoints"])
        for (x, y), f in zip(back["waypoints"], plan["waypoints"]["features"]):
            self.assertAlmostEqual(x, f["geometry"]["coordinates"][0], places=11)
            self.assertAlmostEqual(y, f["geometry"]["coordinates"][1], places=11)

    def test_the_file_name_is_made_safe(self):
        for name, expected in (("../../etc/passwd", "etc_passwd"), ("a b\"c;d", "a_b_c_d"), ("", "luxodm-mission"), ("///", "luxodm-mission"),
                               ("x" * 200, "x" * 60), ("café", "caf")):
            res = self.post("export", body(name=name))
            self.assertEqual(res["Content-Disposition"], 'attachment; filename="%s.kmz"' % expected, name)

    def test_the_export_says_what_to_check_in_a_header(self):
        res = self.post("export", body(height_mode="relativeToStartPoint"))
        self.assertIn("terrain", res["X-Mission-Warnings"])
        self.assertEqual(self.post("export", body(rth_height=150))["X-Mission-Warnings"], "")

    def test_the_export_refuses_what_the_plan_refuses(self):
        for bad in (body(polygon=[[1, 2], [3, 4]]), body(cameras=["ir"]), body(height=1)):
            res = self.post("export", bad)
            self.assertEqual(res.status_code, 400)
            self.assertIn("error", res.json())

    # -- the page -------------------------------------------------------------------------------------------------------

    def test_the_page_loads_its_libraries_and_knows_the_api(self):
        res = self.client.get(route_url(self.route))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertTrue('data-api="/api/plugins/mission_planner/"' in html)
        # MapLibre 6 through the module that makes it a global; the scripts after it deferred, to run after it in order
        self.assertIn('<script type="module" src="/plugins/mission_planner/maplibre.mjs"></script>', html)
        for script in ("node_modules/terra-draw/dist/terra-draw.umd.js",
                       "node_modules/terra-draw-maplibre-gl-adapter/dist/terra-draw-maplibre-gl-adapter.umd.js", "planner_core.js", "layers_panel.js", "search_panel.js", "route_form.js", "planner.js"):
            self.assertIn('<script defer src="/plugins/mission_planner/' + script + '"></script>', html)
        # the libraries come before the scripts that use them
        self.assertLess(html.index("maplibre.mjs"), html.index("planner_core.js"))
        self.assertLess(html.index("terra-draw.umd.js"), html.index("planner.js"))
        self.assertLess(html.index("terra-draw-maplibre-gl-adapter.umd.js"), html.index("planner.js"))
        self.assertLess(html.index("search_panel.js"), html.index("planner.js"))
        self.assertTrue("csrfmiddlewaretoken" in html)

    def test_the_page_has_every_element_the_scripts_read(self):
        html = self.client.get(route_url(self.route)).content.decode()
        root = PUBLIC
        planner = open(root + "planner.js").read()
        route_form = open(root + "route_form.js").read()

        ids = set(re.findall(r'getElementById\("([^"]+)"\)', planner)) | set(re.findall(r'\bel\("([^"]+)"\)', route_form))
        ids |= set(re.findall(r'\{id: "([^"]+)"', route_form))          # the form's fields
        self.assertGreater(len(ids), 40)
        missing = sorted(i for i in ids if 'id="%s"' % i not in html and i not in LINEAR_ONLY_IDS + SLOPE_ONLY_IDS + GEOMETRIC_ONLY_IDS)
        self.assertEqual(missing, [])
        for i in LINEAR_ONLY_IDS + SLOPE_ONLY_IDS + GEOMETRIC_ONLY_IDS:
            self.assertNotIn('id="%s"' % i, html)

        # the segmented buttons name fields and values the form knows
        fields = set(re.findall(r"^\s+(\w+): \{id:", route_form, re.M)) | set(re.findall(r", (\w+): \{id:", route_form))
        for field, value in re.findall(r'data-seg="(\w+)" data-value="(\w+)"', html):
            self.assertIn(field, fields)
        # Pointer first, left of Polygon
        self.assertEqual(re.findall(r'data-tool="([a-z]+)"', html), ["pointer", "polygon", "rectangle", "select", "clear"])
        self.assertLess(html.index("measure.js"), html.index("/planner.js"))

    def test_the_form_starts_with_the_defaults_of_the_core(self):
        # what the page shows before the script runs must not disagree with what the script writes
        html = self.client.get(route_url(self.route)).content.decode()
        self.assertTrue('id="mp-altitude-mode" name="altitude_mode" value="agl"' in html)
        self.assertTrue('id="mp-takeoff-mode" name="takeoff_mode" value="safe"' in html)
        self.assertEqual(re.search(r'id="mp-lens-visible"[^>]*checked', html) is not None, True)

    def test_the_options_that_cannot_be_exported_yet_are_disabled_in_the_form(self):
        html = self.client.get(route_url(self.route)).content.decode()
        self.assertTrue('<option value="time" disabled>' in html)

    def test_asl_is_available_and_needs_the_takeoff_elevation_fetched(self):
        html = self.client.get(route_url(self.route)).content.decode()
        self.assertIn('data-seg="altitude_mode" data-value="asl"', html)
        self.assertNotIn('data-seg="altitude_mode" data-value="asl" disabled', html)
        self.assertIn('id="mp-fetch-elevation"', html)
        self.assertIn('id="mp-takeoff-ellipsoidal-height" name="takeoff_ellipsoidal_height"', html)
        self.assertIn('id="mp-elevation-dialog" hidden', html)

    def test_oblique_collection_is_available_and_its_fields_start_hidden(self):
        html = self.client.get(route_url(self.route)).content.decode()
        self.assertIn('data-seg="collection_mode" data-value="oblique"', html)
        self.assertNotIn('data-seg="collection_mode" data-value="oblique" disabled', html)
        self.assertIn('id="mp-oblique-fields" hidden', html)
        self.assertIn('id="mp-gimbal-pitch"', html)
        self.assertIn('id="mp-inclined-speed-toggle"', html)
        self.assertIn('id="mp-inclined-speed" name="inclined_speed" placeholder="as fast as the oblique photos allow" disabled', html)

    def test_the_menu_entry_is_in_the_main_menu(self):
        html = self.client.get("/dashboard/").content.decode()
        menu = html[html.index('id="side-menu"'):html.index('id="about-menu"')]
        self.assertIn("DJI Mission Planner", menu)
        self.assertIn("/plugins/mission_planner/", menu)


class TestPlannerBasemaps(BootTestCase):
    """The planner shows the same layers as the map of the tasks: the project's basemaps (Administration > Basemaps)"""

    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.route = routes.create(owner=User.objects.get(username="testuser"), name="Test route", route_type="area")

    def tearDown(self):
        disable_plugin("mission_planner")

    def page_basemaps(self):
        html = self.client.get(route_url(self.route)).content.decode()
        found = re.search(r'<script id="mp-basemaps" type="application/json">(.*?)</script>', html, re.S)
        self.assertTrue(found)
        return json.loads(found.group(1)), html

    def test_the_page_offers_the_projects_basemaps(self):
        from app.models import Basemap
        basemaps, html = self.page_basemaps()
        self.assertEqual(basemaps, Basemap.get_cached_basemaps())
        labels = [b["label"] for b in basemaps]
        for label in ("Google Maps Hybrid", "ESRI Satellite", "OpenStreetMap"):      # WebODM's own (migration 0051)
            self.assertIn(label, labels)
        self.assertEqual(basemaps[0]["label"], "Google Maps Hybrid")             # the default comes first

    def test_a_basemap_added_by_an_administrator_shows_up(self):
        from app.models import Basemap
        Basemap.objects.create(type="tms", url="//tiles.example.org/{z}/{x}/{y}.png", label="Our own tiles", maxzoom=19, minzoom=0)
        basemaps, _ = self.page_basemaps()
        self.assertIn("Our own tiles", [b["label"] for b in basemaps])

    def test_the_basemap_json_cannot_break_out_of_the_page(self):
        from app.models import Basemap
        Basemap.objects.create(type="tms", url="//t/{z}/{x}/{y}.png", label="</script><script>alert(1)</script>", maxzoom=19, minzoom=0)
        html = self.client.get("/plugins/mission_planner/").content.decode()
        self.assertFalse("</script><script>alert(1)" in html)
        basemaps, _ = self.page_basemaps()
        self.assertIn("</script><script>alert(1)</script>", [b["label"] for b in basemaps])

    def test_the_layers_button_is_made_by_a_script_that_loads_before_the_planner(self):
        _, html = self.page_basemaps()
        self.assertTrue("/plugins/mission_planner/layers_panel.js" in html)
        self.assertLess(html.index("layers_panel.js"), html.index("planner.js"))
        # the layers are on the map, not in the side panel
        self.assertFalse('id="mp-basemap"' in html)
        # drawing and editing work in 3D too: no note sends the user back to 2D
        self.assertFalse('id="mp-view-note"' in html)


class TestRoutesListPage(BootTestCase):
    """The plugin's '$' mount: a list of the user's own routes plus a New Route dropdown, not the planner directly."""

    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")

    def tearDown(self):
        disable_plugin("mission_planner")

    def test_anonymous_users_are_redirected_to_login(self):
        res = Client().get("/plugins/mission_planner/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login/", res["Location"])

    def test_the_page_offers_a_new_route_button_with_every_type(self):
        html = self.client.get("/plugins/mission_planner/").content.decode()
        for label in ("Area Route", "Linear Route", "Waypoint Route", "Slope Route", "Geometric Route"):
            self.assertIn(label, html)
        self.assertIn('id="mp-new-area"', html)
        self.assertIn('id="mp-new-linear"', html)
        self.assertIn('id="mp-new-waypoint"', html)
        self.assertIn('id="mp-new-slope"', html)
        self.assertIn('id="mp-new-geometric"', html)
        # every route type is built
        self.assertNotIn('class="disabled"', html)

    def test_the_new_route_dropdown_offers_importing_a_kmz_or_kml_file(self):
        html = self.client.get("/plugins/mission_planner/").content.decode()
        self.assertIn('id="mp-import-kmz"', html)
        self.assertIn("Import KMZ or KML file…", html)
        self.assertIn('<input type="file" id="mp-import-file" accept=".kmz,.kml" hidden>', html)
        self.assertIn('id="mp-import-dialog"', html)

    def test_the_new_route_dropdown_offers_the_aircraft_models(self):
        html = self.client.get("/plugins/mission_planner/").content.decode()
        self.assertIn('id="mp-new-model"', html)
        self.assertIn('<label for="mp-new-model">Select Model:</label>', html)
        self.assertIn('<option value="m4t">DJI Matrice 4T</option>', html)
        self.assertIn('<option value="m4e">DJI Matrice 4E</option>', html)
        # M4T is the first (and so default-selected) option
        self.assertLess(html.index('value="m4t"'), html.index('value="m4e"'))
        # the copy dialog offers the same, and the page carries drones.json for its scripts
        self.assertEqual(html.count('<option value="m4e">DJI Matrice 4E</option>'), 2)
        self.assertIn('<script id="mp-drones" type="application/json">{"m4t": {"label": "DJI Matrice 4T"', html)

    def test_the_page_wires_up_the_api_the_list_is_fetched_from(self):
        # the list itself is populated client-side (routes_list.js fetches data-api + "routes"); which routes that
        # returns is covered by TestRouteApi, this just checks the page points the script at the right place.
        html = self.client.get("/plugins/mission_planner/").content.decode()
        self.assertIn('data-api="/api/plugins/mission_planner/"', html)
        self.assertIn('id="mp-routes-body"', html)

    def test_the_list_page_itself_is_not_the_area_route_editor(self):
        # a route id is required to reach the actual form/map
        html = self.client.get("/plugins/mission_planner/").content.decode()
        self.assertNotIn('id="mission_planner"', html)
        self.assertIn('id="mp-routes"', html)


class TestRouteEditor(BootTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")

    def tearDown(self):
        disable_plugin("mission_planner")

    def test_a_nonexistent_route_404s(self):
        self.assertEqual(self.client.get("/plugins/mission_planner/route/999999").status_code, 404)

    def test_someone_elses_route_404s(self):
        theirs = routes.create(owner=User.objects.get(username="testuser2"), name="Not yours", route_type="area")
        self.assertEqual(self.client.get(route_url(theirs)).status_code, 404)

    def test_anonymous_users_are_redirected_to_login(self):
        mine = routes.create(owner=User.objects.get(username="testuser"), name="Mine", route_type="area")
        res = Client().get(route_url(mine))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login/", res["Location"])

    def test_the_aircraft_model_is_shown_at_the_top_of_the_panel(self):
        m4t = routes.create(owner=User.objects.get(username="testuser"), name="M4T route", route_type="area")
        m4e = routes.create(owner=User.objects.get(username="testuser"), name="M4E route", route_type="area", model="m4e")
        self.assertEqual(m4t.model, "m4t")  # the default, unset by this test

        html = self.client.get(route_url(m4t)).content.decode()
        self.assertIn('<div class="mp-model-badge" id="mp-model-badge">DJI Matrice 4T</div>', html)
        self.assertIn('<label class="mp-chip"><input type="checkbox" id="mp-lens-ir"', html)
        self.assertIn('Matrice 4T. With both', html)
        self.assertIn('<script id="mp-drones" type="application/json">', html)

        html = self.client.get(route_url(m4e)).content.decode()
        self.assertIn('<div class="mp-model-badge" id="mp-model-badge">DJI Matrice 4E</div>', html)
        self.assertNotIn("mp-model-warning", html)  # the M4E is planned with its own camera now
        self.assertIn('<script id="mp-route-model" type="application/json">"m4e"</script>', html)
        # the M4E has no thermal camera: its IR chip and IR ground sample distance are hidden
        self.assertIn('<label class="mp-chip" hidden><input type="checkbox" id="mp-lens-ir"', html)
        self.assertIn('<div class="form-group" hidden><label for="mp-gsd-ir">', html)
        self.assertIn("Matrice 4E: the wide camera only.", html)

    def test_a_waypoint_route_opens_the_waypoint_editor(self):
        route = routes.create(owner=User.objects.get(username="testuser"), name="Points", route_type="waypoint")
        html = self.client.get(route_url(route)).content.decode()
        self.assertIn("waypoint_planner.js", html)
        self.assertNotIn("terra-draw", html)
        self.assertIn('<script type="module" src="/plugins/mission_planner/maplibre.mjs"></script>', html)
        for script in ("maplibre.mjs", "planner_core.js", "layers_panel.js", "search_panel.js", "waypoint_form.js"):
            self.assertLess(html.index(script), html.index("waypoint_planner.js"), script)
        for script in ("planner_core.js", "layers_panel.js", "search_panel.js", "waypoint_form.js", "waypoint_planner.js"):
            self.assertIn('<script defer src="/plugins/mission_planner/' + script + '"></script>', html)
        self.assertIn('<script id="mp-route-model" type="application/json">"m4t"</script>', html)

    def test_the_waypoint_editor_opens_in_pointer_with_add_points_beside_it(self):
        route = routes.create(owner=User.objects.get(username="testuser"), name="Points", route_type="waypoint")
        html = self.client.get(route_url(route)).content.decode()
        self.assertEqual(re.findall(r'data-tool="([a-z]+)"', html), ["pointer", "add"])
        self.assertIn('class="btn btn-default active" data-tool="pointer"', html)
        self.assertIn('<script defer src="/plugins/mission_planner/measure.js"></script>', html)
        self.assertLess(html.index("measure.js"), html.index("waypoint_planner.js"))

    def test_the_waypoint_editor_has_every_element_its_scripts_read(self):
        # a POI route, so that the shape section (which a plain waypoint route leaves out) is on the page too
        route = routes.create(owner=User.objects.get(username="testuser"), name="Points", route_type="waypoint",
                                     settings={"shape": {"kind": "circle"}})
        html = self.client.get(route_url(route)).content.decode()
        root = PUBLIC
        page = open(root + "waypoint_planner.js").read()
        form = open(root + "waypoint_form.js").read()
        form_test = open(root + "__tests__/waypoint_form.test.js").read()

        ids = set(re.findall(r'getElementById\("([^"]+)"\)', page)) | set(re.findall(r'\bel\("([^"]+)"\)', form))
        ids |= set(re.findall(r'\{id: "([^"]+)"', form))               # the forms' fields and the labels
        ids |= set(re.findall(r'id="(mp-[^"]+)"', form_test))           # the fixture the form is tested on
        self.assertGreater(len(ids), 50)
        missing = sorted(i for i in ids if 'id="%s"' % i not in html)
        self.assertEqual(missing, [])

        # the segmented buttons name fields and values the form knows
        fields = set(re.findall(r"(\w+): \{id:", form))
        for field, value in re.findall(r'data-seg="(\w+)" data-value="(\w+)"', html):
            self.assertIn(field, fields)
        shape_fields = set(re.findall(r'(\w+): \{id: "mp-shape-', form))
        for field in re.findall(r'data-shape-seg="(\w+)"', html):
            self.assertIn(field, shape_fields)

    def test_a_plain_waypoint_route_has_no_shape_section(self):
        route = routes.create(owner=User.objects.get(username="testuser"), name="Points", route_type="waypoint")
        html = self.client.get(route_url(route)).content.decode()
        self.assertIn("<h3>Waypoint route</h3>", html)
        self.assertNotIn('id="mp-shape-section"', html)

    def test_an_area_route_still_opens_the_area_editor(self):
        route = routes.create(owner=User.objects.get(username="testuser"), name="Area", route_type="area")
        html = self.client.get(route_url(route)).content.decode()
        self.assertIn("/planner.js", html)
        self.assertNotIn("waypoint_planner.js", html)
        self.assertIn("<h3>Area route</h3>", html)
        self.assertIn('data-route-type="area"', html)

    def test_a_linear_route_opens_the_area_editor_with_a_line_to_draw_and_the_strip_to_set(self):
        route = routes.create(owner=User.objects.get(username="testuser"), name="Line", route_type="linear")
        html = self.client.get(route_url(route)).content.decode()
        self.assertIn("/planner.js", html)
        self.assertIn("<h3>Linear route</h3>", html)
        self.assertIn('data-route-type="linear"', html)
        self.assertEqual(sorted(set(re.findall(r'data-tool="([a-z]+)"', html))), ["clear", "line", "pointer", "select"])
        self.assertEqual(re.findall(r'data-tool="([a-z]+)"', html)[:2], ["pointer", "line"])
        for i in LINEAR_ONLY_IDS:
            self.assertIn('id="%s"' % i, html)
        # an area's course, margin, photo mode, collection and start point do not apply to a line
        for i in AREA_ONLY_IDS:
            self.assertNotIn('id="%s"' % i, html)

        # every other element the scripts read is there
        root = PUBLIC
        planner, route_form = open(root + "planner.js").read(), open(root + "route_form.js").read()
        ids = set(re.findall(r'getElementById\("([^"]+)"\)', planner)) | set(re.findall(r'\bel\("([^"]+)"\)', route_form))
        ids |= set(re.findall(r'\{id: "([^"]+)"', route_form))
        missing = sorted(i for i in ids if 'id="%s"' % i not in html and i not in AREA_ONLY_IDS + SLOPE_ONLY_IDS + GEOMETRIC_ONLY_IDS)
        self.assertEqual(missing, [])

    def test_a_slope_route_opens_the_area_editor_with_its_corners_heights_and_side_view(self):
        route = routes.create(owner=User.objects.get(username="testuser"), name="Dam", route_type="slope")
        html = self.client.get(route_url(route)).content.decode()
        self.assertIn("/planner.js", html)
        self.assertIn("<h3>Slope route</h3>", html)
        self.assertIn('data-route-type="slope"', html)
        self.assertEqual(sorted(set(re.findall(r'data-tool="([a-z]+)"', html))), ["clear", "pointer", "polygon", "rectangle", "select"])
        self.assertIn("Distance from the face (m)", html)
        for i in SLOPE_ONLY_IDS:
            self.assertIn('id="%s"' % i, html)
        for i in AREA_ONLY_IDS + LINEAR_ONLY_IDS + HEIGHT_MODE_IDS + GEOMETRIC_ONLY_IDS:
            self.assertNotIn('id="%s"' % i, html)

        root = PUBLIC
        planner, route_form = open(root + "planner.js").read(), open(root + "route_form.js").read()
        ids = set(re.findall(r'getElementById\("([^"]+)"\)', planner)) | set(re.findall(r'\bel\("([^"]+)"\)', route_form))
        ids |= set(re.findall(r'\{id: "([^"]+)"', route_form))
        missing = sorted(i for i in ids if 'id="%s"' % i not in html
                         and i not in AREA_ONLY_IDS + LINEAR_ONLY_IDS + HEIGHT_MODE_IDS + GEOMETRIC_ONLY_IDS)
        self.assertEqual(missing, [])

    def test_a_geometric_route_opens_the_area_editor_with_its_block_heights_and_side_view(self):
        route = routes.create(owner=User.objects.get(username="testuser"), name="Barn", route_type="geometric")
        html = self.client.get(route_url(route)).content.decode()
        self.assertIn("<h3>Geometric route</h3>", html)
        self.assertIn('data-route-type="geometric"', html)
        self.assertEqual(sorted(set(re.findall(r'data-tool="([a-z]+)"', html))), ["clear", "pointer", "polygon", "rectangle", "select"])
        self.assertIn("Distance from the walls (m)", html)
        for i in GEOMETRIC_ONLY_IDS + SIDE_VIEW_IDS:
            self.assertIn('id="%s"' % i, html)
        slope_own = tuple(i for i in SLOPE_ONLY_IDS if i not in SIDE_VIEW_IDS)
        for i in AREA_ONLY_IDS + LINEAR_ONLY_IDS + HEIGHT_MODE_IDS + slope_own:
            self.assertNotIn('id="%s"' % i, html)

        root = PUBLIC
        planner, route_form = open(root + "planner.js").read(), open(root + "route_form.js").read()
        ids = set(re.findall(r'getElementById\("([^"]+)"\)', planner)) | set(re.findall(r'\bel\("([^"]+)"\)', route_form))
        ids |= set(re.findall(r'\{id: "([^"]+)"', route_form))
        missing = sorted(i for i in ids if 'id="%s"' % i not in html
                         and i not in AREA_ONLY_IDS + LINEAR_ONLY_IDS + HEIGHT_MODE_IDS + slope_own)
        self.assertEqual(missing, [])


class TestRouteApi(BootTestCase):
    """CRUD for saved routes: api.py's RouteListCreateView/RouteDetailView."""

    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.user = User.objects.get(username="testuser")
        self.other = User.objects.get(username="testuser2")

    def tearDown(self):
        disable_plugin("mission_planner")

    def test_anonymous_cannot_list_or_create(self):
        c = Client()
        self.assertIn(c.get(API + "routes").status_code, (401, 403))
        self.assertIn(c.post(API + "routes", "{}", content_type="application/json").status_code, (401, 403))

    def test_the_list_starts_empty_and_is_filtered_to_the_owner(self):
        self.assertEqual(self.client.get(API + "routes").json(), [])
        routes.create(owner=self.other, name="Not mine", route_type="area")
        self.assertEqual(self.client.get(API + "routes").json(), [])
        mine = routes.create(owner=self.user, name="Mine", route_type="area")
        listed = self.client.get(API + "routes").json()
        self.assertEqual([r["id"] for r in listed], [mine.id])
        self.assertEqual(listed[0]["name"], "Mine")
        self.assertEqual(listed[0]["route_type"], "area")

    def test_creating_a_route(self):
        res = self.client.post(API + "routes", json.dumps({"name": "New survey", "route_type": "area"}), content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content[:200])
        data = res.json()
        self.assertEqual(data["name"], "New survey")
        self.assertEqual(data["route_type"], "area")
        self.assertEqual(data["model"], "m4t")  # the default when not given
        self.assertEqual(data["settings"], {})
        route = routes.get(data["id"])
        self.assertEqual(route.owner, self.user)

    def test_create_rejects_route_types_the_planner_does_not_have(self):
        for route_type in ("patrol", ""):
            res = self.client.post(API + "routes", json.dumps({"name": "x", "route_type": route_type}), content_type="application/json")
            self.assertEqual(res.status_code, 400, route_type)
        self.assertEqual(routes.count(), 0)

    def test_create_accepts_either_supported_aircraft(self):
        for model in ("m4t", "m4e"):
            res = self.client.post(API + "routes", json.dumps({"name": "x " + model, "route_type": "area", "model": model}),
                                    content_type="application/json")
            self.assertEqual(res.status_code, 201, res.content[:200])
            self.assertEqual(res.json()["model"], model)

    def test_create_rejects_an_unknown_aircraft(self):
        res = self.client.post(API + "routes", json.dumps({"name": "x", "route_type": "area", "model": "m5t"}), content_type="application/json")
        self.assertEqual(res.status_code, 400, res.content[:200])
        self.assertEqual(routes.count(), 0)

    def test_create_ignores_a_client_supplied_owner(self):
        res = self.client.post(API + "routes", json.dumps({"name": "x", "route_type": "area", "owner": self.other.id}),
                                content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content[:200])
        route = routes.get(res.json()["id"])
        self.assertEqual(route.owner, self.user)

    def test_patch_updates_name_and_settings(self):
        route = routes.create(owner=self.user, name="Old name", route_type="area")
        res = self.client.patch(API + "routes/%d" % route.id, json.dumps({"name": "New name", "settings": body()}), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content[:200])
        route.refresh_from_db()
        self.assertEqual(route.name, "New name")
        self.assertEqual(route.settings, body())

    def test_patch_persists_the_drawn_area_and_picked_points(self):
        # settings is an unvalidated JSONField - this locks in that the polygon/takeoff/route_start planner.js now
        # saves (previously only the form fields were persisted, so a reload lost the drawn area) round-trip intact.
        route = routes.create(owner=self.user, name="Mine", route_type="area")
        settings = {"height": "50", "polygon": [[-85.020728, 42.103], [-85.019928, 42.103], [-85.019928, 42.1036]],
                    "takeoff": [42.103, -85.020728], "route_start": [-85.020228, 42.1032]}
        res = self.client.patch(API + "routes/%d" % route.id, json.dumps({"settings": settings}), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content[:200])
        route.refresh_from_db()
        self.assertEqual(route.settings, settings)
        self.assertEqual(self.client.get(API + "routes/%d" % route.id).json()["settings"], settings)

    def test_patch_cannot_change_the_aircraft_model(self):
        route = routes.create(owner=self.user, name="Mine", route_type="area", model="m4t")
        res = self.client.patch(API + "routes/%d" % route.id, json.dumps({"model": "m4e"}), content_type="application/json")
        self.assertEqual(res.status_code, 400, res.content[:200])
        route.refresh_from_db()
        self.assertEqual(route.model, "m4t")  # unchanged - start a new route to plan for a different aircraft

    def test_patch_cannot_change_the_route_type(self):
        route = routes.create(owner=self.user, name="Mine", route_type="waypoint", settings={"points": [{"lat": 1, "lon": 2}]})
        res = self.client.patch(API + "routes/%d" % route.id, json.dumps({"route_type": "area"}), content_type="application/json")
        self.assertEqual(res.status_code, 400, res.content[:200])
        route.refresh_from_db()
        self.assertEqual(route.route_type, "waypoint")

    def test_put_leaves_the_fields_it_does_not_send_as_they_are(self):
        settings = {"points": [{"lat": 1, "lon": 2}], "height": "40"}
        route = routes.create(owner=self.user, name="Mine", route_type="waypoint", model="m4e", settings=settings)
        res = self.client.put(API + "routes/%d" % route.id, json.dumps({"name": "Renamed"}), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content[:200])
        route.refresh_from_db()
        self.assertEqual((route.name, route.route_type, route.model, route.settings), ("Renamed", "waypoint", "m4e", settings))

    def test_patch_is_unaffected_when_the_model_is_sent_back_unchanged(self):
        route = routes.create(owner=self.user, name="Mine", route_type="area", model="m4e")
        res = self.client.patch(API + "routes/%d" % route.id, json.dumps({"name": "Renamed", "model": "m4e"}), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content[:200])
        route.refresh_from_db()
        self.assertEqual(route.name, "Renamed")
        self.assertEqual(route.model, "m4e")

    def test_someone_elses_route_404s_not_403s(self):
        theirs = routes.create(owner=self.other, name="Not yours", route_type="area")
        self.assertEqual(self.client.get(API + "routes/%d" % theirs.id).status_code, 404)
        self.assertEqual(self.client.patch(API + "routes/%d" % theirs.id, json.dumps({"name": "x"}), content_type="application/json").status_code, 404)
        self.assertEqual(self.client.delete(API + "routes/%d" % theirs.id).status_code, 404)
        self.assertEqual(routes.get(theirs.id).name, "Not yours")  # untouched

    def test_delete_removes_the_route(self):
        route = routes.create(owner=self.user, name="Temp", route_type="area")
        res = self.client.delete(API + "routes/%d" % route.id)
        self.assertEqual(res.status_code, 204, res.content[:200])
        self.assertIsNone(routes.get(route.id))

    def test_copy_with_the_same_model_keeps_everything(self):
        settings = {"height": "50", "lens_visible": "false", "lens_ir": "true", "direction": "45"}
        route = routes.create(owner=self.user, name="Original", route_type="area", model="m4t", settings=settings)
        res = self.client.post(API + "routes/%d/copy" % route.id, json.dumps({"model": "m4t"}), content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content[:200])
        data = res.json()
        self.assertEqual(data["settings"], settings)
        self.assertEqual(data["model"], "m4t")
        self.assertEqual(data["route_type"], "area")
        self.assertIn("copy", data["name"].lower())
        self.assertNotEqual(data["id"], route.id)
        self.assertEqual(routes.get(data["id"]).owner, self.user)
        route.refresh_from_db()
        self.assertEqual(route.settings, settings)  # the original is untouched

    def test_copy_defaults_to_the_same_model_when_none_is_given(self):
        route = routes.create(owner=self.user, name="Original", route_type="area", model="m4e", settings={"height": "50"})
        res = self.client.post(API + "routes/%d/copy" % route.id, "{}", content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content[:200])
        self.assertEqual(res.json()["model"], "m4e")
        self.assertEqual(res.json()["settings"], {"height": "50"})

    def copy(self, settings, source_model, model):
        route = routes.create(owner=self.user, name="Original", route_type="area", model=source_model, settings=settings)
        res = self.client.post(API + "routes/%d/copy" % route.id, json.dumps({"model": model}), content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content[:200])
        self.assertEqual(res.json()["model"], model)
        return res.json()["settings"]

    def test_a_copy_to_the_m4e_flies_higher_to_keep_the_ground_sample_distance(self):
        settings = {"height": "50", "direction": "45", "lens_visible": "true", "lens_ir": "true", "speed": "1.79"}
        copied = self.copy(settings, "m4t", "m4e")
        self.assertEqual(copied, {"height": "66.6", "direction": "45", "lens_visible": "true", "lens_ir": "false", "speed": "1.79"})
        # both give 1.79 cm visible pixels
        self.assertAlmostEqual(ground_sample_distance(M4T_WIDE, 50) * 100, 1.79, delta=0.005)
        self.assertAlmostEqual(ground_sample_distance(M4E_WIDE, 66.6) * 100, 1.79, delta=0.005)

    def test_a_copy_to_the_m4t_flies_lower_with_the_thermal_camera_offered_but_off(self):
        copied = self.copy({"height": "80", "lens_visible": "true"}, "m4e", "m4t")
        self.assertEqual(copied, {"height": "60.06", "lens_visible": "true", "lens_ir": "false"})

    def test_a_thermal_only_route_keeps_its_height_and_takes_visible_photos_on_the_m4e(self):
        copied = self.copy({"height": "40", "lens_visible": "false", "lens_ir": "true"}, "m4t", "m4e")
        self.assertEqual(copied, {"height": "40", "lens_visible": "true", "lens_ir": "false"})

    def test_an_oblique_area_copied_for_a_dji_fly_drone_becomes_ortho(self):
        self.assertEqual(self.copy({"height": "50", "collection_mode": "oblique"}, "m4t", "air3")["collection_mode"], "ortho")
        self.assertEqual(self.copy({"height": "50", "collection_mode": "oblique"}, "m4t", "m4e")["collection_mode"], "oblique")

    def test_a_poi_route_cannot_be_copied_for_a_dji_fly_drone(self):
        route = routes.create(owner=self.user, name="Original", route_type="waypoint", model="m4t", settings={"shape": {"radius": 20}})
        res = self.client.post(API + "routes/%d/copy" % route.id, json.dumps({"model": "mini4pro"}), content_type="application/json")
        self.assertEqual(res.status_code, 400, res.content[:200])
        self.assertIn("point of interest", json.dumps(res.json()))

    def test_a_copy_stays_within_the_height_limits(self):
        self.assertEqual(self.copy({"height": "450"}, "m4t", "m4e")["height"], "500")
        self.assertEqual(self.copy({"height": "2"}, "m4e", "m4t")["height"], "2")

    def test_a_copy_of_a_route_without_a_height_keeps_the_default_ground_sample_distance(self):
        self.assertEqual(self.copy({}, "m4t", "m4e")["height"], "66.6")  # from 50 m

    def test_copy_rejects_an_unknown_model(self):
        route = routes.create(owner=self.user, name="Original", route_type="area")
        res = self.client.post(API + "routes/%d/copy" % route.id, json.dumps({"model": "m5t"}), content_type="application/json")
        self.assertEqual(res.status_code, 400, res.content[:200])
        self.assertEqual(routes.count(), 1)  # no copy was created

    def test_copy_someone_elses_route_404s(self):
        theirs = routes.create(owner=self.other, name="Not yours", route_type="area")
        res = self.client.post(API + "routes/%d/copy" % theirs.id, "{}", content_type="application/json")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(routes.count(), 1)

    def test_anonymous_cannot_copy(self):
        route = routes.create(owner=self.user, name="Mine", route_type="area")
        res = Client().post(API + "routes/%d/copy" % route.id, "{}", content_type="application/json")
        self.assertIn(res.status_code, (401, 403))


class TestRouteElevationApi(BootTestCase):
    """The takeoff-point elevation lookup for the ASL height mode: api.py's
    RouteElevationView. missions.elevation.fetch_ground_elevation is mocked throughout - no real network
    calls (see tests/test_mission_elevation.py for that function's own tests)."""

    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.user = User.objects.get(username="testuser")
        self.other = User.objects.get(username="testuser2")
        self.route = routes.create(owner=self.user, name="Mine", route_type="area")

    def tearDown(self):
        disable_plugin("mission_planner")

    def url(self, route=None):
        return API + "routes/%d/elevation" % (route or self.route).id

    def test_get_with_no_cache_yet_404s(self):
        res = self.client.get(self.url())
        self.assertEqual(res.status_code, 404)

    def test_post_fetches_and_caches_the_elevation(self):
        with mock.patch.object(mission_planner_api, "fetch_ground_elevation",
                        return_value={"orthometric": 244.0, "ellipsoidal": 209.8}) as fetch:
            res = self.client.post(self.url(), json.dumps({"lat": 42.103447, "lon": -85.020518}), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content[:200])
        data = res.json()
        self.assertEqual(data["orthometric"], 244.0)
        self.assertEqual(data["ellipsoidal"], 209.8)
        self.assertEqual(data["lat"], 42.103447)
        self.assertEqual(data["lon"], -85.020518)
        self.assertIn("fetched_at", data)
        fetch.assert_called_once_with(42.103447, -85.020518)

        self.route.refresh_from_db()
        self.assertEqual(self.route.takeoff_elevation, data)
        # a later GET serves the cache without fetching again
        self.assertEqual(self.client.get(self.url()).json(), data)

    def test_a_save_of_the_settings_keeps_the_cached_elevation(self):
        with mock.patch.object(mission_planner_api, "fetch_ground_elevation",
                               return_value={"orthometric": 244.0, "ellipsoidal": 209.8}):
            cached = self.client.post(self.url(), json.dumps({"lat": 42.1, "lon": -88.1}), content_type="application/json").json()
        # the editor's Save sends its form and shape, never the cache
        res = self.client.patch(API + "routes/%d" % self.route.id, json.dumps({"settings": {"height": "60"}}),
                                content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content[:200])
        self.assertEqual(self.client.get(self.url()).json(), cached)

    def test_a_save_made_while_the_elevation_is_fetched_is_not_undone(self):
        def fetch_while_saving(lat, lon):
            route = routes.get(self.route.id)
            route.settings = {"height": "75", "polygon": [[1, 2], [3, 4], [5, 6]]}
            route.save(("settings",))
            return {"orthometric": 244.0, "ellipsoidal": 209.8}
        with mock.patch.object(mission_planner_api, "fetch_ground_elevation", side_effect=fetch_while_saving):
            res = self.client.post(self.url(), json.dumps({"lat": 42.1, "lon": -88.1}), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content[:200])
        self.route.refresh_from_db()
        self.assertEqual(self.route.settings, {"height": "75", "polygon": [[1, 2], [3, 4], [5, 6]]})
        self.assertEqual(self.route.takeoff_elevation["orthometric"], 244.0)

    def test_a_cache_kept_in_the_settings_before_is_still_served(self):
        old = {"lat": 42.1, "lon": -88.1, "orthometric": 244.0, "ellipsoidal": 209.8, "fetched_at": 1.0}
        self.route.settings = {"takeoff_elevation": old}
        self.route.save(("settings",))
        self.assertEqual(self.client.get(self.url()).json(), old)

    def test_post_failure_returns_a_structured_error_and_does_not_touch_an_existing_cache(self):
        with mock.patch.object(mission_planner_api, "fetch_ground_elevation",
                        return_value={"orthometric": 244.0, "ellipsoidal": 209.8}):
            self.client.post(self.url(), json.dumps({"lat": 42.1, "lon": -88.1}), content_type="application/json")
        cached_before = self.client.get(self.url()).json()

        with mock.patch.object(mission_planner_api, "fetch_ground_elevation",
                        side_effect=ElevationError("The elevation service returned an error (502)")) as fetch:
            res = self.client.post(self.url(), json.dumps({"lat": 42.1, "lon": -88.1}), content_type="application/json")
        self.assertEqual(res.status_code, 502, res.content[:200])
        self.assertIn("error", res.json())
        fetch.assert_called_once()

        # the earlier successful cache is still there, untouched
        self.assertEqual(self.client.get(self.url()).json(), cached_before)

    def test_anonymous_cannot_fetch_or_read(self):
        route = routes.create(owner=self.user, name="Mine", route_type="area")
        c = Client()
        self.assertIn(c.get(self.url(route)).status_code, (401, 403))
        self.assertIn(c.post(self.url(route), "{}", content_type="application/json").status_code, (401, 403))

    def test_someone_elses_route_404s(self):
        theirs = routes.create(owner=self.other, name="Not yours", route_type="area")
        self.assertEqual(self.client.get(self.url(theirs)).status_code, 404)
        res = self.client.post(self.url(theirs), json.dumps({"lat": 42.1, "lon": -88.1}), content_type="application/json")
        self.assertEqual(res.status_code, 404)

    def test_post_rejects_missing_or_bad_lat_lon(self):
        for bad in ({}, {"lat": 42.1}, {"lat": "x", "lon": -88.1}, {"lat": 999, "lon": -88.1}, {"lat": 42.1, "lon": 999}):
            res = self.client.post(self.url(), json.dumps(bad), content_type="application/json")
            self.assertEqual(res.status_code, 400, bad)


class TestAreaRouteApi(BootTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")

    def tearDown(self):
        disable_plugin("mission_planner")

    def post(self, path, data):
        return self.client.post(API + path, json.dumps(data), content_type="application/json")

    def plan(self, **over):
        res = self.post("plan", body(**over))
        self.assertEqual(res.status_code, 200, res.content[:300])
        return res.json()

    def error(self, **over):
        res = self.post("plan", body(**over))
        self.assertEqual(res.status_code, 400, res.content[:200])
        return res.json()["error"]

    def test_the_summary_has_the_area_and_what_is_needed_to_set_a_ground_sample_distance(self):
        s = self.plan()["summary"]
        self.assertAlmostEqual(s["area"], 2400, delta=6)
        # GSD of each camera per meter of height: 30 m gives 3 cm thermal pixels
        self.assertAlmostEqual(s["gsd_per_m"]["ir"] * 30, s["gsd"]["ir"], places=9)
        self.assertAlmostEqual(s["gsd_per_m"]["ir"], 0.001, places=9)
        self.assertEqual(sorted(s["gsd_per_m"]), ["ir", "visable"])
        # ... also for a camera that is not in the mission
        self.assertEqual(sorted(self.plan(cameras=["visable"])["summary"]["gsd_per_m"]), ["ir", "visable"])

    def test_an_m4e_route_is_planned_with_its_own_wide_camera(self):
        s = self.plan(model="m4e", cameras=["visable"])["summary"]
        self.assertEqual(sorted(s["gsd_per_m"]), ["visable"])
        self.assertAlmostEqual(s["gsd_per_m"]["visable"], 1 / 3725, places=9)
        no_cameras = body(model="m4e")
        del no_cameras["cameras"]
        res = self.post("plan", no_cameras)
        self.assertEqual(res.status_code, 200, res.content[:200])
        self.assertEqual(sorted(res.json()["summary"]["gsd"]), ["visable"])  # the model's default cameras

    def test_an_m4e_route_cannot_use_the_thermal_camera(self):
        self.assertIn("cameras must be a list of visable", self.error(model="m4e"))
        self.assertIn("model must be one of", self.error(model="m5t"))

    def test_the_m4e_export_names_the_m4e(self):
        res = self.post("export", body(model="m4e", cameras=["visable"]))
        self.assertEqual(res.status_code, 200, res.content[:200])
        t = ET.fromstring(zipfile.ZipFile(io.BytesIO(res.content)).read("wpmz/template.kml"))
        self.assertEqual(t.find("k:Document/w:missionConfig/w:droneInfo/w:droneSubEnumValue", NS).text, "0")
        self.assertEqual(t.find("k:Document/w:missionConfig/w:payloadInfo/w:payloadEnumValue", NS).text, "88")

    def test_the_height_for_a_ground_sample_distance_gives_that_distance(self):
        gsd_per_m = self.plan()["summary"]["gsd_per_m"]
        height = 0.05 / gsd_per_m["ir"]                    # 5 cm thermal pixels, as in FlightHub's 50 m example
        self.assertAlmostEqual(height, 50.0, places=6)
        s = self.plan(height=height)["summary"]
        self.assertAlmostEqual(s["gsd"]["ir"], 0.05, places=9)
        self.assertAlmostEqual(s["gsd"]["visable"] * 100, 1.79, delta=0.01)            # FlightHub: 1.78 cm/pixel

    def test_the_route_can_start_where_the_user_says(self):
        default = self.plan()
        area = rectangle(60, 40)
        starts = set()
        for corner in area:
            plan = self.plan(route_start=list(corner))
            starts.add(tuple(round(v, 6) for v in plan["waypoints"]["features"][0]["geometry"]["coordinates"]))
            self.assertEqual(plan["summary"]["lines"], default["summary"]["lines"])
            self.assertAlmostEqual(plan["summary"]["distance"], default["summary"]["distance"], delta=0.05)
        self.assertEqual(len(starts), 4)

    def test_the_new_options_are_passed_to_the_file(self):
        res = self.post("export", body(takeoff_mode="direct", elevation_optimize=False, avoid_limit_area=True, transitional_speed=12,
                                       route_start=list(rectangle(60, 40)[2])))
        self.assertEqual(res.status_code, 200, res.content[:200])
        z = zipfile.ZipFile(io.BytesIO(res.content))
        t = ET.fromstring(z.read("wpmz/template.kml"))
        self.assertEqual(t.find("k:Document/w:missionConfig/w:flyToWaylineMode", NS).text, "pointToPoint")
        self.assertEqual(t.find("k:Document/w:missionConfig/w:waylineAvoidLimitAreaMode", NS).text, "1")
        self.assertEqual(t.find("k:Document/w:missionConfig/w:globalTransitionalSpeed", NS).text, "12")
        self.assertEqual(t.find("k:Document/k:Folder/k:Placemark/w:elevationOptimizeEnable", NS).text, "0")
        w = ET.fromstring(z.read("wpmz/waylines.wpml"))
        self.assertEqual(w.find("k:Document/w:missionConfig/w:flyToWaylineMode", NS).text, "pointToPoint")
        first = w.find("k:Document/k:Folder/k:Placemark/k:Point/k:coordinates", NS).text.split(",")
        corner = rectangle(60, 40)[2]
        # the export starts where the plan says: nearest to the corner asked for
        self.assertLess(distance((float(first[0]), float(first[1])), corner), 12)

    def test_refuses_what_cannot_be_exported_or_is_not_valid(self):
        self.assertIn("seconds cannot be exported yet", self.error(photo_mode="time"))
        self.assertIn("Unknown photo mode", self.error(photo_mode="often"))
        self.assertIn("must be text", self.error(photo_mode=5))
        self.assertIn("takeoff mode", self.error(takeoff_mode="teleport"))
        self.assertIn("must be true or false", self.error(elevation_optimize="yes"))
        self.assertIn("must be true or false", self.error(avoid_limit_area=1))
        self.assertIn("route_start", self.error(route_start=[1]))
        self.assertIn("route_start", self.error(route_start="here"))
        self.assertIn("route_start", self.error(route_start=[500, 0]))
        self.assertIn("route_start", self.error(route_start=[True, 1]))
        self.assertIn("speed between the takeoff", self.error(transitional_speed=99))
        self.assertIn("transitional_speed must be a number", self.error(transitional_speed="fast"))

    def test_the_defaults_are_the_same_as_before(self):
        a = self.plan()
        b = self.plan(takeoff_mode="safe", elevation_optimize=True, avoid_limit_area=False, photo_mode="distance", route_start=None)
        self.assertEqual(a["summary"], b["summary"])
        self.assertEqual(a["lines"], b["lines"])


class TestObliqueApi(BootTestCase):
    """collection_mode="oblique" through the plan/export API - the mission itself (the 5-folder file) is checked
    thoroughly in test_mission_wpml.TestObliqueMission; this is the request/response plumbing around it."""

    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")

    def tearDown(self):
        disable_plugin("mission_planner")

    def post(self, path, data):
        return self.client.post(API + path, json.dumps(data), content_type="application/json")

    def oblique_body(self, **over):
        b = body(height_mode="relativeToStartPoint", collection_mode="oblique", gimbal_pitch=-45)
        b.update(over)
        return b

    def test_an_oblique_agl_plan_is_accepted(self):
        res = self.post("plan", body(height_mode="realTimeFollowSurface", collection_mode="oblique", gimbal_pitch=-45))
        self.assertEqual(res.status_code, 200, res.content[:200])
        self.assertTrue(any("public elevation data" in w for w in res.json()["warnings"]))

    def test_oblique_needs_a_gimbal_pitch_in_range(self):
        res = self.post("plan", self.oblique_body(gimbal_pitch=None))
        self.assertEqual(res.status_code, 400, res.content[:200])
        res = self.post("plan", self.oblique_body(gimbal_pitch=-10))
        self.assertEqual(res.status_code, 400, res.content[:200])
        self.assertIn("gimbal tilt angle", res.json()["error"])

    def test_the_plan_summary_has_an_oblique_section(self):
        res = self.post("plan", self.oblique_body())
        self.assertEqual(res.status_code, 200, res.content[:300])
        summary = res.json()["summary"]
        self.assertIn("oblique", summary)
        self.assertGreater(summary["oblique"]["spacing"], summary["spacing"])  # the tilted footprint is bigger
        self.assertGreater(summary["oblique"]["photos"], 0)

    def test_an_ortho_plan_has_no_oblique_section(self):
        summary = self.post("plan", body()).json()["summary"]
        self.assertNotIn("oblique", summary)

    def test_the_geojson_includes_every_pass(self):
        data = self.post("plan", self.oblique_body()).json()
        names = {f["properties"]["pass"] for f in data["waypoints"]["features"]}
        self.assertEqual(names, {"nadir", "0.0", "90.0", "180.0", "270.0"})

    def test_the_export_is_a_kmz_with_five_folders(self):
        res = self.post("export", self.oblique_body())
        self.assertEqual(res.status_code, 200, res.content[:200])
        z = zipfile.ZipFile(io.BytesIO(res.content))
        w = ET.fromstring(z.read("wpmz/waylines.wpml"))
        self.assertEqual(len(w.findall("k:Document/k:Folder", NS)), 5)
        t = ET.fromstring(z.read("wpmz/template.kml"))
        self.assertEqual(t.find("k:Document/k:Folder/w:templateType", NS).text, "mapping3d")

    def test_inclined_overlap_and_speed_are_passed_through(self):
        res = self.post("export", self.oblique_body(inclined_overlap_h=50, inclined_overlap_w=40, inclined_speed=5.1))
        self.assertEqual(res.status_code, 200, res.content[:200])
        t = ET.fromstring(zipfile.ZipFile(io.BytesIO(res.content)).read("wpmz/template.kml"))
        overlap = t.find("k:Document/k:Folder/k:Placemark/w:overlap", NS)
        self.assertEqual(overlap.find("w:inclinedCameraOverlapH", NS).text, "50")
        self.assertEqual(overlap.find("w:inclinedCameraOverlapW", NS).text, "40")
        self.assertEqual(t.find("k:Document/k:Folder/k:Placemark/w:inclinedFlightSpeed", NS).text, "5.1")

    def test_oblique_settings_are_refused_for_an_ortho_plan(self):
        res = self.post("plan", body(gimbal_pitch=-45))
        self.assertEqual(res.status_code, 400, res.content[:200])
        self.assertIn("only apply", res.json()["error"])


def terrain_tif(ground=180.0, west=LON0 - 0.01, north=LAT0 + 0.01):
    """A flat 0.02 x 0.02 degree terrain around the test route, `ground` m high, as fetch_terrain returns it"""
    return geotiff(np.full((72, 72), ground), dtype="int16", west=west, north=north)


def terrain_info(name="wgs84_COP30_N42W086_dem.tif"):
    return {"dataset": "COP30", "undulation": -33.5, "bounds": [LON0 - 0.01, LAT0 - 0.01, LON0 + 0.01, LAT0 + 0.01],
            "name": name}


class TestObliqueTerrainApi(BootTestCase):
    """Oblique AGL through the API: routes/<pk>/terrain fetches the ground under the route and keeps it on the route,
    and the export embeds it. missions.terrain.fetch_terrain is mocked throughout (see test_mission_terrain)."""

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
            route.delete()          # with its terrain folder
        disable_plugin("mission_planner")

    def post(self, path, data):
        return self.client.post(API + path, json.dumps(data), content_type="application/json")

    def agl_body(self, **over):
        over.setdefault("terrain_source", "cop30")      # the lidar's terrain: test_lidar_terrain
        return body(height_mode="realTimeFollowSurface", collection_mode="oblique", gimbal_pitch=-45,
                    route_id=self.route.id, **over)

    def fetch(self, tif=None, **over):
        with mock.patch.object(terrain, "fetch_terrain", return_value=(tif or terrain_tif(), terrain_info())) as fetch:
            res = self.post("routes/%d/terrain" % self.route.id, self.agl_body(**over))
        return res, fetch

    def test_fetching_the_terrain_keeps_it_on_the_route(self):
        res, fetch = self.fetch()
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res.json()["name"], "wgs84_COP30_N42W086_dem.tif")
        self.assertIn("fetched_at", res.json())

        points = fetch.call_args.args[0]
        for corner in rectangle(60, 40):
            self.assertIn(tuple(corner), points)
        self.route.refresh_from_db()
        self.assertEqual(self.route.terrain_info, res.json())
        self.assertEqual(self.route.read_terrain(), terrain_tif())
        detail = self.client.get(API + "routes/%d" % self.route.id).json()
        self.assertEqual(detail["terrain_info"], res.json())

    def test_fetching_again_replaces_the_terrain_and_removes_the_old_file(self):
        self.fetch()
        self.route.refresh_from_db()
        old = self.route.terrain_path()
        self.fetch(tif=terrain_tif(ground=190.0))
        self.route.refresh_from_db()
        self.assertNotEqual(self.route.terrain_path(), old)
        self.assertFalse(os.path.exists(old))
        self.assertEqual(self.route.read_terrain(), terrain_tif(ground=190.0))

    def test_deleting_the_route_removes_its_terrain_file_and_folder(self):
        self.fetch()
        self.route.refresh_from_db()
        path = self.route.terrain_path()
        self.assertTrue(os.path.exists(path))
        self.client.delete(API + "routes/%d" % self.route.id)
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(os.path.dirname(path)))

    def test_a_failed_fetch_keeps_the_cached_terrain_and_says_whether_it_covers_the_plan(self):
        url = "routes/%d/terrain" % self.route.id
        failing = mock.patch.object(terrain, "fetch_terrain", side_effect=terrain.TerrainError("The terrain service returned an error (503)"))
        with failing:
            res = self.post(url, self.agl_body())
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.json(), {"error": "The terrain service returned an error (503)", "cached_covers": False})

        self.fetch()
        with failing:
            res = self.post(url, self.agl_body())
            self.assertEqual(res.json()["cached_covers"], True)
            moved = [[lon + 0.05, lat] for lon, lat in rectangle(60, 40)]
            res = self.post(url, self.agl_body(polygon=moved))
            self.assertEqual(res.json()["cached_covers"], False)
        self.route.refresh_from_db()
        self.assertEqual(self.route.terrain_info["name"], "wgs84_COP30_N42W086_dem.tif")

    def test_only_a_mission_over_the_terrain_fetches_terrain(self):
        for b in (body(collection_mode="oblique", gimbal_pitch=-45, height_mode="relativeToStartPoint"),
                  body(height_mode="realTimeFollowSurface")):
            res = self.post("routes/%d/terrain" % self.route.id, b)
            self.assertEqual(res.status_code, 400)
            self.assertIn("Only an AGL route with the DSM follow", res.json()["error"])

    def test_the_route_type_of_the_body_must_be_the_routes(self):
        res = self.post("routes/%d/terrain" % self.route.id, {"route_type": "linear"})
        self.assertEqual(res.status_code, 400)

    def test_an_ortho_agl_mission_with_the_dsm_follow_embeds_the_route_terrain(self):
        b = dict(height_mode="realTimeFollowSurface", surface_follow="dsm", route_id=self.route.id)
        self.assertEqual(self.post("export", body(**b)).status_code, 409)
        with mock.patch.object(terrain, "fetch_terrain", return_value=(terrain_tif(), terrain_info())):
            self.assertEqual(self.post("routes/%d/terrain" % self.route.id, body(**b)).status_code, 200)
        res = self.post("export", body(**b))
        self.assertEqual(res.status_code, 200, res.content[:300])
        z = zipfile.ZipFile(io.BytesIO(res.content))
        self.assertIn("<wpml:isRealtimeSurfaceFollow>0<", z.read("wpmz/template.kml").decode())
        heights = [float(e.text) for e in ET.fromstring(z.read("wpmz/waylines.wpml")).iter(
            "{http://www.dji.com/wpmz/1.0.6}executeHeight")]
        self.assertEqual(set(heights), {180.0 + body()["height"]})

    def test_an_unknown_surface_follow_is_refused(self):
        res = self.post("plan", body(height_mode="realTimeFollowSurface", surface_follow="lidar"))
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unknown surface follow", res.json()["error"])
        self.assertIn("must be text", self.post("plan", body(surface_follow=1)).json()["error"])

    def test_the_terrain_of_another_users_route_is_not_found(self):
        other = routes.create(owner=User.objects.get(username="testuser2"), name="Theirs", route_type="area")
        res = self.post("routes/%d/terrain" % other.id, self.agl_body())
        self.assertEqual(res.status_code, 404)

    def test_the_export_embeds_the_route_terrain(self):
        self.fetch()
        res = self.post("export", self.agl_body())
        self.assertEqual(res.status_code, 200, res.content[:300])
        z = zipfile.ZipFile(io.BytesIO(res.content))
        self.assertEqual(z.read("wpmz/res/dsm/wgs84_COP30_N42W086_dem.tif"), terrain_tif())
        heights = [float(e.text) for e in ET.fromstring(z.read("wpmz/waylines.wpml")).iter(
            "{http://www.dji.com/wpmz/1.0.6}executeHeight")]
        self.assertEqual(set(heights), {210.0})         # 30 m over flat ground at 180 m

    def test_the_export_asks_for_the_terrain_when_the_route_has_none_or_it_does_not_cover_the_plan(self):
        res = self.post("export", self.agl_body())
        self.assertEqual(res.status_code, 409)
        self.assertTrue(res.json()["needs_terrain"])
        self.fetch()
        moved = [[lon + 0.05, lat] for lon, lat in rectangle(60, 40)]
        res = self.post("export", self.agl_body(polygon=moved))
        self.assertEqual(res.status_code, 409)

    def test_the_export_of_an_oblique_agl_mission_needs_the_route_id(self):
        b = self.agl_body()
        del b["route_id"]
        res = self.post("export", b)
        self.assertEqual(res.status_code, 400)
        self.assertIn("route_id", res.json()["error"])
