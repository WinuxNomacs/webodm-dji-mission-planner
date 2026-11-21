"""
A processed WebODM task's DSM as the editors' 3D ground (Phase 23): where the user picks one of their tasks in Map
layers and turns its DSM on, the ground inside the task is the task's surface, as new as the flight and finer than the
lidar, blended into the lidar or AWS's terrain at its edge.

The task's dsm.tif is cut once, in WebODM's worker (cut_job), into Terrarium tiles of zoom 15 to 18 (as the lidar
surface, lidar.py) over the task's extent. A tile is RGBA: the heights in its colours, the task's weight in its alpha
(255 inside, falling to 0 over FEATHER meters at the task's edge and holes), so that the browser blends it over the
surface under it (lidar_surface.js) whatever that is, the lidar built later included.

Heights: ODM writes the DSM from the photos' GPS (WGS84-ellipsoidal for a Matrice 4T), a metre or more off the ground
the route is planned over. The whole task is shifted by the median difference from the surface under it (the lidar
where its unit is built, else AWS's terrain) on open ground (the lowest GROUND_PERCENTILE of that surface), decided
with the user 2026-11-20; with neither to compare, by the EGM96 geoid alone. Measured on a task over 2016 lidar: 1.1 m
on open ground after the geoid.

    mission_planner_data/tasks/<task id>/status.json    queued, building, done or failed, with the DSM's time, the
                                                        shift and the version of the tiles
    mission_planner_data/tasks/<task id>/tiles/<z>/<x>/<y>.png

Unattended (in the worker): every write goes to a temporary name renamed into place (the tiles to a folder of their
own, swapped in once all are written), a state that does not read is set aside and the task cut again, a failure is
written into the state (and retried by a request after RETRY_AFTER, or at once when the DSM changed), a cut that died
with its worker is taken over once its state is older than STALE_AFTER, and the folder of a task that is gone is
removed (prune).
"""
import errno
import fcntl
import json
import logging
import math
import os
import re
import shutil
import tempfile
import time

import numpy as np

from app.plugins.functions import get_plugins_persistent_path

from . import lidar
from .routes import DATA_FOLDER

logger = logging.getLogger('app.logger')

STATES = ("queued", "building", "done", "failed")
TILE_ZOOMS = lidar.TILE_ZOOMS
CUT_VERSION = 1             # how the tiles are made; a task cut by an older one is cut again
FEATHER = 3.0               # meters over which the task fades into the surface under it
MAX_FEATHER_PIXELS = 16
MAX_TILES = 5000            # about 100 km2 of task at zoom 18
SAMPLES = 60                # a SAMPLES x SAMPLES grid over the task, to find its shift
GROUND_PERCENTILE = 30.0
MIN_GROUND_POINTS = 20
RETRY_AFTER = 600.0
STALE_AFTER = 1800.0
TILE = 256
_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class TaskSurfaceError(Exception):
    pass


def root():
    return get_plugins_persistent_path(DATA_FOLDER, "tasks")


def is_task_id(value):
    return isinstance(value, str) and bool(_ID.match(value))


def folder(task_id):
    if not is_task_id(task_id):
        raise ValueError("not a task id")
    return os.path.join(root(), task_id)


def dsm_path(task):
    return task.get_check_file_asset_path("dsm.tif")


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


# -- states ------------------------------------------------------------------------------------------------------------

def read_state(task_id):
    """The task's saved state, or None when there is none (or it did not read: set aside)"""
    path = os.path.join(folder(task_id), "status.json")
    try:
        with open(path) as f:
            value = json.load(f)
        if not isinstance(value, dict) or value.get("state") not in STATES or not isinstance(value.get("time"), (int, float)):
            raise ValueError("not a state")
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        lidar._set_aside(path)
        return None
    return value


def write_state(task_id, state, message="", **extra):
    lidar._write_json(os.path.join(folder(task_id), "status.json"),
                      dict(extra, state=state, time=time.time(), message=message, version=CUT_VERSION))


def needs_cut(st, mtime, now):
    if st is None:
        return True
    if st["state"] in ("queued", "building"):
        return now - st["time"] > STALE_AFTER
    if st.get("dsm_mtime") != mtime:
        return True
    if st["state"] == "failed":
        return now - st["time"] > RETRY_AFTER
    return st.get("version", 0) < CUT_VERSION


