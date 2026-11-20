"""
Tests of plain KML (missions/kml.py, Phase 15e): a polygon, line or points read into a new route, the import endpoint
taking them, and a route written out as KML.
"""
import io
import json
import zipfile
from xml.etree import ElementTree as ET

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase

from .. import routes
from ..missions import kml
from ..missions.kmz_import import KmzImportError
from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase
from . import test_mission_kmz_import as area_kmz

API = "/api/plugins/mission_planner/"
NS = "http://www.opengis.net/kml/2.2"


def document(body, ns=NS):
    return ('<?xml version="1.0" encoding="UTF-8"?><kml%s><Document><name>Survey site</name>%s</Document></kml>'
            % (' xmlns="%s"' % ns if ns else "", body)).encode()


POLYGON = ("<Placemark><name>North field</name><Polygon><outerBoundaryIs><LinearRing><coordinates>"
           "-85.020828,42.1037,0 -85.021528,42.1037,0 -85.021628,42.1031,0 -85.020928,42.1031,0 -85.020828,42.1037,0"
           "</coordinates></LinearRing></outerBoundaryIs><innerBoundaryIs><LinearRing><coordinates>"
           "-85.021228,42.1035 -85.021328,42.1035 -85.021328,42.1034</coordinates></LinearRing></innerBoundaryIs></Polygon></Placemark>")
LINE = "<Placemark><name>Canal</name><LineString><coordinates>-85.013728,42.10 -85.003728,42.11 -84.993728,42.11</coordinates></LineString></Placemark>"
POINTS = "".join("<Placemark><name>P%d</name><Point><coordinates>%s,42.1,250</coordinates></Point></Placemark>" % (i, lon)
                 for i, lon in enumerate((-85.013728, -85.003728, -84.993728)))


