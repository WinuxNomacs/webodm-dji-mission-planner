const T = require('../task_layers');

const API = "/api/plugins/mission_planner/";
const TASKS = [{id: "t1", project: 3, name: "Roof", project_name: "Survey", dsm: true, orthophoto: true},
               {id: "t2", project: 3, name: "Photos", project_name: "Survey", dsm: false, orthophoto: true}];

function fakeFetch(handler) {
    const calls = [];
    const fn = (url, init) => {
        calls.push({url, init: init || {}});
        const a = handler(url, init || {});
        if (a instanceof Error) return Promise.reject(a);
        return Promise.resolve({ok: a.status >= 200 && a.status < 300, status: a.status, json: () => Promise.resolve(a.body)});
    };
    fn.calls = calls;
    return fn;
}
const flush = async () => { for (let i = 0; i < 6; i++) await new Promise(r => setTimeout(r, 0)); };

function fakeMap() {
    const layers = {}, sources = {};
    return {
        layers, sources,
        getLayer: id => layers[id], getSource: id => sources[id],
        addLayer: (l, before) => { layers[l.id] = Object.assign({before}, l); },
        removeLayer: id => { delete layers[id]; }, addSource: (id, s) => { sources[id] = s; }, removeSource: id => { delete sources[id]; }
    };
}
function fakePanel() {
    return {tasks: null, selected: null, layers: null, note: "",
            setTasks(t, s) { this.tasks = t; this.selected = s; }, setTaskLayers(l) { this.layers = l; }, setTaskNote(n) { this.note = n; }};
}
function store(initial = {}) {
    const data = Object.assign({}, initial);
    return {data, getItem: k => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = v; }};
}

let map, panel, surfaces, timers, fetch, layers, state;
const make = (opts = {}) => {
    map = fakeMap(); panel = fakePanel(); surfaces = []; timers = [];
    state = opts.state || {state: "done", v: 9, shift: 33.1, match: -1.1, reference: "lidar", bounds: [1, 2, 3, 4]};
    fetch = fakeFetch(opts.web || (url => url.indexOf("task-surfaces") >= 0 ? {status: 200, body: {tasks: TASKS}}
        : url.indexOf("tiles.json") >= 0 ? {status: 200, body: {tiles: ["/api/projects/3/tasks/t1/orthophoto/tiles/{z}/{x}/{y}.png"], bounds: [1, 2, 3, 4], minzoom: 14, maxzoom: 23}}
        : {status: 200, body: state}));
    layers = T.createTaskLayers({map, panel, fetch, api: API, csrf: "tok", storage: opts.storage || null, routeKey: "routeKey" in opts ? opts.routeKey : "54",
                                 before: () => "mp-hillshade", onSurface: s => surfaces.push(s), now: () => 0,
                                 setTimeout: (f, ms) => { timers.push({f, ms}); return timers.length; }, clearTimeout: id => { timers[id - 1] = null; }});
    return layers;
};

