"""
Tests of the mission export (missions/wpml.py). The files are checked against what DJI Pilot 2 writes for a
Matrice 4T (element by element, when the sample missions are available: see test_mission_planning), against the
plan they come from, and against golden files for the exact output.
"""
import io
import math
import os
import re
import unittest
import zipfile
from xml.etree import ElementTree as ET

from django.test import SimpleTestCase

from ..missions import wpml
from ..missions.cameras import M4E_WIDE, M4T_THERMAL, M4T_WIDE
from ..missions.wpml import ExportError, build_kmz, plan_from_settings, settings
from .test_mission_planning import (KMZ_DIR, NS, W, GEOD, distance, parse_kmz, read_kmz, rectangle)

UPDATE = os.environ.get("MP_UPDATE_GOLDEN") == "1"
GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden", "missions")
NOW = 1790011727.518        # a fixed time: the same mission gives the same bytes

# The area, direction, height and overlaps of the Pilot 2 mission TestAreaRoute.kmz
PILOT2_AREA = [(-85.0207969769386, 42.1037487200951), (-85.0215375760992, 42.1037547516642),
               (-85.0216510835836, 42.1031207800876), (-85.020945629745, 42.1031187742014)]


def make(polygon=None, **kw):
    args = dict(polygon=polygon or PILOT2_AREA, direction=181, height=100.5, cameras=[M4T_WIDE, M4T_THERMAL],
                overlap_h=80, overlap_w=70, margin=0, speed=10.2, takeoff_ref_point=(42.103173, -85.020786, 209.782061),
                takeoff_security_height=100, rth_height=100)
    args.update(kw)
    s = settings(**args)
    return plan_from_settings(s), s


def files(plan, s):
    z = zipfile.ZipFile(io.BytesIO(build_kmz(plan, s, now=NOW)))
    return z.read("wpmz/template.kml"), z.read("wpmz/waylines.wpml")


def skeleton(element, depth=0):
    """The tags of an element and everything below it, in order, with their depth: the structure without the values"""
    result = [(depth, element.tag)]
    for child in element:
        result.extend(skeleton(child, depth + 1))
    return result


def golden(test, name, content):
    path = os.path.join(GOLDEN_DIR, name)
    if UPDATE or not os.path.isfile(path):
        if not UPDATE:
            test.fail("Golden file %s is missing. Run with MP_UPDATE_GOLDEN=1 to create it." % name)
        with open(path, "wb") as f:
            f.write(content)
        return
    with open(path, "rb") as f:
        test.assertEqual(rounded(f.read().decode()), rounded(content.decode()), name)


def rounded(text):
    """The text with its numbers to 9 decimal places: the last digits of a distance or a coordinate change with the
    PROJ version, by about 1e-13"""
    return re.sub(r"-?\d+\.\d+", lambda m: ("%.9f" % float(m.group())).rstrip("0").rstrip("."), text)


class TestSettings(SimpleTestCase):
    def check(self, message, **kw):
        with self.assertRaises(ExportError) as ctx:
            make(**kw)
        self.assertIn(message, str(ctx.exception))

    def test_refuses_camera_choices_that_were_never_seen_in_a_pilot_2_file(self):
        self.check("cannot be exported yet", cameras=[M4T_THERMAL])
        self.check("cannot be exported yet", cameras=[])

    def test_accepts_the_camera_choices_that_were(self):
        make(cameras=[M4T_WIDE])
        make(cameras=[M4T_THERMAL, M4T_WIDE])
        make(cameras=[M4E_WIDE], model="m4e")

    def test_refuses_cameras_that_another_model_carries(self):
        self.check("not those of the Matrice 4E", cameras=[M4T_WIDE], model="m4e")
        self.check("not those of the Matrice 4E", cameras=[M4T_WIDE, M4T_THERMAL], model="m4e")
        self.check("not those of the Matrice 4T", cameras=[M4E_WIDE])

    def test_refuses_an_unknown_aircraft_model(self):
        self.check("Unknown aircraft model", model="m5t")

    def test_refuses_what_is_unknown_or_out_of_range(self):
        self.check("height mode", height_mode="aboveTheClouds")
        self.check("finish action", finish_action="explode")
        self.check("remote signal", exit_on_rc_lost="panic")
        self.check("takeoff security height", takeoff_security_height=0)
        self.check("return height", rth_height=5000)
        self.check("return height", rth_height=float("nan"))
        self.check("speed", speed=0)
        self.check("speed", speed=40)
        self.check("speed", speed=float("inf"))
        self.check("takeoff point", takeoff_ref_point=(1, 2))
        self.check("takeoff point", takeoff_ref_point=(1, 2, float("nan")))
        self.check("between the takeoff", transitional_speed=99)

    def test_oblique_agl_is_accepted_and_flown_over_a_dsm(self):
        _, s = make(collection_mode="oblique", gimbal_pitch=-45, height_mode="realTimeFollowSurface")
        self.assertTrue(wpml.uses_dsm(s))
        self.assertFalse(wpml.uses_dsm(make(height_mode="realTimeFollowSurface")[1]))

    def test_oblique_accepts_alt_and_asl_height_modes(self):
        make(collection_mode="oblique", gimbal_pitch=-45, height_mode="relativeToStartPoint")
        make(collection_mode="oblique", gimbal_pitch=-45, height_mode="EGM96",
             takeoff_ref_point=(1, 2, 100), takeoff_ellipsoidal_height=95)

    def test_oblique_requires_a_gimbal_pitch(self):
        self.check("gimbal tilt angle", collection_mode="oblique", height_mode="relativeToStartPoint")
        self.check("gimbal tilt angle", collection_mode="oblique", height_mode="relativeToStartPoint", gimbal_pitch=float("nan"))

    def test_oblique_speed_must_be_in_range(self):
        self.check("oblique speed", collection_mode="oblique", height_mode="relativeToStartPoint", gimbal_pitch=-45,
                   inclined_speed=0)
        self.check("oblique speed", collection_mode="oblique", height_mode="relativeToStartPoint", gimbal_pitch=-45,
                   inclined_speed=40)

    def test_unknown_collection_mode_is_refused(self):
        self.check("collection mode", collection_mode="panoramic")

    def test_oblique_only_settings_are_refused_for_ortho(self):
        self.check("only apply", gimbal_pitch=-45)
        self.check("only apply", inclined_overlap_h=60)
        self.check("only apply", inclined_overlap_w=60)
        self.check("only apply", inclined_speed=5)

    def test_inclined_overlap_defaults_to_the_ortho_overlap(self):
        _, s = make(collection_mode="oblique", height_mode="relativeToStartPoint", gimbal_pitch=-45, overlap_h=85, overlap_w=65)
        self.assertEqual((s.inclined_overlap_h, s.inclined_overlap_w), (85, 65))

    def test_inclined_overlap_can_be_set_separately(self):
        _, s = make(collection_mode="oblique", height_mode="relativeToStartPoint", gimbal_pitch=-45,
                    inclined_overlap_h=60, inclined_overlap_w=50)
        self.assertEqual((s.inclined_overlap_h, s.inclined_overlap_w), (60, 50))

    def test_inclined_speed_defaults_to_none_meaning_mirror_the_global_speed(self):
        _, s = make(collection_mode="oblique", height_mode="relativeToStartPoint", gimbal_pitch=-45)
        self.assertIsNone(s.inclined_speed)


