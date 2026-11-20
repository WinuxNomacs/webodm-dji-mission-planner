"""
The saved routes.

WebODM gives a plugin no tables of its own, so a route is a row of WebODM's plugin data (PluginDatum) in its owner's
name, with the key "mission_planner::route:<id>" and a JSON value holding what LuxODM's Route model held (name, type,
aircraft, settings, terrain, times). Its id is the row's primary key: the database hands it out, so two routes made at
once never share one, and it stays an integer (the editor's URL route/<id>). The rows are read and written here
directly, and only this plugin's rows (by their key): WebODM's UserDataStore lists nothing and its writes create a
row that is gone, so a route deleted in one tab would come back when another tab saved it.

A save writes only the fields it names, under a row lock, as Django's save(update_fields=...) did: fetching a route's
terrain while its editor saves the settings keeps both.

A route's terrain (the elevation raster under it, missions/terrain.py) is a file in WebODM's plugin media, in
mission_planner_data/terrain/<id>/<name>, removed with the route. Not in the plugin's own persistent folder
(get_persistent_path): a plugin installed from a zip lives there, and deleting it in Administration > Plugins (the way
an upload is upgraded) removes that folder whole; this one stays, as the routes' rows do. WebODM skips it when it
looks for plugins (it has no plugin.py). A deleted user's rows go with the user (PluginDatum.user cascades) but
their terrain folders stay: sweep() removes the folders no route has, after every route delete.
"""
import fcntl
import logging
import os
import re
import shutil
import time
import uuid

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _

from app.models import PluginDatum
from app.plugins.functions import get_plugins_persistent_path

from .missions.drones import DRONES

logger = logging.getLogger('app.logger')

PLUGIN = "mission_planner"
KEY_PREFIX = PLUGIN + "::route:"
DATA_FOLDER = PLUGIN + "_data"       # beside the installed plugin's folder in WebODM's plugin media, not inside it

# The route types the mission planner plans (api.SUPPORTED_ROUTE_TYPES says which can be created, not this)
ROUTE_TYPES = (
    ('area', _("Area Route")),
    ('linear', _("Linear Route")),
    ('waypoint', _("Waypoint Route")),
    ('slope', _("Slope Route")),
    ('geometric', _("Geometric Route")),
)

# The aircraft a route is planned for. Fixed once the route is created (api.py refuses the change): a route's flight
# lines, camera footprint and mission file all depend on it. A copy for the other aircraft is re-planned instead.
AIRCRAFT_MODELS = tuple((k, d.label) for k, d in DRONES.items())     # drones.json

FIELDS = ("name", "route_type", "model", "settings", "terrain", "terrain_info", "takeoff_elevation")


class RouteGone(Exception):
    """The route was deleted (in another tab, or with its owner) while it was being saved"""


def key(route_id):
    return KEY_PREFIX + str(route_id)


def terrain_root():
    return get_plugins_persistent_path(DATA_FOLDER, "terrain")


def terrain_folder(route_id):
    return os.path.join(terrain_root(), str(int(route_id)))


class Route:
    def __init__(self, datum):
        self._load(datum)

    def _load(self, datum):
        value = datum.json_value if isinstance(datum.json_value, dict) else {}
        self.id = datum.pk
        self.owner = datum.user
        self.name = value.get("name", "")
        self.route_type = value.get("route_type", "area")
        self.model = value.get("model", "m4t")
        self.settings = value.get("settings") if isinstance(value.get("settings"), dict) else {}
        self.terrain = value.get("terrain") or ""           # the file's name in terrain_folder(id), "" for none
        self.terrain_info = value.get("terrain_info") if isinstance(value.get("terrain_info"), dict) else {}
        # the takeoff point's ground heights (api.RouteElevationView), beside the settings, not in them: a Save sends
        # the editor's settings, which do not carry it; kept in the settings before 2026-11-19
        cached = value.get("takeoff_elevation", self.settings.get("takeoff_elevation"))
        self.takeoff_elevation = cached if isinstance(cached, dict) else None
        self.created_at = parse_datetime(value.get("created_at") or "")
        self.updated_at = parse_datetime(value.get("updated_at") or "")

    def __str__(self):
        return self.name

    def get_model_display(self):
        return dict(AIRCRAFT_MODELS).get(self.model, self.model)

    def refresh_from_db(self):
        self._load(PluginDatum.objects.select_related("user").get(pk=self.id, key=key(self.id)))

    def save(self, fields=FIELDS):
        """Write the named fields (and the time of the change), leaving the others as they are in the database;
        RouteGone when the route was deleted"""
        with transaction.atomic():
            # no select_related("user"): a row lock cannot reach the nullable side of a join
            datum = PluginDatum.objects.select_for_update().filter(pk=self.id, key=key(self.id)).first()
            if datum is None:
                raise RouteGone()
            value = dict(datum.json_value) if isinstance(datum.json_value, dict) else {}
            value.update({f: getattr(self, f) for f in fields})
            value["updated_at"] = timezone.now().isoformat()
            datum.json_value = value
            datum.save(update_fields=["json_value"])
        self._load(datum)

    def delete(self):
        PluginDatum.objects.filter(pk=self.id, key=key(self.id)).delete()
        sweep()

    def terrain_path(self):
        return os.path.join(terrain_folder(self.id), self.terrain) if self.terrain else None

    def read_terrain(self):
        """The bytes of the route's terrain, None when it has none (or its file is gone)"""
        path = self.terrain_path()
        if path is None:
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as e:
            logger.warning("Cannot read the terrain of route {}: {}".format(self.id, str(e)))
            return None

    def save_terrain(self, tif, info):
        """Keep a fetched terrain (GeoTIFF bytes and what it is) on the route, in place of the one before. Two
        fetches at once take turns (a lock on the folder), and each removes every other file in the folder: the
        one saved last stays, and no file is left that no route names."""
        folder = terrain_folder(self.id)
        os.makedirs(folder, exist_ok=True)
        name = terrain_file_name(info["name"])
        path = os.path.join(folder, name)
        lock = os.open(folder, os.O_RDONLY)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with open(path, "wb") as f:
                f.write(tif)
            self.terrain, self.terrain_info = name, dict(info, fetched_at=time.time())
            try:
                self.save(("terrain", "terrain_info"))
            except RouteGone:
                remove(path)
                raise
            for other in os.listdir(folder):
                if other != name:
                    remove(os.path.join(folder, other))
        finally:
            os.close(lock)


