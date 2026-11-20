const Core = require('../planner_core');
const { createWaypointForm, FIELDS, POINT_FIELDS, SHAPE_FIELDS } = require('../waypoint_form');

// The parts of the page's forms that waypoint_form.js works with (ids as in templates/waypoint_planner.html; a Python test
// checks that the template has every id used here)
const HTML = `
<form id="mp-form">
  <input id="mp-name">
  <label class="mp-chip" id="chip-visible"><input type="checkbox" id="mp-lens-visible" checked> Visible</label>
  <label class="mp-chip"><input type="checkbox" id="mp-lens-ir" checked> IR</label>
  <input id="mp-height"><label id="mp-height-label"></label>
  <input type="hidden" id="mp-height-mode" value="alt">
  <button type="button" id="b-alt" data-seg="height_mode" data-value="alt">ALT</button>
  <button type="button" id="b-asl" data-seg="height_mode" data-value="asl">ASL</button>
  <button type="button" id="b-agl" data-seg="height_mode" data-value="agl">AGL</button>
  <input id="mp-speed"><label id="mp-speed-label"></label><input id="mp-gimbal-pitch">
  <input type="hidden" id="mp-heading-mode" value="followWayline">
  <button type="button" id="b-follow" data-seg="heading_mode" data-value="followWayline">Follow</button>
  <button type="button" id="b-manual" data-seg="heading_mode" data-value="manually">Manual</button>
  <button type="button" id="b-poi" data-seg="heading_mode" data-value="towardPOI">POI</button>
  <div id="mp-poi-row"></div>
  <input type="hidden" id="mp-turn-mode" value="stop">
  <button type="button" id="b-stop" data-seg="turn_mode" data-value="stop">Stop</button>
  <button type="button" id="b-pass" data-seg="turn_mode" data-value="pass">Pass</button>
  <button type="button" id="b-curve" data-seg="turn_mode" data-value="curve">Curve</button>
  <input type="checkbox" id="mp-video">
  <input type="hidden" id="mp-interval-mode" value="">
  <button type="button" id="b-int-off" data-seg="photo_interval_mode" data-value="">Off</button>
  <button type="button" id="b-int-distance" data-seg="photo_interval_mode" data-value="distance">Distance</button>
  <button type="button" id="b-int-time" data-seg="photo_interval_mode" data-value="time">Time</button>
  <div id="mp-interval-row"><label id="mp-interval-label"></label><input id="mp-interval"></div>
  <input type="hidden" id="mp-takeoff-mode" value="safe">
  <button type="button" id="b-direct" data-seg="takeoff_mode" data-value="direct">Direct</button>
  <button type="button" id="b-safe" data-seg="takeoff_mode" data-value="safe">Safe</button>
  <div id="mp-safe-row"><label id="mp-tsh-label"></label><input id="mp-tsh"></div>
  <label id="mp-rth-label"></label><input id="mp-rth"><label id="mp-transitional-label"></label><input id="mp-transitional">
  <select id="mp-finish"><option value="goHome">h</option><option value="autoLand">l</option></select>
  <select id="mp-rclost"><option value="goContinue">c</option><option value="executeLostAction">e</option></select>
  <input type="checkbox" id="mp-geozone">
  <label id="mp-takeoff-altitude-label"></label><input id="mp-takeoff-altitude"><input type="hidden" id="mp-takeoff-ellipsoidal-height"><input type="hidden" id="mp-terrain-source" value="lidar"><div><button type="button" data-seg="terrain_source" data-value="lidar">Lidar surface (trees, roofs)</button><button type="button" data-seg="terrain_source" data-value="cop30">COP30</button></div>
  <input type="hidden" id="mp-shape-kind" value="circle">
  <button type="button" id="b-circle" data-shape-seg="kind" data-value="circle">Circle</button>
  <button type="button" id="b-rectangle" data-shape-seg="kind" data-value="rectangle">Rectangle</button>
  <button type="button" id="b-outline" data-shape-seg="kind" data-value="outline">Outline</button>
  <div id="mp-shape-circle-rows"><label id="mp-shape-radius-label"></label><input id="mp-shape-radius"></div>
  <div id="mp-shape-rectangle-rows"><label id="mp-shape-width-label"></label><input id="mp-shape-width">
    <label id="mp-shape-length-label"></label><input id="mp-shape-length"><input id="mp-shape-rotation"></div>
  <div id="mp-shape-outline-rows"></div>
  <label id="mp-shape-height-label"></label><input id="mp-shape-height">
  <label id="mp-shape-distance-label"></label><input id="mp-shape-distance">
  <input id="mp-shape-count"><input id="mp-shape-start"><input id="mp-shape-overlap">
  <input id="mp-shape-loops"><div id="mp-shape-top-row"><label id="mp-shape-top-label"></label><input id="mp-shape-top"></div>
</form>
<form id="mp-point-form">
  <label id="mp-point-height-label"></label><input id="mp-point-height">
  <div id="mp-point-heading-row"><input id="mp-point-heading"></div>
  <input id="mp-point-pitch"><input id="mp-point-hover"><input type="checkbox" id="mp-point-photo">
</form>`;