class TestMissionValues(SimpleTestCase):
    def setUp(self):
        self.plan, self.s = make()
        self.template, self.waylines = files(self.plan, self.s)
        self.t = ET.fromstring(self.template)
        self.w = ET.fromstring(self.waylines)

    def text(self, root, path):
        return root.find(path, NS).text

    def test_the_aircraft_and_camera_are_the_matrice_4t_with_the_thermal_and_wide_cameras(self):
        for root in (self.t, self.w):
            self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:droneInfo/w:droneEnumValue"), "99")
            self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:droneInfo/w:droneSubEnumValue"), "1")
            self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:payloadInfo/w:payloadEnumValue"), "89")
            self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:payloadInfo/w:payloadSubEnumValue"), "2")

    def test_the_wide_camera_alone_is_payload_sub_enum_0(self):
        _, s = make(cameras=[M4T_WIDE])
        plan = plan_from_settings(s)
        t = ET.fromstring(files(plan, s)[0])
        self.assertEqual(t.find("k:Document/w:missionConfig/w:payloadInfo/w:payloadSubEnumValue", NS).text, "0")
        self.assertEqual(t.find("k:Document/k:Folder/w:payloadParam/w:imageFormat", NS).text, "visable")

    def test_the_matrice_4e_is_written_with_the_values_pilot_2_gave_it(self):
        _, s = make(cameras=[M4E_WIDE], model="m4e")
        for root in (ET.fromstring(f) for f in files(plan_from_settings(s), s)):
            self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:droneInfo/w:droneEnumValue"), "99")
            self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:droneInfo/w:droneSubEnumValue"), "0")
            self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:payloadInfo/w:payloadEnumValue"), "88")
            self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:payloadInfo/w:payloadSubEnumValue"), "0")

    def test_the_template_carries_the_settings(self):
        folder = "k:Document/k:Folder/"
        self.assertEqual(self.text(self.t, folder + "w:templateType"), "mapping2d")
        self.assertEqual(self.text(self.t, folder + "w:waylineCoordinateSysParam/w:heightMode"), "realTimeFollowSurface")
        self.assertEqual(self.text(self.t, folder + "w:waylineCoordinateSysParam/w:globalShootHeight"), "100.5")
        self.assertEqual(self.text(self.t, folder + "w:waylineCoordinateSysParam/w:surfaceRelativeHeight"), "100.5")
        self.assertEqual(self.text(self.t, folder + "k:Placemark/w:direction"), "181")
        self.assertEqual(self.text(self.t, folder + "k:Placemark/w:overlap/w:orthoCameraOverlapH"), "80")
        self.assertEqual(self.text(self.t, folder + "k:Placemark/w:overlap/w:orthoCameraOverlapW"), "70")
        self.assertEqual(self.text(self.t, folder + "w:payloadParam/w:imageFormat"), "visable,ir")
        # above sea level in the settings, ellipsoidal in the mission (EGM96 here: -34.201275 m)
        self.assertEqual(self.text(self.t, "k:Document/w:missionConfig/w:takeOffRefPoint"), "42.103173,-85.020786,175.580886")
        self.assertEqual(self.text(self.t, "k:Document/w:missionConfig/w:takeOffSecurityHeight"), "100")
        self.assertEqual(self.text(self.t, "k:Document/w:missionConfig/w:globalRTHHeight"), "100")

    def test_the_area_is_closed_and_in_order(self):
        coords = self.text(self.t, "k:Document/k:Folder/k:Placemark/k:Polygon/k:outerBoundaryIs/k:LinearRing/k:coordinates").split()
        points = [tuple(float(v) for v in c.split(",")) for c in coords]
        self.assertEqual(points[0], points[-1])
        self.assertEqual(len(points), len(PILOT2_AREA) + 1)
        for (lon, lat, alt), (x, y) in zip(points, PILOT2_AREA):
            self.assertAlmostEqual(lon, x, places=11)
            self.assertAlmostEqual(lat, y, places=11)
            self.assertEqual(alt, 0)

    def test_the_waylines_hold_the_waypoints_of_the_plan(self):
        placemarks = self.w.findall("k:Document/k:Folder/k:Placemark", NS)
        self.assertEqual(len(placemarks), len(self.plan.nadir.waypoints))
        for i, (pm, (lon, lat)) in enumerate(zip(placemarks, self.plan.nadir.waypoints)):
            x, y = (float(v) for v in pm.find("k:Point/k:coordinates", NS).text.split(","))
            self.assertAlmostEqual(x, lon, places=11)
            self.assertAlmostEqual(y, lat, places=11)
            self.assertEqual(pm.find("w:index", NS).text, str(i))
            self.assertEqual(pm.find("w:executeHeight", NS).text, "100.5")
            self.assertEqual(pm.find("w:waypointSpeed", NS).text, "10.2")

    def test_headings_follow_the_next_leg(self):
        placemarks = self.w.findall("k:Document/k:Folder/k:Placemark", NS)
        pts = self.plan.nadir.waypoints
        for i, pm in enumerate(placemarks[:-1]):
            heading = float(pm.find("w:waypointHeadingParam/w:waypointHeadingAngle", NS).text)
            expected = GEOD.inv(*pts[i], *pts[i + 1])[0]
            self.assertAlmostEqual(heading, expected, places=6)
        self.assertEqual(placemarks[-1].find("w:waypointHeadingParam/w:waypointHeadingAngle", NS).text, "0")

    def test_the_ends_stop_and_the_corners_between_are_rounded(self):
        placemarks = self.w.findall("k:Document/k:Folder/k:Placemark", NS)
        modes = [pm.find("w:waypointTurnParam/w:waypointTurnMode", NS).text for pm in placemarks]
        self.assertEqual(modes[0], "toPointAndStopWithDiscontinuityCurvature")
        self.assertEqual(modes[-1], "toPointAndStopWithDiscontinuityCurvature")
        self.assertTrue(all(m == "coordinateTurn" for m in modes[1:-1]))
        damping = [float(pm.find("w:waypointTurnParam/w:waypointTurnDampingDist", NS).text) for pm in placemarks]
        self.assertEqual((damping[0], damping[-1]), (0.0, 0.0))
        for d in damping[1:-1]:
            self.assertAlmostEqual(d, self.plan.nadir.spacing / 3.0, places=6)         # as Pilot 2: 19.296 / 3 = 6.432

    def test_photos_are_taken_every_interval_between_the_first_and_the_last_waypoint(self):
        groups = self.w.findall("k:Document/k:Folder/k:Placemark/w:actionGroup", NS)
        by_trigger = {g.find("w:actionTrigger/w:actionTriggerType", NS).text: g for g in groups}
        self.assertEqual(set(by_trigger), {"betweenAdjacentPoints", "multipleDistance", "reachPoint"})
        last = len(self.plan.nadir.waypoints) - 1

        photos = by_trigger["multipleDistance"]
        self.assertAlmostEqual(float(photos.find("w:actionTrigger/w:actionTriggerParam", NS).text), self.plan.nadir.interval, places=6)
        self.assertEqual((photos.find("w:actionGroupStartIndex", NS).text, photos.find("w:actionGroupEndIndex", NS).text), ("0", str(last)))
        funcs = [a.find("w:actionActuatorFunc", NS).text for a in photos.findall("w:action", NS)]
        self.assertEqual(funcs, ["gimbalRotate", "startContinuousShooting"])
        self.assertEqual(photos.find("w:action/w:actionActuatorFuncParam/w:gimbalPitchRotateAngle", NS).text, "-90")
        self.assertEqual(photos.findall("w:action", NS)[1].find("w:actionActuatorFuncParam/w:payloadLensIndex", NS).text, "visable,ir")

        stop = by_trigger["reachPoint"]
        self.assertEqual((stop.find("w:actionGroupStartIndex", NS).text, stop.find("w:actionGroupEndIndex", NS).text), (str(last), str(last)))
        self.assertEqual([a.find("w:actionActuatorFunc", NS).text for a in stop.findall("w:action", NS)],
                         ["stopContinuousShooting", "gimbalAngleUnlock"])
        lock = by_trigger["betweenAdjacentPoints"]
        self.assertEqual([a.find("w:actionActuatorFunc", NS).text for a in lock.findall("w:action", NS)], ["gimbalAngleLock"])

    def test_every_started_run_of_photos_is_stopped_and_group_ids_are_unique(self):
        funcs = [e.text for e in self.w.iter(W + "actionActuatorFunc")]
        self.assertEqual(funcs.count("startContinuousShooting"), funcs.count("stopContinuousShooting"))
        ids = [g.find("w:actionGroupId", NS).text for g in self.w.iter(W + "actionGroup")]
        self.assertEqual(len(ids), len(set(ids)))
        for group in self.w.iter(W + "actionGroup"):
            first, last = (int(group.find("w:actionGroupStartIndex", NS).text), int(group.find("w:actionGroupEndIndex", NS).text))
            self.assertTrue(0 <= first <= last < len(self.plan.nadir.waypoints))
            ids = [a.find("w:actionId", NS).text for a in group.findall("w:action", NS)]
            self.assertEqual(ids, [str(i) for i in range(len(ids))])

    def test_the_survey_starts_with_the_gimbal_down_and_focus_at_infinity(self):
        start = self.w.find("k:Document/k:Folder/w:startActionGroup", NS)
        self.assertEqual([a.find("w:actionActuatorFunc", NS).text for a in start.findall("w:action", NS)],
                         ["gimbalRotate", "hover", "setFocusType", "focus", "hover"])
        self.assertEqual(start.find("w:action/w:actionActuatorFuncParam/w:gimbalPitchRotateAngle", NS).text, "-90")
        self.assertEqual(start.findall("w:action", NS)[3].find("w:actionActuatorFuncParam/w:isInfiniteFocus", NS).text, "1")

    def test_distance_and_duration(self):
        folder = self.w.find("k:Document/k:Folder", NS)
        self.assertAlmostEqual(float(folder.find("w:distance", NS).text), self.plan.nadir.distance, places=6)
        self.assertAlmostEqual(float(folder.find("w:duration", NS).text), self.plan.nadir.distance / 10.2, places=6)
        self.assertEqual(folder.find("w:executeHeightMode", NS).text, "realTimeFollowSurface")

    def test_the_default_speed_is_the_fastest_the_photos_allow_rounded_down(self):
        plan, s = make(speed=None)
        w = ET.fromstring(files(plan, s)[1])
        speed = float(w.find("k:Document/k:Folder/w:autoFlightSpeed", NS).text)
        self.assertLessEqual(speed, plan.nadir.max_speed)
        self.assertGreater(speed, plan.nadir.max_speed - 0.1 - 1e-9)

    def test_heights_relative_to_the_takeoff_point(self):
        plan, s = make(height_mode="relativeToStartPoint", height=14.0209722518921)
        template, waylines = files(plan, s)
        t, w = ET.fromstring(template), ET.fromstring(waylines)
        self.assertEqual(t.find("k:Document/k:Folder/w:waylineCoordinateSysParam/w:heightMode", NS).text, "relativeToStartPoint")
        self.assertIsNone(t.find("k:Document/k:Folder/w:waylineCoordinateSysParam/w:surfaceFollowModeEnable", NS))
        self.assertEqual(w.find("k:Document/k:Folder/w:executeHeightMode", NS).text, "relativeToStartPoint")
        self.assertEqual(w.find("k:Document/k:Folder/k:Placemark/w:executeHeight", NS).text, "14.0209722518921")

    def test_the_takeoff_point_is_left_out_when_unknown(self):
        plan, s = make(takeoff_ref_point=None)
        self.assertNotIn(b"takeOffRefPoint", files(plan, s)[0])

    def test_the_author_is_only_written_when_given(self):
        self.assertNotIn(b"author", self.template)
        plan, s = make(author="someone@example.com")
        self.assertIn(b"<wpml:author>someone@example.com</wpml:author>", files(plan, s)[0])


