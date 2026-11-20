"""
Heights from a processed task's elevation rasters, for the heights of a slope's corners and a block's base and top
(api.py's FaceHeightsView and BlockHeightsView). Taken from LuxODM's app/source_photos.py (its DSM and DTM readers;
the planner never read the point cloud).
"""
import logging

import numpy as np
from pyproj import Transformer

logger = logging.getLogger('app.logger')


def raster_heights(path, points, epsg):
    """Heights of UTM points (EPSG epsg) sampled from an elevation raster, NaN where it has none"""
    import rasterio

    with rasterio.open(path) as src:
        pts = points
        if src.crs is not None and src.crs.to_epsg() != epsg:
            t = Transformer.from_crs("EPSG:{}".format(epsg), src.crs, always_xy=True)
            pts = np.array([t.transform(x, y) for x, y in points])
        values = np.array([v[0] for v in src.sample([tuple(p) for p in pts])], dtype=float)
        if src.nodata is not None:
            values[values == src.nodata] = np.nan
        b = src.bounds
        pts = np.asarray(pts, dtype=float).reshape(-1, 2)
        values[(pts[:, 0] < b.left) | (pts[:, 0] > b.right) | (pts[:, 1] < b.bottom) | (pts[:, 1] > b.top)] = np.nan
    values[~np.isfinite(values)] = np.nan
    return values


def surface_heights(task, points):
    """
    :return: (heights, source): the heights of UTM points (in the task's EPSG), NaN where the first raster with any
        has none, and that raster ("dsm" or "dtm"), or (None, None) if the task has no elevation raster with heights
        at the points
    """
    for asset, source in (('dsm.tif', 'dsm'), ('dtm.tif', 'dtm')):
        path = task.get_check_file_asset_path(asset)
        if path:
            try:
                heights = raster_heights(path, points, task.epsg)
            except Exception as e:  # noqa: BLE001 (any unreadable raster is skipped, as LuxODM did)
                logger.warning("Cannot sample {} of {}: {}".format(asset, task, str(e)))
                heights = None
            if heights is not None and np.isfinite(heights).any():
                return heights, source
    return None, None
