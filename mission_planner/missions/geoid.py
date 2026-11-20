"""
Heights above sea level moved to the WGS84 ellipsoid, for the takeoff point Pilot 2 reads from a mission
(wpml:takeOffRefPoint: "the height of the ellipsoid shall be used", DJI's WPML reference) and writes into one, and for
the lidar terrain of an AGL route (lidar_terrain.py), whose heights are NAVD88.

Sea level here is EGM96, as SRTM GL1's heights are (the takeoff height elevation.py fetches with its ellipsoidal
twin): ellipsoidal = above sea level + the geoid's undulation, from NGA's EGM96 15-minute grid (us_nga_egm96_15.tif,
public domain) through PROJ. The grid is not in WebODM's images: it is downloaded once from PROJ's CDN into WebODM's
plugin media beside the plugin (mission_planner_data/grids), where an upgrade of the plugin leaves it, and checked
against its size and sha256 before it is used. A failure is a GeoidError: the callers go on without the conversion.

NAVD88 (USGS lidar's vertical datum in the conterminous US, on NAD83(2011)): NOAA's GEOID18 grid (us_noaa_g2018u0.tif,
public domain), downloaded and checked the same way, then NAD83(2011) to ITRF2014, which WGS84 (G2139) follows to a
few centimetres. PROJ's own choice for NAD83(2011) to WGS84 is a no-op (accuracy 2 m, pyproj 3.6.1 and 3.8.0), so the
Helmert step is pinned here, as PROJ gives it for EPSG:6319 to EPSG:7912: it lowers the heights by about 0.7-1.1 m
across CONUS. Checked on the shelved branch phase-5-3dep (2026-11-17): the grid matched NGS's GEOID18 to 2 mm.
"""
import datetime
import hashlib
import logging
import math
import os
import tempfile
import time

import numpy as np
import rasterio
import requests
from pyproj import Transformer
from pyproj.exceptions import ProjError

logger = logging.getLogger('app.logger')

GRID_NAME = "us_nga_egm96_15.tif"
GRID_URL = "https://cdn.proj.org/" + GRID_NAME
GRID_SIZE = 2710815
GRID_SHA256 = "db493027562c9b004d7220fa881f5603adada4e1c5029b933fa7de4547b0e78d"
CONNECT_TIMEOUT = 10.0
DEADLINE = 30.0         # seconds for the whole download (2.7 MB)

GEOID18_NAME = "us_noaa_g2018u0.tif"
GEOID18_SIZE = 16742155
GEOID18_SHA256 = "fa9a407ac7ee3f5a3694008e4bcd09ce9cc250452f0c3b11700a4960340abce2"
GEOID18_DEADLINE = 60.0  # seconds for the whole download (16.7 MB: about 1 s from the dev stacks)

# PROJ's operation for EPSG:6319 (NAD83(2011)) to EPSG:7912 (ITRF2014), radians in and out of the Helmert
HELMERT = ("+step +proj=cart +ellps=GRS80 "
           "+step +inv +proj=helmert +x=1.0053 +y=-1.90921 +z=-0.54157 +rx=0.02678138 +ry=-0.00042027 "
           "+rz=0.01093206 +s=0.00036891 +dx=0.00079 +dy=-0.0006 +dz=-0.00144 +drx=6.667e-05 +dry=-0.00075744 "
           "+drz=-5.133e-05 +ds=-7.201e-05 +t_epoch=2010 +convention=coordinate_frame "
           "+step +inv +proj=cart +ellps=GRS80")


class GeoidError(Exception):
    pass


def grid_folder():
    from app.plugins.functions import get_plugins_persistent_path
    from ..routes import DATA_FOLDER
    return get_plugins_persistent_path(DATA_FOLDER, "grids")


def _readable(path, size):
    try:
        if os.path.getsize(path) != size:
            return False
        with rasterio.open(path) as src:
            return src.crs is not None and src.count == 1
    except (OSError, rasterio.errors.RasterioError):
        return False


def _download(path, name, size_expected, sha256, seconds):
    folder = os.path.dirname(path)
    deadline = time.monotonic() + seconds
    try:
        os.makedirs(folder, exist_ok=True)
        fd, part = tempfile.mkstemp(prefix=name + ".", suffix=".part", dir=folder)
    except OSError as e:
        raise GeoidError("Could not write the geoid grid: %s" % e) from e
    try:
        digest, size = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as out, requests.get("https://cdn.proj.org/" + name, stream=True,
                                                      timeout=(CONNECT_TIMEOUT, seconds)) as res:
            if res.status_code != 200:
                raise GeoidError("The geoid grid's download returned an error (%d)" % res.status_code)
            for chunk in res.iter_content(1 << 16):
                size += len(chunk)
                if size > size_expected:
                    raise GeoidError("The geoid grid's download is larger than expected")
                if time.monotonic() > deadline:
                    raise GeoidError("The geoid grid's download took more than %g s" % seconds)
                digest.update(chunk)
                out.write(chunk)
        if size != size_expected or digest.hexdigest() != sha256:
            raise GeoidError("The geoid grid's download is not the expected file")
        if not _readable(part, size_expected):
            raise GeoidError("The geoid grid's download does not read")
        os.replace(part, path)
    except requests.RequestException as e:
        raise GeoidError("Could not download the geoid grid (%s)" % type(e).__name__) from e
    except OSError as e:
        raise GeoidError("Could not write the geoid grid: %s" % e) from e
    finally:
        if os.path.exists(part):
            os.remove(part)