let form, changes, pointChanges;
const $ = id => document.getElementById(id);
const type = (id, value) => { $(id).value = value; $(id).dispatchEvent(new Event("input", {bubbles: true})); };
const click = id => $(id).dispatchEvent(new MouseEvent("click", {bubbles: true}));

function make(model) {
    document.body.innerHTML = HTML;
    form = createWaypointForm(document, Core, () => { changes++; }, model, () => { pointChanges++; });
    form.write(Core.WAYPOINT_DEFAULTS);
    changes = 0;
    pointChanges = 0;
}

beforeEach(() => make());

describe("the route's settings", () => {
    it("writes the defaults and reads them back", () => {
        expect(form.read()).toEqual(Core.WAYPOINT_DEFAULTS);
    });

    it("has a field for everything the core reads", () => {
        expect(Object.keys(FIELDS).sort()).toEqual(Object.keys(Core.WAYPOINT_DEFAULTS).sort());
    });

    it("what is read is what the core accepts", () => {
        expect(Core.parseWaypointForm(form.read()).ok).toBe(true);
    });

    it("never offers the thermal camera on a model without one", () => {
        make("m4e");
        expect(form.read().lens_ir).toBe("false");
        expect(Core.parseWaypointForm(form.read()).values.cameras).toEqual(["visable"]);
    });

    it("shows the chosen lenses as active chips", () => {
        expect($("chip-visible").classList.contains("active")).toBe(true);
        form.write({lens_visible: "false"});
        expect($("chip-visible").classList.contains("active")).toBe(false);
    });
});

describe("segmented buttons", () => {
    it("change the choice, show it and announce it", () => {
        expect($("b-alt").classList.contains("active")).toBe(true);
        click("b-pass");
        click("b-manual");
        expect(form.read().turn_mode).toBe("pass");
        expect(form.read().heading_mode).toBe("manually");
        expect($("b-pass").classList.contains("active")).toBe(true);
        expect($("b-stop").classList.contains("active")).toBe(false);
        expect(changes).toBe(2);
    });

    it("label the height after the height mode", () => {
        expect($("mp-height-label").textContent).toBe("Height above the takeoff point (m)");
        click("b-asl");
        expect($("mp-height-label").textContent).toBe("Height above sea level (m)");
        click("b-agl");
        expect($("mp-height-label").textContent).toBe("Height above the ground under each point (m)");
    });

    it("show the safe takeoff altitude only for a safe takeoff", () => {
        expect($("mp-safe-row").hidden).toBe(false);
        click("b-direct");
        expect($("mp-safe-row").hidden).toBe(true);
    });

    it("show the point's heading only when the heading is set by hand", () => {
        expect($("mp-point-heading-row").hidden).toBe(true);
        click("b-manual");
        expect($("mp-point-heading-row").hidden).toBe(false);
        click("b-poi");
        expect($("mp-point-heading-row").hidden).toBe(true);
    });

    it("show the POI row only for a Toward POI heading", () => {
        expect($("mp-poi-row").hidden).toBe(true);
        click("b-poi");
        expect($("mp-poi-row").hidden).toBe(false);
        expect(form.read().heading_mode).toBe("towardPOI");
    });

    it("show the interval only when photos are taken over the route, labelled by distance or time", () => {
        expect($("mp-interval-row").hidden).toBe(true);
        expect($("b-int-off").classList.contains("active")).toBe(true);
        click("b-int-distance");
        expect($("mp-interval-row").hidden).toBe(false);
        expect($("mp-interval-label").textContent).toBe("A photo every (m)");
        click("b-int-time");
        expect($("mp-interval-label").textContent).toBe("A photo every (s)");
    });
});

describe("the selected point", () => {
    it("writes a point and reads it back as the core's point form takes it", () => {
        form.writePoint({lat: 1, lon: 2, height: 80, heading: -30, pitch: -45, photo: true, hover: 5, ground: null});
        const p = form.readPoint();
        expect(p).toEqual({height: "80", heading: "-30", pitch: "-45", hover: "5", photo: "true"});
        expect(Core.parsePointForm(p, "alt").values).toEqual({height: 80, heading: -30, pitch: -45, hover: 5, photo: true});
    });

    it("leaves blank what the point takes from the route", () => {
        form.writePoint(Core.newPoint(1, 2));
        expect(form.readPoint()).toEqual({height: "", heading: "", pitch: "", hover: "", photo: "false"});
    });

    it("announces a change of the point, not of the route", () => {
        type("mp-point-hover", "3");
        expect(pointChanges).toBe(1);
        expect(changes).toBe(0);
    });
});

