# Changelog

## Unreleased

- Esri's satellite basemap and OpenStreetMap show on a WebODM served over plain http: basemap URLs starting `//`
  load over https (their http answers are redirects the browser refuses), except the instance's own server and local
  addresses.
- The 3D view says "Loading elevation…" while the ground is still loading and being drawn (after switching to 3D,
  turning the lidar surface on or off, panning or zooming).
- With the lidar surface on, the 3D view no longer encodes a PNG in the browser for each close-up tile outside the
  lidar: the tile goes to the map as an image, and each AWS tile it is cut from is decoded once.
- A collision margin for each route (Advanced settings, 2 m by default): the route is red where it passes closer than
  that to the ground, a tree or a roof, above or beside it, along the whole route rather than at points 5 m apart.
- The lidar surface is tighter: each lidar point now counts only in its own 1 m cell (it used to raise the cells round
  it too, about 1.4 m beyond every wall and crown), and distant tiles average rather than widen tall things. Lidar
  surfaces built by an earlier version are built again once, the first time they are needed.
- Relief in the 3D view (layers panel, off by default): the ground coloured by its height round the route, under a
  stronger shading, with the photo faint over it.

## 2.0.0 (2026-11-20)

The first published release. Needs WebODM 4.0.0 or later.

- The plugin is now called DJI Mission Planner (its repo webodm-dji-mission-planner). Its internal name
  `mission_planner` is unchanged: saved routes, terrain and URLs carry on as they were.
- Nine more DJI Pilot 2 drones: Mavic 3E, 3T and 3M (RGB camera), Matrice 30 and 30T, Matrice 3D and 3TD, Matrice
  4D and 4TD, with the route types and terrain follow DJI documents for each (README, Drones).
- The M300 RTK and M350 RTK with a Zenmuse H20, H20T, H20N, H30 or H30T.
- DJI Fly missions for DJI's consumer drones (Mini 3 Pro, Mini 4 Pro, Mini 5 Pro, Air 3, Air 3S, Mavic 3 Classic,
  Mavic 4 Pro, Lito X1): area, linear and waypoint routes as waypoints with a photo each, split at 200 points.
- KML: a polygon, line or points from a plain KML or KMZ imported as a new route; every route downloads as KML (its shape and flight path).
- Needs WebODM 4.0.0 or later: WebODM 3.3.2 is no longer supported.
- The lidar surface is kept under 5 GB: past it, the places opened longest ago are removed (and built again when
  needed). A DJI Fly download holds at most 20 missions; a larger route is refused.
- Lighter on the server: block heights read a bounded number of points, the settings page no longer counts every
  lidar tile, and two terrain fetches at once leave no stray file.
- Rectangle draws square to the screen on a turned map (in 2D and 3D), no longer always along north and east.
- Area and linear routes are laid out in ground metres: the spacing between lines, the strip's width and the
  route's length are now what is asked for, where UTM's scale left them up to 0.1% off (a few cm on 26 m lines).
- The routes list remembers the model chosen under Select Model (in this browser). DJI Fly drones are not offered POI
  routes, which DJI Fly missions cannot fly; an oblique area copied for one becomes an ortho collection.
- A DJI Fly AGL route without a takeoff point warns that its heights are above the first point's ground.
- Fixes from the release review: an encrypted or damaged KMZ is refused with a message; a slope or geometric route's
  KML downloads (its shape) when the geoid grid cannot be had; a refused download says why instead of a parse error,
  and a second click while a download runs is ignored; a huge DJI Fly route is refused at once; lidar units waiting
  in a long build are not built twice, and one removed by the 5 GB cap while it is read no longer fails a request.

- Fixes from a code review:
  - Saving a route no longer drops its cached takeoff height ("Use cached values"), and a takeoff height still being
    fetched when Save is clicked no longer undoes the save.
  - An edit made while a save is in flight stays marked unsaved, so the leave prompt still catches it.
  - Download right after Fetch terrain (or Fetch ground heights) waits for the fetch, instead of doing nothing.
  - A route's type can no longer be changed through the API, and a PUT no longer resets the fields it leaves out.
  - The copy dialog says waypoint and single-line routes keep their heights, as they do; the import dialog describes
    waypoint and linear routes correctly; a delete the server refuses says so.
  - Low, high-overlap surveys get a speed (it could round to 0 m/s and fail); a linear route whose line turns back on
    itself is planned next to it; malformed requests and LuxODM dates answer with a message instead of a server
    error; OpenTopography's messages never show the key.
  - A lidar unit is built from the project covering it, not from a newer one touching only a corner.

- AGL routes can follow the lidar surface: a "Terrain" choice, "Lidar surface (trees, roofs)" (the default) or
  "COP30", in the area editor's terrain model and for AGL waypoint routes. The lidar terrain is the highest lidar point
  in each 10 m cell, moved to the WGS84 ellipsoid with GEOID18 (downloaded once into
  `plugins/mission_planner_data/grids`), its holes filled from COP30; Fetch terrain waits while the lidar is built.
  Outside the conterminous US, over 4 km², without lidar or when something fails, COP30 with the reason shown. The
  terrain warning in the side panel says which terrain the heights follow.
