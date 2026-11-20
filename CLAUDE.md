# CLAUDE.md

What Claude needs to know to work on the DJI Mission Planner plugin for WebODM. General working rules (branches,
phases, testing) live in the user's own CLAUDE.md; this file holds what is specific to this repository. It is
committed: nothing true only on one machine. Keep it short; edit in place.

## Rules for this repository

- **The plugin is `mission_planner/`**: the release zip has that folder as its single root. Dev tools (`dev/`,
  `package.json`, `eslint.config.mjs`, `ruff.toml`, `requirements-dev.txt`) stay outside it. The folder name is
  the plugin's name in WebODM (URLs `/plugins/mission_planner/`, `/api/plugins/mission_planner/`) and makes
  `coreplugins.mission_planner.tests.test_<name>` valid test labels (a hyphen would not be).
- **Official plugin rules only** (`ignored/WebODM-Docs/src/content/docs/plugin-development-guide.md`): no Django
  models or migrations, only the `PluginsAPI` hooks WebODM has, no changes to WebODM itself. Routes are
  `PluginDatum` rows of their owner's (`routes.py`: key `mission_planner::route:<id>`, the id the row's primary
  key), terrain rasters files in WebODM's plugin media beside the plugin (`plugins/mission_planner_data/terrain/<id>/`),
  not in its persistent folder: a zip-installed plugin lives there, and deleting it (the upgrade) removes the folder. The EGM96 geoid grid (`missions/geoid.py`, the takeoff point's ellipsoidal height) is there too
  (`mission_planner_data/grids/`; the tests read the copy in `tests/fixtures/geoid`), with GEOID18 (the lidar terrain's
  NAVD88 heights; never downloaded by the tests), and the 3D view's lidar surface (`lidar.py`) (`mission_planner_data/lidar/`), built by WebODM's
  worker (`run_function_async`): a change to `lidar.py` needs `docker restart mp-worker` to reach it.
  AGL routes' lidar terrain (`lidar_terrain.py`) is made from its units. WebODM runs worker jobs inline under test:
  `tests/__init__.py` points the lidar at a scratch folder and refuses builds and the GEOID18 download. `luxodm_import.py` reads LuxODM's
  route export (format `luxodm-routes`, version 1, written by LuxODM's `app/management/commands/export_routes.py`)
  and writes it with `routes.restore`; a change to the format changes both, with the version.
- **The aircraft are in `mission_planner/drones.json`** (`missions/drones.py` reads and checks it; the pages get it as
  `#mp-drones`): a model, its enums or cameras are changed there, not in the code.
- **WebODM 4.0.0 and later only** (decided 2026-11-19; 3.3.2 dropped): Python 3.14, Django 5.2, DRF 3.18, numpy 2.5,
  rasterio 1.5, Postgres 18 without GIS (`Task.dsm_extent` GeoJSON, so no query uses a GIS lookup). The image has
  GEOS (so `django.contrib.gis.geos` works without PostGIS), PDAL and entwine (checked 2026-11-17). Ruff targets py314.
- **The repo is public** (from 2026-11-19, Phase 18): the KMZ test fixtures were moved off the places they were
  flown, each place due east by its own fixed offset (where EGM96 matches, so Pilot 2's heights still agree), and
  their author emails replaced. A new fixture gets the same treatment before it is committed: no real place, email,
  name or serial number in it, and the offsets are never written down. Phase 18's fresh public history (`main` as
  one new commit) is a force-push the user allowed for that task only. The plugin is installed from the release zip (Administration > Plugins), not listed in WebODM-Plugins.
- **Never push and never tag.** Nothing is published by a push (no CI). A release: Claude first reviews the code
  changed since the last release for bugs and UI breakdowns that would hurt the user's experience (every page,
  panel and dialog a change touches, on both stacks), fixes what it finds on its own branches and merges them;
  then prepares a `release/X.Y.Z` branch (manifest version, `CHANGELOG.md`, `README.md`), builds the zip with `dev/package.sh`
  (`dist/mission_planner-X.Y.Z.zip` and its sha256; reproducible: a commit outside `mission_planner/` and `LICENSE`
  builds the same zip), runs the `release-check` skill and merges; the user tags
  `vX.Y.Z` and attaches the zip to the GitHub release.
- **Copies shared with other repos**: `layers_panel.js` and `search_panel.js` (Photon suggestions as one types,
  Nominatim on Enter) have adapted copies in webodm-geojson (their own class prefixes and features): a fix to one
  is made in the other too, with its tests. The code came from
  LuxODM's `coreplugins/mission-planner` and `app/missions` (see `upcoming-changes.md`).
- `README.md` is the plugin's page: every feature change updates it on the same branch.
- Planned in `upcoming-changes.md`; new requests arrive in `new.md` (untracked).

## Dev environment

- `ignored/WebODM` is a checkout of https://github.com/WebODM/WebODM (ignored by git) at tag `v4.0.0`.
  `ignored/WebODM-Docs` is https://github.com/WebODM/Docs (the plugin guide).
- `dev/webodm.sh up | down | logs [service] | ps` runs WebODM 4.0.0 in dev mode with `mission_planner/` mounted as
  `/webodm/coreplugins/mission_planner`, on http://localhost:8009, containers `mp-webapp`, `mp-worker`, `mp-db`,
  `mp-broker`, `mp-node-odx-1`, project and volumes `webodm-mission-planner` (the repo's old name, kept so the stack keeps its data), so it runs
  beside other WebODMs.
  Its images are pinned by digest in `dev/webodm.sh`.
  `WO_OPENTOPOGRAPHY_API_KEY` (from the environment, else the repo's `.env`, ignored by git) is passed to the
  webapp (the terrain and ground heights); `MP_NO_KEY=1 dev/webodm.sh up` passes none, to check the settings page
  (`config.py`: the environment's key wins over the one saved there, a global `PluginDatum` row
  `mission_planner::opentopography_api_key`). OpenTopography repeats a refused key in its message, and requests
  repeats the URL (with the key) in its errors: messages go through `missions.elevation.without_key`.
- WebODM's start runs npm in `mission_planner/public` as root: `node_modules` is root's. A dependency change is
  made in `package.json`, the lock file updated on the host (`npm install --package-lock-only`, which may also need
  `docker exec mp-webapp chown 1000:1000 /webodm/coreplugins/mission_planner/public/package-lock.json` first), then
  installed with `docker exec -w /webodm/coreplugins/mission_planner/public mp-webapp npm install`.
- The first start runs WebODM's dev setup (npm install, webpack, migrations) for several minutes before the server
  answers.
- Host tools: `uv venv --python 3.14 .venv && uv pip install -r requirements-dev.txt` (Django, DRF, numpy, pyproj,
  rasterio, requests for the IDE, Ruff); `npm install` (Jest, ESLint, Playwright). VSCode: interpreter `.venv`,
  `ignored/WebODM` on Pylance's extra paths (local `.vscode/settings.json`).

## Tests and checks

The `test`, `live-check` and `release-check` skills in `.claude/skills` have the steps.

- Django: the test modules by name, `coreplugins.mission_planner.tests.test_<name>` for each file in
  `mission_planner/tests` (discovery does not find them: WebODM's `coreplugins` is no package), in `mp-webapp`.
  One run at a time. Golden files:
  `MP_UPDATE_GOLDEN=1` rewrites them.
- Jest: `npm test` at the repo root (jsdom). ESLint: `npm run lint -- mission_planner` (the scripts in `public/`
  are ES5; the config does not run from a scratch folder, so check a scratch copy of a live script with
  `node --check` before it lands, then lint in place). Ruff: `.venv/bin/ruff check .`
- To see what an editor sends and gets (the plan, its `air` heights for the 3D view), capture the editor's own
  requests with Playwright: a route's saved settings are the form's strings, not a request body, so rebuilding one
  in `manage.py shell` fails the settings checks.
- Live checks: headless Playwright against http://localhost:8009 with a dev account.
- WebODM routes the plugin API through a plain Django view, so its CSRF check applies: a POST, PATCH or DELETE
  needs the session's CSRF token even with basic or JWT authentication.
