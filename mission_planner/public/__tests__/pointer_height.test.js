const P = require('../pointer_height');

// A tile of 256 x 256 RGBA pixels, every one encoding `height` in Terrarium, except one pixel encoding `spot`
function tile(height, spot) {
    const rgba = new Uint8ClampedArray(256 * 256 * 4);
    const put = (i, h) => { const v = h + 32768; rgba[i] = Math.floor(v / 256); rgba[i + 1] = Math.floor(v) % 256; rgba[i + 2] = Math.floor((v - Math.floor(v)) * 256); rgba[i + 3] = 255; };
    for (let i = 0; i < rgba.length; i += 4) put(i, height);
    if (spot) put((spot.py * 256 + spot.px) * 4, spot.height);
    return rgba;
}

const LNG = -79.528168, LAT = 41.4898;
const flush = () => new Promise(r => setTimeout(r, 0));

describe("tiles and pixels", () => {
    it("finds the tile and the pixel a point lies in", () => {
        const t = P.tileAt(LNG, LAT, 15);
        expect([t.x, t.y]).toEqual([9145, 12226]);
        expect(t.px).toBeGreaterThanOrEqual(0);
        expect(t.px).toBeLessThan(256);
        const fine = P.tileAt(LNG, LAT, 18);
        expect([fine.x >> 3, fine.y >> 3]).toEqual([9145, 12226]);
        const edge = P.tileAt(180, -90, 2);                                                // the edges stay in the tile set
        expect([edge.x, edge.y, edge.px]).toEqual([3, 3, 255]);
        expect(edge.py).toBeGreaterThan(250);
    });

    it("decodes a Terrarium pixel's height", () => {
        expect(P.decodePixel(tile(214.5), 10, 20)).toBeCloseTo(214.5, 2);
        expect(P.decodePixel(tile(-12.25), 0, 0)).toBeCloseTo(-12.25, 2);
    });
});

describe("heights in the editor's units", () => {
    it("are meters to a tenth, or whole feet", () => {
        expect(P.formatHeight(214.46, "metric")).toBe("214.5 m");
        expect(P.formatHeight(214.46, "imperial")).toBe("704 ft");
    });
});

describe("height reader", () => {
    const make = (built, tiles) => {
        const loads = [];
        const reader = P.createHeightReader({
            load: (z, x, y) => { loads.push([z, x, y]); const t = tiles(z, x, y); return t instanceof Error ? Promise.reject(t) : Promise.resolve({data: t}); },
            isBuilt: () => built,
            decode: data => Promise.resolve(data)
        });
        return {reader, loads};
    };

    it("reads the lidar surface's zoom-18 tile where the unit is built", async () => {
        const t = P.tileAt(LNG, LAT, 18);
        const {reader, loads} = make(true, () => tile(214, {px: t.px, py: t.py, height: 240.5}));
        expect(await reader.heightAt(LNG, LAT)).toEqual({height: 240.5, source: "lidar"});
        expect(loads).toEqual([[18, t.x, t.y]]);
    });

    it("reads AWS's zoom-15 tile elsewhere", async () => {
        const {reader, loads} = make(false, () => tile(213.25));
        expect(await reader.heightAt(LNG, LAT)).toEqual({height: 213.25, source: "terrain"});
        expect(loads[0][0]).toBe(15);
    });

    it("loads a tile once for every point in it", async () => {
        const {reader, loads} = make(false, () => tile(200));
        await reader.heightAt(LNG, LAT);
        await reader.heightAt(LNG + 0.0001, LAT);
        expect(loads.length).toBe(1);
    });

    it("reads a tile again once cleared (the lidar's tiles were made again)", async () => {
        let height = 200;
        const {reader, loads} = make(false, () => tile(height));
        await reader.heightAt(LNG, LAT);
        height = 205;
        reader.clear();
        expect(await reader.heightAt(LNG, LAT)).toEqual({height: 205, source: "terrain"});
        expect(loads.length).toBe(2);
    });

    it("answers nothing for a tile that does not load, and tries it again next time", async () => {
        let fail = true;
        const {reader, loads} = make(false, () => fail ? new Error("offline") : tile(200));
        expect(await reader.heightAt(LNG, LAT)).toBeNull();
        await flush();
        fail = false;
        expect(await reader.heightAt(LNG, LAT)).toEqual({height: 200, source: "terrain"});
        expect(loads.length).toBe(2);
    });
});

