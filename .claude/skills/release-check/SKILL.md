---
name: release-check
description: Check a release of the DJI Mission Planner plugin before merging its release/X.Y.Z branch - build the zip, install it in WebODM through Administration > Plugins as a user would, and check it live.
---

# Release check

`release_check.js` (beside this file; its modes in its first lines) drives steps 4 to 6 on one stack:
`install <zip>`, `check`, `delete`, `install <zip>` again, `after` (`cleanup` after a failed run). It logs in with the
dev account from `MP_ADMIN_USER` / `MP_ADMIN_PASSWORD` and writes screenshots and downloads to `MP_OUT` (the
scratchpad). `check` makes one OpenTopography call (an AGL route whose editor fetches COP30). In dev mode, loading the
zip a second time makes Django's autoreloader restart the server, which cuts off the upload's answer
(`ERR_CONNECTION_RESET` or `ERR_SOCKET_NOT_CONNECTED`): the install has gone through; wait for the login page, then go
on. The takeoff-height 404s (`routes/<id>/elevation`, nothing cached yet), the COP30 route's first 409 and the
livereload refusals (port 35729) are expected.

On the `release/X.Y.Z` branch, with the version in `mission_planner/manifest.json`, `CHANGELOG.md` and `README.md`
updated and committed.

1. **The tests** (the `test` skill), including WebODM's `app.tests.test_plugins`.
2. **The zip:** `dev/package.sh`. Check its listing: one root folder `mission_planner/` with `manifest.json`,
   `plugin.py`, `LICENSE`; no `tests/`, `public/__tests__/`, `node_modules` or `__pycache__`. Note the sha256.
3. **WebODM without the mounted plugin:** `MP_PLUGIN_DIR=<an empty folder in the scratchpad> dev/webodm.sh up
   --force-recreate webapp worker` (4.0.0), and wait for http://localhost:8009 to answer. The DJI Mission Planner menu
   entry is gone. `docker exec mp-webapp ls /webodm/app/media/plugins` must not list `mission_planner`: an upload
   whose name has a folder there is refused (a folder left by an older layout is removed once checked empty).
4. **Install the zip as a user would:** log in as the dev admin (the `live-check` skill), Administration > Plugins,
   upload the zip. Restart the webapp if WebODM asks to. Check that the plugin is enabled, that WebODM ran npm in
   the installed copy (`docker exec mp-webapp ls /webodm/app/media/plugins/mission_planner/public/node_modules`) and
   that the menu entry is back.
5. **Live check on the installed copy** (the `live-check` skill): each route type's editor, a KMZ download and
   import, terrain for an AGL route, the settings page (the environment's key shown as set), and an import of a small
   LuxODM export made by hand (the format in `luxodm_import.py`, one route with terrain).
6. **The upgrade path:** with an AGL route that has terrain still there, delete the plugin in Administration >
   Plugins and load the zip again (from 1.0.1 on: install the previous release's zip first, make the route with it,
   then delete it and load the new one). The route opens with its terrain and downloads without fetching terrain
   again; `plugins/mission_planner_data/terrain/<id>` is still there. Then delete what the check made.
7. **Leave it as found:** remove the installed plugin in Administration > Plugins (its data stores stay, shared with
   the mounted copy: the routes must be what they were before the check), then `dev/webodm.sh up --force-recreate
   webapp worker` without `MP_PLUGIN_DIR` to mount `mission_planner/` again.

Then merge the release branch into `main` and tell the user: the zip and its sha256, the tag to make (`vX.Y.Z`) and
where to attach the zip (the GitHub release).
