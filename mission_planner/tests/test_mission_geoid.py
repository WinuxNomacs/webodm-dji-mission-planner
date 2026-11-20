"""
Tests of the EGM96 grid's download and of the sea level to WGS84 ellipsoid conversion (missions/geoid.py). The
download is faked throughout, with a small GeoTIFF standing in for the grid; the conversion uses the real grid, kept
in fixtures/geoid (tests/__init__.py points geoid.py at it).
"""
import errno
import json
import hashlib
import os
import shutil
import tempfile
from unittest.mock import patch

import numpy as np
import requests
from django.test import SimpleTestCase

from ..missions import geoid, wpml
from ..missions.geoid import GeoidError
from .test_mission_terrain import geotiff
from .test_mission_wpml import files, make

class FakeStream:
    def __init__(self, content=b"", status_code=200, error=None, chunk=1024):
        self.content, self.status_code, self.error, self.chunk = content, status_code, error, chunk
        self.seen_while_streaming = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, size):
        for i in range(0, len(self.content), self.chunk):
            if self.error and i > 0:
                raise self.error
            yield self.content[i:i + self.chunk]


class GridTestCase(SimpleTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.grid = geotiff(np.zeros((8, 8)))
        for target, value in (("grid_folder", lambda: self.folder), ("GRID_SIZE", len(self.grid)),
                              ("GRID_SHA256", hashlib.sha256(self.grid).hexdigest())):
            p = patch.object(geoid, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.path = os.path.join(self.folder, geoid.GRID_NAME)

    def leftovers(self):
        return sorted(n for n in os.listdir(self.folder) if n != geoid.GRID_NAME)


class TestEnsureGrid(GridTestCase):
    def test_the_grid_is_downloaded_once_and_then_reused(self):
        with patch(geoid.__name__ + ".requests.get", return_value=FakeStream(self.grid)) as get:
            self.assertEqual(geoid.ensure_grid(), self.path)
            self.assertEqual(geoid.ensure_grid(), self.path)
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], "https://cdn.proj.org/us_nga_egm96_15.tif")
        self.assertEqual(self.leftovers(), [])

    def test_the_grid_is_written_beside_and_moved_into_place_only_once_checked(self):
        stream = FakeStream(self.grid)
        original = stream.iter_content

        def watching(size):
            for chunk in original(size):
                stream.seen_while_streaming.append(os.path.exists(self.path))
                yield chunk
        stream.iter_content = watching
        with patch(geoid.__name__ + ".requests.get", return_value=stream):
            geoid.ensure_grid()
        self.assertEqual(set(stream.seen_while_streaming), {False})
        self.assertTrue(os.path.exists(self.path))

    def test_a_download_that_is_not_the_expected_file_is_discarded(self):
        other = geotiff(np.ones((8, 8)))
        self.assertEqual(len(other), len(self.grid))
        with patch(geoid.__name__ + ".requests.get", return_value=FakeStream(other)):
            with self.assertRaisesRegex(GeoidError, "not the expected file"):
                geoid.ensure_grid()
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.leftovers(), [])

    def test_a_cut_off_download_is_discarded(self):
        with patch(geoid.__name__ + ".requests.get", return_value=FakeStream(self.grid[:-100])):
            with self.assertRaisesRegex(GeoidError, "not the expected file"):
                geoid.ensure_grid()
        with patch(geoid.__name__ + ".requests.get",
                   return_value=FakeStream(self.grid, error=requests.ConnectionError("reset"), chunk=100)):
            with self.assertRaisesRegex(GeoidError, "Could not download"):
                geoid.ensure_grid()
        self.assertEqual(os.listdir(self.folder), [])

    def test_a_download_larger_than_the_grid_is_stopped(self):
        with patch(geoid.__name__ + ".requests.get", return_value=FakeStream(self.grid + b"x" * 5000)):
            with self.assertRaisesRegex(GeoidError, "larger than expected"):
                geoid.ensure_grid()
        self.assertEqual(os.listdir(self.folder), [])

    def test_an_unreachable_or_failing_cdn_is_a_geoid_error(self):
        with patch(geoid.__name__ + ".requests.get", side_effect=requests.ConnectionError("down")):
            with self.assertRaisesRegex(GeoidError, r"Could not download the geoid grid \(ConnectionError\)"):
                geoid.ensure_grid()
        with patch(geoid.__name__ + ".requests.get", side_effect=requests.Timeout("slow")):
            with self.assertRaisesRegex(GeoidError, "Could not download"):
                geoid.ensure_grid()
        with patch(geoid.__name__ + ".requests.get", return_value=FakeStream(status_code=404)):
            with self.assertRaisesRegex(GeoidError, r"error \(404\)"):
                geoid.ensure_grid()
        self.assertEqual(os.listdir(self.folder), [])

    def test_a_download_past_its_deadline_is_stopped(self):
        clock = iter([0.0] + [geoid.DEADLINE + 1.0] * 100)
        with patch(geoid.__name__ + ".requests.get", return_value=FakeStream(self.grid)), \
                patch(geoid.__name__ + ".time.monotonic", side_effect=lambda: next(clock)):
            with self.assertRaisesRegex(GeoidError, "took more than"):
                geoid.ensure_grid()
        self.assertEqual(os.listdir(self.folder), [])

    def test_a_full_disk_is_a_geoid_error(self):
        with patch(geoid.__name__ + ".tempfile.mkstemp", side_effect=OSError(errno.ENOSPC, "No space left")):
            with self.assertRaisesRegex(GeoidError, "Could not write the geoid grid"):
                geoid.ensure_grid()

    def test_a_cached_grid_that_does_not_read_is_set_aside_and_downloaded_again(self):
        with open(self.path, "wb") as f:
            f.write(b"x" * len(self.grid))
        with patch(geoid.__name__ + ".requests.get", return_value=FakeStream(self.grid)) as get:
            self.assertEqual(geoid.ensure_grid(), self.path)
        get.assert_called_once()
        self.assertEqual(self.leftovers(), [geoid.GRID_NAME + ".bad"])
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), self.grid)


