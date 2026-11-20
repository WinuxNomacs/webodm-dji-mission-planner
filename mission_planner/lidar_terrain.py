"""
The terrain of an AGL route from the lidar surface (lidar.py), where the route's settings choose it (terrain_source
"lidar", the default) and USGS lidar covers it: the units' 1 m DSMs (the highest return of each cell, trees and roofs
included) reduced to cells of CELL_ARCSEC (10 m), each the highest point in it, so that the aircraft following it
never flies lower over a tree or a roof than the set height, then moved from NAVD88 to the WGS84 ellipsoid (GEOID18
and NAD83(2011) to WGS84, missions/geoid.py) at every cell, and written as the COP30 terrain is (int16 EPSG:4326,
missions/terrain.py), for the KMZ, the waypoints' ground heights and the 3D view.

Cells the lidar leaves empty (holes, and units with no lidar or with heights that are not NAVD88 meters: lidar.py's
datum_check) are filled from COP30. Everything else falls back to COP30 for the whole route, saying why: outside the
conterminous US (GEOID18's grid), a terrain area over MAX_AREA, no lidar there, a unit that failed, the GEOID18 grid
not to be had. While units are being built, fetch() answers Building: the editor asks again.
"""
import logging
import math

import numpy as np

from . import lidar
from .missions import geoid, terrain

logger = logging.getLogger('app.logger')

CELL_ARCSEC = 1.0 / 3       # 1/3 arc-second, about 10 m (the user's choice, 2026-11-18); Pilot 2's own: 1 arc-second
MAX_AREA = 4e6              # m2 of terrain area (the route plus terrain.MARGIN) taken from lidar (the user's choice)
CONUS = (-125.0, 24.5, -66.9, 49.4)  # west, south, east, north: GEOID18's conterminous grid, coarsely
SOURCES = ("lidar", "cop30")


class Building(Exception):
    """The lidar units are being built: ask again"""

    def __init__(self, states):
        super().__init__("the lidar surface is being built")
        self.states = states


def in_conus(b):
    west, south, east, north = b
    return CONUS[0] <= west and east <= CONUS[2] and CONUS[1] <= south and north <= CONUS[3]


def area(b):
    width, height = terrain.side_lengths(b)
    return width * height


def grid(b):
    """(transform, width, height) of the terrain's cells over the bounds, aligned on whole cells"""
    from rasterio.transform import from_origin
    step = CELL_ARCSEC / 3600.0
    west, south = math.floor(b[0] / step) * step, math.floor(b[1] / step) * step
    east, north = math.ceil(b[2] / step) * step, math.ceil(b[3] / step) * step
    return from_origin(west, north, step, step), int(round((east - west) / step)), int(round((north - south) / step))


def file_name(b):
    return "wgs84_LIDAR10M_%s_dem.tif" % terrain.tile_name(b)


def highest(units, transform, width, height):
    """The units' DSMs on the terrain's cells, each cell the highest lidar in it (NAVD88; NaN where there is none)"""
    import os

    import rasterio
    from rasterio.warp import Resampling, reproject
    out = np.full((height, width), np.nan)
    for unit in units:
        part = np.full((height, width), np.nan)
        with rasterio.open(os.path.join(lidar.unit_folder(unit), "dsm.tif")) as src:
            reproject(rasterio.band(src, 1), part, src_nodata=-9999, dst_transform=transform, dst_crs="EPSG:4326",
                      dst_nodata=np.nan, resampling=Resampling.max)
        part[part < -9000] = np.nan
        out = np.fmax(out, part)
    return out


def cop30_on(tif, transform, width, height):
    """The COP30 terrain (ellipsoidal GeoTIFF bytes) on the terrain's cells"""
    from rasterio.io import MemoryFile
    from rasterio.warp import Resampling, reproject
    out = np.full((height, width), np.nan)
    with MemoryFile(tif) as m, m.open() as src:
        reproject(src.read(1).astype("float64"), out, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=transform, dst_crs="EPSG:4326", dst_nodata=np.nan, resampling=Resampling.bilinear)
    return out


def write(values, transform):
    from rasterio.io import MemoryFile
    values = np.rint(values).astype("int16")
    with MemoryFile() as out:
        with out.open(driver="GTiff", width=values.shape[1], height=values.shape[0], count=1, dtype="int16",
                      crs="EPSG:4326", transform=transform, compress="deflate") as dst:
            dst.write(values, 1)
        return out.read()


