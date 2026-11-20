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

    // Draws `size` x `size` pixels of a tile image, from (left, top), enlarged to 256 x 256 without blending, and
    // answers it as PNG bytes. The browser's version; the tests pass their own.
    function cropInBrowser(blob, crop) {
        return root.createImageBitmap(blob).then(function (image) {
            var canvas = typeof root.OffscreenCanvas === "function" ? new root.OffscreenCanvas(TILE, TILE) : root.document.createElement("canvas");
            canvas.width = canvas.height = TILE;
            var ctx = canvas.getContext("2d");
            ctx.imageSmoothingEnabled = false;
            ctx.drawImage(image, crop.left, crop.top, crop.size, crop.size, 0, 0, TILE, TILE);
            if (image.close) image.close();
            var png = canvas.convertToBlob ? canvas.convertToBlob({type: "image/png"})
                : new Promise(function (resolve) { canvas.toBlob(resolve, "image/png"); });
            return png.then(function (b) { return b.arrayBuffer(); });
        });
    }

    // opts: {maplibregl, fetch, api, csrf, onStatus(status|null), onTilesChanged(tiles), crop(blob, crop), now(),
    //        setTimeout, clearTimeout}
    // Returns {source(), request(bounds), refresh(bounds), stop(), load(params, abortController), isBuilt(unitX, unitY)}
    function createLidarSurface(opts) {
        var fetchFn = opts.fetch, now = opts.now || function () { return Date.now(); };
        var later = opts.setTimeout || setTimeout.bind(root), cancel = opts.clearTimeout || clearTimeout.bind(root);
        var crop = opts.crop || cropInBrowser;
        var built = {}, version = 0, generation = 0, timer = null;

        function bytes(url, signal, credentials) {
            return fetchFn(url, {signal: signal, credentials: credentials || "omit"}).then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.arrayBuffer();
            }).then(function (data) { return {data: data}; });
        }

        function aws(z, x, y, signal) {
            if (z <= UNIT_ZOOM) return bytes(AWS.replace("{z}", z).replace("{x}", x).replace("{y}", y), signal);
            var c = parentCrop(z, x, y);
            return fetchFn(AWS.replace("{z}", UNIT_ZOOM).replace("{x}", c.x).replace("{y}", c.y), {signal: signal, credentials: "omit"})
                .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.blob(); })
                .then(function (blob) { return crop(blob, c); })
                .then(function (data) { return {data: data}; });
        }

        function load(params, abortController) {
            var m = /^mplidar:\/\/(\d+)\/(\d+)\/(\d+)/.exec(params.url || "");
            if (!m) return Promise.reject(new Error("Not a lidar tile: " + params.url));
            var z = +m[1], x = +m[2], y = +m[3], signal = abortController && abortController.signal;
            var unit = z >= UNIT_ZOOM ? unitOf(z, x, y) : null;
            if (unit && built[unit[0] + "_" + unit[1]]) {
                return bytes(opts.api + "lidar/tiles/" + z + "/" + x + "/" + y + ".png", signal, "same-origin")
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

        // Takes the units' states: remembers the built ones (and reloads the tiles when there are new ones), says
        // how far it is (unless quiet), and answers whether to poll again
        function take(units, quiet) {
            var fresh = false;
            units.forEach(function (u) {
                var key = u.x + "_" + u.y;
                if (u.state === "done" && !built[key]) { built[key] = true; fresh = true; }
            });
            if (fresh) {
                version++;
                if (opts.onTilesChanged) opts.onTilesChanged(tiles());
            }
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

        function isBuilt(x, y) { return !!built[x + "_" + y]; }

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

        return {source: source, request: request, ensure: ensure, refresh: refresh, stop: stop, load: load, isBuilt: isBuilt};
    }

    var api = {createLidarSurface: createLidarSurface, createStatusBar: createStatusBar, watchElevation: watchElevation,
               boundsOf: boundsOf, statusOf: statusOf, parentCrop: parentCrop, unitOf: unitOf, unitsKey: unitsKey,
               POLL_MS: POLL_MS, POLL_DEADLINE_MS: POLL_DEADLINE_MS, NOTE_MS: NOTE_MS, LOADING_DELAY_MS: LOADING_DELAY_MS};
    root.MissionPlannerLidar = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
