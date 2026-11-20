"""
Tests of the import of LuxODM's routes (luxodm_import.py, routes.restore and the DJI Mission Planner page > Settings
page's "Import routes from LuxODM"): the file LuxODM's manage.py export_routes writes, checked whole, each route
given to the account of its owner's username, with a new id and LuxODM's times.
"""
import base64
import io
import json
import os
import zipfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase

from .. import luxodm_import, routes
from .test_mission_planner_plugin import API, body, terrain_info, terrain_tif

PAGE = "/plugins/mission_planner/settings"
CREATED = "2026-03-02T10:00:00+00:00"
UPDATED = "2026-10-26T15:30:00.123456+00:00"
INFO = dict(terrain_info(), fetched_at=1761490000.0)


def record(luxodm_id=1, owner="testuser", name="Field", route_type="area", model="m4t", settings=None, tif=None,
           info=None, **over):
    r = {"id": luxodm_id, "owner": owner, "name": name, "route_type": route_type, "model": model,
         "settings": {"height": 30} if settings is None else settings,
         "terrain_info": (info or INFO) if tif else {},
         "terrain": base64.b64encode(tif).decode("ascii") if tif else None,
         "created_at": CREATED, "updated_at": UPDATED}
    r.update(over)
    return r


def export(*records, **over):
    data = {"format": "luxodm-routes", "version": 1, "routes": list(records)}
    data.update(over)
    return json.dumps(data).encode()