class TestUndulation(SimpleTestCase):
    def test_the_real_grid_gives_egm96s_undulation(self):
        # The oblique AGL sample (Phase 5 measured -33.73 m there too), and Paris
        self.assertAlmostEqual(geoid.undulation(41.489810, -79.528136), -33.728, delta=0.001)
        self.assertAlmostEqual(geoid.undulation(48.8566, 2.3522), 44.564, delta=0.001)

    def test_a_height_above_sea_level_becomes_ellipsoidal(self):
        self.assertAlmostEqual(geoid.to_ellipsoidal(41.489810, -79.528136, 216.0), 216.0 - 33.728, delta=0.001)

    def test_without_the_grid_the_conversion_is_a_geoid_error(self):
        with patch.object(geoid, "ensure_grid", side_effect=GeoidError("no grid")):
            with self.assertRaises(GeoidError):
                geoid.to_ellipsoidal(41.5, -79.547968, 216.0)

    def test_a_grid_proj_cannot_use_is_a_geoid_error(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        bad = os.path.join(folder, "bad.tif")
        with open(bad, "wb") as f:
            f.write(b"not a grid")
        with patch.object(geoid, "ensure_grid", return_value=bad):
            with self.assertRaises(GeoidError):
                geoid.undulation(41.5, -79.547968)


class TestTakeoffPointInTheMission(SimpleTestCase):
    """wpml.takeoff_ref_point: the height Pilot 2 reads as ellipsoidal (TestAreaRoute.kmz's settings, from test_mission_wpml)"""
    def test_a_sea_level_takeoff_height_goes_out_ellipsoidal(self):
        plan, s = make(takeoff_ref_point=(42.103173, -85.020786, 244.0))
        lat, lon, h = wpml.takeoff_ref_point(s)
        self.assertAlmostEqual(h, 244.0 + geoid.undulation(lat, lon), places=6)
        self.assertAlmostEqual(h, 244.0 - 34.2, delta=0.01)

    def test_above_sea_level_the_missions_own_ellipsoidal_height_is_used(self):
        plan, s = make(takeoff_ref_point=(42.103173, -85.020786, 244.0), height_mode="EGM96", takeoff_ellipsoidal_height=210.0)
        self.assertEqual(wpml.takeoff_ref_point(s)[2], 210.0)

    def test_slope_and_geometric_routes_keep_theirs_and_a_dsm_gives_its_ground(self):
        plan, s = make(takeoff_ref_point=(42.103173, -85.020786, 244.0))
        self.assertEqual(wpml.takeoff_ref_point(s, ellipsoidal=True)[2], 244.0)

        class Dsm:
            takeoff = (1.0, 2.0, 3.0)
        self.assertEqual(wpml.takeoff_ref_point(s, Dsm()), (1.0, 2.0, 3.0))

    def test_without_the_grid_the_mission_goes_out_without_the_point(self):
        plan, s = make()
        with patch.object(geoid, "undulation", side_effect=GeoidError("no grid")):
            self.assertIsNone(wpml.takeoff_ref_point(s))
            template = files(plan, s)[0].decode()
        self.assertNotIn("takeOffRefPoint", template)
        self.assertIn("missionConfig", template)


# -- GEOID18: NAVD88 heights (the lidar's) to the WGS84 ellipsoid ------------------------------------------------------

def gtx_grid(path, offset, west=-90.0, south=41.0, cells=40, step=0.1):
    """A vertical grid in PROJ's GTX format: `offset` meters everywhere over cells x cells of `step` degrees"""
    import struct
    with open(path, "wb") as f:
        f.write(struct.pack(">4d2i", south, west, step, step, cells, cells))
        f.write(np.full(cells * cells, offset, dtype=">f4").tobytes())
    return path


def helmert_only(lon, lat, h, epoch):
    """NAD83(2011) to ITRF2014 as PROJ chooses it, independently of the pipeline pinned in geoid.py"""
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:6319", "EPSG:7912", always_xy=True).transform(lon, lat, h, epoch)


class TestGeoid18Grid(GridTestCase):
    def setUp(self):
        super().setUp()
        from . import ENSURE_GEOID18
        for target, value in (("GEOID18_SIZE", len(self.grid)), ("GEOID18_SHA256", hashlib.sha256(self.grid).hexdigest()),
                              ("ensure_geoid18", ENSURE_GEOID18)):
            p = patch.object(geoid, target, value)
            p.start()
            self.addCleanup(p.stop)

    def test_the_geoid18_grid_is_downloaded_once_under_its_own_name_beside_egm96s(self):
        with patch(geoid.__name__ + ".requests.get", return_value=FakeStream(self.grid)) as get:
            path = geoid.ensure_geoid18()
            self.assertEqual(geoid.ensure_geoid18(), path)
        self.assertEqual(path, os.path.join(self.folder, "us_noaa_g2018u0.tif"))
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args[0][0], "https://cdn.proj.org/us_noaa_g2018u0.tif")

    def test_a_failed_geoid18_download_is_a_geoid_error_and_leaves_nothing(self):
        with patch(geoid.__name__ + ".requests.get", return_value=FakeStream(self.grid[:-10])):
            with self.assertRaises(GeoidError):
                geoid.ensure_geoid18()
        self.assertEqual(os.listdir(self.folder), [])


