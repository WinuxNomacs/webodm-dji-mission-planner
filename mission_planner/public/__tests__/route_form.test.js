const Core = require('../planner_core');
const { createRouteForm, FIELDS } = require('../route_form');

// The parts of the page's form that route_form.js works with (ids as in templates/planner.html; a Python test checks that
// the template has every id used here)
const HTML = `
<form id="mp-form">
  <input id="mp-name">
  <label class="mp-chip"><input type="checkbox" id="mp-lens-visible" checked> Visible</label>
  <label class="mp-chip"><input type="checkbox" id="mp-lens-ir" checked> IR</label>
  <input id="mp-height"><label id="mp-height-label"></label><input id="mp-gsd-visible"><input id="mp-gsd-ir">
  <input id="mp-direction"><input type="range" id="mp-direction-slider" min="0" max="360">
  <input id="mp-overlap-h"><input id="mp-overlap-w"><input id="mp-margin"><input id="mp-speed">
  <input type="hidden" id="mp-altitude-mode" value="agl"><input type="hidden" id="mp-takeoff-mode" value="safe">
  <button type="button" id="b-asl" data-seg="altitude_mode" data-value="asl">ASL</button>
  <button type="button" id="b-alt" data-seg="altitude_mode" data-value="alt">ALT</button>
  <button type="button" id="b-agl" data-seg="altitude_mode" data-value="agl">AGL</button>
  <input type="hidden" id="mp-takeoff-ellipsoidal-height">
  <button type="button" id="b-direct" data-seg="takeoff_mode" data-value="direct">Direct</button>
  <button type="button" id="b-safe" data-seg="takeoff_mode" data-value="safe">Safe</button>
  <div id="mp-terrain-row"><input type="hidden" id="mp-surface-follow" value="realtime"><div id="mp-surface-follow-row"><button type="button" id="b-realtime" data-seg="surface_follow" data-value="realtime">Real-time follow</button><button type="button" id="b-dsm" data-seg="surface_follow" data-value="dsm">Terrain model</button></div><div id="mp-dsm-row" hidden><input type="hidden" id="mp-terrain-source" value="lidar"><div><button type="button" data-seg="terrain_source" data-value="lidar">Lidar surface (trees, roofs)</button><button type="button" data-seg="terrain_source" data-value="cop30">COP30</button></div></div></div><div id="mp-safe-row"></div>
  <input id="mp-tsh"><input id="mp-rth"><input id="mp-transitional">
  <label class="mp-chip"><input type="checkbox" id="mp-elevation"> Elevation optimization</label><input type="checkbox" id="mp-geozone">
  <select id="mp-photo-mode"><option value="distance">d</option><option value="time">t</option></select>
  <input id="mp-takeoff-altitude"><select id="mp-finish"><option value="goHome">h</option><option value="autoLand">l</option></select>
  <select id="mp-rclost"><option value="goContinue">c</option><option value="executeLostAction">e</option></select>
  <input type="hidden" id="mp-collection-mode" value="ortho">
  <button type="button" id="b-ortho" data-seg="collection_mode" data-value="ortho">Ortho</button>
  <button type="button" id="b-oblique" data-seg="collection_mode" data-value="oblique">Oblique</button>
  <div id="mp-oblique-fields">
    <input id="mp-gimbal-pitch"><input id="mp-inclined-overlap-h"><input id="mp-inclined-overlap-w">
    <input type="checkbox" id="mp-inclined-speed-toggle">
    <input id="mp-inclined-speed" disabled><label id="mp-inclined-speed-label"></label>
  </div>
</form>`;

let form, changes;
const $ = id => document.getElementById(id);
const type = (id, value) => { $(id).value = value; $(id).dispatchEvent(new Event("input", {bubbles: true})); };
const click = id => $(id).dispatchEvent(new MouseEvent("click", {bubbles: true}));

beforeEach(() => {
    document.body.innerHTML = HTML;
    changes = 0;
    form = createRouteForm(document, Core, () => { changes++; });
    form.write(Core.DEFAULTS);
    changes = 0;
});

