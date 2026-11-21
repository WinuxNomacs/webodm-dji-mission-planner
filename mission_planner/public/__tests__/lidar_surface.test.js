const L = require('../lidar_surface');

const API = "/api/plugins/mission_planner/";
const AWS = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/";

// A fetch that answers by URL: handlers return {status, body} (JSON) or {status, bytes}
function fakeFetch(handler) {
    const calls = [];
    const fn = (url, init) => {
        calls.push({url, init: init || {}});
        let a;
        try { a = handler(url, init || {}); } catch (e) { return Promise.reject(e); }
        if (a instanceof Error) return Promise.reject(a);
        const bytes = a.bytes || new Uint8Array([1, 2, 3]).buffer;
        return Promise.resolve({
            ok: a.status >= 200 && a.status < 300, status: a.status,
            json: () => a.body === undefined ? Promise.reject(new Error("no json")) : Promise.resolve(a.body),
            arrayBuffer: () => Promise.resolve(bytes),
            blob: () => Promise.resolve({fake: "blob", url})
        });
    };
    fn.calls = calls;
    return fn;
}

const flush = () => new Promise(r => setTimeout(r, 0));
const units = (...states) => states.map((s, i) => ({x: 10 + i, y: 20, state: s, message: s === "failed" ? "PDAL failed: boom" : ""}));

describe("bounds of a route", () => {
    it("are the box around its points, skipping what is not a point", () => {
        expect(L.boundsOf([[-79.447968, 41.5], [-79.547968, 41.4], null, [NaN, 1]])).toEqual([-79.547968, 41.4, -79.447968, 41.5]);
        expect(L.boundsOf([])).toBeNull();
        expect(L.boundsOf(null)).toBeNull();
    });
});

describe("tiles above zoom 15", () => {
    it("lie in one unit and are cut from their zoom-15 parent", () => {
        expect(L.unitOf(18, 8 * 100 + 7, 8 * 200)).toEqual([100, 200]);
        expect(L.parentCrop(16, 201, 400)).toEqual({x: 100, y: 200, left: 128, top: 0, size: 128});
        expect(L.parentCrop(18, 807, 1600)).toEqual({x: 100, y: 200, left: 224, top: 0, size: 32});
    });
});

describe("what the status bar says", () => {
    it("counts the units while some are still building", () => {
        expect(L.statusOf(units("done", "queued", "building", "none"))).toEqual({busy: true, text: "Building the lidar surface (2 of 4)"});
        expect(L.statusOf(units("missing"))).toEqual({busy: true, text: "Building the lidar surface (0 of 1)"});
    });

    it("says why when a unit failed", () => {
        expect(L.statusOf(units("failed")).text).toBe("The lidar surface could not be built here: PDAL failed: boom");
        expect(L.statusOf(units("done", "failed")).text).toContain("could not be built everywhere");
    });

    it("says there is no lidar when none of the units has any, and nothing when the surface is there", () => {
        expect(L.statusOf(units("none", "none")).text).toBe("No lidar here: the standard terrain is used");
        expect(L.statusOf(units("done", "none"))).toBeNull();
    });
});

