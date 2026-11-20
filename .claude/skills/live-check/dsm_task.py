# Run with: docker exec -i [-e MP_ACTION=delete] -w /webodm mp-webapp python manage.py shell < .claude/skills/live-check/dsm_task.py
# A throwaway project "MP live check" of admin's, with one completed task whose DSM is synthetic: ground 214.5 m, a
# block 219 m high within 6 m of the centre of the geometric sample's outline (EPSG:32616). WebODM fills the extent.
import os
import shutil

import numpy as np
import rasterio
from django.contrib.auth.models import User
from pyproj import Transformer
from rasterio.transform import from_origin

from app.models import Project, Task

NAME = "MP live check"
action = os.environ.get("MP_ACTION", "create")
if action == "delete":
    for p in Project.objects.filter(name=NAME):
        for t in Task.objects.filter(project=p):
            shutil.rmtree(t.task_path(), ignore_errors=True)
        p.delete()
    print("deleted", Project.objects.filter(name=NAME).count() == 0)
else:
    admin = User.objects.get(username="admin")
    project = Project.objects.create(owner=admin, name=NAME)
    task = Task.objects.create(project=project, name="Synthetic DSM", epsg=32616, status=40,
                               available_assets=["dsm.tif"], auto_processing_node=False)
    lon, lat = -85.020388, 42.10339
    x0, y0 = Transformer.from_crs(4326, 32616, always_xy=True).transform(lon, lat)
    size, cell = 600, 0.1
    xs = x0 - size * cell / 2 + (np.arange(size) + 0.5) * cell
    ys = y0 + size * cell / 2 - (np.arange(size) + 0.5) * cell
    gx, gy = np.meshgrid(xs, ys)
    heights = np.where(np.hypot(gx - x0, gy - y0) <= 6.0, 219.0, 214.5).astype("float32")
    path = task.assets_path("odm_dem", "dsm.tif")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=size, height=size, count=1, dtype="float32", crs="EPSG:32616",
                       transform=from_origin(x0 - size * cell / 2, y0 + size * cell / 2, cell, cell), nodata=-9999) as dst:
        dst.write(heights, 1)
    task.populate_extent_fields()
    task.save()
    print("task", task.id, type(task.dsm_extent).__name__, task.get_check_file_asset_path("dsm.tif") is not None)
