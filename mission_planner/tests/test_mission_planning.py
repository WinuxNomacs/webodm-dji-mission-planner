"""
Tests of the survey planner (missions/). The numbers are checked three ways: by hand, by properties that
must hold for any area (every point of the area is photographed, lines are as far apart as they should be), and
against mission files exported by DJI Pilot 2 for a Matrice 4T or 4E, when those are available
(DJI_KMZ_DIR, default tests/fixtures/dji-kmz - see its README.md for what each file must be).
"""
import io
import math
import os
import unittest
import zipfile
from xml.etree import ElementTree as ET

from django.contrib.gis.geos import Polygon
from django.test import SimpleTestCase

from ..missions.cameras import (CAMERAS, CAMERAS_BY_MODEL, M4T_THERMAL, M4T_WIDE, footprint, ground_sample_distance,
                                  oblique_footprint, oblique_ground_sample_distance)
from pyproj import Geod, Transformer

from ..missions.wpml import AIRCRAFT
from ..missions.planning import MAX_GIMBAL_PITCH, MIN_GIMBAL_PITCH, PlanError, check_gimbal_pitch, plan_oblique_survey, plan_survey

KMZ_DIR = os.environ.get("DJI_KMZ_DIR", os.path.join(os.path.dirname(__file__), "fixtures", "dji-kmz"))
NS = {"k": "http://www.opengis.net/kml/2.2", "w": "http://www.dji.com/wpmz/1.0.6"}
W = "{%s}" % NS["w"]

# A 60 x 40 m rectangle where the samples were flown, sides along north/east
LON0, LAT0 = -85.020728, 42.1030
DLAT = 1 / 111195.0
DLON = DLAT / math.cos(math.radians(LAT0))


def rectangle(width_east=60.0, height_north=40.0, lon=LON0, lat=LAT0):
    return [(lon, lat), (lon + width_east * DLON, lat), (lon + width_east * DLON, lat + height_north * DLAT),
            (lon, lat + height_north * DLAT)]


def to_metric(points, origin=None):
    """The points in metres, in an azimuthal equidistant frame centered on origin (true distances from it), by default
    the first point"""
    lon, lat = (origin or points[0])[:2]
    t = Transformer.from_crs(4326, "+proj=aeqd +lat_0=%r +lon_0=%r +ellps=WGS84" % (lat, lon), always_xy=True)
    return [t.transform(*p[:2]) for p in points]


GEOD = Geod(ellps="WGS84")


def distance(a, b):
    return GEOD.inv(a[0], a[1], b[0], b[1])[2]


def bearing(a, b):
    """True bearing from a to b, in degrees"""
    return GEOD.inv(a[0], a[1], b[0], b[1])[0] % 360


def line_distance(line, point):
    """Distance in meters from a point to the (infinite) line through the two ends of `line`"""
    (x0, y0), (x1, y1), (px, py) = to_metric([line[0], line[1], point])
    length = math.hypot(x1 - x0, y1 - y0)
    return abs((x1 - x0) * (py - y0) - (y1 - y0) * (px - x0)) / length


def geodesic_line_distance(line, point):
    """Distance in meters from a point to the geodesic through the two ends of `line`, on the ellipsoid"""
    azimuth = GEOD.inv(*line[0], *line[1])[0]
    to_point, _, d = GEOD.inv(*line[0], *point)
    return abs(d * math.sin(math.radians(to_point - azimuth)))


class TestCameras(SimpleTestCase):
    def test_footprint_is_size_times_height_over_focal_length(self):
        across, along = footprint(M4T_THERMAL, 100.0)
        self.assertAlmostEqual(across, 100 * 7.68 / 12.0, places=9)
        self.assertAlmostEqual(along, 100 * 6.144 / 12.0, places=9)
        self.assertAlmostEqual(across / along, 640 / 512.0, places=9)

    def test_footprints_grow_with_height(self):
        for camera in CAMERAS.values():
            a1, b1 = footprint(camera, 10.0)
            a2, b2 = footprint(camera, 20.0)
            self.assertAlmostEqual(a2, 2 * a1, places=9)
            self.assertAlmostEqual(b2, 2 * b1, places=9)

    def test_ground_sample_distance(self):
        # the thermal camera: 12 um pixels behind a 12 mm lens see 1 mm per meter of height
        self.assertAlmostEqual(ground_sample_distance(M4T_THERMAL, 100.0), 0.1, places=9)
        self.assertAlmostEqual(ground_sample_distance(M4T_THERMAL, 16.0), 0.016, places=9)
        self.assertLess(ground_sample_distance(M4T_WIDE, 16.0), 0.006)         # 0.5 cm: the RGB camera

    def test_the_wide_camera_sees_more_than_the_thermal_one(self):
        for height in (10.0, 100.0):
            self.assertGreater(footprint(M4T_WIDE, height)[0], footprint(M4T_THERMAL, height)[0])
            self.assertGreater(footprint(M4T_WIDE, height)[1], footprint(M4T_THERMAL, height)[1])


