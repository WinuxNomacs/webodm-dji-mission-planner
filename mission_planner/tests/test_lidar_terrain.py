"""
Tests of an AGL route's terrain from the lidar surface (lidar_terrain.py) and of the API around it. The units are built
by test_lidar's stand-ins (a fake PDAL writing ground at GROUND with a TREE block in the middle of each unit, AWS's
tile from a fake web), GEOID18's shift is a constant SHIFT, and COP30 is a mocked terrain.fetch_terrain.
"""
import json
import os
from unittest import mock

import numpy as np
from django.contrib.auth.models import User
from django.test import Client
from rasterio.io import MemoryFile

from app.plugins import disable_plugin, enable_plugin

from .. import lidar, lidar_terrain, routes
from ..missions import geoid, terrain
from .test_lidar import GROUND, LAT, LON, TREE, Answer, LidarTestCase
from .test_mission_planner_plugin import body

SHIFT = -34.0                   # NAVD88 to the ellipsoid, constant here
COP30 = 150.0                   # the mocked COP30 terrain's (ellipsoidal) height
API = "/api/plugins/mission_planner/"
POINTS = [(LON, LAT), (LON + 0.002, LAT + 0.001)]


def constant_shift(lons, lats, grid=None, epoch=None):
    return np.full(np.shape(lons), SHIFT)


def cop30_tif(b=None, height=COP30):
    """A flat COP30 terrain over the bounds (with room to spare), 1 arc-second cells"""
    west, south, east, north = b or terrain.bounds(POINTS)
    west, south, east, north = west - 0.01, south - 0.01, east + 0.01, north + 0.01
    step = 1 / 3600.0
    w, h = int((east - west) / step) + 1, int((north - south) / step) + 1
    from rasterio.transform import from_origin
    with MemoryFile() as f:
        with f.open(driver="GTiff", width=w, height=h, count=1, dtype="int16", crs="EPSG:4326",
                    transform=from_origin(west, north, step, step)) as d:
            d.write(np.full((h, w), height, dtype="int16"), 1)
        return f.read()


def cop30_info():
    return {"dataset": "COP30", "undulation": -33.5, "bounds": list(terrain.bounds(POINTS)), "name": "wgs84_COP30_N41W080_dem.tif"}


def read(tif):
    with MemoryFile(tif) as m, m.open() as d:
        return d.read(1), d.transform, d.crs, d.dtypes[0]


def aws(height):
    return Answer(200, lidar._png(lidar.encode(np.full((256, 256), height))))


class LidarTerrainCase(LidarTestCase):
    def setUp(self):
        super().setUp()
        self.web.aws = aws(GROUND - 0.5)              # AWS's bare ground, NAVD88: just under the lidar's
        self.units = lidar.units_for(terrain.bounds(POINTS), margin=0)
        self.queued = []
        for p in (mock.patch.object(geoid, "navd88_shift", constant_shift),
                  mock.patch.object(terrain, "fetch_terrain", return_value=(cop30_tif(), cop30_info()))):
            self.cop30 = p.start()
            self.addCleanup(p.stop)
        self.cop30 = terrain.fetch_terrain

    def build_all(self, mode="dsm"):
        for unit in self.units:
            self.build(unit, mode)

    def fetch(self, source="lidar", points=POINTS):
        return lidar_terrain.fetch(points, source, enqueue=self.queued.extend)


