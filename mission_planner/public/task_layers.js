// A WebODM task in the editors' map (Phase 23): Map layers lists the processed tasks the user can view over the route
// (the task-surfaces API); the user picks at most one and turns on its DSM (the 3D ground, cut into tiles on the
// server, task_surface.py, and blended over the lidar or terrain by lidar_surface.js) and its orthophoto (WebODM's own
// map tiles, above the basemap), or both. The choice is remembered per route in this browser. Plain ES5, the map and
// the browser's parts passed in, so that it can be tested.
(function (root) {
    var ORTHO = "mp-task-ortho";
    var POLL_MS = 2000, POLL_DEADLINE_MS = 10 * 60 * 1000;
    var KEY = "mission-planner:task:";
    var MATCHED = {lidar: "the lidar", terrain: "the terrain", mixed: "the lidar and terrain"};

    // What Map layers says of a task's surface once cut
    function surfaceNote(answer) {
        if (answer.state === "failed") return "The task's DSM could not be shown: " + (answer.message || "unknown error");
        if (answer.state !== "done") return "Preparing the task's DSM…";
        if (!answer.reference) return "The task's heights are placed by the geoid alone (no surface under it to match)";
        var m = typeof answer.match === "number" ? " (" + (answer.match > 0 ? "+" : "") + answer.match.toFixed(1) + " m)" : "";
        return "The task's heights are matched to " + MATCHED[answer.reference] + m;
    }

    // A tile URL WebODM gives from its root ("/api/...") made whole, its {z}/{x}/{y} kept as they are (URL() would
    // encode them)
    function absolute(url) {
        if (/^https?:\/\//.test(url)) return url;
        var origin = root.location && root.location.origin ? root.location.origin : "";
        return origin + (url.charAt(0) === "/" ? "" : "/") + url;
    }

    // opts: {map, panel (layers_panel.js's), fetch, api, csrf, storage (localStorage or null), routeKey (the route's id,
    //        null for a route not saved yet), before() (the layer the orthophoto goes under), onSurface({id, v, bounds} |
    //        null), setTimeout, clearTimeout, now()}
    // Returns {list(bounds) (the tasks over the route, again), choose(id | null), setDsm(on), setOrthophoto(on),
    //          state(), restore()}
    function createTaskLayers(opts) {
        var map = opts.map, panel = opts.panel, fetchFn = opts.fetch;
        var later = opts.setTimeout || setTimeout.bind(root), cancel = opts.clearTimeout || clearTimeout.bind(root);
        var now = opts.now || function () { return Date.now(); };
        var tasks = [], chosen = read(), timer = null, generation = 0, orthoGeneration = 0, listed = null;

        function read() {
            var out = {task: null, dsm: true, orthophoto: true};
            if (!opts.storage || !opts.routeKey) return out;
            try {
                var v = JSON.parse(opts.storage.getItem(KEY + opts.routeKey) || "null");
                if (v && typeof v === "object") {
                    out.task = typeof v.task === "string" ? v.task : null;
                    out.dsm = v.dsm !== false;
                    out.orthophoto = v.orthophoto !== false;
                }
            } catch (e) { /* not remembered */ }
            return out;
        }
        function remember() {
            if (!opts.storage || !opts.routeKey) return;
            try { opts.storage.setItem(KEY + opts.routeKey, JSON.stringify(chosen)); } catch (e) { /* not remembered */ }
        }

        function current() {
            return tasks.filter(function (t) { return t.id === chosen.task; })[0] || null;
        }

        function stopPolling() {
            generation++;
            if (timer) { cancel(timer); timer = null; }
        }

        function setOrthophoto(task) {
            var mine = ++orthoGeneration;
            if (map.getLayer(ORTHO)) map.removeLayer(ORTHO);
            if (map.getSource(ORTHO)) map.removeSource(ORTHO);
            if (!task) return Promise.resolve();
            var url = "/api/projects/" + task.project + "/tasks/" + task.id + "/orthophoto/tiles.json";
            return fetchFn(url, {credentials: "same-origin"}).then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            }).then(function (tj) {
                if (mine !== orthoGeneration || map.getSource(ORTHO)) return;
                var source = {type: "raster", tileSize: 256, tiles: (tj.tiles || []).map(absolute),
                              attribution: "Orthophoto: " + (task.name || "WebODM task")};
                if (tj.bounds) source.bounds = tj.bounds;
                if (typeof tj.minzoom === "number") source.minzoom = Math.max(0, tj.minzoom);
                if (typeof tj.maxzoom === "number") source.maxzoom = Math.min(24, tj.maxzoom);
                map.addSource(ORTHO, source);
                map.addLayer({id: ORTHO, type: "raster", source: ORTHO}, opts.before ? opts.before() : undefined);
            }).catch(function () {
                if (mine === orthoGeneration) panel.setTaskNote("The task's orthophoto could not be shown");
            });
        }

        // The task's DSM: asks for its cut and polls until its tiles are there
        function surface(task) {
            stopPolling();
            if (!task) { opts.onSurface(null); return; }
            var mine = generation, started = now();
            function take(r) {
                return r.json().catch(function () { return {}; }).then(function (body) {
                    if (!r.ok) throw new Error(body.error || body.detail || ("HTTP " + r.status));
                    return body;
                });
            }
            function answer(body) {
                if (mine !== generation) return;
                panel.setTaskNote(surfaceNote(body));
                if (body.state === "done") { opts.onSurface({id: task.id, v: body.v, bounds: body.bounds}); return; }
                if (body.state === "failed") { opts.onSurface(null); return; }
                if (now() - started > POLL_DEADLINE_MS) {
                    panel.setTaskNote("The task's DSM was not ready within 10 minutes");
                    return;
                }
                timer = later(poll, POLL_MS);
            }
            function failed(e) {
                if (mine !== generation) return;
                panel.setTaskNote("The task's DSM could not be shown: " + e.message);
                opts.onSurface(null);
            }
            function poll() {
                timer = null;
                if (mine !== generation) return;
                fetchFn(opts.api + "task-surface?task=" + encodeURIComponent(task.id), {credentials: "same-origin"})
                    .then(take).then(answer, function () { if (mine === generation) timer = later(poll, POLL_MS); });
            }
            panel.setTaskNote("Preparing the task's DSM…");
            fetchFn(opts.api + "task-surface", {
                method: "POST", credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": opts.csrf}, body: JSON.stringify({task: task.id})
            }).then(take).then(answer, failed);
        }

        function controls() {
            var t = current();
            panel.setTasks(tasks, t ? t.id : null);
            panel.setTaskLayers({dsm: chosen.dsm, orthophoto: chosen.orthophoto, dsmEnabled: !!(t && t.dsm),
                                 orthophotoEnabled: !!(t && t.orthophoto)});
            return t;
        }
        function applyOrthophoto() {
            var t = controls();
            return setOrthophoto(t && t.orthophoto && chosen.orthophoto ? t : null);
        }
        function applyDsm() {
            var t = controls();
            panel.setTaskNote(t || tasks.length ? "" : "No processed task of yours over the route");
            surface(t && t.dsm && chosen.dsm ? t : null);
        }

        // Shows what is chosen: the panel's controls, the DSM and the orthophoto
        function apply() {
            applyDsm();
            return applyOrthophoto();
        }

        function list(bounds) {
            if (!bounds) return Promise.resolve();
            var key = bounds.join(",");
            if (key === listed) return Promise.resolve();
            listed = key;
            return fetchFn(opts.api + "task-surfaces?bounds=" + key, {credentials: "same-origin"})
                .then(function (r) { return r.ok ? r.json() : {tasks: []}; })
                .then(function (body) {
                    if (listed !== key) return;
                    var before = current();
                    tasks = body.tasks || [];
                    var after = current();
                    // the same task still there: nothing to redo
                    if (before && after && before.id === after.id) { panel.setTasks(tasks, after.id); return; }
                    return apply();
                })
                .catch(function () { listed = null; });
        }

        function choose(id) {
            chosen.task = id || null;
            if (id) { chosen.dsm = true; chosen.orthophoto = true; }
            remember();
            return apply();
        }

        return {
            list: list, choose: choose,
            setDsm: function (on) { chosen.dsm = !!on; remember(); applyDsm(); return Promise.resolve(); },
            setOrthophoto: function (on) { chosen.orthophoto = !!on; remember(); return applyOrthophoto(); },
            state: function () { return {task: chosen.task, dsm: chosen.dsm, orthophoto: chosen.orthophoto, tasks: tasks}; },
            restore: apply
        };
    }

    var api = {createTaskLayers: createTaskLayers, surfaceNote: surfaceNote, ORTHO: ORTHO, KEY: KEY, POLL_MS: POLL_MS};
    root.MissionPlannerTaskLayers = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
