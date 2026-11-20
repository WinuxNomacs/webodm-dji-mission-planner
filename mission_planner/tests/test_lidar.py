"""
Tests of the lidar surface of the 3D view (lidar.py, the lidar/surface and lidar/tiles API, the settings page's size
and clear). Nothing is downloaded and PDAL never runs: the index and AWS's tiles come from lidar._get, replaced, and
lidar.PDAL points at a stand-in script that writes a DSM, fails, hangs, ignores SIGTERM or writes a broken file, as
the environment variable FAKE_PDAL says. Every test has its own lidar folder.
"""
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from unittest import mock

import numpy as np
import requests
from django.test import Client

from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase

from .. import lidar

API = "/api/plugins/mission_planner/"
SETTINGS = "/plugins/mission_planner/settings"
LON, LAT = -79.528168, 41.4898          # the oblique AGL sample
AWS_HEIGHT = 210.0
GROUND, TREE = 214.0, 240.0           # the stand-in DSM: ground, with a tree block in the middle of each unit

FAKE_PDAL = r'''#!%(python)s
import json, os, signal, sys, time
mode = os.environ.get("FAKE_PDAL", "dsm")
pipeline = json.loads(sys.stdin.read())
log = os.environ.get("FAKE_PDAL_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps(pipeline) + "\n")
if mode == "fail":
    sys.stderr.write("(pdal pipeline readers.ept Error) Could not read https://example.com/ept.json?secret=1\n")
    sys.exit(1)
if mode == "hang":
    time.sleep(60)
if mode == "ignore_term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open(os.environ["FAKE_PDAL_STARTED"], "w") as f:
        f.write(str(os.getpid()))
    time.sleep(60)
w = pipeline[-1]
if mode == "broken":
    with open(w["filename"], "wb") as f:
        f.write(b"not a tiff")
    sys.exit(0)
import numpy as np, rasterio
from rasterio.transform import from_origin
n, cell = w["width"], w["resolution"]
values = np.full((n, n), %(ground)r, "float32")
if mode == "empty":
    values[:] = -9999
else:
    values[n // 2 - 50:n // 2 + 50, n // 2 - 50:n // 2 + 50] = %(tree)r
with rasterio.open(w["filename"], "w", driver="GTiff", width=n, height=n, count=1, dtype="float32", crs="EPSG:3857",
                   transform=from_origin(w["origin_x"], w["origin_y"] + n * cell, cell, cell), nodata=-9999) as d:
    d.write(values, 1)
'''


def index_geojson(*projects):
    features = [{"type": "Feature", "properties": {"name": name, "id": i, "count": 1, "url": "https://lidar.example/%s/ept.json" % name},
                 "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}}
                for i, (name, (w, s, e, n)) in enumerate(projects)]
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


INDEX = index_geojson(("USGS_LPC_PA_Old_2014_LAS_2016", (-80.0, 41.0, -79.0, 42.0)),
                      ("USGS_LPC_PA_West_2017_LAS_2019", (-80.0, 41.0, -79.0, 42.0)),
                      ("USGS_LPC_WI_Elsewhere_2021", (-90.0, 43.0, -89.0, 44.0)))


def aws_png():
    return lidar._png(lidar.encode(np.full((256, 256), AWS_HEIGHT)))


class Answer:
    def __init__(self, status=200, content=b""):
        self.status_code, self.content = status, content

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]


class Web:
    """Stands in for lidar._get: the index and AWS's tiles, or failures on request"""
    def __init__(self):
        self.index, self.aws, self.calls = Answer(200, INDEX), Answer(200, aws_png()), []

    def __call__(self, url, stream=False):
        self.calls.append(url)
        answer = self.index if url == lidar.INDEX_URL else self.aws
        if isinstance(answer, Exception):
            raise answer
        return answer


