"""
The lidar surface of the 3D view: where USGS 3DEP lidar covers a route, the editors' 3D view raises the ground to a 1 m
surface with its trees and buildings (the highest lidar return of each cell, a DSM), instead of the elevation tiles of
AWS Terrain Tiles (Terrarium), which are the bare shape of the ground.

The lidar is public on AWS as EPT (s3-us-west-2.amazonaws.com/usgs-lidar-public/<project>/ept.json); which project
covers a place says the index hobuinc/usgs-lidar keeps (boundaries/resources.geojson, regenerated daily). PDAL, which
both WebODM images have, reads the EPT at 1 m and writes the DSM; the surface is then cut into Terrarium tiles (zoom 15
to 18) that MapLibre's terrain reads. Heights are NAVD88, as Terrarium's are in the US: they are for display only.

The work is done by zoom-15 web-mercator tiles, "units" (about 0.9 km a side in the middle of the US), shared by every
route nearby: a route asks for the units around it (request), WebODM's worker builds the missing ones (build_units),
and the editor polls their states (states). Everything lives in WebODM's plugin media beside the routes' terrain:

    mission_planner_data/lidar/index/resources.geojson    the index, refreshed when older than INDEX_MAX_AGE
    mission_planner_data/lidar/units/<x>_<y>/status.json  queued, building, done, none (no lidar there) or failed
    mission_planner_data/lidar/units/<x>_<y>/dsm.tif      the unit's DSM, with OVERLAP meters around it
    mission_planner_data/lidar/units/<x>_<y>/tiles/<z>/<x>/<y>.png
    mission_planner_data/lidar/units/<x>_<y>/used         its time: when a route last asked for the unit
    mission_planner_data/lidar/units/<x>_<y>/usage.json   the unit's bytes on disk, kept when its tiles are made

The folder is kept under MAX_BYTES: after each build, the units a route asked for longest ago are removed until it
fits (evict), never one queued or building, nor one the build just made. The settings page's size adds up the units'
usage.json, not every tile (usage).

A unit's tiles are its own lidar, faded into AWS's tile over FEATHER meters where no lidar reaches: at holes, and at
its edges facing a neighbour that has none built. When a neighbour is built, the unit's tiles are made again, so
two built units meet lidar to lidar.

Unattended (in the worker): every wait has a deadline (PDAL is stopped, then killed), every write goes to a temporary
name renamed into place, a state that does not read is set aside and the unit built again, a failure is written into
the unit's state (and retried by a request after RETRY_AFTER), and a unit whose build died with its worker is taken
over once its state is older than STALE_AFTER.
"""
import errno
import fcntl
import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time

import numpy as np
import requests

from app.plugins.functions import get_plugins_persistent_path

from .routes import DATA_FOLDER

logger = logging.getLogger('app.logger')

INDEX_URL = "https://raw.githubusercontent.com/hobuinc/usgs-lidar/master/boundaries/resources.geojson"
TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
PDAL = "pdal"

UNIT_ZOOM = 15
TILE_ZOOMS = (15, 16, 17, 18)
MAX_UNITS = 12              # a request: about 10 km2, about 1.2 GB of lidar read at 1 m
MARGIN = 200.0              # meters of surface around what the route covers
OVERLAP = 40.0              # meters of lidar read around a unit, so that its edges blend with its neighbours'
FEATHER = 40.0              # meters over which lidar fades into AWS's terrain
READ_RESOLUTION = 1.0       # meters on the ground: the EPT's detail read (101 MB a km2 measured, 2026-11-18)
CELL = 1.0                  # meters on the ground: the DSM's cells
SURFACE_VERSION = 2         # how the units' DSM and tiles are made; a unit built by an older one is built again once
                            # (2: each point counts in its own cell only, and far tiles average, Phase 22)
NOISE_CLASSES = (7, 18)     # ASPRS low and high noise
# A unit's heights are taken as NAVD88 meters (what lidar_terrain.py converts) only when its lowest lidar lies within
# DATUM_TOLERANCE of AWS's bare-ground tile (NAVD88 in the US, as the spike measured): the EPT says nothing of its
# vertical datum (its srs is EPSG:3857 alone, checked 2026-11-18), and ellipsoidal heights would be 8 to 50 m off in
# CONUS, feet 3.28 times. DATUM_PERCENTILE of the lidar's lowest point per AWS pixel minus AWS's height is compared:
# low, so that trees and roofs over most of a unit do not hide its roads and fields.
DATUM_TOLERANCE = 5.0
DATUM_PERCENTILE = 2.0
DATUM_MIN_CELLS = 50

