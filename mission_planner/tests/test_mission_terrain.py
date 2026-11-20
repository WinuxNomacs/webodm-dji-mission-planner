"""
Tests of the terrain under a route for oblique AGL (missions/terrain.py). requests and the point elevation are
mocked throughout: the GeoTIFFs are made here, small and with known heights.
"""
import os
from unittest.mock import patch

import numpy as np
import requests
from django.test import SimpleTestCase
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from .. import config
from ..missions import terrain
from ..missions.elevation import ElevationError
from ..missions.terrain import TerrainError

# A 0.01 x 0.01 degree tile where the samples were flown, 1/3600 degree (~30 m) cells, as COP30's
WEST, NORTH = -79.537968, 41.50
CELL = 1 / 3600.0
SIZE = 36


def geotiff(values, crs="EPSG:4326", dtype="float32", nodata=None, west=WEST, north=NORTH, cell=CELL):
    with MemoryFile() as f:
        with f.open(driver="GTiff", width=values.shape[1], height=values.shape[0], count=1, dtype=dtype, crs=crs,
                    transform=from_origin(west, north, cell, cell), nodata=nodata) as dst:
            dst.write(values.astype(dtype), 1)
        return f.read()


def slope():
    """Heights rising 1 m a cell from west to east, from 200 m"""
    return np.tile(200.0 + np.arange(SIZE), (SIZE, 1))


def cell_centre(row, col):
    return WEST + (col + 0.5) * CELL, NORTH - (row + 0.5) * CELL


def response(status_code=200, content=b""):
    class FakeResponse:
        pass
    r = FakeResponse()
    r.status_code, r.content = status_code, content
    return r


GROUND = {"orthometric": 210.0, "ellipsoidal": 176.5}
ROUTE = [(-79.532968, 41.495), (-79.531968, 41.496)]