class TestLidarTerrain(LidarTerrainCase):
    def test_the_terrain_is_the_lidars_highest_point_in_each_10_m_cell_moved_to_the_ellipsoid(self):
        self.build_all()
        tif, info = self.fetch()
        values, transform, crs, dtype = read(tif)
        self.assertEqual((crs.to_epsg(), dtype), (4326, "int16"))
        self.assertAlmostEqual(transform.a, 1 / 10800.0, places=12)       # 1/3 arc-second
        self.assertAlmostEqual(-transform.e, 1 / 10800.0, places=12)
        # the trees' cells take the tree's height and the others the ground's: a cell the tree's edge crosses is the
        # tree's (the highest point), never a mean of the two
        self.assertEqual(set(np.unique(values)), {GROUND + SHIFT, TREE + SHIFT})
        self.assertEqual(info["dataset"], "Lidar")
        self.assertEqual((info["source"], info["requested"], info["filled"]), ("lidar", "lidar", 0.0))
        self.assertEqual(info["cell_m"], 10.3)
        self.assertTrue(info["name"].startswith("wgs84_LIDAR10M_N41W080"))
        self.assertEqual(sorted(map(tuple, info["units"])), sorted(self.units))
        self.cop30.assert_not_called()

    def test_the_terrain_covers_the_route_and_its_margin(self):
        self.build_all()
        tif, _info = self.fetch()
        _values, transform, _crs, _dtype = read(tif)
        west, south, east, north = terrain.bounds(POINTS)
        self.assertLessEqual(transform.c, west)
        self.assertGreaterEqual(transform.f, north)
        self.assertTrue(terrain.covers(tif, POINTS))

    def test_units_not_built_yet_are_queued_and_the_answer_is_to_ask_again(self):
        with self.assertRaises(lidar_terrain.Building) as caught:
            self.fetch()
        self.assertEqual(sorted(self.queued), sorted(self.units))
        self.assertEqual({st["state"] for st in caught.exception.states}, {"queued"})
        self.cop30.assert_not_called()

        self.build_all()
        _tif, info = self.fetch()
        self.assertEqual(info["dataset"], "Lidar")

    def test_holes_in_the_lidar_are_filled_from_cop30(self):
        self.build(self.units[0])
        for unit in self.units[1:]:
            self.build(unit, mode="empty")              # "none": no lidar there
        if len(self.units) == 1:
            self.skipTest("the route lies in one unit")
        tif, info = self.fetch()
        values, _t, _c, _d = read(tif)
        self.assertEqual(info["dataset"], "Lidar+COP30")
        self.assertGreater(info["filled"], 0)
        self.assertLess(info["filled"], 1)
        self.assertIn(COP30, set(np.unique(values)))
        self.assertIn(GROUND + SHIFT, set(np.unique(values)))
        self.cop30.assert_called_once_with(POINTS)

    def test_a_failure_to_fill_the_holes_fails_the_fetch_as_cop30s_would(self):
        self.build(self.units[0])
        for unit in self.units[1:]:
            self.build(unit, mode="empty")
        if len(self.units) == 1:
            self.skipTest("the route lies in one unit")
        with mock.patch.object(terrain, "fetch_terrain", side_effect=terrain.TerrainError("The terrain service returned an error (503)")):
            with self.assertRaisesRegex(terrain.TerrainError, "503"):
                self.fetch()


class TestFallbacks(LidarTerrainCase):
    def assertCop30(self, result, why):
        tif, info = result
        self.assertEqual(tif, cop30_tif())
        self.assertEqual((info["dataset"], info["source"], info["requested"]), ("COP30", "cop30", "lidar"))
        self.assertIn(why, info["fallback"])

    def test_cop30_chosen_is_cop30_without_a_reason(self):
        tif, info = self.fetch("cop30")
        self.assertEqual(tif, cop30_tif())
        self.assertEqual((info["source"], info["requested"]), ("cop30", "cop30"))
        self.assertNotIn("fallback", info)
        self.assertEqual(self.queued, [])

    def test_an_unknown_source_is_refused(self):
        with self.assertRaisesRegex(terrain.TerrainError, "lidar or cop30"):
            self.fetch("srtm")

    def test_no_lidar_there(self):
        self.build_all(mode="empty")
        self.assertCop30(self.fetch(), "no USGS lidar here")

    def test_a_unit_that_failed_to_build(self):
        self.build_all(mode="fail")
        result = self.fetch()
        self.assertCop30(result, "a lidar unit could not be built")
        self.assertNotIn("secret", result[1]["fallback"])         # PDAL's URL is left out, as in the unit's state

    def test_heights_that_are_not_navd88_meters_are_left_out(self):
        self.build_all()
        self.web.aws = aws(GROUND + 34.0)              # the lidar 34 m under AWS's ground: ellipsoidal heights
        self.assertCop30(self.fetch(), "no USGS lidar in NAVD88 here")
        kept = json.load(open(os.path.join(lidar.unit_folder(self.units[0]), "datum.json")))
        self.assertFalse(kept["ok"])
        self.assertAlmostEqual(kept["offset"], -34.0, delta=0.6)

    def test_the_datum_check_is_kept_until_the_dsm_is_made_again(self):
        self.build_all()
        self.fetch()
        calls = len(self.web.calls)
        self.fetch()
        self.assertEqual(len(self.web.calls), calls)   # AWS's tile not fetched again

    def test_aws_unreachable_for_the_datum_check(self):
        self.build_all()
        self.web.aws = Answer(503)                     # no datum check kept yet: AWS is asked
        self.assertCop30(self.fetch(), "the lidar's heights could not be checked")

    def test_the_geoid18_grid_not_to_be_had(self):
        self.build_all()
        with mock.patch.object(geoid, "navd88_shift", side_effect=geoid.GeoidError("Could not download the geoid grid (ConnectionError)")):
            self.assertCop30(self.fetch(), "the GEOID18 grid could not be had")

    def test_outside_the_conterminous_us(self):
        paris = [(2.3522, 48.8566), (2.3532, 48.8570)]
        with mock.patch.object(terrain, "fetch_terrain", return_value=(cop30_tif(), cop30_info())):
            self.assertCop30(self.fetch(points=paris), "outside the conterminous US")
        self.assertEqual(self.queued, [])

    def test_a_terrain_area_over_4_km2(self):
        big = [(LON, LAT), (LON + 0.03, LAT + 0.02)]
        result = self.fetch(points=big)
        self.assertCop30(result, "lidar is used up to 4 km2")
        self.assertEqual(self.queued, [])

    def test_the_lidar_unavailable(self):
        with mock.patch.object(lidar, "request", side_effect=OSError(28, "No space left on device")):
            self.assertCop30(self.fetch(), "the lidar surface is unavailable")


