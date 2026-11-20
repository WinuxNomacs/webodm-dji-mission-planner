const R = require('../route_3d');

const LNG = -79.528168, LAT = 41.4898;
const flat = h => () => h;

describe("the route's heights above sea level", () => {
    it("keeps heights above sea level as they are, the path cut into pieces to check along its length", () => {
        const air = {reference: "sea", paths: [[[LNG, LAT, 250], [LNG + 0.001, LAT, 260]]], drops: [[LNG, LAT, 250]]};   // about 83 m
        const r = R.resolveAir(air, flat(216), null, 5);
        expect(r.points).toEqual([[[LNG, LAT, 250], [LNG + 0.001, LAT, 260]]]);
        expect(r.paths[0].length).toBe(18);
        expect(r.paths[0][0]).toEqual([LNG, LAT, 250]);
        expect(r.paths[0][17]).toEqual([LNG + 0.001, LAT, 260]);
        expect(r.paths[0][9][2]).toBeCloseTo(250 + 10 * 9 / 17);
        expect(r.drops).toEqual([[LNG, LAT, 250, 216]]);
    });

    it("adds the surface under each point to heights above it, the path cut into pieces that follow it", () => {
        const air = {reference: "surface", paths: [[[LNG, LAT, 30], [LNG + 0.0006, LAT, 30]]], drops: []};   // about 50 m
        const surface = lng => (lng > LNG + 0.0003 ? 230 : 210);
        const r = R.resolveAir(air, surface, null, 5);
        expect(r.paths[0].length).toBeGreaterThanOrEqual(10);
        expect(r.paths[0][0][2]).toBe(240);
        expect(r.paths[0][r.paths[0].length - 1][2]).toBe(260);
        expect(new Set(r.paths[0].map(p => p[2]))).toEqual(new Set([240, 260]));
        expect(r.points).toEqual([[[LNG, LAT, 240], [LNG + 0.0006, LAT, 260]]]);   // the plan's own points, lifted alike
    });

    it("adds the takeoff point's surface to heights above it, or the first point's without a takeoff point", () => {
        const air = {reference: "takeoff", paths: [[[LNG, LAT, 40], [LNG + 0.001, LAT, 50]]], drops: []};
        const surface = lng => (lng === LNG - 0.01 ? 200 : 216);
        expect(R.resolveAir(air, surface, [LNG - 0.01, LAT]).points[0].map(p => p[2])).toEqual([240, 250]);
        expect(R.resolveAir(air, surface, null).points[0].map(p => p[2])).toEqual([256, 266]);
    });

    it("is not known while the surface it needs is not loaded", () => {
        expect(R.resolveAir({reference: "surface", paths: [[[LNG, LAT, 30]]], drops: []}, () => null)).toBeNull();
        expect(R.resolveAir({reference: "takeoff", paths: [[[LNG, LAT, 30]]], drops: []}, () => null)).toBeNull();
        expect(R.resolveAir(null, flat(0))).toBeNull();
        expect(R.resolveAir({reference: "sea", paths: [[]], drops: []}, flat(0))).toBeNull();
    });

    it("leaves out a line down from a point at or below the surface, or over a surface not loaded", () => {
        const air = {reference: "sea", paths: [[[LNG, LAT, 250]]], drops: [[LNG, LAT, 250], [LNG + 0.001, LAT, 200], [LNG + 0.002, LAT, 260]]};
        const surface = lng => (lng === LNG + 0.002 ? null : 216);
        expect(R.resolveAir(air, surface).drops).toEqual([[LNG, LAT, 250, 216]]);
    });

    it("cuts no more than its budget of pieces over every path", () => {
        const long = [[LNG, LAT, 30], [LNG + 1, LAT, 30]];                 // about 83 km
        const budget = {left: 100};
        const cut = R.cut(long, 5, budget);
        expect(cut.length).toBe(101);
        expect(R.cut(long, 5, budget).length).toBe(2);                       // nothing left: just the ends
    });
});