def make_oblique(**kw):
    args = dict(collection_mode="oblique", height_mode="relativeToStartPoint", gimbal_pitch=-45.0)
    args.update(kw)
    return make(**args)


class TestObliqueMission(SimpleTestCase):
    """The 5-folder mission collection_mode="oblique" builds - see missions.wpml's module docstring and
    OBLIQUE_HEADINGS. Cross-checked structurally against Pilot 2's own oblique exports in TestObliqueAgainstPilot2
    (tests/test_mission_planning.py); this only tests that our own generator does what it claims to."""

    def setUp(self):
        self.plan, self.s = make_oblique()
        self.template, self.waylines = files(self.plan, self.s)
        self.t = ET.fromstring(self.template)
        self.w = ET.fromstring(self.waylines)

    def test_the_template_is_mapping3d_with_the_inclined_fields_in_the_right_order(self):
        folder = self.t.find("k:Document/k:Folder", NS)
        self.assertEqual(folder.find("w:templateType", NS).text, "mapping3d")
        pm = folder.find("k:Placemark", NS)
        tags = [c.tag.split("}")[-1] for c in pm]
        self.assertEqual(tags, ["caliFlightEnable", "inclinedGimbalPitch", "shootType", "direction", "margin",
                                "inclinedFlightSpeed", "efficiencyFlightModeEnable", "overlap", "Polygon",
                                "ellipsoidHeight", "height"])
        self.assertEqual(pm.find("w:inclinedGimbalPitch", NS).text, "-45")

    def test_the_waylines_have_five_folders(self):
        folders = self.w.findall("k:Document/k:Folder", NS)
        self.assertEqual(len(folders), 5)
        self.assertEqual([f.find("w:waylineId", NS).text for f in folders], ["0", "1", "2", "3", "4"])
        self.assertEqual([f.find("w:templateId", NS).text for f in folders], ["0", "1", "2", "3", "4"])

    def test_folder_zero_is_nadir_and_the_rest_are_tilted(self):
        folders = self.w.findall("k:Document/k:Folder", NS)
        pitches = [float(f.find("w:startActionGroup/w:action/w:actionActuatorFuncParam/w:gimbalPitchRotateAngle", NS).text)
                  for f in folders]
        self.assertEqual(pitches, [-90, -45, -45, -45, -45])
        # the wp0 action group (not the startActionGroup) sets the same pitch again, same as a nadir mission does
        for f, pitch in zip(folders, pitches):
            first = f.findall("k:Placemark", NS)[0]
            group = [g for g in first.findall("w:actionGroup", NS)
                    if g.find("w:actionTrigger/w:actionTriggerType", NS).text == "multipleDistance"][0]
            self.assertEqual(float(group.find("w:action/w:actionActuatorFuncParam/w:gimbalPitchRotateAngle", NS).text), pitch)

    def test_the_four_tilted_folders_are_90_degrees_apart_and_lock_the_heading(self):
        folders = self.w.findall("k:Document/k:Folder", NS)
        angles = []
        for f in folders[1:]:
            pms = f.findall("k:Placemark", NS)
            for pm in pms[:-1]:
                h = pm.find("w:waypointHeadingParam", NS)
                self.assertEqual(h.find("w:waypointHeadingMode", NS).text, "fixed")
            angle = float(pms[0].find("w:waypointHeadingParam/w:waypointHeadingAngle", NS).text)
            self.assertTrue(all(float(pm.find("w:waypointHeadingParam/w:waypointHeadingAngle", NS).text) == angle for pm in pms[:-1]))
            angles.append(angle)
            last = pms[-1].find("w:waypointHeadingParam", NS)
            self.assertEqual((last.find("w:waypointHeadingMode", NS).text, last.find("w:waypointHeadingAngle", NS).text),
                             ("followWayline", "0"))
        self.assertEqual(sorted(round((a - angles[0]) % 360) for a in angles), [0, 90, 180, 270])

    def test_the_nadir_folder_is_unaffected_and_still_follows_the_wayline(self):
        nadir = self.w.findall("k:Document/k:Folder", NS)[0]
        pms = nadir.findall("k:Placemark", NS)
        modes = [pm.find("w:waypointHeadingParam/w:waypointHeadingMode", NS).text for pm in pms]
        self.assertEqual(set(modes[:-1]), {"followWayline"})

    def test_the_oblique_folders_use_their_own_footprint_and_can_need_a_different_line_count(self):
        nadir_plan = self.plan.nadir
        oblique_plan = self.plan.oblique[0]
        self.assertGreater(oblique_plan.spacing, nadir_plan.spacing)     # the tilted footprint is bigger

    def test_oblique_overlap_can_differ_from_ortho_overlap(self):
        plan, s = make_oblique(overlap_h=80, overlap_w=70, inclined_overlap_h=50, inclined_overlap_w=40)
        t = ET.fromstring(files(plan, s)[0])
        overlap = t.find("k:Document/k:Folder/k:Placemark/w:overlap", NS)
        self.assertEqual(overlap.find("w:orthoCameraOverlapH", NS).text, "80")
        self.assertEqual(overlap.find("w:orthoCameraOverlapW", NS).text, "70")
        self.assertEqual(overlap.find("w:inclinedCameraOverlapH", NS).text, "50")
        self.assertEqual(overlap.find("w:inclinedCameraOverlapW", NS).text, "40")

    def test_the_oblique_speed_can_differ_from_the_global_speed(self):
        plan, s = make_oblique(speed=10.2, inclined_speed=5.1)
        t = ET.fromstring(files(plan, s)[0])
        folder = t.find("k:Document/k:Folder", NS)
        self.assertEqual(folder.find("w:autoFlightSpeed", NS).text, "10.2")
        self.assertEqual(folder.find("k:Placemark/w:inclinedFlightSpeed", NS).text, "5.1")
        w = ET.fromstring(files(plan, s)[1])
        folders = w.findall("k:Document/k:Folder", NS)
        self.assertEqual(folders[0].find("w:autoFlightSpeed", NS).text, "10.2")
        self.assertTrue(all(f.find("w:autoFlightSpeed", NS).text == "5.1" for f in folders[1:]))

    def test_the_oblique_speed_defaults_to_the_fastest_the_oblique_photos_allow(self):
        # independent of the nadir speed - the two passes have different footprints/intervals
        plan, s = make_oblique(speed=10.2, inclined_speed=None)
        expected = min(wpml.MAX_SPEED, math.floor(plan.oblique[0].max_speed * 10) / 10.0)
        self.assertEqual(wpml.inclined_speed_of(plan, s), expected)
        self.assertNotEqual(expected, 10.2)  # the nadir speed we explicitly set - confirms it isn't just mirrored

    def test_ortho_missions_are_unaffected(self):
        plan, s = make()
        self.assertIsNone(plan.oblique)
        self.assertEqual(s.collection_mode, "ortho")
        t = ET.fromstring(files(plan, s)[0])
        self.assertEqual(t.find("k:Document/k:Folder", NS).find("w:templateType", NS).text, "mapping2d")
        self.assertEqual(len(ET.fromstring(files(plan, s)[1]).findall("k:Document/k:Folder", NS)), 1)


