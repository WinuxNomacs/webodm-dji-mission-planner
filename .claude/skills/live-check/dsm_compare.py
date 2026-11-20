"""
Compares the terrain (DSM) embedded in mission KMZs: the lidar terrain against COP30 and Pilot 2's own, over the lidar
terrain's cells (each other terrain sampled at their centres, bilinear). Run with the repo's venv:
    .venv/bin/python .claude/skills/live-check/dsm_compare.py <lidar.kmz> <other.kmz> [<other.kmz> ...]
"""
import sys
import zipfile

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import Resampling, reproject


def dsm(kmz):
    with zipfile.ZipFile(kmz) as z:
        names = [n for n in z.namelist() if n.startswith("wpmz/res/dsm/") and n.endswith(".tif")]
        if not names:
            raise SystemExit("%s has no DSM" % kmz)
        return names[0], z.read(names[0])


def main(lidar_kmz, others):
    name, content = dsm(lidar_kmz)
    with MemoryFile(content) as m, m.open() as src:
        base, transform, crs = src.read(1).astype("float64"), src.transform, src.crs
        print("%s: %s, %d x %d cells of %.2f\" (%.1f m), %d to %d m" % (lidar_kmz, name, src.width, src.height,
              transform.a * 3600, transform.a * 111320, base.min(), base.max()))
    for kmz in others:
        other_name, other = dsm(kmz)
        on = np.full(base.shape, np.nan)
        with MemoryFile(other) as m, m.open() as src:
            reproject(src.read(1).astype("float64"), on, src_transform=src.transform, src_crs=src.crs,
                      dst_transform=transform, dst_crs=crs, dst_nodata=np.nan, resampling=Resampling.bilinear)
        d = (base - on)[np.isfinite(on)]
        print("lidar minus %s (%s), %d cells: mean %.2f, median %.2f, 5th %.2f, 95th %.2f, min %.2f, max %.2f m"
              % (kmz, other_name, d.size, d.mean(), np.median(d), np.percentile(d, 5), np.percentile(d, 95), d.min(), d.max()))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    with rasterio.Env():
        main(sys.argv[1], sys.argv[2:])