describe("reading and writing", () => {
    it("writes the defaults and reads them back", () => {
        expect(form.read()).toEqual(Object.assign({}, Core.DEFAULTS, {lens_visible: "true", lens_ir: "true"}));
    });

    it("has a field for everything the core reads", () => {
        Object.keys(Core.DEFAULTS).forEach(k => expect(Object.keys(FIELDS)).toContain(k));
    });

    it("reads switches as true and false", () => {
        form.write({lens_ir: "false", elevation_optimize: "false", avoid_limit_area: "true"});
        const v = form.read();
        expect([v.lens_ir, v.elevation_optimize, v.avoid_limit_area]).toEqual(["false", "false", "true"]);
        form.write({lens_ir: true});
        expect(form.read().lens_ir).toBe("true");
    });

    it("leaves out what it is not given", () => {
        form.write({height: "75"});
        expect(form.read().height).toBe("75");
        expect(form.read().overlap_h).toBe("80");
    });

    it("what is read is what the core accepts", () => {
        expect(Core.parseForm(form.read()).ok).toBe(true);
    });
});

describe("segmented buttons", () => {
    it("show the current choice", () => {
        expect($("b-agl").classList.contains("active")).toBe(true);
        expect($("b-alt").classList.contains("active")).toBe(false);
        expect($("b-safe").classList.contains("active")).toBe(true);
        form.write({altitude_mode: "alt", takeoff_mode: "direct"});
        expect($("b-alt").classList.contains("active")).toBe(true);
        expect($("b-direct").classList.contains("active")).toBe(true);
        expect($("b-agl").classList.contains("active")).toBe(false);
    });

    it("change the choice and announce it", () => {
        click("b-alt");
        expect(form.read().altitude_mode).toBe("alt");
        expect($("b-alt").classList.contains("active")).toBe(true);
        expect(changes).toBe(1);
        click("b-direct");
        expect(form.read().takeoff_mode).toBe("direct");
    });

    it("ignore a disabled button", () => {
        $("b-alt").disabled = true;
        click("b-alt");
        expect(form.read().altitude_mode).toBe("agl");
        expect(changes).toBe(0);
    });

    it("change what is shown: the label of the height, the terrain follow and the safe altitude", () => {
        expect($("mp-height-label").textContent).toBe("Height above the ground (m)");
        expect($("mp-terrain-row").hidden).toBe(false);
        expect($("mp-safe-row").hidden).toBe(false);
        click("b-alt");
        expect($("mp-height-label").textContent).toBe("Height above the takeoff point (m)");
        expect($("mp-terrain-row").hidden).toBe(true);
        click("b-direct");
        expect($("mp-safe-row").hidden).toBe(true);
        click("b-safe");
        expect($("mp-safe-row").hidden).toBe(false);
    });

    it("selects ASL and shows the elevation-data height label, with the terrain row still hidden", () => {
        click("b-asl");
        expect(form.read().altitude_mode).toBe("asl");
        expect($("b-asl").classList.contains("active")).toBe(true);
        expect($("mp-height-label").textContent).toBe("Height above the ground, using elevation data (m)");
        expect($("mp-terrain-row").hidden).toBe(true);
    });
});