HTTP_TIMEOUT = 60.0
INDEX_MAX_AGE = 30 * 24 * 3600
INDEX_MAX_BYTES = 64 * 1024 * 1024
PDAL_DEADLINE = 300.0
KILL_GRACE = 10.0
RETRY_AFTER = 600.0
STALE_AFTER = 1800.0        # a queued or building state older than this is taken over (its worker died, or none ran)
MAX_BYTES = 5 * 1024 ** 3   # the lidar folder's cap, the index included (decided with the user 2026-11-19)

R = 6378137.0
HALF = math.pi * R
STATES = ("queued", "building", "done", "none", "failed")


class LidarError(Exception):
    pass


class TooLarge(LidarError):
    pass


# -- places ------------------------------------------------------------------------------------------------------------

def root():
    return get_plugins_persistent_path(DATA_FOLDER, "lidar")


def unit_folder(unit):
    return os.path.join(root(), "units", "%d_%d" % unit)


def to_mercator(lon, lat):
    lat = max(min(lat, 85.0), -85.0)
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def to_lonlat(x, y):
    return math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)


def tile_size(z):
    return 2 * HALF / 2 ** z


def tile_bounds(z, x, y):
    """(left, bottom, right, top) of a web-mercator tile, in EPSG:3857 meters"""
    s = tile_size(z)
    return (-HALF + x * s, HALF - (y + 1) * s, -HALF + (x + 1) * s, HALF - y * s)


def scale(lat):
    """EPSG:3857 meters a ground meter at latitude `lat`"""
    return 1 / math.cos(math.radians(lat))


