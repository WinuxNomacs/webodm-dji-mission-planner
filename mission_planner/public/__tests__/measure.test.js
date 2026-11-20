/** @jest-environment jsdom */
const M = require('../measure');

describe("the Pointer tool's labels", () => {
    it("labels a dot with its height above sea level, as the pointer tooltip does", () => {
        expect(M.dotText(216.24, "metric")).toBe("216.2 m ASL");
        expect(M.dotText(216.24, "imperial")).toBe("709 ft ASL");
        expect(M.dotText(undefined, "metric")).toBe("…");
        expect(M.dotText(null, "metric")).toBe("no height");
    });

    it("labels a line with the later dot's height minus the earlier's, signed, one decimal, in the editor's units", () => {
        expect(M.diffText(200, 212.3, "metric")).toBe("+12.3 m");
        expect(M.diffText(212, 208, "metric")).toBe("-4.0 m");
        expect(M.diffText(200, 210, "imperial")).toBe("+32.8 ft");
        expect(M.diffText(200, 200, "metric")).toBe("+0.0 m");
        expect(M.diffText(200, 199.98, "metric")).toBe("+0.0 m");                        // never "-0.0"
    });

    it("shows no difference while either height is missing", () => {
        expect(M.diffText(200, undefined, "metric")).toBe("");
        expect(M.diffText(null, 200, "metric")).toBe("");
    });

    it("joins each dot to the one before, with the line's middle for its label", () => {
        const s = M.segments([[0, 0], [2, 4], [4, 4]]);
        expect(s.map(x => [x.from, x.to])).toEqual([[0, 1], [1, 2]]);
        expect(s[0].middle).toEqual([1, 2]);
        expect(M.segments([[0, 0]])).toEqual([]);
    });
});

// A stand-in for MapLibre: markers kept in a list, one GeoJSON source
function fakeMap() {
    const markers = [], sources = {}, layers = [];
    class Marker {
        constructor(o) { this.el = o.element; }
        setLngLat(p) { this.lngLat = p; return this; }
        addTo() { markers.push(this); document.body.appendChild(this.el); return this; }
        getElement() { return this.el; }
        remove() { markers.splice(markers.indexOf(this), 1); this.el.remove(); }
    }
    const map = {
        getSource: id => sources[id],
        addSource: (id) => { sources[id] = {data: null, setData(d) { this.data = d; }}; },
        addLayer: (l, before) => layers.push({id: l.id, before})
    };
    return {maplibregl: {Marker}, map, markers, sources, layers};
}

// Heights answered by hand: each asked point waits until answer() is called for it
function heights() {
    const asked = [];
    return {asked, heightAt: (lng, lat) => new Promise((resolve, reject) => asked.push({lng, lat, resolve, reject}))};
}

const flush = () => new Promise(r => setTimeout(r, 0));
const click = (lng, lat, target) => ({lngLat: {lng, lat}, originalEvent: {target: target || document.body}});
const dotLabels = () => [...document.querySelectorAll(".mp-measure-dot .mp-measure-label")].map(e => e.textContent);
const diffLabels = () => [...document.querySelectorAll(".mp-measure-diff")].map(e => (e.hidden ? "(hidden)" : e.textContent));

