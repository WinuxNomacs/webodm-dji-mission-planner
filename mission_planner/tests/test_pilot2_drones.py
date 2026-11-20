"""
Tests of the Pilot 2 drones beyond the Matrice 4T and 4E (Phases 15b and 15c: the M300 and M350 with a payload):
the numbers each one's mission file carries,
that the file imports again as that drone, the route types each is offered and the real-time terrain follow only
where DJI documents it.
"""
import json
import re

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase

from .. import routes
from ..missions import drones, linear, waypoints, wpml
from ..missions.kmz_import import read_kmz_route
from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase
from . import test_mission_kmz_import as area_kmz
from . import test_mission_linear as linear_kmz
from . import test_mission_waypoints as waypoint_kmz

API = "/api/plugins/mission_planner/"
NEW = ("m3e", "m3t", "m3m", "m30", "m30t", "m3d", "m3td", "m4d", "m4td")
PAYLOADS = {"h20": 42, "h20t": 43, "h20n": 61, "h30": 82, "h30t": 83}
M300_M350 = tuple("%s-%s" % (d, p) for d in ("m300", "m350") for p in PAYLOADS)


def values(data, tag):
    return re.findall(r"<wpml:%s>([^<]*)</wpml:%s>" % (tag, tag), area_kmz.files(data)["wpmz/template.kml"].decode())


def camera_sets(model):
    return [sorted(keys) for keys in drones.DRONES[model].payload_sub]


class TestRegistry(SimpleTestCase):
    def test_the_new_drones_carry_dji_s_enums(self):
        expected = {"m3e": ((77, 0), 66), "m3t": ((77, 1), 67), "m3m": ((77, 2), 68), "m30": ((67, 0), 52),
                    "m30t": ((67, 1), 53), "m3d": ((91, 0), 80), "m3td": ((91, 1), 81), "m4d": ((100, 0), 98),
                    "m4td": ((100, 1), 99)}
        self.assertEqual({k: (drones.DRONES[k].drone, drones.DRONES[k].payload) for k in NEW}, expected)

    def test_the_thermal_drones_offer_the_thermal_camera_and_the_others_the_wide_camera_only(self):
        for model in NEW:
            thermal = model in ("m3t", "m30t", "m3td", "m4td")
            self.assertEqual(sorted(drones.DRONES[model].cameras), ["ir", "visable"] if thermal else ["visable"], model)
            self.assertEqual(camera_sets(model), [["visable"], ["ir", "visable"]] if thermal else [["visable"]], model)

    def test_the_4_3_inch_cameras_give_dji_s_ground_sample_distance(self):
        # DJI: H/37.2 cm per pixel for the Mavic 3M's RGB camera, the same 4/3" 20 MP camera as the M3E's and M3D's
        for model in ("m3e", "m3m", "m3d"):
            c = drones.DRONES[model].cameras["visable"]
            self.assertAlmostEqual(1 / (c.sensor_w_mm / c.px_w / c.focal_mm * 100), 37.2, delta=0.1)

    def test_the_dock_versions_of_the_matrice_4_have_its_measured_cameras(self):
        m4t, m4e = drones.DRONES["m4t"].cameras, drones.DRONES["m4e"].cameras
        self.assertEqual(drones.DRONES["m4d"].cameras["visable"][2:], m4e["visable"][2:])
        for key in ("visable", "ir"):
            self.assertEqual(drones.DRONES["m4td"].cameras[key][2:], m4t[key][2:])

    def test_each_drone_is_offered_the_route_types_its_documents_name(self):
        types = {k: drones.DRONES[k].route_types for k in drones.DRONES}
        everything = ("area", "linear", "waypoint", "slope", "geometric")
        for model in ("m4t", "m4e", "m3e", "m3t", "m3m", "m3d", "m3td"):
            self.assertEqual(types[model], everything, model)
        for model in ("m30", "m30t", "m4d", "m4td"):
            self.assertEqual(types[model], ("area", "linear", "waypoint"), model)

    def test_real_time_terrain_follow_is_offered_only_where_documented_or_seen_in_pilot_2_s_files(self):
        self.assertEqual(sorted(k for k, d in drones.DRONES.items() if d.realtime_follow), ["m3e", "m3m", "m3t", "m4e", "m4t"])

    def test_a_registry_with_bad_route_types_or_follow_is_refused(self):
        def broken(change):
            data = json.loads(json.dumps(drones.DATA))
            change(data["m30"])
            with self.assertRaises(drones.RegistryError):
                drones.parse(data)
        broken(lambda d: d.update(route_types=[]))
        broken(lambda d: d.update(route_types=["area", "area"]))
        broken(lambda d: d.update(route_types=["patrol"]))
        broken(lambda d: d.update(realtime_follow="yes"))
        broken(lambda d: d.pop("route_types"))
        broken(lambda d: d.pop("realtime_follow"))
        broken(lambda d: d.update(cameras=[dict(d["cameras"][0], key="wide")], payload_sub=[{"cameras": ["wide"], "value": 0}]))