describe("the waypoint labels", () => {
    const reader = heights => (lng) => Promise.resolve(heights[lng] === undefined ? null : {height: heights[lng]});

    it("are each point's height above sea level less the surface under it", async () => {
        const air = {reference: "sea", paths: [[[1, LAT, 256], [2, LAT, 256]]]};
        await expect(R.labelHeights(air, reader({1: 216, 2: 260}))).resolves.toEqual([40, -4]);
    });

    it("add the takeoff point's surface to heights above it", async () => {
        const air = {reference: "takeoff", paths: [[[1, LAT, 40], [2, LAT, 40]]]};
        await expect(R.labelHeights(air, reader({0: 200, 1: 216, 2: 190}), [0, LAT])).resolves.toEqual([24, 50]);
        await expect(R.labelHeights(air, reader({1: 216, 2: 190}))).resolves.toEqual([40, 66]);
    });

    it("are the heights themselves above the surface", async () => {
        const air = {reference: "surface", paths: [[[1, LAT, 40], [2, LAT, 25]]]};
        await expect(R.labelHeights(air, reader({}))).resolves.toEqual([40, 25]);
    });

    it("are unknown where the surface is", async () => {
        const air = {reference: "sea", paths: [[[1, LAT, 256], [2, LAT, 256]]]};
        await expect(R.labelHeights(air, reader({1: 216}))).resolves.toEqual([40, null]);
        await expect(R.labelHeights({reference: "takeoff", paths: [[[1, LAT, 40]]]}, reader({1: 216}), [9, LAT])).resolves.toEqual([null]);
        await expect(R.labelHeights(null, reader({}))).resolves.toEqual([]);
    });

    it("say the height in the editor's units, and whether the point is below the surface", () => {
        expect(R.formatLabel(38.4, "metric")).toEqual({text: "38 m", below: false});
        expect(R.formatLabel(38.4, "imperial")).toEqual({text: "126 ft", below: false});
        expect(R.formatLabel(-4.2, "metric")).toEqual({text: "-4 m", below: true});
        expect(R.formatLabel(-0.2, "metric")).toEqual({text: "0 m", below: true});
    });
});