class TestAreaRouteOptions(SimpleTestCase):
    def documents(self, **kw):
        plan, s = make(**kw)
        template, waylines = files(plan, s)
        return ET.fromstring(template), ET.fromstring(waylines)

    def text(self, root, path):
        return root.find(path, NS).text

    def test_the_defaults_are_what_pilot_2_writes(self):
        t, w = self.documents()
        for root in (t, w):
            self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:flyToWaylineMode"), "safely")
            self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:waylineAvoidLimitAreaMode"), "0")
        self.assertEqual(self.text(t, "k:Document/k:Folder/k:Placemark/w:elevationOptimizeEnable"), "1")

    def test_safe_takeoff_or_direct_ascent(self):
        for mode, value in (("safe", "safely"), ("direct", "pointToPoint")):
            t, w = self.documents(takeoff_mode=mode)
            for root in (t, w):
                self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:flyToWaylineMode"), value, mode)
            # the security height is written either way
            self.assertEqual(self.text(t, "k:Document/w:missionConfig/w:takeOffSecurityHeight"), "100")

    def test_elevation_optimization(self):
        for on, value in ((True, "1"), (False, "0")):
            t, _ = self.documents(elevation_optimize=on)
            self.assertEqual(self.text(t, "k:Document/k:Folder/k:Placemark/w:elevationOptimizeEnable"), value)

    def test_geo_zone_bypassing(self):
        for on, value in ((True, "1"), (False, "0")):
            t, w = self.documents(avoid_limit_area=on)
            for root in (t, w):
                self.assertEqual(self.text(root, "k:Document/w:missionConfig/w:waylineAvoidLimitAreaMode"), value)

    def test_photos_every_so_many_meters_is_the_only_photo_mode_that_can_be_exported(self):
        t, _ = self.documents(photo_mode="distance")
        self.assertEqual(self.text(t, "k:Document/k:Folder/k:Placemark/w:shootType"), "distance")
        for bad, message in (("time", "seconds cannot be exported yet"), ("burst", "Unknown photo mode"), (None, "Unknown photo mode")):
            with self.assertRaises(ExportError) as ctx:
                make(photo_mode=bad)
            self.assertIn(message, str(ctx.exception))

    def test_refuses_unknown_takeoff_modes_and_switches_that_are_not_on_or_off(self):
        for kw, message in ((dict(takeoff_mode="teleport"), "takeoff mode"), (dict(elevation_optimize=1), "elevation optimization"),
                            (dict(avoid_limit_area="yes"), "geo zone"), (dict(avoid_limit_area=None), "geo zone")):
            with self.assertRaises(ExportError) as ctx:
                make(**kw)
            self.assertIn(message, str(ctx.exception))