- The Pointer tool, the first tool in both editors and the one every route opens in: each click on the map puts a dot
  with its height above sea level, joined to the one before by a dotted line labelled with the height difference
  ("+12.3 m"); a click on a dot or another tool clears them. The waypoint editor has a toolbar, "Pointer | Add points":
  a click adds a point only in Add points.
- The 3D view shows trees and buildings where USGS lidar covers the route (most of the US): a 1 m surface built in
  the background by WebODM's worker from the public USGS 3DEP lidar, kept in WebODM's media
  (`plugins/mission_planner_data/lidar`) for every route nearby. "Lidar surface (US)" in the map's layers panel
  turns it off; the settings page shows its size and clears it.
- A tooltip beside the pointer on the editors' map, in 2D and 3D, gives the height above sea level of what is under
  it ("216.2 m ASL": the lidar surface where built, else the terrain), in the editor's units.
- The 3D view draws the route in the air at the height it is flown, with lines down to the surface, instead of
  lying on the ground (AGL routes over the route's terrain once fetched, else above the 3D view's surface).
- Each point of a waypoint route has a label with its height above the surface under it (trees and roofs where the
  lidar surface is built), in 2D and 3D; red when the point is below that surface.
- Drawing and editing work in the 3D view: the area editor's Polygon, Rectangle, Line and Edit tools, and in the
  waypoint editor adding points, drawing the subject's outline and dragging the points, whose markers are dragged
  where they are in the air.
- The 3D view shows where the route goes into the surface (the ground, trees or a roof): that part of the line red,
  seen through the surface, with 10 m of yellow before and after it; the side panel counts the collisions.
- The collisions show on the 2D map too (red and yellow on the route's lines, the same count in the side panel). Both
  views check the route every 5 m against the finest surface (the lidar's where built, else the terrain), whatever
  the zoom, and the lidar surface is built when a route is opened, in 2D too. Over the route's line, the pointer's
  tooltip adds the route's height above the surface there.
- ASL without the takeoff point's ground height: a red hint under the takeoff point and under the ASL button (it
  showed only at the bottom of the side panel), and the height fetched when ASL is picked or the takeoff point set
  in ASL (not on opening a route; the route's cached height for the same point is used without a call).
- Fixed: in 3D, an area or linear route in the ASL altitude mode was drawn at its height above sea level (about
  30 m, under the ground) instead of the takeoff point's ground height plus its height, as it is flown.
- Fixed: in 3D, the markers of an AGL waypoint route whose points had no ground height yet stayed on the ground.
- The editors' map shows the arrow cursor instead of an open hand (the hand while dragging).
- Fixed: the mission's reference takeoff point (`takeOffRefPoint`) carried the ground height above sea level where
  Pilot 2 reads an ellipsoidal one (DJI's WPML reference; every Pilot 2 export), putting the point about 33 m too
  high where the samples were flown; and an imported mission's ellipsoidal height showed as "Ground height at the takeoff point (m
  above sea level)". Heights are now converted with the EGM96 geoid (NGA's grid, downloaded once from PROJ's CDN into
  `plugins/mission_planner_data/grids`). The flight's own heights were not affected. Routes imported before this
  keep the old value: press "Fetch from elevation data" on them.

## 1.0.0 (2026-11-17, not published)

The Mission Planner moved here from LuxODM (where it was version 0.9.0), to install on WebODM as a plugin.

- Runs on an unmodified WebODM 3.3.2 or 4.0.0: routes are kept in WebODM's plugin data (no tables of its own), the
  terrain under a route in the plugin's folder; heights from a task's DSM work without PostGIS.
- Enabled when installed.
- MapLibre 6.16.0 (was 5.24.0): fixes GHSA-jrc7-96c5-q579 (a script in a basemap's attribution text could run). The
  map needs a browser with WebGL2 and ES2022.
- The OpenTopography key is set by an administrator on the Mission Planner page, under Settings (tried with
  OpenTopography before it is saved, never shown), or by `WO_OPENTOPOGRAPHY_API_KEY` in WebODM's environment, which
  wins when set. A refused key, or a missing one, says where to change it.
- An error reaching OpenTopography no longer shows the key (the request's URL, repeated in the error, held it).
- LuxODM's routes are imported on the Mission Planner page > Settings page, from the file LuxODM's
  `manage.py export_routes` writes: each to the account of its owner's username, with its settings, terrain and
  times; a route whose owner has no account is skipped and reported.
- The routes list's rename button shows (its icon was blank).
- A route's terrain is kept in WebODM's media beside the plugin (`plugins/mission_planner_data/terrain`), so deleting
  the plugin to upgrade it keeps the terrain, as it keeps the routes.
