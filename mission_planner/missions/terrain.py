"""
The ground under a route, as a small elevation raster, for AGL flown over the terrain (oblique, or ortho and linear
with the DSM follow): the mission carries it as an embedded DSM file and the aircraft follows it (see wpml's DSM
height mode), as Pilot 2's own AGL exports do. Waypoint and POI routes take their ground from it, too.

The raster is Copernicus GLO-30 (COP30) from OpenTopography's Global DEM API, cut to the route plus a margin. COP30
is orthometric (EGM2008); the DSM Pilot 2 embeds is WGS84-ellipsoidal (int16, EPSG:4326), so the heights are moved by
the undulation at the route's centre, the difference between the two heights fetch_ground_elevation gives there.
Checked against the DSM of a real Pilot 2 oblique AGL export: within about 1-4 m.
"""
import math

import numpy as np
import rasterio
import requests
from ..config import NO_KEY, opentopography_api_key
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds

from .elevation import ElevationError, fetch_ground_elevation, without_key

GLOBALDEM_URL = "https://portal.opentopography.org/API/globaldem"
DATASET = "COP30"
TIMEOUT = 60.0

MARGIN = 200.0          # meters of ground fetched around the route
MAX_SIDE = 10000.0      # meters: a larger area is refused (the service limits the size of a request, too)
# The ground height of a waypoint is the highest ground within this many meters of it. Fitted against the sample
# Pilot 2 export: with 50 m no waypoint is more than 0.9 m below Pilot 2's own height, and on average 2 m above it.
RADIUS = 50.0
# Over a lidar terrain (lidar_terrain.py: the highest point of each 10 m cell, trees and roofs), each waypoint is over the
# highest ground within this many meters of the legs flown to and from it instead (flown_ground_heights): 50 m round a
# waypoint lifts a whole small route over one building, and misses one in the middle of a long line, which the aircraft
# flies straight. 15 m leaves room for the GPS without RTK, the wind and the lidar's own placing.
LIDAR_RADIUS = 15.0

METERS_PER_DEGREE = 111320.0


class TerrainError(Exception):
    pass


def _meters_to_degrees(meters, lat):
    """(degrees of longitude, degrees of latitude) for `meters` at latitude `lat`"""
    return meters / (METERS_PER_DEGREE * max(math.cos(math.radians(lat)), 1e-6)), meters / METERS_PER_DEGREE


def bounds(points, margin=MARGIN):
    """(west, south, east, north) of [(lon, lat), ...] plus `margin` meters on every side"""
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    if not lons:
        raise TerrainError("The route has no points")
    dlon, dlat = _meters_to_degrees(margin, max(abs(min(lats)), abs(max(lats))))
    return min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat


def side_lengths(b):
    """(width, height) in meters of the bounds (west, south, east, north)"""
    west, south, east, north = b
    lat = (south + north) / 2.0
    return (east - west) * METERS_PER_DEGREE * math.cos(math.radians(lat)), (north - south) * METERS_PER_DEGREE


def tile_name(b):
    """The 1-degree tile of the south-west corner, named the way the DSM Pilot 2 embeds is (N41W080)"""
    west, south = math.floor(b[0]), math.floor(b[1])
    return "%s%02d%s%03d" % ("N" if south >= 0 else "S", abs(south), "E" if west >= 0 else "W", abs(west))


def file_name(b):
    """The name of the DSM inside the mission (wpmz/res/dsm/<name>), modelled on Pilot 2's
    wgs84_ASTGTMV003_N41W080_dem_2.tif"""
    return "wgs84_%s_%s_dem.tif" % (DATASET, tile_name(b))