describe("oblique collection", () => {
    it("hides the oblique fields until Oblique is chosen", () => {
        expect($("mp-oblique-fields").hidden).toBe(true);
        click("b-oblique");
        expect($("mp-oblique-fields").hidden).toBe(false);
        click("b-ortho");
        expect($("mp-oblique-fields").hidden).toBe(true);
    });

    it("keeps the AGL height mode when Oblique is chosen", () => {
        click("b-oblique");
        expect(form.read().altitude_mode).toBe("agl");
        expect($("b-agl").disabled).toBe(false);
        expect($("b-agl").classList.contains("active")).toBe(true);
    });

    it("shows the terrain fetch instead of the follow choice for oblique AGL", () => {
        expect([$("mp-surface-follow-row").hidden, $("mp-dsm-row").hidden]).toEqual([false, true]);
        click("b-oblique");
        expect([$("mp-surface-follow-row").hidden, $("mp-dsm-row").hidden]).toEqual([true, false]);
        click("b-alt");
        expect($("mp-terrain-row").hidden).toBe(true);
        click("b-ortho");
        click("b-agl");
        expect([$("mp-surface-follow-row").hidden, $("mp-dsm-row").hidden]).toEqual([false, true]);
    });

    it("shows the terrain fetch when ortho AGL flies over the terrain model", () => {
        expect($("b-realtime").classList.contains("active")).toBe(true);
        click("b-dsm");
        expect(form.read().surface_follow).toBe("dsm");
        expect([$("b-dsm").classList.contains("active"), $("mp-dsm-row").hidden]).toEqual([true, false]);
        click("b-realtime");
        expect($("mp-dsm-row").hidden).toBe(true);
    });

    it("keeps the oblique speed field disabled until 'set separately' is checked", () => {
        expect($("mp-inclined-speed").disabled).toBe(true);
        $("mp-inclined-speed-toggle").checked = true;
        $("mp-inclined-speed-toggle").dispatchEvent(new Event("change", {bubbles: true}));
        expect($("mp-inclined-speed").disabled).toBe(false);
    });

    it("clears the oblique speed back to automatic when 'set separately' is unchecked", () => {
        $("mp-inclined-speed-toggle").checked = true;
        $("mp-inclined-speed-toggle").dispatchEvent(new Event("change", {bubbles: true}));
        type("mp-inclined-speed", "12");
        expect(form.read().inclined_speed).toBe("12");

        $("mp-inclined-speed-toggle").checked = false;
        $("mp-inclined-speed-toggle").dispatchEvent(new Event("change", {bubbles: true}));
        expect($("mp-inclined-speed").value).toBe("");
        expect($("mp-inclined-speed").disabled).toBe(true);
        expect(form.read().inclined_speed).toBe("");
    });

    it("checks the toggle and enables the field when a route with an explicit oblique speed is loaded", () => {
        form.write(Object.assign({}, Core.DEFAULTS, {collection_mode: "oblique", inclined_speed: "12"}));
        expect($("mp-inclined-speed-toggle").checked).toBe(true);
        expect($("mp-inclined-speed").disabled).toBe(false);
    });

    it("leaves the toggle unchecked and the field disabled when a route has no explicit oblique speed", () => {
        form.write(Object.assign({}, Core.DEFAULTS, {collection_mode: "oblique", inclined_speed: ""}));
        expect($("mp-inclined-speed-toggle").checked).toBe(false);
        expect($("mp-inclined-speed").disabled).toBe(true);
    });
});

describe("chip toggles", () => {
    it("highlights a chip while its checkbox is checked, and greys it out when unchecked", () => {
        expect($("mp-lens-visible").closest(".mp-chip").classList.contains("active")).toBe(true);
        expect($("mp-lens-ir").closest(".mp-chip").classList.contains("active")).toBe(true);
        $("mp-lens-ir").checked = false;
        $("mp-lens-ir").dispatchEvent(new Event("change", {bubbles: true}));
        expect($("mp-lens-ir").closest(".mp-chip").classList.contains("active")).toBe(false);
        expect($("mp-lens-visible").closest(".mp-chip").classList.contains("active")).toBe(true);
    });

    it("highlights elevation optimization the same way", () => {
        expect($("mp-elevation").closest(".mp-chip").classList.contains("active")).toBe(true);
        $("mp-elevation").checked = false;
        $("mp-elevation").dispatchEvent(new Event("change", {bubbles: true}));
        expect($("mp-elevation").closest(".mp-chip").classList.contains("active")).toBe(false);
    });
});

