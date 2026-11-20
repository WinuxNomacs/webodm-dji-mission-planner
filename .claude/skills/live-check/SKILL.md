---
name: live-check
description: Check a UI change in a real headless browser against the plugin's dev servers (WebODM 4.0.0 on http://localhost:8009), then remove whatever the check created. Use after building or fixing anything visible.
---

# Live browser check

## Login

The change is checked on WebODM 4.0.0 (http://localhost:8009).

Log in at `/login/` with the dev account the user has given for this machine (kept in the project memory, never in
the repo). Without one, ask the user. Never look for credentials or cookies in files, transcripts, the database or
the environment.

## Driving the browser

Prefer the Playwright MCP tools (`mcp__playwright__*`) when they are loaded. Otherwise, write a Node script in the
scratchpad that loads Playwright from this repo (`require('<repo>/node_modules/playwright')`), launches Chromium
with `headless: true`, logs in, and saves screenshots to the scratchpad. Read the screenshots back to look at them,
and read the page's console messages. A KMZ is uploaded with `setInputFiles` on the import's file input.

## What to check

- The change itself, on real data where it applies (the DJI Mission Planner menu entry, the routes list, each route
  type's editor, the KMZ download and import).
- Downloads are saved and opened: a KMZ is a zip with `wpmz/template.kml` and `wpmz/waylines.wpml`.
- Samples to import: the Pilot 2 missions in `mission_planner/tests/fixtures/dji-kmz` (`setInputFiles('#mp-import-file',
  path)`; `m4t-test-waypoint.kmz` is refused by design, `m4e-test-waypoint.kmz` imports). `m4t-testkmz-oblique-AGL.kmz`
  carries a DSM, which becomes the route's terrain without OpenTopography.
- The settings page (the OpenTopography key): `settings_check.js` (beside this file; how to run it in its first
  lines). `nokey` needs the stack started with `MP_NO_KEY=1 dev/webodm.sh up` and a throwaway non-admin user; it
  tries a made-up key, saves the real one from `.env` (never printed), fetches a takeoff height and terrain with
  it, removes it, and checks the non-admin user sees no button and gets 403. `env` (the stack back with the key)
  checks the page says the environment sets it. About 6 OpenTopography calls a stack.
- The LuxODM import without LuxODM (it is retired, and may not be running): `release_check.js <port> check` in the
  `release-check` skill builds a small export by hand (one route with a sample's DSM as terrain) and imports it on
  the settings page; it works on the mounted plugin too. Against real LuxODM data:
- The LuxODM import: `luxodm_import_check.js` and `kmz_compare.py` (beside this file; how to run them in their
  first lines). Needs LuxODM running (the user's stack, :8000: never stop or restart it) with its mission planner
  enabled for the check (`enable_plugin('mission-planner')` in its `manage.py shell`, `disable_plugin` after: it
  ships disabled). Make routes in LuxODM from its fixture KMZs (LuxODM refuses `m4e-test-area*` and
  `m4t-test-poi*.kmz` but `m4t-test-poi-waypoint.kmz`; `lux-copy 1 m4e` gives an M4E area), download them from
  LuxODM's editors, `docker exec -w /webodm webapp python manage.py export_routes /webodm/ignored/route-export/<file>`
  (then `chown 1000:1000` it), import it with `mp 8009`, compare the KMZs. Expect the same entries
  and terrain, and differences only in the create and update times and floating-point noise (about 1e-13,
  2026-11-17). Delete the LuxODM routes, disable its plugin, remove the export, and remove
  `app/media/routes` in `webapp` if the check created it.
- Heights from a task's DSM: `dsm_task.py` (beside this file) makes a throwaway project "MP live check" with a task
  whose synthetic DSM covers the geometric and slope samples (ground 214.5 m, block top 219 m); `MP_ACTION=delete`
  removes it (WebODM's worker then drops the project marked for deletion).
- The 3D view's lidar surface: `lidar_check.js` (beside this file; how to run it in its first lines): imports the
  oblique AGL sample, builds its surface (about 30 s, about 200 MB of lidar), screenshots it on and off, checks "No
  lidar here" in Paris, reads and clears the settings page's size, deletes its routes. Afterwards remove the lidar
  index it downloaded: `docker exec mp-webapp rm -rf /webodm/app/media/plugins/mission_planner_data/lidar`. After changing `lidar.py`, `docker restart mp-worker` (the worker keeps the module it loaded).
- The height under the pointer: `pointer_check.js` (beside this file): hovers the oblique AGL sample in 2D (terrain),
  imperial, 3D once the lidar is built and 2D again (lidar), and a new waypoint route; deletes its routes and
  clears the lidar surface (remove the index by hand as above).
- The takeoff point's heights: `takeoff_check.js` (beside this file): imports Pilot 2's TestAreaRoute.kmz, reads the
  editor's sea-level takeoff height (243.98 m) and checks the downloaded KMZ's `takeOffRefPoint` against Pilot 2's
  (209.78 m ellipsoidal, within the form's centimetre). Afterwards remove the grid it downloaded:
  `docker exec mp-webapp rm -rf /webodm/app/media/plugins/mission_planner_data/grids`.
- Drawing and editing in 3D: `edit3d_check.js` (beside this file; how to run it in its first lines): draws and drags
  an area in 3D, adds and drags waypoints (ALT and AGL, 100 m) in the air and measures how far the marker lands from
  where it was dropped (0 px; 20 to 40 px without the air drag); deletes its routes.
- Collisions in 3D: `collide3d_check.js` (beside this file; how to run it in its first lines): imports the oblique
  AGL sample and makes two ALT waypoint routes there, one with a point 10 m up (expected: "goes into the surface in 1
  place", red; red and yellow on the line in its screenshot), one 150 m up (expected: "stays above"); since Phase 11
  the line shows in 2D too. `lidar` as a third argument turns the lidar surface on, and clears it at the end only if it was empty
  before. Deletes its routes.
- Collisions and the route's height in 2D: `collide2d_check.js` (beside this file; how to run it in its first
  lines): the lidar surface on, built from the 2D editor where it is not yet (its status read); the oblique AGL sample
  and the same two waypoint routes in 2D: the count line, the red and yellow pixels of the map, the tooltip over the
  line (with the route's height) and off it; then the count in 3D at the editor's zoom and three levels out (the same).
  Clears the lidar surface only if it was empty before; then remove the index as above. Deletes its routes.
- ASL without the takeoff height (Phase 12): `asl_hint_check.js` (beside this file; how to run it in its first
  lines): the hints, the automatic fetch on picking the takeoff point (one real OpenTopography call; the other answers
  faked with `page.route`), a takeoff point moved during a slow fetch, no fetch on opening a route in ASL, a failed
  fetch shown in the hint with no dialog. Opening routes starts the lidar build: on a stack whose lidar surface was
  empty, wait until no file under `mission_planner_data/lidar` is newer than a minute, then remove it as above.
  Deletes its routes.
- The Pointer tool (Phase 13): `measure_check.js` (beside this file; how to run it in its first lines): with the lidar
  surface off in its own browser (nothing is built), over the oblique AGL sample's place, an area route opening in
  Pointer, three dots in 2D and 3D (labels against the tooltip off the route, the lines' differences), imperial,
  clearing by a dot and by Polygon; a new waypoint route: a click is a dot in Pointer and a point in Add points.
  Deletes its routes.
- Lidar terrain for AGL routes (Phase 14): `lidar_terrain_check.js` (beside this file; how to run it in its first
  lines): the oblique AGL sample's lidar terrain (waiting while units build), its KMZ and COP30's, a waypoint AGL route's
  grounds, Paris and a 5 km2 route on COP30 with their reasons; about 6 OpenTopography calls. Compare the KMZs with
  `dsm_compare.py` (with Pilot 2's DSM: `mission_planner/tests/fixtures/dji-kmz/m4t-testkmz-oblique-AGL.kmz`). The
  editors' lidar layer also builds units round each route it opens (12 for the large one). Afterwards, once no unit is
  queued or building: note the units before the check and remove only the new ones (on a stack with none before,
  remove the lidar folder), remove the `datum.json` the check wrote into earlier units and make their tiles again
  (`lidar.make_tiles` in `manage.py shell`: building a neighbour re-made them), and remove
  `mission_planner_data/grids/us_noaa_g2018u0.tif`. The real-grid test (`test_mission_geoid.TestRealGeoid18`) runs
  only while the grid is there.
- The route in the air and the waypoint labels: `route3d_check.js` (beside this file; how to run it in its first
  lines): imports the oblique AGL sample (AGL over Pilot 2's DSM: the plan's `air` above sea level), screenshots it in
  3D, makes an ALT waypoint route with one point below the ground (red label) and screenshots its labels in 2D and
  3D; `lidar` as a third argument turns the lidar surface on (and clears it at the end). Afterwards remove the grid
  (and with `lidar`, the lidar index) as above.
- The 3D view's "Loading elevation…" (Phase 20): `elevation_loading_check.js` (beside this file; how to run it in its
  first lines): with the lidar surface off and AWS's elevation tiles slowed, in both editors: shown on switching to 3D
  and on a zoom, hidden once drawn and on leaving 3D; screenshots. Deletes its routes.
- The browser console has no new errors, nor `dev/webodm.sh logs webapp`.

## Before

Note what is there already (the user's routes: `GET /api/plugins/mission_planner/routes`): the user works on this
server too. Give everything the check creates a name of its own (e.g. starting "Live check").

## Afterwards

Delete only what the check created (routes, users, tasks, projects), by those names, through the UI or from the
logged-in browser (the plugin's API takes changes only with the session's CSRF token). Never save over an existing
route. Compare with what was there before, and say what was checked and what was removed.
- The code review's visible fixes: `review_fixes_check.js` (beside this file; how to run it in its first lines): the
  import and copy dialogs of a waypoint route, a refused delete, an edit during a save, and Download right after
  Fetch terrain on an AGL route near the oblique AGL sample (its lidar terrain). Deletes its routes. On a stack without
  those lidar units it builds two (about 30 s) and needs GEOID18: remove the `lidar` folder and
  `grids/us_noaa_g2018u0.tif` under `plugins/mission_planner_data` afterwards if the stack had none before.
