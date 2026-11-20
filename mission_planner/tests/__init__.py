# The tests never download the EGM96 geoid grid (missions/geoid.py): they read the real file, kept in
# fixtures/geoid (public domain, PROJ's us_nga_egm96_15.tif). test_mission_geoid points it elsewhere to test the download.
#
# Nor do they reach the lidar or the GEOID18 grid: WebODM runs worker jobs inline under test, so a lidar build queued by
# a test would download the index and point clouds from AWS (lidar.py), and GEOID18 (16.7 MB) would be downloaded into
# fixtures/geoid. The lidar's folder is a scratch one, a build is refused unless a test patches lidar._enqueue, and
# GEOID18 is refused unless a test puts ENSURE_GEOID18 back (test_mission_geoid, over a folder of its own).
import atexit
import os
import shutil
import tempfile

from .. import lidar
from ..missions import geoid

geoid.grid_folder = lambda: os.path.join(os.path.dirname(__file__), "fixtures", "geoid")

ENSURE_GEOID18 = geoid.ensure_geoid18


def _no_geoid18():
    raise geoid.GeoidError("the tests do not download the GEOID18 grid")


geoid.ensure_geoid18 = _no_geoid18

_LIDAR = tempfile.mkdtemp(prefix="mp-test-lidar-")
atexit.register(shutil.rmtree, _LIDAR, True)
lidar.root = lambda: _LIDAR


def _no_lidar_build(units):
    raise RuntimeError("the tests do not queue lidar builds")


lidar._enqueue = _no_lidar_build