def unit_at(lon, lat):
    x, y = lidar.to_mercator(lon, lat)
    s = lidar.tile_size(lidar.UNIT_ZOOM)
    return int((x + lidar.HALF) // s), int((lidar.HALF - y) // s)


def tile_heights(z, x, y):
    with open(lidar.tile_path(z, x, y), "rb") as f:
        return lidar.decode(lidar._read_png(f.read()))


class LidarTestCase(BootTestCase):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.web = Web()
        script = os.path.join(self.folder, "fake-pdal")
        with open(script, "w") as f:
            f.write(FAKE_PDAL % {"python": sys.executable, "ground": GROUND, "tree": TREE})
        os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.folder, "pdal.log")
        for p in (mock.patch.object(lidar, "root", return_value=os.path.join(self.folder, "lidar")),
                  mock.patch.object(lidar, "_get", self.web),
                  mock.patch.object(lidar, "PDAL", script),
                  mock.patch.dict(os.environ, {"FAKE_PDAL": "dsm", "FAKE_PDAL_LOG": self.log})):
            p.start()
            self.addCleanup(p.stop)
        lidar._index_cache.update(mtime=None, entries=None)
        self.unit = unit_at(LON, LAT)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)
        super().tearDown()

    def pipelines(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def build(self, unit=None, mode="dsm"):
        with mock.patch.dict(os.environ, {"FAKE_PDAL": mode}):
            lidar.build_units([unit or self.unit])
        return lidar.read_state(unit or self.unit)


class TestUnits(LidarTestCase):
    def test_a_route_needs_the_units_within_the_margin_around_it(self):
        units = lidar.units_for([LON, LAT, LON, LAT])
        self.assertIn(self.unit, units)
        self.assertLessEqual(len(units), 4)
        left, bottom, right, top = lidar.tile_bounds(lidar.UNIT_ZOOM, *self.unit)
        # a point just inside the unit's west edge also needs the unit west of it (within 200 m)
        lon, lat = lidar.to_lonlat(left + 10, (bottom + top) / 2)
        self.assertIn((self.unit[0] - 1, self.unit[1]), lidar.units_for([lon, lat, lon, lat]))
        lon, lat = lidar.to_lonlat((left + right) / 2, (bottom + top) / 2)
        self.assertEqual(lidar.units_for([lon, lat, lon, lat]), [self.unit])

    def test_an_area_of_more_than_twelve_units_is_refused_as_too_large(self):
        with self.assertRaises(lidar.TooLarge):
            lidar.units_for([LON - 0.05, LAT - 0.05, LON + 0.05, LAT + 0.05])
        self.assertLessEqual(len(lidar.units_for([LON - 0.01, LAT - 0.005, LON + 0.01, LAT + 0.005])), lidar.MAX_UNITS)

    def test_bounds_that_are_not_west_south_east_north_are_refused(self):
        for bounds in ([LON, LAT, LON - 1, LAT], [0, 89, 1, 89.5], [-181, 0, 0, 1]):
            with self.assertRaises(lidar.LidarError):
                lidar.units_for(bounds)

    def test_every_tile_of_zoom_15_to_18_lies_in_one_unit(self):
        x, y = self.unit
        self.assertEqual(lidar.tile_unit(15, x, y), (x, y))
        self.assertEqual(lidar.tile_unit(18, x * 8 + 7, y * 8), (x, y))


class TestRequest(LidarTestCase):
    def test_a_request_queues_the_missing_units_once(self):
        queued = []
        units = [self.unit, (self.unit[0] + 1, self.unit[1])]
        answer = lidar.request(units, enqueue=queued.append)
        self.assertEqual(queued, [units])
        self.assertEqual([u["state"] for u in answer], ["queued", "queued"])
        lidar.request(units, enqueue=queued.append)            # asked again while queued: nothing queued again
        self.assertEqual(len(queued), 1)

    def test_a_queue_that_cannot_be_reached_fails_the_units_with_a_message(self):
        def down(units):
            raise ConnectionError("broker down")
        answer = lidar.request([self.unit], enqueue=down)
        self.assertEqual(answer[0]["state"], "failed")
        self.assertIn("could not be queued", answer[0]["message"])

    def test_a_failed_unit_is_retried_only_after_ten_minutes(self):
        lidar.write_state(self.unit, "failed", "it broke")
        queued = []
        lidar.request([self.unit], enqueue=queued.append)
        self.assertEqual(queued, [])
        with mock.patch.object(lidar.time, "time", return_value=time.time() + lidar.RETRY_AFTER + 1):
            lidar.request([self.unit], enqueue=queued.append)
        self.assertEqual(queued, [[self.unit]])

    def test_a_build_whose_worker_died_is_taken_over_once_stale(self):
        lidar.write_state(self.unit, "building")
        queued = []
        lidar.request([self.unit], enqueue=queued.append)
        self.assertEqual(queued, [])
        with mock.patch.object(lidar.time, "time", return_value=time.time() + lidar.STALE_AFTER + 1):
            lidar.request([self.unit], enqueue=queued.append)
        self.assertEqual(queued, [[self.unit]])

    def test_a_state_that_does_not_read_is_set_aside_and_the_unit_built_again(self):
        path = os.path.join(lidar.unit_folder(self.unit), "status.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write("{not json")
        queued = []
        self.assertEqual(lidar.request([self.unit], enqueue=queued.append)[0]["state"], "queued")
        self.assertTrue(os.path.exists(path + ".bad"))
        self.assertEqual(queued, [[self.unit]])

    def test_the_worker_job_builds_the_units_of_the_module_it_is_given(self):
        with mock.patch.object(lidar, "build_units") as build:
            lidar.build_job(lidar.__name__, [[1, 2]])
        build.assert_called_once_with([(1, 2)])


class TestBuild(LidarTestCase):
    def test_a_unit_is_built_from_the_newest_lidar_covering_it(self):
        st = self.build()
        self.assertEqual(st["state"], "done")
        self.assertEqual(st["message"], "USGS_LPC_PA_West_2017_LAS_2019")
        reader = self.pipelines()[0][0]
        self.assertEqual(reader["filename"], "https://lidar.example/USGS_LPC_PA_West_2017_LAS_2019/ept.json")
        k = lidar.scale(LAT)
        self.assertAlmostEqual(reader["resolution"], lidar.READ_RESOLUTION * k, delta=0.01)

    def test_a_newer_project_touching_only_a_corner_does_not_beat_one_covering_the_whole_unit(self):
        left, bottom, right, top = lidar.tile_bounds(lidar.UNIT_ZOOM, *self.unit)
        west, south = lidar.to_lonlat(left, bottom)
        east, north = lidar.to_lonlat(right, top)
        corner = (east - (east - west) * 0.2, north - (north - south) * 0.2, east + 1, north + 1)
        self.web.index = Answer(200, index_geojson(("USGS_LPC_PA_Whole_2017", (-80.0, 41.0, -79.0, 42.0)),
                                                   ("USGS_LPC_PA_Corner_2022", corner)))
        self.assertEqual(lidar.project_for(self.unit)[0], "USGS_LPC_PA_Whole_2017")

    def test_of_projects_covering_the_whole_unit_the_newest_wins(self):
        self.assertEqual(lidar.project_for(self.unit)[0], "USGS_LPC_PA_West_2017_LAS_2019")

    def test_its_tiles_of_zoom_15_to_18_show_the_lidar_inside_and_fade_into_aws_at_unbuilt_edges(self):
        self.build()
        x, y = self.unit
        count = sum(1 for z in lidar.TILE_ZOOMS for tx in range(x << (z - 15), (x + 1) << (z - 15))
                    for ty in range(y << (z - 15), (y + 1) << (z - 15)) if lidar.tile_path(z, tx, ty))
        self.assertEqual(count, 1 + 4 + 16 + 64)
        h = tile_heights(15, x, y)
        self.assertAlmostEqual(h[128, 128], TREE, delta=0.1)            # the tree block in the middle
        self.assertAlmostEqual(h[64, 64], GROUND, delta=0.1)            # lidar ground inside
        self.assertAlmostEqual(h[0, 128], AWS_HEIGHT, delta=0.5)        # the edge: AWS's ground (no neighbour built)
        corner = tile_heights(18, x * 8, y * 8)
        self.assertAlmostEqual(corner[0, 0], AWS_HEIGHT, delta=0.5)
        self.assertGreater(corner[255, 255], AWS_HEIGHT + 2)            # fading in, 40 m inside

    def test_a_neighbour_built_later_meets_the_unit_lidar_to_lidar(self):
        self.build()
        east = (self.unit[0] + 1, self.unit[1])
        self.assertAlmostEqual(tile_heights(15, *self.unit)[128, 255], AWS_HEIGHT, delta=0.5)
        self.assertEqual(self.build(east)["state"], "done")
        self.assertAlmostEqual(tile_heights(15, *self.unit)[128, 255], GROUND, delta=0.5)   # made again
        self.assertAlmostEqual(tile_heights(15, *east)[128, 0], GROUND, delta=0.5)
        self.assertAlmostEqual(tile_heights(15, *self.unit)[0, 128], AWS_HEIGHT, delta=0.5)  # north: still none

    def test_a_unit_no_lidar_covers_is_none(self):
        far = unit_at(-100.0, 35.0)
        self.assertEqual(self.build(far)["state"], "none")
        self.assertEqual(self.pipelines(), [])
        self.assertIsNone(lidar.tile_path(15, *far))

    def test_a_unit_where_the_lidar_has_no_points_is_none(self):
        self.assertEqual(self.build(mode="empty")["state"], "none")
        self.assertFalse(os.path.exists(os.path.join(lidar.unit_folder(self.unit), "dsm.tif")))

    def test_pdal_failing_fails_the_unit_with_its_message_without_urls(self):
        st = self.build(mode="fail")
        self.assertEqual(st["state"], "failed")
        self.assertIn("Could not read", st["message"])
        self.assertNotIn("example.com", st["message"])
        self.assertNotIn("secret", st["message"])

    def test_pdal_overrunning_its_deadline_is_stopped_and_fails_the_unit(self):
        with mock.patch.object(lidar, "PDAL_DEADLINE", 1.0):
            started = time.monotonic()
            st = self.build(mode="hang")
        self.assertEqual(st["state"], "failed")
        self.assertIn("longer than", st["message"])
        self.assertLess(time.monotonic() - started, 15)

    def test_pdal_ignoring_sigterm_is_killed(self):
        started_flag = os.path.join(self.folder, "started")
        with mock.patch.object(lidar, "PDAL_DEADLINE", 2.0), mock.patch.object(lidar, "KILL_GRACE", 1.0), \
                mock.patch.dict(os.environ, {"FAKE_PDAL_STARTED": started_flag}):
            started = time.monotonic()
            st = self.build(mode="ignore_term")
        with open(started_flag) as f:
            pid = int(f.read())
        self.assertEqual(st["state"], "failed")
        self.assertLess(time.monotonic() - started, 15)
        with self.assertRaises(ProcessLookupError):     # killed, and reaped
            os.kill(pid, 0)

    def test_pdal_that_cannot_be_started_fails_the_unit(self):
        with mock.patch.object(lidar, "PDAL", os.path.join(self.folder, "no-such-pdal")):
            st = self.build()
        self.assertEqual(st["state"], "failed")
        self.assertIn("could not be started", st["message"])

    def test_a_dsm_that_does_not_read_fails_the_unit(self):
        st = self.build(mode="broken")
        self.assertEqual(st["state"], "failed")
        self.assertIn("no readable DSM", st["message"])
        self.assertEqual([n for n in os.listdir(lidar.unit_folder(self.unit)) if n.startswith(".build-")], [])

    def test_a_full_disk_fails_the_unit_and_leaves_no_work_folder(self):
        real = os.replace

        def full(src, dst):
            if dst.endswith("dsm.tif"):
                raise OSError(28, "No space left on device")
            return real(src, dst)
        with mock.patch.object(lidar.os, "replace", side_effect=full):
            st = self.build()
        self.assertEqual(st["state"], "failed")
        self.assertIn("disk is full", st["message"])
        self.assertEqual([n for n in os.listdir(lidar.unit_folder(self.unit)) if n.startswith(".build-")], [])

    def test_aws_unreachable_fails_the_unit(self):
        self.web.aws = requests.ConnectionError("down")
        st = self.build()
        self.assertEqual(st["state"], "failed")
        self.assertIn("AWS Terrain Tiles", st["message"])
        self.web.aws = Answer(503)
        self.assertIn("503", self.build()["message"])

    def test_one_unit_failing_does_not_stop_the_next(self):
        far = unit_at(-100.0, 35.0)
        with mock.patch.dict(os.environ, {"FAKE_PDAL": "fail"}):
            lidar.build_units([self.unit, far])
        self.assertEqual(lidar.read_state(self.unit)["state"], "failed")
        self.assertEqual(lidar.read_state(far)["state"], "none")

    def test_a_done_unit_whose_dsm_is_gone_reads_as_never_built(self):
        self.build()
        os.remove(os.path.join(lidar.unit_folder(self.unit), "dsm.tif"))
        self.assertIsNone(lidar.read_state(self.unit))
        self.assertIsNone(lidar.tile_path(15, *self.unit))


class TestIndex(LidarTestCase):
    def test_the_index_is_downloaded_once_and_reused(self):
        self.build()
        self.build((self.unit[0] + 1, self.unit[1]))
        self.assertEqual(self.web.calls.count(lidar.INDEX_URL), 1)

    def test_an_index_older_than_thirty_days_is_refreshed_and_a_failed_refresh_keeps_it(self):
        self.build()
        path = os.path.join(lidar.root(), "index", "resources.geojson")
        old = time.time() - lidar.INDEX_MAX_AGE - 10
        os.utime(path, (old, old))
        self.web.index = requests.ConnectionError("down")
        self.assertEqual(self.build((self.unit[0] + 1, self.unit[1]))["state"], "done")
        self.assertEqual(self.web.calls.count(lidar.INDEX_URL), 2)

    def test_with_no_index_and_none_to_download_the_unit_fails_saying_so(self):
        self.web.index = Answer(500)
        st = self.build()
        self.assertEqual(st["state"], "failed")
        self.assertIn("lidar index unavailable", st["message"])

    def test_an_index_that_is_not_one_is_refused_and_not_kept(self):
        self.web.index = Answer(200, b"<html>rate limited</html>")
        self.assertIn("does not read", self.build()["message"])
        self.assertFalse(os.path.exists(os.path.join(lidar.root(), "index", "resources.geojson")))

    def test_an_index_larger_than_the_cap_is_refused(self):
        with mock.patch.object(lidar, "INDEX_MAX_BYTES", 100):
            self.assertIn("larger than", self.build()["message"])

    def test_a_saved_index_that_does_not_read_is_set_aside(self):
        self.build()
        path = os.path.join(lidar.root(), "index", "resources.geojson")
        with open(path, "w") as f:
            f.write("garbage")
        lidar._index_cache.update(mtime=None, entries=None)
        self.assertEqual(self.build((self.unit[0] + 1, self.unit[1]))["state"], "failed")
        self.assertTrue(os.path.exists(path + ".bad"))


class TestClear(LidarTestCase):
    def test_clearing_removes_the_units_but_not_the_index(self):
        self.build()
        built, size = lidar.usage()
        self.assertEqual(built, 1)
        self.assertGreater(size, 0)
        self.assertTrue(lidar.clear())
        self.assertEqual(lidar.usage()[0], 0)
        self.assertTrue(os.path.exists(os.path.join(lidar.root(), "index", "resources.geojson")))

    def test_clearing_is_refused_while_a_unit_is_building(self):
        self.build()
        lidar.write_state((self.unit[0] + 1, self.unit[1]), "building")
        self.assertFalse(lidar.clear())
        self.assertEqual(lidar.usage()[0], 1)


class TestCap(LidarTestCase):
    """The lidar folder is kept under MAX_BYTES (5 GB, decided with the user 2026-11-19): past it, the units least
    recently asked for are removed, never one queued or building"""
    def units(self):
        return [self.unit, (self.unit[0] + 3, self.unit[1]), (self.unit[0] + 6, self.unit[1])]

    def built(self, now):
        units = self.units()
        for n, unit in enumerate(units):
            self.assertEqual(self.build(unit)["state"], "done")
            lidar.mark_used([unit], now - 300 + n * 100)       # the first used longest ago
        return units

    def test_a_request_records_when_each_unit_was_used(self):
        before = time.time()
        lidar.request(self.units(), enqueue=lambda units: None)
        self.assertTrue(all(lidar.last_used(u) >= before - 1 for u in self.units()))

    def test_past_the_cap_the_least_recently_used_units_are_removed(self):
        oldest, middle, newest = self.built(time.time())
        size = lidar.usage()[1]
        with mock.patch.object(lidar, "MAX_BYTES", size - 1):
            lidar.evict()
        self.assertEqual([lidar.read_state(u) is None for u in (oldest, middle, newest)], [True, False, False])
        self.assertFalse(os.path.exists(lidar.unit_folder(oldest)))
        self.assertLessEqual(lidar.usage()[1], size - 1)
        self.assertEqual(lidar.usage()[0], 2)

    def test_a_unit_queued_or_building_is_never_removed(self):
        oldest, middle, newest = self.built(time.time())
        lidar.write_state(oldest, "building")
        with mock.patch.object(lidar, "MAX_BYTES", lidar.usage()[1] - 1):
            lidar.evict()
        self.assertEqual(lidar.read_state(oldest)["state"], "building")
        self.assertIsNone(lidar.read_state(middle))
        self.assertEqual(lidar.read_state(newest)["state"], "done")

    def test_a_build_removes_old_units_past_the_cap_but_never_those_it_built(self):
        oldest, middle, newest = self.built(time.time())
        fresh = (self.unit[0] + 9, self.unit[1])
        lidar.mark_used([fresh], time.time() - 1000)            # asked for long ago, built now
        with mock.patch.object(lidar, "MAX_BYTES", 1):
            self.build(fresh)
        self.assertEqual(lidar.read_state(fresh)["state"], "done")
        self.assertEqual([lidar.read_state(u) for u in (oldest, middle, newest)], [None, None, None])

    def test_the_size_is_read_from_each_unit_s_record_not_by_walking_its_tiles(self):
        self.built(time.time())
        walked = sum(os.path.getsize(os.path.join(d, f)) for d, _, files in os.walk(lidar.root()) for f in files)
        with mock.patch.object(lidar.os, "walk", side_effect=AssertionError("walked")):
            built, size = lidar.usage()
        self.assertEqual(built, 3)
        self.assertAlmostEqual(size, walked, delta=walked * 0.01)

    def test_a_unit_built_before_sizes_were_recorded_is_walked_once(self):
        self.built(time.time())
        os.remove(os.path.join(lidar.unit_folder(self.unit), "usage.json"))
        expected = lidar.usage()[1]
        self.assertTrue(os.path.exists(os.path.join(lidar.unit_folder(self.unit), "usage.json")))
        with mock.patch.object(lidar.os, "walk", side_effect=AssertionError("walked")):
            self.assertEqual(lidar.usage()[1], expected)


class TestLidarApi(LidarTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.bounds = [LON, LAT, LON, LAT]

    def tearDown(self):
        disable_plugin("mission_planner")
        super().tearDown()

    def test_anonymous_users_are_refused(self):
        self.assertIn(Client().get(API + "lidar/surface", {"bounds": "1,2,3,4"}).status_code, (401, 403))
        self.assertIn(Client().get(API + "lidar/tiles/15/1/1.png").status_code, (401, 403))

    def test_a_post_queues_the_units_and_a_get_answers_their_states(self):
        with mock.patch.object(lidar, "_enqueue") as enqueue:
            res = self.client.post(API + "lidar/surface", {"bounds": self.bounds}, content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(all(u["state"] == "queued" for u in res.json()["units"]))
        enqueue.assert_called_once()
        res = self.client.get(API + "lidar/surface", {"bounds": ",".join(map(str, self.bounds))})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(all(u["state"] == "queued" for u in res.json()["units"]))

    def test_bad_or_too_large_bounds_are_refused(self):
        res = self.client.get(API + "lidar/surface", {"bounds": "a,b,c"})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.json()["too_large"])
        res = self.client.post(API + "lidar/surface", {"bounds": [LON - 1, LAT - 1, LON + 1, LAT + 1]}, content_type="application/json")
        self.assertEqual(res.status_code, 400)
        self.assertTrue(res.json()["too_large"])
        self.assertEqual(self.client.post(API + "lidar/surface", ["x"], content_type="application/json").status_code, 400)

    def test_a_built_tile_is_served_and_others_are_404(self):
        self.assertEqual(self.client.get(API + "lidar/tiles/15/%d/%d.png" % self.unit).status_code, 404)
        self.build()
        res = self.client.get(API + "lidar/tiles/15/%d/%d.png" % self.unit)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "image/png")
        self.assertEqual(self.client.get(API + "lidar/tiles/14/1/1.png").status_code, 404)
        self.assertEqual(self.client.get(API + "lidar/tiles/18/999999999/1.png").status_code, 404)


class TestLidarSettings(LidarTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.admin = Client()
        self.admin.login(username="testsuperuser", password="test1234")

    def tearDown(self):
        disable_plugin("mission_planner")
        super().tearDown()

    def test_the_page_shows_the_lidar_surface_size_and_clears_it(self):
        self.build()
        page = self.admin.get(SETTINGS).content.decode()
        self.assertIn("1 unit of about 1 km&sup2; built", page)
        self.assertIn("at most 5.0\xa0GB: past it, the places opened longest ago are removed", page)
        res = self.admin.post(SETTINGS, {"action": "clear_lidar"})
        self.assertEqual(res.status_code, 302)
        self.assertIn("done=lidar_cleared", res["Location"])
        self.assertEqual(lidar.usage()[0], 0)
        self.assertIn("The lidar surface was cleared", self.admin.get(res["Location"]).content.decode())

    def test_clearing_while_a_unit_builds_says_to_try_again(self):
        lidar.write_state(self.unit, "building")
        res = self.admin.post(SETTINGS, {"action": "clear_lidar"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("being built", res.content.decode())

    def test_users_who_are_not_administrators_cannot_clear_it(self):
        self.build()
        user = Client()
        user.login(username="testuser", password="test1234")
        self.assertEqual(user.post(SETTINGS, {"action": "clear_lidar"}).status_code, 403)
        self.assertEqual(lidar.usage()[0], 1)
