/* global Float32Array */
// The route in the air, in the editors' 3D view: the path the aircraft flies drawn at its height, with thin lines down
// to the surface, so its clearance over the ground, trees and roofs can be seen; and the waypoint routes' height
// labels (each point's height above the surface under it, in 2D and 3D). Where the path goes into the surface, it is
// drawn red (seen through the surface), with LEAD meters of yellow before and after, and the stretches are counted;
// in 2D too, on the plan's lines (a GeoJSON layer), with the same count.
//
// The plan's "air" (missions/air.py) gives the path and its heights, measured from sea level, from the surface, or
// from the takeoff point's ground; the surface is the Phase 7 reader's (pointer_height.js: the lidar's 1 m tiles
// where built, else the terrain's), read at every point of the path, the same in 2D and 3D whatever the zoom; the 3D
// view's own surface (map.queryTerrainElevation) only for dragging a point in the air. MapLibre's line layers lie on the ground, so the
// path is drawn by a custom WebGL layer: wide lines made of quads turned to face the screen, and discs at the points,
// at positions relative to the route's first point (float32 is too coarse for whole-world coordinates).
// Plain ES5, the browser's parts passed in, so that it can be tested.
(function (root) {
    var STEP = 5;                   // meters: a path above the surface is cut into pieces this long, to follow it
    var MAX_POINTS = 20000;         // pieces at most, for the whole route
    var M_TO_FT = 3.28084;
    var LEAD = 10;                  // meters of yellow before and after a stretch inside the surface
    var LINE_WIDTH = 3, DROP_WIDTH = 1.5, DISC_RADIUS = 4;
    var NEAR_PX = 6;                // pixels: how close to the route's line the pointer is on it
    var COLORS = {path: [0.118, 0.533, 0.898, 1], drop: [1, 1, 1, 0.85], disc: [1, 1, 1, 1], ring: [0.118, 0.533, 0.898, 1],
                  near: [1, 0.835, 0, 1], inside: [0.898, 0.224, 0.208, 1]};
    var CLEAR = 0, NEAR = 1, INSIDE = 2;    // a segment's kind

    function meters(a, b) {
        var k = Math.cos((a[1] + b[1]) / 2 * Math.PI / 180);
        var dx = (b[0] - a[0]) * 111320 * k, dy = (b[1] - a[1]) * 110540;
        return Math.sqrt(dx * dx + dy * dy);
    }

    // The path's points with pieces of at most `step` meters between them (the height interpolated); `budget`
    // {left} caps the points added over every path
    function cut(path, step, budget) {
        var out = [];
        path.forEach(function (p, i) {
            if (i > 0) {
                var a = path[i - 1], n = Math.min(Math.ceil(meters(a, p) / step), Math.max(1, budget.left));
                for (var j = 1; j < n; j++) {
                    var f = j / n;
                    out.push([a[0] + (p[0] - a[0]) * f, a[1] + (p[1] - a[1]) * f, a[2] + (p[2] - a[2]) * f]);
                }
                budget.left -= Math.max(0, n - 1);
            }
            out.push(p.slice(0, 3));
        });
        return out;
    }

    function lerp(a, b, f) { return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]; }

    // The path in heights above sea level, cut into pieces of at most `step` meters (so that it follows the surface,
    // and is checked against it along its length), and the drop lines from their top to the surface:
    // {paths: [[[lng, lat, asl], ...]], points, drops: [[lng, lat, top, bottom], ...]}, or null when the surface is not known
    // where it is needed yet (its tiles still loading). surfaceAt(lng, lat) -> meters above sea level, or null.
    // takeoff: [lng, lat] of the takeoff point, or null (the path's first point then). points: the plan's own points
    // of each path, lifted alike (paths may have pieces added between them, to follow the surface).
    function resolveAir(air, surfaceAt, takeoff, step) {
        if (!air || !air.paths || !air.paths.length || !air.paths[0].length) return null;
        step = step || STEP;
        var base = function () { return 0; };
        var budget = {left: MAX_POINTS};
        var paths = air.paths.map(function (path) { return cut(path, step, budget); });
        if (air.reference === "takeoff") {
            var at = takeoff || air.paths[0][0];
            var ground = surfaceAt(at[0], at[1]);
            if (ground === null || !isFinite(ground)) return null;
            base = function () { return ground; };
        } else if (air.reference === "surface") {
            base = surfaceAt;
        }
        var missing = false;
        function lift(p) {
            var b = base(p[0], p[1]);
            if (b === null || !isFinite(b)) { missing = true; return null; }
            return [p[0], p[1], p[2] + b];
        }
        var out = paths.map(function (path) { return path.map(lift); });
        var points = air.paths.map(function (path) { return path.map(lift); });
        if (missing) return null;
        var drops = [];
        (air.drops || []).forEach(function (d) {
            var top = lift(d), bottom = surfaceAt(d[0], d[1]);
            if (top && bottom !== null && isFinite(bottom) && top[2] > bottom) drops.push([d[0], d[1], top[2], bottom]);
        });
        return {paths: out, points: points, drops: drops};
    }

    // Where the paths (heights above sea level) go into the surface: each path with the points added where it crosses
    // the surface and where the yellow before and after a stretch inside starts or ends, and each segment's kind
    // (INSIDE the surface, NEAR: within `lead` meters along the path of a stretch inside, else CLEAR); count: the
    // stretches inside, over every path. A point over a surface not loaded is taken as clear of it.
    // band: {margin (meters), maxes: [[the highest surface near each piece of each path, or null]]} (bandMaxes in
    // pointer_height.js): a piece is then inside where its lowest point is less than the margin above that surface,
    // and the path is kept as it is (the pieces are short, STEP). Without it, a piece is inside where the path is under
    // the surface read at its points, and the crossings are added.
    // {paths: [[[lng, lat, asl], ...]], kinds: [[kind of each segment]], count}
    function collide(paths, surfaceAt, lead, band) {
        lead = lead === undefined ? LEAD : lead;
        var count = 0;
        var out = paths.map(function (path, pathIndex) {
            var pts = [], hits = [];
            if (band) {
                var maxes = band.maxes[pathIndex] || [];
                pts = path.map(function (p) { return p.slice(0, 3); });
                for (var q = 1; q < pts.length; q++) {
                    var top = maxes[q - 1];
                    hits.push(typeof top === "number" && isFinite(top) && Math.min(pts[q - 1][2], pts[q][2]) - top < band.margin);
                }
            } else {
                var clearance = path.map(function (p) {
                    var s = surfaceAt(p[0], p[1]);
                    return s === null || !isFinite(s) ? null : p[2] - s;
                });
                // The points where the path crosses the surface added, with their clearance (0)
                var gaps = [];
                path.forEach(function (p, i) {
                    var a = clearance[i - 1], b = clearance[i];
                    if (i > 0 && a !== null && b !== null && (a < 0) !== (b < 0)) {
                        var f = a / (a - b);
                        if (f > 0 && f < 1) { pts.push(lerp(path[i - 1], p, f)); gaps.push(0); }
                    }
                    pts.push(p.slice(0, 3));
                    gaps.push(b);
                });
                for (var g = 1; g < pts.length; g++) hits.push(gaps[g - 1] !== null && gaps[g] !== null && gaps[g - 1] + gaps[g] < 0);
            }
            // The stretches inside, as distances along the path
            var at = [0], inside = [], open = null;
            for (var k = 1; k < pts.length; k++) {
                at.push(at[k - 1] + meters(pts[k - 1], pts[k]));
                var hit = hits[k - 1];
                if (hit && !open) { open = [at[k - 1], at[k]]; inside.push(open); }
                else if (hit) open[1] = at[k];
                else open = null;
            }
            count += inside.length;
            var total = at[at.length - 1], near = [];
            inside.forEach(function (r) { near.push([r[0] - lead, r[0]], [r[1], r[1] + lead]); });
            // The points added where the yellow starts or ends
            var cuts = [];
            near.forEach(function (r) { [r[0], r[1]].forEach(function (d) { if (d > 0 && d < total) cuts.push(d); }); });
            cuts.sort(function (x, y) { return x - y; });
            var final = [pts[0]], dist = [0], c = 0;
            for (var j = 1; j < pts.length; j++) {
                while (c < cuts.length && cuts[c] <= at[j - 1]) c++;
                while (c < cuts.length && cuts[c] < at[j]) {
                    final.push(lerp(pts[j - 1], pts[j], (cuts[c] - at[j - 1]) / (at[j] - at[j - 1])));
                    dist.push(cuts[c]);
                    c++;
                }
                final.push(pts[j]);
                dist.push(at[j]);
            }
            function within(list, d) { return list.some(function (r) { return d > r[0] && d < r[1]; }); }
            var kinds = [];
            for (var n = 1; n < final.length; n++) {
                var mid = (dist[n - 1] + dist[n]) / 2;
                kinds.push(within(inside, mid) ? INSIDE : within(near, mid) ? NEAR : CLEAR);
            }
            return {path: final, kinds: kinds};
        });
        return {paths: out.map(function (o) { return o.path; }), kinds: out.map(function (o) { return o.kinds; }), count: count};
    }

    // The points (as [lng, lat]) whose surface heights resolveAir and collide read for this plan, without duplicates:
    // every piece of every path, the takeoff point, the drop lines' feet. {points, index: "lng,lat" -> position}
    function pointsNeeded(air, takeoff) {
        var points = [], index = {};
        function record(lng, lat) {
            var key = lng + "," + lat;
            if (!(key in index)) { index[key] = points.length; points.push([lng, lat]); }
            return 0;
        }
        var dry = resolveAir(air, record, takeoff);         // the pieces are where they are whatever the surface
        if (dry) collide(dry.paths, record);
        return {points: points, index: index};
    }

    // The 2D map's stretches near and inside the surface (from collide): a GeoJSON line for each run of segments of
    // one kind, with its kind ("near" or "inside")
    function flatStretches(hit) {
        var features = [], names = {};
        names[NEAR] = "near";
        names[INSIDE] = "inside";
        (hit ? hit.paths : []).forEach(function (path, i) {
            var kinds = hit.kinds[i], run = null;
            for (var k = 0; k < kinds.length; k++) {
                var kind = kinds[k];
                if (kind === CLEAR) { run = null; continue; }
                if (!run || run.kind !== kind) {
                    run = {kind: kind, coordinates: [path[k].slice(0, 2)]};
                    features.push(run);
                }
                run.coordinates.push(path[k + 1].slice(0, 2));
            }
        });
        return {type: "FeatureCollection", features: features.map(function (r) {
            return {type: "Feature", properties: {kind: names[r.kind], order: r.kind}, geometry: {type: "LineString", coordinates: r.coordinates}};
        })};
    }

    // The route's point nearest `point` (pixels) on the screen, within `radius` pixels, interpolated on its segment:
    // {lng, lat, height (meters above sea level)}, or null. toScreen(lng, lat, meters) -> {x, y} or null.
    function nearest(paths, toScreen, point, radius) {
        var best = null, bestD = radius * radius;
        (paths || []).forEach(function (path) {
            var prev = null;
            path.forEach(function (p) {
                var s = toScreen(p[0], p[1], p[2]);
                var at = s && {p: p, x: s.x, y: s.y};
                if (at && prev) {
                    var dx = at.x - prev.x, dy = at.y - prev.y, len = dx * dx + dy * dy;
                    var f = len ? Math.max(0, Math.min(1, ((point.x - prev.x) * dx + (point.y - prev.y) * dy) / len)) : 0;
                    var ex = prev.x + dx * f - point.x, ey = prev.y + dy * f - point.y, d = ex * ex + ey * ey;
                    if (d <= bestD) { bestD = d; best = lerp(prev.p, at.p, f); }
                } else if (at && path.length === 1) {
                    var d1 = (at.x - point.x) * (at.x - point.x) + (at.y - point.y) * (at.y - point.y);
                    if (d1 <= bestD) { bestD = d1; best = p.slice(0, 3); }
                }
                prev = at;
            });
        });
        return best && {lng: best[0], lat: best[1], height: best[2]};
    }

    // The side panel's line about the collisions (2D and 3D): {text, hit}
    // margin: the route's collision margin in meters (0 or none: the surface itself); system: "metric" or "imperial"
    function collisionText(count, margin, system) {
        var places = count + (count === 1 ? " place" : " places") + ": red on the map.";
        if (margin > 0) {
            var said = system === "imperial" ? Math.round(margin * M_TO_FT) + " ft" : (Math.round(margin * 10) / 10) + " m";
            if (!count) return {text: "The route stays at least " + said + " above the surface.", hit: false};
            return {text: "The route comes within " + said + " of the surface in " + places, hit: true};
        }
        if (!count) return {text: "The route stays above the surface.", hit: false};
        return {text: "The route goes into the surface in " + places, hit: true};
    }

    // Each point's height above the surface right under it (waypoint routes' labels), meters, null where unknown.
    // heightAt(lng, lat) -> Promise<{height} | null> (pointer_height.js's reader).
    function labelHeights(air, heightAt, takeoff) {
        if (!air || !air.paths || !air.paths.length) return Promise.resolve([]);
        var points = air.paths[0];
        if (air.reference === "surface") return Promise.resolve(points.map(function (p) { return p[2]; }));
        function surface(p) { return heightAt(p[0], p[1]).then(function (h) { return h && isFinite(h.height) ? h.height : null; }); }
        var at = air.reference === "takeoff" ? (takeoff || points[0]) : null;
        return Promise.all([at ? surface(at) : Promise.resolve(0)].concat(points.map(surface))).then(function (found) {
            var ground = found[0];
            return points.map(function (p, i) {
                var under = found[i + 1];
                return ground === null || under === null ? null : p[2] + ground - under;
            });
        });
    }

    // A label's text and whether the point is below the surface: {text: "38 m" | "125 ft" | "-4 m", below}
    function formatLabel(h, system) {
        var v = system === "imperial" ? Math.round(h * M_TO_FT) : Math.round(h);
        if (v === 0) v = 0;         // no "-0"
        return {text: v + (system === "imperial" ? " ft" : " m"), below: h < 0};
    }

    // -- the WebGL layer --------------------------------------------------------------------------------------------

    // The vertices of the resolved route, relative to `origin` (the first point, in world coordinates):
    // {origin, lines: Float32Array, lineCount, inside, insideCount (the segments inside the surface again, drawn
    // through it), drops, dropCount, discs, discCount}. toWorld(lng, lat, meters) -> [x, y, z]. resolved.kinds (from
    // collide) colours the segments, all blue without it; the discs are at resolved.points (the plan's own points),
    // else at every point of the paths.
    // A line vertex: position (3), the other end (3), side (-1 or 1), end (0 at the segment's start, 1 at its end),
    // colour (4); a disc vertex: position (3), corner (2).
    function buildGeometry(resolved, toWorld, withDiscs) {
        var first = resolved.paths[0][0], origin = toWorld(first[0], first[1], first[2]);
        function rel(lng, lat, h) { var w = toWorld(lng, lat, h); return [w[0] - origin[0], w[1] - origin[1], w[2] - origin[2]]; }
        function segments(pairs) {
            var data = new Float32Array(pairs.length * 6 * 12), o = 0;
            pairs.forEach(function (pair) {
                var a = pair[0], b = pair[1];
                [[a, b, -1, 0], [a, b, 1, 0], [b, a, -1, 1], [a, b, 1, 0], [b, a, 1, 1], [b, a, -1, 1]].forEach(function (v) {
                    data.set(v[0], o); data.set(v[1], o + 3); data[o + 6] = v[2]; data[o + 7] = v[3]; data.set(pair[2], o + 8); o += 12;
                });
            });
            return data;
        }
        var linePairs = [], insidePairs = [], points = [];
        var colors = [COLORS.path, COLORS.near, COLORS.inside];
        resolved.paths.forEach(function (path, i) {
            var prev = null, kinds = resolved.kinds && resolved.kinds[i];
            path.forEach(function (p, j) {
                var r = rel(p[0], p[1], p[2]);
                if (prev) {
                    var kind = kinds ? kinds[j - 1] : CLEAR;
                    linePairs.push([prev, r, colors[kind]]);
                    if (kind === INSIDE) insidePairs.push([prev, r, colors[kind]]);
                }
                prev = r;
            });
        });
        (resolved.points || resolved.paths).forEach(function (path) {
            path.forEach(function (p) { points.push(rel(p[0], p[1], p[2])); });
        });
        var dropPairs = resolved.drops.map(function (d) { return [rel(d[0], d[1], d[2]), rel(d[0], d[1], d[3]), COLORS.drop]; });
        var discs = new Float32Array(withDiscs ? points.length * 6 * 5 : 0), o = 0;
        if (withDiscs) {
            points.forEach(function (p) {
                [[-1, -1], [1, -1], [1, 1], [-1, -1], [1, 1], [-1, 1]].forEach(function (c) {
                    discs.set(p, o); discs[o + 3] = c[0]; discs[o + 4] = c[1]; o += 5;
                });
            });
        }
        return {origin: origin, lines: segments(linePairs), lineCount: linePairs.length * 6, inside: segments(insidePairs),
                insideCount: insidePairs.length * 6, drops: segments(dropPairs),
                dropCount: dropPairs.length * 6, discs: discs, discCount: withDiscs ? points.length * 6 : 0};
    }

    // matrix (column-major 4x4) times the translation to `origin`: the matrix for positions relative to it, computed
    // in double precision
    function translated(m, origin) {
        var out = new Float32Array(16);
        for (var i = 0; i < 12; i++) out[i] = m[i];
        for (var r = 0; r < 4; r++) out[12 + r] = m[r] * origin[0] + m[4 + r] * origin[1] + m[8 + r] * origin[2] + m[12 + r];
        return out;
    }

    // The inverse of a 4x4 column-major matrix, or null when it has none
    function invert(m) {
        var a00 = m[0], a01 = m[1], a02 = m[2], a03 = m[3], a10 = m[4], a11 = m[5], a12 = m[6], a13 = m[7],
            a20 = m[8], a21 = m[9], a22 = m[10], a23 = m[11], a30 = m[12], a31 = m[13], a32 = m[14], a33 = m[15];
        var b00 = a00 * a11 - a01 * a10, b01 = a00 * a12 - a02 * a10, b02 = a00 * a13 - a03 * a10,
            b03 = a01 * a12 - a02 * a11, b04 = a01 * a13 - a03 * a11, b05 = a02 * a13 - a03 * a12,
            b06 = a20 * a31 - a21 * a30, b07 = a20 * a32 - a22 * a30, b08 = a20 * a33 - a23 * a30,
            b09 = a21 * a32 - a22 * a31, b10 = a21 * a33 - a23 * a31, b11 = a22 * a33 - a23 * a32;
        var det = b00 * b11 - b01 * b10 + b02 * b09 + b03 * b08 - b04 * b07 + b05 * b06;
        if (!det || !isFinite(det)) return null;
        det = 1 / det;
        return [(a11 * b11 - a12 * b10 + a13 * b09) * det, (a02 * b10 - a01 * b11 - a03 * b09) * det,
                (a31 * b05 - a32 * b04 + a33 * b03) * det, (a22 * b04 - a21 * b05 - a23 * b03) * det,
                (a12 * b08 - a10 * b11 - a13 * b07) * det, (a00 * b11 - a02 * b08 + a03 * b07) * det,
                (a32 * b02 - a30 * b05 - a33 * b01) * det, (a20 * b05 - a22 * b02 + a23 * b01) * det,
                (a10 * b10 - a11 * b08 + a13 * b06) * det, (a01 * b08 - a00 * b10 - a03 * b06) * det,
                (a30 * b04 - a31 * b02 + a33 * b00) * det, (a21 * b02 - a20 * b04 - a23 * b00) * det,
                (a11 * b07 - a10 * b09 - a12 * b06) * det, (a00 * b09 - a01 * b07 + a02 * b06) * det,
                (a31 * b01 - a30 * b03 - a32 * b00) * det, (a20 * b03 - a21 * b01 + a22 * b00) * det];
    }

    function apply(m, v) {
        var out = [0, 0, 0, 0];
        for (var r = 0; r < 4; r++) out[r] = m[r] * v[0] + m[4 + r] * v[1] + m[8 + r] * v[2] + m[12 + r] * v[3];
        return [out[0] / out[3], out[1] / out[3], out[2] / out[3]];
    }

    // Where the ray from the camera through a point of the screen (clip coordinates, -1 to 1) meets the level z of the
    // world, as [x, y]; null when it does not, in front of the camera (the pointer above the horizon)
    function rayAtLevel(inverse, ndcX, ndcY, z) {
        var near = apply(inverse, [ndcX, ndcY, -1, 1]), far = apply(inverse, [ndcX, ndcY, 1, 1]);
        var dz = far[2] - near[2];
        if (!dz || !isFinite(dz)) return null;
        var t = (z - near[2]) / dz;
        if (!(t >= 0) || !isFinite(t)) return null;
        return [near[0] + t * (far[0] - near[0]), near[1] + t * (far[1] - near[1])];
    }

    // Web Mercator (0 to 1) to longitude and latitude, as MapLibre's MercatorCoordinate.toLngLat
    function toLngLat(x, y) {
        return [x * 360 - 180, 360 / Math.PI * Math.atan(Math.exp((180 - y * 360) * Math.PI / 180)) - 90];
    }

    // Dragging a point in the air: the point follows the pointer so that it stays where it was grabbed, at the
    // heights heightAt(lng, lat) gives (meters above sea level). r3d: {project, unproject}; at: [lng, lat, meters], the
    // point when grabbed; grab: {x, y}, the pointer then. Returns move(pointer) -> [lng, lat, meters], or null (the
    // pointer above the horizon); null itself when the point is not on the screen.
    function airDrag(r3d, at, grab, heightAt) {
        var seen = r3d.project(at[0], at[1], at[2]);
        if (!seen) return null;
        var dx = grab.x - seen.x, dy = grab.y - seen.y, last = [at[0], at[1]];
        return function (pointer) {
            var ll = r3d.unproject(pointer.x - dx, pointer.y - dy, heightAt, last);
            if (!ll) return null;
            last = ll;
            return [ll[0], ll[1], heightAt(ll[0], ll[1])];
        };
    }

    var LINE_VS = "#version 300 es\n" +
        "uniform mat4 u_matrix; uniform vec2 u_viewport; uniform float u_width;\n" +
        "in vec3 a_pos; in vec3 a_other; in float a_side; in float a_end; in vec4 a_color; out vec4 v_color;\n" +
        "void main() {\n" +
        "  v_color = a_color;\n" +
        "  vec4 p = u_matrix * vec4(a_pos, 1.0); vec4 o = u_matrix * vec4(a_other, 1.0);\n" +
        "  vec2 d = o.xy / o.w * u_viewport - p.xy / p.w * u_viewport;\n" +
        "  d = length(d) > 0.0001 ? normalize(d) : vec2(1.0, 0.0);\n" +
        "  if (a_end > 0.5) d = -d;\n" +
        "  p.xy += vec2(-d.y, d.x) * a_side * 0.5 * u_width / u_viewport * p.w;\n" +
        "  gl_Position = p;\n" +
        "}\n";
    var COLOR_FS = "#version 300 es\nprecision highp float;\nin vec4 v_color; out vec4 color;\n" +
        "void main() { color = vec4(v_color.rgb * v_color.a, v_color.a); }\n";
    var DISC_VS = "#version 300 es\n" +
        "uniform mat4 u_matrix; uniform vec2 u_viewport; uniform float u_radius;\n" +
        "in vec3 a_pos; in vec2 a_corner; out vec2 v_corner;\n" +
        "void main() {\n" +
        "  vec4 p = u_matrix * vec4(a_pos, 1.0);\n" +
        "  p.xy += a_corner * u_radius / u_viewport * p.w;\n" +
        "  v_corner = a_corner; gl_Position = p;\n" +
        "}\n";
    var DISC_FS = "#version 300 es\nprecision highp float;\nuniform vec4 u_color; uniform vec4 u_ring; uniform float u_radius;\n" +
        "in vec2 v_corner; out vec4 color;\n" +
        "void main() {\n" +
        "  float r = length(v_corner); if (r > 1.0) discard;\n" +
        "  vec4 c = r > 1.0 - 1.5 / u_radius ? u_ring : u_color;\n" +
        "  color = vec4(c.rgb * c.a, c.a);\n" +
        "}\n";

    function program(gl, vs, fs) {
        function shader(type, source) {
            var s = gl.createShader(type);
            gl.shaderSource(s, source);
            gl.compileShader(s);
            if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error("route_3d: " + gl.getShaderInfoLog(s));
            return s;
        }
        var p = gl.createProgram();
        gl.attachShader(p, shader(gl.VERTEX_SHADER, vs));
        gl.attachShader(p, shader(gl.FRAGMENT_SHADER, fs));
        gl.linkProgram(p);
        if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error("route_3d: " + gl.getProgramInfoLog(p));
        return p;
    }

    // opts: {maplibregl, map, id, before (layer id or undefined), discs (draw the points: true where no markers do),
    //        heightsAt(points) -> Promise<[meters or null]> (pointer_height.js's reader: the surface checked against),
    //        onFrame(project) (after each frame drawn: project(lng, lat, meters) -> {x, y} in CSS pixels, or null),
    //        onCollisions(count) (the stretches inside the surface, when worked out again; null when there is no plan)}
    // The 2D map's stretches are the GeoJSON layer `<id>-flat`, added under `flatBefore`, else `before`.
    // Returns {setAir(air, takeoff), show(on) (3D), refresh() (the surface read again), project(lng, lat, meters),
    //          unproject(x, y, heightAt, start), resolved() (with the paths as checked, their kinds and count),
    //          routeNear(point) (the route under the pointer: {lng, lat, height} or null), surfaceAt(lng, lat)}
    function createRoute3d(opts) {
        var map = opts.map, M = opts.maplibregl;
        var air = null, takeoff = null, shown = false, geometry = null, current = null, dirty = false, matrix = null;
        var gl = null, programs = null, buffers = null, run = 0;
        var flatId = opts.id + "-flat", EMPTY = {type: "FeatureCollection", features: []};
        map.addSource(flatId, {type: "geojson", data: EMPTY});
        map.addLayer({id: flatId, type: "line", source: flatId, layout: {"line-sort-key": ["get", "order"], "line-cap": "round"},
                      paint: {"line-color": ["match", ["get", "kind"], "inside", "#e53935", "#ffd500"], "line-width": 4}},
                     [opts.flatBefore, opts.before].filter(function (id) { return id && map.getLayer(id); })[0]);

        function toWorld(lng, lat, h) {
            var c = M.MercatorCoordinate.fromLngLat([lng, lat], h);
            return [c.x, c.y, c.z];
        }

        function surfaceAt(lng, lat) {
            var h = map.queryTerrainElevation([lng, lat]);
            return typeof h === "number" ? h : null;
        }

        // Draws the checked route: the WebGL layer's geometry in 3D, the stretches on the 2D map's lines in 2D
        function draw() {
            geometry = shown && current ? buildGeometry(current, toWorld, !!opts.discs) : null;
            dirty = true;
            map.triggerRepaint();
            var flat = map.getSource(flatId);
            if (flat) flat.setData(!shown && current ? flatStretches(current) : EMPTY);
        }

        // Checks the plan against the surface again: reads its points' heights, then resolves and collides; a newer
        // run drops an older one still reading
        function refresh() {
            var mine = ++run;
            if (!air) {
                current = null; draw();
                if (opts.onCollisions) opts.onCollisions(null);
                return Promise.resolve();
            }
            var a = air, t = takeoff, need = pointsNeeded(a, t);
            return opts.heightsAt(need.points).then(function (heights) {
                if (mine !== run) return;
                function sampled(lng, lat) {
                    var i = need.index[lng + "," + lat], h = i === undefined ? null : heights[i];
                    return typeof h === "number" && isFinite(h) ? h : null;
                }
                var resolved = resolveAir(a, sampled, t);
                if (!resolved) {
                    current = null; draw();
                    if (opts.onCollisions) opts.onCollisions(null);
                    return;
                }
                var margin = opts.margin ? opts.margin() : 0;
                if (!opts.bandMaxes) return finish(collide(resolved.paths, sampled));
                // with the band: every piece checked against the highest surface within the margin of it
                var pieces = [];
                resolved.paths.forEach(function (p) {
                    for (var i = 1; i < p.length; i++) pieces.push([p[i - 1][0], p[i - 1][1], p[i][0], p[i][1]]);
                });
                return opts.bandMaxes(pieces, margin).then(function (found) {
                    if (mine !== run) return;
                    var next = 0, maxes = resolved.paths.map(function (p) { return found.slice(next, next += Math.max(p.length - 1, 0)); });
                    finish(collide(resolved.paths, sampled, LEAD, {margin: margin, maxes: maxes}));
                });
                function finish(hit) {
                    current = {paths: hit.paths, kinds: hit.kinds, count: hit.count, points: resolved.points, drops: resolved.drops};
                    draw();
                    if (opts.onCollisions) opts.onCollisions(hit.count);
                }
            });
        }

        function upload() {
            [["lines", geometry.lines], ["inside", geometry.inside], ["drops", geometry.drops], ["discs", geometry.discs]].forEach(function (b) {
                gl.bindBuffer(gl.ARRAY_BUFFER, buffers[b[0]]);
                gl.bufferData(gl.ARRAY_BUFFER, b[1], gl.STATIC_DRAW);
            });
            dirty = false;
        }

        function attribute(p, name, size, stride, offset) {
            var loc = gl.getAttribLocation(p, name);
            gl.enableVertexAttribArray(loc);
            gl.vertexAttribPointer(loc, size, gl.FLOAT, false, stride * 4, offset * 4);
            return loc;
        }

        function drawLines(buffer, count, width, m, viewport) {
            if (!count) return;
            var p = programs.line;
            gl.useProgram(p);
            gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
            var locs = [attribute(p, "a_pos", 3, 12, 0), attribute(p, "a_other", 3, 12, 3), attribute(p, "a_side", 1, 12, 6),
                        attribute(p, "a_end", 1, 12, 7), attribute(p, "a_color", 4, 12, 8)];
            gl.uniformMatrix4fv(gl.getUniformLocation(p, "u_matrix"), false, m);
            gl.uniform2fv(gl.getUniformLocation(p, "u_viewport"), viewport);
            gl.uniform1f(gl.getUniformLocation(p, "u_width"), width * (root.devicePixelRatio || 1));
            gl.drawArrays(gl.TRIANGLES, 0, count);
            locs.forEach(function (l) { gl.disableVertexAttribArray(l); });
        }

        function drawDiscs(m, viewport) {
            if (!geometry.discCount) return;
            var p = programs.disc, ratio = root.devicePixelRatio || 1;
            gl.useProgram(p);
            gl.bindBuffer(gl.ARRAY_BUFFER, buffers.discs);
            var locs = [attribute(p, "a_pos", 3, 5, 0), attribute(p, "a_corner", 2, 5, 3)];
            gl.uniformMatrix4fv(gl.getUniformLocation(p, "u_matrix"), false, m);
            gl.uniform2fv(gl.getUniformLocation(p, "u_viewport"), viewport);
            gl.uniform1f(gl.getUniformLocation(p, "u_radius"), DISC_RADIUS * ratio);
            gl.uniform4fv(gl.getUniformLocation(p, "u_color"), COLORS.disc);
            gl.uniform4fv(gl.getUniformLocation(p, "u_ring"), COLORS.ring);
            gl.drawArrays(gl.TRIANGLES, 0, geometry.discCount);
            locs.forEach(function (l) { gl.disableVertexAttribArray(l); });
        }

        var layer = {
            id: opts.id, type: "custom", renderingMode: "3d",
            onAdd: function (_map, context) {
                gl = context;
                programs = {line: program(gl, LINE_VS, COLOR_FS), disc: program(gl, DISC_VS, DISC_FS)};
                buffers = {lines: gl.createBuffer(), inside: gl.createBuffer(), drops: gl.createBuffer(), discs: gl.createBuffer()};
                dirty = true;
            },
            onRemove: function () {
                if (!gl) return;
                Object.keys(buffers).forEach(function (k) { gl.deleteBuffer(buffers[k]); });
                gl.deleteProgram(programs.line);
                gl.deleteProgram(programs.disc);
                gl = null;
            },
            render: function (context, args) {
                matrix = args.defaultProjectionData.mainMatrix;
                if (!geometry || !shown) return;
                if (dirty) upload();
                var m = translated(matrix, geometry.origin);
                var viewport = [gl.drawingBufferWidth / 2, gl.drawingBufferHeight / 2];
                gl.enable(gl.DEPTH_TEST);
                gl.depthFunc(gl.LEQUAL);
                gl.depthMask(false);
                gl.enable(gl.BLEND);
                gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
                drawLines(buffers.drops, geometry.dropCount, DROP_WIDTH, m, viewport);
                drawLines(buffers.lines, geometry.lineCount, LINE_WIDTH, m, viewport);
                gl.disable(gl.DEPTH_TEST);                // the stretches inside the surface, seen through it
                drawLines(buffers.inside, geometry.insideCount, LINE_WIDTH, m, viewport);
                gl.enable(gl.DEPTH_TEST);
                drawDiscs(m, viewport);
                if (opts.onFrame) opts.onFrame(project);
            }
        };

        // Where a point in the air is on the screen, in CSS pixels (after the first frame), or null
        function project(lng, lat, h) {
            if (!matrix) return null;
            var w = toWorld(lng, lat, h), m = matrix;
            var x = m[0] * w[0] + m[4] * w[1] + m[8] * w[2] + m[12];
            var y = m[1] * w[0] + m[5] * w[1] + m[9] * w[2] + m[13];
            var q = m[3] * w[0] + m[7] * w[1] + m[11] * w[2] + m[15];
            if (q <= 0) return null;
            var canvas = map.getCanvas(), width = canvas.clientWidth, height = canvas.clientHeight;
            return {x: (x / q + 1) / 2 * width, y: (1 - y / q) / 2 * height};
        }

        // The position on the screen point x, y (CSS pixels) at the heights heightAt(lng, lat) gives, as [lng, lat]:
        // a few rounds from `start` [lng, lat], each taking the height (and the world's scale, which changes with the
        // latitude) where the last landed; null before the first frame or off the ground's side of the horizon
        function unproject(x, y, heightAt, start) {
            var inverse = matrix && invert(matrix);
            if (!inverse) return null;
            var canvas = map.getCanvas(), ndcX = x / canvas.clientWidth * 2 - 1, ndcY = 1 - y / canvas.clientHeight * 2;
            var at = start;
            for (var round = 0; round < 6; round++) {
                var h = heightAt(at[0], at[1]);
                if (typeof h !== "number" || !isFinite(h)) return null;
                var xy = rayAtLevel(inverse, ndcX, ndcY, toWorld(at[0], at[1], h)[2]);
                if (!xy) return null;
                var next = toLngLat(xy[0], xy[1]);
                var moved = Math.abs(next[0] - at[0]) + Math.abs(next[1] - at[1]);
                at = next;
                if (moved < 1e-9) break;
            }
            return at;
        }

        // The route under the pointer: on the 2D map at its place, in 3D at its height
        function routeNear(point) {
            if (!current) return null;
            var toScreen = shown ? project : function (lng, lat) { var s = map.project([lng, lat]); return {x: s.x, y: s.y}; };
            return nearest(current.paths, toScreen, point, NEAR_PX);
        }

        return {
            layer: layer,
            setAir: function (a, t) { air = a || null; takeoff = t || null; return refresh(); },
            show: function (on) {
                shown = !!on;
                if (shown && !map.getLayer(opts.id)) map.addLayer(layer, opts.before && map.getLayer(opts.before) ? opts.before : undefined);
                draw();
            },
            refresh: refresh,
            project: project,
            unproject: unproject,
            resolved: function () { return current; },
            routeNear: routeNear,
            surfaceAt: surfaceAt
        };
    }

    var api = {createRoute3d: createRoute3d, resolveAir: resolveAir, labelHeights: labelHeights, formatLabel: formatLabel,
               buildGeometry: buildGeometry, translated: translated, cut: cut, collide: collide, collisionText: collisionText,
               pointsNeeded: pointsNeeded, flatStretches: flatStretches, nearest: nearest, NEAR_PX: NEAR_PX,
               LEAD: LEAD, CLEAR: CLEAR, NEAR: NEAR, INSIDE: INSIDE,
               invert: invert, rayAtLevel: rayAtLevel, toLngLat: toLngLat, airDrag: airDrag, STEP: STEP, MAX_POINTS: MAX_POINTS};
    root.MissionPlannerRoute3d = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