@patch.dict(os.environ, {"WO_OPENTOPOGRAPHY_API_KEY": "test-key"})
class TestFetchTerrain(SimpleTestCase):
    @patch(terrain.__name__ + ".fetch_ground_elevation", return_value=GROUND)
    @patch(terrain.__name__ + ".requests.get")
    def test_fetches_cop30_around_the_route_and_moves_it_to_the_ellipsoid(self, get, ground):
        get.return_value = response(content=geotiff(slope()))
        tif, info = terrain.fetch_terrain(ROUTE)

        params = get.call_args.kwargs["params"]
        self.assertEqual((params["demtype"], params["outputFormat"], params["API_Key"]), ("COP30", "GTiff", "test-key"))
        self.assertLess(params["west"], -79.532968)
        self.assertGreater(params["north"], 41.496)
        self.assertEqual(info["dataset"], "COP30")
        self.assertEqual(info["undulation"], -33.5)
        self.assertEqual(info["name"], "wgs84_COP30_N41W080_dem.tif")
        self.assertEqual(info["bounds"], [round(v, 7) for v in (params["west"], params["south"], params["east"], params["north"])])

        with MemoryFile(tif) as f, f.open() as src:
            self.assertEqual((src.dtypes[0], src.crs.to_epsg()), ("int16", 4326))
            values = src.read(1)
        self.assertEqual(values[0, 0], 166)         # 200 - 33.5, rounded to even
        self.assertEqual(values[0, 1], 168)         # 201 - 33.5

    def test_the_margin_is_added_on_every_side(self):
        west, south, east, north = terrain.bounds([(-79.532968, 41.495)], margin=111.32)
        self.assertAlmostEqual(north - 41.495, 0.001)
        self.assertAlmostEqual(41.495 - south, 0.001)
        self.assertGreater(east + 79.532968, 0.001)            # a degree of longitude is shorter at 41.5 degrees
        self.assertAlmostEqual(east + 79.532968, -79.532968 - west)

    def test_tiles_are_named_after_their_south_west_corner(self):
        self.assertEqual(terrain.tile_name((-79.527968, 41.49, -79.517968, 41.50)), "N41W080")
        self.assertEqual(terrain.tile_name((151.2, -33.9, 151.3, -33.8)), "S34E151")

    def test_a_route_larger_than_the_limit_is_refused_before_fetching(self):
        with patch(terrain.__name__ + ".requests.get") as get:
            with self.assertRaisesRegex(TerrainError, "too large"):
                terrain.fetch_terrain([(-79.547968, 41.49), (-79.397968, 41.49)])
            get.assert_not_called()

    @patch.dict(os.environ, {"WO_OPENTOPOGRAPHY_API_KEY": ""})
    @patch(config.__name__ + ".saved_api_key", return_value="")
    def test_refuses_to_fetch_without_a_key_and_says_where_to_set_it(self, saved):
        with self.assertRaisesRegex(TerrainError, "API key is set: an administrator sets it on the DJI Mission Planner page"):
            terrain.fetch_terrain(ROUTE)

    @patch.dict(os.environ, {"WO_OPENTOPOGRAPHY_API_KEY": ""})
    @patch(config.__name__ + ".saved_api_key", return_value="saved-key")
    @patch(terrain.__name__ + ".fetch_ground_elevation", return_value=GROUND)
    @patch(terrain.__name__ + ".requests.get")
    def test_without_the_environments_key_the_saved_key_is_used(self, get, ground, saved):
        get.return_value = response(status_code=500)
        with self.assertRaises(TerrainError):
            terrain.fetch_terrain(ROUTE)
        self.assertEqual(get.call_args.kwargs["params"]["API_Key"], "saved-key")

    @patch(terrain.__name__ + ".fetch_ground_elevation", return_value=GROUND)
    @patch(terrain.__name__ + ".requests.get")
    def test_a_service_error_or_an_unreachable_service_is_a_terrain_error(self, get, ground):
        get.return_value = response(status_code=500)
        with self.assertRaisesRegex(TerrainError, r"error \(500\)"):
            terrain.fetch_terrain(ROUTE)
        get.return_value = response(status_code=401)
        with self.assertRaisesRegex(TerrainError, r"refused the API key \(401\).*under Settings"):
            terrain.fetch_terrain(ROUTE)
        get.side_effect = requests.ConnectionError("down")
        with self.assertRaisesRegex(TerrainError, "Could not reach"):
            terrain.fetch_terrain(ROUTE)

    @patch(terrain.__name__ + ".fetch_ground_elevation", return_value=GROUND)
    @patch(terrain.__name__ + ".requests.get")
    def test_an_unreachable_service_does_not_repeat_the_key_in_its_message(self, get, ground):
        get.side_effect = requests.ConnectionError("Max retries exceeded with url: /API/globaldem?API_Key=test-key")
        with self.assertRaises(TerrainError) as ctx:
            terrain.fetch_terrain(ROUTE)
        self.assertNotIn("test-key", str(ctx.exception))
        self.assertIn("API_Key=[API key]", str(ctx.exception))

    @patch(terrain.__name__ + ".fetch_ground_elevation", side_effect=ElevationError("No value here"))
    def test_a_failing_point_elevation_is_a_terrain_error(self, ground):
        with self.assertRaisesRegex(TerrainError, "No value here"):
            terrain.fetch_terrain(ROUTE)

    @patch(terrain.__name__ + ".fetch_ground_elevation", return_value=GROUND)
    @patch(terrain.__name__ + ".requests.get")
    def test_a_response_that_is_not_a_geotiff_in_lon_lat_is_refused(self, get, ground):
        get.return_value = response(content=b"<error>Invalid request</error>")
        with self.assertRaisesRegex(TerrainError, "unexpected response"):
            terrain.fetch_terrain(ROUTE)
        get.return_value = response(content=geotiff(slope(), crs="EPSG:3857"))
        with self.assertRaisesRegex(TerrainError, "unexpected projection"):
            terrain.fetch_terrain(ROUTE)

    @patch(terrain.__name__ + ".fetch_ground_elevation", return_value=GROUND)
    @patch(terrain.__name__ + ".requests.get")
    def test_terrain_with_gaps_is_refused(self, get, ground):
        values = slope()
        values[3, 4] = -9999
        get.return_value = response(content=geotiff(values, nodata=-9999))
        with self.assertRaisesRegex(TerrainError, "gaps"):
            terrain.fetch_terrain(ROUTE)


class TestGroundHeights(SimpleTestCase):
    def setUp(self):
        self.tif = geotiff(slope(), dtype="int16")

    def test_the_ground_at_a_point_is_its_cell(self):
        self.assertEqual(terrain.ground_at(self.tif, *cell_centre(10, 7)), 207)

    def test_the_ground_height_of_a_point_is_the_highest_ground_within_the_radius(self):
        lon, lat = cell_centre(10, 7)
        # A cell is ~23 m wide at 41.5 degrees: 50 m east of the centre of column 7 is in column 9
        self.assertEqual(terrain.ground_heights(self.tif, [(lon, lat)], radius=50), [209])
        self.assertEqual(terrain.ground_heights(self.tif, [(lon, lat)], radius=5), [207])

    def test_points_off_the_terrain_are_refused(self):
        with self.assertRaisesRegex(TerrainError, "does not cover"):
            terrain.ground_at(self.tif, WEST - 0.01, NORTH - 0.005)
        with self.assertRaisesRegex(TerrainError, "does not cover"):
            terrain.ground_heights(self.tif, [(WEST - 0.01, NORTH - 0.005)])

    def test_the_terrain_covers_points_whose_radius_is_inside_it(self):
        self.assertTrue(terrain.covers(self.tif, [cell_centre(10, 10), cell_centre(20, 20)]))
        self.assertFalse(terrain.covers(self.tif, [cell_centre(10, 10), cell_centre(0, 0)]))     # 50 m reaches past the edge
        self.assertFalse(terrain.covers(self.tif, [(WEST - 0.01, NORTH - 0.005)]))


