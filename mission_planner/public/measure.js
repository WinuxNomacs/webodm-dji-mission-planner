// The editors' Pointer tool: each click on the map puts a dot there, labelled with the height above sea level of the
// surface under it ("216.2 m ASL", read like the pointer tooltip's, pointer_height.js); from the second dot on, a
// dotted line joins it to the one before, labelled in its middle with the difference ("+12.3 m": the later dot minus
// the earlier). A click on a dot clears them all, as does the editor when another tool is chosen. Nothing is saved.
// Plain ES5, the map and MapLibre passed in, so that it can be tested.
(function (root) {
    var M_TO_FT = 3.28084, ID = "mp-measure";
    var Height = root.MissionPlannerPointerHeight || (typeof require === "function" ? require("./pointer_height") : null);

    // A dot's label: "216.2 m ASL" (as the pointer tooltip says it), "…" while it is read, "no height" when it can't be
    function dotText(height, system) {
        if (height === undefined) return "…";
        if (height === null || !isFinite(height)) return "no height";
        return Height.formatHeight(height, system) + " ASL";
    }

    // The difference from one dot to the next (to minus from), one decimal, in the editor's units: "+12.3 m", "-4.0 ft".
    // "" while either height is missing.
    function diffText(from, to, system) {
        if (from === null || to === null || from === undefined || to === undefined || !isFinite(from) || !isFinite(to)) return "";
        var d = (to - from) * (system === "imperial" ? M_TO_FT : 1);
        var shown = Math.abs(d).toFixed(1);
        return (d < 0 && Number(shown) !== 0 ? "-" : "+") + shown + (system === "imperial" ? " ft" : " m");
    }

    // The dotted lines between the dots ([[lng, lat], ...]), each with its middle (where its label goes)
    function segments(dots) {
        var out = [];
        for (var i = 1; i < dots.length; i++) {
            var a = dots[i - 1], b = dots[i];
            out.push({from: i - 1, to: i, coordinates: [a, b], middle: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]});
        }
        return out;
    }

    function linesGeojson(dots) {
        return {type: "FeatureCollection", features: segments(dots).map(function (s) {
            return {type: "Feature", properties: {}, geometry: {type: "LineString", coordinates: s.coordinates}};
        })};
    }

    // opts: {maplibregl, map, doc, heightAt(lng, lat) -> Promise<{height} | null>, units() -> "metric" | "imperial",
    //        before: a layer id the lines go under (optional)}
    // Returns {click(e) -> handled: a MapLibre click (on a dot: clear; else a new dot), clear(), relabel(), reread(), count()}
    function createMeasure(opts) {
        var doc = opts.doc || root.document;
        var dots = [];           // {lngLat: [lng, lat], height: undefined (being read) | null | meters, marker, label}
        var diffs = [];          // the line labels' markers

        function ensureLayer() {
            if (opts.map.getSource(ID)) return;
            opts.map.addSource(ID, {type: "geojson", data: linesGeojson([])});
            // Dark dots ringed in white, so that they show on imagery and on maps: the two layers' dashes are the same
            // in pixels (MapLibre's dash lengths are in line widths)
            opts.map.addLayer({id: ID + "-halo", type: "line", source: ID, layout: {"line-cap": "round"},
                               paint: {"line-color": "#fff", "line-width": 7, "line-dasharray": [0.15 * 4 / 7, 2.4 * 4 / 7]}}, opts.before);
            opts.map.addLayer({id: ID, type: "line", source: ID, layout: {"line-cap": "round"},
                               paint: {"line-color": "#212121", "line-width": 4, "line-dasharray": [0.15, 2.4]}}, opts.before);
        }

        function marker(className, lngLat) {
            var el = doc.createElement("div");
            el.className = className;
            // a line's label sits just below its middle, clear of the dots' labels (beside the dots) on a level line
            var o = className === "mp-measure-diff" ? {element: el, offset: [0, 16]} : {element: el};
            return new opts.maplibregl.Marker(o).setLngLat(lngLat).addTo(opts.map);
        }

        function show() {
            var system = opts.units();
            dots.forEach(function (d) { d.label.textContent = dotText(d.height, system); });
            diffs.forEach(function (m) { m.remove(); });
            diffs = segments(dots.map(function (d) { return d.lngLat; })).map(function (s) {
                var text = diffText(dots[s.from].height, dots[s.to].height, system);
                var m = marker("mp-measure-diff", s.middle);
                m.getElement().textContent = text;
                m.getElement().hidden = !text;
                return m;
            });
            ensureLayer();
            opts.map.getSource(ID).setData(linesGeojson(dots.map(function (d) { return d.lngLat; })));
        }

        // Reads a dot's height; an answer for a dot cleared meanwhile is dropped
        function read(dot) {
            opts.heightAt(dot.lngLat[0], dot.lngLat[1]).then(function (h) {
                if (dots.indexOf(dot) < 0) return;
                dot.height = h && isFinite(h.height) ? h.height : null;
                show();
            }, function () {
                if (dots.indexOf(dot) < 0) return;
                dot.height = null;
                show();
            });
        }

        function add(lng, lat) {
            var m = marker("mp-measure-dot", [lng, lat]);
            var label = doc.createElement("span");
            label.className = "mp-measure-label";
            m.getElement().appendChild(label);
            var dot = {lngLat: [lng, lat], height: undefined, marker: m, label: label};
            dots.push(dot);
            show();
            read(dot);
        }

        function clear() {
            dots.forEach(function (d) { d.marker.remove(); });
            diffs.forEach(function (m) { m.remove(); });
            dots = [];
            diffs = [];
            if (opts.map.getSource(ID)) opts.map.getSource(ID).setData(linesGeojson([]));
        }

        function click(e) {
            var target = e.originalEvent && e.originalEvent.target;
            if (target && target.closest && target.closest(".mp-measure-dot")) { clear(); return true; }
            add(e.lngLat.lng, e.lngLat.lat);
            return true;
        }

        // The surface changed (the lidar's built, or turned on or off): every dot read again, its label kept meanwhile
        function reread() { dots.forEach(read); }

        return {click: click, clear: clear, relabel: function () { if (dots.length) show(); }, reread: reread,
                count: function () { return dots.length; }};
    }

    var api = {createMeasure: createMeasure, dotText: dotText, diffText: diffText, segments: segments};
    root.MissionPlannerMeasure = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