describe("the geometry drawn", () => {
    // A world 1 unit per meter east, north and up, from (0, 0, 0)
    const toWorld = (lng, lat, h) => [lng, lat, h];
    const resolved = {paths: [[[10, 20, 30], [11, 20, 30], [11, 21, 31]]], drops: [[10, 20, 30, 0]]};
    const f32 = c => Array.from(new Float32Array(c));
    const blue = f32([0.118, 0.533, 0.898, 1]), yellow = f32([1, 0.835, 0, 1]), red = f32([0.898, 0.224, 0.208, 1]);

    it("is relative to the route's first point", () => {
        const g = R.buildGeometry(resolved, toWorld, true);
        expect(g.origin).toEqual([10, 20, 30]);
        expect(Array.from(g.lines.slice(0, 12))).toEqual([0, 0, 0, 1, 0, 0, -1, 0].concat(blue));
    });

    it("has two triangles for each segment and each line down, and for each disc", () => {
        const g = R.buildGeometry(resolved, toWorld, true);
        expect(g.lineCount).toBe(2 * 6);
        expect(g.lines.length).toBe(2 * 6 * 12);
        expect(g.dropCount).toBe(6);
        expect(Array.from(g.drops.slice(0, 6))).toEqual([0, 0, 0, 0, 0, -30]);
        expect(g.discCount).toBe(3 * 6);
        expect(R.buildGeometry(resolved, toWorld, false).discCount).toBe(0);
    });

    it("draws each segment's quad from both ends, sides opposite", () => {
        const g = R.buildGeometry({paths: [[[0, 0, 0], [1, 0, 0]]], drops: []}, toWorld, false);
        const vertices = [];
        for (let i = 0; i < 6; i++) vertices.push(Array.from(g.lines.slice(i * 12, i * 12 + 12)));
        expect(vertices.map(v => [v[0], v[6], v[7]])).toEqual([[0, -1, 0], [0, 1, 0], [1, -1, 1], [0, 1, 0], [1, 1, 1], [1, -1, 1]]);
    });

    it("colours each segment by its kind, and has the segments inside the surface again, to draw through it", () => {
        const g = R.buildGeometry({...resolved, kinds: [[R.NEAR, R.INSIDE]]}, toWorld, false);
        expect(Array.from(g.lines.slice(8, 12))).toEqual(yellow);
        expect(Array.from(g.lines.slice(6 * 12 + 8, 6 * 12 + 12))).toEqual(red);
        expect(g.insideCount).toBe(6);
        expect(Array.from(g.inside.slice(0, 3))).toEqual([1, 0, 0]);
        expect(R.buildGeometry(resolved, toWorld, false).insideCount).toBe(0);
    });

    it("puts the discs at the plan's own points, not at every piece", () => {
        const g = R.buildGeometry({...resolved, points: [[[10, 20, 30], [11, 21, 31]]]}, toWorld, true);
        expect(g.discCount).toBe(2 * 6);
        expect(Array.from(g.discs.slice(6 * 5, 6 * 5 + 3))).toEqual([1, 1, 1]);
    });

    it("moves the matrix to the origin: positions relative to it land where the whole ones do", () => {
        const m = [2, 0, 0, 0, 0, 3, 0, 0, 0, 0, 4, 0, 5, 6, 7, 1];
        const t = R.translated(m, [10, 20, 30]);
        const apply = (mm, v) => [0, 1, 2, 3].map(r => mm[r] * v[0] + mm[4 + r] * v[1] + mm[8 + r] * v[2] + mm[12 + r]);
        expect(apply(t, [1, 1, 1])).toEqual(apply(m, [11, 21, 31]));
    });
});