def answer(task_id):
    """What the editor needs: {"state", "message", "v", "shift", "match", "reference", "bounds"}; "missing" when never
    asked for"""
    st = read_state(task_id) or {"state": "missing", "message": ""}
    done = st["state"] == "done"
    return {"state": st["state"], "message": st.get("message", ""), "v": st.get("made", 0) if done else 0,
            "shift": st.get("shift") if done else None, "match": st.get("match") if done else None,
            "reference": st.get("reference") if done else None, "bounds": st.get("bounds") if done else None}


def request(task, enqueue=None):
    """Queues a cut of the task's DSM when it needs one (never cut, changed since, failed long enough ago, or a cut
    that died) and answers its state"""
    task_id = str(task.id)
    path = dsm_path(task)
    if path is None:
        return dict(answer(task_id), state="failed", message="the task has no DSM")
    mtime = _mtime(path)
    os.makedirs(folder(task_id), exist_ok=True)
    claimed = False
    with open(os.path.join(folder(task_id), ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if needs_cut(read_state(task_id), mtime, time.time()):
                write_state(task_id, "queued", dsm_mtime=mtime)
                claimed = True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    if claimed:
        try:
            (enqueue or _enqueue)(task_id)
        except Exception:  # the queue (Celery's broker) is down: say so in the state
            logger.exception("DJI Mission Planner: could not queue the cut of task %s's DSM", task_id)
            write_state(task_id, "failed", "the cut could not be queued (WebODM's worker queue is down)", dsm_mtime=mtime)
    return answer(task_id)


def cut_job(module_name, task_id):
    """Run by WebODM's worker (run_function_async evaluates this function's source: imports go inside)"""
    import importlib
    importlib.import_module(module_name).cut(task_id)


def _enqueue(task_id):
    from app.plugins.worker import run_function_async
    run_function_async(cut_job, __name__, task_id)


def cut(task_id):
    """Cuts the task's DSM into its tiles; every failure ends in its state"""
    from app.models import Task
    task = Task.objects.filter(pk=task_id).first()
    if task is None:
        remove(task_id)
        return
    path = dsm_path(task)
    if path is None:
        write_state(task_id, "failed", "the task has no DSM")
        return
    mtime = _mtime(path)
    write_state(task_id, "building", dsm_mtime=mtime)
    try:
        info = make_tiles(task_id, path)
    except TaskSurfaceError as e:
        write_state(task_id, "failed", str(e), dsm_mtime=mtime)
    except OSError as e:
        logger.exception("DJI Mission Planner: the DSM of task %s could not be cut", task_id)
        write_state(task_id, "failed", "the disk is full" if e.errno == errno.ENOSPC else "the DSM could not be read (%s)" % type(e).__name__, dsm_mtime=mtime)
    except Exception as e:  # rasterio raises several kinds for a broken file
        logger.exception("DJI Mission Planner: the DSM of task %s could not be cut", task_id)
        write_state(task_id, "failed", "the DSM could not be read (%s)" % type(e).__name__, dsm_mtime=mtime)
    else:
        write_state(task_id, "done", dsm_mtime=mtime, **info)


def remove(task_id):
    shutil.rmtree(folder(task_id), ignore_errors=True)


def prune():
    """Removes the folders of tasks that are gone"""
    from app.models import Task
    try:
        names = [n for n in os.listdir(root()) if is_task_id(n)]
    except OSError:
        return
    existing = {str(i) for i in Task.objects.filter(pk__in=names).values_list("id", flat=True)} if names else set()
    for name in names:
        if name not in existing:
            remove(name)


def tile_path(task_id, z, x, y):
    """The file of a cut tile, or None"""
    if z not in TILE_ZOOMS or not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return None
    st = read_state(task_id)
    if not st or st["state"] != "done":
        return None
    path = os.path.join(folder(task_id), "tiles", str(z), str(x), "%d.png" % y)
    return path if os.path.isfile(path) else None


# -- cutting -----------------------------------------------------------------------------------------------------------

def _distance(valid, steps):
    """The number of 3 x 3 erosions each valid pixel survives, up to `steps` (its distance to the nearest invalid one, in
    pixels, roughly)"""
    out = np.zeros(valid.shape)
    cur = valid.copy()
    for _ in range(steps):
        out += cur
        padded = np.pad(cur, 1, constant_values=False)
        nxt = cur.copy()
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                nxt &= padded[dy:dy + cur.shape[0], dx:dx + cur.shape[1]]
        cur = nxt
        if not cur.any():
            break
    return out


def weight_of(heights, pixel_m):
    """The task's weight (0 to 1) of each pixel of a tile read with a margin: 0 where the DSM has none, rising to 1
    FEATHER meters inside"""
    valid = np.isfinite(heights)
    steps = int(math.ceil(FEATHER / pixel_m))
    if steps <= 1:
        return valid.astype("float64")
    steps = min(steps, MAX_FEATHER_PIXELS)
    return np.clip(_distance(valid, steps) / steps, 0, 1)


def _png_rgba(rgba):
    import warnings
    from rasterio.errors import NotGeoreferencedWarning
    from rasterio.io import MemoryFile
    with warnings.catch_warnings(), MemoryFile() as m:
        warnings.simplefilter("ignore", NotGeoreferencedWarning)    # a tile has no place of its own: its URL is one
        with m.open(driver="PNG", width=TILE, height=TILE, count=4, dtype="uint8") as d:
            d.write(rgba)
        return m.read()


def tiles_over(bounds_3857):
    """[(z, x, y)] of the zoom 15 to 18 tiles a box of EPSG:3857 meters touches"""
    left, bottom, right, top = bounds_3857
    out = []
    for z in TILE_ZOOMS:
        s = lidar.tile_size(z)
        x0, x1 = int((left + lidar.HALF) // s), int((right + lidar.HALF) // s)
        y0, y1 = int((lidar.HALF - top) // s), int((lidar.HALF - bottom) // s)
        out += [(z, x, y) for y in range(max(y0, 0), min(y1, 2 ** z - 1) + 1) for x in range(max(x0, 0), min(x1, 2 ** z - 1) + 1)]
    return out


def reference_heights(lons, lats):
    """The heights of the surface under the points that the 3D view shows: the lidar where its unit is built, else
    AWS's terrain (NaN where neither could be had), and which was used ("lidar", "terrain" or "mixed")"""
    import rasterio
    out = np.full(len(lons), np.nan)
    used = set()
    xs, ys = zip(*[lidar.to_mercator(lon, lat) for lon, lat in zip(lons, lats)]) if len(lons) else ((), ())
    xs, ys = np.array(xs), np.array(ys)
    s = lidar.tile_size(lidar.UNIT_ZOOM)
    ux, uy = ((xs + lidar.HALF) // s).astype(int), ((lidar.HALF - ys) // s).astype(int)
    for unit in sorted(set(zip(ux.tolist(), uy.tolist()))):
        here = (ux == unit[0]) & (uy == unit[1])
        st = lidar.read_state(unit)
        if st and st["state"] == "done":
            try:
                with rasterio.open(os.path.join(lidar.unit_folder(unit), "dsm.tif")) as r:
                    vals = np.array([v[0] for v in r.sample(zip(xs[here], ys[here]))], dtype="float64")
                vals[vals < -9000] = np.nan
                out[here] = vals
                used.add("lidar")
                continue
            except Exception:  # noqa: BLE001 (an unreadable unit: AWS's terrain instead)
                logger.warning("DJI Mission Planner: the lidar of unit %s could not be read for a task's shift", unit)
        try:
            tile = lidar.terrarium_unit_tile(unit)
        except lidar.LidarError as e:
            logger.info("DJI Mission Planner: no terrain to shift a task by at unit %s: %s", unit, e)
            continue
        left, _b, _r, top = lidar.tile_bounds(lidar.UNIT_ZOOM, *unit)
        col = np.clip(((xs[here] - left) / s * TILE).astype(int), 0, TILE - 1)
        row = np.clip(((top - ys[here]) / s * TILE).astype(int), 0, TILE - 1)
        out[here] = tile[row, col]
        used.add("terrain")
    return out, ("mixed" if len(used) > 1 else (used.pop() if used else None))


def find_shift(src):
    """{"shift", "match", "reference"}: the meters added to the task's heights so that its open ground meets the surface
    under it; match: the same less the EGM96 geoid's (what is left once the heights are taken to sea level), None
    without the geoid; reference: what it was matched with, None when nothing (the geoid's alone)"""
    from pyproj import Transformer
    from .missions import geoid
    from rasterio.warp import transform_bounds
    west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
    lons, lats = np.meshgrid(np.linspace(west, east, SAMPLES + 2)[1:-1], np.linspace(south, north, SAMPLES + 2)[1:-1])
    lons, lats = lons.ravel(), lats.ravel()
    xs, ys = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform(lons, lats)
    task = np.array([v[0] for v in src.sample(zip(xs, ys))], dtype="float64")
    if src.nodata is not None:
        task[task == src.nodata] = np.nan
    task[(task < -1000) | (task > 10000)] = np.nan
    try:
        n = geoid.undulation((south + north) / 2, (west + east) / 2)
    except geoid.GeoidError as e:
        logger.info("DJI Mission Planner: a task's shift without the geoid: %s", e)
        n = None
    inside = np.isfinite(task)
    ref, reference = reference_heights(lons[inside], lats[inside])
    task = task[inside]
    ok = np.isfinite(ref)
    if ok.sum() >= MIN_GROUND_POINTS:
        ground = ok & (ref <= np.percentile(ref[ok], GROUND_PERCENTILE))
        if ground.sum() >= MIN_GROUND_POINTS:
            shift = float(np.median(ref[ground] - task[ground]))
            return {"shift": round(shift, 3), "match": round(shift + n, 3) if n is not None else None, "reference": reference}
    if n is None:
        raise TaskSurfaceError("neither the surface under the task nor the geoid could be had to place its heights")
    return {"shift": round(-n, 3), "match": 0.0, "reference": None}


def make_tiles(task_id, path):
    """The task's tiles, written to a folder of their own and swapped in; {"shift", "match", "reference", "bounds",
    "tiles", "made"}"""
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject, transform_bounds
    base = folder(task_id)
    with rasterio.open(path) as src:
        if src.crs is None:
            raise TaskSurfaceError("the DSM has no coordinate system")
        info = find_shift(src)
        bounds = transform_bounds(src.crs, "EPSG:3857", *src.bounds)
        tiles = tiles_over(bounds)
        if len(tiles) > MAX_TILES:
            raise TaskSurfaceError("the task is too large to show (%d tiles, at most %d)" % (len(tiles), MAX_TILES))
        work = tempfile.mkdtemp(dir=base, prefix=".cut-")
        try:
            written = 0
            for z, x, y in tiles:
                pixel = lidar.tile_size(z) / TILE                      # EPSG:3857 meters
                ground_pixel = pixel / lidar.scale(_lat_of(z, y))       # meters on the ground
                pad = min(int(math.ceil(FEATHER / ground_pixel)), MAX_FEATHER_PIXELS) + 1
                left, bottom, right, top = lidar.tile_bounds(z, x, y)
                size = TILE + 2 * pad
                t = from_bounds(left - pad * pixel, bottom - pad * pixel, right + pad * pixel, top + pad * pixel, size, size)
                heights = np.full((size, size), np.nan, dtype="float32")
                reproject(rasterio.band(src, 1), heights, src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
                          dst_transform=t, dst_crs="EPSG:3857", dst_nodata=np.nan, resampling=Resampling.average)
                heights = heights.astype("float64")
                heights[(heights < -1000) | (heights > 10000)] = np.nan
                w = weight_of(heights, ground_pixel)[pad:-pad, pad:-pad]
                if not (w > 0).any():
                    continue
                h = np.nan_to_num(heights[pad:-pad, pad:-pad] + info["shift"], nan=0.0)
                rgba = np.concatenate([lidar.encode(h), np.round(w * 255).astype("uint8")[None]])
                lidar._write_tile(work, z, x, y, _png_rgba(rgba))
                written += 1
            old = os.path.join(base, "tiles")
            aside = None
            if os.path.exists(old):
                aside = tempfile.mkdtemp(dir=base, prefix=".old-")
                os.replace(old, os.path.join(aside, "tiles"))
            os.makedirs(os.path.join(work, "tiles"), exist_ok=True)
            os.replace(os.path.join(work, "tiles"), old)
            if aside:
                shutil.rmtree(aside, ignore_errors=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    west, south = lidar.to_lonlat(bounds[0], bounds[1])
    east, north = lidar.to_lonlat(bounds[2], bounds[3])
    return dict(info, bounds=[round(west, 7), round(south, 7), round(east, 7), round(north, 7)], tiles=written,
                made=time.time_ns() // 1000)


def _lat_of(z, y):
    """The latitude of the middle of a row of tiles"""
    _l, bottom, _r, top = lidar.tile_bounds(z, 0, y)
    return lidar.to_lonlat(0, (bottom + top) / 2)[1]
