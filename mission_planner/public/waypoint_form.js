// The form of a waypoint route in the planner's side panel, and the panel of the selected point: reading and writing them,
// the segmented buttons and the switches. Plain DOM, no map library, so that it can be tested. waypoint_planner.js gives
// it the page and gets told when something changed (onChange for the route, onPointChange for the selected point).
(function (root) {
    // form field -> element id, as in route_form.js: "checkbox" fields are switches, "unit" fields are shown in the
    // chosen display unit and converted to metric by read() and from it by write() ("interval" fields only by distance)
    var FIELDS = {
        name: {id: "mp-name"}, lens_visible: {id: "mp-lens-visible", checkbox: true}, lens_ir: {id: "mp-lens-ir", checkbox: true},
        height: {id: "mp-height", unit: "length"}, height_mode: {id: "mp-height-mode"}, speed: {id: "mp-speed", unit: "speed"},
        gimbal_pitch: {id: "mp-gimbal-pitch"}, heading_mode: {id: "mp-heading-mode"}, turn_mode: {id: "mp-turn-mode"},
        takeoff_mode: {id: "mp-takeoff-mode"}, takeoff_security_height: {id: "mp-tsh", unit: "length"},
        rth_height: {id: "mp-rth", unit: "length"}, transitional_speed: {id: "mp-transitional", unit: "speed"},
        finish_action: {id: "mp-finish"}, exit_on_rc_lost: {id: "mp-rclost"}, avoid_limit_area: {id: "mp-geozone", checkbox: true},
        takeoff_altitude: {id: "mp-takeoff-altitude", unit: "length"},
        // the interval is a length when the photos are taken by distance and seconds when by time, so the mode comes
        // first and write() sets it before the interval
        video: {id: "mp-video", checkbox: true}, photo_interval_mode: {id: "mp-interval-mode"},
        photo_interval: {id: "mp-interval", unit: "interval"},
        // ASL only, written by the "fetch from elevation data" action (as in route_form.js)
        takeoff_ellipsoidal_height: {id: "mp-takeoff-ellipsoidal-height", unit: "length"},
        // AGL: the terrain the ground heights come from, "lidar" or "cop30" (as in route_form.js)
        terrain_source: {id: "mp-terrain-source"}
    };

    // The selected point's fields; height is a length, the rest degrees, seconds and a switch
    var POINT_FIELDS = {
        height: {id: "mp-point-height", unit: "length"}, heading: {id: "mp-point-heading"}, pitch: {id: "mp-point-pitch"},
        hover: {id: "mp-point-hover"}, photo: {id: "mp-point-photo", checkbox: true}
    };

    // A POI route's shape (settings.shape, without the drawn outline, which the planner keeps): the kind buttons have
    // data-shape-seg instead of data-seg
    var SHAPE_FIELDS = {
        kind: {id: "mp-shape-kind"}, radius: {id: "mp-shape-radius", unit: "length"}, width: {id: "mp-shape-width", unit: "length"},
        length: {id: "mp-shape-length", unit: "length"}, rotation: {id: "mp-shape-rotation"}, height: {id: "mp-shape-height", unit: "length"},
        distance: {id: "mp-shape-distance", unit: "length"}, count: {id: "mp-shape-count"}, start: {id: "mp-shape-start"},
        overlap: {id: "mp-shape-overlap"}, loops: {id: "mp-shape-loops"}, top: {id: "mp-shape-top", unit: "length"}
    };
    var SHAPE_UNIT_LABELS = {
        radius: {id: "mp-shape-radius-label", text: "Radius (%s)"}, width: {id: "mp-shape-width-label", text: "Width (%s)"},
        length: {id: "mp-shape-length-label", text: "Length (%s)"}, height: {id: "mp-shape-height-label", text: "Height of the subject (%s)"},
        distance: {id: "mp-shape-distance-label", text: "Distance from the subject (%s)"},
        top: {id: "mp-shape-top-label", text: "Highest loop at (%s)"}
    };
    var SHAPE_ROWS = {circle: "mp-shape-circle-rows", rectangle: "mp-shape-rectangle-rows", outline: "mp-shape-outline-rows"};

    var HEIGHT_LABELS = {alt: "Height above the takeoff point (%s)", asl: "Height above sea level (%s)",
                         agl: "Height above the ground under each point (%s)"};
    var UNIT_LABELS = {
        takeoff_altitude: {id: "mp-takeoff-altitude-label", text: "Ground height at the takeoff point (%s above sea level)"},
        takeoff_security_height: {id: "mp-tsh-label", text: "Safe takeoff altitude (%s)"},
        rth_height: {id: "mp-rth-label", text: "Return height (%s)"},
        speed: {id: "mp-speed-label", text: "Flight speed (%s)"},
        transitional_speed: {id: "mp-transitional-label", text: "Takeoff speed (%s)"}
    };
    var UNIT_LABEL_TEXT = {length: "m", speed: "m/s"}, IMPERIAL_LABEL_TEXT = {length: "ft", speed: "mph"};

    // model: the route's aircraft ("m4t" when left out); a model without the thermal camera never takes thermal photos
    function createWaypointForm(doc, Core, onChange, model, onPointChange) {
        function el(id) { return doc.getElementById(id); }
        model = model || "m4t";
        var cameras = Object.keys(Core.GSD_PER_M_BY_MODEL[model]);
        var unitSystem = "metric";

        function intervalUnit(unit) {
            if (unit !== "interval") return unit;
            return el("mp-interval-mode").value === "distance" ? "length" : null;
        }

        function toDisplay(unit, metricValue) {
            unit = intervalUnit(unit);
            if (unit === "length") return unitSystem === "imperial" ? Core.metersToFeet(metricValue) : metricValue;
            if (unit === "speed") return unitSystem === "imperial" ? Core.mpsToMph(metricValue) : metricValue;
            return metricValue;
        }

        function toMetric(unit, displayValue) {
            unit = intervalUnit(unit);
            if (unit === "length") return unitSystem === "imperial" ? Core.feetToMeters(displayValue) : displayValue;
            if (unit === "speed") return unitSystem === "imperial" ? Core.mphToMps(displayValue) : displayValue;
            return displayValue;
        }

        function toBool(v) { return v === true || v === "true" || v === "1"; }
        function setText(id, text) { var e = el(id); if (e) e.textContent = text; }

        function readFields(fields) {
            var values = {};
            Object.keys(fields).forEach(function (k) {
                var f = fields[k], e = el(f.id);
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

        function writeFields(fields, values) {
            Object.keys(fields).forEach(function (k) {
                if (values[k] === undefined) return;
                var f = fields[k], e = el(f.id), v = values[k] === null ? "" : values[k];
                if (f.checkbox) { e.checked = toBool(v); return; }
                if (f.unit && String(v).trim() !== "") {
                    var n = parseFloat(v);
                    e.value = isFinite(n) ? String(Core.roundTo(toDisplay(f.unit, n), 2)) : v;
                } else {
                    e.value = String(v);
                }
            });
        }

        function read() { return readFields(FIELDS); }

        // The shape of a POI route, in metric like read(); writeShape leaves the fields not given as they are
        function readShape() { return readFields(SHAPE_FIELDS); }
        function writeShape(shape) { writeFields(SHAPE_FIELDS, shape); refresh(); }

        function segInput(b) {
            var shapeField = b.getAttribute("data-shape-seg");
            return el(shapeField ? SHAPE_FIELDS[shapeField].id : FIELDS[b.getAttribute("data-seg")].id);
        }

        // The parts of the form that follow other parts: the segmented buttons, the chips, the safe takeoff row and the
        // labels that show a unit
        function refresh() {
            [].forEach.call(doc.querySelectorAll("[data-seg], [data-shape-seg]"), function (b) {
                b.classList.toggle("active", segInput(b).value === b.getAttribute("data-value"));
            });
            [].forEach.call(doc.querySelectorAll(".mp-chip"), function (chip) {
                chip.classList.toggle("active", chip.querySelector("input").checked);
            });
            var mode = el("mp-height-mode").value;
            var lengthUnit = unitSystem === "imperial" ? IMPERIAL_LABEL_TEXT.length : UNIT_LABEL_TEXT.length;
            var speedUnit = unitSystem === "imperial" ? IMPERIAL_LABEL_TEXT.speed : UNIT_LABEL_TEXT.speed;
            setText("mp-height-label", (HEIGHT_LABELS[mode] || HEIGHT_LABELS.alt).replace("%s", lengthUnit));
            setText("mp-point-height-label", "Height (" + lengthUnit + ", empty: the route's)");
            el("mp-safe-row").hidden = el("mp-takeoff-mode").value !== "safe";
            el("mp-point-heading-row").hidden = el("mp-heading-mode").value !== "manually";
            el("mp-poi-row").hidden = el("mp-heading-mode").value !== "towardPOI";
            var intervalMode = el("mp-interval-mode").value;
            el("mp-interval-row").hidden = intervalMode === "";
            setText("mp-interval-label", "A photo every (" + (intervalMode === "time" ? "s" : lengthUnit) + ")");
            Object.keys(UNIT_LABELS).forEach(function (k) {
                var label = UNIT_LABELS[k], unitText = FIELDS[k].unit === "speed" ? speedUnit : lengthUnit;
                setText(label.id, label.text.replace("%s", unitText));
            });
            if (el(SHAPE_FIELDS.kind.id)) {
                var kind = el(SHAPE_FIELDS.kind.id).value;
                Object.keys(SHAPE_ROWS).forEach(function (k) { el(SHAPE_ROWS[k]).hidden = k !== kind; });
                el("mp-shape-top-row").hidden = !(parseFloat(el(SHAPE_FIELDS.loops.id).value) > 1);
                Object.keys(SHAPE_UNIT_LABELS).forEach(function (k) {
                    setText(SHAPE_UNIT_LABELS[k].id, SHAPE_UNIT_LABELS[k].text.replace("%s", lengthUnit));
                });
            }
        }

        function write(values) {
            writeFields(FIELDS, values);
            if (cameras.indexOf("ir") === -1) el("mp-lens-ir").checked = false;
            refresh();
        }

        // The selected point, in metric like read(): {height, heading, pitch, hover: text, photo: "true"/"false"}
        function readPoint() { return readFields(POINT_FIELDS); }

        function writePoint(point) {
            writeFields(POINT_FIELDS, {height: point.height, heading: point.heading, pitch: point.pitch,
                                       hover: point.hover ? point.hover : "", photo: point.photo});
        }

        // Switches the unit the lengths and speeds are shown in; the metric values in the form stay the same
        function setUnits(system) {
            if (system !== "metric" && system !== "imperial") return;
            if (system === unitSystem) return;
            var metricValues = read(), pointValues = readPoint(), shapeValues = el(SHAPE_FIELDS.kind.id) ? readShape() : null;
            unitSystem = system;
            if (shapeValues) writeFields(SHAPE_FIELDS, shapeValues);
            write(metricValues);
            writeFields(POINT_FIELDS, pointValues);
        }

        function changed() { if (onChange) onChange(); }
        function pointChanged() { if (onPointChange) onPointChange(); }

        // -- events ---------------------------------------------------------------------------------------------------
        [].forEach.call(doc.querySelectorAll("[data-seg], [data-shape-seg]"), function (b) {
            b.addEventListener("click", function () {
                if (b.disabled) return;
                segInput(b).value = b.getAttribute("data-value");
                refresh();
                changed();
            });
        });
        el("mp-form").addEventListener("input", function (e) {
            if (e.target.id === SHAPE_FIELDS.loops.id) refresh();     // the highest loop's row shows as the count is typed
            changed();
        });
        el("mp-form").addEventListener("change", function () { refresh(); changed(); });
        el("mp-point-form").addEventListener("input", pointChanged);
        el("mp-point-form").addEventListener("change", pointChanged);

        return {read: read, write: write, refresh: refresh, readPoint: readPoint, writePoint: writePoint,
                readShape: readShape, writeShape: writeShape, setUnits: setUnits, getUnits: function () { return unitSystem; }};
    }

    var api = {FIELDS: FIELDS, POINT_FIELDS: POINT_FIELDS, SHAPE_FIELDS: SHAPE_FIELDS, createWaypointForm: createWaypointForm};
    root.MissionPlannerWaypointForm = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
