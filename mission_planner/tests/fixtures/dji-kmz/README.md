# DJI Pilot 2 sample missions (Matrice 4T and 4E)

Real `.kmz` exports from DJI Pilot 2 (and two from FlightHub 2, marked below), checked in so the tests that compare LuxODM's planner/exporter against
Pilot 2's own output always run. Without them those test classes skip silently (they look here by default;
`DJI_KMZ_DIR` overrides the location).

They were moved off the places they were flown before the repo was published: each place due east (latitudes and
heights unchanged, so Pilot 2's distances and heights still hold), the author set to `pilot@example.com`, the two
Smart3D samples' 3D scans removed, and the embedded terrain rasters cut to about 1.7 km round the route. A new sample
gets the same treatment before it is committed.

The tests read specific facts out of specific files, so a regenerated file must be made with the settings below.

| File | Used by | Settings a replacement must have |
|---|---|---|
| `TestAreaRoute.kmz` | `test_mission_planning.TestAgainstPilot2`, `test_mission_wpml.TestAgainstPilot2Files` | Area route, ortho, AGL (real-time terrain follow), wide + thermal, 80/70 overlap, margin 0, direction 181, height 100.5 m, speed 10.2 m/s, takeoff security height 100 m, RTH 100 m, over the area in `PILOT2_AREA` (`test_mission_wpml.py`); the tests also expect 3 lines of about 70.1 m |
| `HomerunThermalOnly.kmz` | `test_mission_planning.TestAgainstPilot2` | Any area route; only the photo interval and line spacing are compared |
| `TestAreaKMZ-{15,20,30,35,45,60,75,100}.kmz` | `test_mission_planning.TestLineCountAgainstPilot2` | 8 files: a 100 m (N-S) x `<width>` m (E-W) rectangle, height 50 m, direction 0, wide + thermal, 80/70 overlap, margin 0 |
| `testkmz-oblique-alt.kmz` | `test_mission_planning.TestObliqueAgainstPilot2` | Oblique, ALT height mode, gimbal pitch -45; the KMZ import refuses it (it flies 49.6 m for a height of 50 m, measured from Pilot 2's ground height for the area) |
| `testkmz-oblique-asl.kmz` | `test_mission_planning.TestObliqueAgainstPilot2`, `test_mission_wpml.TestASLAgainstPilot2` | Oblique, ASL height mode (any area) |
| `testkmz-oblique-speed-on.kmz`, `testkmz-oblique-speed-off.kmz` | `test_mission_planning.TestObliqueAgainstPilot2` | Oblique, with and without a separately set oblique speed |
| `m4t-testkmz-oblique-AGL.kmz` | (upcoming: oblique AGL with an embedded DSM) | Oblique, AGL height mode, as exported by Pilot 2 with its `wpmz/res/dsm/*.tif` |
| `m4e-test-area-alt{100,50,15}m-gsd*.kmz`, `m4t-test-area-alt15m-gsd0.62cm-ogsd0.88cm.kmz` | `test_mission_planning.TestCamerasAgainstPilot2` | Area routes over the same polygon, ALT height mode at the height in the name, wide camera only, Smart Oblique on, direction 270, margin 0, 80/80 overlap (M4E) or 80/70 (M4T); the GSD in the name is the one Pilot 2 shows |
| `m4e-test-area.kmz` | `test_mission_kmz_import` (refused: Smart Oblique) | M4E area route over the same polygon at 72.08 m, as above |
| `m4e-test-waypoint.kmz` | `test_mission_waypoints.TestWaypointPilot2Samples` | M4E waypoint route in ASL (EGM96), passing its points in curves, with heading, gimbal pitch and zoom actions; the tests compare its length, time and `executeHeight`s |
| `m4t-test-waypoint.kmz` | `test_mission_kmz_import` (refused: `startRecord`) | M4T waypoint route in ALT at 15 m, visible + thermal, with a video recording action |
| `m4t-test-poi-waypoint.kmz` | (upcoming: POI routes, phase 1) | Made in Pilot 2: M4T waypoint route, 8 points in a loop around a POI, every point Toward POI, curved pass-through turns, ALT, visible + IR, video and 2 s timed photos from the first point to the last |
| `m4t-test-poi.kmz`, `m4t-test-poi-toward-poi.kmz` | (upcoming: POI routes) | Made in FlightHub 2: the same 9-point M4T loop in AGL, curved pass-through turns, video and 10 m distance photos (visible + IR) from the first point to the last; one with Lock Yaw Axis and gimbal -45, one with a POI on the map and the gimbal set per point |
| `TestWaypointRoute.kmz` | `test_mission_kmz_import` (refused: `panoShot`, `orientedShoot`) | Waypoint route with a panorama and an oriented photo action |
| `m4t-test-linear-single.kmz`, `m4t-test-linear-zigzag.kmz` | `test_mission_linear` | Linear (`mappingStrip`) routes, one single line and one zigzag, ALT, visible + thermal, 80/80 |
| `m4t-test-slope.kmz` | `test_mission_slope` | Slope route (`mapping2d` with `facadeWaylineEnable` 1, ASL), visible + thermal, 80/80, 28.11 m from a 4-corner face (209 m to 79 m), speed 3.5 m/s; the tests compare its 92 points, heights, heading, pitch and photo interval |
| `m4t-test-geo.kmz` | `test_mission_geometric` | Geometric (`mappingPrism`) route, ASL, visible + thermal, 80/80, 6.2 m from a 6-corner block (one corner turned in) 4.5 m high on ground 214.47 m, walls at 0.7 m/s, top face on (a Smart Oblique lawnmower, points 0 to 252); the tests compare its 196 wall points (253 on), heights, headings, turns and photo interval, its 32 roof lines (their run-ons, poses, speeds and turns; 31 lines point for point, within 0.5 m), its distance and duration, and import it with the top face on and off |
| `m4t-test-patrol.kmz`, `m4e-test-patrol.kmz` | (not planned yet) | Patrol (`targetdetection`) routes with their `wpmz/res/area/` files; the M4T one is thermal only |