def _ensure(name, size, sha256, seconds):
    path = os.path.join(grid_folder(), name)
    if os.path.exists(path):
        if _readable(path, size):
            return path
        logger.warning("The cached geoid grid %s does not read: set aside, downloaded again", path)
        try:
            os.replace(path, path + ".bad")
        except OSError as e:
            raise GeoidError("Could not set the unreadable geoid grid aside: %s" % e) from e
    _download(path, name, size, sha256, seconds)
    return path


def ensure_grid():
    """
    The path of the EGM96 grid, downloaded first when it is not there; a cached grid that does not read is set aside
    (<name>.bad) and downloaded again.

    :raises GeoidError: the grid could not be downloaded, checked or written
    """
    return _ensure(GRID_NAME, GRID_SIZE, GRID_SHA256, DEADLINE)


def ensure_geoid18():
    """The path of the GEOID18 grid, as ensure_grid; raises GeoidError"""
    return _ensure(GEOID18_NAME, GEOID18_SIZE, GEOID18_SHA256, GEOID18_DEADLINE)


_transformers = {}


def undulation(lat, lon):
    """
    The EGM96 geoid's height above the WGS84 ellipsoid at (lat, lon), meters: what is added to a height above sea
    level to make it ellipsoidal.

    :raises GeoidError: the grid could not be had, or PROJ could not use it there
    """
    grid = ensure_grid()
    try:
        t = _transformers.get(grid)
        if t is None:
            t = _transformers[grid] = Transformer.from_pipeline(
                "+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad "
                "+step +proj=vgridshift +grids=%s +multiplier=1 "
                "+step +proj=unitconvert +xy_in=rad +xy_out=deg" % grid)
        _x, _y, n = t.transform(float(lon), float(lat), 0.0)
    except ProjError as e:
        raise GeoidError("PROJ could not use the geoid grid: %s" % e) from e
    if not math.isfinite(n) or abs(n) > 200:
        raise GeoidError("The geoid grid has no undulation at %.6f, %.6f" % (lat, lon))
    return n


def to_ellipsoidal(lat, lon, height):
    """A height above sea level (EGM96) at (lat, lon) as a WGS84-ellipsoidal one; raises GeoidError"""
    return height + undulation(lat, lon)


def decimal_year(when=None):
    when = when or datetime.datetime.now(datetime.timezone.utc)
    start = datetime.datetime(when.year, 1, 1, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(when.year + 1, 1, 1, tzinfo=datetime.timezone.utc)
    return when.year + (when - start).total_seconds() / (end - start).total_seconds()


def navd88_pipeline(grid):
    """NAD83(2011) longitude, latitude and NAVD88 height (degrees, meters) to WGS84 longitude, latitude and
    ellipsoidal height"""
    return Transformer.from_pipeline(
        "+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad "
        "+step +proj=vgridshift +grids=%s +multiplier=1 %s "
        "+step +proj=unitconvert +xy_in=rad +xy_out=deg" % (grid, HELMERT))


def navd88_shift(lons, lats, grid=None, epoch=None):
    """
    What is added to a NAVD88 height at each (lon, lat) to make it WGS84-ellipsoidal: GEOID18's height there and the
    NAD83(2011) to WGS84 step (the change of a zero height, the same for any height to well under a millimetre).

    :param lons, lats: arrays of degrees
    :param grid: the GEOID18 grid's path (ensure_geoid18() when left out)
    :return: an array of meters, the shape of lons
    :raises GeoidError: the grid could not be had, or a point is off it (outside the conterminous US)
    """
    grid = grid or ensure_geoid18()
    epoch = decimal_year() if epoch is None else epoch
    lons, lats = np.asarray(lons, dtype="float64"), np.asarray(lats, dtype="float64")
    try:
        _x, _y, z, _t = navd88_pipeline(grid).transform(lons.ravel(), lats.ravel(), np.zeros(lons.size),
                                                       np.full(lons.size, epoch))
    except ProjError as e:
        raise GeoidError("PROJ could not move the heights to the ellipsoid: %s" % e) from e
    z = np.asarray(z, dtype="float64").reshape(lons.shape)
    if not np.isfinite(z).all() or (np.abs(z) > 200).any():
        raise GeoidError("The GEOID18 grid does not cover the terrain (it covers the conterminous US)")
    return z