describe("status bar", () => {
    let host, timers, pending;
    beforeEach(() => {
        host = document.createElement("div");
        pending = [];
        timers = {setTimeout: (f, ms) => { pending.push({f, ms}); return pending.length; }, clearTimeout: id => { pending[id - 1] = null; }};
    });

    it("shows a spinner while building and stays", () => {
        const bar = L.createStatusBar(document, host, timers);
        bar.show({busy: true, text: "Building the lidar surface (0 of 2)"});
        expect(bar.element.hidden).toBe(false);
        expect(bar.element.querySelector(".fa-spin").hidden).toBe(false);
        expect(bar.element.textContent).toContain("0 of 2");
        expect(pending.filter(Boolean)).toEqual([]);
    });

    it("shows a note without the spinner and hides it after a while", () => {
        const bar = L.createStatusBar(document, host, timers);
        bar.show({busy: false, text: "No lidar here"});
        expect(bar.element.querySelector(".fa-spin").hidden).toBe(true);
        expect(pending[0].ms).toBe(L.NOTE_MS);
        pending[0].f();
        expect(bar.element.hidden).toBe(true);
    });

    it("hides at once when there is nothing to say", () => {
        const bar = L.createStatusBar(document, host, timers);
        bar.show({busy: true, text: "x"});
        bar.show(null);
        expect(bar.element.hidden).toBe(true);
    });

    const live = () => pending.filter(Boolean);

    it("says the elevation is loading once the loading has lasted a moment", () => {
        const bar = L.createStatusBar(document, host, timers);
        bar.loading(true);
        expect(bar.element.hidden).toBe(true);
        expect(live()[0].ms).toBe(L.LOADING_DELAY_MS);
        live()[0].f();
        expect(bar.element.hidden).toBe(false);
        expect(bar.element.textContent).toBe("Loading elevation…");
        expect(bar.element.querySelector(".fa-spin").hidden).toBe(false);
    });

    it("says nothing when the loading ends before the moment is over", () => {
        const bar = L.createStatusBar(document, host, timers);
        bar.loading(true);
        bar.loading(false);
        expect(live()).toEqual([]);
        expect(bar.element.hidden).toBe(true);
    });

    it("hides the loading message once the elevation is drawn", () => {
        const bar = L.createStatusBar(document, host, timers);
        bar.loading(true);
        live()[0].f();
        bar.loading(false);
        expect(bar.element.hidden).toBe(true);
    });

    it("does not start the moment again while the loading goes on", () => {
        const bar = L.createStatusBar(document, host, timers);
        bar.loading(true);
        bar.loading(true);
        expect(live().length).toBe(1);
    });

    it("keeps a lidar build's message while the elevation loads", () => {
        const bar = L.createStatusBar(document, host, timers);
        bar.show({busy: true, text: "Building the lidar surface (1 of 2)"});
        bar.loading(true);
        live()[0].f();
        expect(bar.element.textContent).toContain("1 of 2");
        bar.show(null);
        expect(bar.element.textContent).toBe("Loading elevation…");
    });

    it("shows a note once the loading is over, for its usual time", () => {
        const bar = L.createStatusBar(document, host, timers);
        bar.loading(true);
        live()[0].f();
        bar.show({busy: false, text: "No lidar here"});
        expect(bar.element.textContent).toBe("Loading elevation…");
        const notes = () => live().filter(t => t.ms === L.NOTE_MS);
        expect(notes()).toEqual([]);
        bar.loading(false);
        expect(bar.element.textContent).toBe("No lidar here");
        expect(notes().length).toBe(1);
        notes()[0].f();
        expect(bar.element.hidden).toBe(true);
    });

    it("lets a note that was cut short by loading show its whole time afterwards", () => {
        const bar = L.createStatusBar(document, host, timers);
        bar.show({busy: false, text: "No lidar here"});
        bar.loading(true);
        live().filter(t => t.ms === L.LOADING_DELAY_MS)[0].f();
        expect(live().filter(t => t.ms === L.NOTE_MS)).toEqual([]);
        bar.loading(false);
        expect(bar.element.textContent).toBe("No lidar here");
        expect(live().filter(t => t.ms === L.NOTE_MS).length).toBe(1);
    });
});

