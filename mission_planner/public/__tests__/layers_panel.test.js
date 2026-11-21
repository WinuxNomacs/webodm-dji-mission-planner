const { createLayersPanel } = require('../layers_panel');

const BASEMAPS = [{label: "Google Maps Hybrid"}, {label: "Google Maps"}, {label: "Google Terrain"}, {label: "OpenStreetMap"}];

let panel, calls, host;
const make = (over = {}) => {
    calls = {basemap: [], view3d: []};
    host = document.createElement("div");
    document.body.appendChild(host);
    panel = createLayersPanel(document, Object.assign({basemaps: BASEMAPS, selected: "Google Maps", view3d: false,
        onBasemap: l => calls.basemap.push(l), onView3d: on => calls.view3d.push(on)}, over));
    host.appendChild(panel.element);
    return panel;
};
afterEach(() => { document.body.removeChild(host); });

const button = () => panel.element.querySelector(".mp-layers-button");
const panelEl = () => panel.element.querySelector(".mp-layers-panel");
const radios = () => Array.from(panel.element.querySelectorAll("input[type=radio]"));
const views = () => Array.from(panel.element.querySelectorAll(".mp-layers-view"));
const click = el => el.dispatchEvent(new MouseEvent("click", {bubbles: true}));

describe("layers button", () => {
    it("is a button on the map, closed at first", () => {
        make();
        expect(panel.element.className).toContain("maplibregl-ctrl-group");
        expect(button().title).toBe("Map layers");
        expect(button().getAttribute("aria-expanded")).toBe("false");
        expect(panelEl().hidden).toBe(true);
        expect(panel.isOpen()).toBe(false);
    });

    it("opens and closes its panel with the button", () => {
        make();
        click(button());
        expect(panelEl().hidden).toBe(false);
        expect(button().getAttribute("aria-expanded")).toBe("true");
        expect(panel.element.classList.contains("open")).toBe(true);
        click(button());
        expect(panelEl().hidden).toBe(true);
    });

    it("closes when something else is clicked, or on Escape, but not when its own panel is clicked", () => {
        make();
        panel.open();
        click(panelEl());
        expect(panel.isOpen()).toBe(true);
        click(document.body);
        expect(panel.isOpen()).toBe(false);

        panel.open();
        document.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter"}));
        expect(panel.isOpen()).toBe(true);
        document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape"}));
        expect(panel.isOpen()).toBe(false);
    });
});

describe("map choice", () => {
    it("lists every basemap, with the current one chosen", () => {
        make();
        expect(radios().map(r => r.value)).toEqual(BASEMAPS.map(b => b.label));
        expect(radios().filter(r => r.checked).map(r => r.value)).toEqual(["Google Maps"]);
        expect(Array.from(panel.element.querySelectorAll(".mp-layers-choice")).map(l => l.textContent.trim())).toEqual(BASEMAPS.map(b => b.label));
    });

    it("tells which basemap was chosen, once per choice", () => {
        make();
        const terrain = radios()[2];
        terrain.checked = true;
        terrain.dispatchEvent(new Event("change"));
        expect(calls.basemap).toEqual(["Google Terrain"]);
    });

    it("follows the choice made elsewhere, without announcing it", () => {
        make();
        panel.setSelected("OpenStreetMap");
        expect(radios().filter(r => r.checked).map(r => r.value)).toEqual(["OpenStreetMap"]);
        expect(calls.basemap).toEqual([]);
    });

    it("works with one basemap, and with none chosen", () => {
        make({basemaps: [{label: "OpenStreetMap"}], selected: null});
        expect(radios().length).toBe(1);
        expect(radios()[0].checked).toBe(false);
    });

    it("writes labels as text: a label cannot inject markup", () => {
        make({basemaps: [{label: '<img src=x onerror="alert(1)">'}]});
        expect(panel.element.querySelector("img")).toBeNull();
        expect(radios()[0].value).toBe('<img src=x onerror="alert(1)">');
    });
});

