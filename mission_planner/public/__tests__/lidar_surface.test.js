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
});

describe("lidar surface", () => {
    let timers, statuses, tileChanges, clock;
    const make = (handler, over = {}) => {
        timers = [];
        statuses = [];
        tileChanges = [];
        clock = 0;
        const fetch = fakeFetch(handler);
        const surface = L.createLidarSurface(Object.assign({
            fetch, api: API, csrf: "token", now: () => clock,
            setTimeout: (f, ms) => { timers.push({f, ms}); return timers.length; }, clearTimeout: id => { timers[id - 1] = null; },
            onStatus: s => statuses.push(s), onTilesChanged: t => tileChanges.push(t),
            crop: (blob, c) => Promise.resolve({cropped: c, from: blob.url})
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
        expect(fetch.calls.pop()).toMatchObject({url: API + "lidar/tiles/17/401/802.png", init: {credentials: "same-origin"}});
        await surface.load({url: "mplidar://14/50/100?v=1"});
        expect(fetch.calls.pop()).toMatchObject({url: AWS + "14/50/100.png", init: {credentials: "omit"}});
        const r = await surface.load({url: "mplidar://17/409/802?v=1"});        // unit 102_200: not built
        expect(fetch.calls.pop().url).toBe(AWS + "15/102/200.png");
        expect(r.data).toEqual({cropped: {x: 102, y: 200, left: 64, top: 128, size: 64}, from: AWS + "15/102/200.png"});
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