describe("watching the map's elevation", () => {
    // A map with only what watchElevation uses: on(), getSource(), isSourceLoaded()
    function fakeMap() {
        const handlers = {};
        const map = {
            source: true, loaded: true,
            on: (type, f) => { (handlers[type] = handlers[type] || []).push(f); },
            getSource: id => (map.source && id === "mp-dem" ? {} : undefined),
            isSourceLoaded: id => { if (!map.getSource(id)) throw new Error("no source " + id); return map.loaded; },
            fire: (type, e) => (handlers[type] || []).forEach(f => f(e || {}))
        };
        return map;
    }
    function fakeBar() {
        const bar = {states: [], loading: on => bar.states.push(on)};
        return bar;
    }

    it("says loading while the elevation source has tiles loading, in 3D", () => {
        const map = fakeMap(), bar = fakeBar();
        L.watchElevation(map, bar, "mp-dem", () => true);
        map.loaded = false;
        map.fire("render");
        expect(bar.states.slice(-1)).toEqual([true]);
        map.loaded = true;
        map.fire("sourcedata", {sourceId: "mp-dem"});
        expect(bar.states.slice(-1)).toEqual([false]);
    });

    it("stops saying it when the map is idle", () => {
        const map = fakeMap(), bar = fakeBar();
        L.watchElevation(map, bar, "mp-dem", () => true);
        map.loaded = false;
        map.fire("render");
        map.fire("idle");
        expect(bar.states.slice(-1)).toEqual([false]);
    });

    it("says nothing in 2D, nor without the source", () => {
        const map = fakeMap(), bar = fakeBar();
        let view3d = false;
        const watch = L.watchElevation(map, bar, "mp-dem", () => view3d);
        map.loaded = false;
        map.fire("render");
        expect(bar.states.slice(-1)).toEqual([false]);
        view3d = true;
        map.source = false;
        map.fire("render");
        expect(bar.states.slice(-1)).toEqual([false]);
        map.source = true;
        watch.check();
        expect(bar.states.slice(-1)).toEqual([true]);
    });
});