describe("many heights at once (a route's)", () => {
    const make = (built, tiles) => {
        const loads = [];
        let open = 0, most = 0;
        const reader = P.createHeightReader({
            load: (z, x, y) => {
                loads.push([z, x, y]); open++; most = Math.max(most, open);
                const t = tiles(z, x, y);
                return new Promise((resolve, reject) => setTimeout(() => { open--; t instanceof Error ? reject(t) : resolve({data: t}); }, 0));
            },
            isBuilt: () => built,
            decode: data => Promise.resolve(data)
        });
        return {reader, loads, most: () => most};
    };
    // A point in each of n zoom-15 tiles eastward, two points in each
    const spread = n => [].concat(...Array.from({length: n}, (_, i) => [[LNG + i * 0.011, LAT], [LNG + i * 0.011 + 0.0001, LAT]]));

    it("reads each tile once, a few at a time, the heights in the points' order", async () => {
        const {reader, loads, most} = make(false, (z, x) => tile(100 + x % 10));
        const points = spread(10);
        const heights = await reader.heightsAt(points);
        expect(loads.length).toBe(10);
        expect(new Set(loads.map(l => l.join("/"))).size).toBe(10);
        expect(most()).toBeLessThanOrEqual(4);
        points.forEach((p, i) => expect(heights[i]).toBeCloseTo(100 + P.tileAt(p[0], p[1], 15).x % 10, 2));
    });

    it("reads the lidar's tiles where built, at the pixel of each point", async () => {
        const t = P.tileAt(LNG, LAT, 18);
        const {reader, loads} = make(true, () => tile(214, {px: t.px, py: t.py, height: 240.5}));
        expect(await reader.heightsAt([[LNG, LAT]])).toEqual([240.5]);
        expect(loads).toEqual([[18, t.x, t.y]]);
    });

    it("answers null for the points of a tile that does not load, and the others' heights", async () => {
        const bad = P.tileAt(LNG, LAT, 15).x;
        const {reader} = make(false, (z, x) => x === bad ? new Error("offline") : tile(150));
        expect(await reader.heightsAt(spread(2))).toEqual([null, null, 150, 150]);
        expect(await reader.heightsAt([])).toEqual([]);
    });
});

describe("pointer tooltip", () => {
    let host, units;
    const make = heightAt => { host = document.createElement("div"); units = "metric"; return P.createPointerTooltip(document, host, {heightAt, units: () => units}); };

    it("shows the height above sea level beside the pointer, in one short line", async () => {
        const tip = make(() => Promise.resolve({height: 240.46, source: "lidar"}));
        expect(tip.element.hidden).toBe(true);
        await tip.move({x: 100, y: 50}, {lng: LNG, lat: LAT});
        expect(tip.element.hidden).toBe(false);
        expect(tip.element.style.left).toBe("114px");
        expect(tip.element.style.top).toBe("64px");
        expect(tip.element.textContent).toBe("240.5 m ASL");
        expect(tip.element.getAttribute("data-source")).toBe("lidar");
    });

    it("adds the route's height above the surface over the route's line, read where the route is", async () => {
        const asked = [];
        host = document.createElement("div");
        units = "metric";
        let route = {lng: LNG + 0.001, lat: LAT, height: 278.5};
        const tip = P.createPointerTooltip(document, host, {
            heightAt: (lng, lat) => { asked.push([lng, lat]); return Promise.resolve({height: 240.46, source: "lidar"}); },
            units: () => units, routeAt: () => route
        });
        await tip.move({x: 100, y: 50}, {lng: LNG, lat: LAT});
        expect(tip.element.textContent).toBe("240.5 m ASL, route 38.0 m above");
        expect(asked.pop()).toEqual([LNG + 0.001, LAT]);
        expect(tip.element.classList.contains("mp-route-below")).toBe(false);
        route = {lng: LNG, lat: LAT, height: 234.4};
        await tip.move({x: 100, y: 50}, {lng: LNG, lat: LAT});
        expect(tip.element.textContent).toBe("240.5 m ASL, route 6.1 m below");
        expect(tip.element.classList.contains("mp-route-below")).toBe(true);
        route = null;
        await tip.move({x: 100, y: 50}, {lng: LNG, lat: LAT});
        expect(tip.element.textContent).toBe("240.5 m ASL");
        expect(tip.element.classList.contains("mp-route-below")).toBe(false);
    });

    it("gives the route's height in feet too", () => {
        expect(P.tooltipText(240.46, "imperial", {height: 278.5})).toBe("789 ft ASL, route 125 ft above");
    });

    it("follows the editor's units", async () => {
        const tip = make(() => Promise.resolve({height: 213.25, source: "terrain"}));
        units = "imperial";
        await tip.move({x: 0, y: 0}, {lng: LNG, lat: LAT});
        expect(tip.element.textContent).toBe("700 ft ASL");
        expect(tip.element.getAttribute("data-source")).toBe("terrain");
    });

    it("hides where there is no height, and when the pointer leaves the map", async () => {
        let answer = {height: 200, source: "terrain"};
        const tip = make(() => Promise.resolve(answer));
        await tip.move({x: 0, y: 0}, {lng: LNG, lat: LAT});
        tip.hide();
        expect(tip.element.hidden).toBe(true);
        answer = null;
        await tip.move({x: 0, y: 0}, {lng: LNG, lat: LAT});
        expect(tip.element.hidden).toBe(true);
    });

    it("shows only the latest point's height, and nothing after leaving", async () => {
        let resolveFirst;
        const answers = [new Promise(r => { resolveFirst = r; }), Promise.resolve({height: 222, source: "terrain"})];
        const tip = make(() => answers.shift());
        const first = tip.move({x: 0, y: 0}, {lng: LNG, lat: LAT});
        await tip.move({x: 5, y: 5}, {lng: LNG, lat: LAT});
        resolveFirst({height: 111, source: "terrain"});
        await first;
        expect(tip.element.textContent).toBe("222.0 m ASL");
        const late = make(() => new Promise(r => setTimeout(() => r({height: 5, source: "terrain"}), 0)));
        const pending = late.move({x: 0, y: 0}, {lng: LNG, lat: LAT});
        late.hide();
        await pending;
        expect(late.element.hidden).toBe(true);
    });
});

