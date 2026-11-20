"""
Ground elevation at a point, for the ASL (EGM96) height mode: missions/wpml.py needs both the orthometric
(above-sea-level) and WGS84-ellipsoidal ground height at the takeoff point to compute a mission's target altitude
(see wpml.asl_heights). Both come from OpenTopography's Point Elevation API, queried for the same dataset in its
two vertical-datum variants, so the two numbers describe the same ground point on the same model.
"""
import requests
from ..config import NO_KEY, opentopography_api_key

POINT_ELEVATION_URL = "https://portal.opentopography.org/API/v1/elevation"
TIMEOUT = 10.0

# SRTM_GL1 (EGM96 orthometric height) and its WGS84-ellipsoidal twin, SRTM_GL1_Ellip - checked live against the
# takeoff point of a real Pilot 2 ASL export (testkmz-oblique-asl.kmz): both landed within 1.6m of what that
# file's own numbers imply, consistent with 30m SRTM resolution.
ORTHOMETRIC_DATASET = "SRTM_GL1"
ELLIPSOIDAL_DATASET = "SRTM_GL1_Ellip"


class ElevationError(Exception):
    pass


def without_key(text, api_key, mark="[API key]"):
    """text without the key: a requests error repeats the request's URL, and OpenTopography's refusal the key"""
    return text.replace(api_key, mark) if api_key else text


def _point_elevation(lat, lon, dataset, api_key):
    try:
        res = requests.get(POINT_ELEVATION_URL, params={
            "latitude": lat, "longitude": lon, "dataset": dataset, "API_Key": api_key,
        }, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise ElevationError("Could not reach the elevation service: %s" % without_key(str(e), api_key))

    if res.status_code in (401, 403):
        raise ElevationError("OpenTopography refused the API key (%d): an administrator changes it on the Mission "
                             "Planner page, under Settings" % res.status_code)
    if res.status_code != 200:
        raise ElevationError("The elevation service returned an error (%d)" % res.status_code)
    try:
        data = res.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ElevationError("The elevation service returned an unexpected response")
    elevation = data.get("Elevation")
    if data.get("Status") != "Success" or isinstance(elevation, bool) or not isinstance(elevation, (int, float)):
        message = data.get("Message")
        # OpenTopography's own words may repeat the key
        raise ElevationError(without_key(message, api_key) if isinstance(message, str) and message
                             else "The elevation service could not find a value for this point")
    return float(elevation)


def fetch_ground_elevation(lat, lon):
    """
    The ground elevation at (lat, lon), both above sea level and WGS84-ellipsoidal.

    :return: {"orthometric": meters above sea level, "ellipsoidal": meters above the WGS84 ellipsoid}
    :raises ElevationError: the key is not configured, the service could not be reached, or it returned an error
    """
    api_key = opentopography_api_key()
    if not api_key:
        raise ElevationError(NO_KEY)

    return {
        "orthometric": _point_elevation(lat, lon, ORTHOMETRIC_DATASET, api_key),
        "ellipsoidal": _point_elevation(lat, lon, ELLIPSOIDAL_DATASET, api_key),
    }


def fetch_ellipsoidal_elevation(lat, lon):
    """
    The WGS84-ellipsoidal ground height at (lat, lon), for a waypoint route flown above the ground (AGL): each point's
    height is the ground under it plus the route's height (see missions/waypoints.py).

    :raises ElevationError: as fetch_ground_elevation
    """
    api_key = opentopography_api_key()
    if not api_key:
        raise ElevationError(NO_KEY)
    return _point_elevation(lat, lon, ELLIPSOIDAL_DATASET, api_key)


class KeyRefused(Exception):
    """OpenTopography refused the key (its message, without the key)"""


# The point a key is tried on when it is saved: the takeoff point of the Pilot 2 samples (testkmz-oblique-asl.kmz)
CHECK_POINT = (42.10339, -85.020388)


def check_api_key(api_key):
    """
    Try a key with one Point Elevation request (one call of the key's daily allowance).

    :raises KeyRefused: OpenTopography refused the key
    :raises ElevationError: OpenTopography could not be reached, or answered something else than a height
    """
    lat, lon = CHECK_POINT
    try:
        res = requests.get(POINT_ELEVATION_URL, params={
            "latitude": lat, "longitude": lon, "dataset": ORTHOMETRIC_DATASET, "API_Key": api_key,
        }, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise ElevationError("Could not reach OpenTopography: %s" % without_key(str(e), api_key))
    try:
        data = res.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if res.status_code in (401, 403):
        # OpenTopography's message repeats the key ("Invalid API key: <key>")
        message = without_key(str(data.get("Message") or "Authentication failed"), api_key, "").strip().rstrip(":").strip()
        raise KeyRefused(message)
    if res.status_code != 200 or data.get("Status") != "Success" or not isinstance(data.get("Elevation"), (int, float)):
        raise ElevationError("OpenTopography answered with an error (%d)" % res.status_code)