describe("the collisions with the surface", () => {
    // A path east along the latitude, every 5 m, at 100 m above sea level; the surface from `ground(meters east)`
    const M_PER_DEG = 111320 * Math.cos(LAT * Math.PI / 180);
    const east = m => LNG + m / M_PER_DEG;
    const path = (to, step = 5, h = 100) => { const p = []; for (let m = 0; m <= to; m += step) p.push([east(m), LAT, h]); return p; };
    const surface = ground => lng => ground((lng - LNG) * M_PER_DEG);
    // The stretches of each kind as [from, to] meters east, joined
    function stretches(hit, i = 0) {
        const out = {[R.CLEAR]: [], [R.NEAR]: [], [R.INSIDE]: []};
        hit.kinds[i].forEach((k, j) => {
            const a = (hit.paths[i][j][0] - LNG) * M_PER_DEG, b = (hit.paths[i][j + 1][0] - LNG) * M_PER_DEG, list = out[k];
            if (list.length && Math.abs(list[list.length - 1][1] - a) < 1e-6) list[list.length - 1][1] = b;
            else list.push([a, b]);
        });
        Object.values(out).forEach(l => l.forEach(r => { r[0] = Math.round(r[0] * 100) / 100; r[1] = Math.round(r[1] * 100) / 100; }));
        return out;
    }

    it("finds nothing on a path above the surface, and keeps it as it is", () => {
        const p = path(100);
        const hit = R.collide([p], flat(60));
        expect(hit.count).toBe(0);
        expect(hit.paths).toEqual([p]);
        expect(new Set(hit.kinds[0])).toEqual(new Set([R.CLEAR]));
    });

    it("is red from where the path goes into the surface to where it comes out, the crossings added", () => {
        // A building 102 m high from 41 to 63 m east: the path at 100 m is inside it from 41 to 63 m, the crossings
        // between pieces of the path, interpolated from the clearance at each end (here at the edges' steps)
        const ground = m => (m > 40 && m < 64 ? 102 : 60);
        const hit = R.collide([path(100)], surface(ground));
        expect(hit.count).toBe(1);
        const s = stretches(hit);
        expect(s[R.INSIDE].length).toBe(1);
        const [a, b] = s[R.INSIDE][0];
        expect(a).toBeGreaterThan(40); expect(a).toBeLessThan(45);       // between the last piece outside and the first inside
        expect(b).toBeGreaterThan(60); expect(b).toBeLessThan(65);
        expect(s[R.NEAR]).toEqual([[a - 10, a], [b, b + 10]].map(r => r.map(v => Math.round(v * 100) / 100)));
    });

    it("finds the crossing where the clearance passes zero along a sloping path", () => {
        // The path climbs from 50 to 150 m over 100 m; the ground at 80 m: it comes out of the ground at 30 m east
        const p = path(100).map((q, i) => [q[0], q[1], 50 + i * 5]);
        const hit = R.collide([p], flat(80));
        const s = stretches(hit);
        expect(s[R.INSIDE]).toEqual([[0, 30]]);
        expect(s[R.NEAR]).toEqual([[30, 40]]);                             // no yellow before the path's start
        expect(s[R.CLEAR]).toEqual([[40, 100]]);
    });

    it("joins the yellow between two collisions closer than twice its length, and counts both", () => {
        const ground = m => ((m >= 20 && m <= 30) || (m >= 45 && m <= 55) ? 120 : 60);
        const hit = R.collide([path(100, 1)], surface(ground));
        expect(hit.count).toBe(2);
        const s = stretches(hit);
        expect(s[R.INSIDE].length).toBe(2);
        expect(s[R.NEAR].length).toBe(3);                                  // before, between (joined), after
        const between = s[R.NEAR][1];
        expect(between[0]).toBeCloseTo(s[R.INSIDE][0][1], 1);
        expect(between[1]).toBeCloseTo(s[R.INSIDE][1][0], 1);
    });

    it("stops the yellow at the path's ends, and counts the collisions of every path", () => {
        const ground = m => (m <= 4 || m >= 96 ? 120 : 60);
        const hit = R.collide([path(100), path(50)], surface(ground));
        expect(hit.count).toBe(3);
        const s = stretches(hit);
        expect(s[R.INSIDE][0][0]).toBe(0);
        expect(s[R.INSIDE][1][1]).toBe(100);
        expect(s[R.NEAR].every(r => r[0] >= 0 && r[1] <= 100)).toBe(true);
    });

    it("keeps red over yellow where a collision is closer than the yellow's length to the next", () => {
        const ground = m => ((m >= 20 && m <= 30) || (m >= 35 && m <= 45) ? 120 : 60);
        const s = stretches(R.collide([path(100, 1)], surface(ground)));
        expect(s[R.INSIDE].length).toBe(2);
        expect(s[R.INSIDE][1][1] - s[R.INSIDE][1][0]).toBeGreaterThan(9);
        expect(s[R.NEAR][1][0]).toBeCloseTo(s[R.INSIDE][0][1], 1);         // the gap between them is yellow
        expect(s[R.NEAR][1][1]).toBeCloseTo(s[R.INSIDE][1][0], 1);
    });

    it("finds nothing on a path that only touches the surface", () => {
        expect(R.collide([path(50)], flat(100)).count).toBe(0);
    });

    it("takes a point over a surface not loaded as clear of it", () => {
        const hit = R.collide([path(50)], () => null);
        expect(hit.count).toBe(0);
        expect(new Set(hit.kinds[0])).toEqual(new Set([R.CLEAR]));
    });

    it("says in the side panel how many places the route goes into the surface", () => {
        expect(R.collisionText(0)).toEqual({text: "The route stays above the surface.", hit: false});
        expect(R.collisionText(1)).toEqual({text: "The route goes into the surface in 1 place: red on the map.", hit: true});
        expect(R.collisionText(3).text).toBe("The route goes into the surface in 3 places: red on the map.");
    });
});