class ImportTestCase(BootTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.user = User.objects.get(username="testuser")
        self.other = User.objects.get(username="testuser2")

    def tearDown(self):
        for route in routes.all():
            route.delete()
        disable_plugin("mission_planner")

    def run_import(self, content):
        return luxodm_import.import_routes(luxodm_import.read(content))


class TestRestore(ImportTestCase):
    def test_a_restored_route_keeps_its_fields_times_and_terrain(self):
        value = {"name": "Field", "route_type": "slope", "model": "m4e", "settings": {"height": 40},
                 "terrain_info": INFO, "created_at": CREATED, "updated_at": UPDATED}
        route = routes.restore(self.user, value, terrain_tif())
        route = routes.get_for(self.user, route.id)
        self.assertEqual((route.name, route.route_type, route.model, route.settings), ("Field", "slope", "m4e", {"height": 40}))
        self.assertEqual(route.terrain_info, INFO)
        self.assertEqual((route.created_at.isoformat(), route.updated_at.isoformat()), (CREATED, UPDATED))
        self.assertEqual(route.read_terrain(), terrain_tif())
        self.assertTrue(route.terrain.endswith("_" + INFO["name"]))

    def test_a_route_restored_without_terrain_has_no_terrain_info(self):
        value = {"name": "Points", "route_type": "waypoint", "model": "m4t", "settings": {}, "terrain_info": INFO,
                 "created_at": CREATED, "updated_at": UPDATED}
        route = routes.restore(self.user, value)
        self.assertEqual((route.terrain, route.terrain_info, route.read_terrain()), ("", {}, None))

    def test_a_terrain_file_that_cannot_be_written_leaves_no_route(self):
        value = {"name": "Field", "route_type": "area", "model": "m4t", "settings": {}, "terrain_info": INFO,
                 "created_at": CREATED, "updated_at": UPDATED}
        with mock.patch.object(routes.os, "makedirs", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                routes.restore(self.user, value, terrain_tif())
        self.assertEqual(routes.count(), 0)


class TestReadingTheFile(ImportTestCase):
    def refused(self, content, message):
        with self.assertRaisesRegex(luxodm_import.ImportRefused, message):
            luxodm_import.read(content)

    def test_a_file_that_is_not_a_luxodm_export_is_refused(self):
        self.refused(b"not json", "not JSON")
        self.refused(b"\xff\xfe", "not JSON")
        self.refused(b"[]", "not a LuxODM routes export")
        self.refused(export(format="geojson"), "not a LuxODM routes export")
        self.refused(export(version=2), r"version \(2\) is not one this import reads \(1\)")
        self.refused(export(routes={"a": 1}), "no list of routes")

    def test_a_route_that_fails_a_check_is_named_and_refuses_the_file(self):
        for r, message in (
                ("route", "route 1 in the file is not a route"),
                (record(luxodm_id="7"), "route 1 in the file has no id"),
                (record(luxodm_id=True), "route 1 in the file has no id"),
                (record(owner=7), "LuxODM route #1: the owner is not a username"),
                (record(name=" "), "the name is missing"),
                (record(name="x" * 256), "too long"),
                (record(route_type="spiral"), "unknown route type 'spiral'"),
                (record(model="m5t"), "unknown aircraft 'm5t'"),
                (record(settings=[1]), "the settings are not an object"),
                (record(terrain_info=[1]), "the terrain info is not an object"),
                (record(terrain="not base64!"), "the terrain is not a GeoTIFF"),
                (record(terrain=base64.b64encode(b"GIF89a").decode()), "the terrain is not a GeoTIFF"),
                (record(created_at="yesterday"), "created_at is not a time"),
                (record(created_at="2025-02-30T10:00:00+00:00"), "created_at is not a time"),
                (record(updated_at=5), "updated_at is not a time")):
            self.refused(export(r), message)

    def test_a_file_too_large_is_refused_before_it_is_read(self):
        with mock.patch.object(luxodm_import, "MAX_FILE_BYTES", 10):
            self.refused(export(record()), "larger than")

    def test_a_refused_file_imports_nothing_even_its_good_routes(self):
        with self.assertRaises(luxodm_import.ImportRefused):
            self.run_import(export(record(1), record(2, model="m5t")))
        self.assertEqual(routes.count(), 0)

    def test_a_terrain_without_a_name_gets_one(self):
        (_id, _owner, value, tif), = luxodm_import.read(export(record(tif=terrain_tif(), info={"dataset": "COP30"})))
        self.assertEqual(value["terrain_info"]["name"], "terrain.tif")

    def test_missing_times_become_now(self):
        (_id, _owner, value, _tif), = luxodm_import.read(export(record(created_at=None, updated_at=None)))
        self.assertTrue(value["created_at"].startswith("20"))
        self.assertEqual(value["created_at"][:10], value["updated_at"][:10])


class TestImportingRoutes(ImportTestCase):
    def test_each_route_goes_to_the_account_of_its_owners_username(self):
        report = self.run_import(export(
            record(1, name="Area", tif=terrain_tif()),
            record(8, owner="testuser2", name="Points", route_type="waypoint", model="m4e", settings={"waypoints": []})))
        self.assertEqual([(r["luxodm_id"], r["owner"], r["skipped"]) for r in report],
                         [(1, "testuser", None), (8, "testuser2", None)])
        area = routes.get_for(self.user, report[0]["id"])
        points = routes.get_for(self.other, report[1]["id"])
        self.assertEqual((area.name, area.route_type, area.settings, area.terrain_info), ("Area", "area", {"height": 30}, INFO))
        self.assertEqual(area.read_terrain(), terrain_tif())
        self.assertEqual((points.route_type, points.model, points.settings, points.terrain), ("waypoint", "m4e", {"waypoints": []}, ""))
        self.assertEqual(area.updated_at.isoformat(), UPDATED)

    def test_a_route_whose_owner_has_no_account_or_none_is_skipped_and_reported(self):
        report = self.run_import(export(record(1, owner="someone"), record(2, owner=None), record(3)))
        self.assertEqual([r["skipped"] for r in report],
                         ["no account here has the username someone", "it had no owner in LuxODM", None])
        self.assertEqual([r["id"] is None for r in report], [True, True, False])
        self.assertEqual(routes.count(), 1)

    def test_the_routes_list_keeps_luxodms_order(self):
        self.run_import(export(record(1, name="Older", updated_at="2026-01-01T00:00:00+00:00"),
                               record(2, name="Newer", updated_at="2026-09-01T00:00:00+00:00")))
        routes.create(self.user, name="Made here")
        self.assertEqual([r.name for r in routes.list_for(self.user)], ["Made here", "Newer", "Older"])

    def test_importing_the_same_file_again_imports_copies(self):
        content = export(record(1), record(2))
        first = self.run_import(content)
        second = self.run_import(content)
        self.assertEqual(routes.count(), 4)
        self.assertFalse({r["id"] for r in first} & {r["id"] for r in second})

    def test_an_imported_route_opens_in_its_editor_and_exports_with_its_terrain(self):
        report = self.run_import(export(record(20, tif=terrain_tif())))
        new_id = report[0]["id"]
        client = Client()
        client.login(username="testuser", password="test1234")
        self.assertEqual(client.get("/plugins/mission_planner/route/%d" % new_id).status_code, 200)
        self.assertEqual(client.get(API + "routes/%d" % new_id).json()["terrain_info"], INFO)
        res = client.post(API + "export", json.dumps(body(height_mode="realTimeFollowSurface", collection_mode="oblique",
                                                           gimbal_pitch=-45, route_id=new_id)),
                          content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content[:300])
        z = zipfile.ZipFile(io.BytesIO(res.content))
        self.assertEqual(z.read("wpmz/res/dsm/" + INFO["name"]), terrain_tif())

    def test_deleting_an_imported_route_removes_its_terrain_folder(self):
        report = self.run_import(export(record(1, tif=terrain_tif())))
        route = routes.get(report[0]["id"])
        folder = os.path.dirname(route.terrain_path())
        route.delete()
        self.assertFalse(os.path.exists(folder))


class TestTheImportOnTheSettingsPage(ImportTestCase):
    def setUp(self):
        super().setUp()
        self.admin = Client()
        self.admin.login(username="testsuperuser", password="test1234")

    def upload(self, content, client=None):
        return (client or self.admin).post(PAGE, {"action": "import",
                                                  "routes_file": SimpleUploadedFile("routes.json", content)})

    def test_an_import_redirects_to_its_report_once(self):
        res = self.upload(export(record(1, name="Area"), record(2, owner="someone", name="Theirs")))
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res["Location"], PAGE + "?done=imported")
        html = self.admin.get(res["Location"]).content.decode()
        new_id = routes.list_for(self.user)[0].id
        self.assertIn("1 of 2 routes imported.", html)
        self.assertIn('href="/plugins/mission_planner/route/%d"' % new_id, html)
        self.assertIn("#1 Area", html)
        self.assertIn("Skipped: no account here has the username someone", html)
        # reloading the page shows no report and imports nothing again
        again = self.admin.get(res["Location"]).content.decode()
        self.assertNotIn('id="mp-import-report"', again)
        self.assertEqual(routes.count(), 1)

    def test_a_refused_file_says_why_and_imports_nothing(self):
        res = self.upload(export(record(1, model="m5t")))
        self.assertEqual(res.status_code, 400)
        self.assertIn("The file was not imported: LuxODM route #1: unknown aircraft", res.content.decode())
        self.assertEqual(routes.count(), 0)

    def test_an_import_without_a_file_asks_for_one(self):
        res = self.admin.post(PAGE, {"action": "import"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Choose a LuxODM routes export", res.content.decode())

    def test_users_who_are_not_administrators_cannot_import(self):
        user = Client()
        user.login(username="testuser", password="test1234")
        self.assertEqual(self.upload(export(record(1)), client=user).status_code, 403)
        self.assertEqual(routes.count(), 0)

    def test_the_page_shows_the_import_section(self):
        html = self.admin.get(PAGE).content.decode()
        self.assertIn("Import routes from LuxODM", html)
        self.assertIn('enctype="multipart/form-data"', html)