class TestM300AndM350(SimpleTestCase):
    def test_each_payload_is_a_model_with_dji_s_enums(self):
        for model in M300_M350:
            d = drones.DRONES[model]
            self.assertEqual((d.drone, d.payload), ((60, 0) if model.startswith("m300") else (89, 0), PAYLOADS[model[5:]]), model)
            self.assertEqual(d.route_types, ("area", "linear", "waypoint"), model)
            self.assertFalse(d.realtime_follow, model)
            self.assertEqual(sorted(d.cameras), ["ir", "visable"] if model.endswith(("t", "n")) else ["visable"], model)

    def test_the_wide_camera_is_called_wide_in_the_file_and_imports_back_as_the_wide_camera(self):
        for model in M300_M350:
            for cameras in camera_sets(model):
                with self.subTest(model=model, cameras=cameras):
                    data = area_kmz.export(area_kmz.body(model=model, cameras=cameras, height_mode="relativeToStartPoint"))
                    names = sorted(values(data, "imageFormat")[0].split(","))
                    self.assertEqual(names, sorted("wide" if c == "visable" else c for c in cameras))
                    self.assertEqual(values(data, "payloadEnumValue"), [str(PAYLOADS[model[5:]])])
                    imported, settings, body = read_kmz_route(data, "x")
                    self.assertEqual((imported, sorted(body["cameras"])), (model, cameras))
        w = waypoints.build_kmz(waypoint_kmz.route(model="m350-h30t"), now=1700000000)
        self.assertEqual(values(w, "imageFormat"), ["wide,ir"])
        self.assertEqual(read_kmz_route(w, "x")[0], "m350-h30t")

    def test_the_sensors_agree_with_dji_s_focal_length_and_field_of_view(self):
        import math
        for model, dfov in (("m300-h20", 82.9), ("m350-h20n", 73.6), ("m350-h30", 82.1)):
            c = drones.DRONES[model].cameras["visable"]
            self.assertAlmostEqual(2 * math.degrees(math.atan(math.hypot(c.sensor_w_mm, c.sensor_h_mm) / 2 / c.focal_mm)), dfov, delta=0.05)