class TestSatisfies(LidarTestCase):
    def test_a_kept_terrain_serves_the_source_it_was_made_for(self):
        self.assertTrue(lidar_terrain.satisfies({"requested": "lidar", "source": "cop30"}, "lidar"))   # a fallback
        self.assertFalse(lidar_terrain.satisfies({"requested": "lidar"}, "cop30"))
        self.assertTrue(lidar_terrain.satisfies({"dataset": "COP30"}, "cop30"))      # kept before the choice existed
        self.assertFalse(lidar_terrain.satisfies({"dataset": "COP30"}, "lidar"))
        self.assertTrue(lidar_terrain.satisfies({"dataset": "ASTGTMV003", "imported": True}, "lidar"))
        self.assertFalse(lidar_terrain.satisfies(None, "lidar"))


class TestLidarTerrainApi(LidarTerrainCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.user = User.objects.get(username="testuser")
        p = mock.patch.object(lidar, "_enqueue", self.queued.extend)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        for route in routes.all():
            route.delete()
        disable_plugin("mission_planner")
        super().tearDown()

    def post(self, path, data):
        return self.client.post(API + path, json.dumps(data), content_type="application/json")

    def test_waypoint_ground_heights_wait_for_the_lidar_then_come_from_it(self):
        route = routes.create(owner=self.user, name="Tower", route_type="waypoint")
        points = [[LAT, LON], [LAT + 0.001, LON + 0.002]]
        res = self.post("routes/%d/point-elevations" % route.id, {"points": points})
        self.assertEqual(res.status_code, 202, res.content[:300])
        data = res.json()
        self.assertTrue(data["building"])
        self.assertEqual((data["done"], data["units"]), (0, len(data["states"])))
        self.assertTrue(self.queued)

        for unit in {tuple(u) for u in self.queued}:
            self.build(unit)
        res = self.post("routes/%d/point-elevations" % route.id, {"points": points})
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertTrue(all(e in (GROUND + SHIFT, TREE + SHIFT) for e in res.json()["elevations"]))
        route.refresh_from_db()
        self.assertEqual((route.terrain_info["dataset"], route.terrain_info["requested"]), ("Lidar", "lidar"))

        # COP30 chosen afterwards: the lidar terrain does not serve it, COP30 is fetched
        with mock.patch.object(terrain, "fetch_terrain", return_value=(cop30_tif(), cop30_info())) as fetch:
            res = self.post("routes/%d/point-elevations" % route.id, {"points": points, "terrain_source": "cop30"})
        self.assertEqual(res.json()["elevations"], [COP30, COP30])
        fetch.assert_called_once()

    def test_an_unknown_terrain_source_is_refused(self):
        route = routes.create(owner=self.user, name="Tower", route_type="waypoint")
        res = self.post("routes/%d/point-elevations" % route.id, {"points": [[LAT, LON]], "terrain_source": "srtm"})
        self.assertEqual(res.status_code, 400)

    def test_an_area_route_fetches_lidar_terrain_and_the_export_asks_again_for_another_source(self):
        route = routes.create(owner=self.user, name="Field", route_type="area")
        d = 0.0008
        polygon = [[LON - d, LAT - d], [LON + d, LAT - d], [LON + d, LAT + d], [LON - d, LAT + d]]
        b = body(polygon=polygon, height_mode="realTimeFollowSurface", surface_follow="dsm", route_id=route.id)
        res = self.post("routes/%d/terrain" % route.id, b)
        self.assertEqual(res.status_code, 202, res.content[:300])
        for unit in {tuple(u) for u in self.queued}:
            self.build(unit)
        res = self.post("routes/%d/terrain" % route.id, b)
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res.json()["dataset"], "Lidar")

        export = self.post("export", dict(b, terrain_source="lidar"))
        self.assertEqual(export.status_code, 200, export.content[:300])
        self.assertEqual(self.post("export", dict(b, terrain_source="cop30")).status_code, 409)
        self.assertEqual(self.post("export", b).status_code, 200)          # an older page: the kept terrain
        self.assertEqual(self.post("export", dict(b, terrain_source="srtm")).status_code, 400)