class TestObliqueCameras(SimpleTestCase):
    """oblique_footprint/oblique_ground_sample_distance (see their docstrings for the geometry): -90 (nadir) must
    match the ordinary footprint()/ground_sample_distance() exactly, and tilting further must only make the
    footprint bigger (a tilted camera always sees more ground than a straight-down one at the same height)."""

    def test_minus_90_matches_the_ordinary_nadir_footprint(self):
        for camera in CAMERAS.values():
            oa, ob = oblique_footprint(camera, 50.0, -90)
            a, b = footprint(camera, 50.0)
            self.assertAlmostEqual(oa, a, places=9)
            self.assertAlmostEqual(ob, b, places=9)
            self.assertAlmostEqual(oblique_ground_sample_distance(camera, 50.0, -90), ground_sample_distance(camera, 50.0), places=9)

    def test_tilting_further_from_nadir_grows_the_footprint(self):
        for camera in CAMERAS.values():
            across_90, along_90 = oblique_footprint(camera, 50.0, -90)
            across_45, along_45 = oblique_footprint(camera, 50.0, -45)
            self.assertGreater(across_45, across_90)
            self.assertGreater(along_45, along_90)
            self.assertGreater(oblique_ground_sample_distance(camera, 50.0, -45), oblique_ground_sample_distance(camera, 50.0, -90))

    def test_footprint_grows_with_height_at_a_fixed_tilt(self):
        for camera in CAMERAS.values():
            a1, b1 = oblique_footprint(camera, 10.0, -45)
            a2, b2 = oblique_footprint(camera, 20.0, -45)
            self.assertAlmostEqual(a2, 2 * a1, places=9)
            self.assertAlmostEqual(b2, 2 * b1, places=9)


class TestGimbalPitchValidation(SimpleTestCase):
    def test_accepts_the_range_pilot_2_offers(self):
        check_gimbal_pitch(MIN_GIMBAL_PITCH)
        check_gimbal_pitch(MAX_GIMBAL_PITCH)
        check_gimbal_pitch(-45.0)

    def test_refuses_outside_the_range_or_not_a_number(self):
        for bad in (-90.0, -39.9, -85.1, 0.0, float("nan"), float("inf"), "steep"):
            with self.assertRaises(PlanError):
                check_gimbal_pitch(bad)


class TestSpacing(SimpleTestCase):
    def test_the_lines_and_photos_are_spaced_for_the_overlaps(self):
        plan = plan_survey(rectangle(), 0, 50.0, [M4T_THERMAL], overlap_h=80, overlap_w=70)
        across, along = footprint(M4T_THERMAL, 50.0)
        self.assertAlmostEqual(plan.across, across, places=9)
        self.assertAlmostEqual(plan.along, along, places=9)
        self.assertAlmostEqual(plan.spacing, 0.3 * across, places=9)
        self.assertAlmostEqual(plan.interval, 0.2 * along, places=9)

    def test_the_smallest_footprint_of_the_cameras_decides(self):
        both = plan_survey(rectangle(), 0, 50.0, [M4T_WIDE, M4T_THERMAL])
        thermal = plan_survey(rectangle(), 0, 50.0, [M4T_THERMAL])
        wide = plan_survey(rectangle(), 0, 50.0, [M4T_WIDE])
        self.assertEqual((both.spacing, both.interval), (thermal.spacing, thermal.interval))
        self.assertGreater(wide.spacing, thermal.spacing)

    def test_more_overlap_means_closer_lines_and_photos(self):
        low = plan_survey(rectangle(), 0, 30.0, [M4T_THERMAL], overlap_h=60, overlap_w=60)
        high = plan_survey(rectangle(), 0, 30.0, [M4T_THERMAL], overlap_h=90, overlap_w=90)
        self.assertLess(high.spacing, low.spacing)
        self.assertLess(high.interval, low.interval)
        self.assertGreater(len(high.lines), len(low.lines))
        self.assertGreater(high.photos, low.photos)

    def test_the_speed_leaves_time_between_photos(self):
        plan = plan_survey(rectangle(), 0, 50.0, [M4T_THERMAL], overlap_h=80)
        self.assertAlmostEqual(plan.max_speed, plan.interval / 1.25, places=9)
        self.assertAlmostEqual(plan_survey(rectangle(), 0, 50.0, [M4T_THERMAL], min_shot_interval=2.0).max_speed,
                               plan.interval / 2.0, places=9)