describe("the points read for a plan", () => {
    it("are every piece of every path, the takeoff point and the drop lines' feet, each once", () => {
        const air = {reference: "takeoff", paths: [[[LNG, LAT, 50], [LNG + 0.0001, LAT, 50]], [[LNG, LAT, 50]]], drops: [[LNG, LAT, 50]]};
        const need = R.pointsNeeded(air, [LNG - 0.001, LAT]);
        expect(need.points[0]).toEqual([LNG - 0.001, LAT]);                           // the takeoff point first
        const resolved = R.resolveAir(air, () => 0, [LNG - 0.001, LAT]);
        resolved.paths.forEach(path => path.forEach(p => expect(need.index[p[0] + "," + p[1]]).toBeDefined()));
        expect(need.points.length).toBe(1 + resolved.paths[0].length);              // the second path and the drop: no new point
        need.points.forEach((p, i) => expect(need.index[p[0] + "," + p[1]]).toBe(i));
    });

    it("are none without a plan", () => {
        expect(R.pointsNeeded(null, null).points).toEqual([]);
    });
});

describe("the stretches on the 2D map", () => {
    it("are a line for each run of segments near or inside the surface, the red sorted over the yellow", () => {
        const path = [0, 1, 2, 3, 4, 5].map(i => [LNG + i * 0.0001, LAT, 200]);
        const fc = R.flatStretches({paths: [path, path.slice(0, 2)], kinds: [[R.CLEAR, R.NEAR, R.INSIDE, R.INSIDE, R.NEAR], [R.CLEAR]]});
        expect(fc.type).toBe("FeatureCollection");
        expect(fc.features.map(f => [f.properties.kind, f.geometry.coordinates.length])).toEqual([["near", 2], ["inside", 3], ["near", 2]]);
        expect(fc.features[1].geometry.coordinates).toEqual([path[2].slice(0, 2), path[3].slice(0, 2), path[4].slice(0, 2)]);
        expect(fc.features.map(f => f.properties.order)).toEqual([R.NEAR, R.INSIDE, R.NEAR]);
    });

    it("are two lines for two stretches of one colour with clear line between them", () => {
        const path = [0, 1, 2, 3].map(i => [LNG + i * 0.0001, LAT, 200]);
        const fc = R.flatStretches({paths: [path], kinds: [[R.NEAR, R.CLEAR, R.NEAR]]});
        expect(fc.features.map(f => f.geometry.coordinates)).toEqual([[path[0].slice(0, 2), path[1].slice(0, 2)], [path[2].slice(0, 2), path[3].slice(0, 2)]]);
    });

    it("are none where the route stays above the surface, or without a check", () => {
        expect(R.flatStretches({paths: [[[LNG, LAT, 1], [LNG, LAT + 0.001, 1]]], kinds: [[R.CLEAR]]}).features).toEqual([]);
        expect(R.flatStretches(null).features).toEqual([]);
    });
});

describe("the route under the pointer", () => {
    const screen = (lng, lat) => ({x: (lng - LNG) * 1e5, y: (lat - LAT) * 1e5});     // 1 pixel = 0.00001 degree
    const paths = [[[LNG, LAT, 200], [LNG + 0.001, LAT, 300]]];                          // 100 pixels long

    it("is the nearest point of the line within a few pixels, at its height there", () => {
        const at = R.nearest(paths, screen, {x: 25, y: 4}, R.NEAR_PX);
        expect(at.lng).toBeCloseTo(LNG + 0.00025, 9);
        expect(at.lat).toBeCloseTo(LAT, 9);
        expect(at.height).toBeCloseTo(225, 6);
        expect(R.nearest(paths, screen, {x: -3, y: 0}, R.NEAR_PX).height).toBe(200);   // past the end: the end
    });

    it("is nothing farther than that, or off the screen", () => {
        expect(R.nearest(paths, screen, {x: 25, y: R.NEAR_PX + 1}, R.NEAR_PX)).toBeNull();
        expect(R.nearest(paths, () => null, {x: 25, y: 0}, R.NEAR_PX)).toBeNull();
        expect(R.nearest(null, screen, {x: 25, y: 0}, R.NEAR_PX)).toBeNull();
    });

    it("is a lone point when the path has only one", () => {
        expect(R.nearest([[[LNG, LAT, 120]]], screen, {x: 2, y: 2}, R.NEAR_PX)).toEqual({lng: LNG, lat: LAT, height: 120});
    });
});