describe("the Pointer tool's dots", () => {
    let f, h, units, m;
    beforeEach(() => {
        document.body.innerHTML = "";
        f = fakeMap();
        h = heights();
        units = "metric";
        m = M.createMeasure({maplibregl: f.maplibregl, map: f.map, doc: document, heightAt: h.heightAt, units: () => units, before: "mp-takeoff"});
    });

    it("puts a dot at each click, labelled once its height is read, and joins it to the one before", async () => {
        m.click(click(1, 2));
        expect(dotLabels()).toEqual(["…"]);
        h.asked[0].resolve({height: 200, source: "terrain"});
        await flush();
        expect(dotLabels()).toEqual(["200.0 m ASL"]);

        m.click(click(3, 4));
        h.asked[1].resolve({height: 212.34, source: "lidar"});
        await flush();
        expect(dotLabels()).toEqual(["200.0 m ASL", "212.3 m ASL"]);
        expect(diffLabels()).toEqual(["+12.3 m"]);
        expect(f.sources["mp-measure"].data.features.map(x => x.geometry.coordinates)).toEqual([[[1, 2], [3, 4]]]);
        expect(f.layers).toEqual([{id: "mp-measure-halo", before: "mp-takeoff"}, {id: "mp-measure", before: "mp-takeoff"}]);
        expect([h.asked[1].lng, h.asked[1].lat]).toEqual([3, 4]);
    });

    it("chains the dots: each line is labelled with its own two dots' difference", async () => {
        [[0, 0, 210], [1, 0, 215.5], [2, 0, 205]].forEach(([lng, lat]) => m.click(click(lng, lat)));
        h.asked.forEach((a, i) => a.resolve({height: [210, 215.5, 205][i]}));
        await flush();
        expect(diffLabels()).toEqual(["+5.5 m", "-10.5 m"]);
    });

    it("labels each dot when its own height arrives, whatever the order", async () => {
        m.click(click(0, 0));
        m.click(click(1, 0));
        h.asked[1].resolve({height: 220});
        await flush();
        expect(dotLabels()).toEqual(["…", "220.0 m ASL"]);
        expect(diffLabels()).toEqual(["(hidden)"]);
        h.asked[0].resolve({height: 200});
        await flush();
        expect(diffLabels()).toEqual(["+20.0 m"]);
    });

    it("says no height where the tile can't be read, and shows no difference on its lines", async () => {
        m.click(click(0, 0));
        m.click(click(1, 0));
        m.click(click(2, 0));
        h.asked[0].resolve({height: 200});
        h.asked[1].resolve(null);
        h.asked[2].reject(new Error("tile"));
        await flush();
        expect(dotLabels()).toEqual(["200.0 m ASL", "no height", "no height"]);
        expect(diffLabels()).toEqual(["(hidden)", "(hidden)"]);
    });

    it("clears every dot and line when a dot is clicked, and drops heights still coming for them", async () => {
        m.click(click(0, 0));
        m.click(click(1, 0));
        h.asked[0].resolve({height: 200});
        await flush();
        const dot = document.querySelector(".mp-measure-dot .mp-measure-label");
        expect(m.click(click(0, 0, dot))).toBe(true);
        expect(m.count()).toBe(0);
        expect(f.markers).toEqual([]);
        expect(f.sources["mp-measure"].data.features).toEqual([]);
        h.asked[1].resolve({height: 230});
        await flush();
        expect(document.querySelectorAll(".mp-measure-dot, .mp-measure-diff").length).toBe(0);

        m.click(click(5, 5));                                                        // a new chain starts
        expect(m.count()).toBe(1);
        expect(diffLabels()).toEqual([]);
    });

    it("is cleared by the editor (another tool chosen)", () => {
        m.click(click(0, 0));
        m.click(click(1, 0));
        m.clear();
        expect(f.markers).toEqual([]);
        expect(m.count()).toBe(0);
    });

    it("relabels in the other units", async () => {
        m.click(click(0, 0));
        m.click(click(1, 0));
        h.asked[0].resolve({height: 200});
        h.asked[1].resolve({height: 210});
        await flush();
        units = "imperial";
        m.relabel();
        expect(dotLabels()).toEqual(["656 ft ASL", "689 ft ASL"]);
        expect(diffLabels()).toEqual(["+32.8 ft"]);
    });

    it("reads every dot again when the surface changes (the lidar built), keeping its label meanwhile", async () => {
        m.click(click(0, 0));
        h.asked[0].resolve({height: 200, source: "terrain"});
        await flush();
        m.reread();
        expect(h.asked.length).toBe(2);
        expect(dotLabels()).toEqual(["200.0 m ASL"]);
        h.asked[1].resolve({height: 212, source: "lidar"});
        await flush();
        expect(dotLabels()).toEqual(["212.0 m ASL"]);
    });
});
