"""
Tests of importing a Pilot 2 area mission (.kmz) as a saved route: missions/kmz_import.py and the mission planner's
routes/import endpoint. A route is imported only when the planner exports the same mission again; every other file is
refused with the reason.
"""
import io
import os
import re
import unittest
import zipfile
from unittest import mock

import numpy as np
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase

from ..missions import geoid, wpml
from ..missions.kmz_import import KmzImportError, altitude_text, form_number, read_kmz_dsm, read_kmz_route, route_name
from .. import routes
from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase
from .test_mission_planning import KMZ_DIR, LAT0, LON0, rectangle
from .test_mission_terrain import geotiff

API = "/api/plugins/mission_planner/"
from .. import api as mission_planner_api
NOW = 1700000000


def sample(name):
    path = os.path.join(KMZ_DIR, name)
    if not os.path.isfile(path):
        raise unittest.SkipTest("%s is not in %s" % (name, KMZ_DIR))
    with open(path, "rb") as f:
        return f.read()


def body(**over):
    # The corners as precise as the planner's drawing keeps them (kmz_import.read_polygon)
    b = {"model": "m4t", "polygon": [[round(v, 9) for v in p] for p in rectangle(80, 50)], "direction": 30, "height": 40,
         "cameras": ["visable", "ir"], "overlap_h": 80, "overlap_w": 70, "margin": 2, "speed": 6.5,
         "height_mode": "realTimeFollowSurface", "takeoff_security_height": 25, "rth_height": 90,
         "finish_action": "goHome", "exit_on_rc_lost": "goContinue", "takeoff_ref_point": [LAT0 - 0.0002, LON0 - 0.0001, 210.25],
         "transitional_speed": 12, "takeoff_mode": "safe", "elevation_optimize": True, "avoid_limit_area": False,
         "photo_mode": "distance", "route_start": None, "name": "luxodm-mission", "collection_mode": "ortho"}
    b.update(over)
    return b


def export(b, dsm=None):
    s = mission_planner_api.parse_settings(b)
    return wpml.build_kmz(wpml.plan_from_settings(s), s, now=NOW, dsm=dsm)


def dsm():
    """A DSM around the test area as Pilot 2 names its own, the ground rising 1 m a cell (~30 m) to the east from 200 m"""
    return geotiff(np.tile(200.0 + np.arange(36), (36, 1)), west=LON0 - 0.005, north=LAT0 + 0.005), "wgs84_COP30_N42W086_dem_1.tif"


def oblique(**over):
    return body(collection_mode="oblique", gimbal_pitch=-45, inclined_overlap_h=75, inclined_overlap_w=65, inclined_speed=4.5, **over)


def files(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n) for n in z.namelist()}


def edited(data, *replacements, extra=None):
    """The mission file with its template.kml edited by (pattern, replacement) regular expressions"""
    content = files(data)
    template = content["wpmz/template.kml"].decode()
    for pattern, replacement in replacements:
        template, count = re.subn(pattern, replacement, template)
        assert count, pattern
    content["wpmz/template.kml"] = template.encode()
    content.update(extra or {})
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, value in content.items():
            z.writestr(name, value)
    return out.getvalue()