class TestWarnings(SimpleTestCase):
    def test_no_warnings_for_an_ordinary_mission(self):
        plan, s = make(speed=None, rth_height=150)
        self.assertEqual(wpml.mission_warnings(plan, s), [])

    def test_warns_about_a_speed_that_skips_photos(self):
        plan, s = make(speed=15)
        self.assertTrue(any("missed" in w for w in wpml.mission_warnings(plan, s)))

    def test_warns_when_the_aircraft_will_not_follow_the_terrain(self):
        plan, s = make(height_mode="relativeToStartPoint", speed=None)
        self.assertTrue(any("terrain" in w for w in wpml.mission_warnings(plan, s)))

    def test_warns_about_a_low_return_height(self):
        plan, s = make(rth_height=100, height=100.5, speed=None)
        self.assertTrue(any("return height" in w for w in wpml.mission_warnings(plan, s)))


class TestKmz(SimpleTestCase):
    def test_the_kmz_holds_the_two_files_pilot_2_writes(self):
        plan, s = make()
        z = zipfile.ZipFile(io.BytesIO(build_kmz(plan, s, now=NOW)))
        self.assertEqual(sorted(z.namelist()), ["wpmz/template.kml", "wpmz/waylines.wpml"])
        self.assertIsNone(z.testzip())

    def test_the_same_mission_gives_the_same_bytes(self):
        plan, s = make()
        self.assertEqual(build_kmz(plan, s, now=NOW), build_kmz(plan, s, now=NOW))
        self.assertNotEqual(build_kmz(plan, s, now=NOW), build_kmz(plan, s, now=NOW + 1))     # the creation time is in it

    def test_the_creation_time_is_in_milliseconds(self):
        plan, s = make()
        t = ET.fromstring(files(plan, s)[0])
        self.assertEqual(t.find("k:Document/w:createTime", NS).text, "1790011727518")

    def test_reading_it_back_gives_the_settings_and_the_plan(self):
        plan, s = make()
        back = parse_kmz(build_kmz(plan, s, now=NOW))
        self.assertEqual(back["direction"], 181)
        self.assertEqual(back["height"], 100.5)
        self.assertEqual((back["overlap_h"], back["overlap_w"]), (80, 70))
        self.assertEqual([c.key for c in back["cameras"]], ["visable", "ir"])
        self.assertAlmostEqual(back["interval"], plan.nadir.interval, places=6)
        self.assertEqual(len(back["polygon"]), len(PILOT2_AREA))
        self.assertEqual(len(back["waypoints"]), len(plan.nadir.waypoints))

    def test_an_empty_plan_is_refused(self):
        plan, s = make()
        with self.assertRaises(ExportError):
            build_kmz(plan._replace(nadir=plan.nadir._replace(waypoints=[])), s)

    def test_output_is_xml_with_declared_namespaces(self):
        plan, s = make()
        template, waylines = files(plan, s)
        for doc in (template, waylines):
            self.assertTrue(doc.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:wpml="http://www.dji.com/wpmz/1.0.6">'))
            ET.fromstring(doc)

    def test_golden_files(self):
        plan, s = make()
        template, waylines = files(plan, s)
        golden(self, "area_template.kml", template)
        golden(self, "area_waylines.wpml", waylines)

    def test_golden_files_relative_to_the_takeoff_point(self):
        plan, s = make(polygon=rectangle(60, 40), direction=188, height=14.0, overlap_h=85, overlap_w=85, margin=1,
                       height_mode="relativeToStartPoint", speed=0.8, cameras=[M4T_WIDE, M4T_THERMAL], takeoff_ref_point=None,
                       takeoff_security_height=14, rth_height=30)
        template, waylines = files(plan, s)
        golden(self, "relative_template.kml", template)
        golden(self, "relative_waylines.wpml", waylines)


@unittest.skipUnless(os.path.isfile(os.path.join(KMZ_DIR, "TestAreaRoute.kmz")), "DJI Pilot 2 sample missions are not available")
class TestAgainstPilot2Files(SimpleTestCase):
    """The structure of the files must be that of the files Pilot 2 wrote: same elements, same order"""

    @classmethod
    def sample(cls, name):
        with zipfile.ZipFile(os.path.join(KMZ_DIR, "TestAreaRoute.kmz")) as z:
            return ET.fromstring(z.read(name))

    def ours(self):
        plan, s = make(author="someone@example.com")
        template, waylines = files(plan, s)
        return plan, ET.fromstring(template), ET.fromstring(waylines)

    def test_the_template_has_exactly_the_elements_of_pilot_2s(self):
        _, template, _ = self.ours()
        self.assertEqual(skeleton(template), skeleton(self.sample("wpmz/template.kml")))

    def test_the_header_of_the_waylines_has_exactly_the_elements_of_pilot_2s(self):
        _, _, waylines = self.ours()
        theirs = self.sample("wpmz/waylines.wpml")

        def header(root):
            folder = root.find("k:Document/k:Folder", NS)
            for pm in folder.findall("k:Placemark", NS):
                folder.remove(pm)
            return skeleton(root)

        self.assertEqual(header(waylines), header(theirs))

    def test_our_waypoints_have_the_elements_of_theirs(self):
        _, _, waylines = self.ours()
        ours = waylines.findall("k:Document/k:Folder/k:Placemark", NS)
        theirs = self.sample("wpmz/waylines.wpml").findall("k:Document/k:Folder/k:Placemark", NS)
        # the first waypoint (start of the photos), a waypoint in between, and the last one (end of the photos)
        self.assertEqual(skeleton(ours[0]), skeleton(theirs[0]))
        self.assertEqual(skeleton(ours[1]), skeleton(theirs[1]))
        self.assertEqual(skeleton(ours[-1]), skeleton(theirs[-1]))

    def test_the_fixed_values_are_pilot_2s(self):
        _, template, waylines = self.ours()
        theirs_t, theirs_w = self.sample("wpmz/template.kml"), self.sample("wpmz/waylines.wpml")

        def values(root, skip=("createTime", "updateTime", "takeOffRefPoint", "direction", "margin", "globalShootHeight", "surfaceRelativeHeight",
                               "ellipsoidHeight", "height", "autoFlightSpeed", "coordinates", "author", "overlap", "distance", "duration",
                               "waypointSpeed", "executeHeight", "waypointHeadingAngle", "waypointTurnDampingDist", "actionGroupEndIndex",
                               "actionTriggerParam", "actionGroupStartIndex", "orthoCameraOverlapH", "orthoCameraOverlapW", "inclinedCameraOverlapH",
                               "inclinedCameraOverlapW", "index", "actionGroupId", "waypointTurnMode")):
            out = {}
            for e in root.iter():
                name = e.tag.split("}")[1]
                if name in skip or len(e) or e.text is None or not e.text.strip():
                    continue
                out.setdefault(name, set()).add(e.text.strip())
            return out

        for ours, theirs in ((values(template), values(theirs_t)), (values(waylines), values(theirs_w))):
            for name, v in ours.items():
                self.assertTrue(v & theirs.get(name, set()) or name in ("waypointTurnMode",), (name, v, theirs.get(name)))


@unittest.skipUnless(os.path.isfile(os.path.join(KMZ_DIR, "testkmz-oblique-asl.kmz")), "DJI Pilot 2 oblique ASL sample missions are not available")
class TestASLAgainstPilot2(SimpleTestCase):
    """ASL (EGM96) height math, checked against the real numbers in testkmz-oblique-asl.kmz. The ground-elevation
    inputs fed into make_oblique() here are back-derived from that file's own height/ellipsoidHeight fields (this
    app sources those independently from OpenTopography in production - see missions/elevation.py - a
    different provider than whatever Pilot 2 used internally, so they would not match exactly on their own). What
    this actually verifies is that our formula (ground elevation + the target height above ground) and the WPML
    field structure (heightMode/executeHeightMode/executeHeight) exactly reproduce Pilot 2's real output once
    given equivalent ground-elevation inputs."""

    def sample(self):
        with zipfile.ZipFile(os.path.join(KMZ_DIR, "testkmz-oblique-asl.kmz")) as z:
            return ET.fromstring(z.read("wpmz/template.kml")), ET.fromstring(z.read("wpmz/waylines.wpml"))

    def real_values(self):
        t, w = self.sample()
        pm = t.find("k:Document/k:Folder/k:Placemark", NS)
        shoot_height = float(t.find("k:Document/k:Folder/w:waylineCoordinateSysParam/w:globalShootHeight", NS).text)
        return {
            "shoot_height": shoot_height, "height": float(pm.find("w:height", NS).text),
            "ellipsoid_height": float(pm.find("w:ellipsoidHeight", NS).text),
            "height_mode": t.find("k:Document/k:Folder/w:waylineCoordinateSysParam/w:heightMode", NS).text,
            "execute_height_mode": w.find("k:Document/k:Folder/w:executeHeightMode", NS).text,
        }

    def build(self, real):
        return make_oblique(height=real["shoot_height"], height_mode="EGM96",
                            takeoff_ref_point=(42.1, -88.1, real["height"] - real["shoot_height"]),
                            takeoff_ellipsoidal_height=real["ellipsoid_height"] - real["shoot_height"])

    def test_the_real_file_uses_egm96_and_wgs84(self):
        real = self.real_values()
        self.assertEqual(real["height_mode"], "EGM96")
        self.assertEqual(real["execute_height_mode"], "WGS84")

    def test_height_and_ellipsoid_height_match_the_real_file(self):
        real = self.real_values()
        plan, s = self.build(real)
        t = ET.fromstring(files(plan, s)[0])
        pm = t.find("k:Document/k:Folder/k:Placemark", NS)
        self.assertAlmostEqual(float(pm.find("w:height", NS).text), real["height"], places=6)
        self.assertAlmostEqual(float(pm.find("w:ellipsoidHeight", NS).text), real["ellipsoid_height"], places=6)

    def test_execute_height_mode_is_wgs84_and_every_waypoint_uses_the_ellipsoid_height(self):
        real = self.real_values()
        plan, s = self.build(real)
        w = ET.fromstring(files(plan, s)[1])
        folders = w.findall("k:Document/k:Folder", NS)
        for f in folders:
            self.assertEqual(f.find("w:executeHeightMode", NS).text, "WGS84")
            for pm in f.findall("k:Placemark", NS):
                self.assertAlmostEqual(float(pm.find("w:executeHeight", NS).text), real["ellipsoid_height"], places=6)


AGL_SAMPLE = "m4t-testkmz-oblique-AGL.kmz"


@unittest.skipUnless(os.path.isfile(os.path.join(KMZ_DIR, AGL_SAMPLE)), "DJI Pilot 2 oblique AGL sample mission is not available")
class TestObliqueAGLAgainstPilot2(SimpleTestCase):
    """Oblique AGL flies heights over a DSM embedded in the mission. Built here from the area, height and DSM of
    Pilot 2's own export (m4t-testkmz-oblique-AGL.kmz), and checked against its structure and its heights."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with zipfile.ZipFile(os.path.join(KMZ_DIR, AGL_SAMPLE)) as z:
            cls.theirs = ET.fromstring(z.read("wpmz/template.kml")), ET.fromstring(z.read("wpmz/waylines.wpml"))
            cls.dsm_name = [n for n in z.namelist() if n.startswith("wpmz/res/dsm/")][0].split("/")[-1]
            cls.dsm = z.read("wpmz/res/dsm/" + cls.dsm_name)
        r = read_kmz(AGL_SAMPLE)
        cls.plan, cls.s = make_oblique(polygon=r["polygon"], direction=1, height=49.9993904000195, overlap_h=80, overlap_w=70,
                                       height_mode="realTimeFollowSurface", inclined_speed=3.1, author="someone@example.com",
                                       takeoff_ref_point=(41.489810, -79.528136, 0), takeoff_security_height=20, rth_height=100)
        cls.kmz = build_kmz(cls.plan, cls.s, now=NOW, dsm=(cls.dsm, cls.dsm_name))
        z = zipfile.ZipFile(io.BytesIO(cls.kmz))
        cls.ours = ET.fromstring(z.read("wpmz/template.kml")), ET.fromstring(z.read("wpmz/waylines.wpml"))

    def test_the_template_has_exactly_the_elements_of_pilot_2s(self):
        self.assertEqual(skeleton(self.ours[0]), skeleton(self.theirs[0]))

    def test_the_header_of_every_wayline_has_the_elements_of_pilot_2s(self):
        def header(root):
            folder = root.find("k:Document/k:Folder", NS)
            return [e.tag for e in folder if e.tag != "{%s}Placemark" % NS["k"]]

        self.assertEqual(header(self.ours[1]), header(self.theirs[1]))
        self.assertEqual(skeleton(self.ours[1].find("k:Document/w:missionConfig", NS)),
                         skeleton(self.theirs[1].find("k:Document/w:missionConfig", NS)))

    def test_the_template_says_egm96_with_the_dsm_and_no_real_time_follow(self):
        system = self.ours[0].find("k:Document/k:Folder/w:waylineCoordinateSysParam", NS)
        self.assertEqual({e.tag.split("}")[1]: e.text for e in system},
                         {"coordinateMode": "WGS84", "heightMode": "EGM96", "globalShootHeight": "49.9993904000195",
                          "surfaceFollowModeEnable": "1", "isRealtimeSurfaceFollow": "0",
                          "surfaceRelativeHeight": "49.9993904000195", "dsmFile": "wpmz/res/dsm/" + self.dsm_name})

    def test_the_dsm_is_in_the_mission_where_the_template_says(self):
        z = zipfile.ZipFile(io.BytesIO(self.kmz))
        self.assertEqual(sorted(z.namelist()), ["wpmz/res/dsm/" + self.dsm_name, "wpmz/template.kml", "wpmz/waylines.wpml"])
        self.assertEqual(z.read("wpmz/res/dsm/" + self.dsm_name), self.dsm)
        self.assertIsNone(z.testzip())

    def test_the_takeoff_point_and_the_start_are_heights_over_the_dsm_close_to_pilot_2s(self):
        def ref(root, name):
            return [float(v) for v in root.find("k:Document/w:missionConfig/w:" + name, NS).text.split(",")]

        self.assertAlmostEqual(ref(self.ours[0], "takeOffRefPoint")[2], ref(self.theirs[0], "takeOffRefPoint")[2], delta=1)
        self.assertAlmostEqual(ref(self.ours[0], "startPositionRef")[2], ref(self.theirs[0], "startPositionRef")[2], delta=3)
        self.assertIsNone(self.ours[1].find("k:Document/w:missionConfig/w:startPositionRef", NS))

    def test_every_waypoint_flies_the_height_above_the_highest_ground_near_it_close_to_pilot_2s(self):
        def heights(root):
            return [float(e.text) for e in root.iterfind("k:Document/k:Folder/k:Placemark/w:executeHeight", NS)]

        def nadir(root):
            return [(tuple(float(v) for v in pm.find("k:Point/k:coordinates", NS).text.split(",")), float(pm.find("w:executeHeight", NS).text))
                    for pm in root.findall("k:Document/k:Folder/k:Placemark", NS)]

        for f in self.ours[1].findall("k:Document/k:Folder", NS):
            self.assertEqual((f.find("w:executeHeightMode", NS).text, f.find("w:executeCoordinateMode", NS).text), ("WGS84", "WGS84"))
        self.assertGreater(len(set(heights(self.ours[1]))), 1)           # they follow the ground
        # Against Pilot 2's nearest nadir waypoint: never more than 1 m lower, and the highest ground within RADIUS
        # keeps it at most a few meters higher (from 0.9 m lower to 6.8 m higher in this sample)
        theirs = nadir(self.theirs[1])
        for point, height in nadir(self.ours[1]):
            _, near = min(theirs, key=lambda t: distance(point, t[0]))
            self.assertTrue(-1 <= height - near <= 8, (point, height, near))

    def test_it_is_refused_without_the_terrain(self):
        with self.assertRaisesRegex(ExportError, "needs the terrain"):
            build_kmz(self.plan, self.s, now=NOW)

    def test_it_is_refused_when_the_terrain_does_not_cover_the_route(self):
        far = [(lon + 1, lat) for lon, lat in self.s.polygon]
        plan, s = make_oblique(polygon=far, height=50, height_mode="realTimeFollowSurface", takeoff_ref_point=None)
        with self.assertRaisesRegex(ExportError, "does not cover"):
            build_kmz(plan, s, now=NOW, dsm=(self.dsm, self.dsm_name))

    def test_the_warnings_say_the_heights_come_from_public_elevation_data(self):
        self.assertTrue(any("public elevation data" in w for w in wpml.mission_warnings(self.plan, self.s)))


ORTHO_AGL_SAMPLE = "TestAreaKMZ-30.kmz"


@unittest.skipUnless(os.path.isfile(os.path.join(KMZ_DIR, ORTHO_AGL_SAMPLE)), "DJI Pilot 2 ortho DSM sample mission is not available")
class TestOrthoDSMFollowAgainstPilot2(SimpleTestCase):
    """Ortho AGL with the DSM follow flies heights over a DSM embedded in the mission, as Pilot 2's
    TestAreaKMZ-*.kmz do. Built here from the area, height and DSM of TestAreaKMZ-30.kmz."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with zipfile.ZipFile(os.path.join(KMZ_DIR, ORTHO_AGL_SAMPLE)) as z:
            cls.theirs = ET.fromstring(z.read("wpmz/template.kml")), ET.fromstring(z.read("wpmz/waylines.wpml"))
            cls.dsm_name = [n for n in z.namelist() if n.startswith("wpmz/res/dsm/")][0].split("/")[-1]
            cls.dsm = z.read("wpmz/res/dsm/" + cls.dsm_name)
        r = read_kmz(ORTHO_AGL_SAMPLE)
        cls.plan, cls.s = make(polygon=r["polygon"], direction=r["direction"], height=r["height"], overlap_h=80, overlap_w=70,
                               height_mode="realTimeFollowSurface", surface_follow="dsm",
                               takeoff_ref_point=(42.103460, -85.020568, 0), takeoff_security_height=20)
        cls.kmz = build_kmz(cls.plan, cls.s, now=NOW, dsm=(cls.dsm, cls.dsm_name))
        z = zipfile.ZipFile(io.BytesIO(cls.kmz))
        cls.ours = ET.fromstring(z.read("wpmz/template.kml")), ET.fromstring(z.read("wpmz/waylines.wpml"))

    def test_the_real_time_follow_is_still_the_default(self):
        _, s = make(height_mode="realTimeFollowSurface")
        self.assertFalse(wpml.uses_dsm(s))
        self.assertTrue(wpml.uses_dsm(self.s))
        self.assertFalse(wpml.uses_dsm(make(height_mode="relativeToStartPoint", surface_follow="dsm")[1]))

    def test_an_unknown_surface_follow_is_refused(self):
        with self.assertRaisesRegex(ExportError, "surface follow"):
            make(height_mode="realTimeFollowSurface", surface_follow="lidar")

    # The rest of the sample differs from our ortho export the way the other samples do (written by another Pilot 2
    # version): only what the DSM follow changes is compared here
    def test_the_header_of_every_wayline_has_the_elements_of_pilot_2s(self):
        def header(root):
            folder = root.find("k:Document/k:Folder", NS)
            return [e.tag for e in folder if e.tag != "{%s}Placemark" % NS["k"]][:3]

        self.assertEqual(header(self.ours[1]), header(self.theirs[1]))
        self.assertIsNone(self.ours[1].find("k:Document/k:Folder/w:executeCoordinateMode", NS))
        self.assertIsNone(self.ours[1].find("k:Document/w:missionConfig/w:startPositionRef", NS))

    def test_the_template_says_egm96_with_the_dsm_and_no_real_time_follow(self):
        system = self.ours[0].find("k:Document/k:Folder/w:waylineCoordinateSysParam", NS)
        self.assertEqual({e.tag.split("}")[1]: e.text for e in system},
                         {"coordinateMode": "WGS84", "heightMode": "EGM96", "globalShootHeight": "50",
                          "surfaceFollowModeEnable": "1", "isRealtimeSurfaceFollow": "0",
                          "surfaceRelativeHeight": "50", "dsmFile": "wpmz/res/dsm/" + self.dsm_name})
        self.assertIsNone(self.ours[0].find("k:Document/w:missionConfig/w:startPositionRef", NS))

    def test_the_takeoff_point_and_the_waypoints_are_heights_over_the_dsm_close_to_pilot_2s(self):
        def takeoff(root):
            return float(root.find("k:Document/w:missionConfig/w:takeOffRefPoint", NS).text.split(",")[2])

        # Pilot 2's (208.58 m) is not a value of its DSM, whose cells there are 212 m
        self.assertAlmostEqual(takeoff(self.ours[0]), takeoff(self.theirs[0]), delta=4)
        theirs = [float(e.text) for e in self.theirs[1].iterfind("k:Document/k:Folder/k:Placemark/w:executeHeight", NS)]
        for pm in self.ours[1].iterfind("k:Document/k:Folder/k:Placemark", NS):
            self.assertAlmostEqual(float(pm.find("w:executeHeight", NS).text), max(theirs), delta=3)

    def test_the_dsm_is_in_the_mission(self):
        z = zipfile.ZipFile(io.BytesIO(self.kmz))
        self.assertEqual(z.read("wpmz/res/dsm/" + self.dsm_name), self.dsm)

    def test_it_is_refused_without_the_terrain(self):
        with self.assertRaisesRegex(ExportError, "needs the terrain"):
            build_kmz(self.plan, self.s, now=NOW)


class TestAutoSpeed(SimpleTestCase):
    def test_the_speed_is_the_allowed_one_in_steps_of_a_tenth(self):
        self.assertEqual(wpml.auto_speed(4.37), 4.3)
        self.assertEqual(wpml.auto_speed(40), wpml.MAX_SPEED)

    def test_below_a_tenth_the_allowed_speed_itself_never_zero(self):
        self.assertEqual(wpml.auto_speed(0.082), 0.082)