describe("height and ground sample distance", () => {
    it("show the distance of each camera for the height", () => {
        type("mp-height", "50");
        expect($("mp-gsd-ir").value).toBe("5");
        expect($("mp-gsd-visible").value).toBe("1.79");
    });

    it("follow the height when it is written", () => {
        form.write({height: "100"});
        expect($("mp-gsd-ir").value).toBe("10");
    });

    it("empty out when the height is not a number", () => {
        type("mp-height", "abc");
        expect($("mp-gsd-ir").value).toBe("");
        type("mp-height", "0");
        expect($("mp-gsd-visible").value).toBe("");
    });

    it("change the height, and the other camera, when one of them is typed", () => {
        type("mp-gsd-ir", "5");
        expect($("mp-height").value).toBe("50");
        expect($("mp-gsd-visible").value).toBe("1.79");
        expect(changes).toBeGreaterThan(0);

        type("mp-gsd-visible", "1.78");
        expect(parseFloat($("mp-height").value)).toBeCloseTo(49.78, 1);
        expect($("mp-gsd-ir").value).toBe("4.98");
    });

    it("ignore what is not a distance", () => {
        type("mp-height", "30");
        type("mp-gsd-ir", "");
        type("mp-gsd-ir", "-2");
        type("mp-gsd-ir", "x");
        expect($("mp-height").value).toBe("30");
    });

    it("keep the height a real number after typing a distance", () => {
        type("mp-gsd-ir", "3.3");
        expect(Core.parseForm(form.read()).values.height).toBeCloseTo(33, 6);
    });
});

describe("a Matrice 4E route", () => {
    beforeEach(() => {
        document.body.innerHTML = HTML;    // without the Matrice 4T form the outer beforeEach made on the page
        form = createRouteForm(document, Core, () => { changes++; }, "m4e");
        form.write(Core.DEFAULTS);
    });

    it("never turns on the thermal camera it does not have", () => {
        expect($("mp-lens-ir").checked).toBe(false);
        form.write({lens_ir: "true"});
        expect($("mp-lens-ir").checked).toBe(false);
    });

    it("shows the ground sample distance of its own wide camera only", () => {
        type("mp-height", "50");
        expect($("mp-gsd-visible").value).toBe(String(Core.roundTo(5000 / 3725, 2)));
        expect($("mp-gsd-ir").value).toBe("");
    });

    it("sets the height from its wide camera's ground sample distance", () => {
        type("mp-gsd-visible", "2");
        expect(parseFloat($("mp-height").value)).toBeCloseTo(74.5, 1);
        expect($("mp-gsd-ir").value).toBe("");
    });
});

describe("a Matrice 30 route", () => {
    beforeEach(() => {
        document.body.innerHTML = HTML;
        form = createRouteForm(document, Core, () => { changes++; }, "m30");
        form.write(Core.DEFAULTS);
    });

    it("flies AGL over the terrain model only: no real-time follow is offered", () => {
        expect(form.read().surface_follow).toBe("dsm");
        expect($("mp-surface-follow-row").hidden).toBe(true);
        expect($("mp-dsm-row").hidden).toBe(false);
        form.write({surface_follow: "realtime"});
        expect(form.read().surface_follow).toBe("dsm");
    });

    it("on a Matrice 4T the real-time follow stays offered", () => {
        document.body.innerHTML = HTML;
        form = createRouteForm(document, Core, () => { changes++; }, "m4t");
        form.write(Core.DEFAULTS);
        expect(form.read().surface_follow).toBe("realtime");
        expect($("mp-surface-follow-row").hidden).toBe(false);
    });
});

describe("course angle", () => {
    it("moves the slider with the number", () => {
        type("mp-direction", "181");
        expect($("mp-direction-slider").value).toBe("181");
        type("mp-direction", "-90");
        expect($("mp-direction-slider").value).toBe("270");
    });

    it("moves the number with the slider and announces it", () => {
        $("mp-direction-slider").value = "45";
        $("mp-direction-slider").dispatchEvent(new Event("input", {bubbles: true}));
        expect($("mp-direction").value).toBe("45");
        expect(changes).toBeGreaterThan(0);
    });

    it("follows a written direction", () => {
        form.write({direction: "300"});
        expect($("mp-direction-slider").value).toBe("300");
    });
});