def damaged(data, flags=None, method=None, corrupt=None):
    """The zip with every entry's flags or compression method set as given in its headers (flags 1: encrypted;
    method 99: AES), or with the stored bytes of entry `corrupt` changed (its CRC then fails)"""
    content = files(data)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for name, value in content.items():
            z.writestr(name, value)
    b = bytearray(out.getvalue())
    if corrupt is not None:
        at = b.index(content[corrupt][:64])
        b[at + len(content[corrupt]) // 2] ^= 0xFF
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        at = b.find(signature)
        while at >= 0:
            if flags is not None:
                b[at + offset:at + offset + 2] = flags.to_bytes(2, "little")
            if method is not None:
                b[at + offset + 2:at + offset + 4] = method.to_bytes(2, "little")
            at = b.find(signature, at + 4)
    return bytes(b)


def element(tag, value):
    return (r"<wpml:%s>[^<]*</wpml:%s>" % (tag, tag), "<wpml:%s>%s</wpml:%s>" % (tag, value, tag))


class TestReadingPilot2Samples(SimpleTestCase):
    """The area missions exported by Pilot 2 that the planner can fly (tests/fixtures/dji-kmz/README.md)"""

    def read(self, name):
        model, settings, b = read_kmz_route(sample(name), route_name(name))
        return model, settings

    def test_an_m4t_area_above_the_ground_is_read_with_all_its_settings(self):
        model, s = self.read("TestAreaRoute.kmz")
        self.assertEqual(model, "m4t")
        self.assertEqual({k: s[k] for k in ("name", "lens_visible", "lens_ir", "height", "overlap_h", "overlap_w", "margin",
                                            "direction", "speed", "altitude_mode", "takeoff_mode", "takeoff_security_height",
                                            "rth_height", "transitional_speed", "takeoff_altitude", "finish_action",
                                            "exit_on_rc_lost", "collection_mode", "elevation_optimize", "avoid_limit_area")},
                         {"name": "TestAreaRoute", "lens_visible": "true", "lens_ir": "true", "height": "100.5", "overlap_h": "80",
                          "overlap_w": "70", "margin": "0", "direction": "181", "speed": "10.2", "altitude_mode": "agl",
                          "takeoff_mode": "safe", "takeoff_security_height": "100", "rth_height": "100", "transitional_speed": "15",
                          "takeoff_altitude": "243.983236", "finish_action": "goHome", "exit_on_rc_lost": "goContinue",
                          "collection_mode": "ortho", "elevation_optimize": "true", "avoid_limit_area": "false"})
        # takeOffRefPoint's height is ellipsoidal (209.782061): above sea level it is that minus EGM96's -34.2 m
        self.assertEqual(s["takeoff_ellipsoidal_height"], "209.782061")
        self.assertEqual(s["takeoff"], [42.103173, -85.020786])
        self.assertIsNone(s["route_start"])
        self.assertEqual(s["gimbal_pitch"], "")

    def test_the_corners_are_kept_to_9_decimals_as_the_planners_map_draws_them(self):
        model, s = self.read("TestAreaRoute.kmz")
        self.assertEqual(s["polygon"][0], [-85.020796977, 42.10374872])
        for lon, lat in s["polygon"]:
            self.assertEqual((lon, lat), (round(lon, 9), round(lat, 9)))
        self.assertGreaterEqual(len(s["polygon"]), 3)
        self.assertNotEqual(s["polygon"][0], s["polygon"][-1])  # an open ring, as the planner keeps it

    def test_float_values_from_pilot_2_read_as_the_numbers_shown_in_pilot_2(self):
        model, s = self.read("HomerunThermalOnly.kmz")
        self.assertEqual((s["altitude_mode"], s["speed"], s["height"], s["margin"], s["direction"]), ("alt", "0.89", "14.020972", "1", "188"))
        self.assertEqual((s["overlap_h"], s["overlap_w"], s["transitional_speed"]), ("85", "85", "10"))
        self.assertEqual(s["rth_height"], "100")  # not in the file
        self.assertEqual(s["exit_on_rc_lost"], "executeLostAction")
        self.assertEqual((s["lens_visible"], s["lens_ir"]), ("true", "true"))  # "ir,visable"
        self.assertEqual((s["takeoff_altitude"], s["takeoff_ellipsoidal_height"]), ("34.201839", "0"))   # a takeoff point at 0 m ellipsoidal

    def test_an_oblique_area_above_sea_level_takes_the_ground_heights_from_the_mission_heights(self):
        model, s = self.read("testkmz-oblique-asl.kmz")
        self.assertEqual((s["collection_mode"], s["altitude_mode"], s["height"], s["gimbal_pitch"]), ("oblique", "asl", "50", "-45"))
        self.assertEqual((s["inclined_overlap_h"], s["inclined_overlap_w"], s["speed"], s["inclined_speed"]), ("80", "70", "5.1", "4.1"))
        self.assertEqual(s["takeoff_altitude"], "242.417235")          # 292.417235349383 - 50
        self.assertEqual(s["takeoff_ellipsoidal_height"], "208.215055")  # 258.215054591815 - 50
        self.assertEqual(len(s["polygon"]), 4)

    def test_the_geoid_grid_gives_pilot_2s_own_difference_between_sea_level_and_the_ellipsoid(self):
        # Pilot 2 wrote both heights into this mission: its difference and EGM96's agree to the millimetre
        model, s = self.read("testkmz-oblique-asl.kmz")
        lat, lon = s["takeoff"]
        pilot2 = float(s["takeoff_ellipsoidal_height"]) - float(s["takeoff_altitude"])
        self.assertAlmostEqual(geoid.undulation(lat, lon), pilot2, delta=0.001)

    def test_without_the_geoid_grid_an_imported_takeoff_height_above_sea_level_is_left_blank(self):
        with mock.patch.object(geoid, "undulation", side_effect=geoid.GeoidError("no grid")):
            model, s = self.read("TestAreaRoute.kmz")
            self.assertEqual((s["takeoff_altitude"], s["takeoff_ellipsoidal_height"]), ("", "209.782061"))
            # a waypoint route above the takeoff point: the M4E sample switched from EGM96 to ALT
            data = sample("m4e-test-waypoint.kmz")
            z = zipfile.ZipFile(io.BytesIO(data))
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w") as copy:
                for name in z.namelist():
                    copy.writestr(name, z.read(name).replace(b">EGM96<", b">relativeToStartPoint<"))
            model, s, body = read_kmz_route(out.getvalue(), "x")
            self.assertEqual((s["takeoff_altitude"], s["takeoff_ellipsoidal_height"]), ("", "208.561609"))
            self.assertIsNone(body["takeoff_ref_point"])
            # above sea level, Pilot 2's own offset gives the sea-level height: no grid needed
            model, s, body = read_kmz_route(sample("m4e-test-waypoint.kmz"), "x")
            self.assertNotEqual(s["takeoff_altitude"], "")

    def test_oblique_areas_over_pilot_2s_elevation_model_are_read_above_the_ground_with_the_dsm_follow(self):
        # takeoff: above sea level, from takeOffRefPoint's ellipsoidal 183.25029 and 208.589271
        for name, height, takeoff, tile in (("m4t-testkmz-oblique-AGL.kmz", "49.99939", "216.97781", "N41W080_dem_2"),
                                            ("testkmz-oblique-speed-on.kmz", "50", "242.791097", "N42W086_dem_9"),
                                            ("testkmz-oblique-speed-off.kmz", "50", "242.791097", "N42W086_dem_9")):
            with self.subTest(name):
                model, s = self.read(name)
                self.assertEqual((s["collection_mode"], s["altitude_mode"], s["surface_follow"], s["height"], s["takeoff_altitude"]),
                                 ("oblique", "agl", "dsm", height, takeoff))
                tif, info = read_kmz_dsm(sample(name))
                self.assertEqual(tif, files(sample(name))["wpmz/res/dsm/" + info["name"]])
                self.assertEqual((info["dataset"], info["undulation"], info["name"]), ("ASTGTMV003", None, "wgs84_ASTGTMV003_%s.tif" % tile))
                west, south, east, north = info["bounds"]
                lat, lon = s["takeoff"]
                self.assertTrue(west < lon < east and south < lat < north)

    def test_the_imported_routes_export_the_same_heights_and_settings_as_the_samples(self):
        for name in ("TestAreaRoute.kmz", "HomerunThermalOnly.kmz", "testkmz-oblique-asl.kmz", "m4t-testkmz-oblique-AGL.kmz",
                     "testkmz-oblique-speed-on.kmz"):
            with self.subTest(name):
                model, settings, b = read_kmz_route(sample(name), "x")
                terrain = read_kmz_dsm(sample(name))
                original = wpml_values(files(sample(name))["wpmz/template.kml"])
                again = wpml_values(files(export(b, dsm=terrain and (terrain[0], terrain[1]["name"])))["wpmz/template.kml"])
                for tag in ("globalShootHeight", "height", "ellipsoidHeight", "autoFlightSpeed", "inclinedFlightSpeed",
                            "direction", "margin", "orthoCameraOverlapH", "orthoCameraOverlapW", "inclinedGimbalPitch",
                            "takeOffSecurityHeight", "globalTransitionalSpeed", "heightMode", "imageFormat", "finishAction",
                            "exitOnRCLost", "flyToWaylineMode", "payloadSubEnumValue", "templateType", "surfaceFollowModeEnable",
                            "isRealtimeSurfaceFollow", "dsmFile"):
                    if tag in original:
                        self.assertIn(tag, again)
                        self.assertAlmostEqualOrSame(original[tag], again[tag], tag)
                # The takeoff point's position; its altitude is Pilot 2's ellipsoidal one, the planner's is above sea level
                ref, ref_again = original["takeOffRefPoint"].split(","), again["takeOffRefPoint"].split(",")
                for a, b2 in zip(ref[:2], ref_again[:2]):
                    self.assertAlmostEqual(float(a), float(b2), places=6)

    def assertAlmostEqualOrSame(self, a, b, tag):
        try:
            self.assertAlmostEqual(float(a), float(b), places=5, msg=tag)
        except ValueError:
            self.assertEqual(set(a.split(",")), set(b.split(",")), tag)

    def test_everything_else_pilot_2_exports_is_refused_with_the_reason(self):
        refused = {
            "m4e-test-area.kmz": "Smart Oblique", "m4e-test-area-alt50m-gsd1.41cm-ogsd1.99cm.kmz": "Smart Oblique",
            "m4t-test-area-alt15m-gsd0.62cm-ogsd0.88cm.kmz": "Smart Oblique", "HomerunObliqueII.kmz": "Smart Oblique",
            "TestAreaKMZ-30.kmz": "seconds", "Homerun-Smart4e.kmz": "Smart 3D", "TestWaypointRoute.kmz": "panoShot",
            "m4t-test-waypoint.kmz": "video starts at point 2",
            "m4t-test-poi.kmz": r"heading mode \(fixed\)", "m4t-test-poi-toward-poi.kmz": r"heading mode \(fixed\)",
            "m4t-test-patrol.kmz": "patrol", "testkmz-oblique-alt.kmz": "ground height for the area",
        }
        for name, reason in refused.items():
            with self.subTest(name):
                with self.assertRaisesRegex(KmzImportError, reason):
                    read_kmz_route(sample(name), "x")


def wpml_values(template):
    """Every wpml element with text in a template.kml, by tag (the first one of each)"""
    values = {}
    for tag, value in re.findall(r"<wpml:(\w+)>([^<]+)</wpml:\1>", template.decode()):
        values.setdefault(tag, value.strip())
    return values


class TestRoundTrip(SimpleTestCase):
    """A mission the planner exported imports as the same form, and exports again as the same file"""

    def round_trip(self, b):
        data = export(b)
        model, settings, again = read_kmz_route(data, "luxodm-mission")
        self.assertEqual(model, b["model"])
        self.assertEqual(files(export(again)), files(data))
        return settings

    def test_every_model_mode_and_height_mode_exports_the_same_file_again(self):
        for model, cameras in (("m4t", ["visable", "ir"]), ("m4t", ["visable"]), ("m4e", ["visable"])):
            for mode in ("realTimeFollowSurface", "relativeToStartPoint", "EGM96"):
                for collection in ("ortho", "oblique"):
                    if collection == "oblique" and mode == "realTimeFollowSurface":
                        continue
                    b = body(model=model, cameras=cameras, height_mode=mode, collection_mode=collection)
                    if mode == "EGM96":
                        b["takeoff_ellipsoidal_height"] = 176.4
                    if collection == "oblique":
                        b.update(gimbal_pitch=-60, inclined_overlap_h=75, inclined_overlap_w=65, inclined_speed=4.5)
                    with self.subTest(model=model, cameras=cameras, mode=mode, collection=collection):
                        self.round_trip(b)

    def test_a_mission_over_its_elevation_model_exports_the_same_file_again_with_the_same_dsm(self):
        terrain = dsm()
        for b in (body(surface_follow="dsm"), body(surface_follow="dsm", model="m4e", cameras=["visable"]), oblique()):
            with self.subTest(model=b["model"], collection=b["collection_mode"]):
                data = export(b, dsm=terrain)
                model, settings, again = read_kmz_route(data, "luxodm-mission")
                self.assertEqual((settings["altitude_mode"], settings["surface_follow"]), ("agl", "dsm"))
                tif, info = read_kmz_dsm(data)
                self.assertEqual((tif, info["name"], info["dataset"], info["undulation"]), (terrain[0], terrain[1], "COP30", None))
                self.assertEqual(files(export(again, dsm=(tif, info["name"]))), files(data))

    def test_a_mission_following_the_ground_in_real_time_has_no_dsm(self):
        data = export(body())
        self.assertEqual(read_kmz_route(data, "x")[1]["surface_follow"], "realtime")
        self.assertIsNone(read_kmz_dsm(data))
        self.assertIsNone(read_kmz_dsm(edited(data, extra={"wpmz/res/dsm/ground.tif": b"tif"})))  # a stray file is not followed

    def test_the_other_options_come_back_as_they_were_set(self):
        s = self.round_trip(body(takeoff_mode="direct", finish_action="autoLand", exit_on_rc_lost="executeLostAction",
                                 elevation_optimize=False, avoid_limit_area=True, direction=359.5, margin=0))
        self.assertEqual((s["takeoff_mode"], s["finish_action"], s["exit_on_rc_lost"]), ("direct", "autoLand", "executeLostAction"))
        self.assertEqual((s["elevation_optimize"], s["avoid_limit_area"], s["direction"], s["margin"]), ("false", "true", "359.5", "0"))

    def test_a_mission_without_a_takeoff_point_has_none(self):
        s = self.round_trip(body(takeoff_ref_point=None))
        self.assertIsNone(s["takeoff"])
        self.assertEqual(s["takeoff_altitude"], "")

    def test_a_speed_left_to_the_planner_is_imported_as_the_speed_it_chose(self):
        data = export(body(speed=None))
        model, s, b = read_kmz_route(data, "x")
        self.assertEqual(s["speed"], re.search(r"<wpml:autoFlightSpeed>([^<]+)<", files(data)["wpmz/template.kml"].decode()).group(1))
        self.assertEqual(files(export(b)), files(data))

    def test_the_settings_fill_every_field_of_the_form(self):
        s = self.round_trip(body())
        form = ("name lens_visible lens_ir height overlap_h overlap_w margin direction speed altitude_mode takeoff_mode "
                "takeoff_security_height rth_height transitional_speed elevation_optimize avoid_limit_area photo_mode "
                "takeoff_altitude finish_action exit_on_rc_lost collection_mode gimbal_pitch inclined_overlap_h "
                "inclined_overlap_w inclined_speed takeoff_ellipsoidal_height surface_follow").split()
        for key in form:
            self.assertIsInstance(s[key], str, key)
        self.assertEqual(set(s), set(form) | {"polygon", "takeoff", "route_start"})


class TestRefusals(SimpleTestCase):
    """What the planner cannot export the same again is refused, with the reason"""

    def refused(self, data, reason):
        with self.assertRaisesRegex(KmzImportError, reason):
            read_kmz_route(data, "x")

    def test_a_file_that_is_not_a_mission_is_refused(self):
        self.refused(b"not a zip", "not a .kmz")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("doc.kml", "<kml/>")
        self.refused(out.getvalue(), "no wpmz/template.kml")
        self.refused(edited(export(body()), (r"</kml>", "")), "not valid XML")

    def test_an_encrypted_or_damaged_zip_is_refused_with_a_reason(self):
        data = export(body())
        self.refused(damaged(data, flags=1), "cannot be read")
        self.refused(damaged(data, method=99), "cannot be read")
        self.refused(damaged(data, corrupt="wpmz/template.kml"), "cannot be read")
        with_dsm = export(body(surface_follow="dsm"), dsm=dsm())
        with self.assertRaisesRegex(KmzImportError, "cannot be read"):
            read_kmz_dsm(damaged(with_dsm, corrupt="wpmz/res/dsm/" + dsm()[1]))

    def test_a_template_with_a_doctype_is_refused(self):
        self.refused(edited(export(body()), (r"^<\?xml[^>]*\?>", '<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY e "x">]>')), "not valid XML")

    def test_pilot_2_options_the_planner_cannot_fly_are_refused(self):
        data = export(body())
        self.refused(edited(data, element("smartObliqueEnable", 1)), "Smart Oblique")
        # An area with the facade option is a slope, whose corners have heights above sea level
        self.refused(edited(data, element("facadeWaylineEnable", 1)), "slope's heights are in realTimeFollowSurface")
        self.refused(edited(data, element("quickOrthoMappingEnable", 1)), "quick ortho")
        self.refused(edited(data, element("doubleGridWaylineEnable", 1)), "double grid")
        self.refused(edited(data, element("efficiencyFlightModeEnable", 1)), "efficiency")
        self.refused(edited(data, element("caliFlightEnable", 1)), "calibration")
        self.refused(edited(data, element("shootType", "time")), "seconds")

    def test_an_elevation_model_that_is_not_in_the_file_or_not_pilot_2s_is_refused(self):
        data = export(body(surface_follow="dsm"), dsm=dsm())
        name = "wpmz/res/dsm/" + dsm()[1]
        self.refused(edited(export(body()), element("isRealtimeSurfaceFollow", 0)), "DSM.* not in the file")
        self.refused(edited(data, element("dsmFile", "wpmz/res/dsm/other.tif")), "DSM.* not in the file")
        self.refused(edited(data, element("heightMode", "WGS84")), "DSM.* WGS84: Pilot 2 writes EGM96")
        for tif, reason in ((b"not a tif", "cannot be read"), (geotiff(np.zeros((4, 4)), crs="EPSG:32616"), "not in WGS84")):
            with self.assertRaisesRegex(KmzImportError, reason):
                read_kmz_dsm(edited(data, extra={name: tif}))

    def test_other_coordinates_heights_and_aircraft_are_refused(self):
        data = export(body())
        self.refused(edited(data, element("coordinateMode", "GCJ02")), "WGS84")
        self.refused(edited(data, element("heightMode", "WGS84")), "height mode")
        self.refused(edited(data, element("droneEnumValue", 91)), "aircraft or camera")
        self.refused(edited(data, element("payloadSubEnumValue", 5)), "do not match")
        self.refused(edited(data, element("imageFormat", "ir")), "cannot be planned for the Matrice 4T")
        self.refused(edited(export(body(model="m4e", cameras=["visable"])), element("imageFormat", "visable,ir")), "Matrice 4E")

    def test_a_mission_flown_at_another_height_than_its_own_is_refused(self):
        for mode in ("relativeToStartPoint", "realTimeFollowSurface"):
            data = export(body(height_mode=mode))
            self.refused(edited(data, element("height", 39.5)), "flies 39.5 m above the takeoff point for a height of 40 m")

    def test_an_oblique_mission_following_the_ground_in_real_time_is_refused(self):
        data = export(body(height_mode="relativeToStartPoint", collection_mode="oblique", gimbal_pitch=-45))
        self.refused(edited(data, element("heightMode", "realTimeFollowSurface")), "in real time")

    def test_values_outside_the_planners_limits_are_refused(self):
        data = export(body())
        self.refused(edited(data, element("globalShootHeight", 600)), "height")
        self.refused(edited(data, element("orthoCameraOverlapH", 5)), "overlap along")
        self.refused(edited(data, element("autoFlightSpeed", 20)), "speed")
        self.refused(edited(data, element("takeOffSecurityHeight", 1)), "takeoff security")
        self.refused(edited(data, element("margin", -3)), "margin")
        self.refused(edited(data, element("globalShootHeight", "high")), "not a number")
        self.refused(edited(data, element("takeOffRefPoint", "42.1,-85.013728,9999")), "-500 and 9000")

    def test_an_area_with_too_few_or_too_many_corners_is_refused(self):
        data = export(body())
        coordinates = r"<coordinates>[^<]*</coordinates>"
        self.refused(edited(data, (coordinates, "<coordinates>-88,42,0 -88.001,42,0</coordinates>")), "at least 3")
        many = " ".join("%f,%f,0" % (-88 + 0.001 * i, 42 + 0.0001 * (i % 2)) for i in range(201))
        self.refused(edited(data, (coordinates, "<coordinates>%s</coordinates>" % many)), "too many")

    def test_an_asl_mission_without_a_takeoff_point_is_refused(self):
        data = export(body(height_mode="EGM96", takeoff_ellipsoidal_height=176.4))
        self.refused(edited(data, (r"<wpml:takeOffRefPoint>[^<]*</wpml:takeOffRefPoint>", "")), "no takeoff point")


class TestNumbers(SimpleTestCase):
    def test_form_numbers_are_the_shortest_text_of_the_value(self):
        self.assertEqual(form_number(50.0), "50")
        self.assertEqual(form_number(0.0), "0")
        self.assertEqual(form_number(-45.0), "-45")
        self.assertEqual(form_number(0.889999985694885), "0.89")
        self.assertEqual(form_number(10.199999809265137), "10.2")

    def test_altitudes_keep_the_micrometre(self):
        self.assertEqual(altitude_text(209.782061), "209.782061")
        self.assertEqual(altitude_text(0.0), "0")
        self.assertEqual(altitude_text(-0.5), "-0.5")
        self.assertEqual(altitude_text(None), "")

    def test_the_route_name_is_the_file_name_without_the_folder_or_extension(self):
        self.assertEqual(route_name("C:\\missions\\Roof North.KMZ"), "Roof North")
        self.assertEqual(route_name("a/b/area.kmz"), "area")
        self.assertEqual(len(route_name("x" * 300 + ".kmz")), 255)


class TestImportEndpoint(BootTestCase):
    """POST routes/import (api.py RouteImportView)"""

    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.user = User.objects.get(username="testuser")

    def tearDown(self):
        for route in routes.all():
            route.delete()          # with its terrain folder
        disable_plugin("mission_planner")

    def upload(self, data, name="Roof North.kmz", client=None):
        return (client or self.client).post(API + "routes/import", {"file": SimpleUploadedFile(name, data)})

    def test_a_mission_is_saved_as_a_route_with_its_plan_summary(self):
        res = self.upload(export(body(model="m4e", cameras=["visable"], height=60)))
        self.assertEqual(res.status_code, 201, res.content[:300])
        data = res.json()
        route = routes.get(data["id"])
        self.assertEqual((route.owner, route.name, route.route_type, route.model), (self.user, "Roof North", "area", "m4e"))
        self.assertEqual(route.settings["height"], "60")
        self.assertEqual(data["settings"]["name"], "Roof North")
        self.assertGreater(data["summary"]["photos"], 0)
        self.assertIn("visable", data["summary"]["gsd"])

    def test_an_oblique_mission_has_the_oblique_passes_in_its_summary(self):
        res = self.upload(export(body(height_mode="relativeToStartPoint", collection_mode="oblique", gimbal_pitch=-45)))
        self.assertEqual(res.status_code, 201, res.content[:300])
        self.assertIn("oblique", res.json()["summary"])

    def test_a_mission_over_its_elevation_model_keeps_it_as_the_routes_terrain(self):
        tif, name = dsm()
        for b in (oblique(), body(surface_follow="dsm")):
            with self.subTest(collection=b["collection_mode"]):
                res = self.upload(export(b, dsm=(tif, name)))
                self.assertEqual(res.status_code, 201, res.content[:300])
                data = res.json()
                route = routes.get(data["id"])
                self.assertEqual(route.settings["surface_follow"], "dsm")
                self.assertEqual(route.read_terrain(), tif)
                self.assertEqual({k: data["terrain_info"][k] for k in ("dataset", "undulation", "name")},
                                 {"dataset": "COP30", "undulation": None, "name": name})
        self.assertFalse(routes.get(self.upload(export(body())).json()["id"]).terrain)

    def test_a_refused_file_says_why_and_creates_nothing(self):
        res = self.upload(edited(export(body()), element("smartObliqueEnable", 1)))
        self.assertEqual(res.status_code, 400)
        self.assertIn("Smart Oblique", res.json()["error"])
        res = self.upload(b"hello", name="notes.txt")
        self.assertEqual(res.status_code, 400)
        self.assertIn("not a .kmz", res.json()["error"])
        self.assertEqual(routes.count(), 0)

    def test_a_request_without_a_file_is_refused(self):
        res = self.client.post(API + "routes/import", {})
        self.assertEqual(res.status_code, 400)
        self.assertIn("No file", res.json()["error"])

    def test_an_area_the_planner_cannot_plan_is_refused(self):
        bowtie = "-85.020728,42.103,0 -85.019728,42.104,0 -85.019728,42.103,0 -85.020728,42.104,0"
        res = self.upload(edited(export(body()), (r"<coordinates>[^<]*</coordinates>", "<coordinates>%s</coordinates>" % bowtie)))
        self.assertEqual(res.status_code, 400)
        self.assertIn("polygon", res.json()["error"])
        self.assertEqual(routes.count(), 0)

    def test_anonymous_users_cannot_import(self):
        res = self.upload(export(body()), client=Client())
        self.assertIn(res.status_code, (401, 403))
        self.assertEqual(routes.count(), 0)