def kmz(content, name="doc.kml"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(name, content)
    return out.getvalue()


class TestReading(SimpleTestCase):
    def test_a_polygon_is_an_area_route_of_its_outer_boundary(self):
        kind, s = kml.read_kml(document(POLYGON), "file")
        self.assertEqual(kind, "area")
        self.assertEqual(s["name"], "North field")
        self.assertEqual(s["polygon"], [[-85.020828, 42.1037], [-85.021528, 42.1037], [-85.021628, 42.1031], [-85.020928, 42.1031]])

    def test_a_line_in_a_kmz_is_a_linear_route(self):
        kind, s = kml.read_kml(kmz(document(LINE)), "file")
        self.assertEqual((kind, s["name"], s["line"]), ("linear", "Canal", [[-85.013728, 42.1], [-85.003728, 42.11], [-84.993728, 42.11]]))

    def test_points_are_a_waypoint_route_in_the_file_s_order_named_after_the_document(self):
        kind, s = kml.read_kml(document(POINTS, ns=None), "file")
        self.assertEqual((kind, s["name"]), ("waypoint", "Survey site"))
        self.assertEqual([(p["lon"], p["lat"], p["height"]) for p in s["points"]], [(-85.013728, 42.1, None), (-85.003728, 42.1, None), (-84.993728, 42.1, None)])

    def test_the_polygon_comes_first_then_the_line(self):
        self.assertEqual(kml.read_kml(document(POINTS + LINE + POLYGON), "f")[0], "area")
        self.assertEqual(kml.read_kml(document(POINTS + LINE), "f")[0], "linear")

    def test_the_file_name_names_a_route_the_file_does_not(self):
        data = b'<kml xmlns="%s"><Placemark><LineString><coordinates>1,2 3,4</coordinates></LineString></Placemark></kml>' % NS.encode()
        self.assertEqual(kml.read_kml(data, "Roads")[1]["name"], "Roads")

    def test_what_cannot_be_a_route_is_refused(self):
        cases = [
            (document("<Placemark><Point><coordinates>1,2</coordinates></Point></Placemark>"), "no polygon, line or two or more points"),
            (document(LINE.replace("-85.003728,42.11 -84.993728,42.11", "")), "fewer than 2 points"),
            (document(LINE.replace("-85.003728,42.11", "-85.003728,91")), "outside the map"),
            (document(LINE.replace("-85.003728,42.11", "x,y")), "not a longitude and latitude"),
            (document("<Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>%s</coordinates></LinearRing></outerBoundaryIs>"
                      "</Polygon></Placemark>" % " ".join("%f,42" % (i / 1000) for i in range(201))), "too many corners"),
            (b'<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY a "b">]><kml>&a;</kml>', "not valid XML"),
            (b"<kml><Document>", "not valid XML"),
            (kmz(b"x", name="notes.txt"), "holds no .kml"),
            (area_kmz.damaged(kmz(document(LINE)), flags=1), "cannot be read"),
            (area_kmz.damaged(kmz(document(LINE)), method=99), "cannot be read"),
            (area_kmz.damaged(kmz(document(LINE)), corrupt="doc.kml"), "cannot be read"),
        ]
        for data, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(KmzImportError, message):
                    kml.read_kml(data, "f")

    def test_a_dji_mission_is_not_plain_kml(self):
        self.assertFalse(kml.is_kml(area_kmz.export(area_kmz.body())))
        self.assertTrue(kml.is_kml(kmz(document(LINE))))
        self.assertTrue(kml.is_kml(b"\xef\xbb\xbf  " + document(LINE)))
        self.assertFalse(kml.is_kml(b"not a file we know"))


class TestWriting(SimpleTestCase):
    def test_the_shape_is_draped_and_the_path_at_its_heights(self):
        text = kml.write_kml("Field & co", ("polygon", [(1.0, 2.0), (3.0, 2.0), (3.0, 4.0)]),
                             {"reference": "sea", "paths": [[[1, 2, 300.5], [3, 4, 301.0]]]})
        root = ET.fromstring(text)
        names = [e.text for e in root.iter("{%s}name" % NS)]
        self.assertEqual(names, ["Field & co", "Route", "Area", "Flight path", "Flight path"])
        coords = [e.text for e in root.iter("{%s}coordinates" % NS)]
        self.assertEqual(coords, ["1,2 3,2 3,4 1,2", "1,2,300.5 3,4,301"])
        self.assertEqual([e.text for e in root.iter("{%s}altitudeMode" % NS)], ["absolute"])

    def test_without_heights_above_sea_level_the_path_is_drawn_above_the_ground(self):
        text = kml.write_kml("R", ("points", [(1, 2), (3, 4)]), {"reference": "takeoff", "paths": [[[1, 2, 60], [3, 4, 60]]]})
        self.assertIn("<altitudeMode>relativeToGround</altitudeMode>", text)
        self.assertIn("Heights above the takeoff point", text)
        self.assertEqual(text.count("<Point>"), 2)


class TestEndpoints(BootTestCase):
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

    def upload(self, data, name, model=None):
        fields = {"file": SimpleUploadedFile(name, data)}
        if model:
            fields["model"] = model
        return self.client.post(API + "routes/import", fields)

    def test_a_kml_polygon_is_imported_as_an_area_route_for_the_model_chosen(self):
        res = self.upload(document(POLYGON), "site.kml", model="m4e")
        self.assertEqual(res.status_code, 201, res.content[:300])
        route = routes.get(res.json()["id"])
        self.assertEqual((route.name, route.route_type, route.model), ("North field", "area", "m4e"))
        self.assertEqual((route.settings["lens_visible"], route.settings["lens_ir"]), ("true", "false"))
        self.assertEqual(len(route.settings["polygon"]), 4)

    def test_a_kmz_line_is_imported_as_a_linear_route_on_the_m4t_by_default(self):
        res = self.upload(kmz(document(LINE)), "canal.kmz")
        self.assertEqual(res.status_code, 201, res.content[:300])
        self.assertEqual((res.json()["route_type"], res.json()["model"], res.json()["settings"]["lens_ir"]), ("linear", "m4t", "true"))

    def test_a_kml_import_is_refused_with_a_reason_and_creates_nothing(self):
        self.assertIn("no polygon, line", self.upload(document(""), "empty.kml").json()["error"])
        self.assertIn("Unknown aircraft", self.upload(document(LINE), "c.kml", model="m9").json()["error"])
        self.assertEqual(routes.count(), 0)

    def test_a_route_downloads_as_kml(self):
        body = dict(area_kmz.body(height_mode="relativeToStartPoint"), route_type="area", name="Live area")
        res = self.client.post(API + "kml", json.dumps(body), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res["Content-Disposition"], 'attachment; filename="Live_area.kml"')
        root = ET.fromstring(res.content)
        names = [e.text for e in root.iter("{%s}name" % NS)]
        self.assertEqual(names[:4], ["Live area", "Route", "Area", "Flight path"])
        self.assertIn("Flight path", names)
        line = dict(area_kmz.body(), route_type="linear", line=[[-85.013728, 42.1], [-85.012728, 42.1]], left_extend=20, right_extend=20)
        self.assertIn(b"Center line", self.client.post(API + "kml", json.dumps(line), content_type="application/json").content)
        self.assertEqual(self.client.post(API + "kml", json.dumps({"route_type": "area"}), content_type="application/json").status_code, 400)