describe("view choice", () => {
    it("starts flat", () => {
        make();
        expect(views().map(v => v.textContent)).toEqual(["2D", "3D"]);
        expect(views()[0].classList.contains("active")).toBe(true);
        expect(views()[1].classList.contains("active")).toBe(false);
        expect(views()[0].getAttribute("aria-pressed")).toBe("true");
    });

    it("can start in 3D", () => {
        make({view3d: true});
        expect(views()[1].classList.contains("active")).toBe(true);
        expect(views()[0].classList.contains("active")).toBe(false);
    });

    it("switches and tells the map when a view is clicked", () => {
        make();
        click(views()[1]);
        expect(calls.view3d).toEqual([true]);
        expect(views()[1].classList.contains("active")).toBe(true);
        expect(views()[1].getAttribute("aria-pressed")).toBe("true");
        click(views()[0]);
        expect(calls.view3d).toEqual([true, false]);
        expect(views()[0].classList.contains("active")).toBe(true);
    });

    it("follows the view set elsewhere, without announcing it", () => {
        make();
        panel.setView3d(true);
        expect(views()[1].classList.contains("active")).toBe(true);
        expect(calls.view3d).toEqual([]);
    });

    it("explains 3D in its tooltip, and the lidar choice what it adds", () => {
        make();
        expect(views()[1].title).toBe("Tilted map with the terrain raised");
        expect(panel.element.querySelector(".mp-layers-lidar").title).toContain("trees and buildings from USGS lidar");
    });
});

describe("lidar surface choice", () => {
    const lidarBox = () => panel.element.querySelector(".mp-layers-lidar input[type=checkbox]");

    it("is on unless the page says otherwise", () => {
        make();
        expect(lidarBox().checked).toBe(true);
        expect(panel.element.querySelector(".mp-layers-lidar").textContent).toContain("Lidar surface (US)");
        make({lidar: false});
        expect(lidarBox().checked).toBe(false);
    });

    it("tells the page when it is turned on or off", () => {
        const seen = [];
        make({onLidar: on => seen.push(on)});
        lidarBox().click();
        lidarBox().click();
        expect(seen).toEqual([false, true]);
    });

    it("can be set from the page without telling it back", () => {
        const seen = [];
        make({onLidar: on => seen.push(on)});
        panel.setLidar(false);
        expect(lidarBox().checked).toBe(false);
        expect(seen).toEqual([]);
    });
});

describe("relief choice", () => {
    const reliefBox = () => panel.element.querySelector(".mp-layers-relief input[type=checkbox]");

    it("is off unless the page says otherwise, and says what it shows", () => {
        make();
        expect(reliefBox().checked).toBe(false);
        expect(panel.element.querySelector(".mp-layers-relief").textContent).toContain("Relief (3D)");
        expect(panel.element.querySelector(".mp-layers-relief").title).toContain("coloured by its height");
        make({relief: true});
        expect(reliefBox().checked).toBe(true);
    });

    it("tells the page when it is turned on or off, and can be set without telling it back", () => {
        const seen = [];
        make({onRelief: on => seen.push(on)});
        reliefBox().click();
        panel.setRelief(false);
        expect(reliefBox().checked).toBe(false);
        expect(seen).toEqual([true]);
    });
});

describe("WebODM task", () => {
    const select = () => panel.element.querySelector(".mp-layers-task");
    const dsm = () => panel.element.querySelector(".mp-layers-task-dsm input");
    const ortho = () => panel.element.querySelector(".mp-layers-task-ortho input");
    const TASKS = [{id: "a", name: "Roof", project_name: "Survey"}, {id: "b", name: "Field", project_name: "Survey"}];

    it("is not there unless asked for", () => {
        make();
        expect(select()).toBeNull();
        panel.setTasks(TASKS, "a");                                         // harmless
    });

    it("lists the tasks to pick one or none, and says when there are none", () => {
        const picked = [];
        make({tasks: true, onTask: id => picked.push(id)});
        expect(select().disabled).toBe(true);
        expect(select().options[0].textContent).toBe("None over the route");
        panel.setTasks(TASKS, "b");
        expect(Array.from(select().options).map(o => o.textContent)).toEqual(["None", "Roof (Survey)", "Field (Survey)"]);
        expect(select().value).toBe("b");
        select().value = "a";
        select().dispatchEvent(new Event("change"));
        select().value = "";
        select().dispatchEvent(new Event("change"));
        expect(picked).toEqual(["a", null]);
    });

    it("turns the task's DSM and orthophoto on and off, each only where the task has it", () => {
        const got = {dsm: [], ortho: []};
        make({tasks: true, onTaskDsm: on => got.dsm.push(on), onTaskOrthophoto: on => got.ortho.push(on)});
        expect(dsm().disabled && ortho().disabled).toBe(true);
        panel.setTaskLayers({dsm: true, orthophoto: true, dsmEnabled: false, orthophotoEnabled: true});
        expect([dsm().checked, dsm().disabled, ortho().checked, ortho().disabled]).toEqual([false, true, true, false]);
        ortho().click();
        expect(got.ortho).toEqual([false]);
        panel.setTaskNote("Preparing the task's DSM…");
        expect(panel.element.querySelector(".mp-layers-task-note").textContent).toBe("Preparing the task's DSM…");
    });
});