class TestObliqueSpacing(SimpleTestCase):
    """plan_oblique_survey shares _survey_plan with plan_survey (see planning.py) - only the spacing/interval-
    producing footprint differs, so these mirror TestSpacing's cases rather than repeating TestLines/TestCoverage's
    geometry checks, which _survey_plan already covers for any footprint."""

    def test_the_lines_and_photos_are_spaced_for_the_oblique_footprint(self):
        plan = plan_oblique_survey(rectangle(), 0, 50.0, [M4T_THERMAL], -45.0, overlap_h=80, overlap_w=70)
        across, along = oblique_footprint(M4T_THERMAL, 50.0, -45.0)
        self.assertAlmostEqual(plan.across, across, places=9)
        self.assertAlmostEqual(plan.along, along, places=9)
        self.assertAlmostEqual(plan.spacing, 0.3 * across, places=9)
        self.assertAlmostEqual(plan.interval, 0.2 * along, places=9)

    def test_a_steeper_tilt_away_from_nadir_needs_fewer_lines(self):
        shallow = plan_oblique_survey(rectangle(), 0, 50.0, [M4T_THERMAL], -40.0)   # closer to the horizon: bigger footprint
        steep = plan_oblique_survey(rectangle(), 0, 50.0, [M4T_THERMAL], -85.0)     # closer to nadir: smaller footprint
        nadir = plan_survey(rectangle(), 0, 50.0, [M4T_THERMAL])
        self.assertLessEqual(len(shallow.lines), len(steep.lines))
        self.assertLessEqual(len(steep.lines), len(nadir.lines))

    def test_refuses_a_gimbal_pitch_outside_pilot_2s_range(self):
        with self.assertRaises(PlanError):
            plan_oblique_survey(rectangle(), 0, 50.0, [M4T_THERMAL], -90.0)
        with self.assertRaises(PlanError):
            plan_oblique_survey(rectangle(), 0, 50.0, [M4T_THERMAL], -10.0)

    def test_still_validates_the_ordinary_survey_inputs(self):
        with self.assertRaises(PlanError):
            plan_oblique_survey(rectangle(), 0, 600.0, [M4T_THERMAL], -45.0)      # height out of range


class TestLines(SimpleTestCase):
    def test_a_north_south_survey_of_a_rectangle(self):
        plan = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL], overlap_h=80, overlap_w=70)
        across = footprint(M4T_THERMAL, 30.0)[0]       # 19.2 m: lines 5.76 m apart
        self.assertEqual(len(plan.lines), int(math.ceil(60 / (0.3 * across))))
        for line in plan.lines:
            self.assertEqual(len(line), 2)
            self.assertAlmostEqual(distance(*line), 40.0, delta=0.25)        # each line crosses the area (map grid meters)
            self.assertTrue(abs(((bearing(*line) + 90) % 180) - 90) < 0.05, bearing(*line))     # true north/south

    def test_lines_are_flown_back_and_forth(self):
        plan = plan_survey(rectangle(), 0, 30.0, [M4T_THERMAL])
        headings = [round(bearing(*l)) % 360 for l in plan.lines]
        self.assertEqual(headings, [0 if i % 2 == 0 else 180 for i in range(len(plan.lines))])
        # the end of a line is close to the start of the next: no long jump between lines
        for a, b in zip(plan.lines, plan.lines[1:]):
            self.assertAlmostEqual(distance(a[1], b[0]), plan.spacing, delta=0.05)

    def test_neighboring_lines_are_exactly_the_spacing_apart(self):
        plan = plan_survey(rectangle(), 0, 30.0, [M4T_THERMAL])
        for a, b in zip(plan.lines, plan.lines[1:]):
            self.assertAlmostEqual(line_distance(a, b[0]), plan.spacing, delta=0.02)
            self.assertAlmostEqual(line_distance(a, b[1]), plan.spacing, delta=0.02)      # and they are parallel

    def test_the_lines_are_centered_on_the_area(self):
        plan = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL])
        area = rectangle(60, 40)
        west, east = (area[0], area[3]), (area[1], area[2])      # the sides of the area that run north-south
        self.assertAlmostEqual(line_distance(west, plan.lines[0][0]), line_distance(east, plan.lines[-1][0]), delta=0.05)

    def test_the_margin_extends_the_lines_at_both_ends(self):
        plain = plan_survey(rectangle(), 0, 30.0, [M4T_THERMAL], margin=0)
        wider = plan_survey(rectangle(), 0, 30.0, [M4T_THERMAL], margin=5)
        for a, b in zip(plain.lines, wider.lines):
            self.assertAlmostEqual(distance(*b), distance(*a) + 10.0, delta=0.05)
        self.assertGreater(wider.distance, plain.distance)

    def test_every_direction_gives_lines_along_it(self):
        for direction in (0, 45, 90, 181, 270, 359):
            plan = plan_survey(rectangle(80, 80), direction, 30.0, [M4T_THERMAL])
            for line in plan.lines:
                self.assertTrue(abs(((bearing(*line) - direction + 90) % 180) - 90) < 0.05, (direction, bearing(*line)))

    def test_the_direction_is_a_true_bearing_not_a_grid_one(self):
        # Here true north is 1.33 degrees away from UTM's grid north: lines must follow the meridians, or they drift a
        # meter over 100 m
        plan = plan_survey(rectangle(60, 100), 0, 30.0, [M4T_THERMAL])
        for line in plan.lines:
            self.assertLess(abs(((bearing(*line) + 90) % 180) - 90), 0.01)
            self.assertAlmostEqual(line[0][0], line[1][0], delta=1e-9 * 1e5)        # same longitude: along a meridian

    def test_the_lines_are_spaced_as_asked_on_the_ground_anywhere_in_a_utm_zone(self):
        # UTM metres are 0.9996 ground metres on a zone's central meridian and 1.001 at its edge on the equator
        for lon, lat in ((-81.0, 41.0), (-84.02, 0.5), (-79.53, 41.49)):
            plan = plan_survey(rectangle(2000, 1500, lon, lat), 30.0, 60.0, [M4T_WIDE])
            for a, b in zip(plan.lines, plan.lines[1:3]):
                self.assertAlmostEqual(geodesic_line_distance(a, b[0]), plan.spacing, delta=0.001, msg=(lon, lat))

    def test_a_single_line_covers_a_narrow_area(self):
        plan = plan_survey(rectangle(2, 40), 0, 30.0, [M4T_THERMAL])
        self.assertEqual(len(plan.lines), 1)
        self.assertTrue(any("narrower" in w for w in plan.warnings))

    def test_no_warnings_for_an_ordinary_survey(self):
        self.assertEqual(plan_survey(rectangle(), 0, 30.0, [M4T_THERMAL]).warnings, [])

    def test_a_concave_area_is_flown_in_pieces(self):
        # a U opening to the north: east-west lines through the arms have two pieces where the notch is
        u = self.u_shape()
        plan = plan_survey(u, 90, 30.0, [M4T_THERMAL])
        lengths = sorted(round(distance(*l)) for l in plan.lines)
        self.assertIn(60, lengths)                       # lines through the base cross the whole area
        self.assertEqual(lengths.count(20) % 2, 0)       # lines through the arms: two pieces of 20 m each
        self.assertGreater(lengths.count(20), 0)
        self.assertGreater(len(plan.lines), int(math.ceil(60 / plan.spacing)))
        self.assertNotIn(40, lengths)                    # nothing crosses the notch

    @staticmethod
    def u_shape():
        return [(LON0, LAT0), (LON0 + 60 * DLON, LAT0), (LON0 + 60 * DLON, LAT0 + 60 * DLAT), (LON0 + 40 * DLON, LAT0 + 60 * DLAT),
                (LON0 + 40 * DLON, LAT0 + 20 * DLAT), (LON0 + 20 * DLON, LAT0 + 20 * DLAT), (LON0 + 20 * DLON, LAT0 + 60 * DLAT),
                (LON0, LAT0 + 60 * DLAT)]


