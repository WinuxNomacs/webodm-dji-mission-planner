// The logic of the mission planner page that does not need a map: checking the form, building the request,
// and writing the results in words. A plain script (the page has no bundler); tests load it as a module.
(function (root) {
    var DEFAULTS = {
        name: "luxodm-mission", lens_visible: "true", lens_ir: "true", height: "50", overlap_h: "80", overlap_w: "70", margin: "0", direction: "0",
        // Defaults to the metric equivalent of 4 mph (not empty/unbounded): a drone flying its first mission on an
        // untouched form should cruise at a cautious, predictable speed, not "as fast as the photos allow".
        speed: "1.79", altitude_mode: "agl", takeoff_mode: "safe", takeoff_security_height: "20", rth_height: "100", transitional_speed: "15",
        elevation_optimize: "true", avoid_limit_area: "false", photo_mode: "distance", takeoff_altitude: "",
        finish_action: "goHome", exit_on_rc_lost: "goContinue",
        // Oblique also flies 4 tilted passes (see app/missions/wpml.py's OBLIQUE_HEADINGS); with AGL it follows the
        // route's terrain, embedded in the mission (see app/missions/terrain.py). inclined_overlap_h/w and inclined_speed default empty: empty mirrors the ortho
        // overlap/global speed, the same "blank means automatic" idiom as speed/takeoff_altitude already use.
        collection_mode: "ortho", gimbal_pitch: "-45", inclined_overlap_h: "", inclined_overlap_w: "", inclined_speed: "",
        // ASL only: the WGS84-ellipsoidal ground height at the takeoff point, fetched together with
        // takeoff_altitude (see app/missions/elevation.py) - never typed by hand, so always blank until fetched.
        takeoff_ellipsoidal_height: "",
        // AGL only: "realtime" follows the ground the aircraft sees, "dsm" flies heights planned over the route's terrain
        // (embedded in the mission). Oblique AGL always flies over the terrain, whatever this says.
        surface_follow: "realtime",
        // AGL over the terrain: "lidar" (the lidar surface, trees and roofs, where USGS lidar covers the route; else
        // COP30, saying why) or "cop30" (see lidar_terrain.py)
        terrain_source: "lidar"
    };

    // The same limits as the server's (app/missions): the page tells what is wrong before asking
    var LIMITS = {
        height: [2, 500, "Height above the ground", "m"], overlap_h: [10, 95, "Overlap along the lines", "%"],
        overlap_w: [10, 95, "Overlap between lines", "%"], takeoff_security_height: [2, 1500, "Takeoff security height", "m"],
        rth_height: [2, 1500, "Return height", "m"]
    };
    var MAX_SPEED = 15;
    var MIN_GIMBAL_PITCH = -85, MAX_GIMBAL_PITCH = -40;      // the range Pilot 2 offers for the M4T's oblique tilt
    var MIN_OVERLAP = 10, MAX_OVERLAP = 95;
    var COLLECTION_MODES = ["ortho", "oblique"];
    var SURFACE_FOLLOWS = ["realtime", "dsm"];

    // altitude mode -> WPML height mode. Oblique AGL is sent as realTimeFollowSurface too: the server turns it into the
    // DSM height mode, from the terrain fetched for the route (see wpml.uses_dsm).
    var ALTITUDE_MODES = {agl: "realTimeFollowSurface", alt: "relativeToStartPoint", asl: "EGM96"};
    var TAKEOFF_MODES = ["safe", "direct"];
    var FINISH_ACTIONS = ["goHome", "noAction", "autoLand", "gotoFirstWaypoint"];
    var RC_LOST = ["goContinue", "executeLostAction"];

    function toBool(v) { return v === true || v === "true" || v === "1" || v === 1 || v === "on"; }

    function toNumber(text) {
        if (typeof text === "number") return isFinite(text) ? text : NaN;
        if (typeof text !== "string" || text.trim() === "") return NaN;
        return Number(text.trim());
    }

    // Checks a form ({field: text}). Returns {ok, errors: {field: message}, values: {field: number or text}}
    function parseForm(form) {
        var f = {}, errors = {}, values = {};
        Object.keys(DEFAULTS).forEach(function (k) { f[k] = form[k] === undefined ? DEFAULTS[k] : form[k]; });

        Object.keys(LIMITS).forEach(function (k) {
            var n = toNumber(f[k]), l = LIMITS[k];
            if (isNaN(n)) errors[k] = l[2] + " must be a number";
            else if (n < l[0] || n > l[1]) errors[k] = l[2] + " must be between " + l[0] + " and " + l[1] + " " + l[3];
            else values[k] = n;
        });

        var margin = toNumber(f.margin);
        if (isNaN(margin) || margin < 0) errors.margin = "The margin must be a number of meters, 0 or more"; else values.margin = margin;

        var direction = toNumber(f.direction);
        if (isNaN(direction)) errors.direction = "The direction must be a number of degrees"; else values.direction = ((direction % 360) + 360) % 360;

        if (String(f.speed).trim() === "") values.speed = null;
        else {
            var speed = toNumber(f.speed);
            if (isNaN(speed) || speed <= 0 || speed > MAX_SPEED) errors.speed = "The speed must be more than 0 and at most " + MAX_SPEED + " m/s (or empty: as fast as the photos allow)";
            else values.speed = speed;
        }

        var lenses = [];
        if (toBool(f.lens_visible)) lenses.push("visable");
        if (toBool(f.lens_ir)) lenses.push("ir");
        if (!lenses.length) errors.cameras = "Choose at least one lens"; else values.cameras = lenses;

        if (!ALTITUDE_MODES[f.altitude_mode]) errors.altitude_mode = "Choose how the height is kept"; else { values.altitude_mode = f.altitude_mode; values.height_mode = ALTITUDE_MODES[f.altitude_mode]; }
        if (TAKEOFF_MODES.indexOf(f.takeoff_mode) === -1) errors.takeoff_mode = "Choose safe takeoff or direct ascent"; else values.takeoff_mode = f.takeoff_mode;
        if (f.photo_mode !== "distance") errors.photo_mode = "Photos every so many seconds are not available yet: use a photo every so many meters"; else values.photo_mode = f.photo_mode;
        values.elevation_optimize = toBool(f.elevation_optimize);
        values.avoid_limit_area = toBool(f.avoid_limit_area);

        var transitional = toNumber(f.transitional_speed);
        if (isNaN(transitional) || transitional <= 0 || transitional > MAX_SPEED) errors.transitional_speed = "The takeoff speed must be more than 0 and at most " + MAX_SPEED + " m/s"; else values.transitional_speed = transitional;

        if (String(f.takeoff_altitude).trim() === "") values.takeoff_altitude = null;
        else {
            var altitude = toNumber(f.takeoff_altitude);
            if (isNaN(altitude) || altitude < -500 || altitude > 9000) errors.takeoff_altitude = "The ground height at the takeoff point must be a number of meters above sea level"; else values.takeoff_altitude = altitude;
        }
        // Never typed by hand - only ever written by the "fetch from elevation data" action (see planner.js).
        // Blank unless a fetch succeeded; required below when altitude_mode is "asl".
        values.takeoff_ellipsoidal_height = String(f.takeoff_ellipsoidal_height).trim() === "" ? null : toNumber(f.takeoff_ellipsoidal_height);
        if (values.altitude_mode === "asl" && (values.takeoff_altitude === null || values.takeoff_ellipsoidal_height === null || isNaN(values.takeoff_ellipsoidal_height)))
            errors.altitude_mode = "Fetch the ground elevation at the takeoff point before using ASL";

        if (FINISH_ACTIONS.indexOf(f.finish_action) === -1) errors.finish_action = "Choose what happens at the end"; else values.finish_action = f.finish_action;
        if (RC_LOST.indexOf(f.exit_on_rc_lost) === -1) errors.exit_on_rc_lost = "Choose what happens when remote signal is lost"; else values.exit_on_rc_lost = f.exit_on_rc_lost;
        values.name = String(f.name || DEFAULTS.name);
        if (SURFACE_FOLLOWS.indexOf(f.surface_follow) === -1) errors.surface_follow = "Choose real-time follow or the terrain model";
        else values.surface_follow = f.surface_follow;

        if (COLLECTION_MODES.indexOf(f.collection_mode) === -1) errors.collection_mode = "Choose Ortho or Oblique collection";
        else values.collection_mode = f.collection_mode;

        if (values.collection_mode === "oblique") {
            var pitch = toNumber(f.gimbal_pitch);
            if (isNaN(pitch) || pitch < MIN_GIMBAL_PITCH || pitch > MAX_GIMBAL_PITCH)
                errors.gimbal_pitch = "The gimbal tilt angle must be between " + MIN_GIMBAL_PITCH + " and " + MAX_GIMBAL_PITCH + " degrees";
            else values.gimbal_pitch = pitch;

            ["inclined_overlap_h", "inclined_overlap_w"].forEach(function (k) {
                if (String(f[k]).trim() === "") { values[k] = null; return; }
                var n = toNumber(f[k]);
                if (isNaN(n) || n < MIN_OVERLAP || n > MAX_OVERLAP)
                    errors[k] = "The oblique overlap must be between " + MIN_OVERLAP + " and " + MAX_OVERLAP + "% (or empty: same as the ortho overlap)";
                else values[k] = n;
            });

            if (String(f.inclined_speed).trim() === "") values.inclined_speed = null;
            else {
                var ispeed = toNumber(f.inclined_speed);
                if (isNaN(ispeed) || ispeed <= 0 || ispeed > MAX_SPEED)
                    errors.inclined_speed = "The oblique speed must be more than 0 and at most " + MAX_SPEED + " m/s (or empty: as fast as the oblique photos allow)";
                else values.inclined_speed = ispeed;
            }
        } else {
            values.gimbal_pitch = values.inclined_overlap_h = values.inclined_overlap_w = values.inclined_speed = null;
        }

        return {ok: Object.keys(errors).length === 0, errors: errors, values: values};
    }

    // The body of a plan/export request, or null if there is no usable area or the form has errors.
    // area: [[lon, lat], ...] (open or closed ring); takeoff: [lat, lon] or null (the takeoff point needs the ground height
    // typed in the form to be written); routeStart: [lon, lat] or null; model: the aircraft ("m4t" when left out), whose
    // cameras are the only ones sent
    function requestBody(area, form, takeoff, routeStart, model) {
        var parsed = parseForm(form);
        if (!parsed.ok || !area || area.length < 3) return null;
        model = model || "m4t";
        var cameras = parsed.values.cameras.filter(function (c) { return GSD_PER_M_BY_MODEL[model][c] !== undefined; });
        if (!cameras.length) return null;

        var ring = area.map(function (p) { return [p[0], p[1]]; });
        if (ring.length > 3 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]) ring.pop();

        var v = parsed.values;
        var body = {
            model: model, polygon: ring, direction: v.direction, height: v.height, cameras: cameras, overlap_h: v.overlap_h, overlap_w: v.overlap_w,
            margin: v.margin, speed: v.speed, height_mode: v.height_mode, takeoff_security_height: v.takeoff_security_height,
            rth_height: v.rth_height, finish_action: v.finish_action, exit_on_rc_lost: v.exit_on_rc_lost,
            takeoff_ref_point: takeoff && v.takeoff_altitude !== null ? [takeoff[0], takeoff[1], v.takeoff_altitude] : null,
            transitional_speed: v.transitional_speed, takeoff_mode: v.takeoff_mode, elevation_optimize: v.elevation_optimize,
            avoid_limit_area: v.avoid_limit_area, photo_mode: v.photo_mode, route_start: routeStart || null, name: v.name,
            collection_mode: v.collection_mode, surface_follow: v.surface_follow
        };
        // Only meaningful (and only valid server-side) for altitude_mode "asl" - see the "fetch from elevation
        // data" action in planner.js, which is the only thing that ever sets takeoff_ellipsoidal_height.
        if (v.altitude_mode === "asl") body.takeoff_ellipsoidal_height = v.takeoff_ellipsoidal_height;
        // The oblique-only settings are only sent (and only valid server-side) for collection_mode "oblique"
        if (v.collection_mode === "oblique") {
            body.gimbal_pitch = v.gimbal_pitch;
            body.inclined_overlap_h = v.inclined_overlap_h;
            body.inclined_overlap_w = v.inclined_overlap_w;
            body.inclined_speed = v.inclined_speed;
        }
        return body;
    }

    // Initial bearing (degrees clockwise from north) of the great circle from a to b, points as [lon, lat]
    function bearing(a, b) {
        var rad = Math.PI / 180, dLon = (b[0] - a[0]) * rad, lat1 = a[1] * rad, lat2 = b[1] * rad;
        var y = Math.sin(dLon) * Math.cos(lat2), x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
        return ((Math.atan2(y, x) / rad) + 360) % 360;
    }

    function distance(a, b) {
        var rad = Math.PI / 180, dLat = (b[1] - a[1]) * rad, dLon = (b[0] - a[0]) * rad;
        var h = Math.pow(Math.sin(dLat / 2), 2) + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.pow(Math.sin(dLon / 2), 2);
        return 2 * 6371000 * Math.asin(Math.sqrt(h));
    }

    // The direction of the longest side of the area, as a line direction between 0 and 180 degrees: flying along
    // the longest side means fewer turns
    function longestSideDirection(area) {
        if (!area || area.length < 3) return null;
        var best = null, bestLength = -1;
        for (var i = 0; i < area.length; i++) {
            var a = area[i], b = area[(i + 1) % area.length], d = distance(a, b);
            if (d > bestLength) { bestLength = d; best = [a, b]; }
        }
        return Math.round((bearing(best[0], best[1]) % 180) * 10) / 10;
    }

    // The box around the area, [[west, south], [east, north]], for the map to show it when a saved route opens
    function areaBounds(area) {
        if (!area || area.length < 3) return null;
        var lons = area.map(function (p) { return p[0]; }), lats = area.map(function (p) { return p[1]; });
        return [[Math.min.apply(null, lons), Math.min.apply(null, lats)], [Math.max.apply(null, lons), Math.max.apply(null, lats)]];
    }

    // The two other corners of a rectangle drawn from `start` to `end` ([lon, lat]), its sides along the screen of a map
    // turned to `bearingDeg` (MapLibre's: the compass direction the top of the screen faces), not along north and east:
    // [the corner across from start on the screen's horizontal, the one on its vertical]. Worked out in Web Mercator,
    // which keeps angles, so the corners are square on the ground (in 3D too, where the screen's own corners are not).
    function rectangleCorners(start, end, bearingDeg) {
        var R = Math.PI / 180, b = (bearingDeg || 0) * R;
        var toY = function (lat) { return Math.log(Math.tan(Math.PI / 4 + lat * R / 2)); };
        var toLat = function (y) { return (2 * Math.atan(Math.exp(y)) - Math.PI / 2) / R; };
        var sx = start[0] * R, sy = toY(start[1]), dx = end[0] * R - sx, dy = toY(end[1]) - sy;
        var right = [Math.cos(b), -Math.sin(b)], up = [Math.sin(b), Math.cos(b)];
        var a = dx * right[0] + dy * right[1], c = dx * up[0] + dy * up[1];
        var corner = function (k, v) { return [(sx + k * v[0]) / R, toLat(sy + k * v[1])]; };
        return [corner(a, right), corner(c, up)];
    }

    function formatDuration(seconds) {
        var s = Math.round(seconds);
        if (s < 60) return s + " s";
        var m = Math.floor(s / 60), r = s % 60;
        if (m < 60) return m + " min " + (r < 10 ? "0" : "") + r + " s";
        var h = Math.floor(m / 60);
        m = m % 60;
        return h + " h " + (m < 10 ? "0" : "") + m + " min";
    }

    function formatDistance(meters) {
        return meters < 1000 ? Math.round(meters) + " m" : (Math.round(meters / 10) / 100) + " km";
    }

    function formatArea(m2) {
        return m2 < 10000 ? Math.round(m2 * 100) / 100 + " m\u00b2" : (Math.round(m2 / 100) / 100) + " ha";
    }

    function round(v, digits) { var m = Math.pow(10, digits); return Math.round(v * m) / m; }

    // -- units --------------------------------------------------------------------------------------------------------
    // Routes are always planned and saved in metric; the form only converts what is shown to the user (see route_form.js).
    var M_TO_FT = 3.28084, MPS_TO_MPH = 2.23694;
    function metersToFeet(m) { return m * M_TO_FT; }
    function feetToMeters(ft) { return ft / M_TO_FT; }
    function mpsToMph(mps) { return mps * MPS_TO_MPH; }
    function mphToMps(mph) { return mph / MPS_TO_MPH; }

    var CAMERA_LABELS = {visable: "wide camera", ir: "thermal camera"};

    // The results in words: [{label, value}]
    function summaryRows(summary) {
        var rows = [
            {label: "Area", value: summary.area === undefined ? "" : formatArea(summary.area)},
            {label: "Flight lines", value: String(summary.lines)},
            {label: "Distance between lines", value: round(summary.spacing, 2) + " m"},
            {label: "A photo every", value: round(summary.interval, 2) + " m"},
            {label: "Photos", value: String(summary.photos)},
            {label: "Speed", value: round(summary.speed, 1) + " m/s (at most " + round(summary.max_speed, 1) + " m/s)"},
            {label: "Flight", value: formatDistance(summary.distance) + ", " + formatDuration(summary.duration)}
        ];
        Object.keys(summary.gsd || {}).forEach(function (k) {
            var cm = summary.gsd[k] * 100;
            rows.push({label: "Pixel size, " + (CAMERA_LABELS[k] || k), value: round(cm, cm < 1 ? 2 : 1) + " cm"});
        });
        return rows.filter(function (r) { return r.value !== ""; });
    }

    // -- map layers -------------------------------------------------------------------------------------------------
    // The planner uses the basemaps of the project (Administration > Basemaps), the same as the map of the tasks.

    var OSM = {type: "tms", label: "OpenStreetMap", url: "//tile.openstreetmap.org/{z}/{x}/{y}.png", minzoom: 0, maxzoom: 19,
               attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'};

    // Free elevation tiles (Terrain Tiles on AWS Open Data) for the 3D view
    var TERRAIN_SOURCE = {type: "raster-dem", encoding: "terrarium", tileSize: 256, maxzoom: 15,
                          tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
                          attribution: 'Terrain: <a href="https://registry.opendata.aws/terrain-tiles/">Terrain Tiles</a> (SRTM, USGS 3DEP and others)'};

    function withProtocol(url, protocol) {
        return url.indexOf("//") === 0 ? (protocol || "https:") + url : url;
    }

    function wmsUrl(bm, url) {
        var format = bm.format || "image/png";
        var query = ["service=WMS", "request=GetMap", "version=1.1.1", "layers=" + encodeURIComponent(bm.layers || "0"),
                     "styles=" + encodeURIComponent(bm.styles || "default"), "format=" + encodeURIComponent(format),
                     "transparent=" + (format === "image/png"), "srs=EPSG:3857", "width=256", "height=256", "bbox={bbox-epsg-3857}"].join("&");
        return url + (url.indexOf("?") === -1 ? "?" : "&") + query;
    }

    // A MapLibre raster source for a basemap ({type: "tms" | "wms", url, subdomains, minzoom, maxzoom, attribution, ...}).
    // `protocol` is the page's ("http:" or "https:"), for URLs that start with //.
    function basemapSource(bm, protocol) {
        var url = withProtocol(bm.url || "", protocol);
        if (bm.type === "wms") url = wmsUrl(bm, url);

        // Leaflet's {-y}: tile rows counted from the south
        var scheme = "xyz";
        if (url.indexOf("{-y}") !== -1) { url = url.replace(/\{-y\}/g, "{y}"); scheme = "tms"; }

        var tiles;
        if (url.indexOf("{s}") !== -1) {
            var subdomains = bm.subdomains && bm.subdomains.length ? bm.subdomains : ["a", "b", "c"];
            tiles = subdomains.map(function (sub) { return url.replace(/\{s\}/g, sub); });
        } else {
            tiles = [url];
        }

        var source = {type: "raster", tiles: tiles, tileSize: 256, scheme: scheme, minzoom: bm.minzoom || 0, maxzoom: bm.maxzoom || 21};
        if (bm.attribution) source.attribution = bm.attribution;
        return source;
    }

    // The basemap to show: the one the user chose last, else the project's default, else the first, else OpenStreetMap
    function chooseBasemap(basemaps, savedLabel) {
        var list = Array.isArray(basemaps) ? basemaps.filter(function (b) { return b && b.url; }) : [];
        if (!list.length) return OSM;
        for (var i = 0; i < list.length; i++) if (savedLabel && list[i].label === savedLabel) return list[i];
        for (var j = 0; j < list.length; j++) if (list[j].default) return list[j];
        return list[0];
    }

    // -- coordinate search --------------------------------------------------------------------------------------------
    // "40.7128, -74.0060", "40.7128 -74.0060", "40.7128,-74.0060": two numbers, comma and/or whitespace between them.
    // Returns [lat, lng] or null - the search panel tries this before falling back to geocoding the text as an address.
    var COORDS_RE = /^\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*$/;
    function parseCoordinates(text) {
        var m = String(text).match(COORDS_RE);
        if (!m) return null;
        var lat = parseFloat(m[1]), lng = parseFloat(m[2]);
        if (isNaN(lat) || isNaN(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
        return [lat, lng];
    }

    // -- address suggestions (Photon, komoot's geocoder of OpenStreetMap) ---------------------------------------------

    var PHOTON = "https://photon.komoot.io/api/", PHOTON_LANGUAGES = ["en", "de", "fr"];

    // "de-CH" -> "de"; null for a language Photon does not have (it then answers in the places' own)
    function photonLanguage(browserLanguage) {
        var lang = String(browserLanguage || "").toLowerCase().split("-")[0];
        return PHOTON_LANGUAGES.indexOf(lang) !== -1 ? lang : null;
    }

    // center: [lon, lat], which the answers are biased towards
    function photonUrl(query, center, lang) {
        var url = PHOTON + "?q=" + encodeURIComponent(query) + "&limit=10";
        if (center && isFinite(center[0]) && isFinite(center[1])) url += "&lat=" + (+center[1]).toFixed(4) + "&lon=" + (+center[0]).toFixed(4);
        if (lang) url += "&lang=" + lang;
        return url;
    }

    // Photon's GeoJSON answer -> [{label, detail, center: [lon, lat], bbox: [minLon, minLat, maxLon, maxLat] or null}]:
    // the place's name (or its street and number) and the places it is in. Places that would read the same (a square
    // mapped as a node and as an area) are listed once
    function photonSuggestions(json) {
        var seen = {};
        return ((json && json.features) || []).map(function (f) {
            var p = f.properties || {}, c = f.geometry && f.geometry.coordinates;
            if (!c || !isFinite(c[0]) || !isFinite(c[1])) return null;
            var street = [p.street, p.housenumber].filter(Boolean).join(" ");
            var label = p.name || street || p.city || p.state || p.country;
            if (!label) return null;
            var detail = [];
            [p.name ? street : "", p.city || p.county, p.state, p.country].forEach(function (part) {
                if (part && part !== label && detail.indexOf(part) === -1) detail.push(part);
            });
            var e = p.extent;            // [minLon, maxLat, maxLon, minLat]
            var bbox = e && e.length === 4 && e[0] !== e[2] && e[1] !== e[3] ? [e[0], e[3], e[2], e[1]] : null;
            var key = label + "\n" + detail.join(", ");
            if (seen[key]) return null;
            seen[key] = true;
            return {label: label, detail: detail.join(", "), center: [c[0], c[1]], bbox: bbox};
        }).filter(Boolean).slice(0, 5);
    }

    // The suggestions for a query, near center; none for "latitude, longitude", which needs no geocoding.
    // An unreachable service rejects, and the search panel then shows no list
    function suggestPlaces(fetchFn, query, center, lang) {
        if (parseCoordinates(query)) return Promise.resolve([]);
        return fetchFn(photonUrl(query, center, lang))
            .then(function (res) { if (!res.ok) throw new Error("Photon answered " + res.status); return res.json(); })
            .then(photonSuggestions);
    }

    // Moves a MapLibre map to a picked suggestion: its extent when it has one, else its point at zoom 15 or closer
    function showSuggestion(map, s) {
        if (s.bbox) map.fitBounds([[s.bbox[0], s.bbox[1]], [s.bbox[2], s.bbox[3]]], {padding: 40, maxZoom: 18});
        else map.flyTo({center: s.center, zoom: Math.max(map.getZoom(), 15)});
    }

    // -- aircraft ----------------------------------------------------------------------------------------------------
    // The plugin's drones.json (missions/drones.py), which the page carries as JSON (#mp-drones) and tests read as a file
    function readDrones() {
        var script = typeof document !== "undefined" && document.getElementById("mp-drones");
        if (script) return JSON.parse(script.textContent);
        return typeof require === "function" ? require("../drones.json") : {};
    }
    var DRONES = readDrones();

    // {model: {camera: f(camera)}} of every aircraft's cameras
    function byCamera(f) {
        var out = {};
        Object.keys(DRONES).forEach(function (model) {
            out[model] = {};
            DRONES[model].cameras.forEach(function (c) { out[model][c.key] = f(c); });
        });
        return out;
    }

    // -- ground sample distance --------------------------------------------------------------------------------------
    // Size of a pixel on the ground per meter of height for each camera: (sensor width / pixels across) / focal length,
    // as missions/cameras.py has it (the server sends them too, and a test compares them), per aircraft model
    var GSD_PER_M_BY_MODEL = byCamera(function (c) { return (c.sensor_w_mm / c.px_w) / c.focal_mm; });
    var GSD_PER_M = GSD_PER_M_BY_MODEL.m4t;

    // cm per pixel of a camera at a height in meters (on an M4T when no model is given)
    function gsdCm(camera, height, model) { return GSD_PER_M_BY_MODEL[model || "m4t"][camera] * height * 100; }

    // The height in meters for a ground sample distance in cm per pixel
    function heightForGsd(camera, cm, model) { return cm / 100 / GSD_PER_M_BY_MODEL[model || "m4t"][camera]; }

    // The height a copy of a route flown at `height` by `fromModel` is flown at by `toModel`, to keep the visible
    // ground sample distance (the server's copied_settings does the same, kept within 2..500 m)
    function copiedHeight(height, fromModel, toModel) {
        return Math.min(500, Math.max(2, height * GSD_PER_M_BY_MODEL[fromModel].visable / GSD_PER_M_BY_MODEL[toModel].visable));
    }

    function roundTo(v, digits) { var m = Math.pow(10, digits); return Math.round(v * m) / m; }

    // -- waypoint routes ----------------------------------------------------------------------------------------------
    // A waypoint route is a list of points flown in order (app/missions/waypoints.py has the same limits and defaults).
    var WAYPOINT_DEFAULTS = {
        name: "luxodm-waypoints", lens_visible: "true", lens_ir: "true", height: "50", height_mode: "alt", speed: "5",
        gimbal_pitch: "", heading_mode: "followWayline", turn_mode: "stop", takeoff_mode: "safe", takeoff_security_height: "20",
        rth_height: "100", transitional_speed: "15", finish_action: "goHome", exit_on_rc_lost: "goContinue",
        avoid_limit_area: "false", takeoff_altitude: "", takeoff_ellipsoidal_height: "", video: "false",
        photo_interval_mode: "", photo_interval: "", terrain_source: "lidar"
    };
    var WAYPOINT_HEIGHT_MODES = ["alt", "asl", "agl"];
    // towardPOI: the aircraft faces the route's POI (a point kept beside the form, like the takeoff point)
    var HEADING_MODES = ["followWayline", "manually", "towardPOI"];
    var TURN_MODES = ["stop", "pass", "curve"];
    // Photos over the route: none (""), every so many meters or seconds
    var PHOTO_INTERVAL_MODES = ["", "distance", "time"];
    var MIN_INTERVAL = 0.5, MAX_INTERVAL = 900;
    var MIN_HEIGHT = 2, MAX_HEIGHT = 1500, MIN_ASL = -1000, MAX_ASL = 10000;
    var MIN_PITCH = -90, MAX_PITCH = 35, MAX_HOVER = 900;

    // The message for a height that is out of the height mode's range, or null
    function heightError(n, heightMode, label) {
        if (heightMode === "asl") return isNaN(n) || n < MIN_ASL || n > MAX_ASL ? label + " must be between " + MIN_ASL + " and " + MAX_ASL + " m above sea level" : null;
        return isNaN(n) || n < MIN_HEIGHT || n > MAX_HEIGHT ? label + " must be between " + MIN_HEIGHT + " and " + MAX_HEIGHT + " m" : null;
    }

    function blank(text) { return text === null || text === undefined || String(text).trim() === ""; }

    // Checks the route-wide settings of a waypoint route ({field: text}), as parseForm does for an area
    function parseWaypointForm(form) {
        var f = {}, errors = {}, values = {};
        Object.keys(WAYPOINT_DEFAULTS).forEach(function (k) { f[k] = form[k] === undefined ? WAYPOINT_DEFAULTS[k] : form[k]; });

        if (WAYPOINT_HEIGHT_MODES.indexOf(f.height_mode) === -1) errors.height_mode = "Choose how the height is measured"; else values.height_mode = f.height_mode;
        var height = toNumber(f.height), message = heightError(height, values.height_mode, "The height");
        if (message) errors.height = message; else values.height = height;

        var speed = toNumber(f.speed);
        if (isNaN(speed) || speed <= 0 || speed > MAX_SPEED) errors.speed = "The speed must be more than 0 and at most " + MAX_SPEED + " m/s"; else values.speed = speed;

        if (blank(f.gimbal_pitch)) values.gimbal_pitch = null;
        else {
            var pitch = toNumber(f.gimbal_pitch);
            if (isNaN(pitch) || pitch < MIN_PITCH || pitch > MAX_PITCH) errors.gimbal_pitch = "The gimbal pitch must be between " + MIN_PITCH + " and " + MAX_PITCH + " degrees (or empty: leave the gimbal as it is)";
            else values.gimbal_pitch = pitch;
        }

        ["takeoff_security_height", "rth_height"].forEach(function (k) {
            var n = toNumber(f[k]), l = LIMITS[k];
            if (isNaN(n) || n < l[0] || n > l[1]) errors[k] = l[2] + " must be between " + l[0] + " and " + l[1] + " " + l[3]; else values[k] = n;
        });
        var transitional = toNumber(f.transitional_speed);
        if (isNaN(transitional) || transitional <= 0 || transitional > MAX_SPEED) errors.transitional_speed = "The takeoff speed must be more than 0 and at most " + MAX_SPEED + " m/s"; else values.transitional_speed = transitional;

        var lenses = [];
        if (toBool(f.lens_visible)) lenses.push("visable");
        if (toBool(f.lens_ir)) lenses.push("ir");
        if (!lenses.length) errors.cameras = "Choose at least one lens"; else values.cameras = lenses;

        if (HEADING_MODES.indexOf(f.heading_mode) === -1) errors.heading_mode = "Choose how the aircraft is turned"; else values.heading_mode = f.heading_mode;
        if (TURN_MODES.indexOf(f.turn_mode) === -1) errors.turn_mode = "Choose whether the aircraft stops at each point"; else values.turn_mode = f.turn_mode;
        if (TAKEOFF_MODES.indexOf(f.takeoff_mode) === -1) errors.takeoff_mode = "Choose safe takeoff or direct ascent"; else values.takeoff_mode = f.takeoff_mode;
        if (FINISH_ACTIONS.indexOf(f.finish_action) === -1) errors.finish_action = "Choose what happens at the end"; else values.finish_action = f.finish_action;
        if (RC_LOST.indexOf(f.exit_on_rc_lost) === -1) errors.exit_on_rc_lost = "Choose what happens when remote signal is lost"; else values.exit_on_rc_lost = f.exit_on_rc_lost;
        values.avoid_limit_area = toBool(f.avoid_limit_area);
        values.video = toBool(f.video);

        if (PHOTO_INTERVAL_MODES.indexOf(f.photo_interval_mode) === -1) errors.photo_interval_mode = "Choose when the photos over the route are taken";
        else if (!f.photo_interval_mode) { values.photo_interval_mode = null; values.photo_interval = null; }
        else {
            var interval = toNumber(f.photo_interval), meters = f.photo_interval_mode === "distance";
            if (isNaN(interval) || interval < MIN_INTERVAL || interval > MAX_INTERVAL)
                errors.photo_interval = "The photo interval must be between " + MIN_INTERVAL + " and " + MAX_INTERVAL + (meters ? " m" : " seconds");
            else { values.photo_interval_mode = f.photo_interval_mode; values.photo_interval = interval; }
        }

        if (blank(f.takeoff_altitude)) values.takeoff_altitude = null;
        else {
            var altitude = toNumber(f.takeoff_altitude);
            if (isNaN(altitude) || altitude < -500 || altitude > 9000) errors.takeoff_altitude = "The ground height at the takeoff point must be a number of meters above sea level"; else values.takeoff_altitude = altitude;
        }
        values.takeoff_ellipsoidal_height = blank(f.takeoff_ellipsoidal_height) ? null : toNumber(f.takeoff_ellipsoidal_height);
        if (values.height_mode === "asl" && (values.takeoff_altitude === null || values.takeoff_ellipsoidal_height === null || isNaN(values.takeoff_ellipsoidal_height)))
            errors.height_mode = "Fetch the ground elevation at the takeoff point before using ASL";
        values.name = String(f.name || WAYPOINT_DEFAULTS.name);

        return {ok: Object.keys(errors).length === 0, errors: errors, values: values};
    }

    // Checks the settings of one point ({height, heading, pitch, hover: text, photo}); blank height, heading and pitch
    // mean the route's (null), a blank hover none. Headings are kept between -180 and 180 degrees.
    function parsePointForm(form, heightMode) {
        var errors = {}, values = {photo: toBool(form.photo)};
        if (blank(form.height)) values.height = null;
        else {
            var height = toNumber(form.height), message = heightError(height, heightMode, "The height");
            if (message) errors.height = message; else values.height = height;
        }
        if (blank(form.heading)) values.heading = null;
        else {
            var heading = toNumber(form.heading);
            if (isNaN(heading)) errors.heading = "The heading must be a number of degrees"; else values.heading = signedDegrees(heading);
        }
        if (blank(form.pitch)) values.pitch = null;
        else {
            var pitch = toNumber(form.pitch);
            if (isNaN(pitch) || pitch < MIN_PITCH || pitch > MAX_PITCH) errors.pitch = "The gimbal pitch must be between " + MIN_PITCH + " and " + MAX_PITCH + " degrees"; else values.pitch = pitch;
        }
        if (blank(form.hover)) values.hover = 0;
        else {
            var hover = toNumber(form.hover);
            if (isNaN(hover) || hover < 0 || hover > MAX_HOVER) errors.hover = "The hover must be between 0 and " + MAX_HOVER + " seconds"; else values.hover = hover;
        }
        return {ok: Object.keys(errors).length === 0, errors: errors, values: values};
    }

    function signedDegrees(d) { var r = ((d % 360) + 360) % 360; return r > 180 ? r - 360 : r; }

    // The first point whose own height does not fit the height mode (after the mode changed), as a message, or null
    function pointsError(points, heightMode) {
        for (var i = 0; i < points.length; i++) {
            var h = points[i].height;
            if (h !== null && h !== undefined && heightError(h, heightMode, "x")) return heightError(h, heightMode, "The height of point " + (i + 1));
        }
        return null;
    }

    function newPoint(lat, lon) { return {lat: lat, lon: lon, height: null, heading: null, pitch: null, photo: false, hover: 0, ground: null}; }

    // The editing of the points returns a new list, the old one untouched
    function addPoint(points, lat, lon) { return points.concat([newPoint(lat, lon)]); }

    // A new point halfway between point i and the next one (to 9 decimals, like imported points), or null when i is the last
    function insertAfter(points, i) {
        if (i < 0 || i >= points.length - 1) return null;
        var a = points[i], b = points[i + 1], copy = points.slice();
        copy.splice(i + 1, 0, newPoint(roundTo((a.lat + b.lat) / 2, 9), roundTo((a.lon + b.lon) / 2, 9)));
        return copy;
    }

    function deletePoint(points, i) { var copy = points.slice(); copy.splice(i, 1); return copy; }

    // A moved point loses its ground height: it is fetched again for the new place
    function movePoint(points, i, lat, lon) {
        var copy = points.slice();
        copy[i] = Object.assign({}, points[i], {lat: lat, lon: lon, ground: null});
        return copy;
    }

    function updatePoint(points, i, values) {
        var copy = points.slice();
        copy[i] = Object.assign({}, points[i], values);
        return copy;
    }

    // The indexes of the points with no ground height yet (needed by the AGL height mode)
    function missingGrounds(points) {
        var missing = [];
        points.forEach(function (p, i) { if (p.ground === null || p.ground === undefined) missing.push(i); });
        return missing;
    }

    // The middle of the points, [lat, lon] (to 9 decimals), where a new POI is put; null without any
    function pointsCenter(points) {
        if (!points || !points.length) return null;
        var lat = 0, lon = 0;
        points.forEach(function (p) { lat += p.lat; lon += p.lon; });
        return [roundTo(lat / points.length, 9), roundTo(lon / points.length, 9)];
    }

    // The box around the points, [[west, south], [east, north]], or null without any
    function pointsBounds(points) {
        if (!points || !points.length) return null;
        var lons = points.map(function (p) { return p.lon; }), lats = points.map(function (p) { return p.lat; });
        return [[Math.min.apply(null, lons), Math.min.apply(null, lats)], [Math.max.apply(null, lons), Math.max.apply(null, lats)]];
    }

    // The body of a plan/export request for a waypoint route, or null with fewer than 2 points or errors in the form
    // or the points. takeoff: [lat, lon] or null; model: the aircraft, whose cameras are the only ones sent; poi: [lat, lon],
    // needed by the Toward POI heading (which leaves out the points' own headings)
    function waypointRequestBody(points, form, takeoff, model, poi) {
        var parsed = parseWaypointForm(form);
        if (!parsed.ok || !points || points.length < 2) return null;
        var v = parsed.values, towardPoi = v.heading_mode === "towardPOI";
        if (pointsError(points, v.height_mode)) return null;
        if (towardPoi && !poi) return null;
        model = model || "m4t";
        var cameras = v.cameras.filter(function (c) { return GSD_PER_M_BY_MODEL[model][c] !== undefined; });
        if (!cameras.length) return null;

        var body = {
            route_type: "waypoint", model: model, name: v.name, cameras: cameras,
            points: points.map(function (p) {
                return {lat: p.lat, lon: p.lon, height: p.height === undefined ? null : p.height, heading: towardPoi || p.heading === undefined ? null : p.heading,
                        pitch: p.pitch === undefined ? null : p.pitch, photo: !!p.photo, hover: p.hover || 0, ground: p.ground === undefined ? null : p.ground};
            }),
            height: v.height, height_mode: v.height_mode, speed: v.speed, gimbal_pitch: v.gimbal_pitch, heading_mode: v.heading_mode,
            turn_mode: v.turn_mode, takeoff_mode: v.takeoff_mode, finish_action: v.finish_action, exit_on_rc_lost: v.exit_on_rc_lost,
            takeoff_security_height: v.takeoff_security_height, transitional_speed: v.transitional_speed, rth_height: v.rth_height,
            avoid_limit_area: v.avoid_limit_area, video: v.video, photo_interval_mode: v.photo_interval_mode,
            photo_interval: v.photo_interval,
            takeoff_ref_point: takeoff && v.takeoff_altitude !== null ? [takeoff[0], takeoff[1], v.takeoff_altitude] : null
        };
        if (v.height_mode === "asl") body.takeoff_ellipsoidal_height = v.takeoff_ellipsoidal_height;
        if (towardPoi) body.poi = [poi[0], poi[1]];
        return body;
    }

    // The results of a waypoint route in words: [{label, value}]
    function waypointSummaryRows(summary) {
        return [
            {label: "Points", value: String(summary.points)},
            {label: "Photos", value: String(summary.photos)},
            {label: "Speed", value: round(summary.speed, 1) + " m/s"},
            {label: "Flight", value: formatDistance(summary.length) + ", " + formatDuration(summary.duration)}
        ];
    }

    // -- POI routes ---------------------------------------------------------------------------------------------------
    // A POI route is a waypoint route whose points are made around a subject (settings.shape): a circle, a rectangle or
    // a drawn outline, centred on the POI. The path is the subject's outline pushed out by the distance, so its corners
    // are arcs; the points are one every 360/count degrees on the arcs, from the start bearing, clockwise, back to the
    // first point. Lengths are meters, kept as text like the rest of the form; the outline is [[lon, lat], ...].
    // Several loops (stacked loops) go from the route's height up to the top height, bottom up.
    var SHAPE_DEFAULTS = {kind: "circle", radius: "10", width: "20", length: "30", rotation: "0", height: "10", distance: "15",
                          count: "12", start: "0", overlap: "80", loops: "1", top: "", outline: [], edited: false};
    var SHAPE_KINDS = ["circle", "rectangle", "outline"];
    var MAX_SHAPE_COUNT = 72, MAX_LOOPS = 20;

    // Checks a shape ({field: text}); only the fields of its kind are needed
    function parseShapeForm(shape) {
        var f = Object.assign({}, SHAPE_DEFAULTS, shape), errors = {}, values = {};
        if (SHAPE_KINDS.indexOf(f.kind) === -1) errors.kind = "Choose the shape of the subject"; else values.kind = f.kind;
        function number(k, ok, message) { var n = toNumber(f[k]); if (isNaN(n) || !ok(n)) errors[k] = message; else values[k] = n; }
        if (f.kind === "circle") number("radius", function (n) { return n >= 0; }, "The radius must be a number of meters, 0 or more");
        if (f.kind === "rectangle") {
            number("width", function (n) { return n > 0; }, "The width must be more than 0 m");
            number("length", function (n) { return n > 0; }, "The length must be more than 0 m");
            number("rotation", function () { return true; }, "The rotation must be a number of degrees");
        }
        if (f.kind === "outline") {
            var outline = (f.outline || []).filter(function (p) { return p && isFinite(p[0]) && isFinite(p[1]); });
            if (outline.length < 3) errors.outline = "Draw the outline of the subject: at least 3 points"; else values.outline = outline;
        }
        number("height", function (n) { return n >= 0; }, "The subject's height must be a number of meters, 0 or more");
        number("distance", function (n) { return n > 0; }, "The distance from the subject must be more than 0 m");
        number("count", function (n) { return n >= 3 && n <= MAX_SHAPE_COUNT && n === Math.round(n); }, "The points per turn must be a whole number from 3 to " + MAX_SHAPE_COUNT);
        number("start", function () { return true; }, "The start bearing must be a number of degrees");
        number("overlap", function (n) { return n >= 10 && n <= 95; }, "The overlap must be between 10 and 95 %");
        number("loops", function (n) { return n >= 1 && n <= MAX_LOOPS && n === Math.round(n); }, "The loops must be a whole number from 1 to " + MAX_LOOPS);
        if (values.loops > 1) number("top", function () { return true; }, "Give the height of the highest loop");
        return {ok: Object.keys(errors).length === 0, errors: errors, values: values};
    }

    // A local frame in meters around the POI ([lat, lon]): x east, y north (as in stripPolygon)
    function poiFrame(poi) {
        var rad = Math.PI / 180, mx = 6371000 * rad * Math.cos(poi[0] * rad), my = 6371000 * rad;
        return {
            toXY: function (p) { return [(p[0] - poi[1]) * mx, (p[1] - poi[0]) * my]; },
            toLonLat: function (x, y) { return [poi[1] + x / mx, poi[0] + y / my]; }
        };
    }

    // The convex hull of [[x, y], ...], clockwise (monotone chain)
    function hullClockwise(pts) {
        var sorted = pts.slice().sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
        function cross(o, a, b) { return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); }
        function half(list) {
            var h = [];
            list.forEach(function (p) {
                while (h.length >= 2 && cross(h[h.length - 2], h[h.length - 1], p) <= 1e-9) h.pop();
                h.push(p);
            });
            h.pop();
            return h;
        }
        var ccw = half(sorted).concat(half(sorted.slice().reverse()));
        return ccw.reverse();
    }

    // The subject's corners in the POI's frame, clockwise, and how far the path is from them
    function shapeVertices(poi, s) {
        if (s.kind === "circle") return {vertices: [[0, 0]], offset: s.radius + s.distance};
        if (s.kind === "rectangle") {
            var r = s.rotation * Math.PI / 180, d = [Math.sin(r), Math.cos(r)], w = [Math.cos(r), -Math.sin(r)];
            var corner = function (a, b) { return [a * s.length / 2 * d[0] + b * s.width / 2 * w[0], a * s.length / 2 * d[1] + b * s.width / 2 * w[1]]; };
            return {vertices: [corner(1, -1), corner(1, 1), corner(-1, 1), corner(-1, -1)], offset: s.distance};
        }
        var frame = poiFrame(poi), hull = hullClockwise(s.outline.map(frame.toXY));
        return hull.length >= 3 ? {vertices: hull, offset: s.distance} : null;
    }

    function degrees(rad) { return ((rad * 180 / Math.PI) % 360 + 360) % 360; }

    // The arcs of the path: {c: [x, y], from: bearing, span: degrees}, clockwise, one at each corner
    function shapeArcs(vertices) {
        if (vertices.length === 1) return [{c: vertices[0], from: 0, span: 360}];
        var n = vertices.length, normals = [];
        for (var i = 0; i < n; i++) {
            var a = vertices[i], b = vertices[(i + 1) % n];
            normals.push(degrees(Math.atan2(-(b[1] - a[1]), b[0] - a[0])));     // bearing of the left normal (-ey, ex)
        }
        return vertices.map(function (v, k) {
            var from = normals[(k + n - 1) % n];
            return {c: v, from: from, span: ((normals[k] - from) % 360 + 360) % 360};
        });
    }

    function arcPoint(arc, bearingDeg, r) {
        var b = bearingDeg * Math.PI / 180;
        return [arc.c[0] + r * Math.sin(b), arc.c[1] + r * Math.cos(b)];
    }

    // Where the ray from the POI at the start bearing last crosses the path: {arc: k, at: degrees into it} or
    // {side: k, point: [x, y]} (the side after arc k), or null
    function startHit(arcs, r, startDeg) {
        var b = startDeg * Math.PI / 180, u = [Math.sin(b), Math.cos(b)], best = null;
        arcs.forEach(function (arc, k) {
            var uc = u[0] * arc.c[0] + u[1] * arc.c[1], disc = uc * uc - (arc.c[0] * arc.c[0] + arc.c[1] * arc.c[1]) + r * r;
            if (disc < 0) return;
            var t = uc + Math.sqrt(disc);
            if (t <= 0) return;
            var at = (degrees(Math.atan2(t * u[0] - arc.c[0], t * u[1] - arc.c[1])) - arc.from + 360) % 360;
            if (at > arc.span + 1e-6 && arc.span < 360) return;
            if (!best || t > best.t) best = {t: t, arc: k, at: Math.min(at, arc.span)};
        });
        arcs.forEach(function (arc, k) {
            if (arcs.length === 1) return;
            var next = arcs[(k + 1) % arcs.length], p = arcPoint(arc, arc.from + arc.span, r), q = arcPoint(next, next.from, r);
            var e = [q[0] - p[0], q[1] - p[1]], den = u[0] * e[1] - u[1] * e[0];
            if (Math.abs(den) < 1e-12) return;
            var t = (p[0] * e[1] - p[1] * e[0]) / den, s = (p[0] * u[1] - p[1] * u[0]) / den;
            if (t <= 0 || s < 0 || s > 1) return;
            if (!best || t > best.t) best = {t: t, side: k, point: [t * u[0], t * u[1]]};
        });
        return best;
    }

    // The points around the subject, as new points ([] when the shape is not complete), or null with errors in it.
    // poi: [lat, lon]; shape: the form's text, checked by parseShapeForm.
    function poiShapePoints(poi, shape) {
        var parsed = parseShapeForm(shape);
        if (!parsed.ok || !poi) return null;
        var s = parsed.values, geometry = shapeVertices(poi, s);
        if (!geometry) return null;
        var r = geometry.offset, step = 360 / s.count, arcs = shapeArcs(geometry.vertices), n = arcs.length;

        // The pieces flown, in order: arcs (or parts of them), and the start point when it is on a side
        var pieces = [], hit = startHit(arcs, r, s.start), k;
        if (!hit) hit = {arc: 0, at: 0};
        if (hit.arc !== undefined && n === 1) {
            pieces.push({c: arcs[0].c, from: arcs[0].from + hit.at, span: 360});
        } else if (hit.arc !== undefined) {
            var arc = arcs[hit.arc], at = hit.at, first = hit.arc;
            if (at < step / 2) at = 0;
            else if (arc.span - at < step / 2) { at = 0; first = (hit.arc + 1) % n; }
            if (at > 0) pieces.push({c: arc.c, from: arc.from + at, span: arc.span - at});
            for (k = 0; k < n; k++) {
                var i = (first + k + (at > 0 ? 1 : 0)) % n;
                if (at > 0 && i === first) break;
                pieces.push(arcs[i]);
            }
            if (at > 0) pieces.push({c: arc.c, from: arc.from, span: at});
        } else {
            pieces.push({point: hit.point});
            for (k = 1; k <= n; k++) pieces.push(arcs[(hit.side + k) % n]);
        }

        var xy = [];
        pieces.forEach(function (piece) {
            if (piece.point) { xy.push(piece.point); return; }
            var parts = Math.max(1, Math.round(piece.span / step - 1e-9));
            for (var j = 0; j <= parts; j++) xy.push(arcPoint(piece, piece.from + piece.span * j / parts, r));
        });
        var close = function (a, b) { return Math.abs(a[0] - b[0]) < 0.01 && Math.abs(a[1] - b[1]) < 0.01; };
        xy = xy.filter(function (p, j) { return j === 0 || !close(p, xy[j - 1]); });
        if (!close(xy[0], xy[xy.length - 1])) xy.push(xy[0]);

        var frame = poiFrame(poi);
        return xy.map(function (p) {
            var ll = frame.toLonLat(p[0], p[1]);
            return newPoint(roundTo(ll[1], 9), roundTo(ll[0], 9));
        });
    }

    // The subject's outline as a closed ring [[lon, lat], ...] for the map, or null with errors in the shape
    function subjectRing(poi, shape) {
        var parsed = parseShapeForm(shape);
        if (!parsed.ok || !poi) return null;
        var s = parsed.values, frame = poiFrame(poi), ring;
        if (s.kind === "outline") ring = s.outline.map(function (p) { return [p[0], p[1]]; });
        else if (s.kind === "rectangle") ring = shapeVertices(poi, s).vertices.map(function (v) { return frame.toLonLat(v[0], v[1]); });
        else {
            ring = [];
            for (var a = 0; a < 360; a += 5) ring.push(frame.toLonLat(s.radius * Math.sin(a * Math.PI / 180), s.radius * Math.cos(a * Math.PI / 180)));
        }
        ring.push(ring[0]);
        return ring;
    }

    // The middle of a drawn outline ([[lon, lat], ...]), [lat, lon] to 9 decimals, where its POI is put
    function outlineCenter(outline) {
        if (!outline || !outline.length) return null;
        var lat = 0, lon = 0;
        outline.forEach(function (p) { lon += p[0]; lat += p[1]; });
        return [roundTo(lat / outline.length, 9), roundTo(lon / outline.length, 9)];
    }

    // The outline moved with its POI, from one [lat, lon] to another
    function shiftOutline(outline, from, to) {
        return (outline || []).map(function (p) { return [roundTo(p[0] + to[1] - from[1], 9), roundTo(p[1] + to[0] - from[0], 9)]; });
    }

    // The heights of `loops` loops spread evenly from `low` to `top`, bottom up (meters, to the centimetre)
    function poiLoopHeights(low, top, loops) {
        if (loops <= 1) return [low];
        var out = [];
        for (var i = 0; i < loops; i++) out.push(roundTo(low + (top - low) * i / (loops - 1), 2));
        return out;
    }

    // The points of one loop repeated at each height, with each loop's pitch (pitches[i], or null): the next loop
    // starts straight above where the last one ended, so the aircraft climbs on the spot
    function stackLoops(points, heights, pitches) {
        var out = [];
        heights.forEach(function (h, i) {
            points.forEach(function (p) {
                out.push(Object.assign({}, p, {height: h, pitch: pitches && pitches[i] !== undefined ? pitches[i] : null}));
            });
        });
        return out;
    }

    // The gimbal pitch of one of several loops: it aims at the subject level with the loop, or at its top from above
    function poiLoopPitch(flightHeight, subjectHeight, distance) {
        if (flightHeight === null || flightHeight === undefined || !isFinite(flightHeight)) return null;
        return poiPitch(flightHeight, 2 * Math.min(Math.max(flightHeight, 0), subjectHeight), distance);
    }

    // The gimbal pitch that aims at half the subject's height from `distance` meters away, flying `flightHeight` meters
    // above the subject's base (null when that is not known)
    function poiPitch(flightHeight, subjectHeight, distance) {
        if (flightHeight === null || flightHeight === undefined || !isFinite(flightHeight) || !(distance > 0)) return null;
        var pitch = -Math.atan((flightHeight - subjectHeight / 2) / distance) * 180 / Math.PI;
        return roundTo(Math.min(MAX_PITCH, Math.max(MIN_PITCH, pitch)), 1) + 0;     // + 0: not -0
    }

    // The distance between photos for `overlap` % between them, at `distance` meters from the subject: the width a
    // photo covers there, of the narrowest of the cameras (as singleLineHeight); null without a camera
    function poiPhotoSpacing(cameras, distance, overlap, model) {
        model = model || "m4t";
        var widths = modelCameras(cameras, model).map(function (c) { return GSD_PER_M_BY_MODEL[model][c] * PIXELS_ACROSS_BY_MODEL[model][c]; });
        if (!widths.length) return null;
        return roundTo(Math.max(MIN_INTERVAL, distance * Math.min.apply(null, widths) * (1 - overlap / 100)), 1);
    }

    // The number of loops from `low` to `top` for `overlap` % between them, at `distance` meters from the subject: the
    // height a photo covers there, of the narrowest of the cameras; null without a camera
    function poiSuggestedLoops(cameras, distance, overlap, low, top, model) {
        model = model || "m4t";
        var heights = modelCameras(cameras, model).map(function (c) { return GSD_PER_M_BY_MODEL[model][c] * PIXELS_DOWN_BY_MODEL[model][c]; });
        if (!heights.length || !(distance > 0)) return null;
        var step = distance * Math.min.apply(null, heights) * (1 - overlap / 100);
        return Math.min(MAX_LOOPS, Math.ceil(Math.abs(top - low) / step - 1e-9) + 1);
    }

    // -- linear routes -----------------------------------------------------------------------------------------------
    // A linear route flies lines along a strip drawn around a center line (app/missions/linear.py): the Area form's
    // settings, without the direction, margin, photo mode and oblique collection, plus the strip's widths.
    var LINEAR_DEFAULTS = Object.assign({}, DEFAULTS, {name: "luxodm-linear", left_extend: "50", right_extend: "50", single_line: "false"});
    var MAX_LINE_POINTS = 500;
    // Pixels across the flight lines of each camera: with GSD_PER_M, the width a photo covers per meter of height
    var PIXELS_ACROSS_BY_MODEL = byCamera(function (c) { return c.px_w; });
    // ... and along them (a photo's height, with the camera level: the height it covers on a subject's face)
    var PIXELS_DOWN_BY_MODEL = byCamera(function (c) { return c.px_h; });

    // The cameras of a form's lenses that the aircraft has
    function modelCameras(cameras, model) {
        return (cameras || []).filter(function (c) { return GSD_PER_M_BY_MODEL[model][c] !== undefined; });
    }

    // The height at which one photo of every camera covers the strip's width (the server's single_line_height)
    function singleLineHeight(cameras, left, right, model) {
        model = model || "m4t";
        var widths = modelCameras(cameras, model).map(function (c) { return GSD_PER_M_BY_MODEL[model][c] * PIXELS_ACROSS_BY_MODEL[model][c]; });
        return widths.length ? (left + right) / Math.min.apply(null, widths) : null;
    }

    // Checks the form of a linear route, as parseForm does for an area. With a single line, the height is the one
    // that covers the strip (values.height), not the one typed.
    function parseLinearForm(form, model) {
        var f = Object.assign({}, LINEAR_DEFAULTS, form, {direction: "0", margin: "0", photo_mode: "distance", collection_mode: "ortho"});
        var parsed = parseForm(f), errors = parsed.errors, values = parsed.values;
        delete values.direction; delete values.margin; delete values.photo_mode; delete values.collection_mode;
        delete values.gimbal_pitch; delete values.inclined_overlap_h; delete values.inclined_overlap_w; delete values.inclined_speed;

        ["left_extend", "right_extend"].forEach(function (k) {
            var n = toNumber(f[k]);
            if (isNaN(n) || n < 0) errors[k] = "The strip's width to the " + (k === "left_extend" ? "left" : "right") + " must be a number of meters, 0 or more";
            else values[k] = n;
        });
        if (values.left_extend !== undefined && values.right_extend !== undefined && values.left_extend + values.right_extend <= 0)
            errors.left_extend = "The strip needs a width";
        values.single_line = toBool(f.single_line);
        if (values.single_line) {
            delete errors.height;
            var height = values.cameras && values.left_extend !== undefined && values.right_extend !== undefined
                ? singleLineHeight(values.cameras, values.left_extend, values.right_extend, model) : null;
            if (height !== null && (height < LIMITS.height[0] || height > LIMITS.height[1]))
                errors.height = "One line over this strip would be flown at " + Math.round(height) + " m: the height must be between " + LIMITS.height[0] + " and " + LIMITS.height[1] + " m";
            else if (height !== null) values.height = height;
        }
        values.name = String(form.name || LINEAR_DEFAULTS.name);
        return {ok: Object.keys(errors).length === 0, errors: errors, values: values};
    }

    // The body of a plan/export request for a linear route, or null with fewer than 2 points or errors in the form.
    // line: [[lon, lat], ...]; takeoff: [lat, lon] or null; model: the aircraft, whose cameras are the only ones sent
    function linearRequestBody(line, form, takeoff, model) {
        model = model || "m4t";
        var parsed = parseLinearForm(form, model);
        if (!parsed.ok || !line || line.length < 2 || line.length > MAX_LINE_POINTS) return null;
        var v = parsed.values, cameras = modelCameras(v.cameras, model);
        if (!cameras.length) return null;
        var body = {
            route_type: "linear", model: model, name: v.name, cameras: cameras, line: line.map(function (p) { return [p[0], p[1]]; }),
            left_extend: v.left_extend, right_extend: v.right_extend, single_line: v.single_line, height: v.height,
            overlap_h: v.overlap_h, overlap_w: v.overlap_w, speed: v.speed, height_mode: v.height_mode,
            takeoff_security_height: v.takeoff_security_height, rth_height: v.rth_height, finish_action: v.finish_action,
            exit_on_rc_lost: v.exit_on_rc_lost, transitional_speed: v.transitional_speed, takeoff_mode: v.takeoff_mode,
            elevation_optimize: v.elevation_optimize, avoid_limit_area: v.avoid_limit_area, surface_follow: v.surface_follow,
            takeoff_ref_point: takeoff && v.takeoff_altitude !== null ? [takeoff[0], takeoff[1], v.takeoff_altitude] : null
        };
        if (v.altitude_mode === "asl") body.takeoff_ellipsoidal_height = v.takeoff_ellipsoidal_height;
        return body;
    }

    // The strip around a center line ([[lon, lat], ...]) as a closed ring, `left` and `right` meters to each side,
    // for the map to show. The corners are mitred (the planner cuts the outside ones, so this is a little wider there).
    function stripPolygon(line, left, right) {
        if (!line || line.length < 2 || !(left + right > 0)) return null;
        var rad = Math.PI / 180, lat0 = line[0][1] * rad, mx = 6371000 * rad * Math.cos(lat0), my = 6371000 * rad;
        var pts = line.map(function (p) { return [(p[0] - line[0][0]) * mx, (p[1] - line[0][1]) * my]; });
        var dirs = [];
        for (var i = 0; i < pts.length - 1; i++) {
            var dx = pts[i + 1][0] - pts[i][0], dy = pts[i + 1][1] - pts[i][1], d = Math.sqrt(dx * dx + dy * dy);
            dirs.push(d > 0 ? [dx / d, dy / d] : (dirs.length ? dirs[dirs.length - 1] : null));
        }
        var first = null;
        for (var j = 0; j < dirs.length && !first; j++) first = dirs[j];
        if (!first) return null;
        for (var k = 0; k < dirs.length; k++) dirs[k] = dirs[k] || first;
        // The left normal at each point: the bisector of the normals of its two segments, lengthened to keep the width
        var normals = pts.map(function (p, n) {
            var a = dirs[Math.max(0, n - 1)], b = dirs[Math.min(dirs.length - 1, n)];
            var nx = -(a[1] + b[1]), ny = a[0] + b[0], len = Math.sqrt(nx * nx + ny * ny);
            if (len < 1e-9) return [-b[1], b[0]];
            var cos = Math.max(0.25, (nx * -b[1] + ny * b[0]) / len);
            return [nx / len / cos, ny / len / cos];
        });
        var toLonLat = function (x, y) { return [line[0][0] + x / mx, line[0][1] + y / my]; };
        var ring = pts.map(function (p, n) { return toLonLat(p[0] + normals[n][0] * left, p[1] + normals[n][1] * left); });
        for (var m = pts.length - 1; m >= 0; m--) ring.push(toLonLat(pts[m][0] - normals[m][0] * right, pts[m][1] - normals[m][1] * right));
        ring.push(ring[0]);
        return ring;
    }

    function lineLength(line) {
        var total = 0;
        for (var i = 0; line && i < line.length - 1; i++) total += distance(line[i], line[i + 1]);
        return total;
    }

    // The box around a center line, [[west, south], [east, north]], or null with fewer than 2 points
    function lineBounds(line) {
        if (!line || line.length < 2) return null;
        var lons = line.map(function (p) { return p[0]; }), lats = line.map(function (p) { return p[1]; });
        return [[Math.min.apply(null, lons), Math.min.apply(null, lats)], [Math.max.apply(null, lons), Math.max.apply(null, lats)]];
    }

    // The results of a linear route in words: [{label, value}]
    function linearSummaryRows(summary) {
        var rows = [
            {label: "Flight lines", value: String(summary.lines)},
            {label: "Distance between lines", value: summary.lines > 1 ? round(summary.spacing, 2) + " m" : ""},
            {label: "Height", value: round(summary.height, 1) + " m"},
            {label: "Pass along the bends", value: summary.bend_pass ? "yes, camera at -45°" : "no"},
            {label: "A photo every", value: round(summary.interval, 2) + " m"},
            {label: "Photos", value: String(summary.photos)},
            {label: "Speed", value: round(summary.speed, 1) + " m/s (at most " + round(summary.max_speed, 1) + " m/s)"},
            {label: "Flight", value: formatDistance(summary.distance) + ", " + formatDuration(summary.duration)}
        ];
        Object.keys(summary.gsd || {}).forEach(function (k) {
            var cm = summary.gsd[k] * 100;
            rows.push({label: "Pixel size, " + (CAMERA_LABELS[k] || k), value: round(cm, cm < 1 ? 2 : 1) + " cm"});
        });
        return rows.filter(function (r) { return r.value !== ""; });
    }

    // -- slope routes ------------------------------------------------------------------------------------------------
    // A slope route maps a steep face square-on (app/missions/slope.py): the face is drawn as an area, each corner with its
    // height (WGS84-ellipsoidal, as Pilot 2 writes them and a task's DSM gives them), and the height is the distance
    // flown out from the face. The Area form's settings, without the direction, margin, photo mode, oblique collection,
    // height mode and elevation optimization.
    var SLOPE_DEFAULTS = Object.assign({}, DEFAULTS, {name: "luxodm-slope", height: "30", overlap_w: "80", altitude_mode: "face"});
    var MAX_CORNERS = 50;

    function parseSlopeForm(form) {
        var f = Object.assign({}, SLOPE_DEFAULTS, form, {altitude_mode: "alt", direction: "0", margin: "0", photo_mode: "distance",
                                                          collection_mode: "ortho", surface_follow: "realtime"});
        var parsed = parseForm(f), errors = parsed.errors, values = parsed.values;
        ["direction", "margin", "photo_mode", "collection_mode", "gimbal_pitch", "inclined_overlap_h", "inclined_overlap_w",
         "inclined_speed", "altitude_mode", "height_mode", "elevation_optimize", "surface_follow", "takeoff_ellipsoidal_height"]
            .forEach(function (k) { delete values[k]; });
        if (errors.height) errors.height = "The distance from the face must be between " + LIMITS.height[0] + " and " + LIMITS.height[1] + " m";
        if (errors.takeoff_altitude) errors.takeoff_altitude = "The ground height at the takeoff point must be a number of meters";
        values.name = String(form.name || SLOPE_DEFAULTS.name);
        return {ok: Object.keys(errors).length === 0, errors: errors, values: values};
    }

    // What is missing from the corners ([[lon, lat], ...]) and their heights ([h or null, ...]), or null
    function cornersError(corners, heights) {
        if (!corners || corners.length < 3) return "Draw the slope on the map";
        if (corners.length > MAX_CORNERS) return "The slope has too many corners (at most " + MAX_CORNERS + ")";
        var missing = corners.filter(function (c, i) { return !heights || typeof heights[i] !== "number" || !isFinite(heights[i]); }).length;
        return missing ? "Give every corner its height (" + missing + " of " + corners.length + " missing): type them, or take them from a task's DSM" : null;
    }

    // The heights of corners drawn again: a corner that did not move keeps its height, the others have none
    function keptHeights(oldCorners, oldHeights, newCorners) {
        return (newCorners || []).map(function (c) {
            for (var i = 0; oldCorners && i < oldCorners.length; i++) {
                if (oldCorners[i][0] === c[0] && oldCorners[i][1] === c[1]) return oldHeights ? (oldHeights[i] === undefined ? null : oldHeights[i]) : null;
            }
            return null;
        });
    }

    // The body of a plan/export request for a slope route, or null while a corner has no height or the form has errors.
    // corners: [[lon, lat], ...]; heights: [h, ...]; takeoff: [lat, lon] or null; model: the aircraft
    function slopeRequestBody(corners, heights, form, takeoff, model) {
        model = model || "m4t";
        var parsed = parseSlopeForm(form);
        if (!parsed.ok || cornersError(corners, heights)) return null;
        var v = parsed.values, cameras = modelCameras(v.cameras, model);
        if (!cameras.length) return null;
        return {
            route_type: "slope", model: model, name: v.name, cameras: cameras,
            corners: corners.map(function (c, i) { return [c[0], c[1], heights[i]]; }), height: v.height,
            overlap_h: v.overlap_h, overlap_w: v.overlap_w, speed: v.speed, takeoff_security_height: v.takeoff_security_height,
            rth_height: v.rth_height, finish_action: v.finish_action, exit_on_rc_lost: v.exit_on_rc_lost,
            transitional_speed: v.transitional_speed, takeoff_mode: v.takeoff_mode, avoid_limit_area: v.avoid_limit_area,
            takeoff_ref_point: takeoff && v.takeoff_altitude !== null ? [takeoff[0], takeoff[1], v.takeoff_altitude] : null
        };
    }

    var COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
    function compassPoint(degrees) { return COMPASS[Math.round((((degrees % 360) + 360) % 360) / 45) % 8]; }

    // The results of a slope route in words: [{label, value}]
    function slopeSummaryRows(summary) {
        var heading = ((summary.heading % 360) + 360) % 360;
        var rows = [
            {label: "Slope", value: round(summary.slope, 1) + "°"},
            {label: "Camera", value: "facing " + compassPoint(heading) + " (" + Math.round(heading) + "°), tilted " + summary.pitch + "°"},
            {label: "Flight lines", value: String(summary.lines)},
            {label: "Distance between lines", value: summary.lines > 1 ? round(summary.spacing, 2) + " m" : ""},
            {label: "Distance from the face", value: round(summary.height, 1) + " m"},
            {label: "A photo every", value: round(summary.interval, 2) + " m"},
            {label: "Photos", value: String(summary.photos)},
            {label: "Speed", value: round(summary.speed, 1) + " m/s (at most " + round(summary.max_speed, 1) + " m/s)"},
            {label: "Flight", value: formatDistance(summary.distance) + ", " + formatDuration(summary.duration)}
        ];
        Object.keys(summary.gsd || {}).forEach(function (k) {
            var cm = summary.gsd[k] * 100;
            rows.push({label: "Pixel size, " + (CAMERA_LABELS[k] || k), value: round(cm, cm < 1 ? 2 : 1) + " cm"});
        });
        return rows.filter(function (r) { return r.value !== ""; });
    }

    // The route seen from the side (the server's profile: the face's top and bottom and each line, as [out, h]) as an
    // SVG of width x height pixels, to scale: the face, each line's point, and the camera's view to the face from it.
    // A geometric route's profile can also have the roof's lines ("roof": from the wall inwards, above the top), drawn
    // with the top and the view straight down to it.
    function profileSvg(profile, width, height) {
        if (!profile || !profile.face || profile.face.length !== 2) return "";
        var face = profile.face, lines = profile.lines || [], roof = profile.roof && profile.roof.length === 2 ? profile.roof : null, margin = 24;
        var all = face.concat(lines, roof ? roof.concat([[roof[0][0], face[0][1]]]) : []);
        var xs = all.map(function (p) { return p[0]; }), ys = all.map(function (p) { return p[1]; });
        var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs), minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
        var scale = Math.min((width - 2 * margin) / Math.max(maxX - minX, 1), (height - 2 * margin) / Math.max(maxY - minY, 1));
        var left = (width - (maxX - minX) * scale) / 2, top = (height - (maxY - minY) * scale) / 2;
        function x(p) { return round(left + (p[0] - minX) * scale, 1); }
        function y(p) { return round(height - top - (p[1] - minY) * scale, 1); }
        var a = face[0], b = face[1], dx = b[0] - a[0], dy = b[1] - a[1], dd = dx * dx + dy * dy || 1;
        function foot(p) { var s = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / dd; return [a[0] + s * dx, a[1] + s * dy]; }

        var parts = ['<svg xmlns="http://www.w3.org/2000/svg" class="mp-profile-svg" width="' + width + '" height="' + height +
                     '" viewBox="0 0 ' + width + " " + height + '">'];
        lines.forEach(function (p) {
            var f = foot(p);
            parts.push('<line class="mp-profile-view" x1="' + x(p) + '" y1="' + y(p) + '" x2="' + x(f) + '" y2="' + y(f) + '"/>');
        });
        if (roof) {
            var r0 = roof[0], r1 = roof[1], t0 = [r0[0], a[1]], mid = [(r0[0] + r1[0]) / 2, r0[1]], under = [mid[0], a[1]];
            parts.push('<line class="mp-profile-view" x1="' + x(mid) + '" y1="' + y(mid) + '" x2="' + x(under) + '" y2="' + y(under) + '"/>');
            parts.push('<line class="mp-profile-face" x1="' + x(t0) + '" y1="' + y(t0) + '" x2="' + x(a) + '" y2="' + y(a) + '"/>');
            parts.push('<line class="mp-profile-roof" x1="' + x(r0) + '" y1="' + y(r0) + '" x2="' + x(r1) + '" y2="' + y(r1) + '"/>');
        }
        parts.push('<line class="mp-profile-face" x1="' + x(a) + '" y1="' + y(a) + '" x2="' + x(b) + '" y2="' + y(b) + '"/>');
        lines.forEach(function (p) { parts.push('<circle class="mp-profile-point" cx="' + x(p) + '" cy="' + y(p) + '" r="2"/>'); });
        parts.push('<text class="mp-profile-label" x="' + x(a) + '" y="' + (y(a) - 6) + '">' + round(a[1], 1) + " m</text>");
        parts.push('<text class="mp-profile-label" x="' + x(b) + '" y="' + (y(b) + 14) + '">' + round(b[1], 1) + " m</text>");
        parts.push("</svg>");
        return parts.join("");
    }

    // -- geometric routes -------------------------------------------------------------------------------------------
    // A geometric route maps a block (a building) all round in level loops (app/missions/geometric.py): its outline is
    // drawn as an area, with the heights of its base and of its top (WGS84-ellipsoidal, as for a slope), and the height
    // is the distance flown out from the walls, and above the roof when it is mapped too (Smart Oblique, before the
    // walls). The slope form's settings, with the base, the top and the roof.
    var GEOMETRIC_DEFAULTS = Object.assign({}, DEFAULTS, {name: "luxodm-geometric", height: "10", overlap_w: "80",
                                                          altitude_mode: "walls", base: "", top: "", roof: "true"});
    var MIN_BLOCK = 0.5, MAX_BLOCK = 500;

    function parseGeometricForm(form) {
        var parsed = parseSlopeForm(Object.assign({}, GEOMETRIC_DEFAULTS, form)), errors = parsed.errors, values = parsed.values;
        if (errors.height) errors.height = "The distance from the walls must be between " + LIMITS.height[0] + " and " + LIMITS.height[1] + " m";
        var base = String(form.base === undefined ? "" : form.base).trim(), top = String(form.top === undefined ? "" : form.top).trim();
        values.base = base === "" ? NaN : Number(base);
        values.top = top === "" ? NaN : Number(top);
        if (!isFinite(values.base) || !isFinite(values.top)) errors.base = "Give the heights of the base and of the top: type them, or take them from a task's DSM";
        else if (!(values.top - values.base >= MIN_BLOCK && values.top - values.base <= MAX_BLOCK))
            errors.top = "The top must be between " + MIN_BLOCK + " and " + MAX_BLOCK + " m above the base";
        values.roof = toBool(form.roof === undefined ? GEOMETRIC_DEFAULTS.roof : form.roof);
        values.name = String(form.name || GEOMETRIC_DEFAULTS.name);
        return {ok: Object.keys(errors).length === 0, errors: errors, values: values};
    }

    // What is missing from a block's outline ([[lon, lat], ...]), or null
    function outlineError(outline) {
        if (!outline || outline.length < 3) return "Draw the block's outline on the map";
        if (outline.length > MAX_CORNERS) return "The outline has too many corners (at most " + MAX_CORNERS + ")";
        return null;
    }

    // The body of a plan/export request for a geometric route, or null while the outline or the form is not complete.
    // outline: [[lon, lat], ...]; takeoff: [lat, lon] or null; model: the aircraft
    function geometricRequestBody(outline, form, takeoff, model) {
        model = model || "m4t";
        var parsed = parseGeometricForm(form);
        if (!parsed.ok || outlineError(outline)) return null;
        var v = parsed.values, cameras = modelCameras(v.cameras, model);
        if (!cameras.length) return null;
        return {
            route_type: "geometric", model: model, name: v.name, cameras: cameras,
            outline: outline.map(function (c) { return [c[0], c[1]]; }), base: v.base, top: v.top, height: v.height, roof: v.roof,
            overlap_h: v.overlap_h, overlap_w: v.overlap_w, speed: v.speed, takeoff_security_height: v.takeoff_security_height,
            rth_height: v.rth_height, finish_action: v.finish_action, exit_on_rc_lost: v.exit_on_rc_lost,
            transitional_speed: v.transitional_speed, takeoff_mode: v.takeoff_mode, avoid_limit_area: v.avoid_limit_area,
            takeoff_ref_point: takeoff && v.takeoff_altitude !== null ? [takeoff[0], takeoff[1], v.takeoff_altitude] : null
        };
    }

    // The results of a geometric route in words: [{label, value}]
    function geometricSummaryRows(summary) {
        var rows = [
            {label: "Block", value: round(summary.top - summary.base, 1) + " m high (" + round(summary.base, 1) + " to " + round(summary.top, 1) + " m)"},
            {label: "Loops", value: String(summary.loops)},
            {label: "Distance between loops", value: summary.loops > 1 ? round(summary.spacing, 2) + " m" : ""},
            {label: "Distance from the walls", value: round(summary.height, 1) + " m (" + round(summary.closest, 1) + " m at the closest corner)"},
            {label: "A photo every", value: round(summary.interval, 2) + " m"},
            {label: "Roof", value: summary.roof_lines ? summary.roof_lines + " lines " + round(summary.roof_spacing, 2) + " m apart, " +
                                   round(summary.height, 1) + " m above the top, " + summary.roof_photos + " photos (Smart Oblique)" : "Not mapped"},
            {label: "Photos", value: String(summary.photos)},
            {label: "Speed", value: round(summary.speed, 1) + " m/s (at most " + round(summary.max_speed, 1) + " m/s)"},
            {label: "Flight", value: formatDistance(summary.distance) + ", " + formatDuration(summary.duration)}
        ];
        Object.keys(summary.gsd || {}).forEach(function (k) {
            var cm = summary.gsd[k] * 100;
            rows.push({label: "Pixel size, " + (CAMERA_LABELS[k] || k), value: round(cm, cm < 1 ? 2 : 1) + " cm"});
        });
        return rows.filter(function (r) { return r.value !== ""; });
    }

    // -- ASL without the takeoff point's ground height (both editors) ---------------------------------------------------
    // s: {asl: the ASL mode picked, takeoff: a takeoff point set, altitude, ellipsoidal: the form's takeoff_altitude and
    // takeoff_ellipsoidal_height (strings), fetching: a fetch on its way, failed: the last automatic fetch's error or
    // null}. ASL needs both heights, and only "Fetch from elevation data" writes the ellipsoidal one: a typed height
    // is not enough.

    function aslReady(s) {
        return String(s.altitude == null ? "" : s.altitude).trim() !== "" && String(s.ellipsoidal == null ? "" : s.ellipsoidal).trim() !== "";
    }

    // The hint shown under the takeoff height field and under the ASL button, or "" when none is needed
    function aslHint(s) {
        if (!s.asl || aslReady(s)) return "";
        if (!s.takeoff) return "ASL needs the ground height at the takeoff point: set the takeoff point, then fetch its height.";
        if (s.fetching) return "Fetching the ground height at the takeoff point…";
        if (s.failed) return "The ground height at the takeoff point could not be fetched: " + s.failed + ". Try Fetch from elevation data again.";
        if (String(s.altitude == null ? "" : s.altitude).trim() !== "")
            return "ASL needs the ground height fetched with Fetch from elevation data: a typed height is not enough.";
        return "ASL needs the ground height at the takeoff point: Fetch from elevation data.";
    }

    // Whether to fetch the height without being asked: the ASL mode just picked, or the takeoff point just set while
    // it is picked (never on opening a route), with a takeoff point and no height, and no fetch on its way
    function aslAutoFetch(s) {
        return !!(s.asl && s.takeoff && !s.fetching && !aslReady(s));
    }

    // The route's cached elevation when it is for this takeoff point ([lat, lon]), so no call is spent; else null
    function cachedElevationFor(cached, takeoff) {
        if (!cached || !takeoff) return null;
        return cached.lat === takeoff[0] && cached.lon === takeoff[1] ? cached : null;
    }

    // -- the route's terrain: the lidar surface or COP30 (lidar_terrain.py) ---------------------------------------------

    // The terrain status line: what the route's kept terrain (its terrain_info) is, and whether it serves the source
    // chosen in the form
    function terrainText(info, chosen) {
        if (!info || !info.fetched_at) return "No terrain fetched yet";
        if (info.imported) return info.dataset + " terrain from the imported file";
        var when = new Date(info.fetched_at * 1000).toLocaleString();
        var text = info.source === "lidar"
            ? (info.dataset === "Lidar+COP30" ? "Lidar terrain (10 m, " + Math.round(info.filled * 100) + "% filled from COP30)" : "Lidar terrain (10 m)") + " fetched " + when
            : "COP30 terrain fetched " + when + (info.fallback ? ": " + info.fallback : "");
        var made = info.requested || "cop30";
        if (chosen && chosen !== made) text += ". Fetched for " + (made === "lidar" ? "the lidar surface" : "COP30") + ": it is fetched again on export";
        return text;
    }

    // The progress line while the lidar units a terrain needs are built (a 202 answer: {done, units})
    function buildingText(data) {
        return "Building the lidar surface for the terrain: " + data.done + " of " + data.units + " units…";
    }

    // POSTs a terrain request and, while it answers 202 (lidar units being built), asks again every opts.every ms
    // (3 s), calling opts.onWait(data), for at most opts.deadline ms (5 minutes). Resolves to {ok, status, data};
    // past the deadline {ok: false, status: 202, timedOut: true, data: {error}}.
    // post(path, body) -> Promise<Response>; opts.now() and opts.sleep(ms) -> Promise can be stood in for by tests.
    function fetchUntilBuilt(post, path, body, opts) {
        opts = opts || {};
        var every = opts.every || 3000, deadline = opts.deadline || 300000;
        var now = opts.now || function () { return Date.now(); };
        var sleep = opts.sleep || function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
        var started = now();
        function ask() {
            return post(path, body).then(function (res) {
                return res.json().then(function (data) { return {ok: res.ok && res.status !== 202, status: res.status, data: data}; });
            }).then(function (r) {
                if (r.status !== 202) return r;
                if (opts.onWait) opts.onWait(r.data);
                if (now() - started >= deadline) {
                    return {ok: false, status: 202, timedOut: true,
                            data: {error: "The lidar surface is still being built after " + Math.round(deadline / 60000) +
                                   " minutes: fetch the terrain again in a while (the built units are kept)"}};
                }
                return sleep(every).then(ask);
            });
        }
        return ask();
    }

    // The editors' Save: a button, a status line, send() (the PATCH, a promise that rejects on failure) and
    // canSave() (the route exists). An edit made while a save is in flight stays unsaved (the button on, "Unsaved
    // changes"), so the leave prompt still catches it. -> {setDirty(dirty), save() (a promise), isDirty()}
    function createSaver(button, status, send, canSave) {
        var dirty = false, edits = 0, timer = null;
        function setDirty(d) {
            dirty = d;
            if (d) edits++;
            button.disabled = !d;
            clearTimeout(timer);
            status.textContent = d ? "Unsaved changes" : "";
        }
        function save() {
            if (!canSave() || !dirty) return Promise.resolve();
            var sent = edits;
            button.disabled = true;
            status.textContent = "Saving\u2026";
            return send().then(function () {
                if (edits !== sent) { button.disabled = false; status.textContent = "Unsaved changes"; return; }
                setDirty(false);
                status.textContent = "Saved";
                timer = setTimeout(function () { if (!dirty) status.textContent = ""; }, 2000);
            }).catch(function () {
                dirty = true;
                button.disabled = false;     // so the user can retry
                status.textContent = "Could not save - try again";
            });
        }
        return {setDirty: setDirty, save: save, isDirty: function () { return dirty; }};
    }

    var api = {DRONES: DRONES, GSD_PER_M: GSD_PER_M, GSD_PER_M_BY_MODEL: GSD_PER_M_BY_MODEL, copiedHeight: copiedHeight, gsdCm: gsdCm, heightForGsd: heightForGsd, roundTo: roundTo, OSM: OSM, TERRAIN_SOURCE: TERRAIN_SOURCE, basemapSource: basemapSource, chooseBasemap: chooseBasemap, DEFAULTS: DEFAULTS, LIMITS: LIMITS, parseForm: parseForm, requestBody: requestBody, bearing: bearing, distance: distance,
               longestSideDirection: longestSideDirection, areaBounds: areaBounds, rectangleCorners: rectangleCorners, formatArea: formatArea, formatDuration: formatDuration, formatDistance: formatDistance, summaryRows: summaryRows, parseCoordinates: parseCoordinates,
               photonLanguage: photonLanguage, photonUrl: photonUrl, photonSuggestions: photonSuggestions, suggestPlaces: suggestPlaces, showSuggestion: showSuggestion,
               metersToFeet: metersToFeet, feetToMeters: feetToMeters, mpsToMph: mpsToMph, mphToMps: mphToMps,
               WAYPOINT_DEFAULTS: WAYPOINT_DEFAULTS, parseWaypointForm: parseWaypointForm, parsePointForm: parsePointForm, pointsError: pointsError,
               newPoint: newPoint, addPoint: addPoint, insertAfter: insertAfter, deletePoint: deletePoint, movePoint: movePoint, updatePoint: updatePoint,
               missingGrounds: missingGrounds, pointsBounds: pointsBounds, pointsCenter: pointsCenter, waypointRequestBody: waypointRequestBody, waypointSummaryRows: waypointSummaryRows,
               SHAPE_DEFAULTS: SHAPE_DEFAULTS, parseShapeForm: parseShapeForm, poiShapePoints: poiShapePoints, subjectRing: subjectRing, outlineCenter: outlineCenter,
               shiftOutline: shiftOutline, poiPitch: poiPitch, poiPhotoSpacing: poiPhotoSpacing,
               poiLoopHeights: poiLoopHeights, stackLoops: stackLoops, poiLoopPitch: poiLoopPitch, poiSuggestedLoops: poiSuggestedLoops,
               MAX_LOOPS: MAX_LOOPS,
               LINEAR_DEFAULTS: LINEAR_DEFAULTS, singleLineHeight: singleLineHeight, parseLinearForm: parseLinearForm, linearRequestBody: linearRequestBody,
               stripPolygon: stripPolygon, lineLength: lineLength, lineBounds: lineBounds, linearSummaryRows: linearSummaryRows,
               SLOPE_DEFAULTS: SLOPE_DEFAULTS, parseSlopeForm: parseSlopeForm, cornersError: cornersError, keptHeights: keptHeights,
               slopeRequestBody: slopeRequestBody, compassPoint: compassPoint, slopeSummaryRows: slopeSummaryRows, profileSvg: profileSvg,
               GEOMETRIC_DEFAULTS: GEOMETRIC_DEFAULTS, parseGeometricForm: parseGeometricForm, outlineError: outlineError,
               geometricRequestBody: geometricRequestBody, geometricSummaryRows: geometricSummaryRows,
               aslReady: aslReady, aslHint: aslHint, aslAutoFetch: aslAutoFetch, cachedElevationFor: cachedElevationFor,
               terrainText: terrainText, buildingText: buildingText, fetchUntilBuilt: fetchUntilBuilt, createSaver: createSaver};
    root.MissionPlannerCore = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