def terrain_file_name(name):
    """A terrain's file name in its route's folder: a prefix of its own, then name made safe"""
    return "{}_{}".format(uuid.uuid4().hex[:8], re.sub(r"[^A-Za-z0-9._-]+", "_", name).lstrip("."))


def remove(path):
    try:
        os.remove(path)
    except OSError as e:
        logger.warning("Cannot remove {}: {}".format(path, str(e)))


def rows():
    return PluginDatum.objects.select_related("user").filter(key__startswith=KEY_PREFIX)


def create(owner, name, route_type="area", model="m4t", settings=None):
    """A new route of owner's. The row is written under a key of its own first, then given its id's key, in one
    transaction (no one sees the first key)"""
    now = timezone.now().isoformat()
    value = {"name": name, "route_type": route_type, "model": model, "settings": settings or {}, "terrain": "",
             "terrain_info": {}, "created_at": now, "updated_at": now}
    with transaction.atomic():
        datum = PluginDatum.objects.create(key="{}::new-route:{}".format(PLUGIN, uuid.uuid4().hex), user=owner,
                                           json_value=value)
        datum.key = key(datum.pk)
        datum.save(update_fields=["key"])
    return Route(datum)


def restore(owner, value, tif=None):
    """A route of owner's brought from elsewhere (the LuxODM import), all its fields given: value holds name,
    route_type, model, settings, terrain_info, created_at and updated_at (ISO times, kept as they are), and tif is its
    terrain (GeoTIFF bytes, None for none). Written in one transaction with its terrain file, so a file that cannot be
    written leaves no route."""
    value = {f: value[f] for f in ("name", "route_type", "model", "settings", "terrain_info", "created_at",
                                   "updated_at")}
    value["terrain"] = ""
    if tif is None:
        value["terrain_info"] = {}
    path = None
    try:
        with transaction.atomic():
            datum = PluginDatum.objects.create(key="{}::new-route:{}".format(PLUGIN, uuid.uuid4().hex), user=owner,
                                               json_value=value)
            datum.key = key(datum.pk)
            if tif is not None:
                folder = terrain_folder(datum.pk)
                os.makedirs(folder, exist_ok=True)
                value["terrain"] = terrain_file_name(value["terrain_info"].get("name") or "terrain.tif")
                path = os.path.join(folder, value["terrain"])
                with open(path, "wb") as f:
                    f.write(tif)
                datum.json_value = value
            datum.save(update_fields=["key", "json_value"])
    except BaseException:
        if path:
            remove(path)
        raise
    return Route(datum)


def get_for(user, route_id):
    """user's route of that id, or None"""
    datum = rows().filter(pk=route_id, user=user, key=key(route_id)).first()
    return Route(datum) if datum else None


def get(route_id):
    """The route of that id whoever owns it, or None"""
    datum = rows().filter(pk=route_id, key=key(route_id)).first()
    return Route(datum) if datum else None


def list_for(user):
    """user's routes, the most recently changed first"""
    routes = [Route(d) for d in rows().filter(user=user)]
    return sorted(routes, key=lambda r: (r.updated_at.isoformat() if r.updated_at else "", r.id), reverse=True)


def all():
    return [Route(d) for d in rows().order_by("pk")]


def count():
    return rows().count()


def sweep():
    """Remove the terrain folders whose route is gone (deleted, or its owner deleted)"""
    root = terrain_root()
    try:
        names = os.listdir(root)
    except OSError:
        return
    ids = {int(k[len(KEY_PREFIX):]) for k in PluginDatum.objects.filter(key__startswith=KEY_PREFIX)
           .values_list("key", flat=True) if k[len(KEY_PREFIX):].isdigit()}
    for name in names:
        if name.isdigit() and int(name) not in ids:
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)