def _fetch_globaldem(b, api_key):
    west, south, east, north = b
    try:
        res = requests.get(GLOBALDEM_URL, params={
            "demtype": DATASET, "south": south, "north": north, "west": west, "east": east,
            "outputFormat": "GTiff", "API_Key": api_key,
        }, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise TerrainError("Could not reach the terrain service: %s" % without_key(str(e), api_key))
    if res.status_code in (401, 403):
        raise TerrainError("OpenTopography refused the API key (%d): an administrator changes it on the Mission "
                           "Planner page, under Settings" % res.status_code)
    if res.status_code != 200:
        raise TerrainError("The terrain service returned an error (%d)" % res.status_code)
    return res.content


def ellipsoidal_dsm(content, undulation):
    """
    The int16 EPSG:4326 GeoTIFF of WGS84-ellipsoidal heights, from the orthometric GeoTIFF `content`.

    :param undulation: meters to add to an orthometric height to get the ellipsoidal one
    """
    try:
        with MemoryFile(content) as source, source.open() as src:
            if src.crs is None or src.crs.to_epsg() != 4326:
                raise TerrainError("The terrain service returned heights in an unexpected projection")
            heights = src.read(1, masked=True).astype("float64")
            transform = src.transform
    except (rasterio.errors.RasterioError, rasterio.errors.RasterioIOError):
        raise TerrainError("The terrain service returned an unexpected response")
    if heights.mask.any() or not np.isfinite(heights.filled(0)).all():
        raise TerrainError("The terrain data has gaps over this route")

    values = np.rint(heights.filled(0) + undulation).astype("int16")
    with MemoryFile() as out:
        with out.open(driver="GTiff", width=values.shape[1], height=values.shape[0], count=1, dtype="int16",
                      crs="EPSG:4326", transform=transform, compress="deflate") as dst:
            dst.write(values, 1)
        return out.read()


def fetch_terrain(points):
    """
    The DSM for the route through `points`, fetched from OpenTopography.

    :param points: [(lon, lat), ...]: the waypoints and the area's corners
    :return: (GeoTIFF bytes, {"dataset", "undulation", "bounds", "name"})
    :raises TerrainError: the area is too large, the key is not configured, or the service failed
    """
    b = bounds(points)
    width, height = side_lengths(b)
    if max(width, height) > MAX_SIDE:
        raise TerrainError("The route is too large to fetch its terrain: %.1f by %.1f km, at most %g km on a side"
                           % (width / 1000.0, height / 1000.0, MAX_SIDE / 1000.0))
    api_key = opentopography_api_key()
    if not api_key:
        raise TerrainError(NO_KEY)

    lon, lat = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
    try:
        ground = fetch_ground_elevation(lat, lon)
    except ElevationError as e:
        raise TerrainError(str(e))
    undulation = ground["ellipsoidal"] - ground["orthometric"]

    tif = ellipsoidal_dsm(_fetch_globaldem(b, api_key), undulation)
    return tif, {"dataset": DATASET, "undulation": round(undulation, 3), "bounds": [round(v, 7) for v in b],
                 "name": file_name(b)}


def covers(tif, points, radius=RADIUS):
    """Whether the DSM holds the ground within `radius` meters of every point"""
    with MemoryFile(tif) as f, f.open() as src:
        west, south, east, north = src.bounds
    for lon, lat in points:
        dlon, dlat = _meters_to_degrees(radius, lat)
        if lon - dlon < west or lon + dlon > east or lat - dlat < south or lat + dlat > north:
            return False
    return True


def ground_at(tif, lon, lat):
    """The ground under (lon, lat), WGS84-ellipsoidal meters: the value of the cell it falls in"""
    with MemoryFile(tif) as f, f.open() as src:
        row, col = src.index(lon, lat)
        if not (0 <= row < src.height and 0 <= col < src.width):
            raise TerrainError("The terrain does not cover the route")
        return float(src.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])


def grounds_at(tif, points):
    """ground_at for each (lon, lat) point, opening the terrain once"""
    with MemoryFile(tif) as f, f.open() as src:
        heights = src.read(1)
        out = []
        for lon, lat in points:
            row, col = src.index(lon, lat)
            if not (0 <= row < src.height and 0 <= col < src.width):
                raise TerrainError("The terrain does not cover the route")
            out.append(float(heights[row, col]))
        return out