describe("the layer on the map", () => {
    function fakeMap() {
        const layers = {}, sources = {};
        return {
            layers, sources, repaints: 0, order: [],
            on() {},
            getLayer(id) { return layers[id]; },
            addLayer(layer, before) { layers[layer.id] = layer; this.order.push([layer.id, before]); },
            addSource(id, src) { sources[id] = {data: src.data, setData(d) { this.data = d; }}; },
            getSource(id) { return sources[id]; },
            queryTerrainElevation() { return null; },
            triggerRepaint() { this.repaints++; },
            project(ll) { return {x: (ll[0] - LNG) * 1e5, y: (ll[1] - LAT) * 1e5}; },
            getCanvas() { return {clientWidth: 200, clientHeight: 100}; }
        };
    }
    // pointer_height.js's heightsAt over a surface of one height (null: not loaded)
    function sampler(surface) {
        const asked = [];
        return {asked, heightsAt(points) { asked.push(points.length); return Promise.resolve(points.map(() => surface.value)); }};
    }
    const maplibregl = {MercatorCoordinate: {fromLngLat: (ll, h) => ({x: ll[0], y: ll[1], z: h || 0})}};
    const air = {reference: "surface", paths: [[[LNG, LAT, 30]]], drops: [[LNG, LAT, 30]]};
    const through = {reference: "sea", paths: [[[LNG, LAT, 230], [LNG + 0.001, LAT, 230]]], drops: []};

    it("checks the route against the surface read at its points, and adds the 3D layer when shown", async () => {
        const surface = {value: null}, s = sampler(surface), map = fakeMap();
        const r3d = R.createRoute3d({maplibregl, map, id: "mp-route-3d", heightsAt: s.heightsAt});
        await r3d.setAir(air, null);
        expect(r3d.resolved()).toBeNull();                       // no surface: nothing to check against
        surface.value = 216;
        await r3d.refresh();
        expect(r3d.resolved().paths[0][0][2]).toBe(246);
        expect(r3d.resolved().count).toBe(0);
        expect(s.asked).toEqual([1, 1]);
        r3d.show(true);
        expect(map.layers["mp-route-3d"].type).toBe("custom");
        expect(s.asked).toEqual([1, 1]);                          // showing draws what was checked: nothing read again
    });

    it("reports the collisions in 2D and 3D, and none without a plan", async () => {
        const surface = {value: 216}, map = fakeMap(), counts = [];
        const r3d = R.createRoute3d({maplibregl, map, id: "mp-route-3d", heightsAt: sampler(surface).heightsAt, onCollisions: n => counts.push(n)});
        await r3d.setAir(through, null);                          // in 2D
        surface.value = 240;                                      // the surface comes up over the path (the lidar built)
        await r3d.refresh();
        r3d.show(true);
        await r3d.setAir(null, null);
        expect(counts).toEqual([0, 1, null]);
    });

    it("draws the stretches on the 2D map's layer in 2D, and only the 3D layer in 3D", async () => {
        const map = fakeMap();
        map.layers["mp-waypoints"] = {id: "mp-waypoints"};
        const r3d = R.createRoute3d({maplibregl, map, id: "mp-route-3d", before: "mp-takeoff", flatBefore: "mp-waypoints",
                                     heightsAt: sampler({value: 240}).heightsAt});
        expect(map.order[0]).toEqual(["mp-route-3d-flat", "mp-waypoints"]);
        await r3d.setAir(through, null);
        const kinds = map.sources["mp-route-3d-flat"].data.features.map(f => f.properties.kind);
        expect(kinds).toEqual(["inside"]);                        // the whole path inside: no yellow inside its ends
        r3d.show(true);
        expect(map.sources["mp-route-3d-flat"].data.features).toEqual([]);
        r3d.show(false);
        expect(map.sources["mp-route-3d-flat"].data.features.length).toBe(1);
    });

    it("drops an older check still reading when the plan changed meanwhile", async () => {
        const map = fakeMap(), pending = [];
        const r3d = R.createRoute3d({maplibregl, map, id: "mp-route-3d",
                                     heightsAt: points => new Promise(resolve => pending.push(() => resolve(points.map(() => 216))))});
        const first = r3d.setAir({reference: "sea", paths: [[[LNG, LAT, 500]]], drops: []}, null);
        const second = r3d.setAir({reference: "sea", paths: [[[LNG, LAT, 600]]], drops: []}, null);
        pending[1]();
        await second;
        pending[0]();
        await first;
        expect(r3d.resolved().paths[0][0][2]).toBe(600);
    });

    it("finds the route under the pointer on the 2D map at its place, and nothing before it is checked", async () => {
        const map = fakeMap();
        const r3d = R.createRoute3d({maplibregl, map, id: "mp-route-3d", heightsAt: sampler({value: 216}).heightsAt});
        expect(r3d.routeNear({x: 0, y: 0})).toBeNull();
        await r3d.setAir({reference: "sea", paths: [[[LNG, LAT, 250], [LNG + 0.001, LAT, 250]]], drops: []}, null);
        expect(r3d.routeNear({x: 50, y: 3}).height).toBeCloseTo(250, 6);
        expect(r3d.routeNear({x: 50, y: 30})).toBeNull();
    });

    it("projects a point in the air with the last frame's matrix, in CSS pixels", () => {
        const map = fakeMap();
        const r3d = R.createRoute3d({maplibregl, map, id: "mp-route-3d", heightsAt: sampler({value: 0}).heightsAt});
        expect(r3d.project(0, 0, 0)).toBeNull();                 // before the first frame
        const identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
        r3d.layer.render(null, {defaultProjectionData: {mainMatrix: identity}});
        expect(r3d.project(0.5, 0.5, 0)).toEqual({x: 150, y: 25});
        expect(r3d.project(-1, 1, 0)).toEqual({x: 0, y: 0});
    });
});