class TestMissionFiles(SimpleTestCase):
    def test_each_drone_s_area_mission_carries_its_numbers_and_imports_as_that_drone(self):
        for model in NEW:
            d = drones.DRONES[model]
            for cameras in camera_sets(model):
                with self.subTest(model=model, cameras=cameras):
                    data = area_kmz.export(area_kmz.body(model=model, cameras=cameras, height_mode="relativeToStartPoint"))
                    self.assertEqual(values(data, "droneEnumValue") + values(data, "droneSubEnumValue"), [str(v) for v in d.drone])
                    self.assertEqual(values(data, "payloadEnumValue"), [str(d.payload)])
                    self.assertEqual(values(data, "payloadSubEnumValue"), [str(d.payload_sub[frozenset(cameras)])])
                    self.assertEqual(sorted(values(data, "imageFormat")[0].split(",")), cameras)
                    imported, settings, _ = read_kmz_route(data, "x")
                    self.assertEqual(imported, model)
                    self.assertEqual(settings["lens_ir"], "true" if "ir" in cameras else "false")

    def test_a_linear_and_a_waypoint_mission_import_as_their_drone(self):
        s = linear_kmz.export(linear_kmz.body(model="m30t", height_mode="relativeToStartPoint"))
        self.assertEqual(read_kmz_route(s, "x")[0], "m30t")
        w = waypoints.build_kmz(waypoint_kmz.route(model="m4td"), now=1700000000)
        self.assertEqual(read_kmz_route(w, "x")[0], "m4td")

    def test_real_time_follow_is_refused_for_a_drone_without_it(self):
        for model in ("m30", "m3d", "m4d"):
            with self.subTest(model=model):
                with self.assertRaisesRegex(wpml.ExportError, "cannot follow the ground in real time"):
                    area_kmz.export(area_kmz.body(model=model, cameras=["visable"], surface_follow="realtime"))
                with self.assertRaisesRegex(wpml.ExportError, "cannot follow the ground in real time"):
                    linear_kmz.export(linear_kmz.body(model=model, cameras=["visable"], height_mode="realTimeFollowSurface",
                                                      surface_follow="realtime"))

    def test_agl_defaults_to_the_terrain_model_for_a_drone_without_real_time_follow(self):
        from .. import api
        s = api.parse_settings(area_kmz.body(model="m30", cameras=["visable"]))
        self.assertEqual((s.height_mode, s.surface_follow, wpml.uses_dsm(s)), ("realTimeFollowSurface", "dsm", True))
        s = api.parse_linear_settings(linear_kmz.body(model="m4d", cameras=["visable"], height_mode="realTimeFollowSurface"))
        self.assertEqual((s.surface_follow, linear.uses_dsm(s)), ("dsm", True))
        self.assertEqual(api.parse_settings(area_kmz.body(model="m3e", cameras=["visable"])).surface_follow, "realtime")

    def test_oblique_agl_and_other_height_modes_need_no_real_time_follow(self):
        area_kmz.export(area_kmz.body(model="m30", cameras=["visable"], height_mode="relativeToStartPoint", surface_follow="realtime"))
        s = wpml.settings(**dict(polygon=area_kmz.rectangle(80, 50), direction=0, height=40, cameras=[drones.DRONES["m30"].cameras["visable"]],
                                 overlap_h=80, overlap_w=70, margin=0, speed=None, takeoff_security_height=25, rth_height=90,
                                 model="m30", collection_mode="oblique", gimbal_pitch=-45, surface_follow="realtime"))
        self.assertTrue(wpml.uses_dsm(s))


class TestApi(BootTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.user = User.objects.get(username="testuser")

    def tearDown(self):
        for route in routes.all():
            route.delete()
        disable_plugin("mission_planner")

    def post(self, path, body):
        return self.client.post(API + path, json.dumps(body), content_type="application/json")

    def test_a_route_type_the_drone_is_not_offered_is_not_created(self):
        res = self.post("routes", {"name": "x", "route_type": "slope", "model": "m30"})
        self.assertEqual(res.status_code, 400, res.content[:200])
        self.assertIn("The Matrice 30 is not offered slope routes", str(res.json()["route_type"]))
        self.assertEqual(self.post("routes", {"name": "x", "route_type": "geometric", "model": "m3d"}).status_code, 201)
        self.assertEqual(routes.count(), 1)

    def test_a_route_is_not_copied_to_a_drone_not_offered_its_type(self):
        route = routes.create(owner=self.user, name="Face", route_type="slope", model="m4t")
        res = self.post("routes/%d/copy" % route.id, {"model": "m4td"})
        self.assertEqual(res.status_code, 400, res.content[:200])
        self.assertIn("The Matrice 4TD is not offered slope routes", str(res.json()["model"]))
        self.assertEqual(routes.count(), 1)

    def test_a_copy_to_a_drone_without_real_time_follow_flies_over_the_terrain_model(self):
        route = routes.create(owner=self.user, name="Field", route_type="area", model="m4t",
                              settings={"height": "50", "surface_follow": "realtime"})
        res = self.post("routes/%d/copy" % route.id, {"model": "m30t"})
        self.assertEqual(res.status_code, 201, res.content[:200])
        self.assertEqual(res.json()["settings"]["surface_follow"], "dsm")
        res = self.post("routes/%d/copy" % route.id, {"model": "m3t"})
        self.assertEqual(res.json()["settings"]["surface_follow"], "realtime")

    def test_a_mission_of_a_route_type_the_drone_is_not_offered_is_not_imported(self):
        data = area_kmz.edited(area_kmz.sample("m4t-test-geo.kmz"), area_kmz.element("droneEnumValue", 67),
                               area_kmz.element("payloadEnumValue", 53))
        res = self.client.post(API + "routes/import", {"file": SimpleUploadedFile("Block.kmz", data)})
        self.assertEqual(res.status_code, 400, res.content[:200])
        self.assertIn("The Matrice 30T is not offered geometric routes", res.json()["error"])
        self.assertEqual(routes.count(), 0)