describe("lidar surface", () => {
    let timers, statuses, tileChanges, clock, decoded;
    const make = (handler, over = {}) => {
        decoded = [];
        timers = [];
        statuses = [];
        tileChanges = [];
        clock = 0;
        const fetch = fakeFetch(handler);
        const surface = L.createLidarSurface(Object.assign({
            fetch, api: API, csrf: "token", now: () => clock,
            setTimeout: (f, ms) => { timers.push({f, ms}); return timers.length; }, clearTimeout: id => { timers[id - 1] = null; },
            onStatus: s => statuses.push(s), onTilesChanged: t => tileChanges.push(t),
            decodeParent: blob => { decoded.push(blob.url); return Promise.resolve({image: blob.url}); },
            crop: (image, c) => Promise.resolve({cropped: c, from: image.image})
        }, over));
        return {surface, fetch};
    };
    const runTimer = async () => { const t = timers.filter(Boolean).pop(); timers[timers.indexOf(t)] = null; t.f(); await flush(); await flush(); };

    it("is a Terrarium source loaded through its own protocol, up to zoom 18", () => {
        const added = [];
        const maplibregl = {addProtocol: name => added.push(name)};
        const {surface} = make(() => ({status: 200}), {maplibregl});
        const s = surface.source();
        expect(s).toMatchObject({type: "raster-dem", encoding: "terrarium", maxzoom: 18});
        expect(s.tiles[0]).toMatch(/^mplidar:\/\/\{z\}\/\{x\}\/\{y\}\?v=0$/);
        expect(added).toEqual(["mplidar"]);
        make(() => ({status: 200}), {maplibregl});           // a second editor on the page does not add it twice
        expect(added).toEqual(["mplidar"]);
    });

    it("asks for the units around the route with the CSRF token, then polls until they are built", async () => {
        let answer = units("queued", "queued");
        const {surface, fetch} = make(() => ({status: 200, body: {units: answer}}));
        await surface.request([-79.547968, 41.4, -79.447968, 41.5]);
        expect(fetch.calls[0].url).toBe(API + "lidar/surface");
        expect(fetch.calls[0].init.method).toBe("POST");
        expect(fetch.calls[0].init.headers["X-CSRFToken"]).toBe("token");
        expect(JSON.parse(fetch.calls[0].init.body)).toEqual({bounds: [-79.547968, 41.4, -79.447968, 41.5]});
        expect(statuses.pop()).toEqual({busy: true, text: "Building the lidar surface (0 of 2)"});
        expect(timers.filter(Boolean)[0].ms).toBe(L.POLL_MS);

        answer = units("done", "building");
        await runTimer();
        expect(fetch.calls[1].url).toBe(API + "lidar/surface?bounds=-79.547968,41.4,-79.447968,41.5");
        expect(tileChanges).toEqual([["mplidar://{z}/{x}/{y}?v=1"]]);      // the terrain reloads with the new unit
        expect(statuses.pop().text).toContain("1 of 2");

        answer = units("done", "done");
        await runTimer();
        expect(tileChanges.length).toBe(2);
        expect(statuses.pop()).toBeNull();
        expect(timers.filter(Boolean)).toEqual([]);                           // done: no more polling
    });

    it("loads a built unit's tiles from the server and others from AWS, cut from the parent above zoom 15", async () => {
        const {surface, fetch} = make(url => url.indexOf("lidar/surface") >= 0 ? {status: 200, body: {units: [{x: 100, y: 200, state: "done"}]}} : {status: 200});
        await surface.request([1, 2, 3, 4]);
        await surface.load({url: "mplidar://17/401/802?v=1"});
        expect(fetch.calls.pop()).toMatchObject({url: API + "lidar/tiles/17/401/802.png?v=0", init: {credentials: "same-origin"}});
        await surface.load({url: "mplidar://14/50/100?v=1"});
        expect(fetch.calls.pop()).toMatchObject({url: AWS + "14/50/100.png", init: {credentials: "omit"}});
        const r = await surface.load({url: "mplidar://17/409/802?v=1"});        // unit 102_200: not built
        expect(fetch.calls.pop().url).toBe(AWS + "15/102/200.png");
        expect(r.data).toEqual({cropped: {x: 102, y: 200, left: 64, top: 128, size: 64}, from: AWS + "15/102/200.png"});
    });

    it("loads a unit's tiles at their version, and reloads the terrain when a unit's tiles are made again", async () => {
        let v = 111;
        const {surface, fetch} = make(url => url.indexOf("lidar/surface") >= 0 ? {status: 200, body: {units: [{x: 100, y: 200, state: "done", v: v}]}} : {status: 200});
        await surface.request([1, 2, 3, 4]);
        await surface.load({url: "mplidar://17/401/802?v=1"});
        expect(fetch.calls.pop().url).toBe(API + "lidar/tiles/17/401/802.png?v=111");
        await surface.refresh([1, 2, 3, 4]);
        expect(tileChanges.length).toBe(1);                                   // the same version: nothing to reload
        v = 222;
        await surface.refresh([1, 2, 3, 4]);
        expect(tileChanges).toEqual([["mplidar://{z}/{x}/{y}?v=1"], ["mplidar://{z}/{x}/{y}?v=2"]]);
        await surface.load({url: "mplidar://17/401/802?v=2"});
        expect(fetch.calls.pop().url).toBe(API + "lidar/tiles/17/401/802.png?v=222");
    });

    it("decodes each zoom-15 parent once for all the tiles cut from it", async () => {
        const {surface, fetch} = make(() => ({status: 200}));
        const r = await Promise.all([surface.load({url: "mplidar://17/409/802?v=0"}), surface.load({url: "mplidar://17/410/802?v=0"}),
                                     surface.load({url: "mplidar://18/819/1604?v=0"})]);
        expect(fetch.calls.map(c => c.url)).toEqual([AWS + "15/102/200.png"]);
        expect(decoded).toEqual([AWS + "15/102/200.png"]);
        expect(r.map(t => t.data.cropped.left)).toEqual([64, 128, 96]);
    });

    it("fetches a parent again for the next tile when it could not be had", async () => {
        let fail = true;
        const {surface, fetch} = make(() => fail ? {status: 503} : {status: 200});
        await expect(surface.load({url: "mplidar://17/409/802?v=0"})).rejects.toThrow("HTTP 503");
        fail = false;
        const r = await surface.load({url: "mplidar://17/410/802?v=0"});
        expect(fetch.calls.length).toBe(2);
        expect(r.data.from).toBe(AWS + "15/102/200.png");
    });

    it("keeps a tile's parent for the others when that tile is cancelled", async () => {
        const {surface, fetch} = make(() => ({status: 200}));
        const ac = new AbortController();
        const first = surface.load({url: "mplidar://17/409/802?v=0"}, ac);
        ac.abort();
        await expect(first).rejects.toThrow();
        const r = await surface.load({url: "mplidar://17/410/802?v=0"});
        expect(r.data.from).toBe(AWS + "15/102/200.png");
        expect(fetch.calls.length).toBe(1);
    });

    it("keeps only the last parents it decoded", async () => {
        const {surface, fetch} = make(() => ({status: 200}));
        for (let i = 0; i <= L.PARENTS; i++) await surface.load({url: "mplidar://16/" + (2 * i) + "/400?v=0"});
        await surface.load({url: "mplidar://16/0/400?v=0"});                // the first, dropped since
        await surface.load({url: "mplidar://16/" + (2 * L.PARENTS) + "/400?v=0"});   // the last, still kept
        expect(fetch.calls.length).toBe(L.PARENTS + 2);
    });

    it("falls back on AWS when a built unit's tile cannot be had", async () => {
        const {surface, fetch} = make(url => url.indexOf("lidar/surface") >= 0 ? {status: 200, body: {units: [{x: 100, y: 200, state: "done"}]}}
            : url.indexOf("lidar/tiles") >= 0 ? {status: 404} : {status: 200});
        await surface.request([1, 2, 3, 4]);
        await surface.load({url: "mplidar://15/100/200?v=1"});
        expect(fetch.calls.pop().url).toBe(AWS + "15/100/200.png");
    });

    it("refuses what is not one of its tiles", async () => {
        const {surface} = make(() => ({status: 200}));
        await expect(surface.load({url: "https://example.com/1/2/3.png"})).rejects.toThrow("Not a lidar tile");
    });

    it("says why when the server refuses the area", async () => {
        const {surface} = make(() => ({status: 400, body: {error: "the area is too large for the lidar surface", too_large: true}}));
        await surface.request([1, 2, 3, 4]);
        expect(statuses.pop()).toEqual({busy: false, text: "No lidar surface: the area is too large for the lidar surface"});
        expect(timers.filter(Boolean)).toEqual([]);
    });

    it("keeps polling through a missed answer, and gives up after ten minutes", async () => {
        let down = false;
        const {surface} = make(() => down ? new Error("offline") : {status: 200, body: {units: units("queued")}});
        await surface.request([1, 2, 3, 4]);
        down = true;
        await runTimer();
        expect(timers.filter(Boolean).length).toBe(1);                        // asked again
        clock = L.POLL_DEADLINE_MS + 1;
        await runTimer();
        expect(statuses.pop().text).toContain("not built within 10 minutes");
        expect(timers.filter(Boolean)).toEqual([]);
    });

    it("stops polling when stopped, and an old request's answer is ignored", async () => {
        const {surface} = make(() => ({status: 200, body: {units: units("queued")}}));
        await surface.request([1, 2, 3, 4]);
        surface.stop();
        expect(timers.filter(Boolean)).toEqual([]);
        expect(statuses.pop()).toBeNull();

        const slow = make(() => ({status: 200, body: {units: units("done")}}));
        const first = slow.surface.request([1, 2, 3, 4]);
        slow.surface.stop();
        await first;
        expect(tileChanges).toEqual([]);
    });

    it("learns the built units quietly, without asking for a build", async () => {
        const {surface, fetch} = make(() => ({status: 200, body: {units: [{x: 100, y: 200, state: "done"}, {x: 101, y: 200, state: "missing"}]}}));
        await surface.refresh([1, 2, 3, 4]);
        expect(fetch.calls.map(c => c.init.method || "GET")).toEqual(["GET"]);
        expect(surface.isBuilt(100, 200)).toBe(true);
        expect(surface.isBuilt(101, 200)).toBe(false);
        expect(statuses).toEqual([]);
        expect(timers.filter(Boolean)).toEqual([]);
        expect(tileChanges.length).toBe(1);
    });

    it("refreshing survives a server that does not answer", async () => {
        const {surface} = make(() => new Error("offline"));
        await surface.refresh([1, 2, 3, 4]);
        expect(surface.isBuilt(100, 200)).toBe(false);
    });

    it("from the 2D map, asks again only when the route reaches other units, or after a stop", async () => {
        const {surface, fetch} = make(() => ({status: 200, body: {units: units("done")}}));
        const posts = () => fetch.calls.filter(c => c.init.method === "POST").length;
        await surface.ensure([-79.527968, 41.489, -79.526968, 41.49]);
        await surface.ensure([-79.528068, 41.4891, -79.527068, 41.4899]);     // moved a little, in the same units
        expect(posts()).toBe(1);
        await surface.ensure([-79.527968, 41.489, -79.447968, 41.49]);             // stretched east over other units
        expect(posts()).toBe(2);
        surface.stop();
        await surface.ensure([-79.527968, 41.489, -79.447968, 41.49]);
        expect(posts()).toBe(3);
        await surface.ensure(null);
        expect(posts()).toBe(3);
    });

    it("names the zoom-15 units a box spans", () => {
        expect(L.unitsKey([-79.528168, 41.4898, -79.528168, 41.4898])).toBe("9145,12226,9145,12226");
        expect(L.unitsKey([-79.537968, 41.48, -79.517968, 41.5])).not.toBe(L.unitsKey([-79.528168, 41.4898, -79.528168, 41.4898]));
    });

    it("asks for nothing without bounds", async () => {
        const {surface, fetch} = make(() => ({status: 200}));
        await surface.request(null);
        expect(fetch.calls).toEqual([]);
    });
});

