"""
Tests of a WebODM task's DSM as the 3D view's ground (task_surface.py, the task-surfaces, task-surface and its tiles
API, Phase 23). The DSM is a small synthetic GeoTIFF; AWS's terrain comes from lidar.terrarium_unit_tile, replaced;
the worker is never reached (task_surface._enqueue, replaced). Every test has its own folders.
"""
import errno
import json
import os
import shutil
import tempfile
import time
from unittest import mock

import numpy as np
from django.contrib.auth.models import User
from django.contrib.gis.geos import Polygon
from django.test import Client
from pyproj import Transformer

from app.models import Project, Task
from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase

from .. import lidar, task_surface
from ..missions import geoid

API = "/api/plugins/mission_planner/"
LON, LAT = -87.70, 41.90                # the middle of the synthetic task
SIZE_M, CELL = 60.0, 0.25               # a 60 m square DSM of 25 cm cells
GROUND, ROOF = 215.0, 225.0             # ellipsoidal, as ODM writes a Matrice 4T's
TERRAIN = 250.0                         # AWS's terrain under it (sea level)
SHIFT = TERRAIN - GROUND


def extent_of(bbox):
    polygon = Polygon.from_bbox(bbox)
    return {"type": "Polygon", "coordinates": [[list(c) for c in polygon.coords[0]]]}