class TestNavd88Shift(SimpleTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.grid = gtx_grid(os.path.join(self.folder, "flat.gtx"), -30.0)

    def test_the_shift_is_the_grids_height_and_the_nad83_to_wgs84_step_at_every_point(self):
        lons, lats = np.array([[-88.0, -87.9], [-88.0, -87.9]]), np.array([[41.5, 41.5], [41.6, 41.6]])
        z = geoid.navd88_shift(lons, lats, self.grid, epoch=2026.5)
        self.assertEqual(z.shape, (2, 2))
        # PROJ's own choice of the step: the same to a millimetre (another PROJ version may pick one a little off; the
        # pinned pipeline gives the same heights whatever it picks)
        for (row, col), lon in np.ndenumerate(lons):
            self.assertAlmostEqual(z[row, col], helmert_only(lon, lats[row, col], -30.0, 2026.5)[2], delta=0.001)
        self.assertLess(z.max(), -30.5)     # NAD83(2011) to WGS84 lowers the ground by about 1 m here

    def test_a_point_off_the_grid_is_a_geoid_error(self):
        with self.assertRaisesRegex(GeoidError, "conterminous US"):
            geoid.navd88_shift(np.array([2.35]), np.array([48.85]), self.grid)

    def test_a_grid_proj_cannot_read_is_a_geoid_error(self):
        junk = os.path.join(self.folder, "junk.gtx")
        with open(junk, "wb") as f:
            f.write(b"not a grid")
        with self.assertRaises(GeoidError):
            geoid.navd88_shift(np.array([-88.0]), np.array([41.5]), junk)

    def test_without_the_grid_the_shift_is_a_geoid_error(self):
        with patch.object(geoid, "ensure_geoid18", side_effect=GeoidError("no grid")):
            with self.assertRaises(GeoidError):
                geoid.navd88_shift(np.array([-88.0]), np.array([41.5]))

    def test_the_real_geoid18_grid_is_pinned_by_its_size_and_sha256(self):
        self.assertEqual(geoid.GEOID18_NAME, "us_noaa_g2018u0.tif")
        self.assertEqual((geoid.GEOID18_SIZE, geoid.GEOID18_SHA256[:8]), (16742155, "fa9a407a"))

    def test_the_epoch_is_the_decimal_year(self):
        import datetime
        self.assertAlmostEqual(geoid.decimal_year(datetime.datetime(2026, 7, 2, 12, tzinfo=datetime.timezone.utc)),
                               2026.5, places=2)


class TestRealGeoid18(SimpleTestCase):
    def test_the_real_grid_gives_ngs_geoid18_heights(self):
        """Only where the stack has downloaded the grid (the live check of lidar terrain does)"""
        from app.plugins.functions import get_plugins_persistent_path
        from pyproj import Transformer
        from ..routes import DATA_FOLDER
        # the stack's own media, not media_test (WebODM's MEDIA_ROOT under test)
        folder = get_plugins_persistent_path(DATA_FOLDER, "grids").replace(os.sep + "media_test" + os.sep, os.sep + "media" + os.sep)
        path = os.path.join(folder, geoid.GEOID18_NAME)
        if not os.path.exists(path):
            self.skipTest("the GEOID18 grid is not downloaded on this stack yet (the lidar terrain's live check does)")
        t = Transformer.from_pipeline("+proj=vgridshift +grids=%s +multiplier=1" % path)
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "geoid", "geoid18_ngs.json")) as f:
            for p in json.load(f):
                self.assertAlmostEqual(t.transform(p["lon"], p["lat"], 0.0)[2], p["geoidHeight"], delta=0.005)
