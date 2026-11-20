/* global Uint8Array, Uint8ClampedArray, DataView */
// The height under the pointer on the editors' map: a small tooltip beside the pointer, in 2D and 3D, with the height
// above sea level ("216.2 m ASL") of the surface right under it (over the route's line, also the route's height
// above it there: "216.2 m ASL, route 38.0 m above"), read from the same Terrarium tiles the 3D view raises the ground
// with (lidar_surface.js): the lidar surface's zoom-18 tile where its unit is built (the top of trees and roofs),
// else AWS's zoom-15 tile (the shape of the ground). Plain ES5, the browser's parts passed in, so that it can be
// tested.
(function (root) {
    var TILE = 256, UNIT_ZOOM = 15, LIDAR_ZOOM = 18, CACHE = 24, AT_ONCE = 4, M_TO_FT = 3.28084;

    // The tile of zoom z a point lies in, and the pixel in it: {x, y, px, py}
    function tileAt(lng, lat, z) {
        var n = Math.pow(2, z), s = Math.sin(Math.max(Math.min(lat, 85), -85) * Math.PI / 180);
        var fx = (lng + 180) / 360 * n, fy = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n;
        var x = Math.min(Math.floor(fx), n - 1), y = Math.min(Math.floor(fy), n - 1);
        return {x: x, y: y, px: Math.min(Math.floor((fx - x) * TILE), TILE - 1), py: Math.min(Math.floor((fy - y) * TILE), TILE - 1)};
    }

    // A point's position in pixels of the whole world at zoom z, as tileAt reckons it (not rounded)
    function worldPixel(lng, lat, z) {
        var n = Math.pow(2, z) * TILE, s = Math.sin(Math.max(Math.min(lat, 85), -85) * Math.PI / 180);
        return [(lng + 180) / 360 * n, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n];
    }

    // The distance from (x, y) to the segment from a to b, in the same units
    function toSegment(x, y, a, b) {
        var dx = b[0] - a[0], dy = b[1] - a[1], len = dx * dx + dy * dy;
        var t = len ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / len)) : 0;
        var ex = a[0] + t * dx - x, ey = a[1] + t * dy - y;
        return Math.sqrt(ex * ex + ey * ey);
    }

    // A Terrarium pixel's height (meters): red * 256 + green + blue / 256 - 32768
    function decodePixel(rgba, px, py) {
        var i = (py * TILE + px) * 4;
        return rgba[i] * 256 + rgba[i + 1] + rgba[i + 2] / 256 - 32768;
    }

    function formatHeight(meters, system) {
        return system === "imperial" ? Math.round(meters * M_TO_FT) + " ft" : meters.toFixed(1) + " m";
    }

    // A PNG's bytes (8-bit RGB or RGBA, not interlaced, 256 x 256: the lidar surface's tiles and AWS's) as RGBA pixels,
    // decoded here rather than through a canvas: a browser may alter what a canvas gives back (Brave's fingerprinting
    // protection changes a few pixels by one), and a red one higher is 256 m higher in Terrarium, which the collision
    // check, taking the highest pixel along the route, then finds. inflate(bytes) -> Promise<Uint8Array> (zlib).
    function decodePng(buffer, inflate) {
        var b = new Uint8Array(buffer), view = new DataView(b.buffer, b.byteOffset, b.byteLength);
        var signature = [137, 80, 78, 71, 13, 10, 26, 10], channels = 0, width = 0, height = 0, parts = [], size = 0, at = 8;
        for (var s = 0; s < 8; s++) if (b[s] !== signature[s]) return Promise.reject(new Error("Not a PNG"));
        while (at + 8 <= b.length) {
            var length = view.getUint32(at), data = at + 8;
            var type = String.fromCharCode(b[at + 4], b[at + 5], b[at + 6], b[at + 7]);
            if (data + length > b.length) return Promise.reject(new Error("PNG cut short"));
            if (type === "IHDR") {
                width = view.getUint32(data);
                height = view.getUint32(data + 4);
                channels = b[data + 9] === 2 ? 3 : b[data + 9] === 6 ? 4 : 0;
                if (b[data + 8] !== 8 || b[data + 12] !== 0) channels = 0;
                if (!channels) return Promise.reject(new Error("A PNG format not read here"));
            } else if (type === "IDAT") {
                parts.push(b.subarray(data, data + length));
                size += length;
            } else if (type === "IEND") {
                break;
            }
            at = data + length + 4;
        }
        if (!channels || width !== TILE || height !== TILE || !size) return Promise.reject(new Error("Not a tile"));
        var packed = new Uint8Array(size), offset = 0;
        parts.forEach(function (part) { packed.set(part, offset); offset += part.length; });
        return inflate(packed).then(function (raw) { return unfilter(raw, channels); });
    }

    // The PNG's rows, each after its filter byte, as RGBA pixels
    function unfilter(raw, channels) {
        var stride = TILE * channels, out = new Uint8ClampedArray(TILE * TILE * 4);
        var prev = new Uint8Array(stride), cur = new Uint8Array(stride);
        if (raw.length < TILE * (stride + 1)) throw new Error("PNG cut short");
        for (var y = 0; y < TILE; y++) {
            var start = y * (stride + 1), filter = raw[start];
            for (var x = 0; x < stride; x++) {
                var a = x >= channels ? cur[x - channels] : 0, up = prev[x], c = x >= channels ? prev[x - channels] : 0, v = raw[start + 1 + x];
                if (filter === 1) v += a;
                else if (filter === 2) v += up;
                else if (filter === 3) v += (a + up) >> 1;
                else if (filter === 4) {
                    var p = a + up - c, pa = Math.abs(p - a), pb = Math.abs(p - up), pc = Math.abs(p - c);
                    v += pa <= pb && pa <= pc ? a : pb <= pc ? up : c;
                } else if (filter !== 0) throw new Error("A PNG filter not read here");
                cur[x] = v & 255;
            }
            for (var i = 0; i < TILE; i++) {
                var o = (y * TILE + i) * 4, q = i * channels;
                out[o] = cur[q]; out[o + 1] = cur[q + 1]; out[o + 2] = cur[q + 2]; out[o + 3] = channels === 4 ? cur[q + 3] : 255;
            }
            var swap = prev; prev = cur; cur = swap;
        }
        return out;
    }

    // zlib bytes inflated with the browser's DecompressionStream
    function inflateInBrowser(bytes) {
        var stream = new root.DecompressionStream("deflate"), writer = stream.writable.getWriter(), reader = stream.readable.getReader();
        var chunks = [], total = 0;
        writer.write(bytes).catch(function () { /* the reader says so */ });
        writer.close().catch(function () { /* the reader says so */ });
        function next() {
            return reader.read().then(function (r) {
                if (!r.done) { chunks.push(r.value); total += r.value.length; return next(); }
                var out = new Uint8Array(total), offset = 0;
                chunks.forEach(function (chunk) { out.set(chunk, offset); offset += chunk.length; });
                return out;
            });
        }
        return next();
    }

    // A tile's PNG bytes, or its image (a tile cut from AWS's zoom 15: lidar_surface.js), as RGBA pixels (256 x 256 x 4):
    // the bytes decoded by decodePng, through a canvas only where the browser has no DecompressionStream or the PNG is
    // of another kind, and for an image. The browser's version; the tests pass their own.
    function decodeInBrowser(buffer) {
        var isImage = typeof root.ImageBitmap === "function" && buffer instanceof root.ImageBitmap;
        if (!isImage && typeof root.DecompressionStream === "function") {
            return decodePng(buffer, inflateInBrowser).catch(function () { return decodeOnCanvas(buffer, false); });
        }
        return decodeOnCanvas(buffer, isImage);
    }

    function decodeOnCanvas(buffer, isImage) {
        var image = isImage ? Promise.resolve(buffer)
            : root.createImageBitmap(new root.Blob([buffer], {type: "image/png"}), {colorSpaceConversion: "none", premultiplyAlpha: "none"});
        return image.then(function (image) {
            var canvas = typeof root.OffscreenCanvas === "function" ? new root.OffscreenCanvas(TILE, TILE) : root.document.createElement("canvas");
            canvas.width = canvas.height = TILE;
            var ctx = canvas.getContext("2d", {willReadFrequently: true});
            ctx.drawImage(image, 0, 0);
            if (image.close) image.close();
            return ctx.getImageData(0, 0, TILE, TILE).data;
        });
    }

    // opts: {load(z, x, y) -> Promise<{data: ArrayBuffer}>, isBuilt(unitX, unitY) -> bool, decode(buffer) -> Promise<rgba>}
    // Returns {heightAt(lng, lat) -> Promise<{height, source: "lidar" | "terrain"} | null>,
    //          heightsAt(points [[lng, lat], ...]) -> Promise<[meters or null, ...]>, bandMaxes(...),
    //          clear() (the tiles read so far forgotten: the lidar's were made again)}
    function createHeightReader(opts) {
        var decode = opts.decode || decodeInBrowser;
        var cache = {}, order = [];

        function pixels(z, x, y) {
            var key = z + "/" + x + "/" + y;
            if (!cache[key]) {
                cache[key] = opts.load(z, x, y).then(function (r) { return decode(r.data); });
                cache[key].catch(function () { delete cache[key]; });          // a failed tile is tried again later
                order.push(key);
                if (order.length > CACHE) delete cache[order.shift()];
            }
            return cache[key];
        }

        // The tile a point is read from: the lidar's where its unit is built, else the terrain's
        function sourceOf(lng, lat) {
            var unit = tileAt(lng, lat, UNIT_ZOOM);
            var lidar = !!opts.isBuilt(unit.x, unit.y);
            var t = lidar ? tileAt(lng, lat, LIDAR_ZOOM) : unit;
            t.z = lidar ? LIDAR_ZOOM : UNIT_ZOOM;
            t.lidar = lidar;
            return t;
        }

        function heightAt(lng, lat) {
            var t = sourceOf(lng, lat);
            return pixels(t.z, t.x, t.y)
                .then(function (rgba) { return {height: decodePixel(rgba, t.px, t.py), source: t.lidar ? "lidar" : "terrain"}; })
                .catch(function () { return null; });
        }

        // Many points at once (a route's): grouped by tile, AT_ONCE tiles read at a time, so that a large route does
        // not hold all its tiles at once; null for a point whose tile did not load
        function heightsAt(points) {
            var out = points.map(function () { return null; }), groups = {}, keys = [];
            points.forEach(function (p, i) {
                var t = sourceOf(p[0], p[1]), key = t.z + "/" + t.x + "/" + t.y;
                if (!groups[key]) { groups[key] = {t: t, items: []}; keys.push(key); }
                groups[key].items.push({i: i, px: t.px, py: t.py});
            });
            var next = 0;
            function worker() {
                if (next >= keys.length) return Promise.resolve();
                var g = groups[keys[next++]];
                return pixels(g.t.z, g.t.x, g.t.y).then(function (rgba) {
                    g.items.forEach(function (it) { out[it.i] = decodePixel(rgba, it.px, it.py); });
                }, function () { /* its points stay null */ }).then(worker);
            }
            var workers = [];
            for (var w = 0; w < Math.min(AT_ONCE, keys.length); w++) workers.push(worker());
            return Promise.all(workers).then(function () { return out; });
        }

        // The highest surface within `radius` meters of each piece of a route ([lngA, latA, lngB, latB]), along its
        // whole length (route_3d.js's collisions with a margin): the lidar's zoom-18 pixels where the unit is built, else
        // AWS's zoom-15 pixels; a pixel counts when its centre is within the radius and half its diagonal of the piece.
        // Read tile by tile, AT_ONCE at a time, each tile once for all its pieces; null for a piece none of whose
        // tiles loaded. Promise<[meters or null, ...]>
        function bandMaxes(segments, radius) {
            var out = segments.map(function () { return null; }), groups = {}, keys = [], pieces = [];
            var per = Math.pow(2, LIDAR_ZOOM - UNIT_ZOOM);              // zoom-18 tiles across a unit
            function add(z, x, y, i) {
                var key = z + "/" + x + "/" + y;
                if (!groups[key]) { groups[key] = {z: z, x: x, y: y, items: []}; keys.push(key); }
                groups[key].items.push(i);
            }
            segments.forEach(function (s, i) {
                var a = worldPixel(s[0], s[1], LIDAR_ZOOM), b = worldPixel(s[2], s[3], LIDAR_ZOOM);
                var mpp = 40075016.686 * Math.cos((s[1] + s[3]) / 2 * Math.PI / 180) / (TILE * Math.pow(2, LIDAR_ZOOM));
                var r = Math.max(radius, 0) / mpp;                       // the radius in zoom-18 pixels
                pieces.push({a: a, b: b, r: r});
                var x0 = Math.floor((Math.min(a[0], b[0]) - r - 1) / TILE), x1 = Math.floor((Math.max(a[0], b[0]) + r + 1) / TILE);
                var y0 = Math.floor((Math.min(a[1], b[1]) - r - 1) / TILE), y1 = Math.floor((Math.max(a[1], b[1]) + r + 1) / TILE);
                for (var ux = Math.floor(x0 / per); ux <= Math.floor(x1 / per); ux++) {
                    for (var uy = Math.floor(y0 / per); uy <= Math.floor(y1 / per); uy++) {
                        if (!opts.isBuilt(ux, uy)) { add(UNIT_ZOOM, ux, uy, i); continue; }
                        for (var tx = Math.max(x0, ux * per); tx <= Math.min(x1, ux * per + per - 1); tx++) {
                            for (var ty = Math.max(y0, uy * per); ty <= Math.min(y1, uy * per + per - 1); ty++) add(LIDAR_ZOOM, tx, ty, i);
                        }
                    }
                }
            });
            // The piece's highest pixel in one tile, in that tile's zoom (a zoom-15 pixel is 8 zoom-18 pixels across)
            function scan(g, rgba, i) {
                var f = Math.pow(2, LIDAR_ZOOM - g.z), p = pieces[i];
                var a = [p.a[0] / f, p.a[1] / f], b = [p.b[0] / f, p.b[1] / f], reach = p.r / f + Math.SQRT1_2;
                var ox = g.x * TILE, oy = g.y * TILE;
                var px0 = Math.max(0, Math.floor(Math.min(a[0], b[0]) - reach) - ox), px1 = Math.min(TILE - 1, Math.floor(Math.max(a[0], b[0]) + reach) - ox);
                var py0 = Math.max(0, Math.floor(Math.min(a[1], b[1]) - reach) - oy), py1 = Math.min(TILE - 1, Math.floor(Math.max(a[1], b[1]) + reach) - oy);
                for (var py = py0; py <= py1; py++) {
                    for (var px = px0; px <= px1; px++) {
                        if (toSegment(ox + px + 0.5, oy + py + 0.5, a, b) > reach) continue;
                        var h = decodePixel(rgba, px, py);
                        if (out[i] === null || h > out[i]) out[i] = h;
                    }
                }
            }
            var next = 0;
            function worker() {
                if (next >= keys.length) return Promise.resolve();
                var g = groups[keys[next++]];
                return pixels(g.z, g.x, g.y).then(function (rgba) {
                    g.items.forEach(function (i) { scan(g, rgba, i); });
                }, function () { /* its pieces keep what other tiles gave */ }).then(worker);
            }
            var workers = [];
            for (var w = 0; w < Math.min(AT_ONCE, keys.length); w++) workers.push(worker());
            return Promise.all(workers).then(function () { return out; });
        }

        function clear() { cache = {}; order = []; }

        return {heightAt: heightAt, heightsAt: heightsAt, bandMaxes: bandMaxes, clear: clear};
    }

    // The tooltip's text: the surface's height, and the route's height above it when the pointer is on the route
    function tooltipText(surface, system, route) {
        var text = formatHeight(surface, system) + " ASL";
        if (route && isFinite(route.height)) {
            var above = route.height - surface;
            text += ", route " + formatHeight(Math.abs(above), system) + (above < 0 ? " below" : " above");
        }
        return text;
    }

    // opts: {heightAt(lng, lat), units() -> "metric" | "imperial",
    //        routeAt(point) -> {lng, lat, height (meters above sea level)} | null: the route under the pointer, if any}
    // Returns {element, move(point {x, y}, lngLat {lng, lat}), hide()}
    function createPointerTooltip(doc, container, opts) {
        var tip = doc.createElement("div");
        tip.className = "mp-pointer-height";
        tip.hidden = true;
        container.appendChild(tip);
        var asked = 0;

        function hide() {
            asked++;                                                  // an answer still coming is dropped
            tip.hidden = true;
        }

        function move(point, lngLat) {
            var mine = ++asked;
            tip.style.left = (point.x + 14) + "px";
            tip.style.top = (point.y + 14) + "px";
            var route = opts.routeAt ? opts.routeAt(point) : null;
            var at = route || lngLat;
            return opts.heightAt(at.lng, at.lat).then(function (h) {
                if (mine !== asked) return;
                if (!h || !isFinite(h.height)) { tip.hidden = true; return; }
                tip.textContent = tooltipText(h.height, opts.units(), route);
                tip.classList.toggle("mp-route-below", !!(route && route.height < h.height));
                tip.setAttribute("data-source", h.source);           // "lidar" or "terrain": not shown, kept small
                tip.hidden = false;
            });
        }

        return {element: tip, move: move, hide: hide};
    }

    var api = {createHeightReader: createHeightReader, createPointerTooltip: createPointerTooltip, tileAt: tileAt,
               decodePixel: decodePixel, formatHeight: formatHeight, tooltipText: tooltipText, decodeInBrowser: decodeInBrowser,
               decodePng: decodePng};
    root.MissionPlannerPointerHeight = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
