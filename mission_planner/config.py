"""
The plugin's settings: the OpenTopography API key for the terrain and ground heights.

WO_OPENTOPOGRAPHY_API_KEY in WebODM's environment wins when it is set; otherwise the key an administrator saved on
the plugin's settings page (the plugin's global data store: the row "mission_planner::opentopography_api_key").
"""
import os

from app.plugins import GlobalDataStore

PLUGIN = "mission_planner"
ENV_KEY = "WO_OPENTOPOGRAPHY_API_KEY"
STORE_KEY = "opentopography_api_key"

NO_KEY = "No OpenTopography API key is set: an administrator sets it on the DJI Mission Planner page, under Settings"


def store():
    return GlobalDataStore(PLUGIN)


def environment_api_key():
    return os.environ.get(ENV_KEY, "").strip()


def saved_api_key():
    return (store().get_string(STORE_KEY) or "").strip()


def opentopography_api_key():
    """The key in use ("" when none is set)"""
    return environment_api_key() or saved_api_key()


def api_key_source():
    """Where the key in use comes from: "environment", "saved" or None"""
    if environment_api_key():
        return "environment"
    if saved_api_key():
        return "saved"
    return None


def save_api_key(key):
    store().set_string(STORE_KEY, key.strip())


def remove_api_key():
    store().del_key(STORE_KEY)
