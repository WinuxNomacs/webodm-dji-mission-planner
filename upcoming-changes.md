# Upcoming changes

## Phases (current and upcoming)

The order of work, top first. Each phase is planned with the user before it is built; the details are in the
sections below. New requests arrive in `new.md`: they are turned into phases here, and `new.md` is cleared back
to its title.

**Up next**

1. **Phase 22: a sharper 3D ground** (the user, 2026-11-20): buildings and trees drawn closer to their real outlines
   and easier to read, without slowing the 3D view. Started as "1 m blocks like Minecraft"; after the user's
   screenshot (a building's lidar block larger than its roof in the imagery, grass draped on its top edges) the aim is
   definition by sensible, reliable means. Planned (the "Phase 22" section); its first step measures.

Left to the user (Phase 18): ask GitHub Support to garbage-collect the repo and drop cached views of the replaced
commits, then make it public.

Listing in WebODM-Plugins (the user, 2026-11-20, after talking with WebODM's maintainer, who suggested it): from now
on the last step of every release (CLAUDE.md, "Never push and never tag"): a branch in the user's fork of
WebODM-Plugins pointing `directory.json` at the release's zip and sha256, pushed with the user's approval; the user
opens the pull request. It needs the repo public (the directory downloads the zip anonymously). The directory's rules
(its README and `fetch_directory.py`, read 2026-11-20): an OSI licence (AGPL-3.0 here), a `.zip` URL with its sha256,
one root folder with `manifest.json`, the root folder's name as the plugin's id, refused if another plugin has it
(ours `mission_planner`, the maintainer's own Mission Planner `mission-planner`). The README's install section names
the directory in the release that lists it. 2.0.0 can be listed as soon as the repo is public, without a new release.

Releases: 1.0.0 was merged on 2026-11-17 but never published (the plugin was for development only then). 2.0.0, the
first published release, was prepared on 2026-11-20 at the user's request (2.0.0 because 1.0.0 was kept and WebODM 3.3.2
was dropped). Before it, a review of everything changed since the 2026-11-19 code review found 11 issues (none severe),
fixed on `release-review-fixes`: broken KMZ uploads, route types on plan and export, DJI Fly size check and takeoff
warning, lidar files removed mid-read, queued lidar units going stale, POI and oblique copies for DJI Fly, KML without
the geoid grid, readable download errors, double downloads, and the remembered model.

**Later**
1. **Finer terrain for US routes: shelved** (2026-11-17, the user): built and tested on branch `phase-5-3dep`, not
   merged, because USGS 3DEP is bare earth while COP30 and Pilot 2's own DSM include trees and buildings: AGL routes
   would fly up to the canopy's height closer to it than today. COP30 stays. What was built, measured and learned
   is in the Phase 5 section.
2. **Mavic 3M multispectral** (the user, 2026-11-19: after 15b): the `narrow_band` lens as a third camera choice,
   once a real M3M file or a DJI source confirms its name and payload sub value.
3. **Lidar regions, England and Canada** (planned 2026-11-20, kept for later by the user the same day): Phase 23
   (the lidar made pluggable by region, the US its first), Phase 24 (the Environment Agency's 1 m surface, Tower
   Bridge), Phase 25 (Natural Resources Canada's 1 m surface, Canmore; Lake Louise for the fallback). The design and
   the vetting are in the "Lidar regions" section; vet the sources again before building.
4. **Scotland, Wales and Northern Ireland** (the user, 2026-11-20: after England): each nation's lidar as a region,
   once its service is vetted (the Scottish Remote Sensing Portal, Natural Resources Wales through DataMapWales,
   OpenDataNI; partial coverage, and not yet known whether any can be fetched by a program).

**Done**
- **Phase 21: a faster 3D view** (2026-11-20, `phase-21-faster-3d`): `lidar_surface.js` (cut AWS tiles handed to MapLibre
  as `ImageBitmap`s, each zoom-15 parent decoded once, `PARENTS`), `pointer_height.js` (reads such an image). Tests: 4 in
  `lidar_surface.test.js`; `perf_3d_check.js` (live-check skill) measures the 3D view's loads. The user (2026-11-20):
  the slow second switch into 3D (inside MapLibre) is accepted, and the ground is not loaded in 2D.
- **Phase 20: a loading indicator for the 3D view's elevation** (2026-11-20, `phase-20-elevation-loading`): the status
  bar's `loading(on)` and the one-message rule (`lidar_surface.js` `createStatusBar`), `watchElevation` (MapLibre's
  `render`, `sourcedata` and `idle` with `isSourceLoaded("mp-dem")`), wired in `planner.js` and `waypoint_planner.js`.
  Tests: 10 in `lidar_surface.test.js`; live `elevation_loading_check.js` (both editors).
- **Phase 19: true distances in area and linear routes** (2026-11-20, `phase-19-local-frame`): `planning.local_transformers`
  (an azimuthal equidistant frame on the route's middle) replaces the UTM zone in `planning._survey_plan` and
  `linear.plan`; `grid_convergence` and `utm_epsg` removed. Tests: the spacing on the ellipsoid within 1 mm on a zone's
  central meridian, at its edge on the equator and at the sample B place, area and linear (`test_mission_planning`,
  `test_mission_linear`; 10 mm and 6 mm off before); the tests' metric helpers measure true distances; golden files
  regenerated (coordinates up to 1.6e-7 degrees, distance 0.22 m, duration 0.28 s, headings 0.014 degrees).
- **Phase 18: ready to publish** (2026-11-19, `phase-18-publish`): the 36 sample KMZs, the golden files, the tests'
  constants and the live-check scripts moved off the places the samples were flown, each place due east to where
  EGM96 matches at its takeoff point; the author email replaced (`pilot@example.com`); the Smart3D samples' 3D scans
  removed; the terrain rasters cut to about 1.7 km round each route; the place, county and lidar project names out of
  the code, docs and this file; CLAUDE.md says the repo is public. Tests: every module (the golden files regenerated:
  the planner then worked in UTM metres, whose scale changes across a zone; Phase 19 fixed it).
  The fresh public history: `main` force-pushed as one commit (2026-11-19), scanned first.
- **Phase 17: the name DJI Mission Planner** (2026-11-19, `phase-17-dji-name`): the shown name in the manifest, menu,
  page titles and headings, messages, log prefixes, KML text, README, CHANGELOG, CLAUDE.md and skills; the repo name
  in the manifest's homepage and `package.json`; `mission_planner` kept internally; `dev/webodm.sh` keeps the project
  name `webodm-mission-planner` (now commented). Tests: `test_mission_planner_plugin` (the menu), `test_mission_terrain`.
  Left to the user: the rename on GitHub; then Claude points `origin` at the new URL.
- **Rectangle square to the screen** (the user, 2026-11-19, `rectangle-view-aligned`): on a turned map the Rectangle
  tool's sides follow the screen, not north (`Core.rectangleCorners`, in Web Mercator; `viewRectangle` in `planner.js`
  wraps terra-draw 1.35.0's `updateRectangle`, using its internals: check on upgrade). Tests in `planner_core.test.js`.
- **Phase 16: load limits and cleanups from the code review** (2026-11-19, `phase-16-load-limits`): findings 15-21.
  The lidar folder capped at 5 GB (`lidar.evict`, `mark_used`, `usage` from each unit's `usage.json`), at most 20 DJI
  Fly missions a download (`djifly.MAX_MISSIONS`), the block-heights grid and ring bounded, `tasks_covering` reading
  only tasks with a DSM or DTM and the fields used, `save_terrain` leaving no orphan, the settings checks shared in
  `wpml` (`check_choices`, `check_flight`, `check_cameras`, `is_number`, `route_speed`), the import's template read once.
  Tests in `test_lidar.TestCap`, `test_djifly`, `test_mission_geometric` (`TestBlockHeightsGrid`, tasks), `test_routes`.
- **Phase 15d: DJI Fly** (2026-11-19, `phase-15d-djifly`): `missions/djifly.py` (the writer, the split, AGL heights),
  8 consumer drones in `drones.json` (app `djifly`, no payload, `max_speed`), the export choosing it by the drone's app
  (`ExportView.djifly`), the plan refusing what DJI Fly cannot fly; the editors' note and the download's file name.
  Tests in `tests/test_djifly.py`. Details in the Phase 15d section.
- **Phase 15e: KML import and export** (2026-11-19, `phase-15e-kml`): `missions/kml.py` (`read_kml`, `write_kml`), the
  import endpoint taking plain KML (`RouteImportView.plain_kml`, the model from the form), `POST kml` (`api.KmlView`,
  with `plan_result` shared with the plan endpoint), "Download KML" in both editors, the import accepting `.kml`.
  Tests in `tests/test_kml.py`. Details in the Phase 15e section.
- **Phase 15c: M300 RTK and M350 RTK with a payload** (2026-11-19, `phase-15c-m300-m350`): ten entries in
  `drones.json` (`m300-h20` ... `m350-h30t`); a camera's optional `lens` is the name the file uses (`wide`), written by
  `wpml.lens_index` and read back by `kmz_import.read_aircraft`. Tests in `tests/test_pilot2_drones.py`. Details in the
  Phase 15c section.
- **Phase 15b: Pilot 2 drones with built-in cameras** (2026-11-19, `phase-15b-pilot2-drones`): Mavic 3E, 3T, 3M (RGB),
  Matrice 30, 30T, 3D, 3TD, 4D, 4TD in `drones.json` with `route_types` and `realtime_follow` (`missions/drones.py`);
  the API refuses other route types on create, copy and import (`api.check_route_type`) and real-time follow where the
  model lacks it (`wpml.check_realtime_follow`, defaulting to the terrain model); the New Route menu and the copy dialog
  offer only what the model flies (`routes_list.js`), the area and linear editors hide real-time follow
  (`route_form.js`). Tests: `tests/test_pilot2_drones.py`, `test_drones`, Jest (`routes_list`, `route_form`). Live on
  4.0.0: the menu for the M30, its editor, the M3T editor, the copy dialog of a slope route, an M30T KMZ (67/1/53/2,
  `visable,ir`). Details in the Phase 15b section.
- **WebODM 3.3.2 dropped** (2026-11-19, the user: the plugin only needs WebODM 4 and later; `drop-webodm-332`):
  `manifest.json` `webodmMinVersion` 4.0.0; `api.dsm_extent` reads only GeoJSON extents (the PostGIS branch removed,
  and the tests' helper with it); `dev/webodm.sh` runs 4.0.0 only; Ruff targets py314 (two new style rules ignored,
  as the others); the host venv is Python 3.14 with 4.0.0's versions; README, CHANGELOG, CLAUDE.md and the `test`,
  `live-check` and `release-check` skills say 4.0.0 only. The 3.3.2 mentions further down are history.
- **Phase 15a: one drone registry** (2026-11-19, `phase-15a-registry`): `mission_planner/drones.json`, read by
  `missions/drones.py` (validated at load; `cameras.CAMERAS_BY_MODEL`, `wpml.AIRCRAFT`, `routes.AIRCRAFT_MODELS` and
  `kmz_import.read_aircraft` come from it) and by the pages (`#mp-drones`, `planner_core.js` `DRONES`; the model menus,
  IR chip and help text in the templates). M4T and M4E files unchanged (the golden files). The experimental warning
  says "use it at your own risk". Tests: `tests/test_drones.py`, page tests in `test_mission_planner_plugin.py`, Jest
  `planner_core.test.js`. Which route types and features each drone has is left for 15b, where they first differ.
- **Fixes from the code review, findings 1-14** (2026-11-19, `fix-review-1-14`): 13 fixed, number 13 not a bug. Each fix
  has a test seen failing first: `test_mission_planner_plugin.py` (the elevation cache, route type and PUT, low speed,
  bad model), `test_mission_waypoints.py` (malformed values), `test_mission_linear.py` (doubling back, low speed),
  `test_mission_wpml.py` (`auto_speed`), `test_mission_elevation.py`, `test_lidar.py` (`project_for`),
  `test_luxodm_import.py`, Jest `routes_list.test.js` and `planner_core.test.js` (`createSaver`).
- **Phase 14: lidar for AGL routes' terrain** (2026-11-19, `phase-14-lidar-terrain`): `lidar_terrain.py` (the 10 m
  terrain, the fallbacks, `satisfies`), `missions/geoid.py` (GEOID18, `navd88_shift`), `lidar.py` (`units_for`,
  `datum_check`), `api.py` (`terrain_source`, 202 while building), the Terrain choice in both editors
  (`planner_core.js`: `terrainText`, `buildingText`, `fetchUntilBuilt`); tests in `tests/test_lidar_terrain.py`,
  `tests/test_mission_geoid.py`, `__tests__/planner_core.test.js`; live check
  `.claude/skills/live-check/lidar_terrain_check.js`. FlightHub 2 loads the 10 m file (the user, 2026-11-19), but
  replaces it on import, as it does every imported terrain; Pilot 2 on the controller keeps it and flies its
  heights (the user, 2026-11-19).
- **Phase 13: the Pointer tool** (2026-11-18, `phase-13-pointer-tool`): `measure.js` (the dots, the dotted lines and
  their labels), both editors' `setTool` and map clicks (`planner.js`: Terra Draw's static mode in Pointer;
  `waypoint_planner.js`: the new toolbar, `showPointsMessage`), the toolbars in `planner.html` and
  `waypoint_planner.html`; tests in `__tests__/measure.test.js` and `tests/test_mission_planner_plugin.py` (the
  toolbars' order), live check `.claude/skills/live-check/measure_check.js`.
- **Phase 12: ASL without the takeoff height** (2026-11-18, `phase-12-asl-hint`): `planner_core.js` (`aslHint`,
  `aslAutoFetch`, `aslReady`, `cachedElevationFor`), both editors (`showAslHint`, `aslAutoFetch`, `fetchElevation(auto)`),
  the hint lines in `planner.html` and `waypoint_planner.html`; tests in `__tests__/planner_core.test.js`, live check
  `.claude/skills/live-check/asl_hint_check.js`. Also before it: ASL area and linear routes drawn at their flown height
  in 3D (`fix-asl-route-3d`, `missions/air.py`).
- **Phase 11: collisions and the route's height in 2D** (2026-11-18, `phase-11-collisions-2d`): `route_3d.js`
  (`pointsNeeded`, the check run on the sampled heights in 2D and 3D, `flatStretches` and the `-flat` GeoJSON layer,
  `nearest` and `routeNear`), `pointer_height.js` (`heightsAt`, the route's height in the tooltip),
  `lidar_surface.js` (`ensure`, `unitsKey`), both editors (the lidar built from 2D); tests in
  `__tests__/route_3d.test.js`, `pointer_height.test.js`, `lidar_surface.test.js`; live check
  `.claude/skills/live-check/collide2d_check.js`.
- **Phase 10: collisions shown on the route in 3D** (2026-11-18, `phase-10-collisions`): `route_3d.js` (`collide`,
  `collisionText`, every path cut, colours in the line vertices, the red drawn again without the depth test, discs at
  the plan's points), the count line `#mp-collisions` in both editors' side panel; tests in
  `__tests__/route_3d.test.js`, live check `.claude/skills/live-check/collide3d_check.js`.
- **Phase 9: drawing and editing in 3D** (2026-11-18, `phase-9-edit-3d`): `planner.js` and `waypoint_planner.js`
  (`setView3d`, `startAirDrag`), `route_3d.js` (`unproject`, `airDrag`, `resolved().points`); tests in
  `__tests__/route_3d.test.js`, live check `.claude/skills/live-check/edit3d_check.js`.
- **Phase 8: the route in the air in 3D, waypoint height labels** (2026-11-18, `phase-8-route-3d`): `missions/air.py`
  (the path's heights and what they are measured from, in the plan's `air`), `api.py`'s `plan_terrain`,
  `public/route_3d.js` (the custom WebGL layer, the heights over the surface, the labels), wired in both editors;
  tests in `tests/test_air.py` and `public/__tests__/route_3d.test.js`; live check
  `.claude/skills/live-check/route3d_check.js`. Details in the Phase 8 section.
- **Bug: the takeoff point's height in the KMZ is ellipsoidal** (2026-11-18, `fix-takeoff-ellipsoid`):
  `missions/geoid.py` (EGM96 through PROJ), `wpml.takeoff_ref_point`, `kmz_import.sea_level`; tests in
  `tests/test_mission_geoid.py` and `test_mission_kmz_import`, the real grid in `tests/fixtures/geoid`; live check
  `.claude/skills/live-check/takeoff_check.js`. Details in its section.
- **Phase 7: the ground height under the pointer** (2026-11-18, `phase-7-pointer-height`): `public/pointer_height.js`
  (the tile and pixel under a point, Terrarium decoding, the tooltip), `lidar_surface.js`'s `refresh` and
  `isBuilt`, wired in both editors; tests in `public/__tests__/pointer_height.test.js`; live check
  `.claude/skills/live-check/pointer_check.js`. Details in the Phase 7 section.
- **Phase 6: a lidar surface in the 3D view** (2026-11-18, `phase-6-lidar-surface`): `lidar.py` (units, states,
  the index, the worker's build, tiles, the settings page's size and clear), `api.py`'s `LidarSurfaceView` and
  `LidarTileView`, `public/lidar_surface.js` (the `mplidar://` protocol, polling, the status bar), the layers panel's
  "Lidar surface (US)"; tests in `tests/test_lidar.py` (39, every failure injected) and
  `public/__tests__/lidar_surface.test.js`; live check `.claude/skills/live-check/lidar_check.js`. Details in the
  Phase 6 section.
- **Lidar DSM test** (2026-11-18, branch `spike-lidar-dsm`, not merged; its code is the starting point of Phase 6):
  the user judged the look "an acceptable starting point". Details and measurements in its section.
- **Phase 4: 1.0.0 prepared, not released** (2026-11-17, `terrain-folder` and `release/1.0.0`; dev only, the user): the terrain in
  `plugins/mission_planner_data` (`routes.terrain_root`, test in `tests/test_routes.py`), version 1.0.0, the release
  check's script (`.claude/skills/release-check/release_check.js`); details in the Phase 4 section.
- **Phase 3: the routes from LuxODM** (2026-11-17, `phase-3-luxodm-import`): `luxodm_import.py`, `routes.restore`,
  the settings page's import section; tests in `tests/test_luxodm_import.py`; LuxODM's `export_routes` on its
  branch `route-export`; details in the Phase 3 section.
- **Phase 2: the OpenTopography key as a plugin setting** (2026-11-17, `phase-2-key-setting`): `config.py`,
  `plugin.py`'s `settings_page`, `templates/settings.html`, `missions/elevation.py`'s `check_api_key` and
  `without_key`; tests in `tests/test_settings.py`, `test_mission_elevation`, `test_mission_terrain`; details in the
  Phase 2 section.
- **Phase 1: the code moved in, with its own storage** (2026-11-17, `phase-1-move`): `mission_planner/` (`routes.py`,
  `surface.py`, `config.py`, `api.py`, `missions/`, MapLibre 6.16.0), tests in `mission_planner/tests` (Django, 426 on
  each WebODM) and `public/__tests__` (Jest, 282); details and what was checked in the Phase 1 section.
- **Scaffold** (2026-11-17, `scaffold`): the repo (private, `WinuxNomacs/webodm-mission-planner`), the dev stacks
  (`dev/webodm.sh`, WebODM 4.0.0 on :8009 and 3.3.2 on :8010), `dev/package.sh`, Ruff, ESLint, Jest, the host
  venv, the `test`, `live-check` and `release-check` skills, this plan. No plugin code yet.

## Why this repo

LuxODM (a fork of WebODM) is being retired: its other features were ported to plugins, all but the mission planner
(the user, 2026-11-17). In LuxODM the planner was a plugin (`coreplugins/mission-planner`, about 8,460 lines) that
leaned on core code: `app/missions/` (4,200 lines: the planners, the WPML writer, KMZ import, cameras, terrain,
elevation), the `Route` model and its migrations, `app/source_photos.py` (shared with LuxODM's findings), the
OpenTopography key in Django's settings, two dark-theme lines and all its tests (about 8,500 lines, golden files and
36 KMZ fixtures). This repo makes it a plugin that installs on an unmodified WebODM.

Decided with the user (2026-11-17):
- The repo is `webodm-mission-planner`, private (the KMZ fixtures stay as they are: they carry real flight data);
  the plugin is installed from the release zip, not listed in WebODM-Plugins.
- The existing LuxODM routes carry over (Phase 3), by an export from LuxODM and an import in the plugin.
- The plugin is enabled when installed (LuxODM's `disabled` file is dropped); the page keeps its "Experimental:
  check every mission in Pilot 2" warning.
- WebODM 3.3.2 and 4.0.0 both (as webodm-geojson). Changed 2026-11-19 (the user): WebODM 4.0.0 and later only.

## Phase 1: move the code in, with its own storage

Planned 2026-11-17 (the storage settled from WebODM's code; nothing left for the user).

**What moves** (from LuxODM's `main`; the commit is recorded when the phase starts):
- `coreplugins/mission-planner/` to `mission_planner/` (without `disabled`): `plugin.py`, `api.py`, `manifest.json`
  (author and homepage changed, `webodmMinVersion` 3.3.2), `templates/`, `public/` (ES5 scripts, MapLibre 5.24.0
  and terra-draw 1.35.0 from `public/package.json`, installed by WebODM's npm on install).
- `app/missions/*.py` to `mission_planner/missions/`, imports made relative.
- From `app/source_photos.py`, only what the slope and block heights use (`surface_heights` and the DSM and point
  cloud readers) to `mission_planner/source_photos.py`.
- The tests: `app/tests/test_mission_*.py` to `mission_planner/tests/`, `app/tests/golden/missions/` and
  `app/fixtures/dji-kmz/` with them; `public/__tests__/` as it is.
- The two dark-theme lines of LuxODM's `theme.css` into `planner.css`, if WebODM's own theme needs them.

**Storage** (WebODM gives plugins no migrations, so no table):
- A route is one key of the owner's `UserDataStore("mission_planner")`, `route:<id>`, holding what the `Route`
  model held: name, type, aircraft, settings, terrain info, the terrain file's name, created and updated times.
- **A route's id is its `PluginDatum` row's primary key** (settled 2026-11-17): Postgres allocates it, so two
  routes made at once never share one, and it stays an integer as in LuxODM (the editor's URL `route/<id>`, the
  `routes/<pk>` API, `route_id` in the export body: no change to the scripts). Created in one transaction: the row
  is written through the data store under a temporary key (`route:new:<uuid4>`), then its key set to
  `route:<pk>`. Weighed and not taken: a counter in the `GlobalDataStore` (read then write: two requests can take
  the same number) and random string ids (the URLs, the API's patterns and the scripts' `parseInt` change).
- **A user's routes are listed by reading their `PluginDatum` rows** whose keys start `mission_planner::route:`
  (settled 2026-11-17), sorted by `updated_at` in Python. Not an index key: keeping one is a read then a write, so
  two routes made at once lose one. Reading and writing `PluginDatum` directly is limited to the plugin's own
  namespace; everything else goes through `UserDataStore`.
- Saving a route replaces its JSON whole, as LuxODM's `Route.save` wrote every field: two tabs saving the same
  route, the last one wins (as before).
- The terrain rasters are files in the plugin's persistent folder (`get_persistent_path("terrain", "<id>")`),
  removed with their route. A deleted user's rows go with the user (`PluginDatum.user` cascades), their terrain
  folders do not: after each route delete, a sweep removes the folders whose id has no route row (one query).
- Lost from LuxODM: the Django admin page for routes.

**Both WebODM versions:**
- "Heights from a task's DSM" found tasks with `dsm_extent__contains`, a PostGIS lookup that 4.0.0 (JSON extents)
  does not have: it takes the user's tasks that have a DSM and checks the extent in Python, from a geometry (3.3.2)
  or GeoJSON (4.0.0).
- Python 3.9 syntax (Ruff), numpy 1.26 and 2.5, rasterio 1.3 and 1.5, Django 2.2 and 5.2, DRF 3.13 and 3.18.

**Security: MapLibre 5.24.0 to 6.16.0** (found 2026-11-17). MapLibre up to 6.4.0 can let a script through in a
basemap's attribution text ([GHSA-jrc7-96c5-q579](https://github.com/advisories/GHSA-jrc7-96c5-q579)), and the
planner's maps show WebODM's basemaps. webodm-geojson 1.1.1 made the same move (MapLibre 6 handed to the ES5
scripts by one ES module, `maplibre.mjs`; it needs WebGL2 and ES2022). terra-draw's MapLibre adapter is checked
against MapLibre 6 then. LuxODM's own copy has the same version until it is retired.

**Built (2026-11-17, branch `phase-1-move`, from LuxODM `main` 60081583):** `routes.py` (the storage above, with
`tests/test_routes.py`), `surface.py` (LuxODM `source_photos`' DSM and DTM readers only: the planner never read the
point cloud), `config.py` (the key from the environment), `api.py`'s `tasks_covering` (the DSM extent compared in
Python), MapLibre 6.16.0 through `public/maplibre.mjs`. Found on the way: GEOS's transform swaps the axes on 3.3.2
(Django 2.2, GDAL 3), so the API transforms with pyproj (LuxODM's block heights would have been wrong there); PROJ
9.3 and 9.4 differ in the last digits (golden files compared to 9 decimals); the rename icon was `fa-pencil`, which
Font Awesome 5.11.2 lacks. Checked: Django tests on both stacks (426 each, and `app.tests.test_plugins`), Jest
(282), Ruff, ESLint; live on both, each route type imported from Pilot 2 samples, its editor (MapLibre 6.16.0, no
page errors), its export (the same files on both versions), 3D view, rename, copy for the other aircraft, delete,
an imported DSM kept as the route's terrain and embedded in the export, heights from a task's DSM (a synthetic DSM
in a throwaway task: base and top, face corners). Then, with the key (copied, as the user asked,
from LuxODM's `.env` to this repo's): COP30 terrain and the takeoff height fetched live from OpenTopography on both
stacks, the old terrain file replaced, the export embedding the new one. Not changed: MapLibre warns that the hillshade and the 3D terrain
share a source (5.24.0 did too).

**Done when:** the moved tests (Django on both stacks, Jest), Ruff and ESLint pass; live on both, each route type's
editor (area, linear, waypoint, slope, geometric), export to KMZ, KMZ import, copy for the other aircraft, terrain fetched
and cached, heights from a task's DSM.

## Phase 2: the OpenTopography key as a plugin setting

In LuxODM the key was `WO_OPENTOPOGRAPHY_API_KEY` in Django's settings, which a plugin cannot add. Phase 1 reads
it from WebODM's environment only (`config.py`).

Planned 2026-11-17. Decided with the user:
- **Where:** a "Settings" button on the Mission Planner page (the routes list, beside "New route"), shown only
  to administrators (superusers). It opens the plugin's settings page (`/plugins/mission_planner/settings`); others
  get "permission denied". Not a side-menu entry: WebODM's side menu (`main_menu`) has no request, so it would show
  the entry to every user.
- **The environment wins:** when `WO_OPENTOPOGRAPHY_API_KEY` is set, it is the key, and the page says "Set by
  WebODM's environment" with the field disabled. Otherwise the key saved on the page is used.
- **Saving tests the key:** one Point Elevation request (`elevation.py`'s endpoint, one call of the free key's
  50 a day). A key OpenTopography refuses is not saved and the page shows its message; when OpenTopography
  cannot be reached, the key is not saved either and the page says so (try again later).

Design (settled from the code):
- The key is a string in the plugin's `GlobalDataStore` (`mission_planner::opentopography_api_key`), plain text
  in WebODM's database, as the environment variable is in plain text in WebODM's `.env`. The page never shows the key:
  only where the key in use comes from (WebODM's environment, saved here, or none), with "Remove" for a saved
  key.
- `config.opentopography_api_key()` returns the environment's key, else the saved one, else "".
- The page is a plain Django form (POST with CSRF), in WebODM's layout; no script.
- Without a key, fetching terrain, the takeoff height or the ground heights answers "No OpenTopography API key is
  set: an administrator sets it on the Mission Planner page, under Settings"; the rest of the planner works.

**Done when:** Django tests on both stacks: the page and the save refused to non-admins and to anonymous users;
the button shown only to admins; saving tested (accepted, refused, unreachable: the request faked); the
environment winning; "Remove"; the key never in a response. README and CHANGELOG updated. Live on both stacks,
each started once without the environment's key (a `dev/webodm.sh` switch that skips `.env`): the button absent for a non-admin user; a wrong key refused; the
key saved, terrain and the takeoff height fetched with it; removed; then the stack back with the environment's key,
the page showing "Set by WebODM's environment". The live check types the key from this repo's `.env` without
printing it (as the user asked to copy it there for these checks).

**Built (2026-11-17, branch `phase-2-key-setting`):** as designed. Found on the way: OpenTopography's refusal
repeats the key ("Invalid API key: <key>", its answer to a made-up key, captured 2026-11-17), and requests
repeats the URL, key included, in a connection error, which the terrain and takeoff-height errors passed on to
the browser (LuxODM does too). Both are now removed from every message (`without_key`), and a refused key (401,
403) says where to change it. `dev/webodm.sh` got `MP_NO_KEY=1`. Checked: Django tests on both stacks (455 each,
with `app.tests.test_plugins`), the key-leak tests seen failing without the fix, Ruff; live on both
(`.claude/skills/live-check/settings_check.js`): the button for the admin only (403 for a non-admin user), a
made-up key refused without repeating it, the real key saved and never on the page, the takeoff height (246 m
orthometric, 211.80 m ellipsoidal) and COP30 terrain fetched with it, removed, the no-key message; then with
the environment's key, the page saying it is set there, its field and Save disabled. Not changed: WebODM's dev
pages load livereload from port 35729 whatever the stack's port, so with LuxODM running they reload on LuxODM's
rebuilds.

## Phase 3: the routes from LuxODM

Planned with the user 2026-11-17.

**In LuxODM** (a LuxODM branch): `manage.py export_routes <file>` (`app/management/commands/export_routes.py`), run
in `webapp`, writes every route to one JSON file: `{"format": "luxodm-routes", "version": 1, "routes": [...]}`, each
route with the owner's username, its LuxODM id, name, route type, aircraft, settings, terrain info, created and
updated times, and the terrain GeoTIFF (base64, null when none or its file is gone). It only reads (no route is
saved, #20 included). The file goes under `ignored/` (git-ignored).

**In the plugin:** an "Import routes from LuxODM" section on the Mission Planner page > Settings page
(administrators only, as the rest of the page), a file upload. WebODM plugins are not Django apps, so a management
command in the plugin would not be found: the page is the way in.
- The whole file is checked before anything is written (format and version, each route's type, aircraft, settings
  a dict, terrain a GeoTIFF that reads); a file that fails is refused with the reason, nothing imported.
- Each route goes to the account with its owner's username. **No such account: skipped and reported** with the
  username (the user's answer), so the account can be made and the file imported again.
- **Importing the same file again imports its routes again, as copies** (the user's answer): no record of what was
  imported is kept.
- Imported routes get new ids (ids are row keys, see Phase 1) and keep LuxODM's created and updated times, so the
  routes list keeps its order. The page reports each route: its LuxODM id and name, then its new id with an Open
  link, or why it was skipped. Bookmarked LuxODM editor URLs do not carry over.
- **The import stays in the plugin** after the move (the user's answer): it ships in 1.0.0; README and CHANGELOG
  say what it is for.

**Checked:** on both dev stacks, with an export of the user's LuxODM data (LuxODM running): routes 1, 8, 15, 18 and
20 open in the plugin's editors with their settings and terrain, and export the same KMZ as in LuxODM; the skipped
owner and a refused file shown on the page; the imported routes deleted afterwards.

**Built** (2026-11-17, `phase-3-luxodm-import`; LuxODM's part on its branch `route-export`):
- Plugin: `luxodm_import.py`, `routes.restore`, the import section of `templates/settings.html` and `plugin.py`'s
  `settings_page`; tests in `tests/test_luxodm_import.py` (20). LuxODM: `app/management/commands/export_routes.py`,
  tests in `app/tests/test_route_export.py` (6).
- Checked differently from the plan: LuxODM's dev data was gone when the check ran (its database and media volumes
  were recreated empty on 2026-11-17, not by this work), so routes 1, 8, 15, 18 and 20 could not be exported. With
  the user's agreement the check made 7 routes in LuxODM from its fixture KMZs (area oblique AGL with the KMZ's
  DSM as terrain, linear, M4E waypoint, slope, geometric, POI waypoint, and an M4E copy whose COP30 terrain the
  editor fetched), exported them and imported the file on both stacks: 7 of 7 imported, each route's fields equal
  to LuxODM's, reloading the report page imported nothing more, and each editor's download had the same entries and
  terrain as LuxODM's, differing only in the create and update times and floating-point noise (largest: 2.3e-13 m
  on 4.0.0; 9.5e-9 m in a distance, 6e-9 degrees in a heading, 1e-13 degrees in a coordinate on 3.3.2). A skipped
  owner and a file that is not JSON were shown on the page. Everything the check made was removed. The check is in
  the `live-check` skill (`luxodm_import_check.js`, `kmz_compare.py`).

## Phase 4: release 1.0.0

Planned with the user 2026-11-17.

**Found while planning: an upgrade would delete every route's terrain.** A plugin installed from a zip lives in
WebODM's `media/plugins/<name>` (`app/admin.py`'s `plugin_upload`), and `get_persistent_path` points into that same
folder, so the terrain (`terrain/<id>`) sits inside the installed code. Administration > Plugins has no upgrade for
an uploaded zip (only WebODM's plugin browser sends `upgrade=1`, for listed plugins): the user deletes the plugin,
which removes `media/plugins/mission_planner` whole (`delete_plugin`), then uploads the new zip. The routes and the
key survive (their `PluginDatum` rows are not the plugin's); the terrain would not: COP30 is fetched again at one
OpenTopography call per route, a DSM from an imported KMZ is lost. Checked in WebODM 4.0.0 and 3.3.2's code. A later
release cannot rescue it (the folder is gone before its code runs), so it is fixed before 1.0.0.

**1. The terrain beside the plugin** (branch `terrain-folder`; the user's choice, 2026-11-17):
- `routes.terrain_root()` becomes `media/plugins/mission_planner_data/terrain` (`get_plugins_persistent_path`, so
  inside WebODM's plugin media and its path check). WebODM skips the folder when it looks for plugins (no
  `plugin.py`: `valid_plugin`), and deleting the plugin leaves it, as it leaves the routes.
- Weighed and not taken: the terrain in the database (a `PluginDatum` per route, base64: survives too, goes with
  its user, but grows the database by a third more than the files and rewrites the terrain code, the sweep and
  `routes.restore`); leaving it and documenting the loss.
- No existing install to move (nothing released; the dev stacks have no routes). On both dev stacks the old empty
  `media/plugins/mission_planner` (made by the mounted copy's terrain writes) is removed after checking it is
  empty: a zip install refuses a name whose folder exists.
- Tests: the terrain root is not inside the plugin's install folder; a route's terrain survives the removal of
  that folder (as `delete_plugin` does it). The routes.py docstring, README and CLAUDE.md say where terrain lives.
- Done when: the Django tests on both stacks, Ruff; live on one stack, an AGL route's terrain fetched and written
  to the new folder.

**2. `release/1.0.0`:**
- `manifest.json` 1.0.0. `"experimental": true` stays, as the page keeps its "check every mission in Pilot 2"
  warning (WebODM shows the flag only in its plugin browser, where this plugin is not listed).
- `CHANGELOG.md`: "Unreleased" becomes "1.0.0 (<date>)", with the terrain's folder.
- `README.md` "Installing": the zip from the GitHub release, uploaded in Administration > Plugins (with its sha256);
  upgrading is Delete then upload the new zip, and the routes, their terrain and the key stay.
- `dev/package.sh` builds `dist/mission_planner-1.0.0.zip` and prints its sha256.
- No upgrade rehearsal from a published version: there is none. Coming from LuxODM is the import, checked in
  Phase 3. The front-end dependencies are unchanged since Phase 1 (`npm audit` on `public/`: 0 vulnerabilities,
  2026-11-17); the plugin has no Python dependencies of its own.

**The release check** (the `release-check` skill, on 4.0.0 and 3.3.2), with two additions to the skill:
- Before the install, `media/plugins/mission_planner` must not exist on the stack.
- After the live check on the installed copy: the settings page (the environment's key shown as set), an import
  of a small hand-made LuxODM export (one route with terrain), then **Delete the plugin and upload the same zip
  again**: the routes and their terrain are still there and an AGL route downloads without fetching terrain again
  (this is the upgrade path; from 1.0.1 on, the check upgrades from the previous release's zip instead).

**Built** (2026-11-17):
- `terrain-folder` (merged first): as planned; the new test seen failing on the old path. Django tests 476 OK on
  4.0.0 and on 3.3.2 (with `app.tests.test_plugins`), Ruff; live on 4.0.0 an AGL route's COP30 terrain written to
  `mission_planner_data/terrain/<id>` and removed with the route.
- `release/1.0.0`: the manifest, CHANGELOG and README as planned. WebODM's "Load Plugin (.zip)" has no sha256 field,
  so the README says to check the zip with `sha256sum`, and `dev/package.sh`'s comment no longer says WebODM asks for it.
- Release check, on 4.0.0 and 3.3.2 alike (`release_check.js`): the zip built on the release branch installed
  through Administration > Plugins ("Mission Planner installed successfully", enabled, version 1.0.0, the menu entry
  without a restart, WebODM's npm run in the installed copy); the six Pilot 2 samples (area AGL with its DSM, linear,
  M4E waypoint, POI waypoint, slope, geometric) imported (the first through the routes list's dialog), each editor's
  KMZ downloaded; an AGL route's editor fetching COP30 before its download; the settings page showing the
  environment's key; a hand-made LuxODM export imported with its terrain. Then the plugin deleted (its folder and menu
  entry gone, the 3 terrain files kept) and the zip loaded again: all 8 routes there, the 3 with terrain downloading
  without fetching it and with the DSM in the KMZ. Everything the check made deleted; both stacks back on the mounted
  plugin with no routes. Found on the way: in dev mode the second load restarts the server (the autoreloader) and
  cuts off the upload's answer, after the install has gone through (noted in the skill). OpenTopography requests: 4
  answered (the `terrain-folder` live check, the script's first COP30 route, one per stack's full check) and 2 that
  failed with 502 (an editor refetching for that first route, whose copied settings put its takeoff about 70 km from
  its polygon; fixed in the script); whether those 2 counted against the key's daily limit is unknown.

After the merge, `dev/package.sh` was made reproducible (every entry stamped with the last commit that changed
  `mission_planner/` or `LICENSE`, fixed permissions): before, the files' times were HEAD's, so each commit, docs
  included, changed the sha256. The zip to attach, `dist/mission_planner-1.0.0.zip`, sha256
  `8635393ebd01c62cc95378c3013a55c86ae3857b67030e5294cf351c77aa2eef` (the same files as the checked build,
  installed once more on 4.0.0).

**Then:** `release/1.0.0` merged. Not released: after the merge the user said the plugin is for development only and
no release is planned (2026-11-17), so no `v1.0.0` tag and no GitHub release; the README says so.

## Phase 5: finer terrain for US routes (USGS 3DEP 10 m): shelved

Moved from LuxODM's Later 2026-11-17; planned with the user 2026-11-17; built and shelved the same day (below).

**Shelved** (2026-11-17, the user's choice: "Keep COP30, shelve"). Built on branch `phase-5-3dep` (974e069,
7a9093e; not merged): `missions/geoid.py`, the 3DEP path in `missions/terrain.py`, 24 tests, fixtures in
`tests/fixtures/3dep`, and the live-check skill's `terrain_3dep_check.js` and `dem_compare.py`. The Django tests
passed on 4.0.0 (498), and every failure handler was seen caught by its test with that handler broken. Live on
4.0.0, an AGL area route got USGS10m terrain, a waypoint route its heights from it, and the Detroit River fell back
to COP30. Not run on 3.3.2.

**Why shelved:** 3DEP is bare earth (USGS's data catalog: "the topographic bare-earth surface"), while COP30 is a
surface model with buildings and vegetation (Copernicus's documentation, as quoted by a secondary source), and so
is Pilot 2's embedded ASTER DSM. Measured over the Pilot 2 AGL sample's area (3350 cells), the final USGS10m DSM
minus COP30 was: mean -2.52 m, median -2.00 m, RMS 3.17 m, from -10 m to +2 m. Against Pilot 2's DSM: mean -2.05 m,
from -11 m to +6 m. About 0.7 m of the mean is the datum: COP30's EGM96 shift is -33.73 m there, against -34.44 m
for GEOID18 plus NAD83 to WGS84. The rest is the canopy and roofs, which AGL over 3DEP would not clear by the set
height. A per-route choice ("surface" COP30 or "bare ground" 3DEP) was offered and not taken for now.

**Learned (still true if this comes back):**
- 3DEP's answer (captured 2026-11-17) is EPSG:4269 (NAD83), float32, nodata -999999, cells of 1/3 arc-second. It is
  snapped to the service's grid, up to 0.85 of a cell short of the requested bounds on a side. Where 3DEP has no
  data, the raster is cropped to the US (Tijuana) or has gaps (Detroit), or the answer is 204 with no content
  (the Detroit River).
- PROJ's own NAD83(2011) to WGS84 is a no-op with 2 m accuracy (pyproj 3.6.1 and 3.8.0). Through ITRF2014 (EPSG:7912)
  it lowers heights by 0.7-1.1 m and moves points up to about 1 m.
- The GEOID18 grid `us_noaa_g2018u0.tif` (16,742,155 bytes, sha256 `fa9a407a...340abce2`, about 1 s from cdn.proj.org)
  matched NGS's GEOID18 web API to within 2 mm at 6 points across CONUS. WebODM's images ship only `egm96_15.gtx`.
- Pilot 2's embedded DSMs are about 2.9 MB; a 10 km 10 m raster would be smaller. WebODM's gunicorn timeout is
  300000 s.
- OpenTopography calls this phase used: about 13 raster calls (3DEP and Global DEM together) and 8 Point Elevation
  calls, all on 4.0.0.

The AGL terrain embedded in area, linear and waypoint missions is COP30 (30 m, about 2-4 m RMSE) from
OpenTopography (`missions/terrain.py`). In the lower 48 states USGS 3DEP 1/3 arc-second (10 m) is finer, and
OpenTopography's USGS 3DEP Raster API serves it with the same key.

**Decided with the user:**
- **Datum:** 3DEP is NAVD88 on NAD83(2011). Its heights move to the WGS84 ellipsoid with NOAA's GEOID18 grid through
  PROJ, at every pixel, then an explicit NAD83(2011) to WGS84 step. Not taken: NGS's GEOID18 web API per fetch (a
  second outside service, terms and limits unstated), and reusing today's EGM96 shift (an unmeasured error, likely
  1-2 m, which undercuts the gain from 10 m data).
- **The grid** `us_noaa_g2018u0.tif` (16.0 MB, public domain per cdn.proj.org's `us_noaa_README.txt`) is downloaded
  once from cdn.proj.org into `media/plugins/mission_planner_data/grids/`, beside the terrain, so it survives an
  upgrade. Not taken: bundling it in the zip. The dev images hold only `egm96_15.gtx`, and PROJ's network is off
  (checked 2026-11-17: pyproj 3.8.0 on 4.0.0, 3.6.1 on 3.3.2).
- **The takeoff height stays SRTM GL1** (`elevation.py` unchanged): this phase changes the terrain raster only.
- **CONUS only:** a coarse box (lon -125 to -66.9, lat 24.5 to 49.4). Outside it, and wherever 3DEP fails or has
  gaps, COP30 as today. Alaska, Hawaii and Puerto Rico use other vertical datums and grids.

**Checked 2026-11-17** (opentopography.org/developers, opentopography.org/node/3534, the API's OpenAPI listing):
`GET https://portal.opentopography.org/API/usgsdem`, `datasetName=USGS10m`, `south`, `north`, `west`, `east`,
`outputFormat=GTiff`, `API_Key`. 10 m allows 25,000 km2 a request, and 1 m is academic-only. A free non-academic key
gets 50 calls a day, shared by the Global DEM and 3DEP Raster APIs. The service relies on USGS's own services,
whose outages OpenTopography does not control. Not documented, so captured first: the output CRS (expected NAD83,
EPSG:4269), its nodata, and what comes back outside coverage. Weighed and not taken earlier: Esri World Elevation
(an ArcGIS account, mostly 30 m SRTM outside countries with national data, terms for embedding in a KMZ unchecked)
and ASTER GDEM v3 (8.5 m RMSE over the US per USGS, not on OpenTopography).

**Design:**
1. **Samples first** (3-4 OpenTopography calls), as fixtures in `tests/fixtures/3dep/`: a USGS10m GeoTIFF over the
   Pilot 2 samples' area, one straddling the Canadian border, one over the sea or Mexico. Also: GEOID18
   heights from NGS's `geodesy.noaa.gov/api/geoid/ght` at a few points (the grid test's reference), the grid's
   sha256 (pinned), the PROJ operation each stack picks for EPSG:6319 to EPSG:4979 (pinned to a NAD83(2011) to
   ITRF2014 Helmert step if one picks a ballpark or null transform), and the DSM size in a Pilot 2 KMZ beside a
   10 km 10 m raster's (about 1000 x 1000 int16).
2. **`missions/geoid.py`:** the grid's path and `ensure_grid()`. The grid is downloaded to a temporary file with a
   deadline, checked (size, sha256, opens), then renamed into place. A cached grid that does not read is set aside
   (`.bad`), never fatal. `to_ellipsoid(heights, transform)` converts every pixel's centre.
3. **`missions/terrain.py`:** in CONUS, `fetch_terrain` tries 3DEP first (`_fetch_usgsdem`, the same key handling
   and messages as `_fetch_globaldem`). Any failure but a refused key falls back to the current COP30 path,
   unchanged. `terrain_info` records `dataset` (`USGS10m` or `COP30`) and `vertical` (`GEOID18` or `EGM96`); the
   file is `wgs84_USGS10m_<tile>_dem.tif`. The callers in `api.py` are unchanged, and the editor's terrain status
   already shows the dataset. Terrain already cached as COP30 stays until it is fetched again.

**Failures and what happens:**

| Failure | What happens |
|---|---|
| cdn.proj.org unreachable or slow | Times out (deadline under WebODM's request timeout, checked on both stacks), then COP30 |
| Partial or corrupt download | The temporary file is discarded, then COP30 |
| A cached grid that does not read | Set aside, downloaded again |
| Two requests download at once | Each writes its own temporary file; the rename is atomic |
| Disk full | The write error is caught, then COP30 |
| USGS or OpenTopography error or timeout | COP30 |
| 3DEP gaps (outside the US within the box) | COP30 |
| A CRS other than the one captured | COP30 |
| Key refused (401, 403) | The error as today, no fallback |

**Tests:** fake HTTP for 3DEP and the CDN and a small synthetic grid. Every failure above is injected, and each test
is seen failing before its handling is written. Also: the key is never in a message; the grid is downloaded once and
reused; the real conversion is checked against NGS's values when the real grid is present (in the live check).

**Done when:** the Django tests pass on both stacks, along with Ruff, ESLint and Jest. Live on both stacks, with
the call count reported:
- an AGL area route over the Pilot 2 samples' area gets USGS10m terrain, with the grid cached; its KMZ's DSM is
  compared with COP30 and the Pilot 2 DSM;
- a route across the Canadian border falls back to COP30;
- a waypoint AGL route takes its heights from 3DEP.

README, CHANGELOG and CLAUDE.md say where the grid lives.

## Lidar DSM test (spike): done, accepted as a starting point

Asked 2026-11-18: a 3D view like Dronelink's, showing the heights of buildings and trees. Google's Photorealistic 3D
Tiles are out (cost); USGS 3DEP lidar is free and measures trees and roofs. This test checks
the look before any phase is planned. Area chosen by the user: the oblique AGL sample.

**Branch:** `spike-lidar-dsm`, never merged as it is. If the user keeps the idea, a real phase is planned from what
it shows; if not, `git branch -D spike-lidar-dsm` and this section records why.

**What exists** (checked 2026-11-18):
- The area and waypoint editors already have a 3D view (layers button on the map): MapLibre terrain from AWS
  Terrarium tiles (`Core.TERRAIN_SOURCE`, `planner_core.js`, maxzoom 15) with the basemap draped and a hillshade.
- 3DEP lidar is public as EPT on AWS (`s3-us-west-2.amazonaws.com/usgs-lidar-public/<project>/ept.json`, index in
  `hobuinc/usgs-lidar`'s `boundaries/resources.geojson`: 2284 projects, name, point count, URL; no date field, the
  year is in the name). The sample point is in the county's 2017 project and the older
  a neighbouring county's 2014 project. The 2017 project: EPSG:3857, laszip, with `Classification` and
  `ReturnNumber`.
- PDAL with `readers.ept` and `writers.gdal`: 2.6.2 in `mp-webapp` (4.0.0), 2.3.0 in `mp3-webapp` (3.3.2).

**Steps:**
1. A dev script (`dev/lidar_dsm/`, outside the plugin) runs PDAL in `mp-webapp`: the newest project's EPT over a
   square around the sample point, noise dropped (classes 7 and 18), highest point per cell (`writers.gdal`
   `output_type=max`), about 1 m on the ground, small holes filled. First 200 m, then 1 km; points, MB downloaded
   and time measured for each.
2. The script cuts the DSM into Terrarium PNG tiles (zoom 15 to 18) into the plugin's media folder
   (`mission_planner_data/spike-dsm/`), each blended into the AWS tile under it with a feathered edge, so the
   ground outside the square stays as today.
3. A dev-only route in the plugin's API serves a tile from there, or redirects to AWS's tile when there is none;
   on the branch, `Core.TERRAIN_SOURCE` points at it with maxzoom 18.
4. Look: headless screenshots of the 3D view over the square, with a sample AGL route, on Terrarium (`main`) and on
   the lidar DSM, each basemap; and the DSM compared with the Pilot 2 DSM and COP30 (the shelved branch's
   `dem_compare.py`). The user judges from the screenshots.

**Not in the test:** failure handling, datums (lidar is NAVD88, Terrarium about the same for display; a few
decimeters at the seam), choosing among overlapping projects beyond "newest by name", 3.3.2, tests. A real phase
would plan those.

**Result** (2026-11-18, commit f54b6bd on `spike-lidar-dsm`): accepted by the user as a starting point.
- Look: trees are rounded mounds at their measured height (up to about 30 m here), houses low blocks with soft
  edges, walls and tree sides the photo stretched down. A straight "wall" north of the route is a real tree belt
  (class 5 up to 30 m above ground), not a fault.
- Cost: nothing (no key, no account; the bucket answered unsigned requests, so it is not requester-pays). Bandwidth:
  a 1 km square at full density 214 MB and 15.8 s; read at 1 m (`readers.ept` `resolution`) 101 MB and 7.4 s, the
  surface practically the same (mean -0.04 m, 1st percentile -0.54 m); at 2 m 28 MB and 2.8 s (mean -0.17 m, 1st
  percentile -2.51 m). 12 MB of tiles a km2 (zoom 15 to 18).
- Heights match AWS Terrarium on bare ground (213 to 220 m both): no datum work needed for display.
- Against the DSM in Pilot 2's sample KMZ (ASTER, 30 m cells, shifted by GEOID18's -33.73 m): the lidar's highest
  point a cell is about 14 m above it (median; up to 40 m), its mean about 3.5 m. Pilot 2's terrain misses most of
  the canopy here.
- Learned: above zoom 15, a tile missing from the set cannot be answered with a redirect to AWS's zoom-15 tile
  (MapLibre squeezes the parent into the child's place): it is cut from the parent and enlarged. PDAL 2.3.0 on
  3.3.2 reads the same EPT. `docker exec` without `-i` ignores a heredoc on stdin.

## Phase 6: a lidar surface in the 3D view: done

Builds on the spike (`spike-lidar-dsm`). Planned with the user 2026-11-18.

**Decided with the user (2026-11-18):**
- A **"Lidar surface" toggle** in the 3D view, **on by default**. When on, the first 3D view of a route builds the
  surface around it in the background; after that it is there at once. While it builds, the map shows that it is
  loading.
- Tiles **shared by place**, reused by every route nearby; the settings page shows their size, with a button to
  clear them.
- Lidar read at **1 m** (101 MB a km2 measured, practically the full surface).

**Checked 2026-11-18:**
- Lidar: `s3-us-west-2.amazonaws.com/usgs-lidar-public/<project>/ept.json`, public, unsigned. Which project covers a
  point: `hobuinc/usgs-lidar`'s `boundaries/resources.geojson` (8.7 MB, 2284 projects; regenerated daily by a bot,
  last 2026-11-17; repo not archived, no licence file stated by GitHub's API). Overlapping projects: the newest by
  the year in the name.
- Long work: `app.plugins.worker.run_function_async` (in the plugin guide; Celery, `with_progress`), with
  `TaskView`/`CheckTask`/`GetTaskResult` and the client's `Workers.waitForCompletion`, as WebODM's contours plugin
  does. Present in 3.3.2 and 4.0.0.
- PDAL `readers.ept` and `writers.gdal`: 2.6.2 (4.0.0), 2.3.0 (3.3.2), both read the 2017 project.
- MapLibre 6.16 has `addProtocol` (custom tile loading in the browser).

**Design:**
- **Units of work: zoom-15 web-mercator tiles** (about 0.9 km a side at 41.5 N). A route needs the units its area or
  waypoints touch, plus 200 m around. At most 12 units a request (about 10 km2, about 1.2 GB of lidar); beyond that
  the editor says the area is too large for the lidar surface and keeps the standard terrain.
- **Storage** under `plugins/mission_planner_data/lidar/`: `index/resources.geojson` (the lidar index, refreshed
  when older than 30 days; a failed refresh keeps the old one), `units/<x>_<y>/` with `dsm.tif` (the 1 m DSM of the
  unit and a 40 m overlap), `status.json` (`queued`, `building`, `done`, `none` (no lidar), `failed` with the time
  and a message), and the unit's Terrarium tiles `tiles/<z>/<x>/<y>.png`, zoom 15 to 18.
- **Build** (WebODM's worker, `run_function_async`): pick the newest lidar project covering the unit, PDAL
  `readers.ept` (1 m) then `writers.gdal` max, noise (7, 18) dropped; tiles from that DSM and the built neighbours'
  DSMs, blended into AWS's tile only where no unit's lidar reaches (40 m feather), so seams between built units are
  lidar on both sides. When a unit is built, the border tiles of its built neighbours are made again.
- **API** (`api_mount_points`): `POST lidar/surface` with the route's bounds queues the missing units and answers
  their states; `GET lidar/surface?bounds=...` answers the states (the editor polls it, every 2 s, up to 10
  minutes); `GET lidar/tiles/<z>/<x>/<y>.png` a built tile or 404. Settings page: the size and a clear button
  (admins; a clear waits for no unit to be building).
- **Browser:** a `mplidar://` protocol (`addProtocol`) loads a tile: the lidar tile if built, else AWS's tile (above
  zoom 15 cut from its zoom-15 parent and enlarged in a canvas). The terrain source is reloaded as units finish.
  Layers panel (the layers button on the map), under View: "Lidar surface (US)" checkbox, remembered per browser
  like the basemap. While units build: a small "Building the lidar surface (2 of 4)" bar on the map with a spinner;
  "No lidar here" briefly when the route has none; the reason when a build failed.
- Both editors (area, linear and waypoint routes), 4.0.0 and 3.3.2.

**What can fail, and what happens** (the build runs unattended in the worker):

| Failure | What happens |
|---|---|
| The index cannot be downloaded or read | The old one is kept; with none, the states say "lidar index unavailable" and the standard terrain stays |
| The lidar host is unreachable, slow or answers an error | PDAL is stopped at its deadline (300 s: SIGTERM, then SIGKILL after 10 s); the unit is `failed`, retried by a request after 10 minutes |
| No lidar covers the unit | `none`, remembered; the standard terrain there |
| The lidar covers part of the unit | Holes blended into AWS's terrain |
| The worker restarts during a build | Work happens in a temporary folder renamed into place; a `building` state older than the deadline is taken over |
| Two requests ask for the same unit | A lock file created exclusively; the second only reads the state |
| Disk full | The temporary folder removed, `failed` with the message |
| A saved `status.json` or `dsm.tif` does not read | Set aside (`.bad`), the unit built again |
| The worker is not running | The units stay `queued`; the editor stops polling after 10 minutes and says the surface could not be built |
| AWS Terrarium unreachable (blending, the browser's fallback) | Build: `failed`, retried; browser: the tile is missing, MapLibre shows the ground flat there |

**Tests:** Django: a stand-in `pdal` (a script on `PATH` in the tests) that writes a DSM, fails, hangs or writes a
broken file on request; a fake index; fake AWS tiles. Every failure above has a test that injects it, seen failing
before its handling. Jest: the panel's toggle, the protocol's fallback and cropping, the polling and its deadline,
the loading bar. Live: the oblique AGL sample on both stacks, a route outside the US (no lidar), two overlapping
routes sharing units, the settings page's clear.

**Built** (2026-11-18): as designed. Checked:
- Django on 3.3.2 (515 with WebODM's plugin tests) and 4.0.0; each of 14 failure handlers broken in turn was caught
  by its test (the SIGKILL escalation only once its test checked that PDAL is gone).
- Live on both stacks (`lidar_check.js`): the oblique AGL sample's 2 units built in about 31 s; on again, nothing
  rebuilt; Paris says "No lidar here" (4 units, none); the settings page showed 2 units, 23.3 MB, and cleared them
  (the 8.3 MB index stays until removed by hand).
- Learned: Celery's worker keeps the plugin modules it loaded (restart it after a change); `run_function_async`
  evaluates the function's source, so `build_job` imports `lidar.py` by the module name it is given.

## Phase 7: the ground height under the pointer: done

Asked 2026-11-18 (`new.md`): "a tooltip near the pointer that displays the height of the ground directly underneath
it in the user's desired measurement unit". Builds on Phase 6 (the lidar surface and its `mplidar://` tiles) and the
editors' units setting (metric or imperial, per browser, `mission-planner:units`).

**Decided with the user (2026-11-18):**
- In **2D and 3D**, the same heights in both.
- The **surface above sea level**: the top of whatever is there (tree, roof or ground), as the 3D view shows it.

**Checked 2026-11-18:** MapLibre 6.16's `map.queryTerrainElevation(lngLat)` gives the raised ground's height, but
only while 3D is on (the terrain is off in 2D).

**Design** (built as written, 2026-11-18, except that 3D reads the same tiles as 2D instead of
`queryTerrainElevation`, so the two views always agree):
- 3D: `queryTerrainElevation` at the pointer. 2D: the browser reads the height from the same tiles the 3D view
  uses (`lidar_surface.js`'s loading: the lidar tile where its unit is built, else AWS's), decoded from the
  Terrarium colours at the pointer, at zoom 15 to 18 depending on the map's zoom, a few tiles cached.
- The tooltip says where the height comes from: "lidar" (top of trees and roofs) or "terrain" (the ground's
  shape); in 2D the lidar is only there once a 3D view has built it (Phase 6 builds on the first 3D view).
- Hidden while the pointer is off the map, over a control, or where no tile loads; follows the pointer, throttled.
- Heights are NAVD88 (lidar) or about EGM96 (Terrarium) above sea level, labelled "above sea level"; the editor's
  takeoff height (SRTM, through OpenTopography) can differ by a few meters.
- Tests: Jest for the decoding, the tile and pixel under a point, the units, the hiding; live on both stacks.

**Built** (2026-11-18): Jest 315; Django on both stacks; live on both (`pointer_check.js`): the oblique AGL sample read
216.2 m "Terrain" in 2D before any 3D view, 709 ft in imperial, 224.7 m "Lidar" over a tree in 3D, "Lidar" in 2D
afterwards and in the waypoint editor, hidden off the map. Found on the way: the takeoff height bug at the front of
Up next.

## Bug: the takeoff point's height in the KMZ is ellipsoidal: fixed

Found 2026-11-18 in Phase 7's live check; confirmed the same day.

**Evidence:**
- DJI's WPML reference (dji-sdk/Cloud-API-Doc, `20.template-kml.md`): `wpml:takeOffRefPoint` <latitude, longitude,
  altitude>, "only for reference of route planning. When the aircraft executes the route, the actual takeoff point
  of the aircraft shall prevail, and the height of the ellipsoid shall be used".
- Every Pilot 2 export in `tests/fixtures/dji-kmz` has a `takeOffRefPoint` height 33 to 39 m below the ground's
  sea-level height there (AWS Terrarium at zoom 15): 208.58 vs 244.17 (the area samples), 193.12 vs 232.09 (the POI
  samples), 183.25 vs 215.88 (the oblique AGL sample); the geoid is about -34 m there.

**What is wrong:**
- Export (`wpml.py`): area, linear and waypoint routes without a DSM write `takeoff_ref_point`, whose height is the
  sea-level field, into `takeOffRefPoint` (over a DSM it writes the DSM's ellipsoidal ground: right). The point
  shows in Pilot 2 at the wrong height (+33 m there; the geoid is -107 to +85 m worldwide); the flight's
  heights are not affected (DJI: the actual takeoff point prevails; ASL missions carry both heights per point).
- Import (`kmz_import.py`): area and linear routes not in ASL mode, and waypoint routes in any mode, put Pilot 2's
  ellipsoidal height into "Ground height at the takeoff point (m above sea level)". Switching such a route to ASL is
  safe (ASL needs a fetched ellipsoidal height, which overwrites both). A waypoint route's ASL offset is right (the
  difference of two shifted values).
- Slope and geometric routes are right: their field is labelled and holds the ellipsoidal height.

**Decided with the user (2026-11-18):**
- The sea level to ellipsoid conversion is **local**: the EGM96 geoid grid through PROJ, downloaded once from
  cdn.proj.org into `mission_planner_data/grids/`, kept (no key, no daily limit).
- **Routes already saved stay as they are**; the changelog says to press "Fetch from elevation data" on routes
  imported before the fix.

**Checked 2026-11-18:** `us_nga_egm96_15.tif` on cdn.proj.org: 2,710,815 bytes, sha256 db493027...4e78d, public
domain (PROJ's `us_nga_README.txt`: NGA's EGM96, the 15-minute worldwide grid "that transforms physical heights to
WGS84 ellipsoidal heights"); last modified 2020-01-28. SRTM GL1 (the takeoff height OpenTopography gives) is
EGM96, so the conversion matches the fetched pairs. Phase 5's shelved `geoid.py` (GEOID18) has the download code to
adapt.

**Design:**
- `missions/geoid.py` (new): `ensure_grid()` (download with a deadline, size and sha256 checked, atomic rename, an
  unreadable cached grid set aside) and `undulation(lat, lon)` (PROJ `vgridshift` on the grid): ellipsoidal = sea
  level + undulation.
- Export: the reference point's height is the DSM's ground over a DSM; else, for slope and geometric routes, the
  field as now; else the sea-level field converted. The ellipsoidal height kept from a fetch is not used for it (a
  sea-level height typed afterwards would disagree with it). When the grid cannot be had, the KMZ goes out without
  `takeOffRefPoint` (DJI: not required) and the server log says why.
- Import: area and linear routes not in ASL mode, and waypoint routes: `takeOffRefPoint`'s height becomes the
  ellipsoidal height, and the sea-level field that minus the undulation (waypoint ASL: minus Pilot 2's own offset,
  `ellipsoidHeight - height`, no grid). Without the grid the sea-level field stays blank.

**What can fail, and what happens** (the download runs in a request, first time only):

| Failure | What happens |
|---|---|
| cdn.proj.org unreachable or slow (30 s deadline) | Export without the reference point; import with the sea-level field blank |
| Partial or wrong download (size, sha256) | The temporary file removed; as above |
| Cached grid unreadable | Set aside (`.bad`), downloaded again |
| Two requests download at once | Each its own temporary file; atomic rename |
| Disk full | As unreachable |
| PROJ cannot convert the point | As unreachable |

**Tests:** a small fake grid and fake downloads for `geoid.py` (every failure above injected); the export's and
import's heights with the undulation replaced; golden files updated and their differences read; a check against the
real grid in the live check (the oblique AGL sample: 215.88 - 33.x = about 183.25).

**Fixed** (2026-11-18) as designed, with one change: above sea level (ASL), the export writes the ellipsoidal height
the mission's heights are made with (fetched with the sea-level one, or Pilot 2's own), not the converted one: the
grid's undulation differs from Pilot 2's own offset by 0.3 mm, which broke the exact round trip of the ASL waypoint
sample. Checked: Django 529 (4.0.0) and 534 (3.3.2, with WebODM's plugin tests); 5 new behaviours each caught by a
test when broken; the grid's undulation at the ASL oblique sample equals Pilot 2's own offset to 0.3 mm (-34.2019 vs
-34.2022); live on both stacks, TestAreaRoute.kmz imports with 243.98 m above sea level in the editor and exports
`takeOffRefPoint` 209.778725 (Pilot 2: 209.782061; the form keeps centimetres). The tests read the real grid from
`tests/fixtures/geoid` (2.7 MB, public domain; not in the release zip).


## Phase 8: the flight route at its height in 3D, with waypoint height labels

Asked 2026-11-18 (the user, and `new.md` for the labels): in the 3D view, the planned route drawn in the air at its
flying height, so its clearance over the ground, trees and roofs can be seen; beside each numbered point of a waypoint
route, its height above the surface right under it, in the editor's units. Builds on Phase 6 (the 3D view's lidar
surface), Phase 7 (`pointer_height.js`'s height reader) and the takeoff fix (`missions/geoid.py`).

**Decided with the user (2026-11-18):**
- **AGL routes are drawn above the terrain the aircraft follows**: the route's fetched terrain (COP30, or Pilot 2's
  DSM) where it has one, else the 3D view's surface.
- **Lines down to the surface**: a thin vertical line from each point of a waypoint route, and from the ends of each
  pass of the other routes (not from every photo point).
- **Labels in 2D and 3D**, waypoint routes only (decided earlier: the other routes' photo points would bury the map).
- **A point below the surface under it**: its label turns red and shows the negative height ("-4 m").

**Checked 2026-11-18** (MapLibre 6.16.0's `maplibre-gl.d.ts`):
- Line layers have no height: they are draped on the terrain. A custom layer (`type: "custom"`,
  `renderingMode: "3d"`) draws into the 3D scene with depth; `MercatorCoordinate.fromLngLat(lngLat, altitude)`
  places a point in it, and the docs say to position custom 3D objects with `queryTerrainElevation` (meters above
  sea level, times the exaggeration: 1 here).
- Markers (the waypoint editor's numbered points) have no altitude option: they sit on the terrain.

**Design:**
- **Heights (server):** the plan response gains each line's and point's height above sea level (EGM96) where the
  route knows it:
  - ALT (relative to the takeoff point): the takeoff point's ground above sea level plus the height;
  - ASL: the height;
  - slope and building routes: their ellipsoidal heights minus the undulation (`geoid.py`);
  - area and linear AGL over a DSM: the heights the export gives each waypoint (`dsm_of`, the highest ground within
    the radius plus the height, ellipsoidal) minus the undulation, when the route's cached terrain covers the plan;
    the aircraft flies straight between them, so the line is the flight;
  - waypoint AGL: each point's fetched ground (ellipsoidal) minus the undulation, plus its height.
  Otherwise (an AGL route without terrain yet, ALT without a takeoff height, or no geoid grid) the response says the
  heights are above the surface, and the browser adds the 3D view's surface under each point (lines cut into short
  pieces so that they follow it).
- **Drawing (browser):** a new `public/route_3d.js`, plain ES5 and tested like the others, no new dependency (a
  WebGL library would be hundreds of KB for a few lines): a custom layer drawing the route as wide lines (quads
  turned to face the screen) and its points as discs, at their heights, and the drop lines down to the surface. In
  3D the draped route layers are hidden; 2D is unchanged.
- **Waypoint markers in 3D:** moved up to their point in the air each frame (the marker's offset: the point in the
  air on screen minus the point on the ground), so that they stay clickable and selectable.
- **Labels:** beside each numbered marker, the point's height minus the surface right under it (the Phase 7 reader:
  lidar where built, else the terrain tiles), "38 m" or "125 ft"; red when negative. Updated when a point moves,
  the heights change or the lidar surface is built.
- Heights above sea level are EGM96 (the routes) against NAVD88 (lidar) or about EGM96 (Terrarium): they can differ
  by a meter or so in the US, said in the README.

**Tests:** Django for the heights of each route type and mode (and the fallbacks: no terrain, no takeoff height, no
grid); Jest for the geometry (the heights, the pieces, the drop lines, the marker offsets, the labels and their
colour); live on both stacks: an AGL area route with and without terrain, an ALT waypoint route with a point below a
tree, screenshots in 2D and 3D.

**Built** (2026-11-18) as designed. The plan's `air` is `{reference: "sea" | "surface" | "takeoff", paths, drops}`;
the plan request now carries the route's id (for AGL over its kept terrain), and fetching the terrain plans again.
Checked: Django 562 on each stack (with WebODM's plugin tests); Jest 333; 7 mutations of `route_3d.js` and 5 of
`air.py` each caught. Live on both stacks (`route3d_check.js`): the oblique AGL sample's path above sea level over
Pilot 2's DSM (first point 270.73 m), drawn over the lidar's trees with its lines down to them; the ALT waypoint
route's labels 24, 24, -6 (red), 24 m over the bare terrain (3.3.2), 7, 19, -19 (red), 16 m over the lidar (4.0.0),
and its markers lifted to their points in 3D.


## Phase 12: ASL without the takeoff height

Asked 2026-11-18 (the user), after an area route in ASL showed only its outline in 3D. With "Ground height at the
takeoff point" empty, the server refuses the plan ("The ASL height mode needs the ground height at the takeoff
point", `wpml.settings`, `waypoints.settings`), and the message goes to `#mp-errors` at the bottom of the side panel,
out of view; the stats row shows dashes. (The other cause, ASL area and linear routes drawn at their height alone
above sea level, underground, was fixed on `fix-asl-route-3d`, merged 2026-11-18.)

**Decided with the user (2026-11-18):** hints and an automatic fetch.
- **Hints,** in both editors' side panel: while ASL is picked and the takeoff ground height is empty, a red line
  under "Ground height at the takeoff point" and under the ASL button (area editor: "Waypoint altitude mode";
  waypoint editor: "Height mode"): "ASL needs the ground height at the takeoff point: Fetch from elevation data, or
  type it." Without a takeoff point it says to set the takeoff point first. The hints go as soon as there is a height.
- **Automatic fetch:** picking ASL with a takeoff point set and no height, or setting the takeoff point while ASL is
  picked, runs "Fetch from elevation data" once (one OpenTopography call from the free key's 50 a day). Not for
  slope and building routes, whose takeoff height is ellipsoidal and not needed by ASL.

**Design:** `planner.js` and `waypoint_planner.js`: one `showAslHint()` called where the altitude mode, the takeoff
point or the takeoff height changes; the automatic fetch reuses `fetchElevation()`. A route opened in ASL without a
height shows the hints and is not fetched automatically (opening a route must not spend a call).

**Failures and what happens:** the automatic fetch fails (no key, refused key, rate limit, network): no dialog opens
unasked; the hint line says the fetch failed and why (the server's message, without the key), and the button still
opens the dialog with "Use cached values" as now. A takeoff point moved during the fetch: the answer for the old
point is dropped (the request's point compared with `state.takeoff`).

**Tests:** Jest for the hint's text and when it shows; the automatic fetch with a fake `post` (fired once, not on
opening, not for slope and building, the old point's answer dropped, a failure shown in the hint without a dialog).
Live on both stacks: an area route switched to ASL fetches the height and draws in 3D; the hint without a takeoff
point; the waypoint editor alike; the routes deleted.

**Built** (2026-11-18). Changed from the plan: the hint does not say "or type it": ASL also needs the ellipsoidal
height, which only "Fetch from elevation data" writes, so a typed height alone gets its own hint ("a typed height is
not enough"). Added: the route's cached height (from an earlier fetch) is used for the same takeoff point without a
call. The decision whether to fetch is a pure function tested in Jest (`aslAutoFetch`); the editors' wiring (fetched
once, not on opening, the old point's answer dropped, a failure in the hint without a dialog) is checked live, not in
Jest (the editors need MapLibre). Checked: Jest 375, ESLint and Ruff clean; live on both stacks
(`asl_hint_check.js`, one real OpenTopography call each, other answers faked): the hints without a takeoff point,
the fetch on picking the takeoff point (244 m, the route drawn at 294 m in 3D), a takeoff point moved during a slow
fetch keeps the new point's height, no fetch on opening a waypoint route in ASL, a failed automatic fetch shown in
the hint with no dialog, Fetch from elevation data clearing the hints; routes deleted.


## Phase 20: a loading indicator for the 3D view's elevation (planned and built 2026-11-20)

The request (the user, 2026-11-20): make it obvious when the viewer is still loading and drawing the elevation for
the area.

**Today** (read 2026-11-20). The status bar at the bottom middle of the map (`lidar_surface.js` `createStatusBar`,
`.mp-lidar-status`, in both editors: `planner.js`, `waypoint_planner.js`) speaks only about the lidar units: a
spinner and "Building the lidar surface (2 of 6)" while the server builds them, then a note for 6 s ("No lidar
here: the standard terrain is used", a failure). Once the units are built, or with the lidar surface off, or where
there is no lidar, MapLibre fetches and draws the elevation tiles (source `mp-dem`: the lidar tiles through the
`mplidar://` protocol, or AWS's Terrarium tiles) with no sign: the ground rises piece by piece, and panning or
zooming in 3D loads more.

**The design.**
- In 3D only (2D has no raised ground), in both editors: while `mp-dem` has tiles loading or the map has not drawn
  them, the status bar shows a spinner and "Loading elevation…". MapLibre 6.16.0 says when: `isSourceLoaded("mp-dem")`
  checked as each frame is drawn (`render`) and each tile arrives (`sourcedata`), and `idle` (everything loaded and
  drawn) ends it. Built 2026-11-20: a raster source fires `sourcedataloading` only when its metadata loads, not per
  tile (MapLibre's `raster_tile_source.ts`), so it could not start it; the terrain reads the style's own tile manager
  for the source (`render/terrain.ts`), so `isSourceLoaded` covers the 3D ground. It comes back when panning or zooming loads more, when the lidar surface is switched on
  or off, and when new lidar units replace the tiles.
- It shows only after the loading has lasted 400 ms, so a quick pan from the browser's cache does not flash it.
- One bar, one message: a lidar build in progress keeps its own message (it is the longer wait, and says how far it
  is); otherwise "Loading elevation…"; a note (no lidar here, a failure) shows once the loading is over, for its
  usual few seconds. The bar's state is a small function of the three (build status, loading, note) in
  `lidar_surface.js`, so it is tested without a map.
- Leaving 3D hides it. A tile that fails still ends in `idle` (MapLibre counts it as done), so the message cannot
  stay forever; failures keep falling back as today (`mplidar://` answers AWS's tile).

**Tests.** Jest (`lidar_surface.test.js`, fake timers): the 400 ms delay, the build message winning over loading,
the note after loading, hidden on leaving 3D, shown again on new loading; seen failing first. Live check (both
editors, 3D, the Illinois sample and a place with no lidar): with the tile requests slowed by `page.route`, the
message shows, then hides once the map is drawn (screenshots of both); the console has no new errors. ESLint, Jest.

**Docs.** README (the 3D view's paragraph), CHANGELOG (Unreleased).

**Decided with the user (2026-11-20):** the message goes in the existing status bar, not a separate spinner by the
map's buttons.

## Phase 21: a faster 3D view (requested 2026-11-20, built the same day)

The request (`new.md`, 2026-11-20): "Assess the view rendering code for performance improvements. Right now the
first load is the worst as expected and the loading ui informs the user it's in progress." It builds on Phase 6 (the
lidar surface, `lidar_surface.js`, `lidar.py`), Phase 20 (the "Loading elevation…" message, which also gives the
measurement its end: the map's `idle`) and both editors' `showGround3d` (`planner.js`, `waypoint_planner.js`).

**Measure first:** no candidate below is built until a baseline says it matters. A Playwright script (a live-check
skill script) opens the area editor and a waypoint route at the Illinois sample. It switches to 3D and records the
time to `idle`, the requests (count, bytes, which host) and a CPU profile. Each case is measured cold (fresh profile)
and warm (second entry into 3D), lidar off and on (on over built units). The same script measures each change, before
and after.

**Candidates, found in the code (2026-11-20), not measured:**
- **The ground is reloaded on every switch into 3D:** `showGround3d` removes `mp-dem` and adds it again, so
  MapLibre drops the tiles it already decoded and fetches them again (from the browser's cache where it has them).
  Keeping the source across 2D/3D switches (only `setTerrain` and the hillshade turned off and on) would make
  the second entry immediate. A lidar on/off switch still changes the source.
- **One finished unit reloads every tile:** each unit that finishes building bumps `?v=` in the tile URL
  (`onTilesChanged`, `setTiles`), which reloads every elevation tile of the source, not only the finished unit's.
  Whether MapLibre 6.16.0 can reload some tiles only is to be read in its source.
- **AWS tiles above zoom 15 with the lidar on** (where no unit is built): each zoom-16 to 18 tile fetches its
  zoom-15 parent again and decodes and re-encodes a PNG in the browser (`cropInBrowser`): up to 64 times per
  parent at zoom 18. A small in-memory cache of decoded parents would do this once per parent. With the lidar off,
  the source stops at zoom 15 and MapLibre enlarges the tiles itself.
- **Lidar tiles go through Django,** one request each (`LidarTileView`, `private, max-age=3600`): the time per tile
  on the server is to be measured.
- **The hillshade** (`mp-hillshade`) is computed on the GPU from the same tiles: its share of the frame time is
  to be measured.
- **Loading the ground while in 2D**, so that the first switch into 3D finds it ready: faster, but it downloads
  elevation for users who never open 3D (a decision for the user, below).

**Open decisions** (asked once the baseline is in): which loads matter most (the first entry into 3D, a pan in 3D,
switching back and forth); whether the ground may load in 2D before it is shown; a target, if the user has one.

**Measured (2026-11-20, `perf_3d_check.js`, the Illinois sample's area route, 3 runs, medians; headless Chromium,
WebGL on SwiftShader, so drawing is slower than with a GPU; the machine otherwise idle):**
- First, with SwiftShader's 2D canvas: lidar on, the first switch into 3D took 9 to 14 s, with 7 to 12 s of long
  tasks even from the cache. The profile: `convertToBlob` (12 s), `cropInBrowser` encoding a PNG for each zoom-16 to 18
  tile cut from AWS's zoom 15. With the image handed over as it is, the long tasks went (87 ms), but the map was still
  not drawn for 6 to 9 s: the tiles came within 0.6 s and became ready in batches at 7 and 10 s, MapLibre's worker
  reading the images back from SwiftShader's canvas. Reading a canvas back is slow on SwiftShader, not on a GPU, so
  the script now draws 2D canvases in software (`--disable-accelerated-2d-canvas`) and these first figures overstate
  what a browser with a GPU does.
- With the software canvas, lidar on: the first switch into 3D (empty cache) 2.2 s before, 1.9 s after (1.5 to 2.2 s
  over the runs); after a reload 1.45 s before, 0.99 s after; lidar off 1.5 to 1.8 s and 0.7 to 0.9 s. A pan in 3D
  1.1 to 1.4 s either way. The lidar tiles come from Django in about 20 ms each: not a cause.
- The old and new crops give the same pixels, and the source's own pixels enlarged (checked in Chromium on both
  canvases, three tiles, 2026-11-20).

**Built (this branch):** `lidar_surface.js` hands MapLibre an `ImageBitmap` (MapLibre 6.16.0 takes one from a protocol
as it is: `util/image_request.ts`), and decodes each zoom-15 parent once for the tiles cut from it (the last 16 kept,
`PARENTS`); `pointer_height.js` reads such an image too (a lidar tile that fails falls back on a cut one).

**Tried and dropped:** keeping `mp-dem` across 2D/3D switches. MapLibre reloads a source's tiles whenever the terrain is
turned on (`setTerrain`: `if (this.terrain === null) tileManager.reload()`), so it changed nothing.

**Decided (the user, 2026-11-20):** the slow second switch below is accepted, not looked into further; the ground is not
loaded in 2D before it is shown.

**Left as it is:** the second switch into 3D on the same page takes 2.4 to 2.7 s (lidar off or on), against 0.7 to 0.9 s
after a reload. The main thread is idle, and MapLibre requests most of the tiles only about 1.6 s after the switch:
the wait is inside MapLibre, not found yet. MapLibre also warns that one source for both the hillshade and the
terrain lowers the quality of the drawing (Phase 22).

## Phase 22: a sharper 3D ground (requested 2026-11-20, planned the same day)

The request (`new.md`, 2026-11-20): "Would the buildings, trees and such look less stretched and blurred if instead
of being drawn as round stretched image splotches along the curved height, the image was drawn in 1m square block
increments where the once stretched image can span or repeat across the flat surfaces instead. Somewhat comparable to
how the world looks in minecraft on the exterior. Let's discuss further." It builds on Phase 6 (the lidar surface) and
touches everything that reads the 3D ground: drawing and editing in 3D (Phase 9: clicks land on MapLibre's terrain
through `map.unproject`), collisions (Phases 10 and 11), the pointer's height (Phase 7) and the Pointer tool (Phase 13).

**Why it looks the way it does (read in the code, 2026-11-20):**
- MapLibre draws the terrain as one mesh of 128 x 128 cells per tile (`render/terrain.ts`, `meshSize = 128`), with
  the heights between vertices interpolated. A wall becomes a slope from one vertex to the next. On a zoom-18 tile
  (about 115 m a side at 41 N) a cell is about 0.9 m. Tiles farther from the camera are drawn at lower zooms (3.6 m
  cells at 16, 7 m at 15), where buildings become mounds. Which zooms a typical view draws is not yet measured.
- `make_tiles` (`lidar.py`) resamples the 1 m DSM bilinearly at the zooms finer than 1 m, which softens edges further.
- The basemap is draped from above: a wall has no imagery of its own, so the few pixels at a roof's edge are stretched
  down it. Satellite imagery is also seldom true-ortho: a tall building's roof sits offset from its footprint, so
  blocks and imagery will not line up exactly whatever is drawn (not measured here).

**Options:**
- **A. Steps in the existing terrain** (small): nearest-neighbour in place of bilinear in `make_tiles`, nothing else
  changed. Walls get steeper where the mesh is fine (near the camera), and are still a cell wide; everything
  that reads the ground keeps working. A cheap way to see how much of the blur this removes.
- **B. Blocks as a custom WebGL layer** (large): MapLibre's `CustomLayerInterface` draws boxes built from the 1 m
  DSM (equal neighbours merged), their tops textured with the basemap's tiles, walls with the edge pixel repeated
  or a flat shade, over the bare ground's terrain. The Minecraft look. Own shaders. Clicks, collisions and the
  pointer's height would have to read the blocks, since `map.unproject` only knows MapLibre's terrain. About a
  million cells per square km before merging, so it works against Phase 21.
- **C. `fill-extrusion` of height steps** (medium): MapLibre's own extrusions, one polygon per run of equal height,
  one colour each, sampled from the imagery. No texture: a coloured voxel look, not the imagery. Same picking issue as B.
- **D. Buildings from OpenStreetMap as extrusions** (medium): footprints from OSM, heights from the lidar, crisp
  walls at the real outlines; trees and the ground stay on the terrain. Not blocks, but straight walls where
  they matter most; OSM's footprints are incomplete in places.

**The user's screenshot (2026-11-20)** shows a building whose lidar block is wider than its roof in the imagery,
with grass and trees draped over the block's top edges, so the building looks like it sits on a hill. "I'm looking
for effective sensible ways to reliably improve the definition/visibility of map terrain without killing performance
either." Causes found since, in the code and PDAL's documentation:
- **Every tall thing is widened by about 1.4 m on each side when the DSM is made.** `dsm_pipeline` (`lidar.py`)
  writes the DSM with PDAL's `writers.gdal`, `output_type: max`, without a `radius`. PDAL's documentation
  (pdal.io, `writers.gdal`, read 2026-11-20): every point within `radius` of a cell's centre contributes, and the
  default radius is the resolution times the square root of two; `max` takes the highest of them. So a roof's
  height spreads into every cell whose centre is within 1.41 m of a roof point.
- **Widened again further from the camera:** zooms 15 to 17 are cut from the DSM with `Resampling.max`
  (`make_tiles`), up to one more coarse pixel. Only the 3D view draws those zooms: collisions, the pointer's height
  and the Pointer tool read zoom 18 (`pointer_height.js`, `LIDAR_ZOOM`).
- **Walls are ramps a mesh cell wide** (above), and the imagery is stretched down them.
- **The imagery itself may be off:** satellite roofs lean away from their footprints, more the taller the building,
  and a basemap can be shifted. Not measured.

The widening also works as a safety margin: collisions read the same zoom-18 tiles, so a tighter surface makes a
route that passes close to a building show "stays above" where it now shows a collision.

**Proposed steps, cheapest and surest first (none adds work while the map is drawn):**
1. **Measure the misalignment** at a few buildings of different heights (the Illinois sample and the place in the
   screenshot, if the user gives it): the lidar's edges against OpenStreetMap's outlines and the imagery's roofs.
   An offset the same for every building points to a shift (ours or the basemap's); one that grows with height,
   in one direction, is the imagery's lean.
2. **A tighter DSM:** `radius` set to the half-diagonal of a cell (each point counts in its own cell only; empty
   cells still filled by `window_size`), and zooms 15 to 17 cut without `max`. Built units need building again (a
   version in their saved state, so old units are remade once). Collisions keep a margin of their own, if the user
   wants one, rather than the surface's widening.
3. **Shading that shows the shape:** MapLibre 6.16.0's hillshade has `hillshade-method` (`multidirectional`,
   `igor`, ...) and illumination settings; a stronger, multi-directional shade darkens walls and lights roofs
   whatever the imagery says. And a "Relief" ground in the layers panel: the lidar shaded and coloured by height
   (MapLibre's `color-relief` layer), no imagery, so nothing can be misaligned. The tiles are already loaded.
4. **Blocks (option B), parked:** the most work, and the slowest to draw; reconsidered only if 1-3 fall short.

The screenshot's place: the user's own TestAreaRoute route on the dev stack, which the check may copy (the copy
deleted after; the place is not written in the repo).

**Collisions today** (`route_3d.js` `collide`): the path is cut into 5 m pieces (`STEP`), the surface read at each
piece's end (zoom 18, `pointer_height.js`), and a stretch is "inside" where the path is below it (clearance under 0);
the yellow is 10 m along the path before and after (`LEAD`), not a distance from the surface. No margin, up or
sideways. The 1.4 m widening is the only sideways margin today, and it also covers some of what the 5 m sampling
misses (a chimney or pole narrower than a piece, between two readings).

**A collision margin would need:**
- *Up:* a stretch flagged where the clearance is under the margin, not under 0: one comparison in `collide`, its
  wording ("comes within N m of the surface in 2 places"), and the 2D and 3D counts, which share `collide`.
- *Sideways:* the surface at each reading taken as the highest within the margin around it (the zoom-18 pixels in a
  disc, from tiles the reader already holds, about 1 m apart), with the margin at least half a piece (2.5 m), so
  nothing narrower than a piece slips between readings. More reads per route: to be measured (Phase 21's script),
  for the largest route (20,000 pieces, `MAX_POINTS`).
- *Where the number lives* (the user's choice): a fixed value in the code; or a field in each editor's form, saved
  with the route; or one per browser, like the lidar switch.
- Tests: `collide` with a margin, the sideways disc, the wording; the collision live checks again.

**A "Relief" ground would need:**
- *The layers panel* (`layers_panel.js`, beside the basemaps or under "Lidar surface (US)"): "Imagery / Relief",
  remembered per browser like the lidar switch. Its copy in webodm-geojson is not changed (a new feature, not a fix).
- *The map:* the basemap hidden, a `color-relief` layer on `mp-dem` under the hillshade, and the hillshade stronger
  (`multidirectional`). Colour by height above sea level shows a 20 m building in a 250 m town as a faint step, so
  the colour scale is set from the heights round the route (its lowest and highest, read with the pointer's reader)
  and set again when the route moves. Whether `color-relief` drapes on MapLibre 6.16.0's terrain is to be checked.
- *3D only, or 2D too:* in 2D the elevation tiles are not loaded today (the user's choice: it costs downloads).
- *What is lost while it shows:* the basemap's roads and labels (or a faint basemap kept over it, the user's choice).
- Tests: Jest for the panel and the scale; a live check with screenshots in both editors.

**Step 1, measured (2026-11-20):** the lidar's outline (3 m above the lowest ground within about 30 m) over straight-down
screenshots of the editor's basemap (the place georeferenced from the map's bounds; no other service asked), and unit
8403_12226 built again with a tight radius in a scratch folder.
- **The lidar is where the buildings stand; the imagery leans.** At the user's building (about 25 to 30 m tall) the
  lidar's outline follows the foot of the walls; the imagery shows the roof shifted about 6 m north-west, with the
  south wall in view: the photo was taken off-nadir. Low things (parked cars) line up within about a metre: no
  constant shift. So most of the misalignment is the basemap's, grows with height, and no change to the surface
  removes it; the photo's roof will always land partly beside a tall building's block.
- **The widening, measured:** with each point counted in its own cell (`radius` half a cell's diagonal), 13.2% of the
  unit's cells are more than 2 m lower than today, by up to 36 m (cells beside walls carry the roof's height today),
  1.0 m lower on average; no cell is left empty. The building's outlined area drops 5% (about 1 m round its edge).
- The Illinois sample's place is unbroken forest: no buildings to line up, and no ground between the crowns; not used.

**Steps 2 and 3, built (2026-11-20):** `lidar.py` (`radius` half a cell's diagonal; zooms 15 and 16 cut with
`average`, the others were already bilinear; `SURFACE_VERSION` 2 in each state, a unit built before is built again
once, on its next request: until then it reads as queued, AWS's terrain shown there); `pointer_height.js`
(`bandMaxes`); `route_3d.js` (`collide` with a band, `collisionText` with the margin and units); the "Collision margin"
field in both editors' Advanced settings (`collision_margin`, 2 by default, `Core.collisionMargin`). AGL routes' lidar
terrain (`lidar_terrain.py`) is made from the same DSMs at their highest point per 10 m cell, so it changes little: a
cell beside a wall no longer takes the roof's height from up to 1.4 m away. Live: the user's place rebuilt in about
25 s; the copy of TestAreaRoute "stays above the surface" at 0 m and "comes within 2 m of the surface in 2 places" at 2 m.

**Decided with the user (2026-11-20):**
- **A 2 m collision margin, up and sideways, in a field of each route's form** (both editors), saved with the route;
  routes saved without it get 2 m. Shown in feet in imperial. It changes the editors' check only, not the KMZ.
- **The sideways margin covers the whole path, not only the readings:** each 5 m piece is checked against the
  highest surface within the margin of the piece itself (the zoom-18 pixels in a band round it), since a 2 m circle
  at readings 5 m apart would leave 1 m between circles unchecked. With a margin of 0 the band is the piece's own
  pixels, which also closes today's gap between readings. A piece is flagged where its lowest point is less than the
  margin above that highest surface.
- **Relief in 3D only,** with the photo kept faint over it (its roads and labels still readable).

## Lidar regions: Phases 23-25 (planned 2026-11-20, kept for later)

The request (the user, 2026-11-20): USGS lidar covers only the US; add Canada and the UK, as pluggable regions so
that more can be added. Samples: Tower Bridge (London) for the UK, the Lake Louise area for Canada.

**What is US-specific today** (read 2026-11-20). A lidar unit (a zoom-15 web map tile) ends as `dsm.tif`: 1 m cells
on the unit's EPSG:3857 grid with its overlap, the highest return per cell, heights in the source's sea-level datum.
Everything after that file is the same for any source: `make_tiles` (the 3D view's Terrarium tiles, feathered into
AWS's terrain), the cap, the states, the collisions, the Pointer, `datum_check` (lowest lidar against AWS's terrain,
5 m). The US is in:
- `lidar.py`: `index`/`project_for` (the hobuinc USGS index) and `build_unit` running PDAL on the project's EPT;
- `lidar_terrain.py`: `in_conus` and `geoid.navd88_shift` (GEOID18 and NAD83(2011) to WGS84), and its reasons'
  wording ("no USGS lidar here", "outside the conterminous US");
- text: `lidar_surface.js` (its attribution), `layers_panel.js`, `settings.html`, the editors' help and button titles
  (`planner.html`, `waypoint_planner.html`), `planner_core.js`'s comment, README.

**Vetted 2026-11-20** (primary sources and live requests from this machine):
- **England**: the Environment Agency's LIDAR Composite First Return DSM 1m (2022 composite of 2016-2022 surveys,
  about 99% of England; data.gov.uk). WCS 2.0.1 at
  `https://environment.data.gov.uk/spatialdata/lidar-composite-digital-surface-model-first-return-dsm-1m/wcs`,
  coverage `df4e3ec3-315e-48aa-aaaf-b5ae74d7b2bb__Lidar_Composite_Elevation_FZ_DSM_1m`, Fees NONE, AccessConstraints
  NONE, no key; Open Government Licence (attribution: Environment Agency copyright). GetCoverage with `subset=E(..)`
  and `subset=N(..)` in EPSG:27700 returned a 1 m float32 GeoTIFF, EPSG:27700, nodata -3.4e38, in about 1.3 s for
  200 x 200 m. Tower Bridge (250 x 350 m): every cell set, 1.9 to 70.5 m (the towers). Heights ODN (from training
  knowledge: to check in Phase 24's first step). Older composites (2017, 2020) were retired from the same platform:
  the coverage id may change with a new composite. Not checked: the largest size a request accepts, any rate limit.
- **Canada**: Natural Resources Canada's HRDEM Mosaic 1m (CanElevation), DSM and DTM as cloud-optimized GeoTIFFs in
  the public AWS bucket `canelevation-dem` (ca-central-1), one 500 km tile per item in the STAC API
  `https://datacube.services.geo.ca/pgstac/api` (collection `hrdem-mosaic-1m`; `/stac/api` answers too). The
  collection says: lidar-derived, CGVD2013 heights, reprojected to EPSG:3979, the newest source wins where they
  overlap. Licence OGL-Canada-2.0. Read with rasterio over HTTP (`/vsicurl/`, a window): float32, nodata -32767, a
  200 x 200 m window in 0.8 s. Coverage only where lidar was flown: **Lake Louise, Field, Lake O'Hara, Kicking Horse
  Pass and Banff town have none** (the mosaic's DSM and DTM empty there, and no project in the point-cloud index
  `Index_LiDARprojects_projetslidar` dated 2026-11-19); Canmore (100%), Golden (100%) and Radium (88%) are covered. The
  tiles keep a `coverage.gpkg` and an `extent.geojson`. The point clouds (COPC, bucket
  `canelevation-lidar-point-clouds`) are not needed: the mosaic is already a 1 m DSM.
- **Geoid grids** on cdn.proj.org (where `geoid.py` already downloads EGM96 and GEOID18): `uk_os_OSGM15_GB.tif`
  (1,540,925 bytes, BSD-2-Clause per `uk_os_README.txt`), `uk_os_OSTN15_NTv2_OSGBtoETRS.tif` (3,035,814 bytes; the
  OSGB36 to ETRS89 shift), `ca_nrc_CGG2013an83.tif` (11,031,336 bytes, OGL-Canada per `ca_nrc_README.txt`). Which
  grid PROJ picks for each pipeline is captured in each phase's first step.

**The design.**
- **A region** answers four things: whether it may cover a unit (a coarse box, then its own coverage lookup), how a
  unit's `dsm.tif` is made, how its heights reach the WGS84 ellipsoid (a geoid grid from cdn.proj.org with its size
  and sha256, and the frames), and its credit line. Regions are entries in `mission_planner/regions.json` (read and
  checked like `drones.json`): `id`, `name`, `box`, `kind`, the kind's settings (URLs, coverage id, CRS), `geoid`
  (grid, size, sha256, pipeline), `attribution`.
- **Kinds** are code, written once each: `ept` (the USGS index and PDAL, today's code), `stac-cog` (Canada: a STAC
  search, a window of the COG), `wcs` (England: a GetCoverage of the unit's bounds). The two raster kinds reproject
  into the unit's grid with `Resampling.max`, so a roof or a tree is never lowered by the resampling. A new region
  of an existing kind is an entry and a test with its sample; a new kind of service needs code.
- **Choosing a region**: a unit takes the first region in the file whose box holds the unit's centre and whose
  source has data there; a region with no data passes to the next (the US and Canada overlap at the border). The
  unit's state records its region (`"region": "us"`); a unit built before has none and is read as `us`. Nothing is
  migrated or rebuilt.
- **Heights**: the DSM keeps the region's sea-level datum (as the US keeps NAVD88: the 3D view draws it beside
  AWS's terrain, which is near EGM96). `lidar_terrain.from_units` converts each unit with its own region's pipeline
  (`geoid.shift(region, lons, lats)`, generalising `navd88_shift`), so one route may span units of two regions.
  `in_conus` goes: a route outside every region's box falls back to COP30 with "no lidar region covers this route";
  units without lidar are filled from COP30 as holes are today.
- **The datum check** stays for every region (it catches a source in another datum or in ellipsoidal heights).
- **Text**: reasons name the region ("no Canadian lidar here", "the CGVD2013 grid could not be had"); the 3D
  view's attribution lists the regions whose units it shows; the help texts say "where public lidar covers the route
  (most of the US, England, parts of Canada)". README gets a table of regions, sources, licences and datums.
- **Failures** (the worker builds units unattended; each ends in the unit's state, then COP30 for its cells, as
  today): the service or catalogue unreachable, slow (a deadline per request), answering 4xx/5xx or an error
  document instead of a GeoTIFF; a GeoTIFF that does not read, has an unexpected CRS or is empty (state `none`); the
  STAC search answering no item or an item without a `dsm` asset; the geoid grid not to be had (the terrain says
  why, the 3D view is unaffected); the disk full; a coverage id retired (England: the WCS answers an error, every
  unit `failed` with the message, retried after `RETRY_AFTER`). `regions.json` invalid fails the tests, not the
  server. Each failure gets a test that injects it.
- **Fixtures**: small DSM cuts saved from the live services (Tower Bridge, Canmore, an empty Lake Louise answer),
  a few hundred KB each, kept under `tests/fixtures/lidar/<region>/`. These are public landmarks chosen by the user,
  not places anyone flew: the rule in CLAUDE.md that moves fixtures off real places is about flight samples, and its
  wording is made to say so in Phase 24. No live service is called by the tests (`tests/__init__.py` refuses it, as
  it refuses the lidar builds).

**Phase 23: lidar regions** (US only; no visible change but reasons' wording)
1. `regions.json` with the US entry; `missions/regions.py` (read, check, `region_for(unit)`, the kinds' registry);
   `lidar.build_unit` asks the unit's region to make its DSM and records the region; `ept` kind from today's code;
   `geoid.shift` from `navd88_shift`; `lidar_terrain` per unit's region, `in_conus` replaced by the regions' boxes.
2. Tests: every existing lidar, lidar terrain and geoid test passes unchanged (but the reasons' wording); new tests
   for the registry (an invalid file, overlap order, an old state without region, a region with no data passing to
   the next). Live: `lidar_check.js`, `lidar_terrain_check.js` and `collide2d_check.js` give today's results on the
   Illinois sample, and Paris still says no lidar.
3. Docs: CLAUDE.md (regions.json beside drones.json), README (wording only).

**Phase 24: England** (the `wcs` kind)
1. Capture first: Tower Bridge's GetCoverage for a whole unit with its overlap (the size and time), the largest
   request accepted, the error document for a bad request and for a point outside England (sea off Kent), the PROJ
   pipeline for EPSG:27700+5701 to EPSG:4979 with OSTN15 and OSGM15 (and its result at Tower Bridge against OS's own
   transformation, if a public check point is found), and the offset between ETRS89 and WGS84 there (expected under
   a metre: training knowledge).
2. The `wcs` kind and the England entry; tests with the captured answers (a unit built from Tower Bridge's cut, its
   terrain's heights, the sea answer as `none`, each failure above).
3. Live: an AGL area route over Tower Bridge: the 3D view shows the towers, the terrain says lidar (England), the
   KMZ's DSM; a route over the Channel says no lidar. About 2 OpenTopography calls (COP30 for the fallback).
4. CLAUDE.md's fixture rule says it is about flight samples; README; CHANGELOG (Unreleased).

**Phase 25: Canada** (the `stac-cog` kind)
1. Capture first: the STAC answer and a unit's window at Canmore, the answer at Lake Louise (an item whose window is
   all nodata), the PROJ pipeline for EPSG:3979 + CGVD2013 to EPSG:4979 (CGG2013a, and NAD83(CSRS) to WGS84 at the
   current epoch, as GEOID18's Helmert step), checked against NRCan's GPS-H at a point if it answers.
2. The `stac-cog` kind and the Canada entry (after the US in the file); tests with the captured answers (Canmore's
   unit and terrain, Lake Louise as `none` and COP30 with "no Canadian lidar here", a border unit taken by the US
   where both cover it, each failure above).
3. Live: AGL routes at Canmore (lidar) and Lake Louise (COP30, with the reason); the 3D view's attribution.
4. README, CHANGELOG (Unreleased).

**Decided with the user (2026-11-20).** Canada's samples: Canmore for the lidar (Lake Louise has none), Lake Louise
for the fallback. The UK: England now; Scotland, Wales and Northern Ireland under Later, to be vetted. Not a question
(follows Phase 5): Canada's DSM, not its DTM, as for the US; the bare-earth model would have routes fly closer to
trees than set.

## Phase 19: true distances in area and linear routes (planned 2026-11-19, built 2026-11-20)

The request: found in Phase 18 (the golden files changed when the samples moved east), the user asked for the
correction to be planned (2026-11-19).

**What is wrong.** `planning._survey_plan` (area routes, nadir and oblique passes) and `linear.plan` lay out their
lines in metres of the route's UTM zone (`utm_transformers`). UTM metres are not ground metres: the scale is 0.9996
on the zone's central meridian and grows away from it (pyproj, 2026-11-19: 0.99960 on the meridian, 1.00036 at a
zone's edge at 42N, 1.00098 at its edge on the equator). The spacing between lines, the margin, the linear route's
offsets and the plan's distance, duration and area are off by that much. Measured on a 2 km x 1.5 km area, M4T wide,
60 m (the asked spacing 25.952 m; the spacing on the ellipsoid between the first two lines): the sample B place
25.958 m, a central meridian 25.963 m, a zone edge on the equator 25.928 m. The waypoints move by up to 0.5 m,
1.0 m and 2.4 m there when the frame changes. The photo interval along a line is not affected (the aircraft
measures it in flight). Linear routes also take the zone of their first point, so a line crossing a zone edge is
laid out in the zone it starts in. Slope and geometric routes already use a local azimuthal equidistant frame
(`slope.face`, `geometric.frame`) and stay as they are.

**The design.**
- `planning.local_transformers(lon, lat)`: an azimuthal equidistant projection (`+proj=aeqd`, WGS84) centred on the
  given point, the frame slope and geometric routes use. Its scale is 1 at the centre and off by under 1e-7 at 2 km
  (the frame's distortion grows with the square of the distance). It replaces `utm_transformers` and `utm_epsg`.
- Area routes centre it on the polygon's middle (as the zone is picked today). Grid north is true north at the centre,
  so `grid_convergence` goes (the direction is used as it is); a line's bearing away from the centre then differs
  from the asked one by the convergence of meridians over that distance (about 0.01 degree at 1 km at 42N), the same
  as what UTM's single convergence value left.
- Linear routes centre it on the middle of the centre line's extent, not its first point.
- The plan's lengths (distance, duration, transitions) are measured in that frame, which is now true to the
  millimetre at these sizes.
- Saved routes keep their settings; their lines are planned again when they are opened or exported, so they move by
  up to the waypoint shifts above against a KMZ downloaded before. Imported Pilot 2 routes are planned again too
  (as now). Nothing is migrated.

**Tests.** First, a failing test in `test_mission_planning` and `test_mission_linear`: the spacing between two lines,
measured on the ellipsoid (`pyproj.Geod`), equals the asked spacing within 1 mm for an area at a zone's edge on the
equator and on a central meridian (today 24 mm and 11 mm off). The tests' helpers that measure in UTM
(`test_mission_planning.to_metric`) measure on the ellipsoid instead; the convergence test is replaced by one that a
due-north direction gives lines along the meridian through the centre. Golden files regenerated
(`MP_UPDATE_GOLDEN=1`), their differences read before committing: only coordinates in the last digits and the
distances and durations they change. Then every module, Jest, ESLint, Ruff; a live check that an area route and a
linear route still plan, show and download (the plan's numbers in the editor's summary).

**Docs.** README (if it says how lines are laid out), CHANGELOG (Unreleased: the spacing between lines is now the
asked one on the ground), the Phase 18 Done entry's aside on UTM.

No decisions are open: the frame and its centre follow the slope and geometric routes.

## Phase 18: ready to publish (planned and built 2026-11-19)

The request: a secrets review before the user makes the repo public. The review (2026-11-19) found no secret in the
files or in any of the 154 commits (patterns for keys, tokens, private keys, passwords in URLs; the OpenTopography
key's own value appears nowhere; every commit is under the user's GitHub noreply address; the only password-like
strings are WebODM's test user `test1234` and a made-up key `0123456789abcdef` x2). It found personal data:
- **An email address** as `<wpml:author>` in 30 Pilot 2 sample KMZs (`tests/fixtures/dji-kmz`), likely the user's
  DJI account.
- **The user's real places:** nearly every sample's takeoff point is within metres of one spot,
  the oblique AGL sample (`m4t-testkmz-oblique-AGL.kmz`, with Pilot 2's DSM) is at another;
  their coordinates are also in the golden files, about 20 Django and Jest test modules, 10 live-check scripts,
  `README.md`, `CHANGELOG.md` and this file, with place names (the county's lidar project name, the DSM's tile name).
  The two Smart3D samples carry a point cloud, 3D tiles and a mesh of the place.

Decided with the user (2026-11-19):
- **Move the samples:** first planned as public land Claude picks. Built otherwise, with the user (2026-11-19): the
  tests compare with Pilot 2's waypoints to the centimetre and its sea-level and ellipsoidal heights to the millimetre,
  so a place can only move due east or west (a degree of longitude is as long on the same latitude), to the one
  longitude where EGM96 matches at its takeoff point (found with the plugin's geoid code). Neither spot is public
  land (rural private land, fictional flights); both have USGS lidar (checked against the index) and GEOID18. Each of
  the two places has its own fixed offset, applied to every coordinate that sits beside a latitude (so headings in
  the same number range are left alone): the KMZs' template and waylines, the DSM GeoTIFF's transform, the golden
  files, the tests' constants, the live-check scripts. Heights stay as they are, so the tests stay self-consistent
  (the moved DSM no longer matches the real ground there: the live checks that compared it with COP30 or the lidar
  compare moved data, and say so). `geoid18_ngs.json`'s reference heights are fetched again from NGS at the moved
  points; values that depend on the place (geoid undulations, lidar unit numbers, tile names) are worked out again.
- **The author email:** each sample's `<wpml:author>` becomes a neutral placeholder.
- **The Smart3D samples:** their `wpmz/res/ply` (point cloud, 3D tiles, mesh) is removed; template and waylines kept
  (moved). The test that refuses Smart 3D reads only those.
- **Words:** the place names and the old coordinates leave the code, tests, skills, README and CHANGELOG ("the oblique
  AGL sample", not the county); this file keeps its history but with the places and dataset names removed.
- **A fresh public history:** once the above is merged and checked, `main` becomes one new commit holding the
  current tree, force-pushed to GitHub (the user's choice, allowed for this task by the repo's CLAUDE.md); the old
  history stays only in the local clone, as the unpushed branch `private-history`. GitHub can keep serving replaced
  commits by hash from cached views (its "Removing sensitive data" page, read 2026-11-19), so before the repo is made
  public the user asks GitHub Support to garbage-collect it and drop cached views. The user makes it public.
- The repo's CLAUDE.md stops calling the repo private because of the fixtures.

Steps: the moved fixtures written by a script kept outside the repo (it holds the offsets, which would give the real
places back), the KMZs
rewritten entry by entry (same names and order); tests and golden files updated (`MP_UPDATE_GOLDEN=1` only after
reading the diffs); a scan of the whole tree, KMZs and rasters included, for the old coordinates (to 2 decimals),
the email, the place and dataset names; the full Django suite, Jest, ESLint, Ruff; live: an import of the moved
samples, the lidar check at the new place. Then the fresh commit, the scan run on it, the force-push.

**Done when:** the scan finds none of the old places, the email or the names, in the tree or in the new history;
every check passes; the user has the steps for GitHub Support and the visibility switch.

## Phase 17: the name DJI Mission Planner (planned and built 2026-11-19)

The request (`new.md`, 2026-11-19): rename the Mission Planner to DJI Mission Planner, and the repo
webodm-mission-planner to webodm-dji-mission-planner.

Decided with the user (2026-11-19):
- **The shown name only.** "DJI Mission Planner" wherever a person reads the name: `manifest.json` (`name`,
  `homepage`), WebODM's menu entry and the plugin's page titles and headings (`plugin.py`, `templates/`), messages
  that name the plugin, the KML's creator text (`missions/kml.py`), `README.md`, `CHANGELOG.md`, `CLAUDE.md` and the
  skills. The internal name `mission_planner` stays: the folder (WebODM's plugin name), the URLs
  (`/plugins/mission_planner/`, `/api/plugins/mission_planner/`), the route keys (`mission_planner::route:<id>`), the
  data folder (`mission_planner_data`), the test labels. WebODM gives a plugin no migrations, and renaming these would
  orphan every saved route and terrain.
- **The repo:** the user renames it on GitHub (which redirects the old URL); Claude then points `origin` at the new
  URL and changes the repo name in `package.json`, `package-lock.json`, the docs and the skills.
- **The dev stack keeps its volumes:** `dev/webodm.sh` pins the Docker project name `webodm-mission-planner` (volumes
  `webodm-mission-planner_appmedia`, `_dbdata`, and the `mp-*` containers unchanged), so the stack and its routes carry on.

Not changed: the local checkout's folder (renaming it would move Claude's project memory; the user may do it later).
LuxODM's export format name (`luxodm-routes`) is not the plugin's name and stays.

**Done when:** a search finds "Mission Planner" only after "DJI" (or in history: CHANGELOG entries, Done items), and
`webodm-mission-planner` only where the dev stack's pinned name or old history needs it; the Django tests, Jest,
ESLint and Ruff pass; live on :8009 the menu entry, the routes list, each editor and the settings page show the new
name, and routes 39 and 54 open as before.

## Phase 16: load limits and cleanups from the code review (planned and built 2026-11-19)

**Built** (2026-11-19) as designed below, but for 18: each unit keeps its own size (`usage.json`, written with its
tiles) instead of one shared running total, which the web process and the worker would both write. `usage()` adds
them up (a unit built before is walked once); `evict()` reads them. A unit's use is the time of its `used` file,
touched by `request` (the editors and the lidar terrain both ask through it). An evicted unit's built neighbours get
their tiles made again (faded at the edge it leaves). Live check on :8009: the settings page states the cap; a 3 km
DJI Fly square at 40 m (64,800 points) is refused in about 1 s; a 500 m one downloads as 10 missions. Unattended
(the worker's eviction): a unit queued meanwhile is kept (the claim's lock, state read again), a unit removed by
another eviction is skipped, a failed eviction is logged and the next build tries again, a failed tile remake leaves
a seam only.

Findings 15-21 of the code review (below), checked in the code and measured on the 4.0.0 stack (2026-11-19) first:
- **Area size is not the load (finding 15):** planning and writing a Pilot 2 area of 10 km by 10 km takes 0.04 s at
  40 m and under 3 s at the minimum 2 m (11,587 lines); a 25 km corridor with 5 km extends, 0.04 s. No area or extend
  cap is added.
- **What is slow:** the DJI Fly writer, one point per photo (a 3 km square at 40 m: 328 missions, 5.6 s); and
  `BlockHeightsView.sample_points`, which spaces its grid by the outline's area but walks the outline's bounding box
  (a long thin diagonal outline: millions of cells tested in Python).
- **Lidar on disk (finding 16):** a unit is 7 to 9 MB (4 units, 34 MB, plus an 8.4 MB index on :8009); each route opened
  asks for up to 12; only the admin's "clear" removes them.

Decided with the user (2026-11-19):
- **Lidar: any user's editor still builds; the lidar folder is capped at 5 GB** (fixed in the code). Past the cap the
  units least recently used are removed (never one queued or building); a unit's use is recorded when a route asks for
  it (`lidar.request`).
- **A DJI Fly download holds at most 20 missions** (3,981 photo points); a larger route is refused, saying to split the
  area or fly higher. Pilot 2 routes keep no size cap.

Design (Claude's, technical):
- 15: `sample_points` spaces the grid by the bounding box's area, so it never tests more than MAX_POINTS cells.
- 16: as decided; `lidar.evict()` after each build, oldest `used` first, using a running total instead of walking.
- 17: `tasks_covering` reads only the columns it needs (`only`) and the tasks with a DSM asset.
- 18: `lidar.usage()` reads a small `usage.json` the builds, evictions and clears keep up to date, instead of walking
  every tile; rebuilt by a walk when missing or unreadable.
- 19: `save_terrain` removes every file in the route's terrain folder but the one it saved, so two fetches at once
  leave none behind.
- 20: `speed_of` and the settings checks the five writers share move to one place (`wpml`); each module's KMZ writing
  stays its own, as each matches its own Pilot 2 sample.
- 21: the import reads the template once and hands it on (`read_kmz_route` returns what `read_kmz_dsm` needs).

Each with a test seen failing first where it changes behaviour (the cap, the eviction, the 20 missions, the orphan,
the grid bound); the cleanups covered by the existing tests and the golden files.

## Code review findings (2026-11-19)

A review of `mission_planner/` (the `code-review` skill, high effort) for bugs and UI breakdowns. Findings 1-14 are
fixed (branch `fix-review-1-14`), each with a test seen failing first, except 13 (not a bug). 15-21 are fixed in
Phase 16.

**How 1-14 were fixed:** the takeoff-elevation cache is a field of the route beside its settings (`routes.Route.
takeoff_elevation`, read from the settings for routes saved before) and the fetch saves only it; both editors save
through `planner_core.createSaver`, which keeps an edit made during a save unsaved; `planner.js` queues an export
behind a running terrain fetch, `waypoint_planner.js` behind a running ground-height fetch; `RouteDetailView` applies
only the fields sent and refuses a type change; `routes_list.js` mirrors `copied_settings` and describes waypoint and
linear imports, and reports a refused delete; `wpml.auto_speed` (shared by the four modules) never rounds to 0;
`linear.offset_line` bevels inside turns past 150 degrees and caps the outside corner there; `wpml.known` checks a
name is text before looking it up (every settings module, and the model in the API); a point needs lat and lon;
`iso_time` catches Django's ValueError; `_point_elevation` refuses a body that is not an object and masks the key
in OpenTopography's message; `lidar.project_for` picks the newest of the projects covering at least 95% of what the
best one covers.

**Lose the user's work or show wrong information:**
1. `api.py` (elevation): the takeoff-elevation cache lives in `route.settings`, so every Save drops it ("Use cached
   values" gone), and an elevation fetch still running when Save is clicked writes the old settings back over the save.
2. `planner.js` `save()` (and `waypoint_planner.js`): edits made while a Save is in flight are marked as saved; the
   leave prompt no longer catches them.
3. `api.py` `RouteDetailView.update`: a PATCH can change `route_type` (breaking the editor), and a PUT fills in the
   serializer's defaults (type area, model m4t, empty settings).
4. `routes_list.js` `copyNote`: says the height changes on a copy to another model, where the server keeps it (waypoint
   and single-line linear routes).
5. `routes_list.js` `importSummary`: describes imported waypoint and linear routes as Ortho, AGL, with overlaps.
6. `planner.js` `download()`: on a 409 (terrain needed) while a terrain fetch is running, the export is never retried
   and nothing is said.
7. `routes_list.js` `deleteRoute`: a refused or failed delete is silent.

**Server errors (500) instead of a message:**
8. `speed_of` (`wpml.py`, `linear.py`, `slope.py`, `geometric.py`): 0 m/s below 0.1 m/s (low height, high overlap,
   thermal), then a division by zero.
9. `linear.py` `offset_line`: a line that doubles back divides by zero; very sharp turns put waypoints far off.
10. `luxodm_import.py` `iso_time`: a well-formed but impossible date raises instead of refusing the file.
11. `api.py`: malformed JSON (a list as the model, a point without lat, mode fields not text) raises TypeError.
12. `elevation.py` `_point_elevation`: a JSON body that is not an object raises; its message is not passed through
    `without_key` (the repo's rule for OpenTopography's messages).

**Wrong output:**
13. **Not a bug** (checked 2026-11-19): `slope.py` `geoid_undulation` reads `/usr/share/proj/egm96_15.gtx`, which
    both WebODM images have; it gives -34.2 m at the samples, in degrees as passed.
14. `lidar.py` `project_for`: the newest project wins even when it covers only a corner of the unit, which is then
    built almost empty though full lidar exists.

**Load and resources:**
15. `planning.py`, `linear.py`: no upper bound on the area or the extends; `BlockHeightsView` tests every cell of the
    outline's box in Python. One request can tie up a worker.
16. `api.py` `lidar/surface`: any logged-in user can queue lidar builds anywhere; nothing is evicted.
17. `api.py` `tasks_covering`: parses every task's extent on each request.
18. `lidar.py` `usage()`: walks every tile file on each load of the settings page.
19. `routes.py` `save_terrain`: two fetches at once leave an orphaned GeoTIFF.

**Cleanups:**
20. `speed_of`, the settings checks and the KMZ writing are copied in five modules (why finding 8 is in four places).
21. `RouteImportView` parses the KMZ's template twice.

## Phase 15: more drones, generically, through KMZ/WPML

Asked 2026-11-19 (the user): discuss opening the model support up generically, for drones that fly KMZ/WPML missions;
the user knows of a number of open-source projects that may help add more drones, or drones in general. Planned with
the user before anything is built.

**What exists** (checked in the code 2026-11-19):
- **Two models, hard-coded in four places:** `routes.AIRCRAFT_MODELS` (the choice and its label), `missions/cameras.py`
  (`CAMERAS_BY_MODEL`: each camera's focal length, sensor size and pixels, measured from real images and checked
  against Pilot 2's spacing), `missions/wpml.py` (`AIRCRAFT`: the drone, payload and payload sub enum values Pilot 2
  writes, by the cameras chosen), and `missions/kmz_import.py` (`read_lenses`: a file's model from those enums).
- **The file is Pilot 2's dialect of WPML 1.0.6:** every field and its order was matched against Pilot 2's own exports
  (the fixtures in `tests/fixtures/dji-kmz/`), including what only Pilot 2 needs (the embedded DSM, `startPositionRef`,
  the lens names `visable` and `ir`).
- **The browser** takes the cameras and their GSDs from the API (`gsd_per_m`), and the forms' lens choice from the
  model (`planner_core.js`, the editors' templates).

**To discuss:**
- **Which drones**, and how they fly the file:
  - other DJI enterprise drones flown with Pilot 2: the same dialect, new enum values and cameras;
  - DJI drones flown by other apps;
  - non-DJI drones whose apps read WPML or KMZ.
  Each needs a sample mission exported by its own app, as the M4T and M4E had, before its output is trusted.
- **Generic cameras:** a camera defined by its numbers (focal length, sensor, pixels) rather than a fixed list, so
  that a drone without a profile can still be planned. Whether a user can add one in the UI, or only in the code.
- **What a "generic" export means:** plain WPML without Pilot 2's extras, and what the planner then gives up
  (the embedded terrain, Pilot 2's lens choice).
- **The open-source projects:** which ones the user has in mind. Each is vetted before it goes into the plan (its
  repo, releases, maintainers, licence, what it pulls in, whether its data, such as DJI's enum values or camera
  sizes, comes from primary sources). Building our own, small and in the repo, is weighed for each.
- **Primary sources:** DJI's published WPML specification (part of its Cloud API documentation) for the enum values
  and fields, checked when this phase is planned.

**Drones chosen 2026-11-19 (the user):**
- Pilot 2: Mavic 3 Enterprise (M3E, M3T, M3M), Matrice 4D and 4TD, M30 and M30T, M3D and M3TD, M300 RTK and M350 RTK
  (with their payloads H20, H20T, H20N, H30, H30T).
- DJI Fly: all 8 of FlyPath's (Mini 3 Pro, Mini 4 Pro, Mini 5 Pro, Air 3, Air 3S, Mavic 3 Classic, Mavic 4 Pro,
  Lito X1).

**Proposed parts, each its own branch and merge, in this order:**
- **15a, one drone registry, no change in behaviour:** one data file (models, the app each flies with, enums,
  cameras, speeds, which route types and features each supports) replacing `AIRCRAFT_MODELS`, `CAMERAS_BY_MODEL`,
  `wpml.AIRCRAFT` and `kmz_import.read_lenses`'s lookup; the M4T and M4E files byte-for-byte as before (the golden
  files). The experimental warning widened, with "at your own risk".
- **15b, Pilot 2 drones with built-in cameras:** M3E, M3T, M3M, M4D, M4TD, M30, M30T, M3D, M3TD. Enums from DJI's spec,
  cameras from DJI's spec pages. To find out per model from DJI's documents: the lens names in the file (`wide`,
  `zoom`, `ir`, `narrow_band`), and whether its Pilot 2 follows an embedded DSM and real-time terrain (where unknown,
  the plugin offers what DJI documents for it).
- **15c, M300 and M350 with a payload choice:** the payload picked in the forms beside the model, its camera and lens
  names from DJI's spec.
- **15d, DJI Fly:** the second writer (namespace 1.0.2, waypoints only, heights from takeoff, terrain as heights per
  waypoint, routes split at the waypoint limit), the 8 drones with FlyPath's values cross-checked against DJI's spec
  pages, and the README's steps to put a mission on the controller. Which route types DJI Fly can take (area, linear,
  waypoint at least; slope and geometric to check) settled when this part is planned in detail.
- **15e, KML:** importing areas, lines and points from KML or KMZ into a new route, and exporting a route as plain KML.

Each part is checked as now (the tests on both stacks, the live check); a new model's file is checked against DJI's
specification and FlyPath's writer, since no file from its app is at hand.

**The two projects the user named** (reviewed 2026-11-19 from clones of their repos, GitHub's API and PyPI; useful
ideas only, not a source of truth: neither project's compatibility can be vouched for, and each value below is
checked against a file from the drone's own app before we use it):

| | FlyPath (github.com/dronnix-io/FlyPath) | pierotofy/webodm-mission-planner |
|---|---|---|
| What it is | QGIS plugin, version 5.1.0 | WebODM plugin, version 0.6.1, `experimental`, WebODM 4.0.0 or later only |
| Drones offered | 8 DJI Fly consumer drones: Mini 3 Pro, Mini 4 Pro, Mini 5 Pro, Air 3, Air 3S, Mavic 3 Classic, Mavic 4 Pro, Lito X1 | The same 8 (filters FlyPath's list to consumer drones) |
| Verified on hardware (its own README) | Mini 4 Pro (a mission dump from the RC2); Mini 3 Pro and Mini 5 Pro "community-verified"; the other 5 "field-test reports wanted" | Nothing stated |
| Enterprise (Pilot 2) | One entry, Matrice 4E, hidden (`available: false`), "UNVERIFIED - estimated values" | None |
| How a drone is defined | One JSON file (`profiles/drones.json` in the FlyPath engine): per drone, `category` (consumer or enterprise), `app`, `drone_enum`/`drone_sub_enum`, speeds, battery minutes, signal range, the camera (sensor mm, focal mm, pixels, shot interval, payload enums), and free-text `verified` and `notes`; validated at load | Reads the same JSON file, vendored |
| File it writes | Consumer: WPML namespace `uav.com/wpmz/1.0.2`, `templateType` waypoint, heights relative to takeoff, no payload block. Enterprise: `dji.com/wpmz/1.0.6` mapping2d | Consumer only, as FlyPath |
| Terrain | AWS Terrarium tiles (about 30 m, bare earth), per-waypoint heights; no embedded DSM | Online elevation, the same approach |
| KML | Reads QGIS layers (so any format QGIS opens) | Imports GeoJSON, KML and KMZ boundaries through GDAL/OGR (`planner.import_geometry`) |
| Sending to the controller | Replaces an existing DJI Fly mission on a DJI RC2 over USB | The same, only when WebODM runs natively on Windows with the browser on that machine |
| Licence | GPL-3.0; the engine is Apache-2.0 | AGPL-3.0; the vendored engine Apache-2.0 |
| Activity | First commit 2026-04-12, 329 commits, 4 authors (305 by one), last 2026-11-17, 87 stars, 3 open issues, issues answered | 2 commits, both 2026-11-15, one author (WebODM's creator), 2 stars |
| Engine | `dronnix-io/flypath_engine`, tag v2.1.0, pinned by commit; not on PyPI (404), although Piero's README links a PyPI page; 0 stars | Vendored copy |

**What the review shows:**
- **The drone enums are mostly guesses.** 6 of the 8 consumer drones carry `drone_enum` 68, the Mini 4 Pro's value,
  "assumed" until someone reports a failure; the Mini 3 Pro has 97. FlyPath's estimated M4E values agree with ours
  (99/0, payload 88), which came from Pilot 2's exports. DJI's published enum table covers enterprise drones; the
  consumer values are not documented there as far as these projects show. Not checked by us yet.
- **The camera values are estimates too** (several are copied from another drone, per their own notes). Ours are
  measured from real images and Pilot 2's spacing, a higher bar we keep.
- **DJI Fly reads a different dialect** (namespace 1.0.2, no payload or lens, heights relative to takeoff, no
  embedded terrain). Supporting DJI Fly drones means a second writer, not only new enums. FlyPath's notes from the
  field are worth keeping: DJI Fly reshuffles straight-leg paths when a mission is saved again on the controller
  (its issue #13; curved paths survive); the gimbal needs about 3 s to reach nadir before the first photo; DJI Fly
  imports a mission only by replacing one already on the controller.
- **The registry shape is a good model** for our step 2: one validated data file per drone and camera, a category
  that picks the writer, a `verified` field shown to the user, and a flag that hides an unverified drone.
- **Neither project has non-DJI drones** or a generic camera.
- **Neither is a dependency candidate**: their code is a QGIS plugin and a WebODM plugin with their own route models
  (GPL and AGPL); the engine is Apache-2.0 but has no release on PyPI, no users we can see and writes FlyPath's own
  planning, not our Pilot 2 dialect. Ideas and data only, each value checked against a file from the drone's app;
  building our own registry is the option.

**KML** (the user, 2026-11-19: "We'll need to support KML as well"): today the planner reads only DJI KMZ missions
and LuxODM's export; it imports no plain KML. To settle: importing area, line and point boundaries from a KML or
KMZ (Google Earth, other planners), exporting the route as plain KML (for other apps or viewers), or both.
Decided 2026-11-19 (the user): **both**, import and export.

**Decided 2026-11-19 (the user):**
- **Drones first:** DJI enterprise drones flown with Pilot 2, and DJI Fly consumer drones.
- **Testing:** the user can test flight files only on the Matrice 4T and 4E. Every other model's output can be
  checked against sample files (from its owners or the projects above) but not loaded or flown by us.
- **Unverified models are shown like the others, with no "unverified" mark:** the whole plugin is experimental and
  carries the warning. Today the warning names Pilot 2 only (README line 9, `manifest.json`, the notes in
  `planner.html` and `waypoint_planner.html`: "check every mission in Pilot 2 ... before flying"); this phase widens it
  to every app it writes for (DJI Fly too) and says plainly that use is at the user's own risk.
- **No typed-in cameras** (dropped: unnecessary). Proposed step 3 is gone.
- **No sample files:** the values come from FlyPath and other sources good enough to trust, best first: DJI's own
  documents, then DJI's spec pages, then FlyPath.

**Sources checked 2026-11-19:**
- **DJI's WPML specification** (`github.com/dji-sdk/Cloud-API-Doc`, `docs/en/60.api-reference/00.dji-wpml/40.common-element.md`,
  last commit 2024-11-07): `droneEnumValue` 89 M350 RTK, 60 M300 RTK, 67 M30/M30T (sub 0/1), 77 M3E/M3T/M3M (sub
  0/1/2), 91 M3D/M3TD (sub 0/1); `payloadEnumValue` 42 H20, 43 H20T, 52 M30, 53 M30T, 61 H20N, 66 Mavic 3E camera,
  67 Mavic 3T camera, 68 Mavic 3M camera, 80 Matrice 3D camera, 81 Matrice 3TD camera, 82 H30, 83 H30T, 65534 PSDK.
  The live site (developer.dji.com, product support page, seen only in a search result: the page needs JavaScript)
  adds the Matrice 4 series: 99 (M4E/M4T), 100 (M4D/M4TD), matching our Pilot 2 files. **No consumer drone is in
  DJI's documents**: their enums come only from FlyPath (one verified, the Mini 4 Pro, 68).
- **Cameras:** DJI's spec page for each model (sensor size, focal length, pixels), with FlyPath's numbers as a cross
  check.

**What DJI Fly consumer drones need** (from FlyPath's code and notes, not yet checked against a DJI Fly file of ours):
- **A second writer:** WPML namespace `uav.com/wpmz/1.0.2`, `templateType` waypoint only. An area or linear route is
  written as its waypoints with photo actions, not as Pilot 2's mapping template that the app rebuilds.
- **No lens choice:** the file names no payload; the drone uses the camera active at the time.
- **Heights relative to takeoff only:** no embedded DSM and no real-time follow. Terrain follow becomes a height per
  waypoint from our terrain minus the takeoff height, so the route is densified where the ground changes, within a
  waypoint limit per mission (the limit to be found; longer routes split into several files).
- **Getting it onto the controller:** DJI Fly imports no file; a mission made on the controller is replaced by ours
  (copied over USB into its waypoint folder). The README would explain this.
- **Per model:** enum values and camera numbers, unverified for all but the Mini 4 Pro by FlyPath's own account.

### Phase 15b: Pilot 2 drones with built-in cameras (planned 2026-11-19)

The user asked to carry on through Phase 15 without stopping unless a decision is theirs (2026-11-19).
Decided (the user, 2026-11-19): **the Mavic 3M plans with its RGB camera only**; multispectral (`narrow_band`, its
payload sub value unconfirmed by DJI) goes to Later until a real M3M file or a DJI source confirms it.

**Sources** (researched 2026-11-19; DJI first, FlyPath has none of these models):
- Enums: DJI's WPML spec (Cloud-API-Doc, commit 4ec6b0c, 2024-11-07, `40.common-element.md`) and the live Product
  Support page (developer.dji.com/doc/cloud-api-tutorial/en/overview/product-support.html), which also confirms our
  M4E 99/0/88 and M4T 99/1/89 and adds M4D 100/0 payload 98, M4TD 100/1 payload 99; DJI's Cloud API demo
  (DeviceEnum.java) agrees.

  | Model | drone | payload |
  |---|---|---|
  | Mavic 3E / 3T / 3M | 77 / 0, 1, 2 | 66, 67, 68 |
  | Matrice 30 / 30T | 67 / 0, 1 | 52, 53 |
  | Matrice 3D / 3TD | 91 / 0, 1 | 80, 81 |
  | Matrice 4D / 4TD | 100 / 0, 1 | 98, 99 |
- `payloadSubEnumValue` is not documented by DJI (its demo reads it as the payload's sub type, 0 for built-in cameras);
  Pilot 2 wrote 0 (wide) and 2 (wide + thermal) for the M4T. The same values are used for every model.
- Lens names: DJI's Chinese spec and real files write `visable` (the English spec says "visible"); the live spec says
  the M4D/M4TD take only `visable` and `ir`. Every model writes `visable` and `ir`, as the M4T.
- Cameras (DJI spec pages, user manuals and FAQs; where DJI gives only the 35 mm equivalent, the focal length comes
  from it and the sensor's nominal size):
  - 4/3" 20 MP, 5280x3956, 3.3 um (M3E, M3M RGB, M3D): 12.29 mm (DJI, M3M manual and FAQ); agrees with DJI's M3M
    GSD H/37.2 cm/px.
  - M4D: the M4E's measured camera (DJI lists the same sensor, pixels and 24 mm equivalent).
  - M4TD: the M4T's measured wide and thermal cameras (the same 1/1.3" 48 MP wide and 53 mm-equivalent 640x512
    thermal).
  - 1/2" 48 MP, 8000x6000 (M3T wide): 6.4x4.8 mm, 4.44 mm (24 mm equivalent).
  - 1/2" 12 MP, 4000x3000 (M30 wide): 6.4x4.8 mm, 4.5 mm (DJI).
  - 1/1.32" 48 MP, 8064x6048 (M3TD wide): 9.70x7.27 mm, 6.72 mm (24 mm equivalent).
  - Thermal 640x512 at 12 um, 40 mm equivalent (M3T, M30T, M3TD): 7.68x6.144 mm, 9.1 mm (DJI, M30T).
- Route types (Pilot 2 manuals, release notes, FlightHub 2 notes): Mavic 3E/3T/3M all five (geometric since
  2024-05-22); M30/M30T area, linear, waypoint (no slope; DJI says the M30 is not designed for surveying); M3D/M3TD
  area, linear, waypoint, slope, geometric (dock drones: FlightHub 2); M4D/M4TD area, linear, waypoint (slope and
  geometric not documented).
- Real-time terrain following (`realTimeFollowSurface`): DJI documents it for the Mavic 3E/3T/3M only; our M4T and
  M4E Pilot 2 files use it too. Other models: AGL area and linear routes fly over the embedded terrain model only.

**Design:**
- `drones.json` gains, per model, `route_types` (the route types offered) and `realtime_follow` (whether AGL area and
  linear routes can use the real-time follow). The M4T and M4E keep everything as today.
- Server: creating, copying and importing a route refuse a route type the model does not offer; AGL with real-time
  follow is refused for a model without it, and its default is the terrain model; a copy to such a model switches
  real-time follow to the terrain model.
- Pages: the new-route menu offers only the chosen model's route types; the copy dialog lists only the models that
  fly the route's type; the area and linear editors hide "Real-time follow" for a model without it.
- KMZ import: a Pilot 2 file for any of the new models imports, with the same checks.
- Not changed: speeds, the gimbal range and the photo interval stay the M4T's (no DJI source per model); waypoint
  AGL is unchanged.

### Phase 15c: M300 and M350 with a payload (planned and built 2026-11-19)

Researched 2026-11-19 (DJI's WPML spec and live Product Support page, the M300/M350/Zenmuse manuals, spec pages,
FAQs and release notes; no Pilot 2 file for these at hand or found):
- Enums: M300 RTK 60/0, M350 RTK 89/0; payloads H20 42, H20T 43, H20N 61, H30 82, H30T 83 on the main gimbal
  (payloadPositionIndex 0). The Product Support page lists all five for both aircraft with Pilot 2 (the H30 series on
  the M300 needs the DJI RC Plus).
- Lens names: DJI's spec gives only zoom, wide and ir for the M300 and M350 (payloadLensIndex), not visable; so the
  wide camera is written `wide` (a camera's `lens` in drones.json). payloadSubEnumValue undocumented: the M4T's 0/2.
- Cameras from DJI's spec pages: the visible sensors from the focal length and diagonal field of view, the thermal
  ones from the 12 um pitch; the H30's photos 4032x3024 as the Matrice 4T's camera of the same class (DJI lists
  8064x6048 or 4032x3024). The H20N's tele thermal and every zoom camera are not planned for.
- Route types: waypoint, mapping (with oblique) and linear (the manuals); slope only on the Mavic 3E series (spec);
  geometric not documented. Terrain follow over an imported DSM (release notes), no real-time follow (spec).

Design (Claude's choice, the user having asked to carry on without stopping): **one registry entry per aircraft and
payload** ("DJI M350 RTK, Zenmuse H20T"), chosen in "Select Model" like any drone, rather than a second payload menu:
the payload, like the model, is fixed when the route is created, and every check (route types, cameras, the import)
works per entry unchanged.

### Phase 15d: DJI Fly (planned and built 2026-11-19)

Researched 2026-11-19 from FlyPath (commit a6f92c0; its writer `wpml/consumer.py`, matched by its authors to a Mini 4
Pro mission dumped from a DJI RC 2, commit bf9874c) and flypath_engine (3065acc), cross-checked with DJI's user
manuals (Waypoint Flight sections: Mini 4 Pro, Air 3, Mavic 3 Classic, Mini 5 Pro, Air 3S, Mavic 4 Pro, Lito X1; none
in the Mini 3 Pro's v1.6 manual). DJI publishes no DJI Fly format, waypoint limit or consumer enums.

Decided by Claude (the user having asked to carry on), from that research:
- The file: namespace `uav.com/wpmz/1.0.2`, waypoint template only, the Placemarks in both files, no payload, heights
  `relativeToStartPoint`, curved turns (straight legs are reshuffled on a re-save: FlyPath's issue #13).
- Area (ortho only) and linear routes as one waypoint per photo at the plan's interval (DJI Fly ignores
  `multipleDistance` and `multipleTiming`: FlyPath's field reports); the first point turns the gimbal, hovers 3 s,
  then shoots (FlyPath's issue #8). Linear routes shoot along the path the plan counts photos on (lines and turns, then
  the center line).
- AGL as a height per waypoint: the height plus the ground (the route's terrain, `terrain.ground_heights`; a waypoint
  route's fetched grounds) minus the ground at the takeoff point, or at the first point without one.
- At most 200 points a mission (FlyPath's limit); longer routes split into missions sharing their seam point,
  downloaded as a .zip.
- Refused for DJI Fly: oblique, a POI heading, video and interval photos, "back to the first waypoint" at the end, a
  speed over the drone's top speed (FlyPath's 12 or 15 m/s).
- The 8 drones with FlyPath's numbers (drone enum 68, the Mini 3 Pro 97; cameras as its profiles), shown like the
  others (the user: no "unverified" mark); the README says which numbers are confirmed and how to put a mission on
  the controller.
- Not done: importing DJI Fly files; sending a mission to the controller from the browser.

### Phase 15e: KML import and export (planned and built 2026-11-19)

Built while 15d's research ran (15e does not depend on it). Decided by Claude (the user having asked to carry on):
- **Import** through the existing "Import KMZ or KML file" entry: a file that is not a DJI mission (no
  `wpmz/template.kml`) is read as plain KML: its first polygon (outer boundary) is an area route, else its first line a
  linear route, else two or more points a waypoint route; the model is the one chosen in "Select Model"; heights in
  the file are ignored (the route takes the editor's defaults). Limits as the planner's: 200 corners, 500 points.
  DOCTYPE and entities refused, as the DJI import does.
- **Export:** "Download KML" in each editor (api.KmlView, `POST kml` with the plan request's body): the drawn shape
  draped on the ground and the flight path at air.py's heights (`absolute`, above sea level, where known, else
  `relativeToGround`), with a description saying which. For viewing, not a mission file.

## Phase 14: lidar for AGL routes' terrain: done

Asked 2026-11-18 (the user), planned the same day. Builds on Phase 6 (`lidar.py`: the 1 m lidar surface) and on the
shelved Phase 5 (branch `phase-5-3dep`: `geoid.py`'s GEOID18 grid and the NAD83(2011) to WGS84 step).

**Why:** an AGL route follows the terrain embedded in its KMZ: COP30 (30 m) today, or Pilot 2's own ASTER DSM on an
imported route. The spike measured the lidar's highest point a 30 m cell about 14 m above Pilot 2's terrain (median,
up to 40 m) over the Pilot 2 sample: the flight clears trees and roofs by less than the set height. With the lidar
surface as the terrain, the flight, the 3D view and the collision check use one surface.

**What exists:**
- `missions/terrain.py`: `fetch_terrain(points)` cuts COP30 to the route plus 200 m (`MARGIN`, at most 10 km a side),
  moved to the WGS84 ellipsoid by the undulation at the centre (one Point Elevation call), as an int16 EPSG:4326
  GeoTIFF. `RouteTerrainView` (area and linear routes with the DSM follow, or oblique AGL) and
  `RoutePointElevationsView` (waypoint AGL heights: the terrain cell under each point) keep it on the route.
- `lidar.py`: units of about 0.9 km (zoom-15 tiles), built by WebODM's worker, each with a `dsm.tif` (1 m cells,
  EPSG:3857, the highest return per cell, 40 m of overlap, NAVD88 heights); the editors poll their states
  (`request`, `states`).
- Pilot 2's embedded DSMs (the fixtures, checked 2026-11-18): 1 arc-second (about 30 m) int16 EPSG:4326, about
  1200 x 1200 cells, 2.9 MB. Pilot 2 is known to load that; finer cells are untested.
- `missions/geoid.py` on main has the EGM96 grid (the takeoff point's ellipsoidal height). GEOID18 is only on
  `phase-5-3dep`.

**Decided with the user (2026-11-18):**
- **10 m cells** (1/3 arc-second, EPSG:4326), each the highest lidar point in it, so that trees and roofs are never
  underflown. Pilot 2 has not been seen loading cells this fine, so before the merge the user loads a KMZ on the
  controller (see Done when). If Pilot 2 refuses it, the cell size is one constant, with 1 arc-second as the fallback.
- **Per-route choice:** a "Terrain" segmented choice, "Lidar surface (trees, roofs)" or "COP30", in the side panel of
  the area editor (for AGL routes over the terrain) and of the waypoint editor (for AGL).
  - It is saved in the route's settings (`terrain_source`: `lidar` or `cop30`). New routes, and routes saved before
    this phase, default to `lidar`.
  - Where there is no lidar, the route uses COP30, and the terrain status says why.
  - An imported route keeps Pilot 2's DSM until its terrain is fetched again.
- **Wait for the build:** when "Fetch terrain" runs on a route whose lidar units are not built, it starts their
  build and waits, with the progress in the lidar status bar, then makes the terrain from them. The same applies when
  the export or the waypoint heights fetch the terrain.
- **At most 4 km2 from lidar:** the terrain area (the route plus 200 m round it) can be at most 4 km2, about 400 MB
  and a minute of build. A larger route uses COP30, and the terrain status says so.

**Design:**
1. **`missions/geoid.py`:**
   - Adds the GEOID18 grid (`us_noaa_g2018u0.tif`, 16,742,155 bytes, sha256 pinned), downloaded from cdn.proj.org into
     `mission_planner_data/grids/` beside EGM96's, with the same download rules: a deadline, size and sha256 checked,
     an atomic rename, an unreadable grid set aside.
   - `navd88_to_ellipsoid(heights, lon, lat)`: GEOID18, then NAD83(2011) to WGS84 through ITRF2014 (EPSG:7912). The
     code and its tests come from `phase-5-3dep`.
   - CONUS only, since that is the extent of GEOID18's grid. Alaska, Hawaii and Puerto Rico have other geoids, so they
     use COP30.
2. **`lidar.py`:**
   - `units_for` takes the terrain's bounds, not the route's.
   - Each unit's state records its project's vertical datum, read from the project's `ept.json` (`srs`). A project
     not in NAVD88 (EPSG:5703) counts as no lidar.
   - This is checked on the samples' project first and captured as a fixture.
3. **`missions/lidar_terrain.py` (new):** `terrain_from_units(bounds, units)`:
   - mosaics the units' `dsm.tif` files;
   - reduces them to 10 m EPSG:4326 cells, each taking its highest value;
   - moves every cell to the ellipsoid;
   - writes int16, as the COP30 terrain is.
   - Cells with no lidar (holes, or units that have none) are filled from COP30, never from AWS's bare-ground tiles.
     That costs one Global DEM call and one Point Elevation call, as today.
   - `info`: `dataset` (`lidar`, or `lidar+COP30` when filled), `vertical` `NAVD88/GEOID18`, `cell` 10, the units,
     and the share of cells filled.
4. **`api.py`:** `RouteTerrainView` and `RoutePointElevationsView` read the route's `terrain_source`.
   - The lidar is used when the source is `lidar`, the route is in CONUS, under 4 km2, and has lidar there. The units
     are requested.
   - While any unit is queued or building, the answer is 202 `{building: [...units], states}`. The editors poll the
     existing lidar states and ask again once every unit is done or has none. Then the terrain is made and saved.
   - Otherwise the terrain is COP30, as today, with `fallback` saying why: no lidar here, outside CONUS, too large, a
     unit failed, or the grid could not be had.
5. **Editors:**
   - The Terrain choice is added to `route_form.js` and `waypoint_form.js`, and is shown when the route flies over the
     terrain.
   - The terrain status line says "Lidar terrain (10 m) fetched ..." or "COP30 terrain: <why>".
   - Fetch terrain and the export wait on a 202, with the lidar status bar showing the build.
   - Changing the choice marks the terrain as needing a fetch, as moving the area outside it does today.
6. **Waypoint routes:** the ground under each point is still the terrain cell it falls in. Where there is lidar,
   that cell is now 10 m and at the top of the canopy.

**Failures and what happens:**

| Failure | What happens |
|---|---|
| A unit fails to build, or dies with its worker | Its state says failed (`lidar.py`, as today); the terrain uses COP30 with that reason |
| The build takes longer than the editor waits (5 minutes) | The editor stops waiting and says so; Fetch terrain again picks up the built units |
| No lidar here, or a project not in NAVD88 | COP30; the status says why |
| Holes in the lidar | Filled from COP30 (one call); if that fails, the fetch fails as today (502, cached terrain kept) |
| GEOID18 grid unreachable or corrupt, or the disk full | COP30; the status says the grid could not be had |
| Outside CONUS, or over 4 km2 | COP30; the status says why |
| OpenTopography fails (COP30 or the filling) | 502 as today, cached terrain kept |
| Key refused | The error as today |

**Tests:**
- `test_mission_geoid.py`: GEOID18 from `phase-5-3dep`, with the download's failures, and the conversion checked
  against NGS's values when the real grid is present.
- `test_lidar_terrain.py`, on small synthetic unit DSMs:
  - the 10 m maximum and the mosaic across units;
  - holes filled from a fake COP30;
  - the datum shift;
  - the size cap and a project not in NAVD88;
  - every fallback's reason.
- `test_mission_planner_api.py`: 202 while building, then the terrain; `terrain_source` saved and defaulted.
- Jest: the forms' choice and the editors' status text.
- Each failure in the table is injected, and its test is seen failing before the handling is written.

**Done when:**
- The checks pass on both stacks.
- Live on both stacks:
  - the oblique AGL sample's AGL route gets lidar terrain built from scratch: the wait shows, then "Lidar terrain (10 m)";
  - its KMZ's DSM is compared with COP30 and with Pilot 2's, and the canopy's lift is reported;
  - in the 3D view the route is drawn over the same surface;
  - a waypoint AGL route takes its heights from the lidar;
  - choosing COP30 works;
  - a route over 4 km2 and one in Paris fall back to COP30, each with its reason.
- Then **the user loads the lidar KMZ in Pilot 2 on the controller** and checks that it opens and the terrain shows. If
  it does not, the cells go to 1 arc-second and the check is repeated.
- OpenTopography calls are counted.

**Built (2026-11-18, branch `phase-14-lidar-terrain`), with these changes from the design:**
- **The datum check:** USGS's EPT files say nothing of their vertical datum (`srs` is EPSG:3857 alone, checked on
  the two projects there 2026-11-18), so a project not in NAVD88 cannot be read from `ept.json`. Instead
  `lidar.datum_check` compares each unit's lowest lidar per AWS zoom-15 pixel with AWS's bare ground (NAVD88 in the
  US): its 2nd percentile must be within 5 m (ellipsoidal heights would be 8 to 50 m off, feet 3.28 times), kept in
  the unit's `datum.json`. A unit that fails counts as no lidar (filled from COP30).
- `lidar_terrain.py` sits at the plugin's root beside `lidar.py` (it reads the units), not in `missions/`.
- The build's progress shows in the terrain status line (the waypoint editor's ground status) and on the map's lidar
  bar; the editors ask again every 3 s for up to 5 minutes (`Core.fetchUntilBuilt`).
- The 4 km2 cap is on the terrain area, as decided; the units it needs can still number up to `lidar.MAX_UNITS`
  (12, about 10 km2 of lidar) for a route lying across unit corners.
- The side panel's terrain warning (`wpml.terrain_warning`) no longer says the terrain leaves out trees and roofs.
- The tests were isolated from the lidar and GEOID18 (`tests/__init__.py`): WebODM runs worker jobs inline under
  test, and the first run built two real units and downloaded GEOID18 into `tests/fixtures/geoid` (removed).

**Tested:** Django 587 on both stacks (`test_lidar_terrain.py`: 20; GEOID18 in `test_mission_geoid.py`, the real grid
against NGS's values at 6 points while the live check had it), Jest 394, ESLint, Ruff. Seven handlers broken one at a
time (a failed unit, the datum check, GeoidError, the wait, the area cap, the filling, max resampling): each caught by
its test. Live on both stacks (`.claude/skills/live-check/lidar_terrain_check.js`): the oblique AGL sample's lidar terrain
(3.3.2 built its 2 units in 27 s, with the progress shown), its KMZ against COP30 (lidar minus COP30: median +7.7 m,
5th percentile -1.3 m, 95th +18.9 m, max +34.2 m) and Pilot 2's DSM (median +8.3 m, max +39.3 m), the same DSM on
both stacks; COP30 chosen (the status says it is fetched again, the export fetched it); a waypoint AGL route's grounds
from lidar (184, 195, 199 m ellipsoidal) after building 2 units; Paris and a 5.2 km2 route on COP30 with their
reasons. 12 OpenTopography calls (3 COP30 fetches a stack). Left as found: the units and GEOID18 removed, 4.0.0's four
earlier units' tiles made again.

**The user's check (2026-11-19):** the user's TestAreaRoute, exported with Terrain model over lidar terrain, opens in
FlightHub 2 with the 10 m file listed under Terrain Follow File Management, but shows "Terrain follow file updated.
Altitude relative to ground error. Refresh file" until Update is clicked; after Update the error goes and the lidar
file is used. The 10 m cells are accepted; the heights are not (next section). Merged with that bug recorded.

## Bug: FlightHub 2 rejects the heights over lidar terrain: not a bug, closed

Reported 2026-11-19 (the user). **Not the heights:** the first guess was `wpml.dsm_of`'s rule (each waypoint the set
height above the highest terrain within `terrain.RADIUS`, 50 m, of it: +23 to +35 m over the cell under it beside
the building, where Pilot 2's own exports are -3 to +7 m). A copy of the user's export with every waypoint exactly
the set height above the cell under it showed the same error (the user, 2026-11-19).

**What differs from Pilot 2's own DSM** (`TestAreaKMZ-35.kmz`): Pilot 2 embeds a whole 1 degree ASTER tile (1201 x
1201, uncompressed, `wgs84_ASTGTMV003_N42W086_dem_9.tif`); ours is a cut round the route (59 x 46), deflate, named
`wgs84_LIDAR10M_N41W080_dem.tif`.

**FlightHub 2 does this to every imported terrain file** (the user, 2026-11-19): the four test files (A our COP30
export, B Pilot 2's own `TestAreaKMZ-35.kmz`, C our lidar file uncompressed, D C with a DJI-style name) all show
the error, and Update replaces the file with FlightHub 2's own "Global Elevation Data". Pilot 2's own export is
treated the same, so no change to our files can avoid it: a mission imported into FlightHub 2 flies over
FlightHub 2's terrain after Update, not the embedded one (COP30 or lidar alike, since Phase 1).

**Confirmed with FlightHub 2's own exports** (the user, 2026-11-19, kept outside the repo): they embed
the whole ASTER tile, with a template field for field like ours (plus the takeoff point) and smoothed heights (-9 to
+3 m from the set height over the cell under each point); imported back into FlightHub 2, the same error. Nothing to
fix in the plugin: the README says to load lidar-terrain missions in Pilot 2 on the controller.

**Pilot 2 keeps it** (the user, 2026-11-19): the user's lidar-terrain export, imported straight into Pilot 2 on the
controller, loads without the error, shows `wgs84_LIDAR10M_N41W080_dem.tif` as its terrain and the right flight
height. Closed: lidar-terrain missions go to the controller as files.

## Phase 13: the Pointer tool

Asked 2026-11-18 (the user): a pointer tool, the default tool, left of the Polygon button. Each click places a dot
that stays and shows the height above sea level of that spot; dots are joined by a dotted line with the height
difference between them in its middle, in "+/-" form, in the user's units.

**What exists:** the area editor's toolbar (`templates/planner.html`): Polygon, Rectangle, Edit and the bin (linear
routes: Line, Edit, bin), Terra Draw modes set by `setTool`; a new route opens in Polygon (Line), a drawn one in Edit.
The waypoint editor has no toolbar: a click on the map adds a point (`waypoint_planner.js`, `map.on("click")`). The
pointer tooltip's heights (`pointer_height.js`: the lidar surface's tiles where built, else AWS's terrain tiles,
`heightsAt`) are what a dot reads.

**Decided with the user (2026-11-18):**
- **Both editors.** Area editor: "Pointer" first in the toolbar, left of Polygon (Line). Waypoint editor: a new
  toolbar in the side panel, where the area editor has its toolbar, "Pointer | Add points"; a click adds a point only in "Add points".
- **Always the default:** every route opens in Pointer, new ones too (Polygon, Line or Add points is clicked to
  draw). After drawing finishes the editor goes to Edit as now.
- **Chained dots:** each click adds a dot, labelled "216.2 m ASL"; from the second on, a dotted line joins it to the
  previous dot, labelled in its middle with the difference "+12.3 m" or "-4.0 m" (the later dot minus the earlier, one
  decimal, the editor's units). Clicking an existing dot, or switching to another tool, clears them all. Nothing is
  saved with the route.

**Design:**
- A small `measure.js` (with tests): the dots' and lines' GeoJSON and labels from the dots and their heights, and the
  difference's text; the editors own the clicks.
- 2D and 3D: GeoJSON layers for the dotted lines and labels (draped on the surface in 3D), the dots as markers on the
  surface; in 3D a click takes the surface point under the pointer, as adding a waypoint does.
- A dot's height is read with `heightReader.heightsAt`; until it is read the label says "…"; a tile that cannot be
  read: "no height", and its lines show no difference. A change of units relabels them. When the lidar surface is
  built later, the dots are read again.
- Area editor: in Pointer, Terra Draw is in "static" mode; picking the takeoff point or the route's start still wins
  over a dot. The tooltip keeps working in Pointer.

**Failures and what happens:** a tile that does not load: "no height", as above; clicks faster than heights load:
each dot is labelled when its own height arrives (answers matched to their dot, dots cleared meanwhile dropped).

**Tests:** Jest for `measure.js` (labels, signs, units, "no height", clearing), the area editor's default tool and
toolbar order, the waypoint editor's modes (a click adds a point only in "Add points"); live on both stacks: three
dots in 2D and in 3D over the oblique AGL sample (labels and differences matching the tooltip's heights), clearing by
clicking a dot and by switching tools, adding waypoints in "Add points", a new route opening in Pointer.


**Built (2026-11-18):** as planned, with these details: in imperial a dot reads in whole feet, as the tooltip does,
while the differences keep one decimal; a line's label sits just below its middle, clear of the dots' labels; the
dotted line is dark dots ringed in white, to show on imagery. In the waypoint editor a POI route's subject is also
placed with Add points, drawing the subject's outline and picking the takeoff point win over either tool, and the
side panel's message says "Choose Add points and click the map..." while Pointer is on. The editors' wiring is
tested by the Django page tests (the toolbars' order, Pointer active) and live, not in Jest (the editors need
MapLibre); the dots read again when the lidar surface is built is tested in Jest only (the live check turns the lidar
off in its browser, so that nothing is built).

## Phase 11: collisions and the route's height in 2D

Asked 2026-11-18 (the user): the 2D map also showing the route's height, so that collisions are found and drawn in
2D as well; and the height tooltip at the pointer in 2D. Builds on Phases 7 (`pointer_height.js`), 8 and 10
(`route_3d.js`).

**What exists:** the pointer tooltip already works in 2D (checked live 2026-11-18 on 4.0.0: "215.9 m ASL" over
route 39, "244.1 m ASL" over route 54): it reads the lidar's zoom-18 tiles where built, else AWS's zoom-15 terrain
tiles. The collision check (`collide`) runs only in 3D, against `map.queryTerrainElevation` (the 3D view's surface
as loaded, coarser when zoomed out), and the lidar surface is built only on a route's first 3D view.

**Decided with the user (2026-11-18):**
- **One check for both views,** against the pointer tooltip's tiles (lidar 1 m where built, else AWS ground): 2D and
  3D give the same count whatever the zoom.
- **The 2D editor builds the lidar surface** too (when "Lidar surface (US)" is on): opening a route in 2D starts the
  build in the background, as the first 3D view does now; the check is run again when units are built.
- **2D shows** the route line red where it goes into the surface and 10 m of yellow each side, as in 3D, and the same
  count line in the side panel. No depth labels.
- **The tooltip over the route line** adds the route's height above the surface there, e.g. "216.2 m ASL, route
  38.0 m above" (or "route 6.0 m below").

**Design:**
- `pointer_height.js`: `heightsAt(points)` reads many points at once, grouped by tile, a few tiles at a time, so a
  large route does not hold every tile at once.
- `route_3d.js`: the surface for the check, the lift of "surface" and "takeoff" routes and the drop lines is the
  sampled heights at the route's points (every 5 m piece, the takeoff point), read with `heightsAt`, not
  `queryTerrainElevation`; the work is redone when the plan changes, the view changes, or lidar units are built (not
  on every `idle`), and a newer run drops an older one still reading. It runs in 2D too: the WebGL layer draws only
  in 3D; in 2D a GeoJSON line layer above the plan's lines draws the yellow and red stretches. The count line shows
  in both views. Dragging a point in 3D still follows the 3D view's surface.
- `routeNear(point)`: the route's point nearest the pointer on the screen (within a few pixels), from the checked
  paths (`map.project` in 2D, the layer's `project` at its height in 3D); the tooltip then shows the surface height
  there and the route's height above it.
- Both editors: the lidar surface requested in 2D when the route has a place, again when its area moves to other
  units; not stopped on leaving 3D; the status bar's texts no longer name the 3D view.

**Failures and what happens:** a tile that does not load: its points count as clear (as in Phase 10) and the next
run tries again; the lidar build fails or is refused: the AWS terrain tiles, the status bar says so, as now; a plan
changed while its heights are read: the older run's result is dropped.

**Tests:** Jest for `heightsAt` (grouping, few tiles at once, a failed tile), the check in 2D (the GeoJSON of the
stretches, the count in 2D), the run order (an older run dropped), `routeNear` and the tooltip's text; live on both
stacks: the waypoint route through the oblique AGL sample in 2D (red and yellow, the count, the tooltip over the line),
the lidar built from 2D, the 3D count the same at two zooms, the routes deleted.

**Built** (2026-11-18) as designed. Found while testing: routes measured from sea level or the takeoff point read the
surface under their path only in `collide`, so `pointsNeeded` collects `collide`'s points too. Outside lidar coverage
the status bar now says "No lidar here: the standard terrain is used" for a few seconds whenever a route is opened.
Checked: Jest 368; ESLint and Ruff clean; 11 mutations of the new code each caught (one test added for a survivor:
two stretches of one colour with clear line between them). Live on both stacks (`collide2d_check.js`): on 3.3.2 the
2D editor built the lidar surface itself ("Building the lidar surface (1 of 2)", about 23 s; 4.0.0 had it built);
the waypoint route with a point 10 m up reads "goes into the surface in 1 place" in 2D, with red and yellow into
point 3 on the map, and the same in 3D at the editor's zoom and three levels out; the one 150 m up and the oblique
AGL sample read "stays above"; the tooltip on the line reads "220.4 m ASL, route 129.6 m above" and near point 3
"route 12.3 m above", off the line the surface only; no new console errors; routes deleted, the lidar surface cleared
on 3.3.2 (empty before).


## Phase 10: collisions shown on the route in 3D

Asked 2026-11-18 (the user, with a screenshot of the oblique AGL sample in 3D over the lidar surface, its passes going
through the building's lidar shape): in the 3D view, the part of the route's line that is inside the surface drawn
red, and a short part of the line leading up to it, and away from it, drawn yellow, to find where each collision
starts and ends. Builds on Phase 8 (`public/route_3d.js`).

**What exists:** `resolveAir` already cuts each path into pieces of `STEP` (5 m) where its heights are above the
surface, and `surfaceAt` reads the 3D view's surface (lidar where built, else the terrain tiles) under any point;
`buildGeometry` draws every segment in one colour (`#1e88e5`).

**Decided with the user (2026-11-18):**
- **Yellow:** 10 m of line before and after each red stretch, fixed (whatever the speed).
- **Red:** only where the line is inside the surface (below the ground, trees or a roof), no safety margin. The
  datum gap (the routes' EGM96 against the lidar's NAVD88, about a meter in the US) stays a known limit, as the
  README says.
- **Seen through:** the red stretches are drawn on top of the surface, so a pass through a building or trees shows;
  the rest of the line keeps its depth (hidden behind hills and roofs, as now).
- **A count in 3D:** in the 3D view, the side panel of both editors (the area editor's and the waypoint editor's)
  says how many places the route goes into the surface, or that it stays above it. The 2D map shows nothing: it has
  no surface heights loaded.

**Design:**
- `resolveAir` cuts every path into `STEP` (5 m) pieces, "sea" and "takeoff" routes too (today only "surface"
  routes are cut), within `MAX_POINTS`, so a line between two points high enough is still checked along its length.
- Each piece's height is compared with `surfaceAt` (the 3D view's surface: lidar where built, else the terrain
  tiles). Where the line crosses the surface, the crossing point is added (interpolated), so red starts and ends
  where the line meets the surface, not at the nearest piece.
- Each vertex gets a colour: red inside, yellow within 10 m along the path of a red stretch, blue elsewhere. The
  colour goes into the line's vertex data (no extra draw for colour); the red segments are drawn a second time with
  the depth test off.
- The count is the number of red stretches over all paths. It is recomputed with the geometry (the map's `idle`,
  as now), so it follows the surface as its tiles and the lidar load: zoomed far out, coarser tiles can move or
  hide a collision.
- Drop lines and waypoint labels are unchanged (a label is already red below the surface).

**Tests:** Jest for the cut of every reference, the crossing points, the colours and the 10 m of yellow (also where
two collisions are closer than 20 m, and at a path's ends), the count, and the second draw; live on both stacks: a
waypoint ALT route through the oblique AGL sample's trees and building over the lidar, and one above everything,
screenshots in 3D, the count line read, the routes deleted.

**Built** (2026-11-18) as designed. Also: the discs (the area editor's points) are drawn at the plan's own points,
not at every 5 m piece, now that every path is cut. Checked: Jest 351; Django 562 on each stack (with WebODM's
plugin tests); 11 mutations of `route_3d.js` each caught (two tests added for survivors: a line touching the
surface, collisions closer than the yellow's length). Live on both stacks (`collide3d_check.js`; 4.0.0 also with
the lidar surface): the waypoint route with a point 10 m up reads "goes into the surface in 1 place" (red), its
line blue, yellow, then red into point 3 (-6 m); the one 150 m up and the area sample read "stays above";
the line is hidden in 2D; no new console errors; the routes deleted.


## Phase 9: drawing and editing in 3D

Asked 2026-11-18 (the user): the editors' drawing and editing tools working in the 3D view as in 2D. Today
`setView3d` disables them in 3D and shows "Drawing and editing are done in 2D" (`planner.js`) or "Points are added
and moved in 2D" (`waypoint_planner.js`) under the map. Builds on Phase 8 (`route_3d.js`, `liftMarkers`).

**Decided with the user (2026-11-18):**
- **Dragging a waypoint marker in 3D holds the marker in the air:** the point moves so that its lifted marker stays
  under the pointer; its height does not change.
- **No height dragging:** a drag moves a point sideways only; heights are still typed in the selected point's panel.

**Checked 2026-11-18** (the installed packages: terra-draw 1.35.0, terra-draw-maplibre-gl-adapter 1.4.1, maplibre-gl
6.16.0):
- The adapter turns the pointer into a position with `map.unproject`, which over terrain gives the point of the 3D
  surface under the pointer: Polygon, Rectangle, Line and Edit should place corners where they are clicked on the
  surface (a roof's corner at the roof's position). To be confirmed live, with the map's own drag and rotate gestures.
- A `Marker`'s drag (`_onMove`) unprojects the pointer less its offset at the drag's start: with the Phase 8 offset
  (the point in the air minus the point on the ground), which changes as the surface under the point changes, the
  point would drift from under the pointer. The drag is computed by the editor instead.
- The takeoff point and route start pickers already work in 3D (the map's click handler).

**Design:**
- **Area editor** (area, linear, slope and building routes; the Polygon, Rectangle, Line, Edit and delete buttons
  above the map): the buttons stay enabled in 3D and terra-draw keeps its mode (no `static`); the shape stays
  draped on the surface; the note under the map goes.
- **Waypoint editor:** a click on the map adds a point in 3D too (at the surface position under the pointer), the
  subject's outline ("Draw the outline") can be drawn, and the subject marker dragged (it is on the ground). The
  numbered markers are draggable in 3D: during a drag, the point's position is where the ray from the camera
  through the pointer meets the point's height (above sea level from the drawn route; for heights above the surface,
  a few rounds with the surface under the last guess). A new `route_3d.js` function does this with the inverse of
  the last frame's matrix, beside `project`. The route, its lines down and the labels follow at the drag's end, as in
  2D.
- 2D is unchanged.

**Tests:** Jest for the ray-height intersection (round trip with `project`, heights above sea level and above the
surface, a ray that misses: pointer above the horizon), the tools enabled in 3D, and the marker drag; live on both
stacks: draw and edit an area in 3D, add and drag waypoints in 3D (the marker stays under the pointer), screenshots.

**Built** (2026-11-18) as designed. The ray-height intersection runs a few rounds (the height and the world's scale
where the last landed); the drag uses the pointer pressed and moved as the map reports them, MapLibre's own marker
drag still moving the marker, corrected on each `drag` event. Found on the way, fixed: an AGL waypoint route whose
points had no ground yet ("surface" heights) had its markers left on the ground in 3D, its path being cut into
pieces that no longer matched the points (`resolveAir` now also gives the plan's own points, lifted). A point higher
than the camera cannot be projected: its marker stays on the ground, or off the map's top (zoom out; said in the
README). Checked: Jest 339; Django 562 on each stack (with WebODM's plugin tests; the page test now checks that the
"done in 2D" note is gone); live on both stacks (`edit3d_check.js`): an area drawn and dragged in 3D and saved, a
point added by a click in 3D, and a marker of an ALT and of an AGL route (100 m) dragged in the air: 0 px from where
it was dropped after the plan came back, against 22.6 and 38.2 px with the air drag turned off.
