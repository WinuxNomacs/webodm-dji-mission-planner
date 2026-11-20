"""
Tests of the aircraft registry (drones.json, read by missions/drones.py): the file the server and the pages share, and
what it refuses.
"""
import copy

from django.test import SimpleTestCase

from .. import routes
from ..missions import cameras, drones, wpml


class DronesTestCase(SimpleTestCase):
    def broken(self, change):
        data = copy.deepcopy(drones.DATA)
        change(data["m4t"])
        with self.assertRaises(drones.RegistryError):
            drones.parse(data)

    def test_the_registry_has_the_matrice_4t_and_4e_with_the_numbers_pilot_2_writes(self):
        self.assertEqual(list(drones.DRONES)[:2], ["m4t", "m4e"])
        m4t, m4e = drones.DRONES["m4t"], drones.DRONES["m4e"]
        self.assertEqual((m4t.drone, m4t.payload, m4t.app), ((99, 1), 89, "pilot2"))
        self.assertEqual(m4t.payload_sub, {frozenset(["visable"]): 0, frozenset(["visable", "ir"]): 2})
        self.assertEqual((m4e.drone, m4e.payload, m4e.payload_sub), ((99, 0), 88, {frozenset(["visable"]): 0}))

    def test_the_cameras_are_those_measured_from_real_images(self):
        self.assertEqual(cameras.M4T_THERMAL, drones.Camera("ir", "M4T thermal", 12.0, 7.68, 6.144, 640, 512))
        self.assertEqual(cameras.M4T_WIDE, drones.Camera("visable", "M4T wide", 6.7, 9.66, 7.25, 4032, 3024))
        self.assertEqual(cameras.M4E_WIDE, drones.Camera("visable", "M4E wide", 12.3, 5280 * 12.3 / 3725, 3956 * 12.3 / 3725, 5280, 3956))
        self.assertEqual(list(cameras.CAMERAS_BY_MODEL["m4t"]), ["ir", "visable"])

    def test_the_models_the_routes_offer_and_the_mission_files_know_are_the_registry_s(self):
        self.assertEqual(routes.AIRCRAFT_MODELS[:2], (("m4t", "DJI Matrice 4T"), ("m4e", "DJI Matrice 4E")))
        self.assertEqual(routes.AIRCRAFT_MODELS, tuple((k, d.label) for k, d in drones.DRONES.items()))
        self.assertIs(wpml.AIRCRAFT, drones.DRONES)

    def test_a_drone_without_a_field_is_refused(self):
        for field in ("label", "name", "app", "drone", "payload", "payload_sub", "cameras", "route_types", "realtime_follow"):
            self.broken(lambda d: d.pop(field))
        self.broken(lambda d: d["cameras"][0].pop("px_w"))

    def test_a_number_that_is_not_one_is_refused(self):
        self.broken(lambda d: d.update(payload=True))
        self.broken(lambda d: d.update(payload="89"))
        self.broken(lambda d: d.update(drone=[99]))
        self.broken(lambda d: d["cameras"][0].update(focal_mm=0))
        self.broken(lambda d: d["cameras"][0].update(px_w=640.5))

    def test_two_cameras_with_one_key_are_refused(self):
        self.broken(lambda d: d["cameras"].append(dict(d["cameras"][0])))

    def test_a_camera_choice_naming_a_camera_the_drone_does_not_have_is_refused(self):
        self.broken(lambda d: d["payload_sub"].append({"cameras": ["zoom"], "value": 1}))
        self.broken(lambda d: d["payload_sub"].append({"cameras": [], "value": 1}))

    def test_an_unknown_app_is_refused(self):
        self.broken(lambda d: d.update(app="dji-fly"))

    def test_an_empty_registry_is_refused(self):
        with self.assertRaises(drones.RegistryError):
            drones.parse({})