class TestCoverage(SimpleTestCase):
    """Whatever the area, every point of it must be inside the photos of at least one line"""

    def swaths(self, plan, origin):
        metric = [to_metric(l, origin) for l in plan.lines]
        result = []
        half = plan.across / 2.0
        for (x0, y0), (x1, y1) in metric:
            length = math.hypot(x1 - x0, y1 - y0)
            ux, uy = (x1 - x0) / length, (y1 - y0) / length
            nx, ny = -uy * half, ux * half
            # the photos at both ends of the line reach half a footprint beyond it
            ex, ey = ux * plan.along / 2.0, uy * plan.along / 2.0
            x0, y0, x1, y1 = x0 - ex, y0 - ey, x1 + ex, y1 + ey
            result.append(Polygon(((x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny), (x0 + nx, y0 + ny))))
        return result

    def covered_fraction(self, area, plan):
        poly = Polygon([tuple(p) for p in to_metric(area)] + [to_metric(area)[0]])
        union = None
        for s in self.swaths(plan, area[0]):
            union = s if union is None else union.union(s)
        return poly.intersection(union).area / poly.area

    def test_the_photos_cover_the_whole_area(self):
        cases = [rectangle(60, 40), rectangle(17, 93), rectangle(200, 30), rectangle(5, 5)]
        for area in cases:
            for direction in (0, 30, 90, 181):
                for height in (14.0, 50.0, 100.5):
                    plan = plan_survey(area, direction, height, [M4T_WIDE, M4T_THERMAL], overlap_h=80, overlap_w=70)
                    self.assertGreater(self.covered_fraction(area, plan), 0.999, (area[2], direction, height))

    def test_neighboring_lines_overlap_as_requested(self):
        plan = plan_survey(rectangle(100, 60), 0, 50.0, [M4T_THERMAL], overlap_w=70)
        swaths = self.swaths(plan, (LON0, LAT0))
        for a, b in zip(swaths, swaths[1:]):
            shared = a.intersection(b).area / a.area
            self.assertAlmostEqual(shared, 0.70, delta=0.01)

    def test_a_concave_area_is_covered_too(self):
        for direction in (0, 90, 45):
            u = TestLines.u_shape()
            plan = plan_survey(u, direction, 30.0, [M4T_THERMAL])
            self.assertGreater(self.covered_fraction(u, plan), 0.999, direction)


