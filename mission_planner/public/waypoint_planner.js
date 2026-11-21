// The editor of a waypoint route: the points clicked on the map, in the order they are flown, the route's form, the
// selected point's panel, and the plan the server makes of them. As planner.js does for an area; the logic that needs
// no map is in planner_core.js and the forms are in waypoint_form.js.
(function () {
    var Core = window.MissionPlannerCore;
    var root = document.getElementById("mission-planner");
    if (!root) return;

    var API = root.getAttribute("data-api");
    var routeId = root.getAttribute("data-route-id");
    var csrf = (root.querySelector("input[name=csrfmiddlewaretoken]") || {}).value;
    var els = {
        errors: document.getElementById("mp-errors"), results: document.getElementById("mp-results"),
        warnings: document.getElementById("mp-warnings"), download: document.getElementById("mp-download"),
        downloadKml: document.getElementById("mp-download-kml"),
        pointsMessage: document.getElementById("mp-points-message"), pointForm: document.getElementById("mp-point-form"),
        pointTitle: document.getElementById("mp-point-title"), pointErrors: document.getElementById("mp-point-errors"),
        pointInsert: document.getElementById("mp-point-insert"), groundRow: document.getElementById("mp-ground-row"),
        groundStatus: document.getElementById("mp-ground-status"), fetchGrounds: document.getElementById("mp-fetch-grounds")
    };

    // points: [{lat, lon, height, heading, pitch, photo, hover, ground}] (see Core.newPoint); selected: the index of the
    // point in the panel, or null; poi: [lat, lon] the aircraft faces on a Toward POI route, or null. A POI route
    // (settings.shape) also has its subject's drawn outline ([[lon, lat], ...]), whether its points were edited by hand
    // since they were made, the outline being drawn (or null) and the shape the points were last made from
    var state = {points: [], selected: null, takeoff: null, poi: null, picking: false, planTimer: null, planRequest: 0,
                 view3d: false, basemap: null, fetchingGrounds: false, outline: [], edited: false, drawing: null, madeFrom: null,
                 tool: "pointer"};

    function escapeHtml(t) { return String(t).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }

    // -- forms --------------------------------------------------------------------------------------------------------

    // The form's callbacks fire for real user edits only (write() sets values without events), as in planner.js
    function onFormChange() { setDirty(true); marginChanged(); terrainSourceChanged(); showGroundStatus(); showPoi(); shapeChanged(); if (isPoiRoute) showLoopsHint(); aslModeChanged(); schedulePlan(); }
    // A changed collision margin checks the route against the surface again (the plan itself does not change)
    function marginChanged() { if (route3d && checkedMargin !== null && collisionMargin() !== checkedMargin) route3d.refresh(); }

    var routeModel = "m4t";
    try { routeModel = JSON.parse(document.getElementById("mp-route-model").textContent) || "m4t"; } catch (e) { routeModel = "m4t"; }
    var form = window.MissionPlannerWaypointForm.createWaypointForm(document, Core, onFormChange, routeModel, onPointChange);

    var savedSettings = {};
    try { savedSettings = JSON.parse(document.getElementById("mp-route-settings").textContent) || {}; } catch (e) { savedSettings = {}; }
    var isPoiRoute = !!savedSettings.shape;

    function loadForm() {
        var name;
        try { name = JSON.parse(document.getElementById("mp-route-name").textContent) || ""; } catch (e) { name = ""; }
        form.write(Object.assign({}, Core.WAYPOINT_DEFAULTS, {name: name}, savedSettings));
        if (isPoiRoute) {
            var shape = Object.assign({}, Core.SHAPE_DEFAULTS, savedSettings.shape);
            form.writeShape(shape);
            state.outline = shape.outline || [];
            state.edited = !!shape.edited;
            state.madeFrom = shapeKey();
        }
    }

    function heightMode() { return form.read().height_mode; }

    // -- saving (only on Save, as in planner.js) ---------------------------------------------------------------------

    var saveButton = document.getElementById("mp-save-button"), saveStatus = document.getElementById("mp-save-status");
    function saveToServer() {
        var values = form.read();
        var settings = Object.assign({}, values, {takeoff: state.takeoff, points: state.points, poi: state.poi});
        if (isPoiRoute) settings.shape = currentShape();
        return fetch(API + "routes/" + routeId, {method: "PATCH", credentials: "same-origin",
            headers: {"Content-Type": "application/json", "X-CSRFToken": csrf}, body: JSON.stringify({name: values.name, settings: settings})
        }).then(function (res) { if (!res.ok) throw new Error("save failed"); });
    }

    // Saving, as both editors do it (planner_core.js createSaver): an edit made during a save stays unsaved
    var saver = Core.createSaver(saveButton, saveStatus, saveToServer, function () { return !!routeId; });
    var setDirty = saver.setDirty, save = saver.save;

    saveButton.addEventListener("click", save);

    // -- server ------------------------------------------------------------------------------------------------------

    function post(path, body) {
        return fetch(API + path, {method: "POST", credentials: "same-origin",
                                  headers: {"Content-Type": "application/json", "X-CSRFToken": csrf}, body: JSON.stringify(body)});
    }

    var bar = {points: document.getElementById("mp-sum-points"), length: document.getElementById("mp-sum-length"),
               time: document.getElementById("mp-sum-time"), photos: document.getElementById("mp-sum-photos")};

    function showBar(summary) {
        bar.points.textContent = String(state.points.length);
        bar.length.textContent = summary ? Core.formatDistance(summary.length) : "–";
        bar.time.textContent = summary ? Core.formatDuration(summary.duration) : "–";
        bar.photos.textContent = summary ? String(summary.photos) : "–";
    }

    function showResults(result) {
        showBar(result.summary);
        els.results.innerHTML = "<table>" + Core.waypointSummaryRows(result.summary).map(function (r) {
            return "<tr><td>" + escapeHtml(r.label) + "</td><td>" + escapeHtml(r.value) + "</td></tr>";
        }).join("") + "</table>";
        els.warnings.innerHTML = (result.warnings || []).map(function (w) { return '<div class="alert alert-warning">' + escapeHtml(w) + "</div>"; }).join("");
    }

    function clearResults(message) {
        showBar(null);
        els.results.innerHTML = "";
        els.warnings.innerHTML = "";
        els.errors.textContent = message || "";
        els.download.disabled = true;
        els.downloadKml.disabled = true;
        setLines(null);
    }

    function schedulePlan() {
        clearTimeout(state.planTimer);
        state.planTimer = setTimeout(plan, 300);
    }

    function firstError(errors) { return Object.keys(errors).map(function (k) { return errors[k]; })[0]; }

    function plan() {
        ensurePoi();
        var values = form.read(), parsed = Core.parseWaypointForm(values);
        if (!parsed.ok) { clearResults(firstError(parsed.errors)); return; }
        var problem = Core.pointsError(state.points, parsed.values.height_mode);
        if (problem) { clearResults(problem); return; }
        var body = Core.waypointRequestBody(state.points, values, state.takeoff, routeModel, state.poi);
        if (!body) { clearResults(""); return; }

        var ticket = ++state.planRequest;
        post("plan", body).then(function (res) { return res.json().then(function (data) { return {ok: res.ok, data: data}; }); }).then(function (r) {
            if (ticket !== state.planRequest) return;        // a newer request is on its way
            if (!r.ok) { clearResults(r.data.error || "The plan could not be made"); return; }
            els.errors.textContent = "";
            showResults(r.data);
            setLines(r.data);
            els.download.disabled = false;
            els.downloadKml.disabled = false;
        }).catch(function () { if (ticket === state.planRequest) clearResults("Could not reach the server"); });
    }

    function exportMission() {
        if (state.exporting) return;           // a second click while the first download runs
        var body = Core.waypointRequestBody(state.points, form.read(), state.takeoff, routeModel, state.poi);
        if (!body) return;
        state.exporting = true;

        post("export", body).then(function (res) {
            if (!res.ok) return Core.failure(res, "The mission could not be exported");
            return res.blob().then(function (blob) {
                var link = document.createElement("a");
                link.href = URL.createObjectURL(blob);
                // the server's name: a DJI Fly route split into several missions comes as a .zip of them
                var named = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
                link.download = named ? named[1] : (body.name || "luxodm-waypoints").replace(/[^A-Za-z0-9._-]+/g, "_") + ".kmz";
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
            });
        }).catch(function (e) { els.errors.textContent = e.message; }).then(function () { state.exporting = false; });
    }

    // The route as plain KML (its shape and flight path, api.KmlView), saved as a file
    function downloadKml() {
        if (state.makingKml) return;           // a second click while the first download runs
        var body = Core.waypointRequestBody(state.points, form.read(), state.takeoff, routeModel, state.poi);
        if (!body) return;
        state.makingKml = true;
        if (routeId) body.route_id = parseInt(routeId, 10);     // AGL over the route's terrain: the path at its heights
        post("kml", body).then(function (res) {
            if (!res.ok) return Core.failure(res, "The KML could not be made");
            return res.blob().then(function (blob) {
                var link = document.createElement("a");
                link.href = URL.createObjectURL(blob);
                link.download = (body.name || "route").replace(/[^A-Za-z0-9._-]+/g, "_") + ".kml";
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
            });
        }).catch(function (e) { els.errors.textContent = e.message; }).then(function () { state.makingKml = false; });
    }

    // AGL needs the ground height under every point: the missing ones are fetched first
    function download() {
        if (heightMode() !== "agl") { exportMission(); return; }
        fetchGrounds().then(function (ok) { if (ok) exportMission(); });
    }

    // -- ground heights under the points, for the AGL height mode (app/missions/elevation.py) ------------------------

    function showGroundStatus() {
        els.groundRow.hidden = heightMode() !== "agl";
        if (els.groundRow.hidden || state.fetchingGrounds) return;
        var missing = Core.missingGrounds(state.points).length, total = state.points.length;
        els.fetchGrounds.disabled = !missing;
        els.groundStatus.textContent = !total ? "" : !missing ? "All points have their ground height"
            : missing + " of " + total + " points without a ground height yet (fetched before the download)";
    }

    // Another terrain chosen (the lidar surface or COP30): the points' ground heights came from the other one, so they
    // are fetched again (before the download, or with the button)
    function terrainSourceChanged() {
        var chosen = form.read().terrain_source;
        if (state.terrainSource !== undefined && chosen !== state.terrainSource && state.points.some(function (p) { return p.ground !== null && p.ground !== undefined; })) {
            state.points = state.points.map(function (p) { return Object.assign({}, p, {ground: null}); });
            showPoints();
        }
        state.terrainSource = chosen;
    }

    // Resolves to true when every point has its ground height. The points may change while the request runs: a ground
    // height is kept only for a point still where it was asked for. While the lidar units the terrain needs are built
    // (202), it waits, the progress in the status line and on the map's lidar bar.
    function fetchGrounds() {
        var missing = Core.missingGrounds(state.points);
        if (!missing.length) return Promise.resolve(true);
        if (!routeId) return Promise.resolve(false);
        // a fetch already running (the button, then Download): wait for it, then say whether every point has its height
        if (state.groundsFetch) return state.groundsFetch.then(function () { return Core.missingGrounds(state.points).length === 0; });
        var asked = missing.map(function (i) { return state.points[i]; });
        state.fetchingGrounds = true;
        els.fetchGrounds.disabled = true;
        els.groundStatus.textContent = "Fetching the ground heights of " + asked.length + " points…";

        function done(message) {
            state.fetchingGrounds = false;
            state.groundsFetch = null;
            showGroundStatus();
            if (message) els.errors.textContent = message;
        }

        var waited = false;
        state.groundsFetch = Core.fetchUntilBuilt(post, "routes/" + routeId + "/point-elevations",
                                    {points: asked.map(function (p) { return [p.lat, p.lon]; }), terrain_source: form.read().terrain_source || "lidar"},
                                    {onWait: function (d) {
                                        waited = true;
                                        els.groundStatus.textContent = Core.buildingText(d);
                                        lidarBar.show({busy: true, text: Core.buildingText(d)});
                                    }})
            .then(function (r) {
                if (waited) {
                    lidarBar.show(null);
                    if (lidarOn) lidar.refresh(lidarBounds());
                }
                if (!r.ok) { done(r.data.error || "The terrain service could not be reached"); return false; }
                var points = state.points;
                asked.forEach(function (p, k) {
                    var i = points.indexOf(p);
                    if (i !== -1) points = Core.updatePoint(points, i, {ground: r.data.elevations[k]});
                });
                state.points = points;
                setDirty(true);
                done("");
                return Core.missingGrounds(state.points).length === 0;
            })
            .catch(function () { done("Could not reach the server"); return false; });
        return state.groundsFetch;
    }
    els.fetchGrounds.addEventListener("click", function () { fetchGrounds(); });

    // -- map ----------------------------------------------------------------------------------------------------------

    var lastView;
    try { lastView = JSON.parse(window.localStorage.getItem("mission-planner:view") || "null"); } catch (e) { lastView = null; }

    var map = new maplibregl.Map({
        container: "mp-map",
        style: {version: 8, sources: {}, layers: []},
        center: (lastView && lastView.center) || [0, 20], zoom: (lastView && lastView.zoom) || 2
    });
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-right");
    map.addControl(new maplibregl.ScaleControl({unit: "metric"}), "bottom-left");
    map.on("moveend", function () {
        try { window.localStorage.setItem("mission-planner:view", JSON.stringify({center: map.getCenter().toArray(), zoom: map.getZoom()})); } catch (e) { /* ignore */ }
    });

    var EMPTY = {type: "FeatureCollection", features: []};

    // The flight the server planned (from the takeoff point when there is one), over the dashed line through the points
    function setLines(data) {
        var lines = map.getSource("mp-lines");
        if (lines) lines.setData(data ? data.lines : EMPTY);
        state.air = data && data.air ? data.air : null;
        if (lidarOn) lidar.ensure(routeBounds());       // the lidar surface around the route, from 2D too
        if (taskLayers) taskLayers.list(routeBounds());  // the user's tasks over it
        if (relief && reliefOn && state.view3d) relief.refresh(lidarBounds());     // the relief's colours round it
        if (route3d) route3d.setAir(state.air, takeoffLngLat());
        showDraped();
        showLabels();
    }

    function takeoffLngLat() { return state.takeoff ? [state.takeoff[1], state.takeoff[0]] : null; }

    // -- the route in the air in 3D (route_3d.js), the numbered markers lifted to it, and the height labels -------------

    var DRAPED = ["mp-lines", "mp-path"];
    var route3d = null;

    // The side panel's line about where the route goes into the surface (2D and 3D)
    // The route's collision margin (the form's, in meters): how close to the surface it may pass, above or beside
    function collisionMargin() { return Core.collisionMargin(form.read().collision_margin); }
    var shownCount = null, checkedMargin = null;
    function showCollisions(count) {
        shownCount = count;
        var el = document.getElementById("mp-collisions");
        if (!el) return;
        var said = count === null || count === undefined ? null : window.MissionPlannerRoute3d.collisionText(count, collisionMargin(), unitsSystem);
        el.hidden = !said;
        el.textContent = said ? said.text : "";
        el.classList.toggle("mp-hit", !!(said && said.hit));
    }
    function showDraped() {
        var visible = !(state.view3d && state.air) ? "visible" : "none";
        DRAPED.forEach(function (id) { if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible); });
    }

    // In 3D each marker is moved from its place on the ground up to its point in the air (a marker has no height)
    // (the point being dragged in the air is where the drag has it)
    function liftMarkers(project) {
        var resolved = route3d && route3d.resolved(), path = resolved && resolved.points[0];
        markers.forEach(function (m, i) {
            var p = state.view3d && path && path.length === markers.length ? path[i] : null;
            if (p && airDragging && airDragging.index === i) p = airDragging.at;
            var up = p && project(p[0], p[1], p[2]), ground = p && project(p[0], p[1], route3d.surfaceAt(p[0], p[1]) || 0);
            m.setOffset(up && ground ? [up.x - ground.x, up.y - ground.y] : [0, 0]);
        });
    }

    // Beside each numbered point, its height above the surface right under it; red below it
    var labelTicket = 0;
    function showLabels() {
        var ticket = ++labelTicket, air = state.air;
        var count = air && air.paths && air.paths[0] ? air.paths[0].length : 0;
        if (!air || count !== markers.length) { markers.forEach(function (m) { setLabel(m, null); }); return; }
        window.MissionPlannerRoute3d.labelHeights(air, heightReader.heightAt, takeoffLngLat()).then(function (heights) {
            if (ticket !== labelTicket || heights.length !== markers.length) return;
            markers.forEach(function (m, i) { setLabel(m, heights[i]); });
        });
    }

    function setLabel(marker, h) {
        var label = marker.getElement().querySelector(".mp-wp-height");
        if (!label) return;
        label.hidden = h === null || h === undefined || !isFinite(h);
        if (label.hidden) return;
        var f = window.MissionPlannerRoute3d.formatLabel(h, unitsSystem);
        label.textContent = f.text;
        label.classList.toggle("below", f.below);
        label.title = f.below ? "Below the surface under the point (trees, roofs or ground)" : "Height above the surface under the point";
    }

    function showPath() {
        var path = map.getSource("mp-path");
        if (!path) return;
        path.setData(state.points.length < 2 ? EMPTY : {type: "FeatureCollection", features: [{type: "Feature", properties: {},
            geometry: {type: "LineString", coordinates: state.points.map(function (p) { return [p.lon, p.lat]; })}}]});
    }

    // -- the points: numbered markers, dragged to move them, clicked to select them -------------------------------------

    var markers = [];

    // In 3D a numbered marker is dragged in the air: the point follows the pointer at its height (route_3d.js's
    // airDrag), not MapLibre's way (the point on the ground under the pointer, which the marker's lift would leave
    // behind). AGL points keep their height above the surface as they go; the others their height above sea level.
    var pointer = null, pressed = null, airDragging = null;
    map.on("mousedown", function (e) { pressed = e.point; });
    map.on("touchstart", function (e) { pressed = e.point; });
    map.on("mousemove", function (e) { pointer = e.point; });
    map.on("touchmove", function (e) { pointer = e.point; });

    function startAirDrag(i) {
        airDragging = null;
        var resolved = route3d && route3d.resolved(), path = resolved && resolved.points[0];
        if (!state.view3d || !pressed || !path || path.length !== markers.length) return;
        var at = path[i], heightAt = function () { return at[2]; };
        if (heightMode() === "agl") {
            var under = route3d.surfaceAt(at[0], at[1]);
            if (under === null) return;
            heightAt = function (lng, lat) { var s = route3d.surfaceAt(lng, lat); return s === null ? null : s + at[2] - under; };
        }
        var move = window.MissionPlannerRoute3d.airDrag(route3d, at, pressed, heightAt);
        if (move) airDragging = {index: i, move: move, at: at};
    }

    function airDrag(marker) {
        if (!airDragging || !pointer) return;
        var to = airDragging.move(pointer);
        if (to) airDragging.at = to;
        marker.setLngLat([airDragging.at[0], airDragging.at[1]]);    // above the horizon: where it last was
        liftMarkers(route3d.project);
    }

    // What a click on the map does now; in Pointer, that Add points is chosen first
    function showPointsMessage() {
        var n = state.points.length;
        var text = isPoiRoute && !state.poi ? "Click the subject on the map: the points are made around it."
            : isPoiRoute ? n + " points around the subject. Drag the first one to start elsewhere; click a point to change it."
            : !n ? "Click the map to add the points, in the order they are flown."
            : n === 1 ? "1 point. Click the map to add the next one."
            : n + " points. Click the map to add more, drag a point to move it, click it to change it.";
        els.pointsMessage.textContent = state.tool === "pointer" ? text.replace(/Click the (map|subject)/, "Choose Add points and click the $1") : text;
    }

    function showPoints() {
        markers.forEach(function (m) { m.remove(); });
        markers = state.points.map(function (p, i) {
            var div = document.createElement("div");
            div.className = "mp-wp-marker" + (i === state.selected ? " selected" : "") + (p.photo ? " photo" : "");
            div.textContent = String(i + 1);
            div.title = "Point " + (i + 1) + (p.photo ? " (photo)" : "");
            var label = document.createElement("span");
            label.className = "mp-wp-height";
            label.hidden = true;
            div.appendChild(label);
            var marker = new maplibregl.Marker({element: div, draggable: true}).setLngLat([p.lon, p.lat]).addTo(map);
            var dragged = false;
            marker.on("dragstart", function () { dragged = true; startAirDrag(i); });
            marker.on("drag", function () { airDrag(marker); });
            marker.on("dragend", function () {
                airDrag(marker);
                airDragging = null;
                var ll = marker.getLngLat();
                // the first point of a POI route not edited by hand (or the last, which closes the loop on top of it)
                // sets where the points start around the subject
                if (isPoiRoute && (i === 0 || i === state.points.length - 1) && !state.edited && state.poi) {
                    form.writeShape({start: String(Core.roundTo(Core.bearing([state.poi[1], state.poi[0]], [ll.lng, ll.lat]), 1))});
                    makePoints();
                    return;
                }
                state.points = Core.movePoint(state.points, i, Core.roundTo(ll.lat, 9), Core.roundTo(ll.lng, 9));
                pointsEdited();
                setDirty(true);
                showPath();
                showGroundStatus();
                schedulePlan();
            });
            div.addEventListener("click", function (e) {
                e.stopPropagation();
                if (dragged) { dragged = false; return; }      // the end of a drag is not a click
                select(i === state.selected ? null : i);
            });
            return marker;
        });
        showLabels();
        showPath();
        var n = state.points.length;
        bar.points.textContent = String(n);     // the rest of the bar waits for the plan
        showPointsMessage();
        showGroundStatus();
        showPoi();
    }

    // Shows the point in the panel (null: closes the panel)
    function select(i) {
        state.selected = i;
        els.pointForm.hidden = i === null;
        els.pointErrors.textContent = "";
        if (i !== null) {
            els.pointTitle.textContent = "Point " + (i + 1) + " of " + state.points.length;
            form.writePoint(state.points[i]);
            form.refresh();
            els.pointInsert.disabled = i >= state.points.length - 1;
        }
        showPoints();
    }

    // The points changed: shown again, with i selected (or none)
    function pointsChanged(points, i) {
        state.points = points;
        pointsEdited();
        setDirty(true);
        select(i);
        schedulePlan();
    }

    function onPointChange() {
        if (state.selected === null) return;
        var parsed = Core.parsePointForm(form.readPoint(), heightMode());
        els.pointErrors.textContent = parsed.ok ? "" : firstError(parsed.errors);
        if (!parsed.ok) return;
        state.points = Core.updatePoint(state.points, state.selected, parsed.values);
        pointsEdited();
        markers[state.selected].getElement().classList.toggle("photo", parsed.values.photo);
        setDirty(true);
        schedulePlan();
    }

    document.getElementById("mp-point-close").addEventListener("click", function () { select(null); });
    els.pointInsert.addEventListener("click", function () {
        var points = Core.insertAfter(state.points, state.selected);
        if (points) pointsChanged(points, state.selected + 1);
    });
    document.getElementById("mp-point-delete").addEventListener("click", function () {
        if (state.selected !== null) pointsChanged(Core.deletePoint(state.points, state.selected), null);
    });

    // -- the point of interest of a Toward POI route: a marker dragged to move it, first put in the middle of the points ---

    var poiRow = {text: document.getElementById("mp-poi-text"), center: document.getElementById("mp-poi-center")};
    var poiMarker = null;

    function towardPoi() { return form.read().heading_mode === "towardPOI"; }

    // A Toward POI route without a POI gets one in the middle of its points
    function ensurePoi() {
        if (state.poi || !towardPoi() || isPoiRoute) return;     // a POI route's POI is its subject's middle
        state.poi = Core.pointsCenter(state.points);
        if (state.poi) { setDirty(true); showPoi(); }
    }

    function showPoi() {
        var shown = (towardPoi() || isPoiRoute) && state.poi;
        poiRow.text.textContent = !towardPoi() ? "" : state.poi ? "POI " + state.poi[0].toFixed(6) + ", " + state.poi[1].toFixed(6)
            : isPoiRoute ? "Click the subject on the map to put the POI there." : "Add the points first: the POI starts in their middle.";
        poiRow.center.disabled = !state.points.length;
        poiRow.center.hidden = isPoiRoute;
        if (!shown) { if (poiMarker) { poiMarker.remove(); poiMarker = null; } return; }
        if (!poiMarker) {
            var div = document.createElement("div");
            div.className = "mp-poi-marker";
            div.title = "Point of interest: the aircraft faces it all the way (drag to move it)";
            div.addEventListener("click", function (e) { e.stopPropagation(); });
            poiMarker = new maplibregl.Marker({element: div, draggable: true}).setLngLat([state.poi[1], state.poi[0]]).addTo(map);
            poiMarker.on("dragend", function () {
                var ll = poiMarker.getLngLat(), from = state.poi;
                state.poi = [Core.roundTo(ll.lat, 9), Core.roundTo(ll.lng, 9)];
                setDirty(true);
                showPoi();
                if (isPoiRoute) {
                    // the subject moves with its POI, and the points around it
                    state.outline = Core.shiftOutline(state.outline, from, state.poi);
                    showShape();
                    if (!state.edited || window.confirm("Make the points around the subject again? The changes made to them by hand are lost.")) makePoints(true);
                }
                schedulePlan();
            });
        } else {
            poiMarker.setLngLat([state.poi[1], state.poi[0]]);
        }
    }

    poiRow.center.addEventListener("click", function () {
        var center = Core.pointsCenter(state.points);
        if (!center) return;
        state.poi = center;
        setDirty(true);
        showPoi();
        schedulePlan();
    });

    // -- a POI route: the points made around the subject at the POI (Core.poiShapePoints) ---------------------------------

    var shapeEls = {errors: document.getElementById("mp-shape-errors"), make: document.getElementById("mp-shape-make"),
                    draw: document.getElementById("mp-shape-draw"), finish: document.getElementById("mp-shape-finish"),
                    outlineText: document.getElementById("mp-shape-outline-text"), loopsHint: document.getElementById("mp-shape-loops-hint")};

    function currentShape() { return Object.assign(form.readShape(), {outline: state.outline, edited: state.edited}); }
    // What the points are made from: the shape, and with several loops the route's height (the lowest loop's)
    function shapeKey() {
        var shape = form.readShape(), key = Object.assign({}, shape, {outline: state.outline});
        if (parseFloat(shape.loops) > 1) {
            var values = form.read();
            Object.assign(key, {route_height: values.height, height_mode: values.height_mode, takeoff_altitude: values.takeoff_altitude});
        }
        return JSON.stringify(key);
    }

    function pointsEdited() { if (isPoiRoute) state.edited = true; }

    // The flight height above the subject's base: AGL and ALT are taken as from the ground at the subject, ASL less the
    // takeoff point's ground height (null when that is not known)
    function heightAboveSubject(values, loopHeight) {
        var height = loopHeight === undefined ? parseFloat(values.height) : loopHeight;
        if (!isFinite(height)) return null;
        if (values.height_mode !== "asl") return height;
        var ground = parseFloat(values.takeoff_altitude);
        return isFinite(ground) ? height - ground : null;
    }

    // Makes the points around the subject, with the gimbal pitch and photo spacing for it; after edits by hand only once
    // they are confirmed (ask)
    function makePoints(confirmed) {
        var shape = currentShape(), parsed = Core.parseShapeForm(shape);
        shapeEls.errors.textContent = parsed.ok ? "" : firstError(parsed.errors);
        showShape();
        if (!parsed.ok || !state.poi) return;
        if (state.edited && !confirmed && !window.confirm("Make the points around the subject again? The changes made to them by hand are lost.")) return;
        var points = Core.poiShapePoints(state.poi, shape);
        if (!points) return;
        var values = form.read(), route = Core.parseWaypointForm(values), s = parsed.values;
        var pitch = Core.poiPitch(heightAboveSubject(values), s.height, s.distance);
        if (s.loops > 1) {
            var low = parseFloat(values.height), refused = !isFinite(low) ? "Give the route's height: the lowest loop flies at it"
                : !(s.top > low) ? "The highest loop must be above the route's height, where the lowest loop flies" : null;
            // forgotten, so that going back to the form the points were made from makes them (and clears this) again
            if (refused) { shapeEls.errors.textContent = refused; state.madeFrom = null; return; }
            var heights = Core.poiLoopHeights(low, s.top, s.loops);
            var pitches = heights.map(function (h) { return Core.poiLoopPitch(heightAboveSubject(values, h), s.height, s.distance); });
            points = Core.stackLoops(points, heights, pitches);
            pitch = pitches[0];
        }
        var spacing = route.values.cameras ? Core.poiPhotoSpacing(route.values.cameras, s.distance, s.overlap, routeModel) : null;
        var update = {heading_mode: "towardPOI"};
        if (pitch !== null) update.gimbal_pitch = String(pitch);
        if (spacing !== null) { update.photo_interval_mode = "distance"; update.photo_interval = String(spacing); }
        form.write(update);
        state.madeFrom = shapeKey();
        pointsChanged(points, null);
        state.edited = false;
    }

    // A change of the form: the points follow the subject while they were not edited by hand
    function shapeChanged() {
        if (!isPoiRoute) return;
        var key = shapeKey();
        if (key === state.madeFrom) return;
        var parsed = Core.parseShapeForm(currentShape());
        shapeEls.errors.textContent = parsed.ok ? "" : firstError(parsed.errors);
        showShape();
        if (!parsed.ok) return;
        if (!state.edited) makePoints();
        else shapeEls.errors.textContent = "The subject changed: Make the points to make them around it again.";
    }

    // How many loops the overlap asks for, from the route's height to the highest loop's
    function showLoopsHint() {
        if (!shapeEls.loopsHint) return;
        var shape = form.readShape(), values = form.read(), route = Core.parseWaypointForm(values);
        var low = parseFloat(values.height), top = parseFloat(shape.top), distance = parseFloat(shape.distance), overlap = parseFloat(shape.overlap);
        var n = parseFloat(shape.loops) > 1 && route.values.cameras && isFinite(low) && top > low && isFinite(overlap)
            ? Core.poiSuggestedLoops(route.values.cameras, distance, overlap, low, top, routeModel) : null;
        shapeEls.loopsHint.textContent = n ? "For " + overlap + " % overlap between loops: " + n + " loops" : "";
    }

    // The subject on the map (or the outline being drawn)
    function showShape() {
        var source = map.getSource("mp-shape");
        if (!source || !isPoiRoute) return;
        if (state.drawing) {
            source.setData(state.drawing.length < 2 ? EMPTY : {type: "FeatureCollection", features: [{type: "Feature", properties: {},
                geometry: {type: "LineString", coordinates: state.drawing}}]});
        } else {
            var ring = Core.subjectRing(state.poi, currentShape());
            source.setData(!ring ? EMPTY : {type: "FeatureCollection", features: [{type: "Feature", properties: {},
                geometry: {type: "Polygon", coordinates: [ring]}}]});
        }
        if (shapeEls.outlineText) {
            shapeEls.outlineText.textContent = state.drawing ? state.drawing.length + " corners, click the next one"
                : state.outline.length ? state.outline.length + " corners" : "No outline yet";
        }
    }

    function draw(on) {
        state.drawing = on ? [] : null;
        shapeEls.draw.hidden = on;
        shapeEls.finish.hidden = !on;
        map.getCanvas().style.cursor = on ? "crosshair" : "";
        showShape();
    }

    if (isPoiRoute) {
        shapeEls.make.addEventListener("click", function () { makePoints(); });
        shapeEls.draw.addEventListener("click", function () { draw(true); });
        shapeEls.finish.addEventListener("click", function () {
            var drawn = state.drawing;
            draw(false);
            if (drawn.length < 3) { shapeEls.errors.textContent = "Click at least 3 corners of the subject"; return; }
            state.outline = drawn;
            state.poi = Core.outlineCenter(drawn);
            setDirty(true);
            showPoi();
            makePoints();
            schedulePlan();
        });
    }

    // -- layers: the basemaps of the project, and the 3D view ---------------------------------------------------------------

    var basemaps = [];
    try { basemaps = JSON.parse(document.getElementById("mp-basemaps").textContent) || []; } catch (e) { basemaps = []; }
    if (!basemaps.length) basemaps = [Core.OSM];
    var BASEMAP_KEY = "mission-planner:basemap";

    // The lidar surface of the 3D view (lidar_surface.js): on unless turned off in the layers panel, remembered per
    // browser like the basemap
    var LIDAR_KEY = "mission-planner:lidar";
    var lidarOn = true;
    try { lidarOn = window.localStorage.getItem(LIDAR_KEY) !== "off"; } catch (e) { /* on */ }
    // The 3D view's Relief (relief.js): off unless turned on in the layers panel, remembered per browser
    var RELIEF_KEY = "mission-planner:relief";
    var reliefOn = false, relief = null;
    try { reliefOn = window.localStorage.getItem(RELIEF_KEY) === "on"; } catch (e) { /* off */ }
    var TaskLayers = window.MissionPlannerTaskLayers, taskLayers = null, taskSurface = null;
    var lidarBar = window.MissionPlannerLidar.createStatusBar(document, map.getContainer());
    var lidar = window.MissionPlannerLidar.createLidarSurface({
        maplibregl: maplibregl, fetch: fetch.bind(window), api: API, csrf: csrf, onStatus: lidarBar.show, lidar: lidarOn,
        onTilesChanged: function (tiles) {
            var dem = map.getSource("mp-dem");
            if (dem && lidarOn && dem.setTiles) dem.setTiles(tiles);
            if (heightReader) heightReader.clear();     // the heights read from the tiles before are read again
            showLabels();                       // the surface under the points is the lidar's now
            if (route3d) route3d.refresh();
            if (relief && reliefOn && state.view3d) relief.refresh(lidarBounds());  // its colours from the lidar's heights
            measure.reread();
        }
    });

    // "Loading elevation…" on the status bar while the 3D view's ground loads and is drawn
    var elevationWatch = window.MissionPlannerLidar.watchElevation(map, lidarBar, "mp-dem", function () { return state.view3d; });

    // What the lidar surface is built around: the route (null when it has no place yet), else the middle of the map
    function routeBounds() {
        var points = state.points.map(function (p) { return [p.lon, p.lat]; });
        if (state.takeoff) points.push([state.takeoff[1], state.takeoff[0]]);
        if (state.poi) points.push([state.poi[1], state.poi[0]]);
        return window.MissionPlannerLidar.boundsOf(points);
    }
    function lidarBounds() {
        var b = routeBounds();
        if (b) return b;
        var c = map.getCenter();
        return [c.lng, c.lat, c.lng, c.lat];
    }

    // The 3D view's ground, with its hillshade: the lidar surface, or AWS's terrain tiles when it is off
    function showGround3d() {
        if (relief) relief.apply(false);        // its layer off the source before the source goes
        map.setTerrain(null);
        if (map.getLayer("mp-hillshade")) map.removeLayer("mp-hillshade");
        if (map.getSource("mp-dem")) map.removeSource("mp-dem");
        map.addSource("mp-dem", lidarOn || taskSurface ? lidar.source() : Core.TERRAIN_SOURCE);
        map.addLayer({id: "mp-hillshade", type: "hillshade", source: "mp-dem", paint: {"hillshade-exaggeration": 0.35}}, "mp-path");
        map.setTerrain({source: "mp-dem", exaggeration: 1});
        if (lidarOn) lidar.request(lidarBounds()); else lidar.stop();
        if (relief && reliefOn) relief.apply(true, lidarBounds());
    }

    // The height under the pointer (pointer_height.js), in 2D and 3D, read from the same tiles as the 3D view's ground
    var unitsSystem = "metric";
    var heightReader = window.MissionPlannerPointerHeight.createHeightReader({
        load: function (z, x, y) { return lidar.load({url: "mplidar://" + z + "/" + x + "/" + y}); },
        isBuilt: function (x, y) { return (lidarOn && lidar.isBuilt(x, y)) || lidar.hasTask(x, y); }
    });
    relief = window.MissionPlannerRelief.createRelief({map: map, heightsAt: heightReader.heightsAt});
    var pointerTip = window.MissionPlannerPointerHeight.createPointerTooltip(document, map.getContainer(), {
        heightAt: heightReader.heightAt, units: function () { return unitsSystem; },
        routeAt: function (point) { return route3d ? route3d.routeNear(point) : null; }
    });
    map.on("mousemove", function (e) { pointerTip.move(e.point, e.lngLat); });
    map.on("mouseout", pointerTip.hide);

    // The Pointer tool (measure.js): dots with their heights above sea level, read from the same tiles
    var measure = window.MissionPlannerMeasure.createMeasure({maplibregl: maplibregl, map: map, doc: document, before: "mp-takeoff",
                                                             heightAt: heightReader.heightAt, units: function () { return unitsSystem; }});

    // The toolbar: Pointer, or Add points (a click adds a point, or places a POI route's subject). Choosing the other
    // tool clears the Pointer's dots.
    function setTool(tool) {
        if (state.tool === "pointer" && tool !== "pointer") measure.clear();
        state.tool = tool;
        [].forEach.call(root.querySelectorAll("[data-tool]"), function (b) { b.classList.toggle("active", b.getAttribute("data-tool") === tool); });
        showPointsMessage();
    }
    [].forEach.call(root.querySelectorAll("[data-tool]"), function (b) {
        b.addEventListener("click", function () { setTool(b.getAttribute("data-tool")); });
    });

    function setRelief(on) {
        reliefOn = on;
        try { window.localStorage.setItem(RELIEF_KEY, on ? "on" : "off"); } catch (e) { /* not remembered */ }
        if (relief && state.view3d) relief.apply(on, lidarBounds());
    }

    function setLidar(on) {
        lidarOn = on;
        lidar.setLidar(on);
        try { window.localStorage.setItem(LIDAR_KEY, on ? "on" : "off"); } catch (e) { /* not remembered */ }
        if (state.view3d) showGround3d();
        else if (on) lidar.ensure(routeBounds());
        else lidar.stop();
        if (route3d) route3d.refresh();
        showLabels();
        measure.reread();
    }

    // The layer the basemap (and a task's orthophoto) goes under
    function underBasemap() {
        return map.getLayer("mp-relief") ? "mp-relief" : map.getLayer("mp-hillshade") ? "mp-hillshade" : (map.getLayer("mp-path") ? "mp-path" : undefined);
    }

    function applyBasemap(bm) {
        if (map.getLayer("mp-basemap")) map.removeLayer("mp-basemap");
        if (map.getSource("mp-basemap")) map.removeSource("mp-basemap");
        map.addSource("mp-basemap", Core.basemapSource(bm, window.location));
        map.addLayer({id: "mp-basemap", type: "raster", source: "mp-basemap"}, map.getLayer(TaskLayers.ORTHO) ? TaskLayers.ORTHO : underBasemap());
        if (relief) relief.basemapChanged();
        state.basemap = bm.label;
        layersPanel.setSelected(bm.label);
        try { window.localStorage.setItem(BASEMAP_KEY, bm.label); } catch (e) { /* not remembered */ }
    }

    // 3D: the ground is raised by the elevation tiles and the map tilted. Points are added and moved as in 2D: a click
    // adds one on the surface under the pointer, and a numbered marker is dragged in the air (startAirDrag).
    function setView3d(on) {
        state.view3d = on;
        layersPanel.setView3d(on);
        if (route3d) route3d.show(on);
        showDraped();
        if (!on) liftMarkers(function () { return null; });

        if (on) {
            showGround3d();
            map.easeTo({pitch: 60});
        } else {
            if (relief) relief.apply(false);
            map.setTerrain(null);
            if (map.getLayer("mp-hillshade")) map.removeLayer("mp-hillshade");
            map.easeTo({pitch: 0, bearing: 0});
            elevationWatch.check();
        }
    }

    var layersPanel = window.MissionPlannerLayers.createLayersPanel(document, {
        basemaps: basemaps, selected: null, view3d: false, lidar: lidarOn,
        onBasemap: function (label) {
            var chosen = basemaps.filter(function (b) { return b.label === label; })[0];
            if (chosen) applyBasemap(chosen);
        },
        onView3d: function (on) { if (on !== state.view3d) setView3d(on); },
        onLidar: setLidar, relief: reliefOn, onRelief: setRelief,
        tasks: true, onTask: function (id) { taskLayers.choose(id); }, onTaskDsm: function (on) { taskLayers.setDsm(on); },
        onTaskOrthophoto: function (on) { taskLayers.setOrthophoto(on); }
    });
    function LayersControl() {}
    LayersControl.prototype.onAdd = function () { return layersPanel.element; };
    LayersControl.prototype.onRemove = function () { if (layersPanel.element.parentNode) layersPanel.element.parentNode.removeChild(layersPanel.element); };
    map.addControl(new LayersControl(), "top-right");

    // One of the user's WebODM tasks over the route (task_layers.js), picked in Map layers: its DSM blended into the 3D
    // ground (lidar_surface.js), its orthophoto over the basemap
    taskLayers = TaskLayers.createTaskLayers({
        map: map, panel: layersPanel, fetch: fetch.bind(window), api: API, csrf: csrf, routeKey: routeId,
        storage: (function () { try { return window.localStorage; } catch (e) { return null; } })(),
        before: underBasemap,
        onSurface: function (s) {
            var had = !!taskSurface;
            taskSurface = s;
            lidar.setTask(s);
            if (state.view3d && !lidarOn && had !== !!s) showGround3d();     // the ground's source changes
        }
    });

    var searchPanel = window.MissionPlannerSearch.createSearchPanel(document, {
        preconnect: "https://photon.komoot.io",
        suggest: function (query) {
            var c = map.getCenter();
            return Core.suggestPlaces(fetch.bind(window), query, [c.lng, c.lat], Core.photonLanguage(window.navigator.language));
        },
        onPick: function (suggestion) { Core.showSuggestion(map, suggestion); },
        onSearch: function (query) {
            var coords = Core.parseCoordinates(query);
            if (coords) {
                map.flyTo({center: [coords[1], coords[0]], zoom: Math.max(map.getZoom(), 15)});
                return;
            }

            searchPanel.setLoading(true);
            fetch("https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=" + encodeURIComponent(query))
                .then(function (res) { return res.json(); })
                .then(function (results) {
                    searchPanel.setLoading(false);
                    if (!results || !results.length) { searchPanel.setError("No results found for that address."); return; }
                    map.flyTo({center: [parseFloat(results[0].lon), parseFloat(results[0].lat)], zoom: Math.max(map.getZoom(), 15)});
                })
                .catch(function () { searchPanel.setLoading(false); searchPanel.setError("Could not reach the address search service."); });
        }
    });
    function SearchControl() {}
    SearchControl.prototype.onAdd = function () { return searchPanel.element; };
    SearchControl.prototype.onRemove = function () { if (searchPanel.element.parentNode) searchPanel.element.parentNode.removeChild(searchPanel.element); };
    map.addControl(new SearchControl(), "top-right");

    // -- the takeoff point, picked on the map ---------------------------------------------------------------------------

    var takeoffButton = document.getElementById("mp-takeoff-button"), takeoffText = document.getElementById("mp-takeoff-text");
    var altitudeRow = document.getElementById("mp-takeoff-altitude-row");

    function showTakeoff() {
        var takeoff = map.getSource("mp-takeoff");
        if (takeoff) takeoff.setData(state.takeoff ? {type: "FeatureCollection", features: [{type: "Feature", properties: {},
            geometry: {type: "Point", coordinates: [state.takeoff[1], state.takeoff[0]]}}]} : EMPTY);
        takeoffText.textContent = state.picking ? "Click the takeoff point on the map"
            : state.takeoff ? "Takeoff point " + state.takeoff[0].toFixed(6) + ", " + state.takeoff[1].toFixed(6) + " (click to clear)" : "Reference takeoff point not set";
        altitudeRow.hidden = !state.takeoff;
        showAslHint();
    }

    function pick(on) {
        state.picking = on;
        map.getCanvas().style.cursor = on ? "crosshair" : "";
        showTakeoff();
    }

    takeoffButton.addEventListener("click", function () {
        if (state.takeoff) { state.takeoff = null; setDirty(true); showTakeoff(); schedulePlan(); return; }
        pick(!state.picking);
    });

    // A click on the map picks the takeoff point while it is being picked, draws a POI route's outline while it is drawn,
    // in Pointer puts a dot, and in Add points adds a point (in 3D, on the surface under the pointer: MapLibre's
    // position for a click follows the terrain)
    map.on("click", function (e) {
        var target = e.originalEvent && e.originalEvent.target;
        if (target && target.closest && target.closest(".mp-wp-marker, .mp-poi-marker")) return;
        if (state.picking) {
            state.takeoff = [e.lngLat.lat, e.lngLat.lng];
            setDirty(true);
            pick(false);
            aslAutoFetch();
            schedulePlan();
            return;
        }
        if (state.drawing) {
            state.drawing.push([Core.roundTo(e.lngLat.lng, 9), Core.roundTo(e.lngLat.lat, 9)]);
            showShape();
            return;
        }
        if (state.tool === "pointer") { measure.click(e); return; }
        if (isPoiRoute && !state.poi) {
            state.poi = [Core.roundTo(e.lngLat.lat, 9), Core.roundTo(e.lngLat.lng, 9)];
            setDirty(true);
            showPoi();
            makePoints();
            return;
        }
        var points = Core.addPoint(state.points, Core.roundTo(e.lngLat.lat, 9), Core.roundTo(e.lngLat.lng, 9));
        pointsChanged(points, points.length - 1);
    });

    // -- ground elevation at the takeoff point, for the ASL height mode (as in planner.js) ------------------------------

    var fetchButton = document.getElementById("mp-fetch-elevation"), elevationStatus = document.getElementById("mp-elevation-status");
    var elevationDialog = document.getElementById("mp-elevation-dialog"), elevationError = document.getElementById("mp-elevation-error");
    var elevationCancel = document.getElementById("mp-elevation-cancel"), elevationUseCached = document.getElementById("mp-elevation-use-cached"),
        elevationRetry = document.getElementById("mp-elevation-retry");

    var cachedElevation = null;

    function fillElevation(data) {
        cachedElevation = data;
        form.write({takeoff_altitude: String(data.orthometric), takeoff_ellipsoidal_height: String(data.ellipsoidal)});
        state.aslFailed = null;
        setDirty(true);
        showAslHint();
        schedulePlan();
    }

    function hideElevationDialog() { elevationDialog.hidden = true; }
    elevationDialog.addEventListener("click", function (e) { if (e.target === elevationDialog) hideElevationDialog(); });
    elevationCancel.addEventListener("click", hideElevationDialog);
    elevationUseCached.addEventListener("click", function () {
        hideElevationDialog();
        if (cachedElevation) fillElevation(cachedElevation);
    });
    elevationRetry.addEventListener("click", function () { hideElevationDialog(); fetchElevation(); });

    function showElevationFailure(message) {
        fetchButton.disabled = false;
        elevationStatus.textContent = "";
        elevationError.textContent = message;
        elevationUseCached.disabled = !cachedElevation;
        elevationDialog.hidden = false;
    }

    // auto: fetched without being asked (aslAutoFetch): a failure shows in the ASL hint, not in the dialog. The answer
    // for a takeoff point moved meanwhile is dropped. (As in planner.js.)
    function fetchElevation(auto) {
        if (!state.takeoff || !routeId) return;
        var at = state.takeoff.slice();
        fetchButton.disabled = true;
        elevationStatus.textContent = "Fetching…";
        state.elevationFetching = true;
        state.aslFailed = null;
        showAslHint();
        function done() {
            state.elevationFetching = false;
            fetchButton.disabled = false;
            elevationStatus.textContent = "";
            var moved = !state.takeoff || state.takeoff[0] !== at[0] || state.takeoff[1] !== at[1];
            if (moved) { showAslHint(); aslAutoFetch(); }
            return !moved;
        }
        function failed(message) {
            if (!done()) return;
            if (auto === true) { state.aslFailed = message; showAslHint(); } else { showAslHint(); showElevationFailure(message); }
        }
        post("routes/" + routeId + "/elevation", {lat: at[0], lon: at[1]})
            .then(function (res) { return res.json().then(function (data) { return {ok: res.ok, data: data}; }); })
            .then(function (r) {
                if (!r.ok) { failed(r.data.error || "The elevation service could not be reached"); return; }
                if (done()) fillElevation(r.data);
            })
            .catch(function () { failed("Could not reach the server"); });
    }
    fetchButton.addEventListener("click", function () { fetchElevation(false); });

    // -- ASL without the takeoff point's ground height (as in planner.js) -----------------------------------------------

    var aslHints = ["mp-asl-hint-takeoff", "mp-asl-hint-mode"].map(function (id) { return document.getElementById(id); }).filter(Boolean);

    function aslState() {
        var f = form.read();
        return {asl: f.height_mode === "asl", takeoff: !!state.takeoff, altitude: f.takeoff_altitude,
                ellipsoidal: f.takeoff_ellipsoidal_height, fetching: !!state.elevationFetching, failed: state.aslFailed || null};
    }

    function showAslHint() {
        if (!aslHints || !aslHints.length) return;
        var text = Core.aslHint(aslState());
        aslHints.forEach(function (el) { el.textContent = text; el.hidden = !text; });
    }

    function aslAutoFetch() {
        if (!aslHints || !aslHints.length) return;
        if (!Core.aslAutoFetch(aslState())) { showAslHint(); return; }
        var cached = Core.cachedElevationFor(cachedElevation, state.takeoff);
        if (cached) fillElevation(cached); else fetchElevation(true);
    }

    // Called on every form change: fetches when ASL has just been picked
    function aslModeChanged() {
        var mode = heightMode();
        var picked = mode === "asl" && state.altitudeMode !== "asl";
        state.altitudeMode = mode;
        if (picked) aslAutoFetch(); else showAslHint();      // (aslAutoFetch shows the hint when it does not fetch)
    }

    if (routeId) {
        fetch(API + "routes/" + routeId + "/elevation", {credentials: "same-origin"})
            .then(function (res) { return res.ok ? res.json() : null; })
            .then(function (data) { if (data) cachedElevation = data; })
            .catch(function () { /* ignore - "use cached" just starts disabled */ });
    }

    map.on("load", function () {
        var saved;
        try { saved = window.localStorage.getItem(BASEMAP_KEY); } catch (e) { saved = null; }
        applyBasemap(Core.chooseBasemap(basemaps, saved));

        map.addSource("mp-path", {type: "geojson", data: EMPTY});
        map.addSource("mp-lines", {type: "geojson", data: EMPTY});
        map.addSource("mp-takeoff", {type: "geojson", data: EMPTY});
        map.addSource("mp-shape", {type: "geojson", data: EMPTY});
        map.addLayer({id: "mp-shape-fill", type: "fill", source: "mp-shape", paint: {"fill-color": "#ff9800", "fill-opacity": 0.2}});
        map.addLayer({id: "mp-shape", type: "line", source: "mp-shape", paint: {"line-color": "#ff9800", "line-width": 2}});
        map.addLayer({id: "mp-path", type: "line", source: "mp-path", paint: {"line-color": "#555", "line-width": 1.5, "line-dasharray": [2, 2]}});
        map.addLayer({id: "mp-lines", type: "line", source: "mp-lines", paint: {"line-color": "#1e88e5", "line-width": 2}});
        map.addLayer({id: "mp-takeoff", type: "circle", source: "mp-takeoff", paint: {"circle-radius": 7, "circle-color": "#43a047", "circle-stroke-color": "#fff", "circle-stroke-width": 2}});
        route3d = window.MissionPlannerRoute3d.createRoute3d({maplibregl: maplibregl, map: map, id: "mp-route-3d", before: "mp-takeoff",
                                                             heightsAt: heightReader.heightsAt,
                                                             bandMaxes: heightReader.bandMaxes, margin: function () { checkedMargin = collisionMargin(); return checkedMargin; },
                                                             discs: false, onFrame: liftMarkers, onCollisions: showCollisions});

        restoreMapState();
    });

    // The points and takeoff saved on this route, with the map on the points rather than wherever this browser last
    // looked (an imported route is often elsewhere)
    function restoreMapState() {
        var points = (savedSettings.points || []).filter(function (p) { return p && isFinite(p.lat) && isFinite(p.lon); });
        state.points = points.map(function (p) { return Object.assign(Core.newPoint(p.lat, p.lon), p); });
        if (savedSettings.takeoff) state.takeoff = savedSettings.takeoff;
        if (savedSettings.poi && isFinite(savedSettings.poi[0]) && isFinite(savedSettings.poi[1])) state.poi = savedSettings.poi;
        showPoints();
        showTakeoff();
        showShape();
        var bounds = Core.pointsBounds(state.points);
        if (bounds) map.fitBounds(bounds, {padding: 60, maxZoom: 19, duration: 0});
        schedulePlan();
    }

    els.download.addEventListener("click", download);
    els.downloadKml.addEventListener("click", downloadKml);

    // -- units: a per-browser display preference, never sent to the server --------------------------------------------

    var UNITS_KEY = "mission-planner:units";

    function applyUnits(system) {
        unitsSystem = system;
        form.setUnits(system);
        showCollisions(shownCount);              // the margin in the chosen units
        showLabels();
        measure.relabel();
        [].forEach.call(root.querySelectorAll("[data-units]"), function (b) { b.classList.toggle("active", b.getAttribute("data-units") === system); });
    }

    [].forEach.call(root.querySelectorAll("[data-units]"), function (b) {
        b.addEventListener("click", function () {
            var system = b.getAttribute("data-units");
            applyUnits(system);
            try { window.localStorage.setItem(UNITS_KEY, system); } catch (e) { /* not remembered */ }
        });
    });

    var savedUnits;
    try { savedUnits = window.localStorage.getItem(UNITS_KEY); } catch (e) { savedUnits = null; }

    // -- leaving the page without saving (as in planner.js) ------------------------------------------------------------

    var backLink = document.getElementById("mp-back-link");
    var leaveDialog = document.getElementById("mp-leave-dialog");

    function hideLeaveDialog() { leaveDialog.hidden = true; }

    backLink.addEventListener("click", function (e) {
        if (!saver.isDirty()) return;
        e.preventDefault();
        leaveDialog.hidden = false;
    });
    leaveDialog.addEventListener("click", function (e) { if (e.target === leaveDialog) hideLeaveDialog(); });
    document.getElementById("mp-leave-discard").addEventListener("click", function () { window.location.href = backLink.href; });
    document.getElementById("mp-leave-save").addEventListener("click", function () {
        save().then(function () { if (!saver.isDirty()) window.location.href = backLink.href; });
    });

    window.addEventListener("beforeunload", function (e) {
        if (!saver.isDirty()) return;
        e.preventDefault();
        e.returnValue = "";
    });

    loadForm();
    state.altitudeMode = heightMode();
    state.terrainSource = form.read().terrain_source;
    showGroundStatus();
    if (isPoiRoute) showLoopsHint();
    if (savedUnits === "imperial") applyUnits("imperial");
    if (lidarOn) lidar.refresh(lidarBounds());              // the units already built, for the heights under the pointer
})();
