"""
The aircraft the planner plans for, read from the plugin's drones.json: the one place a model is described (its name,
the app that flies its missions, the numbers the mission file carries for it and its cameras). The pages get the same
file (plugin.py writes it into them; planner_core.js reads it), so the browser and the server agree.

Each entry, by model key:
- label, name: "DJI Matrice 4T" (lists and menus), "Matrice 4T" (sentences)
- app: the app that flies the mission ("pilot2": DJI Pilot 2 and FlightHub 2, missions/wpml.py and the others;
  "djifly": DJI Fly, missions/djifly.py)
- drone: [droneEnumValue, droneSubEnumValue]; payload: payloadEnumValue (null for DJI Fly, whose files name none)
- payload_sub: the payloadSubEnumValue for each set of cameras a mission can use; any other set is refused
- cameras: what each camera's photo covers (cameras.Camera's fields), in the order the planner lists them; every model
  has the wide camera ("visable"), which a copy and the GSD shown on the routes list are based on. A camera's key is
  its role in the planner ("visable" wide, "ir" thermal); "lens", when given, is the name the mission file uses for it
  (imageFormat, payloadLensIndex: "wide" on the M300 and M350's payloads), else the key
- route_types: the route types the model is offered (its app's documents say it flies them)
- realtime_follow: whether AGL area and linear routes may use the aircraft's real-time terrain follow; without it they
  fly over the terrain model embedded in the mission
- max_speed: (optional) the fastest the mission may fly, m/s
- source: where the numbers come from
"""
import json
import os
from collections import namedtuple

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "drones.json")
APPS = ("pilot2", "djifly")
ROUTE_TYPES = ("area", "linear", "waypoint", "slope", "geometric")

# focal_mm and sensor sizes in millimeters; the sensor width runs across the flight lines, its height along them
Camera = namedtuple("Camera", "key label focal_mm sensor_w_mm sensor_h_mm px_w px_h lens", defaults=(None,))
Drone = namedtuple("Drone", "key label name app drone payload payload_sub cameras route_types realtime_follow max_speed source")


class RegistryError(Exception):
    """drones.json does not describe the aircraft as this module expects"""


def _number(value, where, integer=False):
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)):
        raise RegistryError("%s must be a%s number" % (where, "n integer" if integer else ""))
    if not integer and not value > 0:
        raise RegistryError("%s must be more than 0" % where)
    return value if integer else float(value)


def _drone(key, d):
    where = "drones.json %s" % key
    try:
        cameras = {}
        for c in d["cameras"]:
            camera = Camera(c["key"], c["label"], *(_number(c[f], "%s camera %s" % (where, f))
                                                    for f in ("focal_mm", "sensor_w_mm", "sensor_h_mm")),
                            *(_number(c[f], "%s camera %s" % (where, f), integer=True) for f in ("px_w", "px_h")),
                            str(c["lens"]) if "lens" in c else None)
            if camera.key in cameras:
                raise RegistryError("%s has two cameras %r" % (where, camera.key))
            cameras[camera.key] = camera
        if "visable" not in cameras:
            raise RegistryError("%s has no wide camera (\"visable\")" % where)
        payload_sub = {}
        for p in d["payload_sub"]:
            keys = frozenset(p["cameras"])
            if not keys or not keys <= set(cameras):
                raise RegistryError("%s payload_sub names cameras it does not have: %s" % (where, sorted(keys)))
            payload_sub[keys] = _number(p["value"], where + " payload_sub value", integer=True)
        drone = tuple(_number(v, where + " drone", integer=True) for v in d["drone"])
        if len(drone) != 2:
            raise RegistryError("%s drone must be [enum, sub enum]" % where)
        if d["app"] not in APPS:
            raise RegistryError("%s app must be one of %s" % (where, ", ".join(APPS)))
        route_types = tuple(d["route_types"])
        if not route_types or len(set(route_types)) != len(route_types) or not set(route_types) <= set(ROUTE_TYPES):
            raise RegistryError("%s route_types must be some of %s, each once" % (where, ", ".join(ROUTE_TYPES)))
        if not isinstance(d["realtime_follow"], bool):
            raise RegistryError("%s realtime_follow must be true or false" % where)
        payload = (None if d["app"] == "djifly" and d["payload"] is None
                   else _number(d["payload"], where + " payload", integer=True))
        max_speed = None if d.get("max_speed") is None else _number(d["max_speed"], where + " max_speed")
        return Drone(key, str(d["label"]), str(d["name"]), d["app"], drone, payload, payload_sub, cameras, route_types,
                     d["realtime_follow"], max_speed, str(d.get("source", "")))
    except (KeyError, TypeError) as e:
        raise RegistryError("%s is incomplete: %r" % (where, e))


def read(path=PATH):
    """The file as it is (the pages get it: plugin.py, planner_core.js)"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse(data):
    """{model key: Drone}, in the file's order; RegistryError when the data is not as described above"""
    if not isinstance(data, dict) or not data:
        raise RegistryError("drones.json must list the aircraft by key")
    return {key: _drone(key, d) for key, d in data.items()}


DATA = read()
DRONES = parse(DATA)
