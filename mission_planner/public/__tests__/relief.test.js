const R = require('../relief');

// A map with the layers the editors have in 3D: the basemap, the elevation source, the hillshade
function fakeMap() {
    const layers = {"mp-basemap": {paint: {}}, "mp-hillshade": {paint: {}}}, order = [];
    return {
        layers, order,
        getLayer(id) { return layers[id]; },
        getSource(id) { return id === "mp-dem" ? {} : undefined; },
        addLayer(layer, before) { layers[layer.id] = {paint: Object.assign({}, layer.paint), type: layer.type, source: layer.source}; order.push([layer.id, before]); },
        removeLayer(id) { delete layers[id]; },
        setPaintProperty(id, k, v) { layers[id].paint[k] = v; }
    };
}
const BOUNDS = [-79.53, 41.48, -79.52, 41.49];

describe("the relief's colours", () => {
    it("span the heights round the route, leaving out the lowest and highest few", () => {
        const heights = Array.from({length: 100}, (_, i) => 200 + i).concat([null, 5000]);
        const [lo, hi] = R.heightRange(heights);
        expect(lo).toBeGreaterThanOrEqual(201);
        expect(lo).toBeLessThan(205);
        expect(hi).toBeGreaterThan(295);
        expect(hi).toBeLessThan(300);
    });

    it("span at least 10 m, so that flat ground is not coloured from end to end", () => {
        expect(R.heightRange([210, 210.5, 211, 210])).toEqual([205.5, 215.5]);
    });

    it("are none without a height", () => {
        expect(R.heightRange([null, null])).toBeNull();
        expect(R.heightRange([])).toBeNull();
    });

    it("go from blue on the lowest ground to red on the highest roofs", () => {
        const ramp = R.colorRamp([200, 240]);
        expect(ramp.slice(0, 3)).toEqual(["interpolate", ["linear"], ["elevation"]]);
        expect(ramp[3]).toBe(200);
        expect(ramp[ramp.length - 2]).toBe(240);
        expect(ramp[4]).toBe(R.COLORS[0]);
        expect(ramp[ramp.length - 1]).toBe(R.COLORS[R.COLORS.length - 1]);
    });

    it("are read on a grid over the route and 100 m round it", () => {
        const points = R.gridPoints([-79.53, 41.48, -79.52, 41.49], 5);
        expect(points.length).toBe(25);
        const lngs = points.map(p => p[0]), lats = points.map(p => p[1]);
        expect(Math.min(...lngs)).toBeLessThan(-79.53);
        expect(Math.max(...lats)).toBeGreaterThan(41.49);
    });
});

describe("the relief on the map", () => {
    const make = heights => {
        const map = fakeMap(), asked = [];
        const relief = R.createRelief({map, heightsAt: points => { asked.push(points.length); return Promise.resolve(points.map(heights)); }});
        return {map, relief, asked};
    };

    it("colours the ground by height under the hillshade, the photo faint and the shading stronger", async () => {
        const {map, relief} = make((p, i) => 200 + i % 40);
        await relief.apply(true, BOUNDS);
        const layer = map.layers[R.LAYER];
        expect(layer).toMatchObject({type: "color-relief", source: "mp-dem"});
        expect(map.order).toEqual([[R.LAYER, "mp-hillshade"]]);
        expect(layer.paint["color-relief-color"][3]).toBeGreaterThanOrEqual(200);
        expect(map.layers["mp-basemap"].paint["raster-opacity"]).toBe(R.PHOTO_OPACITY);
        expect(map.layers["mp-hillshade"].paint["hillshade-method"]).toBe("igor");
    });

    it("puts the photo and the shading back when turned off", async () => {
        const {map, relief} = make(() => 210);
        await relief.apply(true, BOUNDS);
        await relief.apply(false);
        expect(map.layers[R.LAYER]).toBeUndefined();
        expect(map.layers["mp-basemap"].paint["raster-opacity"]).toBe(1);
        expect(map.layers["mp-hillshade"].paint).toMatchObject({"hillshade-method": "standard", "hillshade-exaggeration": 0.35});
    });

    it("sets its colours again for a route moved elsewhere", async () => {
        let base = 200;
        const {map, relief} = make(() => base);
        await relief.apply(true, BOUNDS);
        base = 400;
        await relief.refresh(BOUNDS);
        expect(map.layers[R.LAYER].paint["color-relief-color"][3]).toBeGreaterThan(390);
    });

    it("adds nothing when the heights come after it was turned off", async () => {
        const map = fakeMap();
        let answer;
        const relief = R.createRelief({map, heightsAt: points => new Promise(r => { answer = () => r(points.map(() => 210)); })});
        const on = relief.apply(true, BOUNDS);
        await relief.apply(false);
        answer();
        await on;
        expect(map.layers[R.LAYER]).toBeUndefined();
    });

    it("keeps the photo faint on a basemap chosen while it is on", async () => {
        const {map, relief} = make(() => 210);
        await relief.apply(true, BOUNDS);
        map.layers["mp-basemap"] = {paint: {}};                 // the editor put another basemap in
        relief.basemapChanged();
        expect(map.layers["mp-basemap"].paint["raster-opacity"]).toBe(R.PHOTO_OPACITY);
    });
});