class TestAreaAndRouteStart(SimpleTestCase):
    def test_the_area_is_that_of_the_polygon(self):
        self.assertAlmostEqual(plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL]).area, 2400, delta=6)
        self.assertAlmostEqual(plan_survey(rectangle(10, 10), 0, 30.0, [M4T_THERMAL]).area, 100, delta=0.5)
        # the same whatever the direction of the lines
        for direction in (0, 33, 90, 181):
            self.assertAlmostEqual(plan_survey(rectangle(60, 40), direction, 30.0, [M4T_THERMAL]).area, 2400, delta=6)
        self.assertAlmostEqual(plan_survey(TestLines.u_shape(), 90, 30.0, [M4T_THERMAL]).area, 2800, delta=8)      # 60x60 less a 20x40 notch

    def corners(self):
        a = rectangle(60, 40)
        return {"sw": a[0], "se": a[1], "ne": a[2], "nw": a[3]}

    def ends_of_first_and_last_lines(self):
        plan = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL])
        return plan, [plan.lines[0][0], plan.lines[0][1], plan.lines[-1][0], plan.lines[-1][1]]

    def test_without_a_start_the_route_begins_as_before(self):
        plan = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL])
        again = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL], route_start=None)
        self.assertEqual(plan.lines, again.lines)

    def test_the_route_begins_at_the_end_of_a_line_nearest_to_the_start(self):
        default, ends = self.ends_of_first_and_last_lines()
        for name, corner in self.corners().items():
            plan = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL], route_start=corner)
            nearest = min(ends, key=lambda e: distance(e, corner))
            self.assertLess(distance(plan.waypoints[0], nearest), 0.05, name)

    def test_the_four_starts_are_four_different_routes_over_the_same_ground(self):
        starts = set()
        for corner in self.corners().values():
            plan = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL], route_start=corner)
            starts.add((round(plan.waypoints[0][0], 6), round(plan.waypoints[0][1], 6)))

        self.assertEqual(len(starts), 4)
        default = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL])
        segments = lambda p: sorted(tuple(sorted((round(a[0], 7), round(a[1], 7)) for a in l)) for l in p.lines)
        for corner in self.corners().values():
            plan = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL], route_start=corner)
            self.assertEqual(segments(plan), segments(default))                       # the same lines...
            self.assertAlmostEqual(plan.distance, default.distance, delta=0.05)       # ...as long a flight
            self.assertEqual(plan.photos, default.photos)

    def test_every_start_still_flies_back_and_forth_line_by_line(self):
        for corner in self.corners().values():
            plan = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL], route_start=corner)
            headings = [round(bearing(*l)) % 360 for l in plan.lines]
            self.assertEqual(len(set(headings)), 2)
            self.assertTrue(all(headings[i] != headings[i + 1] for i in range(len(headings) - 1)))
            for a, b in zip(plan.lines, plan.lines[1:]):
                self.assertAlmostEqual(distance(a[1], b[0]), plan.spacing, delta=0.05)

    def test_a_start_far_from_the_area_picks_the_nearest_end(self):
        default, ends = self.ends_of_first_and_last_lines()
        far_north_east = (LON0 + 500 * DLON, LAT0 + 500 * DLAT)
        plan = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL], route_start=far_north_east)
        self.assertLess(distance(plan.waypoints[0], min(ends, key=lambda e: distance(e, far_north_east))), 0.05)

    def test_a_start_keeps_a_notched_area_covered(self):
        u = TestLines.u_shape()
        for corner in (u[0], u[2], u[7]):
            plan = plan_survey(u, 90, 30.0, [M4T_THERMAL], route_start=corner)
            self.assertGreater(TestCoverage().covered_fraction(u, plan), 0.999)

    def test_refuses_a_start_that_is_not_a_place(self):
        for bad in ([1], "here", [float("nan"), 1], ["a", "b"], [None, None]):
            with self.assertRaises(PlanError):
                plan_survey(rectangle(), 0, 30.0, [M4T_THERMAL], route_start=bad)