describe("a WebODM task in the map", () => {
    it("lists the tasks over the route, none chosen at first, and asks again only when the route moves", async () => {
        make();
        await layers.list([1, 2, 3, 4]);
        expect(fetch.calls[0].url).toBe(API + "task-surfaces?bounds=1,2,3,4");
        expect(panel.tasks).toEqual(TASKS);
        expect(panel.selected).toBeNull();
        expect(panel.layers).toEqual({dsm: true, orthophoto: true, dsmEnabled: false, orthophotoEnabled: false});
        await layers.list([1, 2, 3, 4]);
        expect(fetch.calls.length).toBe(1);
        await layers.list([1, 2, 3, 5]);
        expect(fetch.calls.length).toBe(2);
    });

    it("says when the user has no task over the route", async () => {
        make({web: () => ({status: 200, body: {tasks: []}})});
        await layers.list([1, 2, 3, 4]);
        expect(panel.note).toBe("No processed task of yours over the route");
    });

    it("shows a chosen task's DSM once cut and its orthophoto above the basemap, from WebODM's own tiles", async () => {
        make();
        await layers.list([1, 2, 3, 4]);
        await layers.choose("t1");
        await flush();
        const post = fetch.calls.find(c => c.init.method === "POST");
        expect(post.url).toBe(API + "task-surface");
        expect(JSON.parse(post.init.body)).toEqual({task: "t1"});
        expect(post.init.headers["X-CSRFToken"]).toBe("tok");
        expect(surfaces).toEqual([null, {id: "t1", v: 9, bounds: [1, 2, 3, 4]}]);
        expect(panel.note).toBe("The task's heights are matched to the lidar (-1.1 m)");
        const src = map.sources[T.ORTHO];
        expect(src.tiles[0]).toMatch(/^https?:\/\/[^/]+\/api\/projects\/3\/tasks\/t1\/orthophoto\/tiles\/\{z\}\/\{x\}\/\{y\}\.png$/);
        expect(src).toMatchObject({type: "raster", bounds: [1, 2, 3, 4], minzoom: 14, maxzoom: 23});
        expect(map.layers[T.ORTHO].before).toBe("mp-hillshade");
        expect(panel.layers).toEqual({dsm: true, orthophoto: true, dsmEnabled: true, orthophotoEnabled: true});
    });

    it("polls while the DSM is being cut, and says why when it fails", async () => {
        make({state: {state: "queued"}});
        await layers.list([1, 2, 3, 4]);
        await layers.choose("t1");
        await flush();
        expect(panel.note).toBe("Preparing the task's DSM…");
        expect(timers.filter(Boolean)[0].ms).toBe(T.POLL_MS);
        state = {state: "failed", message: "the disk is full"};
        timers.filter(Boolean)[0].f();
        await flush();
        expect(fetch.calls.pop().url).toBe(API + "task-surface?task=t1");
        expect(panel.note).toBe("The task's DSM could not be shown: the disk is full");
        expect(surfaces.pop()).toBeNull();
        expect(timers.filter(Boolean).length).toBe(1);                       // the poll that ran, no new one
    });

    it("turns the orthophoto off without asking for the DSM again, and the DSM off without touching the photo", async () => {
        make();
        await layers.list([1, 2, 3, 4]);
        await layers.choose("t1");
        await flush();
        const posts = () => fetch.calls.filter(c => c.init.method === "POST").length;
        await layers.setOrthophoto(false);
        expect(map.layers[T.ORTHO]).toBeUndefined();
        expect(posts()).toBe(1);
        await layers.setDsm(false);
        expect(surfaces.pop()).toBeNull();
        await layers.setOrthophoto(true);
        await flush();
        expect(map.layers[T.ORTHO]).toBeDefined();
        expect(posts()).toBe(1);
    });

    it("a task with only an orthophoto has no DSM to turn on", async () => {
        make();
        await layers.list([1, 2, 3, 4]);
        await layers.choose("t2");
        await flush();
        expect(panel.layers).toEqual({dsm: true, orthophoto: true, dsmEnabled: false, orthophotoEnabled: true});
        expect(fetch.calls.some(c => c.init.method === "POST")).toBe(false);
        expect(map.sources[T.ORTHO]).toBeDefined();
    });

    it("remembers the choice per route in this browser, and shows it again when the route opens", async () => {
        const storage = store();
        make({storage});
        await layers.list([1, 2, 3, 4]);
        await layers.choose("t1");
        await layers.setOrthophoto(false);
        expect(JSON.parse(storage.data[T.KEY + "54"])).toEqual({task: "t1", dsm: true, orthophoto: false});
        make({storage});
        await layers.list([1, 2, 3, 4]);
        await flush();
        expect(panel.selected).toBe("t1");
        expect(surfaces.pop()).toEqual({id: "t1", v: 9, bounds: [1, 2, 3, 4]});
        expect(map.sources[T.ORTHO]).toBeUndefined();
        make({storage, routeKey: "55"});                                     // another route: its own
        await layers.list([1, 2, 3, 4]);
        expect(panel.selected).toBeNull();
    });

    it("a route not saved yet remembers nothing, and a remembered task gone shows none", async () => {
        const storage = store({[T.KEY + "54"]: JSON.stringify({task: "gone", dsm: true, orthophoto: true})});
        make({storage, routeKey: null});
        await layers.list([1, 2, 3, 4]);
        await layers.choose("t1");
        expect(Object.keys(storage.data)).toEqual([T.KEY + "54"]);
        make({storage});
        await layers.list([1, 2, 3, 4]);
        expect(panel.selected).toBeNull();
        make({storage: {getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }}});
        await layers.list([1, 2, 3, 4]);
        await layers.choose("t1");                                          // storage refused: still works
        expect(panel.selected).toBe("t1");
    });

    it("says so when the orthophoto or the DSM cannot be had", async () => {
        make({web: url => url.indexOf("task-surfaces") >= 0 ? {status: 200, body: {tasks: TASKS}}
            : url.indexOf("tiles.json") >= 0 ? {status: 403, body: {}} : {status: 404, body: {detail: "Not found."}}});
        await layers.list([1, 2, 3, 4]);
        await layers.choose("t1");
        await flush();
        expect(map.sources[T.ORTHO]).toBeUndefined();
        expect(panel.note).toMatch(/could not be shown/);
    });

    it("words the heights' placement by what they were matched with", () => {
        expect(T.surfaceNote({state: "done", reference: "terrain", match: 0.25})).toBe("The task's heights are matched to the terrain (+0.3 m)");
        expect(T.surfaceNote({state: "done", reference: null, match: 0})).toMatch(/geoid alone/);
        expect(T.surfaceNote({state: "building"})).toBe("Preparing the task's DSM…");
    });
});