# A lidar terrain's grid: cells of 10 m north to south (about 7.5 m east to west here), flat at 200 m
LIDAR_CELL = 10 / 110540.0
LIDAR_NAME = "e39c8a7e_wgs84_LIDAR10M_N41W080_dem.tif"


def meters_east(m):
    return m / (111320.0 * np.cos(np.radians(NORTH - 0.002)))


class TestFlownGroundHeights(SimpleTestCase):
    """Lidar terrain: each waypoint over the highest ground within terrain.LIDAR_RADIUS of the legs flown to and from it"""
    def terrain(self, block=None):
        """Flat ground at 200 m with one 40 m block (a building) at (meters east, meters north) of the first point"""
        values = np.full((60, 160), 200.0)
        if block:
            col = int((meters_east(block[0]) + (WEST_OF_START - WEST)) / LIDAR_CELL)
            row = int(((NORTH - START_LAT) - block[1] / 110540.0) / LIDAR_CELL)
            values[row, col] = 240.0
        return geotiff(values, dtype="int16", cell=LIDAR_CELL)

    def path(self, *east):
        return [(WEST_OF_START + meters_east(e), START_LAT) for e in east]

    def test_lidar_terrain_is_known_by_its_file_name(self):
        self.assertTrue(terrain.is_lidar(LIDAR_NAME))
        self.assertFalse(terrain.is_lidar("wgs84_COP30_N41W080_dem.tif"))
        self.assertFalse(terrain.is_lidar("wgs84_ASTGTMV003_N41W080_dem_2.tif"))
        self.assertFalse(terrain.is_lidar(None))

    def test_a_building_in_the_middle_of_a_leg_lifts_both_its_ends(self):
        tif = self.terrain(block=(300, 0))
        self.assertEqual(terrain.flown_ground_heights(tif, self.path(0, 150, 450), LIDAR_NAME), [200, 240, 240])
        # 150 m from either end of a longer leg: the radius round the waypoints alone would fly into it
        self.assertEqual(terrain.flown_ground_heights(tif, self.path(150, 450), LIDAR_NAME), [240, 240])
        self.assertEqual(terrain.ground_heights(tif, self.path(150, 450), radius=terrain.LIDAR_RADIUS), [200, 200])

    def test_each_waypoint_takes_the_higher_of_its_two_legs(self):
        tif = self.terrain(block=(450, 0))
        self.assertEqual(terrain.flown_ground_heights(tif, self.path(0, 300, 600, 900), LIDAR_NAME), [200, 240, 240, 200])

    def test_a_building_beside_a_leg_counts_within_the_radius_and_not_beyond_it(self):
        self.assertEqual(terrain.flown_ground_heights(self.terrain(block=(150, 8)), self.path(0, 300), LIDAR_NAME), [240, 240])
        self.assertEqual(terrain.flown_ground_heights(self.terrain(block=(150, 40)), self.path(0, 300), LIDAR_NAME), [200, 200])

    def test_a_path_of_one_point_takes_the_ground_within_the_radius_of_it(self):
        self.assertEqual(terrain.flown_ground_heights(self.terrain(block=(8, 0)), self.path(0), LIDAR_NAME), [240])
        self.assertEqual(terrain.flown_ground_heights(self.terrain(block=(60, 0)), self.path(0), LIDAR_NAME), [200])

    def test_other_terrain_keeps_the_highest_ground_within_50_m_of_each_waypoint(self):
        tif = self.terrain(block=(300, 0))
        for name in ("wgs84_COP30_N41W080_dem.tif", None):
            self.assertEqual(terrain.flown_ground_heights(tif, self.path(0, 270, 600), name),
                             terrain.ground_heights(tif, self.path(0, 270, 600)))
        self.assertEqual(terrain.flown_ground_heights(tif, self.path(0, 270, 600), None), [200, 240, 200])

    def test_a_leg_off_the_terrain_is_refused(self):
        with self.assertRaisesRegex(TerrainError, "does not cover"):
            terrain.flown_ground_heights(self.terrain(), [(WEST - 0.01, START_LAT), (WEST - 0.009, START_LAT)], LIDAR_NAME)

    def test_the_lowest_ground_near_a_point_is_its_lowest_cell_within_the_radius(self):
        tif = self.terrain(block=(0, 0))
        self.assertEqual(terrain.lowest_ground_near(tif, *self.path(0)[0]), 200)
        values = np.full((60, 120), 230.0)
        values[30, 30] = 205.0
        lon, lat = WEST + 30.5 * LIDAR_CELL, NORTH - 30.5 * LIDAR_CELL
        self.assertEqual(terrain.lowest_ground_near(geotiff(values, dtype="int16", cell=LIDAR_CELL), lon + meters_east(10), lat), 205)


WEST_OF_START, START_LAT = WEST + 10.5 * LIDAR_CELL, NORTH - 30.5 * LIDAR_CELL