class TestSummary(SimpleTestCase):
    def test_distance_photos_and_duration_add_up(self):
        plan = plan_survey(rectangle(60, 40), 0, 30.0, [M4T_THERMAL], overlap_h=80, overlap_w=70)
        survey = sum(distance(*l) for l in plan.lines)
        turns = sum(distance(a[1], b[0]) for a, b in zip(plan.lines, plan.lines[1:]))
        self.assertAlmostEqual(plan.distance, survey + turns, delta=0.05)
        self.assertAlmostEqual(plan.duration, plan.distance / plan.max_speed, places=6)
        self.assertEqual(plan.photos, sum(int(distance(*l) // plan.interval) + 1 for l in plan.lines))
        self.assertEqual(plan.waypoints, [p for l in plan.lines for p in l])


class TestInvalidInput(SimpleTestCase):
    def check(self, message, **kw):
        args = dict(polygon=rectangle(), direction=0, height=30.0, cameras=[M4T_THERMAL])
        args.update(kw)
        with self.assertRaises(PlanError) as ctx:
            plan_survey(**args)
        self.assertIn(message, str(ctx.exception))

    def test_refuses_what_cannot_be_flown(self):
        self.check("at least one camera", cameras=[])
        self.check("height must be between", height=0.5)
        self.check("height must be between", height=900)
        self.check("height must be between", height=float("nan"))
        self.check("overlap along", overlap_h=5)
        self.check("overlap across", overlap_w=99)
        self.check("direction", direction=float("inf"))
        self.check("direction", direction="north")
        self.check("margin", margin=-1)
        self.check("at least 3 corners", polygon=rectangle()[:2])
        self.check("at least 3 corners", polygon=[(0, 0), (1, float("nan")), (2, 2)])

    def test_refuses_a_bowtie_and_a_flat_area(self):
        bowtie = [(LON0, LAT0), (LON0 + 40 * DLON, LAT0 + 40 * DLAT), (LON0 + 40 * DLON, LAT0), (LON0, LAT0 + 40 * DLAT)]
        self.check("not a valid polygon", polygon=bowtie)
        line = [(LON0, LAT0), (LON0 + 10 * DLON, LAT0), (LON0 + 20 * DLON, LAT0)]
        self.check("not a valid polygon", polygon=line)


# -- against mission files exported by DJI Pilot 2 -------------------------------------------------------------------

def read_kmz(name):
    path = os.path.join(KMZ_DIR, name)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return parse_kmz(f.read())


def parse_kmz(data):
    """What a Pilot 2 (or LuxODM) mission says: its aircraft, area, direction, height, overlaps, cameras and waypoints"""
    z = zipfile.ZipFile(io.BytesIO(data))
    template = ET.fromstring(z.read("wpmz/template.kml"))
    waylines = ET.fromstring(z.read("wpmz/waylines.wpml"))

    pm = template.find("k:Document/k:Folder/k:Placemark", NS)
    coords = pm.find("k:Polygon/k:outerBoundaryIs/k:LinearRing/k:coordinates", NS).text.split()
    polygon = [tuple(float(v) for v in c.split(",")[:2]) for c in coords]
    if polygon[0] == polygon[-1]:
        polygon = polygon[:-1]

    def text(path):
        return pm.find(path, NS).text if pm.find(path, NS) is not None else None

    folder = template.find("k:Document/k:Folder", NS)
    height = folder.find("w:waylineCoordinateSysParam/w:globalShootHeight", NS).text
    overlap = {k: float(pm.find("w:overlap/w:" + k, NS).text) for k in ("orthoCameraOverlapH", "orthoCameraOverlapW")}
    formats = folder.find("w:payloadParam/w:imageFormat", NS).text.split(",")
    drone = template.find("k:Document/w:missionConfig/w:droneInfo", NS)
    drone = (int(drone.find("w:droneEnumValue", NS).text), int(drone.find("w:droneSubEnumValue", NS).text))
    model = next(m for m, a in AIRCRAFT.items() if a.drone == drone)

    triggers = [float(e.text) for e in waylines.iter(W + "actionTriggerParam")]
    points = []
    for p in waylines.iter("{%s}Placemark" % NS["k"]):
        points.append(tuple(float(v) for v in p.find("k:Point/k:coordinates", NS).text.split(",")[:2]))
    return {"model": model, "polygon": polygon, "direction": float(text("w:direction")), "margin": float(text("w:margin")), "height": float(height),
            "overlap_h": overlap["orthoCameraOverlapH"], "overlap_w": overlap["orthoCameraOverlapW"],
            "cameras": [CAMERAS_BY_MODEL[model][f] for f in formats], "interval": triggers[0] if triggers else None, "waypoints": points}


def plan_like(name):
    """A sample mission and our plan of the same area with the same settings"""
    sample = read_kmz(name)
    plan = plan_survey(sample["polygon"], sample["direction"], sample["height"], sample["cameras"],
                       overlap_h=sample["overlap_h"], overlap_w=sample["overlap_w"], margin=sample["margin"])
    return sample, plan


def hops(sample):
    """The distances between a mission's consecutive waypoints"""
    pts = to_metric(sample["waypoints"])
    return [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]


@unittest.skipUnless(os.path.isfile(os.path.join(KMZ_DIR, "TestAreaRoute.kmz")), "DJI Pilot 2 sample missions are not available")
class TestAgainstPilot2(SimpleTestCase):
    def test_photo_interval_matches_within_a_fraction_of_a_percent(self):
        for name in ("TestAreaRoute.kmz", "HomerunThermalOnly.kmz"):
            sample, plan = plan_like(name)
            self.assertAlmostEqual(plan.interval / sample["interval"], 1.0, delta=0.002, msg=name)

    def test_line_spacing_matches_the_hop_between_lines(self):
        # Pilot 2 flies from one line to the next in a hop as long as the distance between the lines
        for name in ("TestAreaRoute.kmz", "HomerunThermalOnly.kmz"):
            sample, plan = plan_like(name)
            self.assertTrue(any(abs(h / plan.spacing - 1.0) < 0.01 for h in hops(sample)), name)

    def test_the_lines_cover_the_area_the_way_pilot_2_flew_it(self):
        sample, plan = plan_like("TestAreaRoute.kmz")
        self.assertIn(len(plan.lines), (3, 4))            # Pilot 2 flew 3 lines plus a transit: see the module notes
        # the lines through the middle of the area are as long as Pilot 2's (70.1 to 70.25 m); the ones at the slanted
        # edges of this area are shorter
        for length in sorted(distance(*l) for l in plan.lines)[-2:]:
            self.assertAlmostEqual(length, 70.1, delta=1.5)

    def test_the_lines_run_the_way_pilot_2_flew_them(self):
        sample, plan = plan_like("TestAreaRoute.kmz")
        # Pilot 2 planned direction 181: its first waypoint's heading is 1 degree; ours run along the same axis
        for line in plan.lines:
            self.assertLess(abs(((bearing(*line) - 181 + 90) % 180) - 90), 0.05)
        first_pilot2_leg = bearing(sample["waypoints"][0], sample["waypoints"][1])
        self.assertLess(abs(((first_pilot2_leg - 181 + 90) % 180) - 90), 0.5)


# Smart Oblique area missions over one polygon at several heights, wide camera only, 80/80 (M4E) and 80/70 (M4T)
# overlap. Pilot 2 named each file after the GSD it shows, computed at globalShootHeight; the photos are taken by
# time, so there is no photo interval to compare, only the GSD and the line spacing.
SMART_OBLIQUE_AREAS = {
    "m4e-test-area-alt100m-gsd2.76cm-ogsd3.89cm.kmz": ("m4e", 2.76),
    "m4e-test-area-alt50m-gsd1.41cm-ogsd1.99cm.kmz": ("m4e", 1.41),
    "m4e-test-area-alt15m-gsd0.47cm-ogsd0.67cm.kmz": ("m4e", 0.47),
    "m4t-test-area-alt15m-gsd0.62cm-ogsd0.88cm.kmz": ("m4t", 0.62),
}


@unittest.skipUnless(os.path.isfile(os.path.join(KMZ_DIR, "m4e-test-area-alt50m-gsd1.41cm-ogsd1.99cm.kmz")),
                     "DJI Pilot 2 M4E sample missions are not available")
class TestCamerasAgainstPilot2(SimpleTestCase):
    def test_the_aircraft_model_is_read_from_the_file(self):
        for name, (model, gsd) in SMART_OBLIQUE_AREAS.items():
            self.assertEqual(read_kmz(name)["model"], model, name)

    def test_the_ground_sample_distance_matches_pilot_2s_within_one_percent(self):
        for name, (model, gsd) in SMART_OBLIQUE_AREAS.items():
            sample = read_kmz(name)
            ours = ground_sample_distance(sample["cameras"][0], sample["height"]) * 100
            self.assertAlmostEqual(ours / gsd, 1.0, delta=0.01, msg=name)

    def test_the_line_spacing_matches_the_hop_between_lines(self):
        for name in SMART_OBLIQUE_AREAS:
            sample, plan = plan_like(name)
            self.assertTrue(any(abs(h / plan.spacing - 1.0) < 0.01 for h in hops(sample)), name)


# Calibration set for the line-count formula (ceil(width / spacing)): 8 synthetic Pilot 2 missions, all the same
# 100 m (N-S) x <width> m (E-W) rectangle, height 50 m, course 0 deg, both lenses, 80/70 overlap, no margin - only
# the width (and so the number of lines DJI plans) varies. Distinguishes the current formula from a competing
# "first line's own footprint already covers ground" hypothesis, which predicts fewer lines at every width tested
# here; the current formula matched DJI's actual line count exactly at all 8 widths when this was calibrated.
CALIBRATION_WIDTHS = (15, 20, 30, 35, 45, 60, 75, 100)


@unittest.skipUnless(os.path.isfile(os.path.join(KMZ_DIR, "TestAreaKMZ-15.kmz")), "DJI Pilot 2 calibration missions are not available")
class TestLineCountAgainstPilot2(SimpleTestCase):
    def test_the_line_count_matches_pilot_2_at_every_calibrated_width(self):
        for width in CALIBRATION_WIDTHS:
            sample = read_kmz("TestAreaKMZ-%d.kmz" % width)
            actual_lines = len(sample["waypoints"]) // 2
            plan = plan_survey(sample["polygon"], sample["direction"], sample["height"], sample["cameras"],
                               overlap_h=sample["overlap_h"], overlap_w=sample["overlap_w"], margin=sample["margin"])
            self.assertEqual(len(plan.lines), actual_lines, "width=%d" % width)


# -- structure of Pilot 2's own oblique (mapping3d) exports, checked directly (not through parse_kmz/plan_survey,
# which only understand the single-folder ortho shape) - see missions.wpml's module docstring and OBLIQUE_HEADINGS

def read_oblique_kmz(name):
    path = os.path.join(KMZ_DIR, name)
    with open(path, "rb") as f:
        z = zipfile.ZipFile(io.BytesIO(f.read()))
        return ET.fromstring(z.read("wpmz/template.kml")), ET.fromstring(z.read("wpmz/waylines.wpml"))


@unittest.skipUnless(os.path.isfile(os.path.join(KMZ_DIR, "testkmz-oblique-alt.kmz")), "DJI Pilot 2 oblique sample missions are not available")
class TestObliqueAgainstPilot2(SimpleTestCase):
    def test_the_template_is_mapping3d_and_drops_the_ortho_only_flags(self):
        t, w = read_oblique_kmz("testkmz-oblique-alt.kmz")
        folder = t.find("k:Document/k:Folder", NS)
        self.assertEqual(folder.find("w:templateType", NS).text, "mapping3d")
        pm = folder.find("k:Placemark", NS)
        self.assertIsNotNone(pm.find("w:inclinedGimbalPitch", NS))
        self.assertIsNotNone(pm.find("w:inclinedFlightSpeed", NS))
        for tag in ("elevationOptimizeEnable", "smartObliqueEnable", "quickOrthoMappingEnable",
                   "facadeWaylineEnable", "isLookAtSceneSet", "doubleGridWaylineEnable"):
            self.assertIsNone(pm.find("w:" + tag, NS), tag)

    def test_the_template_keeps_both_ortho_and_inclined_overlap(self):
        t, w = read_oblique_kmz("testkmz-oblique-alt.kmz")
        overlap = t.find("k:Document/k:Folder/k:Placemark/w:overlap", NS)
        for tag in ("orthoCameraOverlapH", "orthoCameraOverlapW", "inclinedCameraOverlapH", "inclinedCameraOverlapW"):
            self.assertIsNotNone(overlap.find("w:" + tag, NS), tag)

    def test_the_waylines_have_five_folders_nadir_then_four_tilted(self):
        t, w = read_oblique_kmz("testkmz-oblique-alt.kmz")
        folders = w.findall("k:Document/k:Folder", NS)
        self.assertEqual(len(folders), 5)
        self.assertEqual([f.find("w:waylineId", NS).text for f in folders], ["0", "1", "2", "3", "4"])
        pitches = [float(f.find("w:startActionGroup/w:action/w:actionActuatorFuncParam/w:gimbalPitchRotateAngle", NS).text) for f in folders]
        self.assertEqual(pitches[0], -90)
        self.assertTrue(all(p == -45 for p in pitches[1:]), pitches)

    def test_the_four_tilted_folders_lock_the_heading_instead_of_following_the_wayline(self):
        t, w = read_oblique_kmz("testkmz-oblique-alt.kmz")
        folders = w.findall("k:Document/k:Folder", NS)
        nadir_modes = {pm.find("w:waypointHeadingParam/w:waypointHeadingMode", NS).text for pm in folders[0].findall("k:Placemark", NS)[:-1]}
        self.assertEqual(nadir_modes, {"followWayline"})
        angles = []
        for f in folders[1:]:
            pms = f.findall("k:Placemark", NS)
            modes_angles = {(pm.find("w:waypointHeadingParam/w:waypointHeadingMode", NS).text,
                             round(float(pm.find("w:waypointHeadingParam/w:waypointHeadingAngle", NS).text)))
                            for pm in pms[:-1]}
            self.assertEqual(len(modes_angles), 1, "every waypoint but the last should share one (mode, angle)")
            mode, angle = next(iter(modes_angles))
            self.assertEqual(mode, "fixed")
            angles.append(angle)
            last = pms[-1].find("w:waypointHeadingParam", NS)
            self.assertEqual((last.find("w:waypointHeadingMode", NS).text, last.find("w:waypointHeadingAngle", NS).text),
                             ("followWayline", "0"))
        self.assertEqual(sorted(round((a - angles[0]) % 360) for a in angles), [0, 90, 180, 270])

    def test_alt_and_asl_use_different_height_modes(self):
        t_alt, _ = read_oblique_kmz("testkmz-oblique-alt.kmz")
        t_asl, _ = read_oblique_kmz("testkmz-oblique-asl.kmz")
        self.assertEqual(t_alt.find("k:Document/k:Folder/w:waylineCoordinateSysParam/w:heightMode", NS).text, "relativeToStartPoint")
        self.assertEqual(t_asl.find("k:Document/k:Folder/w:waylineCoordinateSysParam/w:heightMode", NS).text, "EGM96")

    def test_the_inclined_speed_field_is_written_whether_or_not_it_was_set_separately(self):
        t_on, _ = read_oblique_kmz("testkmz-oblique-speed-on.kmz")
        t_off, _ = read_oblique_kmz("testkmz-oblique-speed-off.kmz")
        for t in (t_on, t_off):
            pm = t.find("k:Document/k:Folder/k:Placemark", NS)
            self.assertIsNotNone(pm.find("w:inclinedFlightSpeed", NS))