describe("units", () => {
    it("defaults to metric and reads/writes metric regardless", () => {
        expect(form.getUnits()).toBe("metric");
        form.write({height: "50", speed: "10"});
        expect($("mp-height").value).toBe("50");
        expect($("mp-speed").value).toBe("10");
        expect(form.read().height).toBe("50");
        expect(form.read().speed).toBe("10");
    });

    it("displays length/speed fields in the chosen unit but still reads them back as metric", () => {
        form.write({height: "50", margin: "10", speed: "10", takeoff_security_height: "20"});
        form.setUnits("imperial");
        expect(form.getUnits()).toBe("imperial");
        expect(parseFloat($("mp-height").value)).toBeCloseTo(164.04, 1);   // 50 m
        expect(parseFloat($("mp-speed").value)).toBeCloseTo(22.37, 1);     // 10 m/s

        // the displayed feet/mph value is rounded to 2 decimals, so the round trip back to metric is close but not exact
        const read = form.read();
        expect(parseFloat(read.height)).toBeCloseTo(50, 2);
        expect(parseFloat(read.speed)).toBeCloseTo(10, 2);
        expect(Core.parseForm(read).ok).toBe(true);
    });

    it("leaves an empty optional field empty across a unit switch", () => {
        form.write({speed: "", takeoff_altitude: ""});
        form.setUnits("imperial");
        expect($("mp-speed").value).toBe("");
        expect($("mp-takeoff-altitude").value).toBe("");
        expect(form.read().speed).toBe("");
    });

    it("does not touch fields that have no unit", () => {
        form.write({direction: "45", overlap_h: "80"});
        form.setUnits("imperial");
        expect($("mp-direction").value).toBe("45");
        expect($("mp-overlap-h").value).toBe("80");
    });

    it("switching back to the same unit does nothing", () => {
        form.write({height: "50"});
        form.setUnits("metric");
        expect($("mp-height").value).toBe("50");
    });
});

describe("changes", () => {
    it("are announced for any field", () => {
        type("mp-overlap-h", "85");
        expect(changes).toBeGreaterThan(0);
        changes = 0;
        $("mp-elevation").checked = false;
        $("mp-elevation").dispatchEvent(new Event("change", {bubbles: true}));
        expect(changes).toBeGreaterThan(0);
    });
});

describe("a linear route", () => {
    // The linear page's form: no course angle, margin, photo mode or collection, and the strip's widths instead
    const LINEAR_HTML = HTML
        .replace(/<input id="mp-direction">.*\n/, "")
        .replace('<input id="mp-margin">', "")
        .replace(/<select id="mp-photo-mode">.*\n/, "")
        .replace(/<input type="hidden" id="mp-collection-mode"[\s\S]*<\/div>\n/, "")
        .replace("</form>", `<input id="mp-left-extend"><label id="mp-left-extend-label"></label>
  <input id="mp-right-extend"><label id="mp-right-extend-label"></label>
  <input type="checkbox" id="mp-single-line">
</form>`);

    beforeEach(() => {
        document.body.innerHTML = LINEAR_HTML;
        form = createRouteForm(document, Core, () => { changes++; });
        form.write(Object.assign({}, Core.DEFAULTS, Core.LINEAR_DEFAULTS));
        changes = 0;
    });

    it("reads and writes without the fields only an area has", () => {
        expect($("mp-direction")).toBeNull();
        form.write({left_extend: "30", right_extend: "20", single_line: "true"});
        const v = form.read();
        expect([v.left_extend, v.right_extend, v.single_line]).toEqual(["30", "20", "true"]);
        expect(v.direction).toBeUndefined();
        expect(Core.parseLinearForm(v, "m4t").ok).toBe(true);
    });

    it("flies a single line at the height that covers the strip, and does not let it be typed", () => {
        $("mp-single-line").checked = true;
        $("mp-single-line").dispatchEvent(new Event("input", {bubbles: true}));
        expect($("mp-height").disabled).toBe(true);
        expect($("mp-gsd-visible").disabled).toBe(true);
        expect(parseFloat($("mp-height").value)).toBeCloseTo(Core.singleLineHeight(["visable", "ir"], 50, 50, "m4t"), 1);

        type("mp-left-extend", "25");
        expect(parseFloat($("mp-height").value)).toBeCloseTo(Core.singleLineHeight(["visable", "ir"], 25, 50, "m4t"), 1);

        $("mp-single-line").checked = false;
        $("mp-single-line").dispatchEvent(new Event("input", {bubbles: true}));
        expect($("mp-height").disabled).toBe(false);
    });

    it("shows the strip's widths in feet in imperial units", () => {
        form.setUnits("imperial");
        expect($("mp-left-extend-label").textContent).toBe("Width to the left (ft)");
        expect(parseFloat($("mp-right-extend").value)).toBeCloseTo(164.04, 1);
        expect(parseFloat(form.read().right_extend)).toBeCloseTo(50, 2);
    });
});