def units_for(bounds, margin=MARGIN):
    """
    The units a route needs: those within `margin` meters of `bounds` [west, south, east, north] (degrees). TooLarge
    when more than MAX_UNITS.
    """
    west, south, east, north = (float(v) for v in bounds)
    if not (-180 <= west <= east <= 180 and -85 <= south <= north <= 85):
        raise LidarError("bounds must be [west, south, east, north] in degrees")
    k = scale((south + north) / 2)
    left, bottom = to_mercator(west, south)
    right, top = to_mercator(east, north)
    left, bottom, right, top = left - margin * k, bottom - margin * k, right + margin * k, top + margin * k
    s = tile_size(UNIT_ZOOM)
    x0, x1 = int((left + HALF) // s), int((right + HALF) // s)
    y0, y1 = int((HALF - top) // s), int((HALF - bottom) // s)
    count = (x1 - x0 + 1) * (y1 - y0 + 1)
    if count > MAX_UNITS:
        raise TooLarge("the area is too large for the lidar surface (%d units of about 1 km2, at most %d)" % (count, MAX_UNITS))
    return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def tile_unit(z, x, y):
    """The unit a tile of zoom 15 to 18 lies in"""
    d = z - UNIT_ZOOM
    return (x >> d, y >> d)


# -- states ------------------------------------------------------------------------------------------------------------

def _write_json(path, value):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(value, f)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _set_aside(path):
    """A saved file that does not read is renamed, never fatal: the unit is built again"""
    try:
        os.replace(path, path + ".bad")
        logger.warning("DJI Mission Planner lidar: set aside %s, it did not read", path)
    except OSError:
        pass


def read_state(unit):
    """The unit's saved state ({"state", "time", "message"}), or None when there is none (or it did not read)"""
    path = os.path.join(unit_folder(unit), "status.json")
    try:
        with open(path) as f:
            value = json.load(f)
        if not isinstance(value, dict) or value.get("state") not in STATES or not isinstance(value.get("time"), (int, float)):
            raise ValueError("not a state")
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        _set_aside(path)
        return None
    if value["state"] == "done" and not os.path.isfile(os.path.join(unit_folder(unit), "dsm.tif")):
        _set_aside(path)
        return None
    return value


def write_state(unit, state, message=""):
    _write_json(os.path.join(unit_folder(unit), "status.json"),
                {"state": state, "time": time.time(), "message": message, "version": SURFACE_VERSION})


def _needs_build(st, now):
    if st is None:
        return True
    if st["state"] == "failed":
        return now - st["time"] > RETRY_AFTER
    if st["state"] in ("queued", "building"):
        return now - st["time"] > STALE_AFTER
    if st["state"] == "done":
        return st.get("version", 1) < SURFACE_VERSION
    return False


def states(units):
    """[{"x", "y", "state", "message", "v"}] for the units, "missing" for one never asked for; v: the version of a built
    unit's tiles (tiles_version), which the browser puts in their URLs"""
    out = []
    for unit in units:
        st = read_state(unit)
        state = st["state"] if st else "missing"
        out.append({"x": unit[0], "y": unit[1], "state": state, "message": st.get("message", "") if st else "",
                    "v": tiles_version(unit) if state == "done" else 0})
    return out


def tiles_version(unit):
    """When the unit's tiles were last made (microseconds, a whole number JavaScript keeps exactly; make_tiles writes it
    once they all are), 0 when unknown (made before tiles had a version, or the file does not read): the tiles' URLs
    change with it, so that a browser that keeps them an hour reads the new ones once a unit is built again or its
    tiles are made again for a neighbour"""
    try:
        with open(os.path.join(unit_folder(unit), "tiles.json")) as f:
            made = json.load(f).get("made")
        return made if isinstance(made, int) and not isinstance(made, bool) and made > 0 else 0
    except (OSError, ValueError, AttributeError):
        return 0


def _claim(unit, now):
    """Marks the unit queued if it needs a build; False when another request did it first (or it needs none)"""
    folder = unit_folder(unit)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if not _needs_build(read_state(unit), now):
                return False
            write_state(unit, "queued")
            return True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def request(units, enqueue=None):
    """Queues the units that need a build (one worker job for them all) and answers every unit's state. Records that
    they were used (the cap removes those used longest ago first)."""
    mark_used(units)
    now = time.time()
    claimed = [unit for unit in units if _claim(unit, now)]
    if claimed:
        try:
            (enqueue or _enqueue)(claimed)
        except Exception as e:  # the queue (Celery's broker) is down: say so in the units' states
            logger.exception("DJI Mission Planner lidar: could not queue a build")
            for unit in claimed:
                write_state(unit, "failed", "the build could not be queued (%s)" % type(e).__name__)
    return states(units)


def build_job(module_name, units):
    """Run by WebODM's worker (run_function_async evaluates this function's source: imports go inside)"""
    import importlib
    importlib.import_module(module_name).build_units([tuple(u) for u in units])


def _enqueue(units):
    from app.plugins.worker import run_function_async
    run_function_async(build_job, __name__, [list(u) for u in units])


# -- the index ---------------------------------------------------------------------------------------------------------

def _get(url, stream=False):
    return requests.get(url, timeout=HTTP_TIMEOUT, stream=stream)


def _download_index(path):
    r = _get(INDEX_URL, stream=True)
    if r.status_code != 200:
        raise LidarError("the lidar index answered %d" % r.status_code)
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        size = 0
        deadline = time.monotonic() + HTTP_TIMEOUT * 3
        with os.fdopen(fd, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                size += len(chunk)
                if size > INDEX_MAX_BYTES:
                    raise LidarError("the lidar index is larger than %d MB" % (INDEX_MAX_BYTES >> 20))
                if time.monotonic() > deadline:
                    raise LidarError("the lidar index took too long to download")
                f.write(chunk)
        _parse_index(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _parse_index(path):
    """[(name, url, year, polygons as GEOS)] from the index file; LidarError when it is not one"""
    from django.contrib.gis.geos import GEOSGeometry
    try:
        with open(path) as f:
            data = json.load(f)
        out = []
        for feature in data["features"]:
            p = feature["properties"]
            years = [int(y) for y in re.findall(r"(?<!\d)(19[89]\d|20\d\d)(?!\d)", p["name"])]
            out.append((p["name"], p["url"], years[0] if years else 0, GEOSGeometry(json.dumps(feature["geometry"]), srid=4326)))
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise LidarError("the lidar index does not read (%s)" % type(e).__name__) from e
    if not out:
        raise LidarError("the lidar index lists no lidar")
    return out


_index_cache = {"mtime": None, "entries": None}


def index():
    """The index's entries; downloaded when missing or older than INDEX_MAX_AGE (a failed refresh keeps the old one)"""
    path = os.path.join(root(), "index", "resources.geojson")
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        age = None
    if age is None or age > INDEX_MAX_AGE:
        try:
            _download_index(path)
        except (LidarError, requests.RequestException, OSError) as e:
            if age is None:
                raise LidarError("lidar index unavailable: %s" % without_url(str(e))) from e
            logger.warning("DJI Mission Planner lidar: the index could not be refreshed, the old one is kept: %s", e)
    mtime = os.path.getmtime(path)
    if _index_cache["mtime"] != mtime:
        try:
            entries = _parse_index(path)
        except LidarError:
            _set_aside(path)
            raise
        _index_cache.update(mtime=mtime, entries=entries)
    return _index_cache["entries"]


def without_url(text):
    return re.sub(r"https?://\S+", "[URL]", text)


# A project covering at least this share of what the best-covering one covers counts as covering the unit as well
COVER_SHARE = 0.95


def project_for(unit):
    """(name, url) of the lidar project for the unit, or None: of the projects covering about as much of it as the
    best-covering one (COVER_SHARE), the newest (by the first year in its name), so that a newer project touching only
    a corner does not leave the rest of the unit empty"""
    from django.contrib.gis.geos import Polygon
    left, bottom, right, top = tile_bounds(UNIT_ZOOM, *unit)
    west, south = to_lonlat(left, bottom)
    east, north = to_lonlat(right, top)
    box = Polygon.from_bbox((west, south, east, north))
    box.srid = 4326
    covering = [(year, box.intersection(geom).area, name, url) for name, url, year, geom in index() if geom.intersects(box)]
    if not covering:
        return None
    best = max(area for _year, area, _name, _url in covering)
    covering = sorted((c for c in covering if c[1] >= COVER_SHARE * best), reverse=True)
    return covering[0][2], covering[0][3]


# -- building ----------------------------------------------------------------------------------------------------------

def run_pdal(pipeline, deadline=None):
    """Runs a PDAL pipeline; LidarError when it fails or overruns its deadline (stopped, then killed)"""
    deadline = PDAL_DEADLINE if deadline is None else deadline
    try:
        proc = subprocess.Popen([PDAL, "pipeline", "--stdin"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as e:
        raise LidarError("PDAL could not be started (%s)" % e.strerror) from e
    try:
        _out, err = proc.communicate(json.dumps(pipeline), timeout=deadline)
    except subprocess.TimeoutExpired:
        _stop(proc)
        raise LidarError("reading the lidar took longer than %d s" % deadline) from None
    if proc.returncode != 0:
        lines = [line for line in (err or "").strip().splitlines() if line.strip()]
        raise LidarError("PDAL failed: %s" % without_url(lines[-1] if lines else "exit %d" % proc.returncode)[:300])


def _stop(proc):
    for sig, wait in ((signal.SIGTERM, KILL_GRACE), (signal.SIGKILL, KILL_GRACE)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.communicate(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def dsm_pipeline(url, unit, out):
    left, bottom, right, top = tile_bounds(UNIT_ZOOM, *unit)
    lat = to_lonlat(0, (bottom + top) / 2)[1]
    k = scale(lat)
    o = OVERLAP * k
    cell = CELL * k
    n = int(math.ceil((right - left + 2 * o) / cell))
    return [
        {"type": "readers.ept", "filename": url, "resolution": READ_RESOLUTION * k,
         "bounds": "([%.3f, %.3f], [%.3f, %.3f])" % (left - o, left - o + n * cell, top + o - n * cell, top + o)},
        {"type": "filters.range", "limits": ",".join("Classification![%d:%d]" % (c, c) for c in NOISE_CLASSES)},
        # radius: half a cell's diagonal, each point in its own cell (PDAL's default, the cell times the square root of
        # two, spreads a roof's height into every cell round it, about 1.4 m beyond its walls); window_size fills the
        # cells left empty
        {"type": "writers.gdal", "filename": out, "output_type": "max", "resolution": cell, "radius": cell * math.sqrt(2) / 2, "window_size": 3,
         "nodata": -9999, "data_type": "float32", "gdaldriver": "GTiff", "gdalopts": "COMPRESS=DEFLATE,PREDICTOR=3",
         "origin_x": left - o, "origin_y": top + o - n * cell, "width": n, "height": n, "override_srs": "EPSG:3857"},
    ]


def build_units(units):
    for i, unit in enumerate(units):
        _refresh_queued(units[i:])
        try:
            build_unit(unit)
        except Exception as e:  # every failure ends in the unit's state, the next unit is built
            logger.exception("DJI Mission Planner lidar: unit %s failed", unit)
            try:
                write_state(unit, "failed", str(e) if isinstance(e, LidarError) else "unexpected error (%s)" % type(e).__name__)
            except OSError:
                logger.exception("DJI Mission Planner lidar: could not write the state of unit %s", unit)
    try:
        evict(keep=units)
    except Exception:  # the folder stays over its cap until the next build: not these units' failure
        logger.exception("DJI Mission Planner lidar: could not keep the lidar folder under its cap")


def _refresh_queued(units):
    """The units still waiting in this batch marked queued now, so that a long batch does not leave them stale (taken
    over by another request, or removed by the cap, while they wait)"""
    for unit in units:
        try:
            st = read_state(unit)
            if st is not None and st["state"] == "queued":
                write_state(unit, "queued", st.get("message", ""))
        except OSError:
            logger.exception("DJI Mission Planner lidar: could not refresh the state of unit %s", unit)


def build_unit(unit):
    import rasterio
    write_state(unit, "building")
    project = project_for(unit)
    if project is None:
        write_state(unit, "none", "no USGS lidar here")
        return
    name, url = project
    folder = unit_folder(unit)
    work = tempfile.mkdtemp(dir=folder, prefix=".build-")
    try:
        dsm = os.path.join(work, "dsm.tif")
        run_pdal(dsm_pipeline(url, unit, dsm))
        try:
            with rasterio.open(dsm) as src:
                values = src.read(1)
        except Exception as e:  # rasterio raises several kinds for a broken file
            raise LidarError("PDAL wrote no readable DSM") from e
        if not (values > -9000).any():
            write_state(unit, "none", "the lidar has no points here")
            return
        os.replace(dsm, os.path.join(folder, "dsm.tif"))
    except OSError as e:
        if e.errno == errno.ENOSPC:
            raise LidarError("the disk is full") from e
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    write_state(unit, "building", name)
    make_tiles(unit)
    write_state(unit, "done", name)
    for neighbour in neighbours(unit):
        st = read_state(neighbour)
        if st and st["state"] == "done":
            try:
                make_tiles(neighbour)
            except Exception:  # the neighbour keeps its old tiles (faded at this edge): not this unit's failure
                logger.exception("DJI Mission Planner lidar: the tiles of unit %s could not be made again", neighbour)


def neighbours(unit):
    x, y = unit
    return [(x + dx, y + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy]


# -- tiles -------------------------------------------------------------------------------------------------------------

def decode(rgb):
    rgb = rgb.astype("float64")
    return rgb[0] * 256 + rgb[1] + rgb[2] / 256 - 32768


def encode(heights):
    v = np.clip(np.asarray(heights, dtype="float64") + 32768, 0, 65535.996)
    r = np.floor(v / 256)
    g = np.floor(v) - r * 256
    b = np.floor((v - np.floor(v)) * 256)
    return np.stack([r, g, b]).astype("uint8")


def _png(rgb):
    from rasterio.io import MemoryFile
    with MemoryFile() as m:
        with m.open(driver="PNG", width=rgb.shape[2], height=rgb.shape[1], count=3, dtype="uint8") as d:
            d.write(rgb)
        return m.read()


def _read_png(content):
    import warnings
    from rasterio.errors import NotGeoreferencedWarning
    from rasterio.io import MemoryFile
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with MemoryFile(content) as m, m.open() as d:
            return d.read()[:3]


def terrarium_unit_tile(unit):
    """AWS's zoom-15 Terrarium heights of the unit (256 x 256)"""
    try:
        r = _get(TERRARIUM_URL.format(z=UNIT_ZOOM, x=unit[0], y=unit[1]))
    except requests.RequestException as e:
        raise LidarError("AWS Terrain Tiles could not be reached (%s)" % type(e).__name__) from e
    if r.status_code != 200:
        raise LidarError("AWS Terrain Tiles answered %d" % r.status_code)
    try:
        return decode(_read_png(r.content))
    except Exception as e:
        raise LidarError("AWS Terrain Tiles sent a tile that does not read") from e


def weights(valid, unit, built_neighbours, cell_size, origin, k):
    """
    How much lidar each DSM cell shows (0 to 1): fading over FEATHER meters to 0 at holes and where the unit meets a
    neighbour with no lidar built (its overlap there counts as a hole); 1 elsewhere.
    `origin` is the DSM's (left, top) and `cell_size` its cells in EPSG:3857 meters.
    """
    from scipy.ndimage import distance_transform_edt
    ok = valid.copy()
    left, bottom, right, top = tile_bounds(UNIT_ZOOM, *unit)
    h, w = ok.shape
    xs = origin[0] + (np.arange(w) + 0.5) * cell_size
    ys = origin[1] - (np.arange(h) + 0.5) * cell_size
    col = np.where(xs < left, -1, np.where(xs > right, 1, 0))
    row = np.where(ys > top, -1, np.where(ys < bottom, 1, 0))
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if (dx or dy) and (unit[0] + dx, unit[1] + dy) not in built_neighbours:
                ok[np.ix_(row == dy, col == dx)] = False
    distance = distance_transform_edt(np.pad(ok, 1))[1:-1, 1:-1] * cell_size / k   # ground meters to the nearest hole
    return np.clip(distance / FEATHER, 0, 1)


def make_tiles(unit):
    """The unit's Terrarium tiles, zoom 15 to 18, from its DSM and AWS's tile, written in place one by one"""
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject
    folder = unit_folder(unit)
    with open(os.path.join(folder, ".tiles-lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            built = {n for n in neighbours(unit) if (read_state(n) or {}).get("state") == "done"}
            with rasterio.open(os.path.join(folder, "dsm.tif")) as src:
                dsm = src.read(1).astype("float64")
                transform, crs = src.transform, src.crs
            valid = dsm > -9000
            k = scale(to_lonlat(0, (tile_bounds(UNIT_ZOOM, *unit)[1] + tile_bounds(UNIT_ZOOM, *unit)[3]) / 2)[1])
            weight = weights(valid, unit, built, transform.a, (transform.c, transform.f), k)
            dsm[~valid] = 0
            aws = terrarium_unit_tile(unit)
            aws_transform = from_bounds(*tile_bounds(UNIT_ZOOM, *unit), 256, 256)
            for z in TILE_ZOOMS:
                d = z - UNIT_ZOOM
                for ty in range(unit[1] << d, (unit[1] + 1) << d):
                    for tx in range(unit[0] << d, (unit[0] + 1) << d):
                        t = from_bounds(*tile_bounds(z, tx, ty), 256, 256)
                        fine = tile_size(z) / 256 < transform.a
                        lidar = np.zeros((256, 256))
                        w = np.zeros((256, 256))
                        ground = np.zeros((256, 256))
                        reproject(dsm, lidar, src_transform=transform, src_crs=crs, dst_transform=t, dst_crs=crs,
                                  resampling=Resampling.bilinear if fine else Resampling.average)
                        reproject(weight, w, src_transform=transform, src_crs=crs, dst_transform=t, dst_crs=crs,
                                  resampling=Resampling.bilinear if fine else Resampling.min)
                        reproject(aws, ground, src_transform=aws_transform, src_crs=crs, dst_transform=t, dst_crs=crs,
                                  resampling=Resampling.bilinear)
                        _write_tile(folder, z, tx, ty, _png(encode(ground * (1 - w) + lidar * w)))
            _write_json(os.path.join(folder, "tiles.json"), {"made": time.time_ns() // 1000})
            _record_size(unit)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _write_tile(folder, z, x, y, content):
    path = os.path.join(folder, "tiles", str(z), str(x), "%d.png" % y)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def tile_path(z, x, y):
    """The file of a built tile, or None"""
    if z not in TILE_ZOOMS or not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return None
    unit = tile_unit(z, x, y)
    st = read_state(unit)
    if not st or st["state"] != "done":
        return None
    path = os.path.join(unit_folder(unit), "tiles", str(z), str(x), "%d.png" % y)
    return path if os.path.isfile(path) else None


# -- the datum check ---------------------------------------------------------------------------------------------------

def datum_check(unit):
    """
    {"ok", "offset", "cells"}: whether the built unit's heights are NAVD88 meters, by DATUM_PERCENTILE of its lowest
    lidar per AWS zoom-15 pixel minus AWS's height there ("offset", meters), over "cells" pixels with lidar. Kept in the
    unit's datum.json for its DSM (made again when the DSM is). LidarError when AWS's tile cannot be had.
    """
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject
    folder = unit_folder(unit)
    dsm_path, cache = os.path.join(folder, "dsm.tif"), os.path.join(folder, "datum.json")
    try:
        mtime = os.path.getmtime(dsm_path)
    except OSError as e:
        raise LidarError("the unit's DSM is gone") from e
    try:
        with open(cache) as f:
            kept = json.load(f)
        if kept.get("dsm_mtime") == mtime and isinstance(kept.get("ok"), bool):
            return {"ok": kept["ok"], "offset": kept.get("offset"), "cells": kept.get("cells")}
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with rasterio.open(dsm_path) as src:
            dsm = src.read(1).astype("float64")
            transform, crs = src.transform, src.crs
    except Exception as e:  # rasterio raises several kinds for a broken file
        raise LidarError("the unit's DSM does not read") from e
    aws = terrarium_unit_tile(unit)
    lowest = np.full((256, 256), np.nan)
    reproject(dsm, lowest, src_transform=transform, src_crs=crs, src_nodata=-9999,
              dst_transform=from_bounds(*tile_bounds(UNIT_ZOOM, *unit), 256, 256), dst_crs=crs, dst_nodata=np.nan,
              resampling=Resampling.min)
    diff = (lowest - aws)[np.isfinite(lowest) & (lowest > -9000)]
    if diff.size < DATUM_MIN_CELLS:
        result = {"ok": False, "offset": None, "cells": int(diff.size)}
    else:
        offset = float(np.percentile(diff, DATUM_PERCENTILE))
        result = {"ok": abs(offset) <= DATUM_TOLERANCE, "offset": round(offset, 2), "cells": int(diff.size)}
    try:
        _write_json(cache, dict(result, dsm_mtime=mtime))
    except OSError:
        logger.warning("DJI Mission Planner lidar: the datum check of unit %s could not be kept", unit)
    return result


# -- the settings page -------------------------------------------------------------------------------------------------

def usage():
    """(units built, bytes on disk) of the lidar surface, the index included: each unit's recorded size (unit_bytes)"""
    built, size = 0, _index_bytes()
    for unit in _units():
        st = read_state(unit)
        built += bool(st and st["state"] == "done")
        size += unit_bytes(unit, st)
    return built, size


def _unit_of(folder):
    x, y = os.path.basename(folder).split("_")
    return int(x), int(y)


def _units():
    """The units that have a folder (one being removed has another name)"""
    try:
        names = os.listdir(os.path.join(root(), "units"))
    except FileNotFoundError:
        return []
    out = []
    for name in names:
        try:
            out.append(_unit_of(name))
        except ValueError:
            continue
    return out


def _index_bytes():
    folder = os.path.join(root(), "index")
    try:
        return sum(os.path.getsize(os.path.join(folder, name)) for name in os.listdir(folder))
    except OSError:
        return 0


def _walk_size(folder):
    size = 0
    for path, _dirs, files in os.walk(folder):
        for name in files:
            try:
                size += os.path.getsize(os.path.join(path, name))
            except OSError:
                pass
    return size


def _record_size(unit):
    """Walks the unit's folder once and keeps its size in usage.json (made again with its tiles)"""
    folder = unit_folder(unit)
    size = _walk_size(folder)
    try:
        _write_json(os.path.join(folder, "usage.json"), {"bytes": size})
    except OSError:
        logger.warning("DJI Mission Planner lidar: the size of unit %s could not be kept", unit)
    return size


def unit_bytes(unit, st=None):
    """The unit's bytes on disk: its usage.json; a built unit without one (built before sizes were kept) is walked
    once and gets one, a unit queued or building is walked (its few files)"""
    try:
        with open(os.path.join(unit_folder(unit), "usage.json")) as f:
            size = json.load(f).get("bytes")
        if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
            return size
    except (OSError, ValueError, AttributeError):
        pass
    if st and st["state"] == "done":
        return _record_size(unit)
    return _walk_size(unit_folder(unit))


# -- the cap -----------------------------------------------------------------------------------------------------------

def mark_used(units, when=None):
    """Records that a route asked for the units now (or at `when`), in each unit's `used` file's time"""
    when = time.time() if when is None else when
    for unit in units:
        path = os.path.join(unit_folder(unit), "used")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a"):
                pass
            os.utime(path, (when, when))
        except OSError:
            logger.warning("DJI Mission Planner lidar: the use of unit %s could not be recorded", unit)


def last_used(unit):
    """When a route last asked for the unit; its state's time when that was not recorded, else 0"""
    try:
        return os.path.getmtime(os.path.join(unit_folder(unit), "used"))
    except OSError:
        st = read_state(unit)
        return st["time"] if st else 0.0


def _busy(st, now):
    return bool(st and st["state"] in ("queued", "building") and now - st["time"] <= STALE_AFTER)


def _remove_unit(unit, now):
    """Removes the unit's folder, unless a request queued it meanwhile (under the lock _claim takes)"""
    folder = unit_folder(unit)
    aside = os.path.join(os.path.dirname(folder), ".removing-%d_%d-%d" % (unit[0], unit[1], os.getpid()))
    try:
        with open(os.path.join(folder, ".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if _busy(read_state(unit), now):
                    return False
                os.replace(folder, aside)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    except OSError:     # gone already (another eviction), or it cannot be moved: kept
        return False
    shutil.rmtree(aside, ignore_errors=True)
    return True


def evict(keep=()):
    """
    While the lidar folder is over MAX_BYTES, removes the units used longest ago (last_used), never one queued or
    building, nor one of `keep` (the units a build just made). The built neighbours of a removed unit get their tiles
    made again, faded at the edge it leaves. Run by the worker after each build. Returns the units removed.
    """
    keep = {tuple(u) for u in keep}
    now = time.time()
    total, candidates = _index_bytes(), []
    for unit in _units():
        st = read_state(unit)
        size = unit_bytes(unit, st)
        total += size
        if unit not in keep and not _busy(st, now):
            candidates.append((last_used(unit), unit, size))
    removed = []
    for _used, unit, size in sorted(candidates):
        if total <= MAX_BYTES:
            break
        if _remove_unit(unit, now):
            total -= size
            removed.append(unit)
    if removed:
        logger.info("DJI Mission Planner lidar: removed %d units used longest ago, over the %d GB cap", len(removed), MAX_BYTES // 1024 ** 3)
    for neighbour in sorted({n for u in removed for n in neighbours(u)} - set(removed)):
        if (read_state(neighbour) or {}).get("state") == "done":
            try:
                make_tiles(neighbour)
            except Exception:  # the neighbour keeps lidar to the removed unit's edge: a seam, not a failure
                logger.exception("DJI Mission Planner lidar: the tiles of unit %s could not be made again", neighbour)
    return removed


def clear():
    """Removes every unit (not the index); False, removing nothing, while a unit is queued or building"""
    units = os.path.join(root(), "units")
    if not os.path.isdir(units):
        return True
    now = time.time()
    for name in os.listdir(units):
        try:
            st = read_state(_unit_of(os.path.join(units, name)))
        except ValueError:
            continue
        if st and st["state"] in ("queued", "building") and now - st["time"] <= STALE_AFTER:
            return False
    aside = units + ".removing-%d" % os.getpid()
    os.replace(units, aside)
    shutil.rmtree(aside, ignore_errors=True)
    return True