// A 256 x 256 Terrarium tile of one height, its alpha `alpha`
function terrarium(h, alpha = 255) {
    const out = new Uint8ClampedArray(256 * 256 * 4), v = h + 32768;
    for (let i = 0; i < out.length; i += 4) {
        out[i] = Math.floor(v / 256); out[i + 1] = Math.floor(v) % 256; out[i + 2] = Math.floor((v - Math.floor(v)) * 256); out[i + 3] = alpha;
    }
    return out;
}
const heightOf = (rgba, i = 0) => rgba[i * 4] * 256 + rgba[i * 4 + 1] + rgba[i * 4 + 2] / 256 - 32768;

describe("a task's surface over the rest", () => {
    it("mixes the task's heights by its alpha, and keeps the surface where it is 0", () => {
        const under = terrarium(200), task = terrarium(210, 0);
        expect(heightOf(L.blend(under, task))).toBeCloseTo(200, 2);
        expect(heightOf(L.blend(under, terrarium(210, 255)))).toBeCloseTo(210, 2);
        expect(heightOf(L.blend(under, terrarium(210, 51)))).toBeCloseTo(202, 1);
        expect(L.blend(under, task)[3]).toBe(255);
    });

    it("enlarges part of a tile pixel for pixel", () => {
        const src = terrarium(0);
        src[(10 * 256 + 20) * 4] = 99;                                    // the pixel at (20, 10)
        const out = L.cropRgba(src, {left: 20, top: 10, size: 64});
        expect(out[0]).toBe(99);
        expect(out[(3 * 256 + 3) * 4]).toBe(99);                          // 4 x 4 pixels from one
        expect(out[(4 * 256 + 4) * 4]).not.toBe(99);
    });

    it("knows a tile's bounds in degrees", () => {
        const b = L.tileLonLat(1, 1, 0);
        expect(b[0]).toBeCloseTo(0, 6);
        expect(b[2]).toBeCloseTo(180, 6);
        expect(b[3]).toBeCloseTo(85.0511, 3);
    });

    // AWS answers bytes [1], the lidar [2], the task [3]; decodeRgba turns them into tiles of 200 m, 220 m and 240 m
    const X = 8 * 1000 + 3, Y = 8 * 2000 + 5, UNIT = {x: 1000, y: 2000};
    const BOUNDS = L.tileLonLat(18, X, Y);
    const tiles = {1: terrarium(200), 2: terrarium(220), 3: terrarium(240, 255)};
    let images, fetch, surface, changes;
    const setup = (handler, over = {}) => {
        images = []; changes = [];
        fetch = fakeFetch(handler);
        surface = L.createLidarSurface(Object.assign({
            fetch, api: API, csrf: "t", onTilesChanged: t => changes.push(t), onStatus: () => {},
            decodeRgba: buf => Promise.resolve(tiles[new Uint8Array(buf)[0]]),
            toImage: rgba => { images.push(rgba); return Promise.resolve({image: true}); },
            decodeParent: () => Promise.resolve({image: "parent"}), crop: (image, c) => Promise.resolve({cropped: c})
        }, over));
    };
    const answer = which => ({status: 200, bytes: new Uint8Array([which]).buffer});
    const web = (taskStatus = 200) => url => url.indexOf("task-surface/") >= 0 ? (taskStatus === 200 ? answer(3) : {status: taskStatus})
        : url.indexOf("lidar/tiles") >= 0 ? answer(2)
        : url.indexOf("lidar/surface") >= 0 ? {status: 200, body: {units: [{x: UNIT.x, y: UNIT.y, state: "done", v: 7}]}}
        : answer(1);

    it("blends the chosen task's tile over AWS's terrain, cut from its zoom-15 parent, with the task's version", async () => {
        setup(web());
        surface.setTask({id: "abc", v: 42, bounds: BOUNDS});
        expect(changes.length).toBe(1);                                    // the terrain reloads
        const r = await surface.load({url: "mplidar://18/" + X + "/" + Y + "?v=1"});
        const urls = fetch.calls.map(c => c.url);
        expect(urls).toContain(API + "task-surface/abc/tiles/18/" + X + "/" + Y + ".png?v=42");
        expect(urls).toContain(AWS + "15/" + (X >> 3) + "/" + (Y >> 3) + ".png");
        expect(heightOf(r.rgba)).toBeCloseTo(240, 2);
        expect(r.data).toEqual({image: true});
        surface.setTask({id: "abc", v: 42, bounds: BOUNDS});
        expect(changes.length).toBe(1);                                    // the same task: nothing to reload
        surface.setTask(null);
        expect(changes.length).toBe(2);
    });

    it("blends it over the lidar where its unit is built", async () => {
        setup(web());
        await surface.refresh([1, 2, 3, 4]);
        surface.setTask({id: "abc", v: 1, bounds: BOUNDS});
        tiles[3] = terrarium(240, 0);                                      // the task's edge: none of it here
        const r = await surface.load({url: "mplidar://18/" + X + "/" + Y});
        tiles[3] = terrarium(240, 255);
        expect(fetch.calls.map(c => c.url)).toContain(API + "lidar/tiles/18/" + X + "/" + Y + ".png?v=7");
        expect(heightOf(r.rgba)).toBeCloseTo(220, 2);
    });

    it("shows the surface alone where the task has no tile", async () => {
        setup(web(404));
        surface.setTask({id: "abc", v: 1, bounds: BOUNDS});
        const r = await surface.load({url: "mplidar://18/" + X + "/" + Y});
        expect(heightOf(r.rgba)).toBeCloseTo(200, 2);
    });

    it("loads the tiles away from the task as before", async () => {
        setup(web());
        surface.setTask({id: "abc", v: 1, bounds: BOUNDS});
        await surface.load({url: "mplidar://18/" + (X + 40) + "/" + Y});
        expect(fetch.calls.some(c => c.url.indexOf("task-surface/") >= 0)).toBe(false);
        expect(surface.hasTask(UNIT.x, UNIT.y)).toBe(true);
        expect(surface.hasTask(UNIT.x + 5, UNIT.y)).toBe(false);
    });

    it("leaves the lidar out while it is turned off, and reloads the terrain when that changes", async () => {
        setup(web(), {lidar: false});
        await surface.refresh([1, 2, 3, 4]);
        expect(surface.isBuilt(UNIT.x, UNIT.y)).toBe(false);
        await surface.load({url: "mplidar://15/" + UNIT.x + "/" + UNIT.y});
        expect(fetch.calls.pop().url).toBe(AWS + "15/" + UNIT.x + "/" + UNIT.y + ".png");
        const before = changes.length;
        surface.setLidar(true);
        expect(changes.length).toBe(before + 1);
        expect(surface.isBuilt(UNIT.x, UNIT.y)).toBe(true);
    });
});
