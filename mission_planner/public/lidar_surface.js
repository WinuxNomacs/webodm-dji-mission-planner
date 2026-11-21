/* global Uint8ClampedArray */
// The lidar surface of the 3D view, in the browser (the server side is lidar.py). Where USGS lidar covers a route, the
// editors' 3D view raises the ground to a 1 m surface with trees and buildings; elsewhere it is AWS's Terrarium tiles,
// as before. The terrain source loads its tiles through an "mplidar://" protocol (maplibregl.addProtocol): a lidar
// tile when its unit (a zoom-15 tile) is built, else AWS's tile, above zoom 15 cut from its zoom-15 parent and
// enlarged pixel for pixel (the heights are encoded in the colours, so they must not be blended). request() asks the
// server for the units around a route and polls their states until they are built, saying so in the status bar on the
// map; ensure() does the same from the 2D map, only when the route reaches units not asked for yet. Plain ES5, the browser's parts passed in, so that it can be tested.
(function (root) {
    var AWS = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
    var PROTOCOL = "mplidar";
    var UNIT_ZOOM = 15, MAX_ZOOM = 18, TILE = 256;
    var POLL_MS = 2000, POLL_DEADLINE_MS = 10 * 60 * 1000, NOTE_MS = 6000;
    var LOADING_DELAY_MS = 400, LOADING_TEXT = "Loading elevation…";
    var PARENTS = 16;                       // decoded zoom-15 AWS tiles kept, to cut the tiles above zoom 15 from
    var ATTRIBUTION = 'Terrain: <a href="https://www.usgs.gov/3d-elevation-program">USGS 3DEP lidar</a> and ' +
                      '<a href="https://registry.opendata.aws/terrain-tiles/">Terrain Tiles</a>';

    function unitOf(z, x, y) {
        var d = z - UNIT_ZOOM;
        return [x >> d, y >> d];
    }

    // The zoom-15 units a [west, south, east, north] box spans, as a key: "west_x,north_y,east_x,south_y"
    function unitsKey(b) {
        var n = Math.pow(2, UNIT_ZOOM);
        function x(lng) { return Math.min(Math.floor((lng + 180) / 360 * n), n - 1); }
        function y(lat) {
            var s = Math.sin(Math.max(Math.min(lat, 85), -85) * Math.PI / 180);
            return Math.min(Math.floor((0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n), n - 1);
        }
        return [x(b[0]), y(b[3]), x(b[2]), y(b[1])].join(",");
    }

    // Where a tile above zoom 15 lies in its zoom-15 parent: {x, y, left, top, size} (pixels of the parent)
    function parentCrop(z, x, y) {
        var d = z - UNIT_ZOOM, px = x >> d, py = y >> d, size = TILE >> d;
        return {x: px, y: py, left: (x - (px << d)) * size, top: (y - (py << d)) * size, size: size};
    }

    // [west, south, east, north] of [[lng, lat], ...], or null when there are none
    function boundsOf(points) {
        var b = null;
        (points || []).forEach(function (p) {
            if (!p || typeof p[0] !== "number" || typeof p[1] !== "number" || !isFinite(p[0]) || !isFinite(p[1])) return;
            if (!b) b = [p[0], p[1], p[0], p[1]];
            else b = [Math.min(b[0], p[0]), Math.min(b[1], p[1]), Math.max(b[2], p[0]), Math.max(b[3], p[1])];
        });
        return b;
    }

    // What the status bar says about the units' states: {busy, text}, or null when there is nothing to say
    function statusOf(units) {
        var count = {done: 0, none: 0, failed: 0, waiting: 0}, failure = "";
        units.forEach(function (u) {
            if (u.state === "done") count.done++;
            else if (u.state === "none") count.none++;
            else if (u.state === "failed") { count.failed++; if (!failure) failure = u.message || ""; }
            else count.waiting++;
        });
        if (count.waiting) {
            return {busy: true, text: "Building the lidar surface (" + (units.length - count.waiting) + " of " + units.length + ")"};
        }
        if (count.failed) {
            return {busy: false, text: "The lidar surface could not be built " + (count.done ? "everywhere" : "here") + (failure ? ": " + failure : "")};
        }
        if (!count.done) return {busy: false, text: "No lidar here: the standard terrain is used"};
        return null;
    }

    // The small bar on the map that says the surface is being built or its elevation loaded (with a spinner), or why
    // it is not there. One message at a time: show(status) sets the lidar's (a build in progress first), loading(on)
    // says whether the map's elevation tiles are loading (said once it has lasted LOADING_DELAY_MS, so that a quick
    // pan from the cache does not flash it); a note (a status not busy) shows for NOTE_MS once nothing else is said.
    function createStatusBar(doc, container, timers) {
        timers = timers || {setTimeout: setTimeout.bind(root), clearTimeout: clearTimeout.bind(root)};
        var bar = doc.createElement("div");
        bar.className = "mp-lidar-status";
        bar.setAttribute("role", "status");
        bar.hidden = true;
        var spinner = doc.createElement("i");
        spinner.className = "fa fa-circle-notch fa-spin";
        var text = doc.createElement("span");
        bar.appendChild(spinner);
        bar.appendChild(text);
        container.appendChild(bar);
        var status = null, isLoading = false, loadingShown = false, loadingTimer = null, noteTimer = null;
        function render() {
            var current = status && status.busy ? status : loadingShown ? {busy: true, text: LOADING_TEXT} : status;
            if (noteTimer && current !== status) { timers.clearTimeout(noteTimer); noteTimer = null; }   // shown in full later
            bar.hidden = !current;
            if (!current) return;
            spinner.hidden = !current.busy;
            text.textContent = current.text;
            if (!current.busy && !noteTimer) noteTimer = timers.setTimeout(function () { noteTimer = null; status = null; render(); }, NOTE_MS);
        }
        function show(s) {
            if (noteTimer) { timers.clearTimeout(noteTimer); noteTimer = null; }
            status = s;
            render();
        }
        function loading(on) {
            on = !!on;
            if (on === isLoading) return;
            isLoading = on;
            if (on) {
                loadingTimer = timers.setTimeout(function () { loadingTimer = null; loadingShown = true; render(); }, LOADING_DELAY_MS);
                return;
            }
            if (loadingTimer) { timers.clearTimeout(loadingTimer); loadingTimer = null; }
            if (loadingShown) { loadingShown = false; render(); }
        }
        return {element: bar, show: show, loading: loading};
    }

    // Tells the bar whether the map's elevation (source sourceId) has tiles loading, while active() (the 3D view):
    // checked as each frame is drawn and each tile arrives (a raster source says nothing when a tile starts loading),
    // and over once the map is idle (everything loaded and drawn; a tile that failed counts as done). check() for a
    // change the map does not draw (leaving 3D).
    function watchElevation(map, bar, sourceId, active) {
        function check() {
            var on = false;
            if (active() && map.getSource(sourceId)) {
                try { on = !map.isSourceLoaded(sourceId); } catch (e) { on = false; }
            }
            bar.loading(on);
        }
        map.on("render", check);
        map.on("sourcedata", function (e) { if (!e || e.sourceId === sourceId) check(); });
        map.on("idle", function () { bar.loading(false); });
        return {check: check};
    }

    // The bounds of a web-mercator tile, [west, south, east, north] in degrees
    function tileLonLat(z, x, y) {
        var n = Math.pow(2, z);
        function lat(row) { return Math.atan(Math.sinh(Math.PI * (1 - 2 * row / n))) * 180 / Math.PI; }
        return [x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)];
    }

    function touches(b, z, x, y) {
        var t = tileLonLat(z, x, y);
        return t[0] <= b[2] && b[0] <= t[2] && t[1] <= b[3] && b[1] <= t[3];
    }

    // `size` x `size` pixels of a 256 x 256 RGBA tile, from (left, top), enlarged to 256 x 256 pixel for pixel
    function cropRgba(rgba, c) {
        var out = new Uint8ClampedArray(TILE * TILE * 4);
        for (var j = 0; j < TILE; j++) {
            var row = (c.top + Math.floor(j * c.size / TILE)) * TILE;
            for (var i = 0; i < TILE; i++) {
                var from = (row + c.left + Math.floor(i * c.size / TILE)) * 4, to = (j * TILE + i) * 4;
                out[to] = rgba[from]; out[to + 1] = rgba[from + 1]; out[to + 2] = rgba[from + 2]; out[to + 3] = 255;
            }
        }
        return out;
    }

    // A task's tile (Terrarium, its weight in the alpha) over the surface under it: the heights mixed by that weight
    function blend(under, task) {
        var out = new Uint8ClampedArray(TILE * TILE * 4);
        for (var i = 0; i < out.length; i += 4) {
            var a = task[i + 3] / 255;
            if (a <= 0) {
                out[i] = under[i]; out[i + 1] = under[i + 1]; out[i + 2] = under[i + 2];
            } else {
                var hu = under[i] * 256 + under[i + 1] + under[i + 2] / 256;
                var ht = task[i] * 256 + task[i + 1] + task[i + 2] / 256;
                var v = Math.min(Math.max(hu * (1 - a) + ht * a, 0), 65535.996);
                out[i] = Math.floor(v / 256); out[i + 1] = Math.floor(v) % 256; out[i + 2] = Math.floor((v - Math.floor(v)) * 256);
            }
            out[i + 3] = 255;
        }
        return out;
    }

    function imageInBrowser(rgba) {
        return root.createImageBitmap(new root.ImageData(rgba, TILE, TILE));
    }

    // opts: {maplibregl, fetch, api, csrf, onStatus(status|null), onTilesChanged(tiles), now(),
    //        setTimeout, clearTimeout, decodeRgba(buffer) -> Promise<rgba> (pointer_height.js's, no canvas: Brave),
    //        toImage(rgba) -> Promise<image>, lidar: false (the lidar's tiles not used, until setLidar(true))}
    // Returns {source(), request(bounds), refresh(bounds), stop(), load(params, abortController), isBuilt(unitX, unitY),
    //          setTask({id, v, bounds} | null) (a WebODM task's surface over the rest, Phase 23), hasTask(unitX, unitY),
    //          setLidar(on) (the lidar's tiles used or not)}
    function createLidarSurface(opts) {
        var fetchFn = opts.fetch, now = opts.now || function () { return Date.now(); };
        var later = opts.setTimeout || setTimeout.bind(root), cancel = opts.clearTimeout || clearTimeout.bind(root);
        var built = {}, version = 0, generation = 0, timer = null;   // built: the units' tiles' versions, by "x_y"
        var task = null, lidarOn = opts.lidar !== false;
        var decodeRgba = opts.decodeRgba || function (b) { return root.MissionPlannerPointerHeight.decodeInBrowser(b); };
        var toImage = opts.toImage || imageInBrowser;
        var rgbaParents = {}, rgbaOrder = [];   // zoom-15 AWS tiles as RGBA, decoded once for every tile cut from them

        function bytes(url, signal, credentials) {
            return fetchFn(url, {signal: signal, credentials: credentials || "omit"}).then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.arrayBuffer();
            }).then(function (data) { return {data: data}; });
        }

        // AWS's tile; above zoom 15 cut from its zoom-15 parent, as an image for the map with its pixels (read as they
        // are by pointer_height.js: through a canvas, Brave would alter them)
        function aws(z, x, y, signal) {
            if (z <= UNIT_ZOOM) return bytes(AWS.replace("{z}", z).replace("{x}", x).replace("{y}", y), signal);
            var c = parentCrop(z, x, y);
            return parentRgba(c.x, c.y).then(function (rgba) {
                if (signal && signal.aborted) throw new Error("Cancelled");
                var cut = cropRgba(rgba, c);
                return toImage(cut).then(function (image) { return {data: image, rgba: cut}; });
            });
        }

        // The zoom-15 AWS tile as RGBA (decoded without a canvas), shared by the tiles above it: fetched without a
        // tile's signal, since another tile may still need it; dropped when it fails, so that the next tile tries again
        function parentRgba(x, y) {
            var key = x + "/" + y;
            if (!rgbaParents[key]) {
                var p = rgbaParents[key] = fetchFn(AWS.replace("{z}", UNIT_ZOOM).replace("{x}", x).replace("{y}", y), {credentials: "omit"})
                    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.arrayBuffer(); })
                    .then(decodeRgba);
                p.catch(function () { if (rgbaParents[key] === p) { delete rgbaParents[key]; rgbaOrder.splice(rgbaOrder.indexOf(key), 1); } });
                rgbaOrder.push(key);
                if (rgbaOrder.length > PARENTS) delete rgbaParents[rgbaOrder.shift()];
            }
            return rgbaParents[key];
        }

        // The surface under a task's tile as RGBA: the lidar's tile where its unit is built, else AWS's
        function underRgba(z, x, y, signal) {
            function aws() {
                if (z <= UNIT_ZOOM) return bytes(AWS.replace("{z}", z).replace("{x}", x).replace("{y}", y), signal).then(function (r) { return decodeRgba(r.data); });
                var c = parentCrop(z, x, y);
                return parentRgba(c.x, c.y).then(function (rgba) { return cropRgba(rgba, c); });
            }
            var unit = unitOf(z, x, y);
            if (!isBuilt(unit[0], unit[1])) return aws();
            return bytes(lidarUrl(z, x, y, unit), signal, "same-origin").then(function (r) { return decodeRgba(r.data); })
                .catch(function (e) { if (signal && signal.aborted) throw e; return aws(); });
        }

        // A tile where the chosen task is: its tile blended over the surface under it ({data: image, rgba}); the
        // surface alone where the task has no tile there
        function blended(z, x, y, signal) {
            var t = task;
            var mine = bytes(opts.api + "task-surface/" + t.id + "/tiles/" + z + "/" + x + "/" + y + ".png?v=" + t.v, signal, "same-origin")
                .then(function (r) { return decodeRgba(r.data); }, function (e) { if (signal && signal.aborted) throw e; return null; });
            return Promise.all([underRgba(z, x, y, signal), mine]).then(function (both) {
                var rgba = both[1] ? blend(both[0], both[1]) : both[0];
                return toImage(rgba).then(function (image) { return {data: image, rgba: rgba}; });
            });
        }

        function lidarUrl(z, x, y, unit) {
            // the version in the URL: the browser keeps a tile an hour, and a unit built again has new ones
            return opts.api + "lidar/tiles/" + z + "/" + x + "/" + y + ".png?v=" + built[unit[0] + "_" + unit[1]];
        }

        function load(params, abortController) {
            var m = /^mplidar:\/\/(\d+)\/(\d+)\/(\d+)/.exec(params.url || "");
            if (!m) return Promise.reject(new Error("Not a lidar tile: " + params.url));
            var z = +m[1], x = +m[2], y = +m[3], signal = abortController && abortController.signal;
            if (task && z >= UNIT_ZOOM && touches(task.bounds, z, x, y)) return blended(z, x, y, signal);
            var unit = z >= UNIT_ZOOM ? unitOf(z, x, y) : null;
            if (unit && isBuilt(unit[0], unit[1])) {
                return bytes(lidarUrl(z, x, y, unit), signal, "same-origin")
                    .catch(function (e) { if (signal && signal.aborted) throw e; return aws(z, x, y, signal); });
            }
            return aws(z, x, y, signal);
        }
        if (opts.maplibregl && opts.maplibregl.addProtocol && !opts.maplibregl.__mpLidar) {
            opts.maplibregl.addProtocol(PROTOCOL, load);
            opts.maplibregl.__mpLidar = true;
        }

        function tiles() { return [PROTOCOL + "://{z}/{x}/{y}?v=" + version]; }

        function source() {
            return {type: "raster-dem", encoding: "terrarium", tileSize: TILE, maxzoom: MAX_ZOOM, tiles: tiles(), attribution: ATTRIBUTION};
        }

        var asked = null;                       // the units of the last request, while it stands

        function stop() {
            generation++;
            asked = null;
            if (timer) { cancel(timer); timer = null; }
            if (opts.onStatus) opts.onStatus(null);
        }

        // Takes the units' states: remembers the built ones and their tiles' versions (and reloads the tiles when there
        // are new ones, or a unit's are made again), says
        // how far it is (unless quiet), and answers whether to poll again
        function take(units, quiet) {
            var fresh = false;
            units.forEach(function (u) {
                var key = u.x + "_" + u.y;
                var v = u.v || 0;
                if (u.state === "done" && built[key] !== v) { built[key] = v; fresh = true; }
            });
            if (fresh) changed();
            var status = statusOf(units);
            if (opts.onStatus && !quiet) opts.onStatus(status);
            return !!(status && status.busy);
        }

        // Learns which units around a route are built, building none and saying nothing (the 2D view's heights)
        function refresh(bounds) {
            if (!bounds) return Promise.resolve();
            return fetchFn(opts.api + "lidar/surface?bounds=" + bounds.join(","), {credentials: "same-origin"})
                .then(function (r) { return r.ok ? r.json() : {units: []}; })
                .then(function (body) { take(body.units || [], true); })
                .catch(function () { /* the heights fall back on the terrain tiles */ });
        }

        function isBuilt(x, y) { return lidarOn && Object.prototype.hasOwnProperty.call(built, x + "_" + y); }

        function changed() {
            version++;
            if (opts.onTilesChanged) opts.onTilesChanged(tiles());
        }

        // The chosen task's surface ({id, v, bounds: [west, south, east, north]}), or none
        function setTask(t) {
            var next = t && t.id && t.bounds ? {id: t.id, v: t.v || 0, bounds: t.bounds} : null;
            if (JSON.stringify(next) === JSON.stringify(task)) return;
            task = next;
            changed();
        }

        function setLidar(on) {
            if (lidarOn === !!on) return;
            lidarOn = !!on;
            changed();
        }

        function hasTask(x, y) { return !!task && touches(task.bounds, UNIT_ZOOM, x, y); }

        function request(bounds) {
            stop();
            if (!bounds) return Promise.resolve();
            asked = unitsKey(bounds);
            var mine = generation, started = now();
            function answer(r) {
                return r.json().catch(function () { return {}; }).then(function (body) {
                    if (!r.ok) throw new Error(body.error || ("HTTP " + r.status));
                    return body.units || [];
                });
            }
            function poll() {
                timer = null;
                if (mine !== generation) return;
                if (now() - started > POLL_DEADLINE_MS) {
                    if (opts.onStatus) opts.onStatus({busy: false, text: "The lidar surface was not built within 10 minutes: the standard terrain is used"});
                    return;
                }
                fetchFn(opts.api + "lidar/surface?bounds=" + bounds.join(","), {credentials: "same-origin"})
                    .then(answer)
                    .then(function (units) { if (mine === generation && take(units)) timer = later(poll, POLL_MS); })
                    .catch(function () { if (mine === generation) timer = later(poll, POLL_MS); });   // a missed answer: ask again
            }
            return fetchFn(opts.api + "lidar/surface", {
                method: "POST", credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": opts.csrf}, body: JSON.stringify({bounds: bounds})
            }).then(answer).then(function (units) {
                if (mine === generation && take(units)) timer = later(poll, POLL_MS);
            }).catch(function (e) {
                if (mine === generation && opts.onStatus) opts.onStatus({busy: false, text: "No lidar surface: " + e.message});
            });
        }

        // request(), unless the last one (not stopped since) was for the same units
        function ensure(bounds) {
            if (!bounds || unitsKey(bounds) === asked) return Promise.resolve();
            return request(bounds);
        }

        return {source: source, request: request, ensure: ensure, refresh: refresh, stop: stop, load: load, isBuilt: isBuilt,
                setTask: setTask, hasTask: hasTask, setLidar: setLidar};
    }

    var api = {createLidarSurface: createLidarSurface, createStatusBar: createStatusBar, watchElevation: watchElevation, PARENTS: PARENTS,
               boundsOf: boundsOf, statusOf: statusOf, parentCrop: parentCrop, unitOf: unitOf, unitsKey: unitsKey,
               blend: blend, cropRgba: cropRgba, tileLonLat: tileLonLat,
               POLL_MS: POLL_MS, POLL_DEADLINE_MS: POLL_DEADLINE_MS, NOTE_MS: NOTE_MS, LOADING_DELAY_MS: LOADING_DELAY_MS};
    root.MissionPlannerLidar = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