describe("units", () => {
    it("show lengths and speeds in imperial and still read metric", () => {
        form.write({height: "100", speed: "10"});
        form.writePoint({height: 30, heading: null, pitch: null, photo: false, hover: 0});
        form.setUnits("imperial");
        expect($("mp-height").value).toBe("328.08");
        expect($("mp-point-height").value).toBe("98.43");
        expect($("mp-height-label").textContent).toBe("Height above the takeoff point (ft)");
        expect($("mp-speed-label").textContent).toBe("Flight speed (mph)");
        expect(parseFloat(form.read().height)).toBeCloseTo(100, 1);
        expect(parseFloat(form.readPoint().height)).toBeCloseTo(30, 1);
        expect(form.getUnits()).toBe("imperial");
    });

    it("show a distance interval in feet and a time interval in seconds", () => {
        form.write({photo_interval_mode: "distance", photo_interval: "10"});
        form.setUnits("imperial");
        expect($("mp-interval").value).toBe("32.81");
        expect($("mp-interval-label").textContent).toBe("A photo every (ft)");
        expect(parseFloat(form.read().photo_interval)).toBeCloseTo(10, 1);
        form.write({photo_interval_mode: "time", photo_interval: "3"});
        expect($("mp-interval").value).toBe("3");
        expect(form.read().photo_interval).toBe("3");
    });

    it("leave degrees and seconds as they are", () => {
        form.writePoint({height: null, heading: 90, pitch: -60, photo: false, hover: 4});
        form.setUnits("imperial");
        expect(form.readPoint()).toEqual({height: "", heading: "90", pitch: "-60", hover: "4", photo: "false"});
    });
});

it("names every point field after an id in the point form", () => {
    Object.keys(POINT_FIELDS).forEach(k => expect($(POINT_FIELDS[k].id)).not.toBeNull());
});

describe("the shape of a POI route", () => {
    const shape = () => { const s = Object.assign({}, Core.SHAPE_DEFAULTS); delete s.outline; delete s.edited; return s; };

    it("writes the defaults and reads them back as the core takes them", () => {
        form.writeShape(Core.SHAPE_DEFAULTS);
        expect(form.readShape()).toEqual(shape());
        expect(Core.parseShapeForm(Object.assign(form.readShape(), {outline: []})).ok).toBe(true);
    });

    it("has a field for everything in the shape but the outline and whether its points were edited", () => {
        expect(Object.keys(SHAPE_FIELDS).sort()).toEqual(Object.keys(shape()).sort());
    });

    it("shows the rows of the chosen kind and announces the change", () => {
        form.writeShape(Core.SHAPE_DEFAULTS);
        expect($("mp-shape-circle-rows").hidden).toBe(false);
        expect($("mp-shape-rectangle-rows").hidden).toBe(true);
        click("b-rectangle");
        expect(form.readShape().kind).toBe("rectangle");
        expect($("b-rectangle").classList.contains("active")).toBe(true);
        expect($("mp-shape-circle-rows").hidden).toBe(true);
        expect($("mp-shape-rectangle-rows").hidden).toBe(false);
        click("b-outline");
        expect($("mp-shape-outline-rows").hidden).toBe(false);
        expect(changes).toBe(2);
    });

    it("shows its lengths in feet and still reads metric", () => {
        form.writeShape(Core.SHAPE_DEFAULTS);
        form.setUnits("imperial");
        expect($("mp-shape-distance").value).toBe("49.21");
        expect($("mp-shape-count").value).toBe("12");
        expect($("mp-shape-distance-label").textContent).toBe("Distance from the subject (ft)");
        expect(parseFloat(form.readShape().distance)).toBeCloseTo(15, 1);
    });

    it("shows the highest loop only for several loops, in the unit of the lengths", () => {
        form.writeShape(Object.assign({}, Core.SHAPE_DEFAULTS, {loops: "1", top: ""}));
        expect($("mp-shape-top-row").hidden).toBe(true);
        $("mp-shape-loops").value = "3";
        $("mp-shape-loops").dispatchEvent(new Event("input", {bubbles: true}));
        expect($("mp-shape-top-row").hidden).toBe(false);
        form.writeShape(Object.assign({}, Core.SHAPE_DEFAULTS, {loops: "3", top: "30"}));
        form.setUnits("imperial");
        expect($("mp-shape-top").value).toBe("98.43");
        expect($("mp-shape-top-label").textContent).toBe("Highest loop at (ft)");
        expect(form.readShape()).toMatchObject({loops: "3"});
        expect(parseFloat(form.readShape().top)).toBeCloseTo(30, 1);
    });
});
