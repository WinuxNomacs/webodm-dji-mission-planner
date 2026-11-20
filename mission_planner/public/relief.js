// The 3D view's Relief: the ground coloured by its height (MapLibre's color-relief layer on the elevation source,
// "mp-dem"), from blue on the lowest ground round the route to red on its highest roofs, under a stronger hillshade,
// with the basemap's photo kept faint over it, so that the shapes of trees and buildings read whatever the photo shows
// (a photo taken at an angle leans tall buildings off the lidar's blocks, Phase 22). The colours span the heights read
// on a grid over the route and 100 m round it, again when the route moves or the lidar surface is built. Plain ES5,
// the map passed in, so that it can be tested.
(function (root) {
    var LAYER = "mp-relief", SOURCE = "mp-dem", HILLSHADE = "mp-hillshade", BASEMAP = "mp-basemap";
    var COLORS = ["#2b83ba", "#abdda4", "#ffffbf", "#fdae61", "#d7191c"];
    var RELIEF_OPACITY = 0.65, PHOTO_OPACITY = 0.45;
    var SHADE = {"hillshade-method": "igor", "hillshade-exaggeration": 0.5};          // with the relief
    var PLAIN = {"hillshade-method": "standard", "hillshade-exaggeration": 0.35};     // the editors' own, without it
    var GRID = 21, AROUND_M = 100, MIN_SPAN = 10, CUT = 0.02;

    // [lowest, highest] of the heights, the lowest and highest CUT left out, at least MIN_SPAN meters apart; null without any
    function heightRange(heights) {
        var h = (heights || []).filter(function (v) { return typeof v === "number" && isFinite(v); }).sort(function (a, b) { return a - b; });
        if (!h.length) return null;
        var lo = h[Math.floor((h.length - 1) * CUT)], hi = h[Math.ceil((h.length - 1) * (1 - CUT))];
        if (hi - lo < MIN_SPAN) { var mid = (lo + hi) / 2; lo = mid - MIN_SPAN / 2; hi = mid + MIN_SPAN / 2; }
        return [lo, hi];
    }

    // The color-relief layer's colours over [lowest, highest]
    function colorRamp(range) {
        var ramp = ["interpolate", ["linear"], ["elevation"]];
        COLORS.forEach(function (c, i) { ramp.push(range[0] + (range[1] - range[0]) * i / (COLORS.length - 1), c); });
        return ramp;
    }

    // n x n points over [west, south, east, north] and AROUND_M round it
    function gridPoints(b, n) {
        var lat = (b[1] + b[3]) / 2, dLat = AROUND_M / 110540, dLng = AROUND_M / (111320 * Math.cos(lat * Math.PI / 180));
        var w = b[0] - dLng, s = b[1] - dLat, e = b[2] + dLng, north = b[3] + dLat, out = [];
        for (var i = 0; i < n; i++) {
            for (var j = 0; j < n; j++) out.push([w + (e - w) * i / (n - 1), s + (north - s) * j / (n - 1)]);
        }
        return out;
    }

    // opts: {map, heightsAt(points) -> Promise<[meters or null]> (pointer_height.js's reader)}
    // Returns {apply(on, bounds) (the relief on in 3D over the route's bounds, or off), refresh(bounds) (its colours
    // again), basemapChanged() (a new basemap gets the faint photo too), isOn()}
    function createRelief(opts) {
        var map = opts.map, on = false, range = null, run = 0;

        function paint(id, props) {
            if (!map.getLayer(id)) return;
            Object.keys(props).forEach(function (k) { map.setPaintProperty(id, k, props[k]); });
        }
        function show() {
            if (!on || !range || !map.getSource(SOURCE)) return;
            if (map.getLayer(LAYER)) map.setPaintProperty(LAYER, "color-relief-color", colorRamp(range));
            else map.addLayer({id: LAYER, type: "color-relief", source: SOURCE,
                               paint: {"color-relief-color": colorRamp(range), "color-relief-opacity": RELIEF_OPACITY}},
                              map.getLayer(HILLSHADE) ? HILLSHADE : undefined);
            paint(HILLSHADE, SHADE);
            paint(BASEMAP, {"raster-opacity": PHOTO_OPACITY});
        }
        function hide() {
            if (map.getLayer(LAYER)) map.removeLayer(LAYER);
            paint(HILLSHADE, PLAIN);
            paint(BASEMAP, {"raster-opacity": 1});
        }
        function refresh(bounds) {
            if (!on || !bounds) return Promise.resolve();
            var mine = ++run;
            return opts.heightsAt(gridPoints(bounds, GRID)).then(function (heights) {
                if (mine !== run || !on) return;
                range = heightRange(heights) || range;
                show();
            });
        }
        function apply(value, bounds) {
            on = !!value;
            if (!on) { run++; hide(); return Promise.resolve(); }
            show();                                 // with the colours it had, until the new ones are read
            return refresh(bounds);
        }
        return {apply: apply, refresh: refresh, basemapChanged: function () { if (on && range) paint(BASEMAP, {"raster-opacity": PHOTO_OPACITY}); },
                isOn: function () { return on; }};
    }

    var api = {createRelief: createRelief, heightRange: heightRange, colorRamp: colorRamp, gridPoints: gridPoints,
               LAYER: LAYER, COLORS: COLORS, PHOTO_OPACITY: PHOTO_OPACITY, RELIEF_OPACITY: RELIEF_OPACITY};
    root.MissionPlannerRelief = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
