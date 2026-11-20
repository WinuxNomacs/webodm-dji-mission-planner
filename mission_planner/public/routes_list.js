// The mission planner's landing page: the current user's saved routes, and the "New Route" dropdown. Plain DOM, no
// map library, so the row-rendering logic can be tested the same way route_form.js/planner_core.js are.
(function (root) {
    var ROUTE_TYPE_LABELS = {
        area: "Area Route", linear: "Linear Route", waypoint: "Waypoint Route", slope: "Slope Route", geometric: "Geometric Route"
    };

    function escapeHtml(t) { return String(t).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }

    // planner_core.js is loaded before this script in the page (and required under Jest) for the cameras' numbers
    var Core = root.MissionPlannerCore || (typeof require === "function" ? require("./planner_core") : null);
    // The aircraft's names in sentences (drones.json)
    var MODEL_NAMES = {};
    Object.keys(Core.DRONES).forEach(function (model) { MODEL_NAMES[model] = Core.DRONES[model].name; });

    // Whether the model is offered routes of the type (drones.json route_types: what its app's documents say it flies)
    function offersRouteType(model, routeType) {
        var drone = Core.DRONES[model];
        return !!drone && (!drone.route_types || drone.route_types.indexOf(routeType) !== -1);
    }
    // The New Route menu's entries and the route type each makes
    var NEW_ROUTE_TYPES = {"mp-new-area": "area", "mp-new-linear": "linear", "mp-new-waypoint": "waypoint", "mp-new-poi": "waypoint",
                           "mp-new-slope": "slope", "mp-new-geometric": "geometric"};

    // settings: the route's, to tell a POI route (a waypoint route with a shape) from a waypoint route
    function routeTypeLabel(type, settings) {
        if (type === "waypoint" && settings && settings.shape) return "POI Route";
        return ROUTE_TYPE_LABELS[type] || type;
    }

    // What copying a route ({model, settings}) for another aircraft model changes, as the copy dialog says it (the
    // server's copied_settings makes the copy)
    function copyNote(route, model) {
        if (model === route.model) return "An exact copy.";
        var s = route.settings || {};
        var height = parseFloat(s.height === undefined ? Core.DEFAULTS.height : s.height);
        var visible = String(s.lens_visible === undefined ? "true" : s.lens_visible) === "true";
        var cameras = Core.GSD_PER_M_BY_MODEL[model].ir !== undefined ? "The copy takes photos with the wide camera; the thermal camera can be turned on in it."
                                      : "The " + MODEL_NAMES[model] + " takes photos with its wide camera only.";
        var heightText;
        if (route.route_type === "waypoint") heightText = "A waypoint route's points are where to fly: the copy keeps their heights. ";
        else if (route.route_type === "linear" && String(s.single_line) === "true") heightText = "A single-line route's height comes from the strip's width: the copy keeps it. ";
        else if (!isFinite(height)) heightText = "";
        else if (!visible) heightText = "This route takes thermal photos only: the copy keeps its height (" + Core.roundTo(height, 2) + " m). ";
        else heightText = "Height " + Core.roundTo(height, 2) + " m → " + Core.roundTo(Core.copiedHeight(height, route.model, model), 2) +
                          " m, to keep " + Core.roundTo(Core.gsdCm("visable", height, route.model), 2) + " cm/pixel on the wide camera. ";
        return heightText + cameras + " Everything else (overlap, direction, speed and so on) is copied as it is.";
    }

    var HEIGHT_MODES = {agl: "above the ground (AGL)", alt: "above the takeoff point (ALT)", asl: "above the takeoff ground, flown above sea level (ASL)"};

    // What an imported route ({route_type, model, settings}) flies, as [label, text] rows for the import dialog
    function importSummary(route) {
        var type = route.route_type, waypoint = type === "waypoint";
        var s = Object.assign({}, waypoint ? Core.WAYPOINT_DEFAULTS : Core.DEFAULTS, type === "linear" ? Core.LINEAR_DEFAULTS : {}, route.settings || {});
        var cameras = [s.lens_visible === "true" ? "wide" : "", s.lens_ir === "true" ? "thermal" : ""].filter(Boolean).join(" + ");
        var oblique = s.collection_mode === "oblique", slope = type === "slope", geometric = type === "geometric";
        var typeText = slope ? "Slope, " + (s.corners || []).length + " corners"
            : geometric ? "Geometric, " + (s.outline || []).length + " corners, " + Core.roundTo(Number(s.top) - Number(s.base), 1) + " m high" +
                          (s.roof === "false" ? ", walls only" : ", roof and walls")
            : waypoint ? (s.shape ? "POI, " : "Waypoint, ") + (s.points || []).length + " points"
            : type === "linear" ? "Linear, " + (s.line || []).length + " points, " +
                                  (String(s.single_line) === "true" ? "one line" : "strip " + s.left_extend + " m left, " + s.right_extend + " m right")
            : oblique ? "Oblique, gimbal at " + s.gimbal_pitch + "°" : "Ortho";
        var mode = waypoint ? s.height_mode : s.altitude_mode;
        var rows = [
            ["Aircraft", (MODEL_NAMES[route.model] || route.model) + ", " + cameras + (cameras.indexOf("+") >= 0 ? " cameras" : " camera")],
            ["Type", typeText],
            ["Height", s.height + " m " + (slope ? "from the face" : geometric ? "from the walls" : HEIGHT_MODES[mode] || mode)]
        ];
        if (!waypoint) rows.push(["Overlap", s.overlap_h + "% forward, " + s.overlap_w + "% side"]);
        if (oblique) rows.push(["Oblique", (s.inclined_overlap_h || s.overlap_h) + "% forward, " + (s.inclined_overlap_w || s.overlap_w) + "% side"]);
        return rows;
    }

    function formatUpdated(iso) {
        var d = new Date(iso);
        return isNaN(d.getTime()) ? "" : d.toLocaleString();
    }

    // One <tr>'s markup for a route, given a route object from the API ({id, name, route_type, updated_at, ...})
    // and the plugin's public URL prefix (to link to its editor).
    function routeRow(route, publicUrl) {
        var href = publicUrl + "route/" + route.id;
        return "<tr>" +
            '<td><a href="' + href + '">' + escapeHtml(route.name || "(untitled)") + "</a></td>" +
            "<td>" + escapeHtml(routeTypeLabel(route.route_type, route.settings)) + "</td>" +
            "<td>" + escapeHtml(formatUpdated(route.updated_at)) + "</td>" +
            '<td><a href="javascript:void(0);" class="mp-route-rename" data-id="' + route.id + '" title="Rename"><i class="fa fa-pencil-alt"></i></a>' +
            '<a href="javascript:void(0);" class="mp-route-copy" data-id="' + route.id + '" title="Copy"><i class="fa fa-copy"></i></a>' +
            '<a href="javascript:void(0);" class="mp-route-delete" data-id="' + route.id + '" title="Delete"><i class="fa fa-trash"></i></a></td>' +
            "</tr>";
    }

    function init(doc, fetchFn, navigate) {
        // navigate(url) opens a page (tests pass their own: jsdom cannot change window.location)
        navigate = navigate || function (url) { window.location.href = url; };
        var root = doc.getElementById("mp-routes");
        if (!root) return;

        var API = root.getAttribute("data-api");
        var publicUrl = root.getAttribute("data-public");
        var csrf = (root.querySelector("input[name=csrfmiddlewaretoken]") || {}).value;
        var table = doc.getElementById("mp-routes-table");
        var body = doc.getElementById("mp-routes-body");
        var message = doc.getElementById("mp-routes-message");
        var copyDialog = doc.getElementById("mp-copy-dialog");
        var copyName = doc.getElementById("mp-copy-name");
        var copyModel = doc.getElementById("mp-copy-model");
        var copyNoteText = doc.getElementById("mp-copy-note");
        var importFile = doc.getElementById("mp-import-file");
        var importDialog = doc.getElementById("mp-import-dialog");

        var routes = [];       // the last list loaded, so Copy can look up a route's own settings/model without a round-trip
        var copySource = null;

        function render(loaded) {
            routes = loaded;
            if (!loaded.length) {
                table.hidden = true;
                message.textContent = "No routes yet. Use New Route to plan your first mission.";
                return;
            }
            message.textContent = "";
            table.hidden = false;
            body.innerHTML = loaded.map(function (r) { return routeRow(r, publicUrl); }).join("");
            [].forEach.call(body.querySelectorAll(".mp-route-delete"), function (a) {
                a.addEventListener("click", function () { deleteRoute(a.getAttribute("data-id")); });
            });
            [].forEach.call(body.querySelectorAll(".mp-route-copy"), function (a) {
                a.addEventListener("click", function () { openCopyDialog(a.getAttribute("data-id")); });
            });
            [].forEach.call(body.querySelectorAll(".mp-route-rename"), function (a) {
                a.addEventListener("click", function () { renameRoute(a.getAttribute("data-id")); });
            });
        }

        function load() {
            message.textContent = "Loading…";
            fetchFn(API + "routes", {credentials: "same-origin"})
                .then(function (res) { return res.json(); })
                .then(render)
                .catch(function () { message.textContent = "Could not load your routes."; });
        }

        function deleteRoute(id) {
            if (!window.confirm("Delete this route? This cannot be undone.")) return;
            fetchFn(API + "routes/" + id, {method: "DELETE", credentials: "same-origin", headers: {"X-CSRFToken": csrf}})
                .then(function (res) {
                    if (res.ok || res.status === 404) { load(); return; }       // 404: already gone (another tab)
                    message.textContent = "Could not delete the route (" + (res.status === 403 ? "your session has expired: reload the page" : "error " + res.status) + ").";
                })
                .catch(function () { message.textContent = "Could not delete the route."; });
        }

        function renameRoute(id) {
            var found = routes.filter(function (r) { return String(r.id) === String(id); });
            if (!found.length) return;
            var name = window.prompt("Rename route:", found[0].name || "");
            if (name === null) return;         // cancelled
            name = name.trim();
            if (!name || name === found[0].name) return;
            fetchFn(API + "routes/" + id, {method: "PATCH", credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrf}, body: JSON.stringify({name: name})
            }).then(function (res) { return res.ok ? load() : (message.textContent = "Could not rename the route."); })
              .catch(function () { message.textContent = "Could not rename the route."; });
        }

        function openCopyDialog(id) {
            var found = routes.filter(function (r) { return String(r.id) === String(id); });
            if (!found.length) return;
            copySource = found[0];
            copyName.textContent = copySource.name || "(untitled)";
            // only the models offered the route's type
            [].forEach.call(copyModel.options, function (o) { o.disabled = !offersRouteType(o.value, copySource.route_type); });
            copyModel.value = copySource.model;    // defaults to an exact copy; the user picks a different model to change it
            showCopyNote();
            copyDialog.hidden = false;
        }

        function showCopyNote() { if (copySource) copyNoteText.textContent = copyNote(copySource, copyModel.value); }
        copyModel.addEventListener("change", showCopyNote);

        function closeCopyDialog() {
            copyDialog.hidden = true;
            copySource = null;
        }

        doc.getElementById("mp-copy-cancel").addEventListener("click", closeCopyDialog);
        copyDialog.addEventListener("click", function (e) { if (e.target === copyDialog) closeCopyDialog(); });

        doc.getElementById("mp-copy-confirm").addEventListener("click", function () {
            if (!copySource) return;
            var id = copySource.id, model = copyModel.value;
            closeCopyDialog();
            fetchFn(API + "routes/" + id + "/copy", {method: "POST", credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrf}, body: JSON.stringify({model: model})
            }).then(function (res) { return res.json().then(function (data) { return {ok: res.ok, data: data}; }); })
              .then(function (r) {
                  if (!r.ok) { message.textContent = "Could not copy the route." + (r.data && r.data.model ? " " + r.data.model : ""); return; }
                  navigate(publicUrl + "route/" + r.data.id);
              }).catch(function () { message.textContent = "Could not copy the route."; });
        });

        // The New Route menu offers only the route types of the chosen model
        var newModel = doc.getElementById("mp-new-model");
        function showNewRouteTypes() {
            Object.keys(NEW_ROUTE_TYPES).forEach(function (id) {
                var entry = doc.getElementById(id);
                (entry.closest("li") || entry).hidden = !offersRouteType(newModel.value, NEW_ROUTE_TYPES[id]);
            });
        }
        newModel.addEventListener("change", showNewRouteTypes);
        showNewRouteTypes();

        // A new route of the type, named by the user, opened in its editor; settings: the new route's, if any
        function newRoute(routeType, defaultName, settings) {
            var name = window.prompt("Name this route:", defaultName);
            if (name === null) return;         // cancelled
            name = name.trim() || defaultName;
            var model = doc.getElementById("mp-new-model").value;
            fetchFn(API + "routes", {method: "POST", credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrf},
                body: JSON.stringify(Object.assign({name: name, route_type: routeType, model: model}, settings ? {settings: settings} : {}))
            }).then(function (res) { return res.json().then(function (data) { return {ok: res.ok, data: data}; }); })
              .then(function (r) {
                  if (!r.ok) { message.textContent = "Could not create the route."; return; }
                  navigate(publicUrl + "route/" + r.data.id);
              }).catch(function () { message.textContent = "Could not create the route."; });
        }
        doc.getElementById("mp-new-area").addEventListener("click", function () { newRoute("area", "New area route"); });
        doc.getElementById("mp-new-linear").addEventListener("click", function () { newRoute("linear", "New linear route"); });
        doc.getElementById("mp-new-slope").addEventListener("click", function () { newRoute("slope", "New slope route"); });
        doc.getElementById("mp-new-geometric").addEventListener("click", function () { newRoute("geometric", "New geometric route"); });
        doc.getElementById("mp-new-waypoint").addEventListener("click", function () { newRoute("waypoint", "New waypoint route"); });
        // a POI route: a waypoint route around a subject, facing it, in smooth curves at a height above the ground
        doc.getElementById("mp-new-poi").addEventListener("click", function () {
            newRoute("waypoint", "New POI route", {shape: Object.assign({}, Core.SHAPE_DEFAULTS), heading_mode: "towardPOI",
                                                   turn_mode: "curve", height_mode: "agl"});
        });

        var imported = null;

        doc.getElementById("mp-import-kmz").addEventListener("click", function () { importFile.click(); });

        importFile.addEventListener("change", function () {
            var file = importFile.files[0];
            importFile.value = "";             // so choosing the same file again is a change too
            if (!file) return;
            var form = new FormData();
            form.append("file", file);
            form.append("model", doc.getElementById("mp-new-model").value);    // the aircraft of a plain KML's route
            message.textContent = "Importing " + file.name + "…";
            fetchFn(API + "routes/import", {method: "POST", credentials: "same-origin", headers: {"X-CSRFToken": csrf}, body: form})
                .then(function (res) { return res.json().then(function (data) { return {ok: res.ok, data: data}; }); })
                .then(function (r) {
                    if (!r.ok) { message.textContent = "Could not import " + file.name + ": " + (r.data.error || "the server refused it") + "."; return; }
                    message.textContent = "";
                    showImported(r.data);
                }).catch(function () { message.textContent = "Could not import " + file.name + "."; });
        });

        function showImported(route) {
            imported = route;
            doc.getElementById("mp-import-name").textContent = route.name;
            doc.getElementById("mp-import-summary").innerHTML = importSummary(route).map(function (row) {
                return "<dt>" + escapeHtml(row[0]) + "</dt><dd>" + escapeHtml(row[1]) + "</dd>";
            }).join("");
            importDialog.hidden = false;
        }

        // The route is already saved: closing the dialog shows it in the list instead of opening it
        function closeImportDialog() {
            importDialog.hidden = true;
            imported = null;
            load();
        }

        doc.getElementById("mp-import-close").addEventListener("click", closeImportDialog);
        importDialog.addEventListener("click", function (e) { if (e.target === importDialog) closeImportDialog(); });
        doc.getElementById("mp-import-open").addEventListener("click", function () {
            if (imported) navigate(publicUrl + "route/" + imported.id);
        });

        load();
    }

    var api = {offersRouteType: offersRouteType, copyNote: copyNote, importSummary: importSummary, routeTypeLabel: routeTypeLabel, formatUpdated: formatUpdated, routeRow: routeRow, init: init};
    root.MissionPlannerRoutesList = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});

if (typeof window !== "undefined" && window.document && window.fetch) {
    window.MissionPlannerRoutesList.init(document, window.fetch.bind(window));
}