describe("the highest surface near each piece of a route (collisions with a margin)", () => {
    const make = (built, tiles) => {
        const loads = [];
        const reader = P.createHeightReader({
            load: (z, x, y) => { loads.push([z, x, y]); const t = tiles(z, x, y); return t instanceof Error ? Promise.reject(t) : Promise.resolve({data: t}); },
            isBuilt: () => built,
            decode: data => Promise.resolve(data)
        });
        return {reader, loads};
    };
    // A point east of (LNG, LAT) by dx meters and north by dy meters
    const at = (dx, dy) => [LNG + dx / (111320 * Math.cos(LAT * Math.PI / 180)), LAT + dy / 110540];
    // The zoom-18 pixel (in its tile) of a point, and a tile with a 40 m spike there
    const spikeAt = p => { const t = P.tileAt(p[0], p[1], 18); return {t, tile: (z, x, y) => tile(214, x === t.x && y === t.y ? {px: t.px, py: t.py, height: 254} : null)}; };
    const piece = (a, b) => [a[0], a[1], b[0], b[1]];

    it("is the highest pixel within the margin of the piece, along its whole length", async () => {
        const {tile: tiles} = spikeAt(at(10, 1.5));                // beside the middle of a 20 m piece, 1.5 m off
        const {reader} = make(true, tiles);
        const [near, far] = await Promise.all([reader.bandMaxes([piece(at(0, 0), at(20, 0))], 2), reader.bandMaxes([piece(at(0, 0), at(20, 0))], 0.5)]);
        expect(near[0]).toBeCloseTo(254, 1);
        expect(far[0]).toBeCloseTo(214, 1);
    });

    it("with no margin, is the highest pixel the piece crosses", async () => {
        const {tile: tiles} = spikeAt(at(10, 0));
        const {reader} = make(true, tiles);
        expect((await reader.bandMaxes([piece(at(0, 0), at(20, 0))], 0))[0]).toBeCloseTo(254, 1);
    });

    it("reads AWS's zoom-15 tile where the lidar is not built", async () => {
        const {reader, loads} = make(false, () => tile(213.25));
        expect((await reader.bandMaxes([piece(at(0, 0), at(20, 0))], 2))[0]).toBeCloseTo(213.25, 2);
        expect(loads.every(l => l[0] === 15)).toBe(true);
    });

    it("reads each tile once for all the pieces in it", async () => {
        const {reader, loads} = make(true, () => tile(214));
        const pieces = [0, 1, 2, 3].map(i => piece(at(i * 5, 0), at(i * 5 + 5, 0)));
        await reader.bandMaxes(pieces, 2);
        expect(new Set(loads.map(l => l.join("/"))).size).toBe(loads.length);
    });

    it("answers nothing for a piece whose tiles did not load", async () => {
        const {reader} = make(true, () => new Error("offline"));
        expect(await reader.bandMaxes([piece(at(0, 0), at(20, 0))], 2)).toEqual([null]);
    });
});