describe("a slope route", () => {
    // The slope page's form: no course angle, margin, photo mode, collection, height mode or elevation optimization,
    // the distance from the face as the height, and the takeoff point's height not above sea level
    const SLOPE_HTML = HTML
        .replace(/<input id="mp-direction">.*\n/, "")
        .replace('<input id="mp-margin">', "")
        .replace(/<select id="mp-photo-mode">.*\n/, "")
        .replace(/<input type="hidden" id="mp-collection-mode"[\s\S]*<\/div>\n/, "")
        .replace('<input type="hidden" id="mp-altitude-mode" value="agl">', '<input type="hidden" id="mp-altitude-mode" value="face">')
        .replace(/ {2}<button type="button" id="b-a[sgl]+".*\n/g, "")
        .replace(/<div id="mp-terrain-row">.*?<div id="mp-dsm-row" hidden>.*?<\/div><\/div><\/div>/, "")
        .replace('<label class="mp-chip"><input type="checkbox" id="mp-elevation"> Elevation optimization</label>', "")
        .replace('<input id="mp-takeoff-altitude">', '<input id="mp-takeoff-altitude"><label id="mp-takeoff-altitude-label" data-unit-text="Ground height at the takeoff point (%s, WGS84 ellipsoidal, as the corners)"></label>');

    beforeEach(() => {
        document.body.innerHTML = SLOPE_HTML;
        form = createRouteForm(document, Core, () => { changes++; });
        form.write(Object.assign({}, Core.DEFAULTS, Core.SLOPE_DEFAULTS));
        changes = 0;
    });

    it("reads and writes the distance from the face as the height", () => {
        expect($("mp-terrain-row")).toBeNull();
        expect($("mp-height-label").textContent).toBe("Distance from the face (m)");
        expect($("mp-height").value).toBe("30");
        expect(Core.parseSlopeForm(form.read()).ok).toBe(true);
    });

    it("labels the takeoff point's height as the page says, in the units shown", () => {
        expect($("mp-takeoff-altitude-label").textContent).toBe("Ground height at the takeoff point (m, WGS84 ellipsoidal, as the corners)");
        form.setUnits("imperial");
        expect($("mp-takeoff-altitude-label").textContent).toBe("Ground height at the takeoff point (ft, WGS84 ellipsoidal, as the corners)");
        expect($("mp-height-label").textContent).toBe("Distance from the face (ft)");
    });
});

describe("a geometric route", () => {
    // The geometric page's form: the slope's, the distance from the walls as the height, with the base and the top
    const GEOMETRIC_HTML = HTML
        .replace(/<input id="mp-direction">.*\n/, "")
        .replace('<input id="mp-margin">', "")
        .replace('<input type="hidden" id="mp-altitude-mode" value="agl">', '<input type="hidden" id="mp-altitude-mode" value="walls"><input id="mp-base"><input id="mp-top"><input type="checkbox" id="mp-roof">');

    beforeEach(() => {
        document.body.innerHTML = GEOMETRIC_HTML;
        form = createRouteForm(document, Core, () => { changes++; });
        form.write(Object.assign({}, Core.DEFAULTS, Core.GEOMETRIC_DEFAULTS, {base: "214.47", top: "218.97"}));
        changes = 0;
    });

    it("reads and writes the distance from the walls as the height, and the base and the top in meters", () => {
        expect($("mp-height-label").textContent).toBe("Distance from the walls (m)");
        expect($("mp-height").value).toBe("10");
        form.setUnits("imperial");
        expect($("mp-height-label").textContent).toBe("Distance from the walls (ft)");
        expect(form.read()).toMatchObject({base: "214.47", top: "218.97", roof: "true"});
        expect(Core.parseGeometricForm(form.read()).ok).toBe(true);
        form.write({roof: "false"});
        expect($("mp-roof").checked).toBe(false);
        expect(Core.parseGeometricForm(form.read()).values.roof).toBe(false);
    });
});