def ground_heights(tif, points, radius=RADIUS):
    """The highest ground within `radius` meters of each (lon, lat) point, WGS84-ellipsoidal meters"""
    with MemoryFile(tif) as f, f.open() as src:
        heights = src.read(1)
        transform = src.transform
        out = []
        for lon, lat in points:
            dlon, dlat = _meters_to_degrees(radius, lat)
            window = from_bounds(lon - dlon, lat - dlat, lon + dlon, lat + dlat, transform)
            r0, c0 = max(int(math.floor(window.row_off)), 0), max(int(math.floor(window.col_off)), 0)
            r1 = min(int(math.ceil(window.row_off + window.height)), heights.shape[0])
            c1 = min(int(math.ceil(window.col_off + window.width)), heights.shape[1])
            if r1 <= r0 or c1 <= c0:
                raise TerrainError("The terrain does not cover the route")
            out.append(float(heights[r0:r1, c0:c1].max()))
    return out


def is_lidar(name):
    """Whether the terrain of that file name was made from lidar (lidar_terrain.file_name)"""
    return bool(name) and "_LIDAR" in name


def _cells(src, heights):
    """The (lon, lat) centre of each cell, as two arrays"""
    rows, cols = np.indices(heights.shape)
    lons, lats = src.transform * (cols + 0.5, rows + 0.5)
    return lons, lats


def _near(src, heights, lons, lats, a, b, radius):
    """The heights of the cells within `radius` meters of the segment from a to b ((lon, lat); a point when a is b), a
    cell counting when any of it may be (its centre within the radius and half its diagonal); none when off the terrain"""
    lat0 = (a[1] + b[1]) / 2
    kx, ky = METERS_PER_DEGREE * math.cos(math.radians(lat0)), 110540.0
    half = math.hypot(abs(src.transform.a) * kx, abs(src.transform.e) * ky) / 2
    west, south, east, north = src.bounds
    reach_lon, reach_lat = (radius + half) / kx, (radius + half) / ky
    if (max(a[0], b[0]) + reach_lon < west or min(a[0], b[0]) - reach_lon > east
            or max(a[1], b[1]) + reach_lat < south or min(a[1], b[1]) - reach_lat > north):
        return heights[:0, :0].ravel()
    bx, by = (b[0] - a[0]) * kx, (b[1] - a[1]) * ky
    px, py = (lons - a[0]) * kx, (lats - a[1]) * ky
    length = bx * bx + by * by
    t = np.clip((px * bx + py * by) / length, 0, 1) if length else 0
    return heights[np.hypot(px - t * bx, py - t * by) <= radius + half]


def flown_ground_heights(tif, points, name):
    """
    The ground of each (lon, lat) waypoint of a path flown in order, WGS84-ellipsoidal meters: over a lidar terrain (by
    its file `name`), the highest ground within LIDAR_RADIUS of the legs flown to and from it, so that a leg flown
    straight between two waypoints at their heights clears everything along it; over any other, ground_heights (RADIUS
    round each waypoint).
    """
    if not is_lidar(name):
        return ground_heights(tif, points)
    with MemoryFile(tif) as f, f.open() as src:
        heights = src.read(1)
        lons, lats = _cells(src, heights)
        legs = list(zip(points, points[1:])) if len(points) > 1 else [(p, p) for p in points]
        tops = []
        for a, b in legs:
            near = _near(src, heights, lons, lats, a, b, LIDAR_RADIUS)
            if not near.size:
                raise TerrainError("The terrain does not cover the route")
            tops.append(float(near.max()))
    if len(points) == 1:
        return tops
    return [max(tops[max(i - 1, 0)], tops[min(i, len(tops) - 1)]) for i in range(len(points))]


def lowest_ground_near(tif, lon, lat, radius=LIDAR_RADIUS):
    """The lowest ground within `radius` meters of a point (a lidar terrain's takeoff point: the ground the aircraft
    stands on, not a tree or a roof beside it)"""
    with MemoryFile(tif) as f, f.open() as src:
        heights = src.read(1)
        lons, lats = _cells(src, heights)
        near = _near(src, heights, lons, lats, (lon, lat), (lon, lat), radius)
        if not near.size:
            raise TerrainError("The terrain does not cover the route")
        return float(near.min())