// A PNG of the given RGB or RGBA pixels (256 x 256), each row filtered with the next of PNG's five filters, as an encoder may
function png(rgba, channels, header) {
    const zlib = require('zlib'), W = 256, stride = W * channels, rows = [];
    const raw = y => { const r = Buffer.alloc(stride); for (let x = 0; x < W; x++) for (let c = 0; c < channels; c++) r[x * channels + c] = rgba[(y * W + x) * 4 + c]; return r; };
    const paeth = (a, b, c) => { const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c); return pa <= pb && pa <= pc ? a : pb <= pc ? b : c; };
    let prev = Buffer.alloc(stride);
    for (let y = 0; y < W; y++) {
        const cur = raw(y), f = y % 5, out = Buffer.alloc(stride + 1);
        out[0] = f;
        for (let x = 0; x < stride; x++) {
            const a = x >= channels ? cur[x - channels] : 0, b = prev[x], c = x >= channels ? prev[x - channels] : 0;
            const pred = [0, a, b, (a + b) >> 1, paeth(a, b, c)][f];
            out[x + 1] = (cur[x] - pred) & 255;
        }
        rows.push(out);
        prev = cur;
    }
    const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); return Buffer.concat([len, Buffer.from(type), data, Buffer.alloc(4)]); };
    const ihdr = Buffer.alloc(13);
    ihdr.writeUInt32BE(W, 0); ihdr.writeUInt32BE(W, 4);
    ihdr[8] = (header && header.depth) || 8; ihdr[9] = (header && header.color) || (channels === 4 ? 6 : 2); ihdr[12] = (header && header.interlace) || 0;
    const z = zlib.deflateSync(Buffer.concat(rows));
    const bytes = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', z.subarray(0, 1000)), chunk('IDAT', z.subarray(1000)), chunk('IEND', Buffer.alloc(0))]);
    return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length);
}
const inflate = bytes => Promise.resolve(new Uint8Array(require('zlib').inflateSync(Buffer.from(bytes))));
// A tile with heights that change from pixel to pixel, so that every filter has something to predict
function varied() {
    const rgba = tile(200);
    for (let i = 0; i < 256 * 256; i++) { const v = 200 + (i * 37 % 5000) / 100 + 32768; rgba[i * 4] = Math.floor(v / 256); rgba[i * 4 + 1] = Math.floor(v) % 256; rgba[i * 4 + 2] = (i * 13) % 256; }
    return rgba;
}

describe("tiles decoded without a canvas", () => {
    it("give back every pixel of an RGB or an RGBA PNG, whatever the rows' filters", async () => {
        const rgba = varied();
        expect(await P.decodePng(png(rgba, 3), inflate)).toEqual(rgba);
        const alpha = rgba.slice();
        for (let i = 3; i < alpha.length; i += 4) alpha[i] = i % 251;
        expect(await P.decodePng(png(alpha, 4), inflate)).toEqual(alpha);
    });

    it("refuse what is not an 8-bit RGB or RGBA PNG, not interlaced", async () => {
        const rgba = varied();
        await expect(P.decodePng(png(rgba, 3, {interlace: 1}), inflate)).rejects.toThrow();
        await expect(P.decodePng(png(rgba, 3, {depth: 16}), inflate)).rejects.toThrow();
        await expect(P.decodePng(png(rgba, 3, {color: 3}), inflate)).rejects.toThrow();
        await expect(P.decodePng(new ArrayBuffer(40), inflate)).rejects.toThrow();
    });

    it("keep their heights in a browser whose canvas alters a few pixels (Brave's fingerprinting protection)", async () => {
        const rgba = varied(), saved = {};
        ['createImageBitmap', 'OffscreenCanvas', 'DecompressionStream'].forEach(k => { saved[k] = window[k]; });
        window.createImageBitmap = () => Promise.resolve({close() {}});
        window.OffscreenCanvas = class { getContext() { return {drawImage() {}, getImageData() {
            const data = rgba.slice();
            for (let i = 0; i < 400; i += 4) data[i * 97] += 1;                      // the red of a few pixels one higher: 256 m
            return {data};
        }}; } };
        window.DecompressionStream = require('stream/web').DecompressionStream;
        try {
            const got = await P.decodeInBrowser(png(rgba, 3));
            let worst = 0;
            for (let px = 0; px < 256; px++) for (let py = 0; py < 256; py++) worst = Math.max(worst, Math.abs(P.decodePixel(got, px, py) - P.decodePixel(rgba, px, py)));
            expect(worst).toBe(0);
        } finally {
            Object.keys(saved).forEach(k => { window[k] = saved[k]; });
        }
    });
});

describe("a tile that comes with its pixels", () => {
    it("is read as it is, not decoded again", async () => {
        const t = P.tileAt(LNG, LAT, 18);
        const rgba = tile(214, {px: t.px, py: t.py, height: 233.5});
        const decode = jest.fn();
        const reader = P.createHeightReader({load: () => Promise.resolve({data: {image: true}, rgba}), isBuilt: () => true, decode});
        expect(await reader.heightAt(LNG, LAT)).toEqual({height: 233.5, source: "lidar"});
        expect(decode).not.toHaveBeenCalled();
    });
});
