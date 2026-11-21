// The mission planner page: a map to draw the area (or a linear route's center line, a slope route's face or a geometric
// route's block) on, the form, and the plan the server makes of them. The logic that needs no map is in planner_core.js.
(function () {
    var Core = window.MissionPlannerCore;
    var root = document.getElementById("mission-planner");
    if (!root) return;

    var API = root.getAttribute("data-api");
    var routeId = root.getAttribute("data-route-id");
    var isLinear = root.getAttribute("data-route-type") === "linear";
    var isSlope = root.getAttribute("data-route-type") === "slope";
    var isGeometric = root.getAttribute("data-route-type") === "geometric";
    var csrf = (root.querySelector("input[name=csrfmiddlewaretoken]") || {}).value;
    var els = {
        errors: document.getElementById("mp-errors"), results: document.getElementById("mp-results"),
        warnings: document.getElementById("mp-warnings"), download: document.getElementById("mp-download"),
        downloadKml: document.getElementById("mp-download-kml"),
        areaMessage: document.getElementById("mp-area-message")
    };

    // heights: a slope route's corner heights, one per corner of area (null where it has none yet)
    var state = {area: null, heights: [], line: null, takeoff: null, routeStart: null, picking: null, planTimer: null, planRequest: 0, tool: "pointer", view3d: false, basemap: null};

    function escapeHtml(t) { return String(t).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }

    // -- form -------------------------------------------------------------------------------------------------------

    // routeForm's onChange fires for real user edits only (loadForm's write() below sets values directly, without
    // dispatching input/change events) - safe to mark the route dirty unconditionally here.
    function onFormChange() { setDirty(true); marginChanged(); showStrip(); aslModeChanged(); showTerrain(); schedulePlan(); }
    // A changed collision margin checks the route against the surface again (the plan itself does not change)
    function marginChanged() { if (route3d && checkedMargin !== null && collisionMargin() !== checkedMargin) route3d.refresh(); }
    // The route's aircraft model, rendered into the page like its settings: it sets the cameras and is sent with each
    // plan and export
    var routeModel = "m4t";
    try { routeModel = JSON.parse(document.getElementById("mp-route-model").textContent) || "m4t"; } catch (e) { routeModel = "m4t"; }
    var routeForm = window.MissionPlannerForm.createRouteForm(document, Core, onFormChange, routeModel);

    function readForm() { return routeForm.read(); }

    // The route's name/settings are rendered into the page (see plugin.py's route_editor), so loading the form and
    // the drawn area/takeoff/start (restored once the map is ready - see restoreMapState) need no extra round-trip.
    var savedSettings = {};
    try { savedSettings = JSON.parse(document.getElementById("mp-route-settings").textContent) || {}; } catch (e) { savedSettings = {}; }

    function loadForm() {
        var name;
        try { name = JSON.parse(document.getElementById("mp-route-name").textContent) || ""; } catch (e) { name = ""; }
        routeForm.write(Object.assign({}, Core.DEFAULTS, isLinear ? Core.LINEAR_DEFAULTS : isSlope ? Core.SLOPE_DEFAULTS
            : isGeometric ? Core.GEOMETRIC_DEFAULTS : {}, {name: name}, savedSettings));
    }

    // -- saving ---------------------------------------------------------------------------------------------------
    // No autosave: changes only reach the server when the user clicks Save (or chooses Save from the "leave without
    // saving" prompt below). setDirty tracks whether there is anything to save, and keeps the Save button/status in sync.

    var saveButton = document.getElementById("mp-save-button"), saveStatus = document.getElementById("mp-save-status");
    function saveToServer() {
        var form = readForm();
        var settings = Object.assign({}, form, isLinear ? {line: state.line, takeoff: state.takeoff}
            : isSlope ? {corners: (state.area || []).map(function (c, i) { return [c[0], c[1], state.heights[i]]; }), takeoff: state.takeoff}
            : isGeometric ? {outline: state.area, takeoff: state.takeoff}
            : {polygon: state.area, takeoff: state.takeoff, route_start: state.routeStart});
        return fetch(API + "routes/" + routeId, {method: "PATCH", credentials: "same-origin",
            headers: {"Content-Type": "application/json", "X-CSRFToken": csrf}, body: JSON.stringify({name: form.name, settings: settings})
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

    var bar = {area: document.getElementById("mp-sum-area"), length: document.getElementById("mp-sum-length"),
               time: document.getElementById("mp-sum-time"), photos: document.getElementById("mp-sum-photos")};

    function showBar(summary) {
        bar.area.textContent = !summary ? "\u2013" : isLinear ? Core.formatDistance(Core.lineLength(state.line))
            : isSlope ? Math.round(summary.slope) + "\u00b0" : isGeometric ? Core.roundTo(summary.top - summary.base, 1) + " m"
            : Core.formatArea(summary.area);
        bar.length.textContent = summary ? Core.formatDistance(summary.distance) : "\u2013";
        bar.time.textContent = summary ? Core.formatDuration(summary.duration) : "\u2013";
        bar.photos.textContent = summary ? String(summary.photos) : "\u2013";
    }

    function showResults(result) {
        showBar(result.summary);
        var rows = isLinear ? Core.linearSummaryRows : isSlope ? Core.slopeSummaryRows : isGeometric ? Core.geometricSummaryRows : Core.summaryRows;
        els.results.innerHTML = "<table>" + rows(result.summary).map(function (r) {
            return "<tr><td>" + escapeHtml(r.label) + "</td><td>" + escapeHtml(r.value) + "</td></tr>";
        }).join("") + "</table>";
        els.warnings.innerHTML = (result.warnings || []).map(function (w) { return '<div class="alert alert-warning">' + escapeHtml(w) + "</div>"; }).join("");
        showProfile(result.summary);
    }

    // A slope or geometric route's side view, and how far its heights are from sea level's
    function showProfile(summary) {
        var profile = document.getElementById("mp-profile");
        if (!profile) return;
        profile.hidden = !summary;
        document.getElementById("mp-profile-svg").innerHTML = summary ? Core.profileSvg(summary.profile, 320, 220) : "";
        if (summary && typeof summary.undulation === "number")
            document.getElementById("mp-undulation-note").textContent = " (here " + Math.abs(Core.roundTo(summary.undulation, 1)) + " m " +
                (summary.undulation < 0 ? "below" : "above") + " the heights above sea level)";
    }

    function clearResults(message) {
        showBar(null);
        els.results.innerHTML = "";
        els.warnings.innerHTML = "";
        els.errors.textContent = message || "";
        els.download.disabled = true;
        els.downloadKml.disabled = true;
        setLines(null);
        showProfile(null);
    }

    // Asks the server for the flight lines of the current area and form (after a pause in typing)
    function schedulePlan() {
        clearTimeout(state.planTimer);
        state.planTimer = setTimeout(plan, 300);
    }

    // The plan/export request of the drawn area or line and the form, or null when there is nothing to send yet
    function requestBody() {
        if (isSlope) return Core.slopeRequestBody(state.area, state.heights, readForm(), state.takeoff, routeModel);
        if (isGeometric) return Core.geometricRequestBody(state.area, readForm(), state.takeoff, routeModel);
        return isLinear ? Core.linearRequestBody(state.line, readForm(), state.takeoff, routeModel)
            : Core.requestBody(state.area, readForm(), state.takeoff, state.routeStart, routeModel);
    }

    function plan() {
        var parsed = isLinear ? Core.parseLinearForm(readForm(), routeModel) : isSlope ? Core.parseSlopeForm(readForm())
            : isGeometric ? Core.parseGeometricForm(readForm()) : Core.parseForm(readForm());
        if (!parsed.ok) { clearResults(Object.keys(parsed.errors).map(function (k) { return parsed.errors[k]; })[0]); return; }
        if (isSlope && state.area && Core.cornersError(state.area, state.heights)) { clearResults(Core.cornersError(state.area, state.heights)); return; }
        if (isGeometric && state.area && Core.outlineError(state.area)) { clearResults(Core.outlineError(state.area)); return; }
        var body = requestBody();
        if (!body) { clearResults(""); return; }
        if (routeId) body.route_id = parseInt(routeId, 10);     // AGL over the route's terrain: its heights in 3D

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

    // An AGL mission over the terrain model (oblique, or the terrain follow) embeds the route's terrain: the export
    // says when the route has none that covers the plan (409, needs_terrain), and it is fetched and the export tried
    // again
    function download(afterFetch) {
        if (state.exporting) return;           // a second click while the first download runs
        var body = requestBody();
        if (!body) return;
        state.exporting = true;
        if (routeId) body.route_id = parseInt(routeId, 10);
        if (readForm().terrain_source) body.terrain_source = readForm().terrain_source;   // the kept terrain must be made for it

        post("export", body).then(function (res) {
            if (res.status === 409) return res.json().then(function (d) {
                if (!d.needs_terrain || afterFetch === true) throw new Error(d.error || "The mission could not be exported");
                state.exporting = false;            // the export is tried again once the terrain is fetched
                fetchTerrain(function () { download(true); });
            });
            if (!res.ok) return Core.failure(res, "The mission could not be exported");
            return res.blob().then(function (blob) {
                var link = document.createElement("a");
                link.href = URL.createObjectURL(blob);
                // the server's name: a DJI Fly route split into several missions comes as a .zip of them
                var named = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
                link.download = named ? named[1] : (body.name || "luxodm-mission").replace(/[^A-Za-z0-9._-]+/g, "_") + ".kmz";
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
        var body = requestBody();
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

    // -- map ----------------------------------------------------------------------------------------------------------

    var lastView;
    try { lastView = JSON.parse(window.localStorage.getItem("mission-planner:view") || "null"); } catch (e) { lastView = null; }

    var map = new maplibregl.Map({
        container: "mp-map",
        style: {version: 8, sources: {}, layers: []},          // the basemap is added below, from the project's list
        center: (lastView && lastView.center) || [0, 20], zoom: (lastView && lastView.zoom) || 2
    });
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-right");
    map.addControl(new maplibregl.ScaleControl({unit: "metric"}), "bottom-left");
    map.on("moveend", function () {
        try { window.localStorage.setItem("mission-planner:view", JSON.stringify({center: map.getCenter().toArray(), zoom: map.getZoom()})); } catch (e) { /* ignore */ }
    });

    var EMPTY = {type: "FeatureCollection", features: []};

    function setLines(data) {
        var lines = map.getSource("mp-lines"), points = map.getSource("mp-waypoints");
        if (lines) lines.setData(data ? data.lines : EMPTY);
        if (points) points.setData(data ? data.waypoints : EMPTY);
        state.air = data && data.air ? data.air : null;
        if (lidarOn) lidar.ensure(routeBounds());       // the lidar surface around the route, from 2D too
        if (taskLayers) taskLayers.list(routeBounds());  // the user's tasks over it
        if (relief && reliefOn && state.view3d) relief.refresh(lidarBounds());     // the relief's colours round it
        if (route3d) route3d.setAir(state.air, state.takeoff ? [state.takeoff[1], state.takeoff[0]] : null);
        showDraped();
    }

    // The route in the air in 3D (route_3d.js); the lines on the ground stay in 2D, and in 3D when the plan has no
    // heights for it
    var DRAPED = ["mp-lines", "mp-lines-bend", "mp-lines-roof", "mp-waypoints"];
    var route3d = null;
    // The side panel's line about where the route goes into the surface (2D and 3D)
    // The route's collision margin (the form's, in meters): how close to the surface it may pass, above or beside
    function collisionMargin() { return Core.collisionMargin(readForm().collision_margin); }
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

    // The strip a linear route surveys, around its center line, as wide as the form says
    function showStrip() {
        var strip = map.getSource("mp-strip");
        if (!strip) return;
        var v = isLinear && state.line ? Core.parseLinearForm(readForm(), routeModel).values : {};
        var ring = v.left_extend !== undefined && v.right_extend !== undefined ? Core.stripPolygon(state.line, v.left_extend, v.right_extend) : null;
        strip.setData(ring ? {type: "FeatureCollection", features: [{type: "Feature", properties: {}, geometry: {type: "Polygon", coordinates: [ring]}}]} : EMPTY);
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
            if (route3d) route3d.refresh();     // the route checked against the lidar's surface now
            if (relief && reliefOn && state.view3d) relief.refresh(lidarBounds());  // its colours from the lidar's heights
            measure.reread();                   // and the Pointer tool's dots read from it
        }
    });

    // "Loading elevation…" on the status bar while the 3D view's ground loads and is drawn
    var elevationWatch = window.MissionPlannerLidar.watchElevation(map, lidarBar, "mp-dem", function () { return state.view3d; });

    // What the lidar surface is built around: the route (null when it has no place yet), else the middle of the map
    function routeBounds() {
        var points = (state.area || []).concat(state.line || []);
        if (state.takeoff) points.push([state.takeoff[1], state.takeoff[0]]);
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
        map.addLayer({id: "mp-hillshade", type: "hillshade", source: "mp-dem", paint: {"hillshade-exaggeration": 0.35}}, "mp-lines");
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
        measure.reread();
    }

    // The layer the basemap (and a task's orthophoto) goes under
    function underBasemap() {
        return map.getLayer("mp-relief") ? "mp-relief" : map.getLayer("mp-hillshade") ? "mp-hillshade" : (map.getLayer("mp-lines") ? "mp-lines" : undefined);
    }

    // Puts a basemap under everything else (the plan and the area are drawn above it)
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

    // 3D: the ground is raised by the elevation tiles and the map tilted. The tools work as in 2D: a click lands on
    // the surface under the pointer (terra-draw reads it with map.unproject, which follows the terrain), and the
    // shape stays laid on the surface.
    function setView3d(on) {
        state.view3d = on;
        layersPanel.setView3d(on);

        if (route3d) route3d.show(on);
        showDraped();
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

    // The layers button on the map, under the zoom buttons
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

    // The search button on the map, under the layers button: an address (suggested by Photon as one types, or geocoded
    // via Nominatim on Enter) or "latitude, longitude"
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

    // -- the takeoff point and the start of the route, picked on the map -----------------------------------------------------

    var takeoffButton = document.getElementById("mp-takeoff-button"), takeoffText = document.getElementById("mp-takeoff-text");
    var startButton = document.getElementById("mp-start-button"), startText = document.getElementById("mp-start-text");
    var altitudeRow = document.getElementById("mp-takeoff-altitude-row");

    function point(lng, lat) {
        return {type: "FeatureCollection", features: [{type: "Feature", properties: {}, geometry: {type: "Point", coordinates: [lng, lat]}}]};
    }

    function showPicked() {
        var takeoff = map.getSource("mp-takeoff"), start = map.getSource("mp-start");
        if (takeoff) takeoff.setData(state.takeoff ? point(state.takeoff[1], state.takeoff[0]) : EMPTY);
        if (start) start.setData(state.routeStart ? point(state.routeStart[0], state.routeStart[1]) : EMPTY);
        takeoffText.textContent = state.picking === "takeoff" ? "Click the takeoff point on the map"
            : state.takeoff ? "Takeoff point " + state.takeoff[0].toFixed(6) + ", " + state.takeoff[1].toFixed(6) + " (click to clear)" : "Reference takeoff point not set";
        if (startText) startText.textContent = state.picking === "start" ? "Click the start of the route on the map"
            : state.routeStart ? "Route starts at " + state.routeStart[1].toFixed(6) + ", " + state.routeStart[0].toFixed(6) + " (click to clear)" : "Set route start point";
        altitudeRow.hidden = !state.takeoff;
        showAslHint();
    }

    // While picking, drawing is paused: a click must not also add a corner of the area
    function pick(what) {
        if (state.picking === what) what = null;
        state.picking = what;
        map.getCanvas().style.cursor = what ? "crosshair" : "";
        if (draw) { if (what) draw.setMode("static"); else setTool(state.tool); }
        showPicked();
    }

    takeoffButton.addEventListener("click", function () {
        if (state.takeoff) { state.takeoff = null; setDirty(true); showPicked(); schedulePlan(); return; }
        pick("takeoff");
    });
    if (startButton) startButton.addEventListener("click", function () {
        if (state.routeStart) { state.routeStart = null; setDirty(true); showPicked(); schedulePlan(); return; }
        pick("start");
    });
    // A click picks the takeoff point or the route's start while one is being picked, else in Pointer puts a dot
    map.on("click", function (e) {
        if (!state.picking) { if (state.tool === "pointer") measure.click(e); return; }
        var takeoff = state.picking === "takeoff";
        if (takeoff) state.takeoff = [e.lngLat.lat, e.lngLat.lng]; else state.routeStart = [e.lngLat.lng, e.lngLat.lat];
        setDirty(true);
        pick(state.picking);               // done: back to drawing
        if (takeoff) aslAutoFetch();
        schedulePlan();
    });

    // -- ground elevation at the takeoff point, for the ASL height mode (app/missions/elevation.py) ---------------------

    var fetchButton = document.getElementById("mp-fetch-elevation"), elevationStatus = document.getElementById("mp-elevation-status");
    var failureDialog = document.getElementById("mp-elevation-dialog"), failureTitle = document.getElementById("mp-elevation-title"),
        failureError = document.getElementById("mp-elevation-error");
    var failureCancel = document.getElementById("mp-elevation-cancel"), failureUseCached = document.getElementById("mp-elevation-use-cached"),
        failureRetry = document.getElementById("mp-elevation-retry");

    // The dialog of a failed fetch, the takeoff elevation's or the terrain's: Retry calls retry, "Use cached values"
    // calls useCached (disabled when it is null)
    var failureActions = {};
    function hideFailure() { failureDialog.hidden = true; }
    failureDialog.addEventListener("click", function (e) { if (e.target === failureDialog) hideFailure(); });
    failureCancel.addEventListener("click", hideFailure);
    failureUseCached.addEventListener("click", function () { hideFailure(); if (failureActions.useCached) failureActions.useCached(); });
    failureRetry.addEventListener("click", function () { hideFailure(); failureActions.retry(); });

    function showFailure(title, message, retry, useCached) {
        failureActions = {retry: retry, useCached: useCached};
        failureTitle.textContent = title;
        failureError.textContent = message;
        failureUseCached.disabled = !useCached;
        failureDialog.hidden = false;
    }

    // The last successfully fetched value - either from this session, or silently loaded from the route's own
    // server-side cache on open (see below) - so "Use cached values" works even on the very first failure.
    var cachedElevation = null;

    function fillElevation(data) {
        cachedElevation = data;
        // write() sets values directly without dispatching input/change events (see loadForm above), so the
        // dirty/re-plan side effects are done explicitly here, the same as the takeoff/start picking above.
        // A slope or geometric route's heights are ellipsoidal, the takeoff point's too (as Pilot 2 writes it)
        routeForm.write(isSlope || isGeometric ? {takeoff_altitude: String(data.ellipsoidal)}
            : {takeoff_altitude: String(data.orthometric), takeoff_ellipsoidal_height: String(data.ellipsoidal)});
        state.aslFailed = null;
        setDirty(true);
        showAslHint();
        schedulePlan();
    }

    function showElevationFailure(message) {
        fetchButton.disabled = false;
        elevationStatus.textContent = "";
        showFailure("Could not fetch the elevation", message, fetchElevation,
                    cachedElevation ? function () { fillElevation(cachedElevation); } : null);
    }

    // auto: fetched without being asked (aslAutoFetch): a failure shows in the ASL hint, not in the dialog. The answer
    // for a takeoff point moved meanwhile is dropped.
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

    // -- ASL without the takeoff point's ground height: hints under the takeoff height and the ASL button, and the
    // height fetched when ASL is picked or the takeoff point set in it (not on opening a route) ---------------------------

    var aslHints = ["mp-asl-hint-takeoff", "mp-asl-hint-mode"].map(function (id) { return document.getElementById(id); }).filter(Boolean);

    function aslState() {
        var f = readForm();
        return {asl: f.altitude_mode === "asl", takeoff: !!state.takeoff, altitude: f.takeoff_altitude,
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
        var mode = readForm().altitude_mode;
        var picked = mode === "asl" && state.altitudeMode !== "asl";
        state.altitudeMode = mode;
        if (picked) aslAutoFetch(); else showAslHint();      // (aslAutoFetch shows the hint when it does not fetch)
    }

    // Silently check for a previously cached value on open, so "Use cached values" can be offered on the very
    // first failure this session, not just after a successful fetch already happened here.
    if (routeId) {
        fetch(API + "routes/" + routeId + "/elevation", {credentials: "same-origin"})
            .then(function (res) { return res.ok ? res.json() : null; })
            .then(function (data) { if (data) cachedElevation = data; })
            .catch(function () { /* ignore - "use cached" just starts disabled */ });
    }

    // -- the terrain under the route, for AGL over a terrain model (app/missions/terrain.py) -------------------------------------------

    var terrainButton = document.getElementById("mp-fetch-terrain"), terrainStatus = document.getElementById("mp-terrain-status");
    var routeTerrain = null;
    try { routeTerrain = JSON.parse(document.getElementById("mp-route-terrain").textContent); } catch (e) { routeTerrain = null; }

    function showTerrain() {
        if (!terrainStatus || state.fetchingTerrain) return;
        terrainStatus.textContent = Core.terrainText(routeTerrain, readForm().terrain_source);
    }

    // Fetches the terrain under the drawn route and the form, then calls done (the export, when it asked for it).
    // While the lidar units it needs are built (202), it waits, the progress in the status line and on the map's
    // lidar bar. When the service fails and the route's cached terrain still covers the plan, it can be used instead.
    var terrainWaiters = [];    // callbacks of the calls made while a fetch was running (an export waiting for it)
    function fetchTerrain(done) {
        var body = requestBody();
        if (!body || !routeId) return;
        // a fetch already running (Fetch terrain, then Download): the export waits for it
        if (state.fetchingTerrain) { if (done) terrainWaiters.push(done); return; }
        body.terrain_source = readForm().terrain_source || "lidar";
        terrainButton.disabled = true;
        terrainStatus.textContent = "Fetching terrain…";
        state.fetchingTerrain = true;
        var waited = false;
        Core.fetchUntilBuilt(post, "routes/" + routeId + "/terrain", body, {onWait: function (d) {
            waited = true;
            terrainStatus.textContent = Core.buildingText(d);
            lidarBar.show({busy: true, text: Core.buildingText(d)});
        }})
            .then(function (r) {
                state.fetchingTerrain = false;
                terrainButton.disabled = false;
                if (!r.ok) terrainWaiters.length = 0;     // the failure dialog below offers the retry
                if (waited) {
                    lidarBar.show(null);
                    if (lidarOn) lidar.refresh(lidarBounds());      // the units built for the terrain, in 3D too
                }
                if (!r.ok) {
                    showTerrain();
                    showFailure("Could not fetch the terrain", r.data.error || "The terrain service could not be reached",
                                function () { fetchTerrain(done); },
                                r.data.cached_covers && done ? done : null);
                    return;
                }
                routeTerrain = r.data;
                showTerrain();
                schedulePlan();                 // the route's heights in 3D are over the terrain now
                var waiting = terrainWaiters.splice(0);
                if (done) done();
                waiting.forEach(function (f) { f(); });
            })
            .catch(function () {
                state.fetchingTerrain = false;
                terrainButton.disabled = false;
                terrainWaiters.length = 0;
                showTerrain();
                showFailure("Could not fetch the terrain", "Could not reach the server", function () { fetchTerrain(done); }, null);
            });
    }
    if (terrainButton) {
        terrainButton.addEventListener("click", function () { fetchTerrain(null); });
        showTerrain();
    }

    var draw = null;

    // The toolbar's tools: Pointer (the dots of measure.js; the shape stays, in Terra Draw's static mode), the drawing
    // tools, Edit, and the bin. Choosing another tool clears the Pointer's dots.
    function setTool(tool) {
        if (state.tool === "pointer" && tool !== "pointer") measure.clear();
        state.tool = tool;
        [].forEach.call(root.querySelectorAll("[data-tool]"), function (b) { b.classList.toggle("active", b.getAttribute("data-tool") === tool); });
        if (!draw) return;
        if (tool === "clear") { draw.clear(); setShape(null); tool = isLinear ? "line" : "polygon"; state.tool = tool; }
        draw.setMode(tool === "line" ? "linestring" : tool === "pointer" ? "static" : tool);
        [].forEach.call(root.querySelectorAll("[data-tool]"), function (b) { b.classList.toggle("active", b.getAttribute("data-tool") === state.tool); });
    }

    // The area's corners, or the linear route's center line. silent is true only when restoreMapState puts back a
    // previously-saved one - that is not a new change to save.
    function setShape(coords, silent) {
        if (isLinear) {
            state.line = coords;
            els.areaMessage.textContent = coords ? "The line has " + coords.length + " points. Use Edit to change it." : "Draw the center line of the strip to survey on the map.";
            showStrip();
        } else if (isSlope) {
            state.heights = Core.keptHeights(state.area, state.heights, coords);
            state.area = coords;
            els.areaMessage.textContent = coords ? "The slope has " + coords.length + " corners. Use Edit to change it." : "Draw the slope on the map: its outline as seen from above.";
            showCorners();
        } else if (isGeometric) {
            state.area = coords;
            els.areaMessage.textContent = coords ? "The block has " + coords.length + " corners. Use Edit to change it." : "Draw the block on the map: its outline as seen from above.";
            blockButton.disabled = !(coords && coords.length >= 3);
            blockTasks.innerHTML = "";
            blockStatus.textContent = "";
        } else {
            state.area = coords;
            els.areaMessage.textContent = coords ? "The area has " + coords.length + " corners. Use Edit to change it." : "Draw the area to survey on the map.";
        }
        if (!silent) setDirty(true);
        if (coords) schedulePlan(); else clearResults("");
    }

    // -- a slope route's corner heights: typed, or from the DSM of a processed task over the slope ---------------------------

    var cornersList = document.getElementById("mp-corners"), faceButton = document.getElementById("mp-face-heights");
    var faceStatus = document.getElementById("mp-face-status"), faceTasks = document.getElementById("mp-face-tasks");
    var cornerMarkers = [];

    // The corners' numbers on the map and their heights in the panel
    function showCorners() {
        if (!cornersList) return;
        cornerMarkers.forEach(function (m) { m.remove(); });
        cornerMarkers = (state.area || []).map(function (c, i) {
            var label = document.createElement("div");
            label.className = "mp-corner-label";
            label.textContent = String(i + 1);
            return new maplibregl.Marker({element: label}).setLngLat(c).addTo(map);
        });
        cornersList.innerHTML = "";
        (state.area || []).forEach(function (c, i) {
            var row = document.createElement("div"), input = document.createElement("input");
            row.className = "mp-corner";
            row.innerHTML = '<span class="mp-corner-number">' + (i + 1) + "</span>";
            input.type = "number";
            input.step = "any";
            input.className = "form-control input-sm";
            input.setAttribute("aria-label", "Height of corner " + (i + 1) + " (m)");
            input.value = typeof state.heights[i] === "number" ? String(Core.roundTo(state.heights[i], 3)) : "";
            input.addEventListener("input", function () {
                var n = input.value.trim() === "" ? NaN : Number(input.value);
                state.heights[i] = isFinite(n) ? n : null;
                setDirty(true);
                schedulePlan();
            });
            row.appendChild(input);
            cornersList.appendChild(row);
        });
        faceButton.disabled = !(state.area && state.area.length >= 3);
        faceTasks.innerHTML = "";
        faceStatus.textContent = "";
    }

    function useTaskHeights(task) {
        state.heights = task.heights.slice();
        showCorners();
        faceStatus.textContent = "Heights from the " + (task.source === "point cloud" ? task.source : task.source.toUpperCase()) + " of " + task.name;
        setDirty(true);
        schedulePlan();
    }

    if (faceButton) faceButton.addEventListener("click", function () {
        if (!state.area) return;
        faceButton.disabled = true;
        faceStatus.textContent = "Looking for tasks over the slope…";
        faceTasks.innerHTML = "";
        post("face-heights", {corners: state.area}).then(function (res) {
            return res.json().then(function (data) { return {ok: res.ok, data: data}; });
        }).then(function (r) {
            faceButton.disabled = false;
            if (!r.ok) { faceStatus.textContent = r.data.error || "The heights could not be read"; return; }
            if (!r.data.tasks.length) { faceStatus.textContent = "No processed task you can see has a DSM over the whole slope"; return; }
            if (r.data.tasks.length === 1) { useTaskHeights(r.data.tasks[0]); return; }
            faceStatus.textContent = "Choose the task to take them from:";
            r.data.tasks.forEach(function (task) {
                var b = document.createElement("button");
                b.type = "button";
                b.className = "btn btn-default btn-sm btn-block";
                b.textContent = task.project_name + " / " + task.name;
                b.addEventListener("click", function () { useTaskHeights(task); });
                faceTasks.appendChild(b);
            });
        }).catch(function () { faceButton.disabled = false; faceStatus.textContent = "Could not reach the server"; });
    });

    // -- a geometric route's base and top: typed, or from the DSM of a processed task over the block ----------------------

    var blockButton = document.getElementById("mp-block-heights"), blockStatus = document.getElementById("mp-block-status");
    var blockTasks = document.getElementById("mp-block-tasks");

    function useBlockHeights(task) {
        routeForm.write({base: String(task.base), top: String(task.top)});
        blockTasks.innerHTML = "";
        blockStatus.textContent = "Heights from the " + (task.source === "point cloud" ? task.source : task.source.toUpperCase()) + " of " + task.name +
            ": the lowest ground round the block, and its highest point";
        setDirty(true);
        schedulePlan();
    }

    if (blockButton) blockButton.addEventListener("click", function () {
        if (!state.area) return;
        blockButton.disabled = true;
        blockStatus.textContent = "Looking for tasks over the block…";
        blockTasks.innerHTML = "";
        post("block-heights", {outline: state.area}).then(function (res) {
            return res.json().then(function (data) { return {ok: res.ok, data: data}; });
        }).then(function (r) {
            blockButton.disabled = false;
            if (!r.ok) { blockStatus.textContent = r.data.error || "The heights could not be read"; return; }
            if (!r.data.tasks.length) { blockStatus.textContent = "No processed task you can see has a DSM over the block and the ground round it"; return; }
            if (r.data.tasks.length === 1) { useBlockHeights(r.data.tasks[0]); return; }
            blockStatus.textContent = "Choose the task to take them from:";
            r.data.tasks.forEach(function (task) {
                var b = document.createElement("button");
                b.type = "button";
                b.className = "btn btn-default btn-sm btn-block";
                b.textContent = task.project_name + " / " + task.name;
                b.addEventListener("click", function () { useBlockHeights(task); });
                blockTasks.appendChild(b);
            });
        }).catch(function () { blockButton.disabled = false; blockStatus.textContent = "Could not reach the server"; });
    });

    // Terra Draw's rectangle has its sides along north and east (terra-draw 1.35.0, no option for the screen): on a
    // turned map, its two side corners are put back along the screen's sides (Core.rectangleCorners) each time it
    // sets them, before the finish is reported. Uses the mode's internals (startPosition, currentRectangleId,
    // mutateFeature): checked again when terra-draw is upgraded.
    function viewRectangle(mode) {
        var update = mode.updateRectangle;
        mode.updateRectangle = function (end, updateType) {
            var made = update.call(this, end, updateType);
            var bearing = map.getBearing();
            if (!made || !this.startPosition || !this.currentRectangleId || Math.abs(bearing) < 1e-9) return made;
            var corners = Core.rectangleCorners(this.startPosition, end, bearing);
            return this.mutateFeature.updatePolygon({featureId: this.currentRectangleId,
                coordinateMutations: [{type: "update", index: 1, coordinate: corners[0]}, {type: "update", index: 3, coordinate: corners[1]}],
                propertyMutations: {}, context: {updateType: updateType}}) || made;
        };
        return mode;
    }

    // The area is the last polygon drawn (the line the last line drawn): drawing another replaces it
    function shapeFromDrawing() {
        var features = draw.getSnapshot().filter(function (f) { return f.geometry.type === (isLinear ? "LineString" : "Polygon"); });
        if (!features.length) return null;
        var coords = features[features.length - 1].geometry.coordinates;
        if (isLinear) return coords.map(function (p) { return [p[0], p[1]]; });
        return coords[0].slice(0, coords[0].length - 1);
    }

    map.on("load", function () {
        var saved;
        try { saved = window.localStorage.getItem(BASEMAP_KEY); } catch (e) { saved = null; }
        applyBasemap(Core.chooseBasemap(basemaps, saved));

        map.addSource("mp-strip", {type: "geojson", data: EMPTY});
        map.addLayer({id: "mp-strip", type: "fill", source: "mp-strip", paint: {"fill-color": "#1e88e5", "fill-opacity": 0.12}});
        map.addLayer({id: "mp-strip-outline", type: "line", source: "mp-strip", paint: {"line-color": "#1e88e5", "line-width": 1, "line-dasharray": [2, 2]}});
        map.addSource("mp-lines", {type: "geojson", data: EMPTY});
        map.addSource("mp-waypoints", {type: "geojson", data: EMPTY});
        map.addSource("mp-takeoff", {type: "geojson", data: EMPTY});
        map.addSource("mp-start", {type: "geojson", data: EMPTY});
        // A linear route's passes along the bends (camera tilted) are dashed
        map.addLayer({id: "mp-lines", type: "line", source: "mp-lines", filter: ["!", ["in", ["get", "pass"], ["literal", ["bend", "roof"]]]], paint: {"line-color": "#1e88e5", "line-width": 2}});
        map.addLayer({id: "mp-lines-bend", type: "line", source: "mp-lines", filter: ["==", ["get", "pass"], "bend"], paint: {"line-color": "#8e24aa", "line-width": 2, "line-dasharray": [3, 2]}});
        // A geometric route's lines over the roof, under its loops
        map.addLayer({id: "mp-lines-roof", type: "line", source: "mp-lines", filter: ["==", ["get", "pass"], "roof"], paint: {"line-color": "#43a047", "line-width": 1.5}}, "mp-lines");
        map.addLayer({id: "mp-waypoints", type: "circle", source: "mp-waypoints", paint: {"circle-radius": 3, "circle-color": "#fff", "circle-stroke-color": "#1e88e5", "circle-stroke-width": 1.5}});

        map.addLayer({id: "mp-takeoff", type: "circle", source: "mp-takeoff", paint: {"circle-radius": 7, "circle-color": "#43a047", "circle-stroke-color": "#fff", "circle-stroke-width": 2}});
        map.addLayer({id: "mp-start", type: "circle", source: "mp-start", paint: {"circle-radius": 7, "circle-color": "#fb8c00", "circle-stroke-color": "#fff", "circle-stroke-width": 2}});
        route3d = window.MissionPlannerRoute3d.createRoute3d({maplibregl: maplibregl, map: map, id: "mp-route-3d", before: "mp-takeoff",
                                                             heightsAt: heightReader.heightsAt, flatBefore: "mp-waypoints", discs: true,
                                                             bandMaxes: heightReader.bandMaxes, margin: function () { checkedMargin = collisionMargin(); return checkedMargin; },
                                                             onCollisions: showCollisions});
        if (state.air) route3d.setAir(state.air, state.takeoff ? [state.takeoff[1], state.takeoff[0]] : null);

        var TD = window.terraDraw, adapter = window.terraDrawMaplibreGlAdapter;
        var editable = {feature: {draggable: true, rotateable: true, coordinates: {midpoints: true, draggable: true, deletable: true}}};
        draw = new TD.TerraDraw({
            adapter: new adapter.TerraDrawMapLibreGLAdapter({map: map, lib: maplibregl}),
            modes: isLinear ? [new TD.TerraDrawLineStringMode(), new TD.TerraDrawSelectMode({flags: {linestring: editable}})]
                : [new TD.TerraDrawPolygonMode(), viewRectangle(new TD.TerraDrawRectangleMode()),
                   new TD.TerraDrawSelectMode({flags: {polygon: editable, rectangle: editable}})]
        });
        draw.start();
        setTool("pointer");                 // every route opens in Pointer: a drawing tool is chosen to draw

        draw.on("finish", function (id, context) {
            if (context.action === "draw") {
                // Only one area (or line): the new one replaces the old
                draw.getSnapshot().forEach(function (f) { if (f.id !== id) draw.removeFeatures([f.id]); });
                setShape(shapeFromDrawing());
                setTool("select");
            } else {
                setShape(shapeFromDrawing());
            }
        });
        draw.on("change", function (ids, type) { if (type === "update" && state.tool === "select") setShape(shapeFromDrawing()); });

        restoreMapState();
    });

    // The area/takeoff/start saved on this route (see saveToServer) - restored once the map and the draw library
    // are ready, so a reload (or opening a route someone else's browser saved) shows the same mission, not a blank one,
    // with the map on its area rather than wherever this browser last looked (an imported route is often elsewhere).
    function restoreMapState() {
        if (isLinear && savedSettings.line && savedSettings.line.length >= 2) {
            try {
                draw.addFeatures([{type: "Feature", properties: {mode: "linestring"}, geometry: {type: "LineString", coordinates: savedSettings.line}}]);
                setShape(savedSettings.line, true);
                map.fitBounds(Core.lineBounds(savedSettings.line), {padding: 60, maxZoom: 19, duration: 0});
            } catch (e) { /* a corrupted saved line should not break the page - the user can just redraw it */ }
        }
        if (isSlope && savedSettings.corners && savedSettings.corners.length >= 3) {
            try {
                var corners = savedSettings.corners.map(function (c) { return [c[0], c[1]]; });
                draw.addFeatures([{type: "Feature", properties: {mode: "polygon"},
                    geometry: {type: "Polygon", coordinates: [corners.concat([corners[0]])]}}]);
                state.heights = savedSettings.corners.map(function (c) { return typeof c[2] === "number" ? c[2] : null; });
                state.area = corners;
                setShape(corners, true);
                map.fitBounds(Core.areaBounds(corners), {padding: 60, maxZoom: 19, duration: 0});
            } catch (e) { /* a corrupted saved slope should not break the page - the user can just redraw it */ }
        }
        if (isGeometric && savedSettings.outline && savedSettings.outline.length >= 3) {
            try {
                draw.addFeatures([{type: "Feature", properties: {mode: "polygon"},
                    geometry: {type: "Polygon", coordinates: [savedSettings.outline.concat([savedSettings.outline[0]])]}}]);
                setShape(savedSettings.outline, true);
                map.fitBounds(Core.areaBounds(savedSettings.outline), {padding: 60, maxZoom: 19, duration: 0});
            } catch (e) { /* a corrupted saved outline should not break the page - the user can just redraw it */ }
        }
        if (!isLinear && !isSlope && !isGeometric && savedSettings.polygon && savedSettings.polygon.length >= 3) {
            try {
                draw.addFeatures([{type: "Feature", properties: {mode: "polygon"},
                    geometry: {type: "Polygon", coordinates: [savedSettings.polygon.concat([savedSettings.polygon[0]])]}}]);
                setShape(savedSettings.polygon, true);
                map.fitBounds(Core.areaBounds(savedSettings.polygon), {padding: 60, maxZoom: 19, duration: 0});
            } catch (e) { /* a corrupted saved polygon should not break the page - the user can just redraw it */ }
        }
        if (savedSettings.takeoff) state.takeoff = savedSettings.takeoff;
        if (savedSettings.route_start && !isLinear) state.routeStart = savedSettings.route_start;
        showPicked();
    }

    // -- wiring -------------------------------------------------------------------------------------------------------

    [].forEach.call(root.querySelectorAll("[data-tool]"), function (b) {
        b.addEventListener("click", function () { setTool(b.getAttribute("data-tool")); });
    });
    els.download.addEventListener("click", download);
    els.downloadKml.addEventListener("click", downloadKml);
    var longest = document.getElementById("mp-longest");
    if (longest) longest.addEventListener("click", function () {
        var direction = Core.longestSideDirection(state.area);
        if (direction === null) return;
        document.getElementById("mp-direction").value = direction;
        routeForm.refresh();
        setDirty(true);
        schedulePlan();
    });

    // -- units: a per-browser display preference, like the map view/basemap - never sent to the server -----------------

    var UNITS_KEY = "mission-planner:units";

    function applyUnits(system) {
        unitsSystem = system;
        routeForm.setUnits(system);
        showCollisions(shownCount);              // the margin in the chosen units
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

    // -- leaving the page without saving -----------------------------------------------------------------------------
    // No autosave, so a click on "Routes" while dirty is intercepted and asks Save or Discard instead of silently
    // losing the change. Any other way to leave (closing the tab, typing a new URL, a link outside this page) is
    // caught by beforeunload instead - browsers do not allow customizing that dialog's buttons or text.

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
        save().then(function () { if (!saver.isDirty()) window.location.href = backLink.href; });   // stay put if the save failed
    });

    window.addEventListener("beforeunload", function (e) {
        if (!saver.isDirty()) return;
        e.preventDefault();
        e.returnValue = "";
    });

    loadForm();
    state.altitudeMode = readForm().altitude_mode;
    if (savedUnits === "imperial") applyUnits("imperial");
    if (lidarOn) lidar.refresh(lidarBounds());              // the units already built, for the heights under the pointer
})();