def from_units(points, b, units):
    """(GeoTIFF bytes, info) of the lidar terrain over the bounds from the built units (None: none usable)"""
    transform, width, height = grid(b)
    navd = highest(units, transform, width, height)
    have = np.isfinite(navd)
    if not have.any():
        return None
    cols, rows = np.meshgrid(np.arange(width) + 0.5, np.arange(height) + 0.5)
    lons, lats = transform * (cols, rows)
    heights = navd + geoid.navd88_shift(lons, lats)   # raises GeoidError
    filled = 0.0
    if not have.all():
        cop30, _info = terrain.fetch_terrain(points)      # raises TerrainError: the fetch fails as COP30's would
        fill = cop30_on(cop30, transform, width, height)
        heights[~have] = fill[~have]
        if not np.isfinite(heights).all():
            raise terrain.TerrainError("The terrain data has gaps over this route")
        filled = float((~have).mean())
    info = {"dataset": "Lidar" if not filled else "Lidar+COP30", "source": "lidar", "requested": "lidar",
            "vertical": "NAVD88 to WGS84 (GEOID18)", "cell_m": round(CELL_ARCSEC / 3600.0 * terrain.METERS_PER_DEGREE, 1),
            "filled": round(filled, 4), "units": [list(u) for u in units],
            "bounds": [round(v, 7) for v in b], "name": file_name(b)}
    return write(heights, transform), info


def cop30(points, requested, why):
    tif, info = terrain.fetch_terrain(points)
    info = dict(info, source="cop30", requested=requested)
    if why:
        info["fallback"] = why
    return tif, info


def fetch(points, source="lidar", enqueue=None):
    """
    The terrain of the route through `points` ([(lon, lat), ...]) from the chosen source: (GeoTIFF bytes, info).

    :raises Building: lidar units are queued or being built (their states in .states): ask again
    :raises terrain.TerrainError: COP30 (or the filling of the lidar's holes) could not be fetched
    """
    if source not in SOURCES:
        raise terrain.TerrainError("terrain_source must be lidar or cop30")
    if source == "cop30":
        return cop30(points, "cop30", None)

    b = terrain.bounds(points)
    if not in_conus(b):
        return cop30(points, "lidar", "outside the conterminous US (lidar heights are converted with GEOID18)")
    if area(b) > MAX_AREA:
        return cop30(points, "lidar", "the terrain area is %.1f km2, lidar is used up to %g km2" % (area(b) / 1e6, MAX_AREA / 1e6))
    try:
        units = lidar.units_for(b, margin=0)
        states = lidar.request(units, enqueue=enqueue)
    except lidar.TooLarge:
        return cop30(points, "lidar", "the route needs more lidar units than are built at once (%d)" % lidar.MAX_UNITS)
    except (lidar.LidarError, OSError) as e:
        return cop30(points, "lidar", "the lidar surface is unavailable (%s)" % e)
    if any(st["state"] in ("queued", "building", "missing") for st in states):
        raise Building(states)
    failed = [st for st in states if st["state"] == "failed"]
    if failed:
        return cop30(points, "lidar", "a lidar unit could not be built (%s)" % (failed[0]["message"] or "failed"))

    usable, other_datum = [], 0
    for st in states:
        if st["state"] != "done":
            continue
        unit = (st["x"], st["y"])
        try:
            check = lidar.datum_check(unit)
        except lidar.LidarError as e:
            return cop30(points, "lidar", "the lidar's heights could not be checked (%s)" % e)
        if check["ok"]:
            usable.append(unit)
        else:
            other_datum += 1
            logger.warning("DJI Mission Planner: lidar unit %s left out of the terrain: %s", unit, check)
    if not usable:
        return cop30(points, "lidar", "no USGS lidar in NAVD88 here" if other_datum else "no USGS lidar here")
    try:
        made = from_units(points, b, usable)
    except geoid.GeoidError as e:
        return cop30(points, "lidar", "the GEOID18 grid could not be had (%s)" % e)
    if made is None:
        return cop30(points, "lidar", "no USGS lidar here")
    return made


def satisfies(info, source):
    """Whether a route's kept terrain (its terrain_info) was made for the chosen source: an imported terrain (Pilot 2's
    DSM) for any, one kept before this choice existed (COP30) for cop30"""
    if not info:
        return False
    if info.get("imported"):
        return True
    return info.get("requested", "cop30") == source
