// MapLibre 6 is an ES module only: this makes it the global the planner's ES5 scripts use. Loaded as
// <script type="module"> before them (planner.html, waypoint_planner.html)
import * as maplibregl from "./node_modules/maplibre-gl/dist/maplibre-gl.mjs";

window.maplibregl = maplibregl;
