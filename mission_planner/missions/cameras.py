"""
Camera models for survey planning: what a photo covers on the ground. The cameras of each aircraft and where their
numbers come from are in drones.json (drones.py).
"""
import math

from .drones import DRONES, Camera  # noqa: F401 (Camera: the type of every camera here)

# The cameras of each aircraft model, by key
CAMERAS_BY_MODEL = {k: d.cameras for k, d in DRONES.items()}
M4T_THERMAL = CAMERAS_BY_MODEL["m4t"]["ir"]
M4T_WIDE = CAMERAS_BY_MODEL["m4t"]["visable"]
M4E_WIDE = CAMERAS_BY_MODEL["m4e"]["visable"]
# The cameras of the M4T, the model a route has when none is given
CAMERAS = CAMERAS_BY_MODEL["m4t"]


def footprint(camera, height):
    """
    Size on the ground of one photo taken straight down from `height` meters above it.

    :return: (across, along) in meters: across the flight lines and along them
    """
    return height * camera.sensor_w_mm / camera.focal_mm, height * camera.sensor_h_mm / camera.focal_mm


def ground_sample_distance(camera, height):
    """Size of one pixel on the ground, in meters"""
    return height * (camera.sensor_w_mm / camera.px_w) / camera.focal_mm


def _oblique_geometry(camera, height, gimbal_pitch):
    """The angle from nadir and the slant range to the ground, for a photo taken with the camera tilted
    gimbal_pitch degrees from straight down (DJI's convention: -90 is nadir, -40 is the shallowest oblique
    Pilot 2 offers for the M4T)."""
    alpha = math.radians(90.0 + gimbal_pitch)
    return alpha, height / math.cos(alpha)


def oblique_footprint(camera, height, gimbal_pitch):
    """
    Ground footprint of a photo taken tilted gimbal_pitch degrees from straight down (see _oblique_geometry).

    The along-track edges (the direction of the tilt) are exact: the near and far edge rays lie in the same
    vertical plane as the tilt, so their ground intersections follow directly from the angle from nadir and the
    half of the along-track field of view. The across-track width uses the boresight's slant range in place of
    height in the ordinary (nadir) footprint formula - the same approximation aerial oblique photogrammetry tools
    generally use, exact only for a narrow across-track field of view (comfortably true for the M4T's cameras).
    It also reduces to the ordinary footprint() exactly when gimbal_pitch is -90 (no tilt).

    :return: (across, along) in meters: across the flight line and along it
    """
    alpha, slant = _oblique_geometry(camera, height, gimbal_pitch)
    beta_h = math.atan(camera.sensor_w_mm / 2.0 / camera.focal_mm)
    beta_v = math.atan(camera.sensor_h_mm / 2.0 / camera.focal_mm)
    across = 2.0 * slant * math.tan(beta_h)
    along = height * (math.tan(alpha + beta_v) - math.tan(alpha - beta_v))
    return across, along


def oblique_ground_sample_distance(camera, height, gimbal_pitch):
    """Size of one pixel on the ground at the boresight's slant range, in meters - see oblique_footprint."""
    _, slant = _oblique_geometry(camera, height, gimbal_pitch)
    return slant * (camera.sensor_w_mm / camera.px_w) / camera.focal_mm