describe("dragging a point in the air", () => {
    // Web Mercator as MapLibre's MercatorCoordinate.fromLngLat
    const C = 40075016.68557849;
    const mercator = {MercatorCoordinate: {fromLngLat: (ll, h) => ({
        x: (ll[0] + 180) / 360,
        y: (180 - 180 / Math.PI * Math.log(Math.tan(Math.PI / 4 + ll[1] * Math.PI / 360))) / 360,
        z: (h || 0) / (C * Math.cos(ll[1] * Math.PI / 180))
    })}};
    const multiply = (a, b) => {                                 // column-major a * b
        const out = new Array(16).fill(0);
        for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) out[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k];
        return out;
    };
    // A camera over the route, tilted 60 degrees, looking north, as MapLibre's: perspective * view, in Mercator units
    function cameraMatrix() {
        const o = mercator.MercatorCoordinate.fromLngLat([LNG, LAT], 0), s = Math.pow(2, 22), tilt = -60 * Math.PI / 180;
        const toCamera = [s, 0, 0, 0, 0, -s, 0, 0, 0, 0, s, 0, -s * o.x, s * o.y, 0, 1];      // meters-ish, north up
        const pitch = [1, 0, 0, 0, 0, Math.cos(tilt), Math.sin(tilt), 0, 0, -Math.sin(tilt), Math.cos(tilt), 0, 0, 0, -600, 1];
        const f = 1 / Math.tan(Math.PI / 6), near = 1, far = 10000;
        const perspective = [f / 2, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, 2 * far * near / (near - far), 0];
        return multiply(perspective, multiply(pitch, toCamera));
    }
    function layerWithCamera() {
        const map = {on() {}, getLayer() { return null; }, addLayer() {}, addSource() {}, getSource() { return null; }, triggerRepaint() {}, queryTerrainElevation: () => 216,
                     getCanvas: () => ({clientWidth: 800, clientHeight: 400})};
        const r3d = R.createRoute3d({maplibregl: mercator, map, id: "mp-route-3d"});
        r3d.layer.render(null, {defaultProjectionData: {mainMatrix: cameraMatrix()}});
        return r3d;
    }
    const close = (a, b) => { expect(Math.abs(a[0] - b[0])).toBeLessThan(1e-7); expect(Math.abs(a[1] - b[1])).toBeLessThan(1e-7); };

    it("inverts the camera's matrix", () => {
        const m = cameraMatrix(), product = multiply(m, R.invert(m));
        product.forEach((v, i) => expect(v).toBeCloseTo(i % 5 === 0 ? 1 : 0, 6));
        expect(R.invert(new Array(16).fill(0))).toBeNull();
    });

    it("finds the position on the screen at a height above sea level: the way back from project", () => {
        const r3d = layerWithCamera();
        [[LNG, LAT, 300], [LNG + 0.0005, LAT + 0.0004, 256], [LNG - 0.0003, LAT + 0.001, 216]].forEach(p => {
            const seen = r3d.project(p[0], p[1], p[2]);
            close(r3d.unproject(seen.x, seen.y, () => p[2], [LNG, LAT]), p);
        });
    });

    it("finds it at heights that follow the surface, from the height where the last round landed", () => {
        const r3d = layerWithCamera();
        const heightAt = lng => (lng > LNG + 0.0002 ? 280 : 250);          // a step in the surface, 30 m up from it
        const p = [LNG + 0.0004, LAT + 0.0005];
        const seen = r3d.project(p[0], p[1], 280);
        close(r3d.unproject(seen.x, seen.y, heightAt, [LNG, LAT]), p);
    });

    it("finds nothing above the horizon, before the first frame, or where the height is unknown", () => {
        const r3d = layerWithCamera();
        expect(r3d.unproject(400, -2000, () => 216, [LNG, LAT])).toBeNull();
        expect(r3d.unproject(400, 300, () => null, [LNG, LAT])).toBeNull();
        const map = {on() {}, getLayer() { return null; }, addLayer() {}, addSource() {}, getCanvas: () => ({clientWidth: 800, clientHeight: 400})};
        expect(R.createRoute3d({maplibregl: mercator, map, id: "x"}).unproject(400, 300, () => 216, [LNG, LAT])).toBeNull();
    });

    it("keeps the point where it was grabbed, under the pointer, at its height", () => {
        const r3d = layerWithCamera();
        const at = [LNG, LAT + 0.0003, 260];
        const seen = r3d.project(at[0], at[1], at[2]);
        const move = R.airDrag(r3d, at, {x: seen.x + 3, y: seen.y - 2}, () => 260);   // grabbed off its centre
        const to = [LNG + 0.0006, LAT + 0.0007];
        const there = r3d.project(to[0], to[1], 260);
        const moved = move({x: there.x + 3, y: there.y - 2});
        close(moved, to);
        expect(moved[2]).toBe(260);
        expect(move({x: 400, y: -2000})).toBeNull();
    });

    it("is not started for a point off the screen", () => {
        const r3d = {project: () => null, unproject: () => null};
        expect(R.airDrag(r3d, [LNG, LAT, 260], {x: 0, y: 0}, () => 260)).toBeNull();
    });
});

