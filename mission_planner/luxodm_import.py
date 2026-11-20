"""
The import of LuxODM's routes: the mission planner was LuxODM's before it was this plugin, and LuxODM's
`manage.py export_routes <file>` writes all its routes to one JSON file, which an administrator imports on the
DJI Mission Planner page > Settings page.

The whole file is checked before anything is written: a file that fails is refused with the reason. Each route goes
to the account with its LuxODM owner's username; a route whose owner has no account here (or that had no owner) is
skipped and reported. Imported routes get new ids and keep LuxODM's created and updated times. Nothing records what
was imported, so importing a file again imports its routes again, as copies.
"""
import base64
import binascii
import json

import rasterio
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _
from rasterio.io import MemoryFile

from . import routes

FORMAT = "luxodm-routes"
VERSION = 1
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_NAME_LENGTH = 255

ROUTE_TYPES = {k for k, _label in routes.ROUTE_TYPES}
AIRCRAFT = {k for k, _label in routes.AIRCRAFT_MODELS}


class ImportRefused(Exception):
    """The file is not a LuxODM routes export this import reads; nothing was imported"""


def is_geotiff(tif):
    try:
        with MemoryFile(tif) as f, f.open() as src:
            return src.driver == "GTiff" and src.count >= 1
    except (rasterio.errors.RasterioError, rasterio.errors.RasterioIOError):
        return False


def iso_time(value, where, field):
    """The ISO time value (now when it has none)"""
    if value is None:
        return timezone.now().isoformat()
    try:
        # None for text that is not a time; ValueError for one well formed but impossible (2025-02-30)
        parsed = parse_datetime(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None:
        raise ImportRefused(_("%(where)s: %(field)s is not a time") % {"where": where, "field": field})
    return value


def check_route(r, n):
    """The route's record checked, as (LuxODM id, owner's username, value for routes.restore, terrain bytes)"""
    where = _("route %(n)d in the file") % {"n": n}
    if not isinstance(r, dict):
        raise ImportRefused(_("%(where)s is not a route") % {"where": where})
    luxodm_id = r.get("id")
    if isinstance(luxodm_id, bool) or not isinstance(luxodm_id, int):
        raise ImportRefused(_("%(where)s has no id") % {"where": where})
    where = _("LuxODM route #%(id)d") % {"id": luxodm_id}
    owner = r.get("owner")
    if owner is not None and not isinstance(owner, str):
        raise ImportRefused(_("%(where)s: the owner is not a username") % {"where": where})
    name = r.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME_LENGTH:
        raise ImportRefused(_("%(where)s: the name is missing or too long") % {"where": where})
    if r.get("route_type") not in ROUTE_TYPES:
        raise ImportRefused(_("%(where)s: unknown route type %(type)r") % {"where": where, "type": r.get("route_type")})
    if r.get("model") not in AIRCRAFT:
        raise ImportRefused(_("%(where)s: unknown aircraft %(model)r") % {"where": where, "model": r.get("model")})
    if not isinstance(r.get("settings"), dict):
        raise ImportRefused(_("%(where)s: the settings are not an object") % {"where": where})
    terrain_info = r.get("terrain_info") or {}
    if not isinstance(terrain_info, dict):
        raise ImportRefused(_("%(where)s: the terrain info is not an object") % {"where": where})
    tif = None
    if r.get("terrain") is not None:
        try:
            tif = base64.b64decode(r["terrain"], validate=True)
        except (TypeError, ValueError, binascii.Error):
            tif = None
        if not tif or not is_geotiff(tif):
            raise ImportRefused(_("%(where)s: the terrain is not a GeoTIFF") % {"where": where})
        if not isinstance(terrain_info.get("name"), str) or not terrain_info["name"].strip():
            # the export names the embedded terrain file after it
            terrain_info = dict(terrain_info, name="terrain.tif")
    value = {"name": name, "route_type": r["route_type"], "model": r["model"], "settings": r["settings"],
             "terrain_info": terrain_info,
             "created_at": iso_time(r.get("created_at"), where, "created_at"),
             "updated_at": iso_time(r.get("updated_at"), where, "updated_at")}
    return luxodm_id, owner, value, tif


def read(content):
    """The routes of a LuxODM export (its bytes), checked; ImportRefused when the file fails a check"""
    if len(content) > MAX_FILE_BYTES:
        raise ImportRefused(_("The file is larger than %(mb)d MB") % {"mb": MAX_FILE_BYTES // (1024 * 1024)})
    try:
        data = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        raise ImportRefused(_("The file is not JSON"))
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ImportRefused(_("The file is not a LuxODM routes export (from LuxODM's manage.py export_routes)"))
    if data.get("version") != VERSION:
        raise ImportRefused(_("The export's version (%(version)r) is not one this import reads (%(ours)d)") % {
            "version": data.get("version"), "ours": VERSION})
    if not isinstance(data.get("routes"), list):
        raise ImportRefused(_("The file has no list of routes"))
    return [check_route(r, n) for n, r in enumerate(data["routes"], 1)]


def import_routes(checked):
    """Write the checked routes (from read) to their owners' accounts; a report line for each route:
    {luxodm_id, name, owner, id (the new id, None when skipped), skipped (why, or None)}"""
    report = []
    for luxodm_id, owner, value, tif in checked:
        line = {"luxodm_id": luxodm_id, "name": value["name"], "owner": owner, "id": None, "skipped": None}
        user = User.objects.filter(username=owner).first() if owner else None
        if owner is None:
            line["skipped"] = _("it had no owner in LuxODM")
        elif user is None:
            line["skipped"] = _("no account here has the username %(owner)s") % {"owner": owner}
        else:
            line["id"] = routes.restore(user, value, tif).id
        report.append(line)
    return report