def write_dsm(path, ground=GROUND, roof=ROOF, holes=False):
    """A DSM in UTM 16N round (LON, LAT): ground, a 20 m roof block in the middle, nodata outside a 2 m margin"""
    import rasterio
    from rasterio.transform import from_origin
    x, y = Transformer.from_crs(4326, 32616, always_xy=True).transform(LON, LAT)
    n = int(SIZE_M / CELL)
    values = np.full((n, n), ground, "float32")
    m = int(20 / CELL)
    values[n // 2 - m // 2:n // 2 + m // 2, n // 2 - m // 2:n // 2 + m // 2] = roof
    values[:8, :] = values[-8:, :] = values[:, :8] = values[:, -8:] = -9999
    if holes:
        values[n // 4:n // 4 + 20, n // 4:n // 4 + 20] = -9999
    with rasterio.open(path, "w", driver="GTiff", width=n, height=n, count=1, dtype="float32", crs="EPSG:32616",
                       transform=from_origin(x - SIZE_M / 2, y + SIZE_M / 2, CELL, CELL), nodata=-9999) as d:
        d.write(values, 1)


def bbox():
    to = Transformer.from_crs(32616, 4326, always_xy=True)
    x, y = Transformer.from_crs(4326, 32616, always_xy=True).transform(LON, LAT)
    w, s = to.transform(x - SIZE_M / 2, y - SIZE_M / 2)
    e, n = to.transform(x + SIZE_M / 2, y + SIZE_M / 2)
    return [w, s, e, n]


def tile_of(z, lon, lat):
    mx, my = lidar.to_mercator(lon, lat)
    s = lidar.tile_size(z)
    return int((mx + lidar.HALF) // s), int((lidar.HALF - my) // s)


def read_tile(path):
    import rasterio
    with rasterio.open(path) as d:
        rgba = d.read()
    return lidar.decode(rgba[:3]), rgba[3]


class TaskSurfaceTestCase(BootTestCase):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.dsm = os.path.join(self.folder, "dsm.tif")
        write_dsm(self.dsm)
        self.terrain_calls = []

        def terrain(unit):
            self.terrain_calls.append(unit)
            return np.full((256, 256), TERRAIN)
        self.project = Project.objects.get(name="User Test Project")
        self.task = Task.objects.create(project=self.project, name="Roof survey", epsg=32616,
                                        available_assets=["dsm.tif", "orthophoto.tif"], dsm_extent=extent_of(bbox()),
                                        orthophoto_extent=extent_of(bbox()))
        self.id = str(self.task.id)
        self.queued = []
        for p in (mock.patch.object(task_surface, "root", return_value=os.path.join(self.folder, "tasks")),
                  mock.patch.object(lidar, "root", return_value=os.path.join(self.folder, "lidar")),
                  mock.patch.object(lidar, "terrarium_unit_tile", side_effect=terrain),
                  mock.patch.object(task_surface, "dsm_path", side_effect=lambda task: self.dsm if os.path.exists(self.dsm) else None),
                  mock.patch.object(task_surface, "_enqueue", side_effect=self.queued.append)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)
        super().tearDown()

    def cut(self):
        task_surface.request(self.task)
        task_surface.cut(self.id)
        return task_surface.read_state(self.id)


class TestCut(TaskSurfaceTestCase):
    def test_the_dsm_is_cut_into_tiles_of_zoom_15_to_18_over_the_task(self):
        st = self.cut()
        self.assertEqual(st["state"], "done", st)
        for z in task_surface.TILE_ZOOMS:
            self.assertIsNotNone(task_surface.tile_path(self.id, z, *tile_of(z, LON, LAT)), z)
        far = tile_of(18, LON + 0.01, LAT)
        self.assertIsNone(task_surface.tile_path(self.id, 18, *far))
        w, s, e, n = st["bounds"]
        self.assertTrue(w < LON < e and s < LAT < n)
        self.assertGreater(st["made"], 0)
        self.assertLessEqual(st["made"], 2 ** 53 - 1)

    def test_its_heights_are_shifted_to_meet_the_terrain_on_open_ground_and_its_roofs_keep_their_height(self):
        st = self.cut()
        self.assertAlmostEqual(st["shift"], SHIFT, delta=0.01)
        self.assertEqual(st["reference"], "terrain")
        n = geoid.undulation(LAT, LON)
        self.assertAlmostEqual(st["match"], SHIFT + n, delta=0.01)
        heights, alpha = read_tile(task_surface.tile_path(self.id, 18, *tile_of(18, LON, LAT)))
        middle = heights[alpha == 255]
        self.assertAlmostEqual(float(middle.max()), ROOF + SHIFT, delta=0.05)
        self.assertAlmostEqual(float(np.median(middle)), GROUND + SHIFT, delta=0.05)

    def test_the_task_fades_out_over_its_last_meters_and_is_absent_outside(self):
        self.cut()
        alphas = []
        for x in range(tile_of(18, bbox()[0], LAT)[0], tile_of(18, bbox()[2], LAT)[0] + 1):
            for y in range(tile_of(18, LON, bbox()[3])[1], tile_of(18, LON, bbox()[1])[1] + 1):
                path = task_surface.tile_path(self.id, 18, x, y)
                if path:
                    alphas.append(read_tile(path)[1])
        alpha = np.concatenate([a.ravel() for a in alphas])
        self.assertTrue((alpha == 0).any())                                 # outside
        self.assertTrue((alpha == 255).any())                               # inside
        self.assertTrue(((alpha > 0) & (alpha < 255)).any())                # the feather

    def test_a_hole_in_the_dsm_is_not_part_of_the_task(self):
        write_dsm(self.dsm, holes=True)
        self.cut()
        z = 18
        x, y = Transformer.from_crs(4326, 32616, always_xy=True).transform(LON, LAT)
        lon, lat = Transformer.from_crs(32616, 4326, always_xy=True).transform(x - SIZE_M / 4 + 2.5, y + SIZE_M / 4 - 2.5)
        tx, ty = tile_of(z, lon, lat)
        _heights, alpha = read_tile(task_surface.tile_path(self.id, z, tx, ty))
        mx, my = lidar.to_mercator(lon, lat)
        left, _b, _r, top = lidar.tile_bounds(z, tx, ty)
        s = lidar.tile_size(z) / 256
        self.assertEqual(alpha[int((top - my) / s), int((mx - left) / s)], 0)

    def test_the_built_lidar_is_preferred_to_aws_to_place_the_task(self):
        import rasterio
        from rasterio.transform import from_bounds
        unit = tile_of(15, LON, LAT)
        folder = lidar.unit_folder(unit)
        os.makedirs(folder)
        with rasterio.open(os.path.join(folder, "dsm.tif"), "w", driver="GTiff", width=64, height=64, count=1, dtype="float32",
                           crs="EPSG:3857", transform=from_bounds(*lidar.tile_bounds(15, *unit), 64, 64), nodata=-9999) as d:
            d.write(np.full((64, 64), 248.0, "float32"), 1)
        lidar.write_state(unit, "done", "lidar")
        st = self.cut()
        self.assertEqual(st["reference"], "lidar")
        self.assertAlmostEqual(st["shift"], 248.0 - GROUND, delta=0.01)
        self.assertEqual(self.terrain_calls, [])

    def test_with_no_surface_under_it_the_task_is_placed_by_the_geoid_alone(self):
        with mock.patch.object(lidar, "terrarium_unit_tile", side_effect=lidar.LidarError("AWS answered 503")):
            st = self.cut()
        self.assertEqual(st["state"], "done")
        self.assertIsNone(st["reference"])
        self.assertAlmostEqual(st["shift"], -geoid.undulation(LAT, LON), delta=0.01)
        self.assertEqual(st["match"], 0.0)

    def test_without_the_surface_nor_the_geoid_the_cut_fails_saying_so(self):
        with mock.patch.object(lidar, "terrarium_unit_tile", side_effect=lidar.LidarError("down")), \
                mock.patch.object(geoid, "undulation", side_effect=geoid.GeoidError("no grid")):
            st = self.cut()
        self.assertEqual(st["state"], "failed")
        self.assertIn("neither the surface under the task nor the geoid", st["message"])

    def test_a_dsm_that_does_not_read_fails_with_the_reason_and_leaves_no_work_behind(self):
        with open(self.dsm, "wb") as f:
            f.write(b"not a tiff")
        st = self.cut()
        self.assertEqual(st["state"], "failed")
        self.assertIn("could not be read", st["message"])
        self.assertEqual([n for n in os.listdir(task_surface.folder(self.id)) if n.startswith(".cut-")], [])

    def test_a_task_without_a_dsm_fails_saying_so(self):
        os.remove(self.dsm)
        self.assertEqual(task_surface.request(self.task)["message"], "the task has no DSM")
        self.assertEqual(self.queued, [])
        task_surface.cut(self.id)
        self.assertEqual(task_surface.read_state(self.id)["message"], "the task has no DSM")

    def test_a_full_disk_fails_saying_so_and_keeps_the_tiles_it_had(self):
        self.cut()
        before = task_surface.tile_path(self.id, 18, *tile_of(18, LON, LAT))
        write_dsm(self.dsm, roof=230.0)
        with mock.patch.object(lidar, "_write_tile", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            st = self.cut()
        self.assertEqual((st["state"], st["message"]), ("failed", "the disk is full"))
        self.assertTrue(os.path.isfile(before))
        self.assertEqual([n for n in os.listdir(task_surface.folder(self.id)) if n.startswith((".cut-", ".old-"))], [])

    def test_a_task_too_large_to_show_fails_saying_so(self):
        with mock.patch.object(task_surface, "MAX_TILES", 3):
            st = self.cut()
        self.assertEqual(st["state"], "failed")
        self.assertIn("too large", st["message"])

    def test_a_task_deleted_before_its_cut_has_its_folder_removed(self):
        task_surface.request(self.task)
        self.task.delete()
        task_surface.cut(self.id)
        self.assertFalse(os.path.exists(task_surface.folder(self.id)))

    def test_cutting_again_replaces_the_tiles(self):
        self.cut()
        write_dsm(self.dsm, roof=235.0)
        os.utime(self.dsm, (time.time() + 10, time.time() + 10))
        st = self.cut()
        heights, alpha = read_tile(task_surface.tile_path(self.id, 18, *tile_of(18, LON, LAT)))
        self.assertAlmostEqual(float(heights[alpha == 255].max()), 235.0 + st["shift"], delta=0.05)


class TestRequest(TaskSurfaceTestCase):
    def test_a_request_queues_one_cut_and_answers_queued(self):
        self.assertEqual(task_surface.request(self.task)["state"], "queued")
        self.assertEqual(task_surface.request(self.task)["state"], "queued")
        self.assertEqual(self.queued, [self.id])

    def test_a_cut_task_is_not_cut_again_until_its_dsm_changes(self):
        self.cut()
        self.queued.clear()
        answer = task_surface.request(self.task)
        self.assertEqual(answer["state"], "done")
        self.assertGreater(answer["v"], 0)
        self.assertEqual(self.queued, [])
        os.utime(self.dsm, (time.time() + 10, time.time() + 10))         # the task processed again
        self.assertEqual(task_surface.request(self.task)["state"], "queued")
        self.assertEqual(self.queued, [self.id])

    def test_a_failed_cut_is_retried_after_a_while(self):
        with mock.patch.object(task_surface, "MAX_TILES", 3):
            self.cut()
        self.queued.clear()
        self.assertEqual(task_surface.request(self.task)["state"], "failed")
        later = time.time() + task_surface.RETRY_AFTER + 1
        with mock.patch.object(task_surface.time, "time", return_value=later):
            self.assertEqual(task_surface.request(self.task)["state"], "queued")
        self.assertEqual(self.queued, [self.id])

    def test_a_cut_that_died_with_its_worker_is_taken_over(self):
        task_surface.request(self.task)
        task_surface.write_state(self.id, "building", dsm_mtime=os.path.getmtime(self.dsm))
        self.queued.clear()
        self.assertEqual(task_surface.request(self.task)["state"], "building")
        later = time.time() + task_surface.STALE_AFTER + 1
        with mock.patch.object(task_surface.time, "time", return_value=later):
            self.assertEqual(task_surface.request(self.task)["state"], "queued")
        self.assertEqual(self.queued, [self.id])

    def test_with_the_queue_down_the_state_says_so(self):
        with mock.patch.object(task_surface, "_enqueue", side_effect=ConnectionError("broker")):
            answer = task_surface.request(self.task)
        self.assertEqual(answer["state"], "failed")
        self.assertIn("could not be queued", answer["message"])

    def test_a_state_that_does_not_read_is_set_aside_and_the_task_cut_again(self):
        self.cut()
        path = os.path.join(task_surface.folder(self.id), "status.json")
        with open(path, "w") as f:
            f.write("garbage")
        self.queued.clear()
        self.assertEqual(task_surface.request(self.task)["state"], "queued")
        self.assertTrue(os.path.exists(path + ".bad"))

    def test_the_worker_job_cuts_the_task_of_the_module_it_is_given(self):
        with mock.patch.object(task_surface, "cut") as cut:
            task_surface.cut_job(task_surface.__name__, self.id)
        cut.assert_called_once_with(self.id)

    def test_a_task_id_that_is_not_one_never_names_a_folder(self):
        for bad in ("../lidar", "", None, "47f064e5-c14f-468b-bd2e-0bd578ba551"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                task_surface.folder(bad)


class TestTaskSurfaceApi(TaskSurfaceTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")
        self.other = Task.objects.create(project=Project.objects.get(name="User 2 Test Project"), name="Not mine",
                                         epsg=32616, available_assets=["dsm.tif"], dsm_extent=extent_of(bbox()))

    def tearDown(self):
        disable_plugin("mission_planner")
        super().tearDown()

    def post(self, path, data):
        return self.client.post(API + path, json.dumps(data), content_type="application/json")

    def test_the_list_has_the_users_tasks_overlapping_the_route_with_what_each_has(self):
        w, s, e, n = bbox()
        Task.objects.create(project=self.project, name="Photos only", epsg=32616, available_assets=["orthophoto.tif"],
                            orthophoto_extent=extent_of(bbox()))
        Task.objects.create(project=self.project, name="Elsewhere", epsg=32616, available_assets=["dsm.tif"],
                            dsm_extent=extent_of([w + 1, s, e + 1, n]))
        Task.objects.create(project=self.project, name="Images only", epsg=32616, available_assets=[])
        # a route reaching into the task's corner overlaps it
        res = self.client.get(API + "task-surfaces", {"bounds": "%f,%f,%f,%f" % (e - 0.0001, n - 0.0001, e + 0.01, n + 0.01)})
        self.assertEqual(res.status_code, 200, res.content[:300])
        tasks = res.json()["tasks"]
        self.assertEqual([t["name"] for t in tasks], ["Photos only", "Roof survey"])
        self.assertEqual(tasks[1], {"id": self.id, "project": self.project.id, "project_name": "User Test Project",
                                    "name": "Roof survey", "dsm": True, "orthophoto": True})
        self.assertEqual((tasks[0]["dsm"], tasks[0]["orthophoto"]), (False, True))
        # a route of one point inside it
        res = self.client.get(API + "task-surfaces", {"bounds": "%f,%f,%f,%f" % (LON, LAT, LON, LAT)})
        self.assertEqual(len(res.json()["tasks"]), 2)
        self.assertEqual(self.client.get(API + "task-surfaces", {"bounds": "1,2"}).status_code, 400)

    def test_a_task_is_cut_and_served_through_the_api(self):
        res = self.post("task-surface", {"task": self.id})
        self.assertEqual(res.json()["state"], "queued")
        task_surface.cut(self.id)
        res = self.client.get(API + "task-surface", {"task": self.id})
        body = res.json()
        self.assertEqual(body["state"], "done")
        self.assertAlmostEqual(body["shift"], SHIFT, delta=0.01)
        self.assertEqual(set(body), {"state", "message", "v", "shift", "match", "reference", "bounds"})
        x, y = tile_of(18, LON, LAT)
        res = self.client.get(API + "task-surface/%s/tiles/18/%d/%d.png" % (self.id, x, y))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "image/png")
        self.assertIn("private", res["Cache-Control"])
        far = tile_of(18, LON + 0.01, LAT)
        self.assertEqual(self.client.get(API + "task-surface/%s/tiles/18/%d/%d.png" % ((self.id,) + far)).status_code, 404)

    def test_someone_elses_task_is_not_found(self):
        other = str(self.other.id)
        self.assertEqual(self.post("task-surface", {"task": other}).status_code, 404)
        self.assertEqual(self.client.get(API + "task-surface", {"task": other}).status_code, 404)
        self.assertEqual(self.client.get(API + "task-surface/%s/tiles/18/1/1.png" % other).status_code, 404)
        self.assertEqual(self.post("task-surface", {"task": "../x"}).status_code, 404)
        self.assertEqual(self.post("task-surface", ["x"]).status_code, 404)
        self.assertEqual(self.queued, [])
        res = self.client.get(API + "task-surfaces", {"bounds": "%f,%f,%f,%f" % (LON, LAT, LON, LAT)})
        self.assertNotIn(other, [t["id"] for t in res.json()["tasks"]])

    def test_anonymous_users_get_nothing(self):
        anonymous = Client()
        self.assertIn(anonymous.get(API + "task-surfaces", {"bounds": "1,2,3,4"}).status_code, (401, 403))
        self.assertIn(anonymous.get(API + "task-surface", {"task": self.id}).status_code, (401, 403))

    def test_listing_removes_the_surfaces_of_deleted_tasks(self):
        self.cut()
        self.task.delete()
        self.client.get(API + "task-surfaces", {"bounds": "1,2,3,4"})
        self.assertFalse(os.path.exists(task_surface.folder(self.id)))

    def test_a_user_who_can_view_the_project_gets_its_task(self):
        user2 = User.objects.get(username="testuser2")
        from guardian.shortcuts import assign_perm
        assign_perm("view_project", user2, self.project)
        client = Client()
        client.login(username="testuser2", password="test1234")
        self.assertEqual(client.get(API + "task-surface", {"task": self.id}).status_code, 200)
