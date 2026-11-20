// The form of the route in the planner's side panel: reading and writing it, the segmented buttons, the switches, and the
// ground sample distances that follow the height (and the height that follows them). Plain DOM, no map library, so that it
// can be tested. planner.js gives it the page and gets told when something changed.
(function (root) {
    // form field -> element id. "checkbox" fields are true/false switches; "unit" fields are always kept in the DOM
    // and read/written in the form's current display unit, but read()/write() convert them to/from metric at the
    // boundary - the route is always planned and saved in metric (see setUnits below). The rest hold text as-is.
    var FIELDS = {
        name: {id: "mp-name"}, lens_visible: {id: "mp-lens-visible", checkbox: true}, lens_ir: {id: "mp-lens-ir", checkbox: true},
        height: {id: "mp-height", unit: "length"}, direction: {id: "mp-direction"}, overlap_h: {id: "mp-overlap-h"}, overlap_w: {id: "mp-overlap-w"},
        margin: {id: "mp-margin", unit: "length"}, speed: {id: "mp-speed", unit: "speed"}, altitude_mode: {id: "mp-altitude-mode"}, takeoff_mode: {id: "mp-takeoff-mode"},
        takeoff_security_height: {id: "mp-tsh", unit: "length"}, rth_height: {id: "mp-rth", unit: "length"}, transitional_speed: {id: "mp-transitional", unit: "speed"},
        elevation_optimize: {id: "mp-elevation", checkbox: true}, avoid_limit_area: {id: "mp-geozone", checkbox: true},
        photo_mode: {id: "mp-photo-mode"}, takeoff_altitude: {id: "mp-takeoff-altitude", unit: "length"}, finish_action: {id: "mp-finish"},
        exit_on_rc_lost: {id: "mp-rclost"},
        // Oblique only (see planner_core.js's DEFAULTS comment): gimbal_pitch/inclined_overlap_h/w are plain
        // degrees/percent, no unit conversion, like direction/overlap_h/overlap_w. inclined_speed converts like speed.
        collection_mode: {id: "mp-collection-mode"}, surface_follow: {id: "mp-surface-follow"}, gimbal_pitch: {id: "mp-gimbal-pitch"},
        terrain_source: {id: "mp-terrain-source"},
        inclined_overlap_h: {id: "mp-inclined-overlap-h"}, inclined_overlap_w: {id: "mp-inclined-overlap-w"},
        inclined_speed: {id: "mp-inclined-speed", unit: "speed"},
        // ASL only: the WGS84-ellipsoidal ground height at the takeoff point. Like takeoff_altitude, a length in
        // meters - but never typed by hand, only ever written by the "fetch from elevation data" action in
        // planner.js (see planner_core.js's DEFAULTS comment), so it has no label/row of its own.
        takeoff_ellipsoidal_height: {id: "mp-takeoff-ellipsoidal-height", unit: "length"},
        // Linear routes only: the strip's widths each side of the center line, and whether one line covers it
        left_extend: {id: "mp-left-extend", unit: "length"}, right_extend: {id: "mp-right-extend", unit: "length"},
        single_line: {id: "mp-single-line", checkbox: true},
        // Geometric routes only: the WGS84-ellipsoidal heights of the block's base and top, in meters whatever the units
        // (as a slope's corner heights)
        base: {id: "mp-base"}, top: {id: "mp-top"}, roof: {id: "mp-roof", checkbox: true}
        // A page leaves out the fields its route type does not have (a linear route has no direction, margin, photo
        // mode or oblique collection): read() and write() skip them.
        // mp-inclined-speed-toggle ("set oblique speed separately") is NOT a field here: it doesn't carry its own
        // saved state, it just enables/disables mp-inclined-speed and mirrors whether that field is blank - see
        // refresh()/write() and its own listener below.
    };

    var HEIGHT_LABELS = {agl: "Height above the ground (%s)", alt: "Height above the takeoff point (%s)",
                         asl: "Height above the ground, using elevation data (%s)", face: "Distance from the face (%s)",
                         walls: "Distance from the walls (%s)"};
    // field -> {id of its label, text template ("%s" is the unit)}, for the other fields whose label shows a unit. A
    // page can give a label its own template in data-unit-text (a slope route's takeoff height is not above sea level).
    var UNIT_LABELS = {
        takeoff_altitude: {id: "mp-takeoff-altitude-label", text: "Ground height at the takeoff point (%s above sea level)"},
        takeoff_security_height: {id: "mp-tsh-label", text: "Safe takeoff altitude (%s)"},
        rth_height: {id: "mp-rth-label", text: "Return height (%s)"},
        margin: {id: "mp-margin-label", text: "Margin (%s)"},
        left_extend: {id: "mp-left-extend-label", text: "Width to the left (%s)"},
        right_extend: {id: "mp-right-extend-label", text: "Width to the right (%s)"},
        speed: {id: "mp-speed-label", text: "Global flight speed (%s)"},
        transitional_speed: {id: "mp-transitional-label", text: "Takeoff speed (%s)"},
        inclined_speed: {id: "mp-inclined-speed-label", text: "Oblique speed (%s)"}
    };
    var UNIT_LABEL_TEXT = {length: "m", speed: "m/s"}, IMPERIAL_LABEL_TEXT = {length: "ft", speed: "mph"};

    // model: the route's aircraft ("m4t" when left out); only its cameras are shown and offered
    function createRouteForm(doc, Core, onChange, model) {
        function el(id) { return doc.getElementById(id); }
        model = model || "m4t";
        var cameras = Object.keys(Core.GSD_PER_M_BY_MODEL[model]);
        // A model without the real-time terrain follow flies AGL over the terrain model only (drones.json)
        var realtimeFollow = Core.DRONES[model].realtime_follow !== false;

        // The route is always planned and saved in metric; only the DOM value of a "unit" field is ever shown in the
        // user's chosen display unit. metric<->display conversion happens right here, at the only two places that
        // cross the boundary: read() (display -> metric, going out) and write() (metric -> display, coming in).
        var unitSystem = "metric";

        function toDisplay(unit, metricValue) {
            if (unit === "length") return unitSystem === "imperial" ? Core.metersToFeet(metricValue) : metricValue;
            if (unit === "speed") return unitSystem === "imperial" ? Core.mpsToMph(metricValue) : metricValue;
            return metricValue;
        }

        function toMetric(unit, displayValue) {
            if (unit === "length") return unitSystem === "imperial" ? Core.feetToMeters(displayValue) : displayValue;
            if (unit === "speed") return unitSystem === "imperial" ? Core.mphToMps(displayValue) : displayValue;
            return displayValue;
        }

        function read() {
            var values = {};
            Object.keys(FIELDS).forEach(function (k) {
                var f = FIELDS[k], e = el(f.id);
                if (!e) return;
                if (f.checkbox) { values[k] = String(e.checked); return; }
                if (f.unit && e.value.trim() !== "") {
                    var n = parseFloat(e.value);
                    values[k] = isFinite(n) ? String(toMetric(f.unit, n)) : e.value;
                } else {
                    values[k] = e.value;
                }
            });
            return values;
        }

        function toBool(v) { return v === true || v === "true" || v === "1"; }
        function setText(id, text) { var e = el(id); if (e) e.textContent = text; }

        // The parts of the form that follow other parts: the segmented buttons, what is shown for the chosen mode, the slider,
        // and the unit shown in each length/speed label
        function refresh() {
            var collection = el(FIELDS.collection_mode.id) ? el(FIELDS.collection_mode.id).value : "ortho";

            [].forEach.call(doc.querySelectorAll("[data-seg]"), function (b) {
                b.classList.toggle("active", el(FIELDS[b.getAttribute("data-seg")].id).value === b.getAttribute("data-value"));
            });
            [].forEach.call(doc.querySelectorAll(".mp-chip"), function (chip) {
                chip.classList.toggle("active", chip.querySelector("input").checked);
            });
            var altitude = el("mp-altitude-mode").value, takeoff = el("mp-takeoff-mode").value;
            var lengthUnit = unitSystem === "imperial" ? IMPERIAL_LABEL_TEXT.length : UNIT_LABEL_TEXT.length;
            var speedUnit = unitSystem === "imperial" ? IMPERIAL_LABEL_TEXT.speed : UNIT_LABEL_TEXT.speed;
            setText("mp-height-label", (HEIGHT_LABELS[altitude] || HEIGHT_LABELS.agl).replace("%s", lengthUnit));
            if (el("mp-terrain-row")) el("mp-terrain-row").hidden = altitude !== "agl";
            // AGL follows the ground in real time or flies over the route's terrain; oblique AGL always flies over the terrain
            if (el("mp-dsm-row")) {
                el("mp-surface-follow-row").hidden = collection === "oblique" || !realtimeFollow;
                el("mp-dsm-row").hidden = collection !== "oblique" && el(FIELDS.surface_follow.id).value !== "dsm";
            }
            el("mp-safe-row").hidden = takeoff !== "safe";
            if (el("mp-oblique-fields")) {
                el("mp-oblique-fields").hidden = collection !== "oblique";
                // The "set separately" checkbox only enables/disables the field; the value itself (blank = automatic)
                // is the only thing actually saved - see the toggle's own listener below, and write()'s initial sync.
                el("mp-inclined-speed").disabled = !el("mp-inclined-speed-toggle").checked;
            }
            Object.keys(UNIT_LABELS).forEach(function (k) {
                var label = UNIT_LABELS[k], unitText = FIELDS[k].unit === "speed" ? speedUnit : lengthUnit, e = el(label.id);
                if (e) e.textContent = (e.getAttribute("data-unit-text") || label.text).replace("%s", unitText);
            });
            var direction = el("mp-direction") ? parseFloat(el("mp-direction").value) : NaN;
            if (isFinite(direction)) el("mp-direction-slider").value = ((direction % 360) + 360) % 360;
            followSingleLine();
        }

        // With one line over a linear route's strip, the height is the one at which the photos cover the strip: shown,
        // not typed
        function followSingleLine() {
            var single = el("mp-single-line");
            if (!single) return;
            ["mp-height", "mp-gsd-visible", "mp-gsd-ir"].forEach(function (id) { if (el(id)) el(id).disabled = single.checked; });
            if (!single.checked) return;
            var lenses = [];
            if (el("mp-lens-visible").checked) lenses.push("visable");
            if (el("mp-lens-ir").checked) lenses.push("ir");
            var left = toMetric("length", parseFloat(el("mp-left-extend").value)), right = toMetric("length", parseFloat(el("mp-right-extend").value));
            var h = left >= 0 && right >= 0 ? Core.singleLineHeight(lenses, left, right, model) : null;
            el("mp-height").value = h ? String(Core.roundTo(toDisplay("length", h), 2)) : "";
            showGsd();
        }

        // The ground sample distances that go with the height (always computed from the metric height)
        function showGsd() {
            var h = toMetric("length", parseFloat(el("mp-height").value));
            cameras.forEach(function (camera) {
                var input = el(camera === "visable" ? "mp-gsd-visible" : "mp-gsd-ir");
                input.value = isFinite(h) && h > 0 ? String(Core.roundTo(Core.gsdCm(camera, h, model), 2)) : "";
            });
        }

        function write(values) {
            Object.keys(FIELDS).forEach(function (k) {
                if (values[k] === undefined) return;
                var f = FIELDS[k], e = el(f.id);
                if (!e) return;
                if (f.checkbox) { e.checked = toBool(values[k]); return; }
                if (f.unit && String(values[k]).trim() !== "") {
                    var n = parseFloat(values[k]);
                    e.value = isFinite(n) ? String(Core.roundTo(toDisplay(f.unit, n), 2)) : values[k];
                } else {
                    e.value = values[k];
                }
            });
            // The toggle isn't a saved field (see FIELDS' comment on inclined_speed) - it just reflects whether the
            // loaded route has an explicit oblique speed, so reopening a route shows the field enabled when it's set.
            if (el("mp-inclined-speed-toggle")) el("mp-inclined-speed-toggle").checked = el("mp-inclined-speed").value.trim() !== "";
            // A model without the thermal camera never takes thermal photos (its IR chip is hidden in the page)
            if (cameras.indexOf("ir") === -1) el("mp-lens-ir").checked = false;
            if (!realtimeFollow && el(FIELDS.surface_follow.id)) el(FIELDS.surface_follow.id).value = "dsm";
            refresh();
            showGsd();
        }

        // Switches what unit length/speed fields are shown in. The route's actual (metric) values do not change:
        // whatever is currently in the form is read in the old unit, then written back out in the new one.
        function setUnits(system) {
            if (system !== "metric" && system !== "imperial") return;
            if (system === unitSystem) return;
            var metricValues = read();
            unitSystem = system;
            write(metricValues);
        }

        function changed() { if (onChange) onChange(); }

        // -- events ---------------------------------------------------------------------------------------------------
        [].forEach.call(doc.querySelectorAll("[data-seg]"), function (b) {
            b.addEventListener("click", function () {
                if (b.disabled) return;
                el(FIELDS[b.getAttribute("data-seg")].id).value = b.getAttribute("data-value");
                refresh();
                changed();
            });
        });

        // Height and ground sample distances are one setting seen three ways
        el("mp-height").addEventListener("input", function () { showGsd(); });
        [["mp-gsd-visible", "visable", "mp-gsd-ir", "ir"], ["mp-gsd-ir", "ir", "mp-gsd-visible", "visable"]].forEach(function (pair) {
            if (cameras.indexOf(pair[1]) === -1) return;
            el(pair[0]).addEventListener("input", function () {
                var cm = parseFloat(el(pair[0]).value);
                if (!isFinite(cm) || cm <= 0) return;
                el("mp-height").value = String(Core.roundTo(toDisplay("length", Core.heightForGsd(pair[1], cm, model)), 2));
                if (cameras.indexOf(pair[3]) !== -1) el(pair[2]).value = String(Core.roundTo(Core.gsdCm(pair[3], toMetric("length", parseFloat(el("mp-height").value)), model), 2));
                changed();
            });
        });

        // Unchecking "set oblique speed separately" clears the field back to blank (automatic) rather than just
        // disabling it with a stale number left inside - matches Pilot 2's own toggle behavior.
        if (el("mp-inclined-speed-toggle")) el("mp-inclined-speed-toggle").addEventListener("change", function () {
            if (!el("mp-inclined-speed-toggle").checked) el("mp-inclined-speed").value = "";
            refresh();
            changed();
        });

        var slider = el("mp-direction-slider");
        if (slider) {
            slider.addEventListener("input", function () { el("mp-direction").value = slider.value; changed(); });
            el("mp-direction").addEventListener("input", function () { refresh(); });
        }

        el("mp-form").addEventListener("input", function () { followSingleLine(); changed(); });
        el("mp-form").addEventListener("change", function () { refresh(); changed(); });

        return {read: read, write: write, refresh: refresh, showGsd: showGsd, setUnits: setUnits, getUnits: function () { return unitSystem; }};
    }

    var api = {FIELDS: FIELDS, createRouteForm: createRouteForm};
    root.MissionPlannerForm = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
