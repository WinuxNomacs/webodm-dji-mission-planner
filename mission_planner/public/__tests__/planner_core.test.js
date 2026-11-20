const Core = require('../planner_core');

const form = over => Object.assign({}, Core.DEFAULTS, over);
const SQUARE = [[-85.020728, 42.1030], [-85.019928, 42.1030], [-85.019928, 42.1036], [-85.020728, 42.1036]];

describe("parseForm", () => {
    it("accepts the defaults", () => {
        const r = Core.parseForm(Core.DEFAULTS);
        expect(r.ok).toBe(true);
        expect(r.errors).toEqual({});
        expect(r.values).toMatchObject({height: 50, overlap_h: 80, overlap_w: 70, margin: 0, direction: 0, speed: 1.79,
                                        cameras: ["visable", "ir"], height_mode: "realTimeFollowSurface"});
    });

    it("reads numbers typed as text, with spaces", () => {
        const r = Core.parseForm(form({height: " 100.5 ", overlap_h: "85", speed: "8.5"}));
        expect(r.values).toMatchObject({height: 100.5, overlap_h: 85, speed: 8.5});
    });

    it("leaves what is missing at its default", () => {
        expect(Core.parseForm({}).ok).toBe(true);
    });

    it("names each field that is wrong, with its limits", () => {
        const r = Core.parseForm(form({height: "1", overlap_h: "5", overlap_w: "99", takeoff_security_height: "0", rth_height: "9999"}));
        expect(r.ok).toBe(false);
        expect(r.errors.height).toBe("Height above the ground must be between 2 and 500 m");
        expect(r.errors.overlap_h).toBe("Overlap along the lines must be between 10 and 95 %");
        expect(r.errors.overlap_w).toContain("between 10 and 95");
        expect(r.errors.takeoff_security_height).toContain("between 2 and 1500");
        expect(r.errors.rth_height).toContain("Return height");
    });

    it("refuses what is not a number", () => {
        ["", "abc", "1,5", "NaN", null, {}].forEach(v => {
            expect(Core.parseForm(form({height: v})).errors.height).toContain("must be a number");
        });
        // too big to be a height, whatever it is called
        expect(Core.parseForm(form({height: "Infinity"})).errors.height).toContain("between 2 and 500");
        expect(Core.parseForm(form({direction: "north"})).errors.direction).toBeDefined();
        expect(Core.parseForm(form({margin: "-1"})).errors.margin).toBeDefined();
        expect(Core.parseForm(form({margin: ""})).errors.margin).toBeDefined();
    });

    it("keeps the direction between 0 and 360", () => {
        expect(Core.parseForm(form({direction: "-90"})).values.direction).toBe(270);
        expect(Core.parseForm(form({direction: "450"})).values.direction).toBe(90);
        expect(Core.parseForm(form({direction: "360"})).values.direction).toBe(0);
    });

    it("takes an empty speed as 'as fast as allowed' and limits the others", () => {
        expect(Core.parseForm(form({speed: ""})).values.speed).toBeNull();
        expect(Core.parseForm(form({speed: "  "})).values.speed).toBeNull();
        ["0", "-1", "15.1", "abc"].forEach(v => expect(Core.parseForm(form({speed: v})).errors.speed).toBeDefined());
        expect(Core.parseForm(form({speed: "15"})).ok).toBe(true);
    });

    it("only accepts the known choices", () => {
        expect(Core.parseForm(form({altitude_mode: "sky"})).errors.altitude_mode).toBeDefined();
        expect(Core.parseForm(form({takeoff_mode: "teleport"})).errors.takeoff_mode).toBeDefined();
        expect(Core.parseForm(form({finish_action: "crash"})).errors.finish_action).toBeDefined();
        expect(Core.parseForm(form({exit_on_rc_lost: "panic"})).errors.exit_on_rc_lost).toBeDefined();
        ["goHome", "noAction", "autoLand", "gotoFirstWaypoint"].forEach(a => expect(Core.parseForm(form({finish_action: a})).ok).toBe(true));
    });

    it("takes the lenses from the two switches", () => {
        expect(Core.parseForm(form({lens_visible: "true", lens_ir: "true"})).values.cameras).toEqual(["visable", "ir"]);
        expect(Core.parseForm(form({lens_ir: "false"})).values.cameras).toEqual(["visable"]);
        expect(Core.parseForm(form({lens_visible: "false"})).values.cameras).toEqual(["ir"]);
        expect(Core.parseForm(form({lens_visible: false, lens_ir: true})).values.cameras).toEqual(["ir"]);
        expect(Core.parseForm(form({lens_visible: "false", lens_ir: "false"})).errors.cameras).toBe("Choose at least one lens");
    });

    it("turns the altitude mode into the height mode of the mission file", () => {
        expect(Core.parseForm(form({altitude_mode: "agl"})).values.height_mode).toBe("realTimeFollowSurface");
        expect(Core.parseForm(form({altitude_mode: "alt"})).values.height_mode).toBe("relativeToStartPoint");
        expect(Core.parseForm(form({altitude_mode: "asl", takeoff_altitude: "208.5", takeoff_ellipsoidal_height: "209.8"})).values.height_mode).toBe("EGM96");
    });

    it("ASL needs the takeoff elevation to have been fetched first", () => {
        expect(Core.parseForm(form({altitude_mode: "asl"})).errors.altitude_mode).toBeDefined();
        expect(Core.parseForm(form({altitude_mode: "asl", takeoff_altitude: "208.5"})).errors.altitude_mode).toBeDefined();     // ellipsoidal missing
        const r = Core.parseForm(form({altitude_mode: "asl", takeoff_altitude: "208.5", takeoff_ellipsoidal_height: "209.8"}));
        expect(r.ok).toBe(true);
        expect(r.values.takeoff_ellipsoidal_height).toBe(209.8);
    });

    it("reads the switches", () => {
        const v = Core.parseForm(Core.DEFAULTS).values;
        expect([v.elevation_optimize, v.avoid_limit_area]).toEqual([true, false]);
        const w = Core.parseForm(form({elevation_optimize: "false", avoid_limit_area: "true"})).values;
        expect([w.elevation_optimize, w.avoid_limit_area]).toEqual([false, true]);
        expect(Core.parseForm(form({elevation_optimize: true, avoid_limit_area: false})).values.elevation_optimize).toBe(true);
    });

    it("accepts safe takeoff and direct ascent", () => {
        ["safe", "direct"].forEach(m => expect(Core.parseForm(form({takeoff_mode: m})).values.takeoff_mode).toBe(m));
    });

    it("says photos every so many seconds are not available yet", () => {
        expect(Core.parseForm(form({photo_mode: "time"})).errors.photo_mode).toContain("not available yet");
        expect(Core.parseForm(form({photo_mode: "distance"})).ok).toBe(true);
    });

    it("limits the takeoff speed", () => {
        expect(Core.parseForm(form({transitional_speed: "10"})).values.transitional_speed).toBe(10);
        ["0", "-3", "16", "fast", ""].forEach(v => expect(Core.parseForm(form({transitional_speed: v})).errors.transitional_speed).toBeDefined());
    });

    it("reads the ground height at the takeoff point, which is optional", () => {
        expect(Core.parseForm(form({takeoff_altitude: ""})).values.takeoff_altitude).toBeNull();
        expect(Core.parseForm(form({takeoff_altitude: "209.78"})).values.takeoff_altitude).toBe(209.78);
        expect(Core.parseForm(form({takeoff_altitude: "-12"})).values.takeoff_altitude).toBe(-12);
        ["abc", "99999", "-1000"].forEach(v => expect(Core.parseForm(form({takeoff_altitude: v})).errors.takeoff_altitude).toBeDefined());
    });

    it("has the same limits as the server", () => {
        // app/missions/planning.py and wpml.py
        expect(Core.LIMITS.height.slice(0, 2)).toEqual([2, 500]);
        expect(Core.LIMITS.overlap_h.slice(0, 2)).toEqual([10, 95]);
        expect(Core.LIMITS.overlap_w.slice(0, 2)).toEqual([10, 95]);
        expect(Core.LIMITS.rth_height.slice(0, 2)).toEqual([2, 1500]);
    });

    describe("oblique collection", () => {
        it("defaults to ortho, with every oblique field null", () => {
            const v = Core.parseForm(Core.DEFAULTS).values;
            expect(v.collection_mode).toBe("ortho");
            expect([v.gimbal_pitch, v.inclined_overlap_h, v.inclined_overlap_w, v.inclined_speed]).toEqual([null, null, null, null]);
        });

        it("accepts AGL height mode, sent as real-time follow for the server to turn into the DSM mode", () => {
            const r = Core.parseForm(form({collection_mode: "oblique", altitude_mode: "agl", gimbal_pitch: "-45"}));
            expect(r.ok).toBe(true);
            expect(r.values.height_mode).toBe("realTimeFollowSurface");
        });

        it("accepts ASL height mode when the takeoff elevation was fetched", () => {
            const r = Core.parseForm(form({collection_mode: "oblique", altitude_mode: "asl", gimbal_pitch: "-45",
                                           takeoff_altitude: "208.5", takeoff_ellipsoidal_height: "209.8"}));
            expect(r.ok).toBe(true);
        });

        it("accepts oblique with ALT height mode and a gimbal tilt in range", () => {
            const r = Core.parseForm(form({collection_mode: "oblique", altitude_mode: "alt", gimbal_pitch: "-45"}));
            expect(r.ok).toBe(true);
            expect(r.values.gimbal_pitch).toBe(-45);
        });

        it("limits the gimbal tilt angle to Pilot 2's range", () => {
            const base = {collection_mode: "oblique", altitude_mode: "alt"};
            expect(Core.parseForm(form(Object.assign({}, base, {gimbal_pitch: "-85"}))).ok).toBe(true);
            expect(Core.parseForm(form(Object.assign({}, base, {gimbal_pitch: "-40"}))).ok).toBe(true);
            ["-90", "-39", "-86", "0", "steep"].forEach(v =>
                expect(Core.parseForm(form(Object.assign({}, base, {gimbal_pitch: v}))).errors.gimbal_pitch).toBeDefined());
        });

        it("leaves the inclined overlap empty (mirrors the ortho overlap) unless it is set", () => {
            const base = {collection_mode: "oblique", altitude_mode: "alt", gimbal_pitch: "-45"};
            const empty = Core.parseForm(form(Object.assign({}, base, {inclined_overlap_h: "", inclined_overlap_w: ""})));
            expect(empty.ok).toBe(true);
            expect([empty.values.inclined_overlap_h, empty.values.inclined_overlap_w]).toEqual([null, null]);
            const set = Core.parseForm(form(Object.assign({}, base, {inclined_overlap_h: "60", inclined_overlap_w: "50"})));
            expect([set.values.inclined_overlap_h, set.values.inclined_overlap_w]).toEqual([60, 50]);
            expect(Core.parseForm(form(Object.assign({}, base, {inclined_overlap_h: "5"}))).errors.inclined_overlap_h).toBeDefined();
        });

        it("leaves the inclined speed empty (as fast as the oblique photos allow) unless it is set", () => {
            const base = {collection_mode: "oblique", altitude_mode: "alt", gimbal_pitch: "-45"};
            expect(Core.parseForm(form(Object.assign({}, base, {inclined_speed: ""}))).values.inclined_speed).toBeNull();
            expect(Core.parseForm(form(Object.assign({}, base, {inclined_speed: "5.1"}))).values.inclined_speed).toBe(5.1);
            expect(Core.parseForm(form(Object.assign({}, base, {inclined_speed: "0"}))).errors.inclined_speed).toBeDefined();
            expect(Core.parseForm(form(Object.assign({}, base, {inclined_speed: "16"}))).errors.inclined_speed).toBeDefined();
        });

        it("rejects an unknown collection mode", () => {
            expect(Core.parseForm(form({collection_mode: "panoramic"})).errors.collection_mode).toBeDefined();
        });
    });
});

describe("requestBody", () => {
    it("is what the server expects", () => {
        const body = Core.requestBody(SQUARE, form({height: "30", direction: "45", name: "Field 1"}), null);
        expect(body).toEqual({model: "m4t", polygon: SQUARE, direction: 45, height: 30, cameras: ["visable", "ir"], overlap_h: 80, overlap_w: 70, margin: 0,
                              speed: 1.79, height_mode: "realTimeFollowSurface", takeoff_security_height: 20, rth_height: 100,
                              finish_action: "goHome", exit_on_rc_lost: "goContinue", takeoff_ref_point: null, transitional_speed: 15,
                              takeoff_mode: "safe", elevation_optimize: true, avoid_limit_area: false, photo_mode: "distance",
                              route_start: null, name: "Field 1", collection_mode: "ortho", surface_follow: "realtime"});
    });

    it("sends the aircraft model, with only the cameras it has", () => {
        const m4e = Core.requestBody(SQUARE, Core.DEFAULTS, null, null, "m4e");
        expect(m4e.model).toBe("m4e");
        expect(m4e.cameras).toEqual(["visable"]);
        expect(Core.requestBody(SQUARE, form({lens_visible: "false"}), null, null, "m4e")).toBeNull();
        expect(Core.requestBody(SQUARE, form({lens_visible: "false"}), null, null, "m4t").cameras).toEqual(["ir"]);
    });

    it("opens a closed ring, and does not touch the area it was given", () => {
        const closed = SQUARE.concat([SQUARE[0]]);
        const body = Core.requestBody(closed, Core.DEFAULTS, null);
        expect(body.polygon).toEqual(SQUARE);
        expect(closed.length).toBe(5);
        body.polygon[0][0] = 0;
        expect(SQUARE[0][0]).toBe(-85.020728);
    });

    it("is null without an area, or with a form that has errors", () => {
        expect(Core.requestBody(null, Core.DEFAULTS, null)).toBeNull();
        expect(Core.requestBody([], Core.DEFAULTS, null)).toBeNull();
        expect(Core.requestBody(SQUARE.slice(0, 2), Core.DEFAULTS, null)).toBeNull();
        expect(Core.requestBody(SQUARE, form({height: "1"}), null)).toBeNull();
    });

    it("writes the takeoff point only when its ground height is known", () => {
        expect(Core.requestBody(SQUARE, Core.DEFAULTS, [42.1, -85.013728]).takeoff_ref_point).toBeNull();
        expect(Core.requestBody(SQUARE, form({takeoff_altitude: "209.5"}), [42.1, -85.013728]).takeoff_ref_point).toEqual([42.1, -85.013728, 209.5]);
        expect(Core.requestBody(SQUARE, form({takeoff_altitude: "209.5"}), null).takeoff_ref_point).toBeNull();
    });

    it("passes the route start on", () => {
        expect(Core.requestBody(SQUARE, Core.DEFAULTS, null, [-85.020728, 42.103]).route_start).toEqual([-85.020728, 42.103]);
        expect(Core.requestBody(SQUARE, Core.DEFAULTS, null, undefined).route_start).toBeNull();
    });

    it("carries the options of the route", () => {
        const b = Core.requestBody(SQUARE, form({altitude_mode: "alt", takeoff_mode: "direct", elevation_optimize: "false", avoid_limit_area: "true",
                                                 transitional_speed: "12", lens_ir: "false"}), null);
        expect(b).toMatchObject({height_mode: "relativeToStartPoint", takeoff_mode: "direct", elevation_optimize: false, avoid_limit_area: true,
                                 transitional_speed: 12, cameras: ["visable"]});
    });

    it("sends the terrain follow, and refuses one it does not know", () => {
        expect(Core.requestBody(SQUARE, form({surface_follow: "dsm"}), null).surface_follow).toBe("dsm");
        expect(Core.parseForm(form({surface_follow: "laser"})).errors.surface_follow).toBe("Choose real-time follow or the terrain model");
        expect(Core.requestBody(SQUARE, form({surface_follow: "laser"}), null)).toBeNull();
    });

    it("leaves the oblique settings out of the request when the mode is ortho", () => {
        const b = Core.requestBody(SQUARE, Core.DEFAULTS, null);
        expect(b.collection_mode).toBe("ortho");
        ["gimbal_pitch", "inclined_overlap_h", "inclined_overlap_w", "inclined_speed"].forEach(k => expect(b).not.toHaveProperty(k));
    });

    it("includes the oblique settings when the mode is oblique", () => {
        const b = Core.requestBody(SQUARE, form({collection_mode: "oblique", altitude_mode: "alt", gimbal_pitch: "-45",
                                                 inclined_overlap_h: "60", inclined_overlap_w: "50", inclined_speed: "5.1"}), null);
        expect(b).toMatchObject({collection_mode: "oblique", gimbal_pitch: -45, inclined_overlap_h: 60, inclined_overlap_w: 50, inclined_speed: 5.1});
    });

    it("includes the ellipsoidal takeoff height only when the mode is asl", () => {
        const b = Core.requestBody(SQUARE, form({altitude_mode: "asl", takeoff_altitude: "208.5", takeoff_ellipsoidal_height: "209.8"}), null);
        expect(b).toMatchObject({height_mode: "EGM96", takeoff_ellipsoidal_height: 209.8});
        expect(Core.requestBody(SQUARE, form({altitude_mode: "alt"}), null)).not.toHaveProperty("takeoff_ellipsoidal_height");
    });
});

describe("directions", () => {
    it("computes bearings between points", () => {
        expect(Core.bearing([0, 0], [0, 1])).toBeCloseTo(0, 6);
        expect(Core.bearing([0, 0], [1, 0])).toBeCloseTo(90, 6);
        expect(Core.bearing([0, 0], [0, -1])).toBeCloseTo(180, 6);
        expect(Core.bearing([0, 0], [-1, 0])).toBeCloseTo(270, 6);
        expect(Core.bearing([10, 45], [11, 46])).toBeGreaterThan(0);
        expect(Core.bearing([10, 45], [11, 46])).toBeLessThan(90);
    });

    it("computes distances on the ground", () => {
        expect(Core.distance([0, 0], [0, 1])).toBeCloseTo(111195, -1);
        expect(Core.distance([0, 60], [1, 60])).toBeCloseTo(55597, -1);       // a degree of longitude is half as long at 60 degrees
        expect(Core.distance([5, 5], [5, 5])).toBe(0);
    });

    it("flies along the longest side of the area", () => {
        // 100 m east-west by 40 m north-south: the lines run east-west
        const lon = 100 / 82600, lat = 40 / 111195;
        const wide = [[-88, 42], [-88 + lon, 42], [-88 + lon, 42 + lat], [-88, 42 + lat]];
        expect(Core.longestSideDirection(wide)).toBeCloseTo(90, 0);
        const tall = [[-88, 42], [-88 + lat, 42], [-88 + lat, 42 + lon], [-88, 42 + lon]];
        expect(Core.longestSideDirection(tall)).toBeCloseTo(0, 0);
    });

    it("gives the direction as a line: between 0 and 180 degrees, whichever way the area was drawn", () => {
        const lon = 100 / 82600, lat = 40 / 111195;
        const clockwise = [[-88, 42], [-88, 42 + lat], [-88 + lon, 42 + lat], [-88 + lon, 42]];
        const anticlockwise = clockwise.slice().reverse();
        [clockwise, anticlockwise].forEach(a => {
            const d = Core.longestSideDirection(a);
            expect(d).toBeGreaterThanOrEqual(0);
            expect(d).toBeLessThan(180);
            expect(d).toBeCloseTo(90, 0);
        });
    });

    it("has no direction without an area", () => {
        expect(Core.longestSideDirection(null)).toBeNull();
        expect(Core.longestSideDirection([[0, 0], [1, 1]])).toBeNull();
    });

    it("frames the area in a box from its south-west to its north-east corner", () => {
        expect(Core.areaBounds([[-85.013728, 42.10], [-85.023728, 42.11], [-85.003728, 42.105]])).toEqual([[-85.023728, 42.10], [-85.003728, 42.11]]);
        expect(Core.areaBounds(null)).toBeNull();
        expect(Core.areaBounds([[0, 0], [1, 1]])).toBeNull();
    });
});

describe("words", () => {
    it("writes durations", () => {
        expect(Core.formatDuration(0)).toBe("0 s");
        expect(Core.formatDuration(44.6)).toBe("45 s");
        expect(Core.formatDuration(60)).toBe("1 min 00 s");
        expect(Core.formatDuration(125)).toBe("2 min 05 s");
        expect(Core.formatDuration(3600)).toBe("1 h 00 min");
        expect(Core.formatDuration(3725)).toBe("1 h 02 min");
    });

    it("writes distances", () => {
        expect(Core.formatDistance(0)).toBe("0 m");
        expect(Core.formatDistance(304.2)).toBe("304 m");
        expect(Core.formatDistance(999.4)).toBe("999 m");
        expect(Core.formatDistance(1234)).toBe("1.23 km");
        expect(Core.formatDistance(15000)).toBe("15 km");
    });

    it("lists the results", () => {
        const rows = Core.summaryRows({lines: 4, spacing: 19.296, interval: 10.2912, photos: 23, speed: 8, max_speed: 8.233, distance: 304.2, duration: 38.02,
                                       gsd: {visable: 0.0127, ir: 0.1}});
        const byLabel = {};
        rows.forEach(r => byLabel[r.label] = r.value);
        expect(byLabel["Flight lines"]).toBe("4");
        expect(byLabel["Distance between lines"]).toBe("19.3 m");
        expect(byLabel["A photo every"]).toBe("10.29 m");
        expect(byLabel["Photos"]).toBe("23");
        expect(byLabel["Speed"]).toBe("8 m/s (at most 8.2 m/s)");
        expect(byLabel["Flight"]).toBe("304 m, 38 s");
        expect(byLabel["Pixel size, wide camera"]).toBe("1.3 cm");
        expect(byLabel["Pixel size, thermal camera"]).toBe("10 cm");
    });

    it("shows fine pixel sizes with more digits", () => {
        const rows = Core.summaryRows({lines: 1, spacing: 1, interval: 1, photos: 1, speed: 1, max_speed: 1, distance: 1, duration: 1, gsd: {visable: 0.0057}});
        expect(rows.filter(r => r.label.indexOf("wide") !== -1)[0].value).toBe("0.57 cm");
    });
});

describe("basemaps", () => {
    const hybrid = {type: "tms", label: "Google Maps Hybrid", url: "//{s}.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}", subdomains: ["mt0", "mt1", "mt2", "mt3"],
                    minzoom: 0, maxzoom: 21, attribution: "Map data: &copy; Google Maps", default: true};

    it("makes a raster source of a tile basemap, one URL per subdomain", () => {
        const s = Core.basemapSource(hybrid, "https:");
        expect(s.type).toBe("raster");
        expect(s.tiles).toEqual(["https://mt0.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}", "https://mt1.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}",
                                 "https://mt2.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}", "https://mt3.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}"]);
        expect(s).toMatchObject({tileSize: 256, scheme: "xyz", minzoom: 0, maxzoom: 21, attribution: "Map data: &copy; Google Maps"});
    });

    it("follows the protocol of the page for URLs that start with //", () => {
        expect(Core.basemapSource({url: "//tile.example.org/{z}/{x}/{y}.png"}, "http:").tiles).toEqual(["http://tile.example.org/{z}/{x}/{y}.png"]);
        expect(Core.basemapSource({url: "//tile.example.org/{z}/{x}/{y}.png"}, "https:").tiles).toEqual(["https://tile.example.org/{z}/{x}/{y}.png"]);
        expect(Core.basemapSource({url: "https://tile.example.org/{z}/{x}/{y}.png"}, "http:").tiles).toEqual(["https://tile.example.org/{z}/{x}/{y}.png"]);
        expect(Core.basemapSource({url: "//tile.example.org/{z}/{x}/{y}.png"}).tiles[0]).toBe("https://tile.example.org/{z}/{x}/{y}.png");
    });

    it("uses Leaflet's default subdomains when {s} has none, and no subdomain when there is no {s}", () => {
        expect(Core.basemapSource({url: "https://{s}.tile.example.org/{z}/{x}/{y}.png"}).tiles.map(t => t.slice(8, 9))).toEqual(["a", "b", "c"]);
        expect(Core.basemapSource({url: "https://tile.example.org/{z}/{x}/{y}.png", subdomains: ["a", "b"]}).tiles.length).toBe(1);
    });

    it("reads flipped tile rows ({-y}) as TMS", () => {
        const s = Core.basemapSource({url: "https://t.example.org/{z}/{x}/{-y}.png"});
        expect(s.scheme).toBe("tms");
        expect(s.tiles).toEqual(["https://t.example.org/{z}/{x}/{y}.png"]);
    });

    it("asks a WMS server for tiles in web mercator", () => {
        const s = Core.basemapSource({type: "wms", url: "//maps.example.org/wms", layers: "roads,water", styles: "", format: "image/jpeg"}, "https:");
        expect(s.tiles.length).toBe(1);
        const url = s.tiles[0];
        expect(url.indexOf("https://maps.example.org/wms?")).toBe(0);
        ["service=WMS", "request=GetMap", "layers=roads%2Cwater", "format=image%2Fjpeg", "transparent=false", "srs=EPSG:3857", "width=256", "height=256", "bbox={bbox-epsg-3857}"]
            .forEach(part => expect(url).toContain(part));
        expect(Core.basemapSource({type: "wms", url: "//maps.example.org/wms?map=x"}, "https:").tiles[0]).toContain("wms?map=x&service=WMS");
        expect(Core.basemapSource({type: "wms", url: "//m/wms"}, "https:").tiles[0]).toContain("layers=0&styles=default&format=image%2Fpng&transparent=true");
    });

    it("defaults the zoom range and leaves out a missing attribution", () => {
        const s = Core.basemapSource({url: "https://t/{z}/{x}/{y}.png"});
        expect(s.minzoom).toBe(0);
        expect(s.maxzoom).toBe(21);
        expect("attribution" in s).toBe(false);
    });

    it("chooses the basemap the user chose before, else the default, else the first, else OpenStreetMap", () => {
        const a = {label: "A", url: "//a/{z}/{x}/{y}.png"}, b = {label: "B", url: "//b/{z}/{x}/{y}.png", default: true}, c = {label: "C", url: "//c/{z}/{x}/{y}.png"};
        expect(Core.chooseBasemap([a, b, c], "C")).toBe(c);
        expect(Core.chooseBasemap([a, b, c], "gone")).toBe(b);
        expect(Core.chooseBasemap([a, b, c], null)).toBe(b);
        expect(Core.chooseBasemap([a, c], null)).toBe(a);
        expect(Core.chooseBasemap([], null)).toBe(Core.OSM);
        expect(Core.chooseBasemap(null, "A")).toBe(Core.OSM);
        expect(Core.chooseBasemap([{label: "no url"}], null)).toBe(Core.OSM);
    });

    it("has free elevation tiles for the 3D view", () => {
        expect(Core.TERRAIN_SOURCE.type).toBe("raster-dem");
        expect(Core.TERRAIN_SOURCE.encoding).toBe("terrarium");
        expect(Core.TERRAIN_SOURCE.tiles[0]).toContain("{z}/{x}/{y}");
        expect(Core.TERRAIN_SOURCE.attribution).toContain("Terrain");
    });
});

describe("ground sample distance", () => {
    it("is the size of a pixel on the ground for each camera", () => {
        // FlightHub at 50 m: 1.78 cm/pixel for the visible lens and 5 cm/pixel for the thermal one
        expect(Core.gsdCm("ir", 50)).toBeCloseTo(5, 9);
        expect(Core.gsdCm("visable", 50)).toBeCloseTo(1.79, 2);
        expect(Core.gsdCm("ir", 0)).toBe(0);
    });

    it("gives the height for a ground sample distance, and back", () => {
        expect(Core.heightForGsd("ir", 5)).toBeCloseTo(50, 9);
        ["visable", "ir"].forEach(camera => {
            [3, 10, 50, 120.5, 400].forEach(h => expect(Core.heightForGsd(camera, Core.gsdCm(camera, h))).toBeCloseTo(h, 9));
        });
    });

    it("links the two cameras: the height for one is the ground sample distance of the other", () => {
        const height = Core.heightForGsd("visable", 1.78);
        expect(Core.gsdCm("ir", height)).toBeCloseTo(4.97, 1);
    });

    it("rounds", () => {
        expect(Core.roundTo(1.7849, 2)).toBe(1.78);
        expect(Core.roundTo(49.96, 1)).toBe(50);
    });

    it("converts between metric and imperial", () => {
        expect(Core.metersToFeet(50)).toBeCloseTo(164.042, 2);
        expect(Core.feetToMeters(Core.metersToFeet(50))).toBeCloseTo(50, 9);
        expect(Core.mpsToMph(10)).toBeCloseTo(22.3694, 3);
        expect(Core.mphToMps(Core.mpsToMph(10))).toBeCloseTo(10, 9);
    });

    it("uses the Matrice 4E's wide camera when asked for that model", () => {
        expect(Core.gsdCm("visable", 50, "m4e")).toBeCloseTo(5000 / 3725, 9);
        expect(Core.heightForGsd("visable", Core.gsdCm("visable", 80, "m4e"), "m4e")).toBeCloseTo(80, 9);
        expect(Core.GSD_PER_M_BY_MODEL.m4e.ir).toBeUndefined();
    });

    it("gives a copy for the other model the height that keeps the visible ground sample distance", () => {
        expect(Core.copiedHeight(50, "m4t", "m4e")).toBeCloseTo(66.6, 2);
        expect(Core.copiedHeight(80, "m4e", "m4t")).toBeCloseTo(60.06, 2);
        expect(Core.copiedHeight(50, "m4t", "m4t")).toBe(50);
        expect(Core.copiedHeight(450, "m4t", "m4e")).toBe(500);
        expect(Core.copiedHeight(2, "m4e", "m4t")).toBe(2);
    });

    it("reads the aircraft from the page when the page carries them", () => {
        document.body.innerHTML = '<script id="mp-drones" type="application/json">' +
            '{"x1": {"name": "X1", "cameras": [{"key": "visable", "focal_mm": 10, "sensor_w_mm": 20, "sensor_h_mm": 15, "px_w": 2000, "px_h": 1500}]}}</script>';
        try {
            jest.isolateModules(() => {
                const PageCore = require("../planner_core");
                expect(Object.keys(PageCore.DRONES)).toEqual(["x1"]);
                expect(PageCore.GSD_PER_M_BY_MODEL.x1.visable).toBeCloseTo(0.001, 12);
            });
        } finally {
            document.body.innerHTML = "";
        }
    });

    it("has the numbers of the server", () => {
        // app/missions/cameras.py: 12 mm lens, 640 px over 7.68 mm; 6.7 mm lens, 4032 px over 9.66 mm
        expect(Core.GSD_PER_M.ir).toBeCloseTo(0.001, 12);
        expect(Core.GSD_PER_M.visable).toBeCloseTo(9.66 / 4032 / 6.7, 12);
        expect(Core.GSD_PER_M_BY_MODEL.m4e.visable).toBeCloseTo(1 / 3725, 12);
    });
});

describe("area", () => {
    it("writes areas", () => {
        expect(Core.formatArea(105.69)).toBe("105.69 m²");
        expect(Core.formatArea(2400)).toBe("2400 m²");
        expect(Core.formatArea(9999.99)).toBe("9999.99 m²");
        expect(Core.formatArea(10000)).toBe("1 ha");
        expect(Core.formatArea(123456)).toBe("12.35 ha");
    });

    it("is the first row of the results, when the server sent it", () => {
        const base = {lines: 1, spacing: 1, interval: 1, photos: 1, speed: 1, max_speed: 1, distance: 1, duration: 1, gsd: {}};
        expect(Core.summaryRows(Object.assign({area: 2400}, base))[0]).toEqual({label: "Area", value: "2400 m²"});
        expect(Core.summaryRows(base)[0].label).toBe("Flight lines");
    });
});

describe("parseCoordinates", () => {
    it("parses comma and/or space separated latitude, longitude", () => {
        expect(Core.parseCoordinates("40.7128, -74.0060")).toEqual([40.7128, -74.0060]);
        expect(Core.parseCoordinates("40.7128 -74.0060")).toEqual([40.7128, -74.0060]);
        expect(Core.parseCoordinates("40.7128,-74.0060")).toEqual([40.7128, -74.0060]);
        expect(Core.parseCoordinates("  0, 0  ")).toEqual([0, 0]);
        expect(Core.parseCoordinates("-33.8688, 151.2093")).toEqual([-33.8688, 151.2093]);
    });

    it("rejects out-of-range values", () => {
        expect(Core.parseCoordinates("91, 0")).toBeNull();
        expect(Core.parseCoordinates("0, 181")).toBeNull();
        expect(Core.parseCoordinates("-91, 0")).toBeNull();
        expect(Core.parseCoordinates("0, -181")).toBeNull();
    });

    it("rejects text that is not a coordinate pair, so it can be tried as an address", () => {
        expect(Core.parseCoordinates("1600 Amphitheatre Parkway")).toBeNull();
        expect(Core.parseCoordinates("Paris, France")).toBeNull();
        expect(Core.parseCoordinates("")).toBeNull();
        expect(Core.parseCoordinates("40.7128")).toBeNull();
        expect(Core.parseCoordinates("40.7128, -74.0060, 10")).toBeNull();
    });
});

describe("waypoint routes", () => {
    const wform = over => Object.assign({}, Core.WAYPOINT_DEFAULTS, over);
    const two = [Core.newPoint(50, 6), Core.newPoint(50.001, 6.001)];

    it("accepts the default waypoint settings", () => {
        const parsed = Core.parseWaypointForm(Core.WAYPOINT_DEFAULTS);
        expect(parsed.ok).toBe(true);
        expect(parsed.values).toMatchObject({height: 50, height_mode: "alt", speed: 5, gimbal_pitch: null, heading_mode: "followWayline",
                                             turn_mode: "stop", cameras: ["visable", "ir"], avoid_limit_area: false});
    });

    it("checks the height against the limits of the height mode", () => {
        expect(Core.parseWaypointForm(wform({height: "1"})).errors.height).toBe("The height must be between 2 and 1500 m");
        expect(Core.parseWaypointForm(wform({height: "1", height_mode: "agl"})).errors.height).toBeDefined();
        const asl = wform({height: "-50", height_mode: "asl", takeoff_altitude: "300", takeoff_ellipsoidal_height: "347"});
        expect(Core.parseWaypointForm(asl).ok).toBe(true);
        expect(Core.parseWaypointForm(wform({height: "20000", height_mode: "asl"})).errors.height).toMatch(/above sea level/);
    });

    it("needs the ground elevation at the takeoff point for ASL", () => {
        expect(Core.parseWaypointForm(wform({height_mode: "asl"})).errors.height_mode).toBe("Fetch the ground elevation at the takeoff point before using ASL");
    });

    it("leaves the gimbal as it is when the pitch is blank, and checks it otherwise", () => {
        expect(Core.parseWaypointForm(wform({gimbal_pitch: "-90"})).values.gimbal_pitch).toBe(-90);
        expect(Core.parseWaypointForm(wform({gimbal_pitch: "40"})).errors.gimbal_pitch).toBeDefined();
    });

    it("rejects unknown modes, a zero speed and no lens", () => {
        const parsed = Core.parseWaypointForm(wform({heading_mode: "x", turn_mode: "x", speed: "0", lens_visible: "false", lens_ir: "false"}));
        expect(Object.keys(parsed.errors).sort()).toEqual(["cameras", "heading_mode", "speed", "turn_mode"]);
    });

    it("reads a point's settings, blank meaning the route's", () => {
        expect(Core.parsePointForm({height: "", heading: "", pitch: "", hover: "", photo: false}, "alt"))
            .toEqual({ok: true, errors: {}, values: {height: null, heading: null, pitch: null, hover: 0, photo: false}});
        expect(Core.parsePointForm({height: "30", heading: "270", pitch: "-45", hover: "5", photo: true}, "alt").values)
            .toEqual({height: 30, heading: -90, pitch: -45, hover: 5, photo: true});
    });

    it("rejects a point's settings out of range", () => {
        const parsed = Core.parsePointForm({height: "1", heading: "x", pitch: "-91", hover: "901"}, "alt");
        expect(Object.keys(parsed.errors).sort()).toEqual(["heading", "height", "hover", "pitch"]);
    });

    it("finds a point height that no longer fits after the height mode changed", () => {
        const points = Core.updatePoint(two, 1, {height: -20});
        expect(Core.pointsError(points, "asl")).toBeNull();
        expect(Core.pointsError(points, "alt")).toBe("The height of point 2 must be between 2 and 1500 m");
    });

    it("adds, inserts, moves and deletes points without changing the old list", () => {
        const three = Core.addPoint(two, 50.002, 6.002);
        expect(three).toHaveLength(3);
        expect(two).toHaveLength(2);
        const inserted = Core.insertAfter(three, 0);
        expect(inserted[1]).toMatchObject({lat: 50.0005, lon: 6.0005, ground: null});
        expect(Core.insertAfter(three, 2)).toBeNull();
        const grounded = Core.updatePoint(three, 1, {ground: 120});
        expect(Core.missingGrounds(grounded)).toEqual([0, 2]);
        const moved = Core.movePoint(grounded, 1, 51, 7);
        expect(moved[1]).toMatchObject({lat: 51, lon: 7, ground: null});
        expect(grounded[1].ground).toBe(120);
        expect(Core.deletePoint(three, 0).map(p => p.lat)).toEqual([50.001, 50.002]);
    });

    it("gives the box around the points, or null without any", () => {
        expect(Core.pointsBounds(two)).toEqual([[6, 50], [6.001, 50.001]]);
        expect(Core.pointsBounds([])).toBeNull();
    });

    it("builds the request body, with only the aircraft's lenses", () => {
        const body = Core.waypointRequestBody(two, Core.WAYPOINT_DEFAULTS, [50, 6], "m4e");
        expect(body).toMatchObject({route_type: "waypoint", model: "m4e", cameras: ["visable"], height: 50, takeoff_ref_point: null});
        expect(body.points[0]).toEqual({lat: 50, lon: 6, height: null, heading: null, pitch: null, photo: false, hover: 0, ground: null});
        expect(body.takeoff_ellipsoidal_height).toBeUndefined();
    });

    it("sends the takeoff point and, for ASL, its ellipsoidal height", () => {
        const body = Core.waypointRequestBody(two, wform({height_mode: "asl", height: "400", takeoff_altitude: "300", takeoff_ellipsoidal_height: "347"}), [50, 6], "m4t");
        expect(body.takeoff_ref_point).toEqual([50, 6, 300]);
        expect(body.takeoff_ellipsoidal_height).toBe(347);
    });

    it("builds no request body with fewer than 2 points or errors", () => {
        expect(Core.waypointRequestBody(two.slice(0, 1), Core.WAYPOINT_DEFAULTS, null, "m4t")).toBeNull();
        expect(Core.waypointRequestBody(two, wform({speed: "0"}), null, "m4t")).toBeNull();
        expect(Core.waypointRequestBody(two, wform({lens_visible: "false"}), null, "m4e")).toBeNull();
    });

    it("reads video and the photos over the route", () => {
        expect(Core.parseWaypointForm(Core.WAYPOINT_DEFAULTS).values).toMatchObject({video: false, photo_interval_mode: null, photo_interval: null});
        expect(Core.parseWaypointForm(wform({video: "true", photo_interval_mode: "time", photo_interval: "2.5"})).values)
            .toMatchObject({video: true, photo_interval_mode: "time", photo_interval: 2.5});
        expect(Core.parseWaypointForm(wform({photo_interval_mode: "distance", photo_interval: "0.1"})).errors.photo_interval)
            .toBe("The photo interval must be between 0.5 and 900 m");
        expect(Core.parseWaypointForm(wform({photo_interval_mode: "time", photo_interval: ""})).errors.photo_interval)
            .toBe("The photo interval must be between 0.5 and 900 seconds");
        expect(Core.parseWaypointForm(wform({photo_interval_mode: "x"})).errors.photo_interval_mode).toBeDefined();
    });

    it("accepts the Toward POI heading and the smooth curve", () => {
        expect(Core.parseWaypointForm(wform({heading_mode: "towardPOI", turn_mode: "curve"})).ok).toBe(true);
    });

    it("puts the POI in the middle of the points, or nowhere without any", () => {
        expect(Core.pointsCenter(two)).toEqual([50.0005, 6.0005]);
        expect(Core.pointsCenter([])).toBeNull();
    });

    it("sends the POI on a Toward POI route, without the points' headings", () => {
        const headed = Core.updatePoint(two, 0, {heading: 90});
        const body = Core.waypointRequestBody(headed, wform({heading_mode: "towardPOI"}), null, "m4t", [50.0005, 6.0005]);
        expect(body.poi).toEqual([50.0005, 6.0005]);
        expect(body.points[0].heading).toBeNull();
        expect(Core.waypointRequestBody(headed, wform({heading_mode: "towardPOI"}), null, "m4t", null)).toBeNull();
    });

    it("leaves the POI out of other routes and sends video and the interval", () => {
        const body = Core.waypointRequestBody(two, wform({video: "true", photo_interval_mode: "distance", photo_interval: "20"}), null, "m4t", [1, 2]);
        expect(body.poi).toBeUndefined();
        expect(body).toMatchObject({video: true, photo_interval_mode: "distance", photo_interval: 20});
    });

    it("describes the results in words", () => {
        const rows = Core.waypointSummaryRows({points: 4, photos: 2, speed: 5, length: 141.48, duration: 49.3});
        expect(rows.map(r => r.label)).toEqual(["Points", "Photos", "Speed", "Flight"]);
        expect(rows[2].value).toBe("5 m/s");
    });
});

describe("linear routes", () => {
    const LINE = [[-85.020728, 42.1030], [-85.019728, 42.1030], [-85.019728, 42.1036]];
    const linearForm = over => Object.assign({}, Core.LINEAR_DEFAULTS, over);

    it("accepts the defaults, without the settings of an area only", () => {
        const r = Core.parseLinearForm(Core.LINEAR_DEFAULTS);
        expect(r.ok).toBe(true);
        expect(r.values).toMatchObject({left_extend: 50, right_extend: 50, single_line: false, height: 50, name: "luxodm-linear"});
        ["direction", "margin", "photo_mode", "collection_mode", "gimbal_pitch"].forEach(k => expect(r.values).not.toHaveProperty(k));
    });

    it("ignores an oblique collection or a timed photo mode left in the form", () => {
        expect(Core.parseLinearForm(linearForm({collection_mode: "oblique", photo_mode: "time", altitude_mode: "agl"})).ok).toBe(true);
    });

    it("needs widths of 0 or more that add up to a strip", () => {
        expect(Core.parseLinearForm(linearForm({left_extend: "-1"})).errors.left_extend).toContain("0 or more");
        expect(Core.parseLinearForm(linearForm({right_extend: "x"})).errors.right_extend).toContain("to the right");
        expect(Core.parseLinearForm(linearForm({left_extend: "0", right_extend: "0"})).errors.left_extend).toBe("The strip needs a width");
        expect(Core.parseLinearForm(linearForm({left_extend: "0", right_extend: "20"})).ok).toBe(true);
    });

    it("flies a single line at the height that covers the strip with every camera", () => {
        // The M4T's narrowest photo is the thermal camera's: 7.68 / 12 = 0.64 m across per meter of height
        expect(Core.singleLineHeight(["visable", "ir"], 20, 12, "m4t")).toBeCloseTo(50, 6);
        expect(Core.singleLineHeight(["visable"], 20, 12, "m4t")).toBeCloseTo(32 / (9.66 / 6.7), 6);
        expect(Core.singleLineHeight(["visable"], 20, 12, "m4e")).toBeCloseTo(32 * 3725 / 5280, 6);
        const r = Core.parseLinearForm(linearForm({single_line: "true", left_extend: "20", right_extend: "12", height: "1"}));
        expect(r.ok).toBe(true);
        expect(r.values.height).toBeCloseTo(50, 6);
    });

    it("says when a single line over the strip would be too high", () => {
        const r = Core.parseLinearForm(linearForm({single_line: "true", left_extend: "200", right_extend: "200"}));
        expect(r.errors.height).toBe("One line over this strip would be flown at 625 m: the height must be between 2 and 500 m");
    });

    it("builds the request of a linear route", () => {
        const body = Core.linearRequestBody(LINE, linearForm({speed: "", left_extend: "30", right_extend: "10"}), [42.1, -85.013728], "m4e");
        expect(body).toMatchObject({route_type: "linear", model: "m4e", cameras: ["visable"], line: LINE, left_extend: 30, right_extend: 10,
                                    single_line: false, height: 50, speed: null, height_mode: "realTimeFollowSurface", takeoff_ref_point: null,
                                    surface_follow: "realtime"});
        expect(Core.linearRequestBody(LINE, linearForm({surface_follow: "dsm"})).surface_follow).toBe("dsm");
        ["polygon", "direction", "margin", "route_start", "collection_mode", "takeoff_ellipsoidal_height"].forEach(k => expect(body).not.toHaveProperty(k));
    });

    it("builds no request without a line of at least 2 points or with errors", () => {
        expect(Core.linearRequestBody(LINE.slice(0, 1), Core.LINEAR_DEFAULTS)).toBeNull();
        expect(Core.linearRequestBody(null, Core.LINEAR_DEFAULTS)).toBeNull();
        expect(Core.linearRequestBody(LINE, linearForm({left_extend: "-5"}))).toBeNull();
    });

    it("draws the strip around the center line, mitred at the bend", () => {
        const ring = Core.stripPolygon(LINE, 10, 20);
        expect(ring).toHaveLength(7);
        expect(ring[0]).toEqual(ring[6]);
        // Going east, the left side is north and the right side south
        expect(Core.distance(LINE[0], ring[0])).toBeCloseTo(10, 1);
        expect(ring[0][1]).toBeGreaterThan(LINE[0][1]);
        expect(Core.distance(LINE[0], ring[5])).toBeCloseTo(20, 1);
        expect(ring[5][1]).toBeLessThan(LINE[0][1]);
        // At the right-angle bend the corner is the width away from both segments
        expect(Core.distance(LINE[1], ring[1])).toBeCloseTo(10 * Math.SQRT2, 0);
        expect(Core.stripPolygon(LINE, 0, 0)).toBeNull();
        expect(Core.stripPolygon([LINE[0], LINE[0]], 10, 10)).toBeNull();
    });

    it("measures and frames the center line", () => {
        expect(Core.lineLength(LINE)).toBeCloseTo(Core.distance(LINE[0], LINE[1]) + Core.distance(LINE[1], LINE[2]), 6);
        expect(Core.lineBounds(LINE)).toEqual([[-85.020728, 42.1030], [-85.019728, 42.1036]]);
        expect(Core.lineBounds(LINE.slice(0, 1))).toBeNull();
    });

    it("writes the results of a linear route in words", () => {
        const summary = {lines: 1, spacing: 0, interval: 9.5, photos: 30, speed: 7.3, max_speed: 7.32, distance: 380, duration: 61,
                         height: 50, bend_pass: true, gsd: {ir: 0.05}};
        const rows = Core.linearSummaryRows(summary);
        expect(rows.map(r => r.label)).toEqual(["Flight lines", "Height", "Pass along the bends", "A photo every", "Photos", "Speed", "Flight", "Pixel size, thermal camera"]);
        expect(rows[2].value).toBe("yes, camera at -45°");
        expect(Core.linearSummaryRows(Object.assign({}, summary, {lines: 3, spacing: 12.345, bend_pass: false}))[1]).toEqual({label: "Distance between lines", value: "12.35 m"});
    });
});

describe("POI routes", () => {
    const POI = [42.1033, -85.020328];
    const lonLat = p => [p.lon, p.lat];
    const center = [POI[1], POI[0]];
    const shape = over => Object.assign({}, Core.SHAPE_DEFAULTS, over);

    it("puts 12 points on a circle around the subject, from north, back to the first", () => {
        const points = Core.poiShapePoints(POI, shape({radius: "10", distance: "15"}));
        expect(points).toHaveLength(13);
        points.forEach(p => expect(Core.distance(center, lonLat(p))).toBeCloseTo(25, 1));
        expect(Core.bearing(center, lonLat(points[0]))).toBeCloseTo(0, 3);
        expect(Core.bearing(center, lonLat(points[1]))).toBeCloseTo(30, 1);
        expect(points[12]).toEqual(points[0]);
        expect(points[0]).toMatchObject({height: null, heading: null, photo: false});
    });

    it("starts the circle at the start bearing and takes the points per turn", () => {
        const points = Core.poiShapePoints(POI, shape({start: "90", count: "8"}));
        expect(points).toHaveLength(9);
        expect(Core.bearing(center, lonLat(points[0]))).toBeCloseTo(90, 1);
        expect(Core.bearing(center, lonLat(points[1]))).toBeCloseTo(135, 1);
    });

    it("goes round a rectangle with straight sides and arcs at its corners", () => {
        // 20 m wide and 30 m long, 15 m away: the sides are 25 m east and west and 30 m north and south
        const points = Core.poiShapePoints(POI, shape({kind: "rectangle", width: "20", length: "30", distance: "15"}));
        expect(points).toHaveLength(18);
        expect(Core.bearing(center, lonLat(points[0]))).toBeCloseTo(0, 3);
        expect(Core.distance(center, lonLat(points[0]))).toBeCloseTo(30, 1);
        expect(Core.distance(center, lonLat(points[4]))).toBeCloseTo(Math.hypot(25, 15), 1);
        expect(points[17]).toEqual(points[0]);
    });

    it("turns the rectangle with its rotation", () => {
        const points = Core.poiShapePoints(POI, shape({kind: "rectangle", rotation: "90", start: "90"}));
        expect(Core.distance(center, lonLat(points[0]))).toBeCloseTo(30, 1);
    });

    it("goes round the convex hull of a drawn outline", () => {
        const outline = [[-85.020728, 42.1030], [-85.019928, 42.1030], [-85.020328, 42.1033], [-85.019928, 42.1036], [-85.020728, 42.1036]];
        const points = Core.poiShapePoints(POI, shape({kind: "outline", outline: outline, distance: "5"}));
        expect(points.length).toBeGreaterThan(12);
        expect(points[points.length - 1]).toEqual(points[0]);
        // No point is closer to the outline than the distance
        points.forEach(p => outline.forEach(v => expect(Core.distance(v, lonLat(p))).toBeGreaterThan(4.9)));
        expect(Core.poiShapePoints(POI, shape({kind: "outline", outline: outline.slice(0, 2)}))).toBeNull();
    });

    it("finds what is wrong with a shape", () => {
        expect(Core.parseShapeForm(Core.SHAPE_DEFAULTS).ok).toBe(true);
        const r = Core.parseShapeForm(shape({kind: "rectangle", width: "0", distance: "0", count: "2.5", overlap: "99", height: "-1"}));
        expect(Object.keys(r.errors).sort()).toEqual(["count", "distance", "height", "overlap", "width"]);
        expect(Core.parseShapeForm(shape({kind: "square"})).errors.kind).toBeDefined();
        expect(Core.parseShapeForm(shape({kind: "outline"})).errors.outline).toBeDefined();
        expect(Core.poiShapePoints(POI, shape({distance: ""}))).toBeNull();
        expect(Core.poiShapePoints(null, shape({}))).toBeNull();
    });

    it("draws the subject for the map as a closed ring", () => {
        const circle = Core.subjectRing(POI, shape({radius: "10"}));
        expect(circle).toHaveLength(73);
        expect(Core.distance(center, circle[10])).toBeCloseTo(10, 1);
        const rect = Core.subjectRing(POI, shape({kind: "rectangle"}));
        expect(rect).toHaveLength(5);
        expect(rect[4]).toEqual(rect[0]);
    });

    it("moves a drawn outline with its POI and finds its middle", () => {
        const outline = [[-85.020728, 42.1030], [-85.019928, 42.1030], [-85.019928, 42.1036], [-85.020728, 42.1036]];
        expect(Core.outlineCenter(outline)).toEqual([42.1033, -85.020328]);
        const moved = Core.shiftOutline(outline, [42.1033, -85.020328], [42.1043, -85.019328]);
        expect(moved[0][0]).toBeCloseTo(-85.019728, 9);
        expect(moved[0][1]).toBeCloseTo(42.1040, 9);
        expect(Core.outlineCenter([])).toBeNull();
    });

    it("aims the gimbal at half the subject's height", () => {
        expect(Core.poiPitch(30, 10, 15)).toBe(-59);
        expect(Core.poiPitch(5, 10, 15)).toBe(0);
        expect(Core.poiPitch(0, 40, 10)).toBe(35);
        expect(Core.poiPitch(null, 10, 15)).toBeNull();
    });

    it("spaces the photos by the overlap of the narrowest camera", () => {
        expect(Core.poiPhotoSpacing(["visable", "ir"], 15, 80, "m4t")).toBe(1.9);
        expect(Core.poiPhotoSpacing(["visable"], 15, 80, "m4t")).toBe(4.3);
        expect(Core.poiPhotoSpacing(["ir"], 1, 95, "m4t")).toBe(0.5);
        expect(Core.poiPhotoSpacing([], 15, 80, "m4t")).toBeNull();
    });

    it("spreads the loops evenly from the lowest to the highest", () => {
        expect(Core.poiLoopHeights(10, 40, 4)).toEqual([10, 20, 30, 40]);
        expect(Core.poiLoopHeights(10, 20, 3)).toEqual([10, 15, 20]);
        expect(Core.poiLoopHeights(10, 40, 1)).toEqual([10]);
    });

    it("stacks a loop at each height with its own pitch, each starting above where the last one ended", () => {
        const loop = Core.poiShapePoints(POI, shape({count: "4"}));
        const points = Core.stackLoops(loop, [10, 20], [-20, 0]);
        expect(points).toHaveLength(10);
        expect(points[4]).toMatchObject({lat: loop[4].lat, lon: loop[4].lon, height: 10, pitch: -20});
        expect(points[5]).toMatchObject({lat: points[4].lat, lon: points[4].lon, height: 20, pitch: 0});
        expect(Core.stackLoops(loop, [10]).every(p => p.pitch === null)).toBe(true);
        expect(loop[0].height).toBeNull();
    });

    it("aims each loop at the subject level with it, or at its top from above", () => {
        expect(Core.poiLoopPitch(10, 30, 15)).toBe(0);
        expect(Core.poiLoopPitch(40, 30, 15)).toBe(-33.7);
        expect(Core.poiLoopPitch(-5, 30, 15)).toBe(18.4);
        expect(Core.poiLoopPitch(null, 30, 15)).toBeNull();
    });

    it("suggests the loops for the overlap of the narrowest camera's height", () => {
        expect(Core.poiSuggestedLoops(["visable"], 15, 80, 10, 40, "m4t")).toBe(11);
        expect(Core.poiSuggestedLoops(["visable", "ir"], 15, 80, 10, 40, "m4t")).toBe(Core.MAX_LOOPS);
        expect(Core.poiSuggestedLoops(["visable"], 15, 80, 10, 10, "m4t")).toBe(1);
        expect(Core.poiSuggestedLoops([], 15, 80, 10, 40, "m4t")).toBeNull();
    });

    it("needs a whole count of loops and, for several, the highest loop's height", () => {
        expect(Core.parseShapeForm(shape({loops: "1", top: ""})).ok).toBe(true);
        expect(Core.parseShapeForm(shape({loops: "3", top: ""})).errors).toEqual({top: "Give the height of the highest loop"});
        ["0", "2.5", "21"].forEach(n => expect(Core.parseShapeForm(shape({loops: n, top: "30"})).errors.loops).toBeDefined());
        expect(Core.parseShapeForm(shape({loops: "3", top: "30"})).values).toMatchObject({loops: 3, top: 30});
    });
});

describe("address suggestions", () => {
    const EIFFEL = {type: "Feature", geometry: {type: "Point", coordinates: [2.2945, 48.8584]},
                    properties: {name: "Eiffel Tower", street: "Avenue Gustave Eiffel", housenumber: "5", city: "Paris", state: "Île-de-France",
                                 country: "France", extent: [2.2933, 48.8592, 2.2957, 48.8575]}};
    const ADDRESS = {type: "Feature", geometry: {type: "Point", coordinates: [11.1, 46.1]},
                     properties: {street: "Via Roma", housenumber: "12", city: "Trento", country: "Italy"}};
    const answer = (status, body) => Promise.resolve({status, ok: status < 400, json: () => Promise.resolve(body)});

    test("Photon is asked for ten places near the map's centre, in the browser's language when it has it", () => {
        expect(Core.photonUrl("rue de rivoli", [2.35222, 48.85661], "fr"))
            .toBe("https://photon.komoot.io/api/?q=rue%20de%20rivoli&limit=10&lat=48.8566&lon=2.3522&lang=fr");
        expect(Core.photonUrl("Paris", null, null)).toBe("https://photon.komoot.io/api/?q=Paris&limit=10");
        expect(Core.photonLanguage("de-CH")).toBe("de");
        expect(Core.photonLanguage("EN")).toBe("en");
        expect(Core.photonLanguage("it-IT")).toBeNull();
        expect(Core.photonLanguage(undefined)).toBeNull();
    });

    test("a suggestion is the place's name with the street and places it is in, its point and its extent", () => {
        expect(Core.photonSuggestions({features: [EIFFEL]})).toEqual([{
            label: "Eiffel Tower", detail: "Avenue Gustave Eiffel 5, Paris, Île-de-France, France",
            center: [2.2945, 48.8584], bbox: [2.2933, 48.8575, 2.2957, 48.8592]
        }]);
    });

    test("an address without a name is labelled by its street and number, and has no extent", () => {
        expect(Core.photonSuggestions({features: [ADDRESS]})).toEqual([
            {label: "Via Roma 12", detail: "Trento, Italy", center: [11.1, 46.1], bbox: null}
        ]);
    });

    test("a city is not repeated in its own detail, and places without a position or a name are left out", () => {
        const paris = {geometry: {coordinates: [2.35, 48.85]}, properties: {name: "Paris", city: "Paris", country: "France"}};
        expect(Core.photonSuggestions({features: [paris, {geometry: null, properties: {name: "x"}}, {geometry: {coordinates: [1, 2]}, properties: {}}]}))
            .toEqual([{label: "Paris", detail: "France", center: [2.35, 48.85], bbox: null}]);
        expect(Core.photonSuggestions(null)).toEqual([]);
    });

    test("five suggestions are kept out of ten places, once those that read the same are dropped", () => {
        const addresses = [1, 1, 2, 2, 3, 3, 4, 5, 6, 7].map(n => ({...ADDRESS, properties: {...ADDRESS.properties, housenumber: String(n)}}));
        expect(Core.photonSuggestions({features: addresses}).map(s => s.label)).toEqual(["Via Roma 1", "Via Roma 2", "Via Roma 3", "Via Roma 4", "Via Roma 5"]);
    });

    test("at most five suggestions are kept", () => {
        const addresses = [1, 2, 3, 4, 5, 6, 7, 8].map(n => ({...ADDRESS, properties: {...ADDRESS.properties, housenumber: String(n)}}));
        expect(Core.photonSuggestions({features: addresses}).length).toBe(5);
    });

    test("places that would read the same are suggested once, the first of them", () => {
        const area = {...ADDRESS, geometry: {type: "Point", coordinates: [11.2, 46.2]}};
        expect(Core.photonSuggestions({features: [ADDRESS, area, EIFFEL]}).map(s => s.center)).toEqual([[11.1, 46.1], [2.2945, 48.8584]]);
    });

    test("places are suggested from Photon's answer, and coordinates are not sent to it", async () => {
        const asked = [];
        const fetchFn = url => { asked.push(url); return answer(200, {features: [ADDRESS]}); };
        expect(await Core.suggestPlaces(fetchFn, "via roma", [11, 46], "en")).toEqual([
            {label: "Via Roma 12", detail: "Trento, Italy", center: [11.1, 46.1], bbox: null}
        ]);
        expect(asked).toEqual(["https://photon.komoot.io/api/?q=via%20roma&limit=10&lat=46.0000&lon=11.0000&lang=en"]);
        expect(await Core.suggestPlaces(fetchFn, "46.1, 11.1", [11, 46], "en")).toEqual([]);
        expect(asked.length).toBe(1);
    });

    test("a failed answer from Photon rejects, so that no list is shown", async () => {
        await expect(Core.suggestPlaces(() => answer(503, null), "via roma", null, null)).rejects.toThrow("Photon answered 503");
        await expect(Core.suggestPlaces(() => Promise.reject(new TypeError("offline")), "via roma", null, null)).rejects.toThrow("offline");
    });

    test("a picked place with an extent is fitted on the map, one without is flown to at zoom 15 or closer", () => {
        const calls = [];
        const map = {getZoom: () => 12, fitBounds: (b, o) => calls.push(["fit", b, o]), flyTo: o => calls.push(["fly", o])};
        Core.showSuggestion(map, {center: [2.29, 48.86], bbox: [2.2933, 48.8575, 2.2957, 48.8592]});
        Core.showSuggestion(map, {center: [11.1, 46.1], bbox: null});
        map.getZoom = () => 17;
        Core.showSuggestion(map, {center: [11.1, 46.1], bbox: null});
        expect(calls).toEqual([
            ["fit", [[2.2933, 48.8575], [2.2957, 48.8592]], {padding: 40, maxZoom: 18}],
            ["fly", {center: [11.1, 46.1], zoom: 15}],
            ["fly", {center: [11.1, 46.1], zoom: 17}]
        ]);
    });
});

describe("slope routes", () => {
    const CORNERS = [[-85.0206061, 42.1032755], [-85.0201804, 42.1032629], [-85.0201747, 42.1035673], [-85.0206005, 42.1035799]];
    const HEIGHTS = [209.24, 209.01, 79.09, 79.32];
    const slopeForm = over => Object.assign({}, Core.SLOPE_DEFAULTS, over);

    it("checks the form without the settings only an area has", () => {
        const r = Core.parseSlopeForm(slopeForm({altitude_mode: "face"}));
        expect(r.ok).toBe(true);
        expect(r.values).toMatchObject({height: 30, overlap_w: 80, cameras: ["visable", "ir"]});
        ["direction", "margin", "photo_mode", "collection_mode", "height_mode", "elevation_optimize", "surface_follow"]
            .forEach(k => expect(r.values[k]).toBeUndefined());
        expect(Core.parseSlopeForm(slopeForm({height: "1"})).errors.height).toBe("The distance from the face must be between 2 and 500 m");
        expect(Core.parseSlopeForm(slopeForm({takeoff_altitude: "x"})).errors.takeoff_altitude).toBe("The ground height at the takeoff point must be a number of meters");
    });

    it("says what is missing from the corners", () => {
        expect(Core.cornersError(null, [])).toBe("Draw the slope on the map");
        expect(Core.cornersError(CORNERS, [209, null, 79, undefined])).toMatch(/^Give every corner its height \(2 of 4 missing\)/);
        expect(Core.cornersError(CORNERS, HEIGHTS)).toBeNull();
    });

    it("keeps the heights of the corners that did not move", () => {
        const moved = [CORNERS[0], [-85.020128, 42.1032], CORNERS[2], CORNERS[3], [-85.020628, 42.1034]];
        expect(Core.keptHeights(CORNERS, HEIGHTS, moved)).toEqual([209.24, null, 79.09, 79.32, null]);
        expect(Core.keptHeights(null, [], CORNERS)).toEqual([null, null, null, null]);
    });

    it("sends the corners with their heights, once every corner has one", () => {
        const body = Core.slopeRequestBody(CORNERS, HEIGHTS, slopeForm({speed: "3.5", takeoff_altitude: "208.65"}), [42.1034, -85.020528], "m4t");
        expect(body).toMatchObject({route_type: "slope", model: "m4t", name: "luxodm-slope", height: 30, speed: 3.5,
                                    cameras: ["visable", "ir"], takeoff_ref_point: [42.1034, -85.020528, 208.65]});
        expect(body.corners[0]).toEqual([-85.0206061, 42.1032755, 209.24]);
        expect(body.height_mode).toBeUndefined();
        expect(Core.slopeRequestBody(CORNERS, [209, null, 79, 79], slopeForm(), null, "m4t")).toBeNull();
        expect(Core.slopeRequestBody(CORNERS, HEIGHTS, slopeForm(), null, "m4e").cameras).toEqual(["visable"]);
    });

    it("says where the camera faces and how it is tilted", () => {
        const rows = Core.slopeSummaryRows({slope: 75.41, heading: -177.63, pitch: -14, lines: 46, spacing: 2.878, height: 28.11,
                                            interval: 3.598, photos: 487, speed: 3.5, max_speed: 2.88, distance: 1750, duration: 644,
                                            gsd: {visable: 0.0065}});
        expect(rows.slice(0, 2)).toEqual([{label: "Slope", value: "75.4°"}, {label: "Camera", value: "facing S (182°), tilted -14°"}]);
        expect(rows.map(r => r.label)).toContain("Pixel size, wide camera");
        expect(Core.compassPoint(-90)).toBe("W");
    });

    it("draws the side view to scale, each line looking square-on at the face", () => {
        const profile = {face: [[0, 209], [34, 79]], lines: [[27, 214], [61, 84]]};
        const svg = Core.profileSvg(profile, 320, 220);
        const numbers = s => (s.match(/"-?[\d.]+"/g) || []).map(v => Number(v.slice(1, -1)));
        const face = numbers(svg.match(/<line class="mp-profile-face"[^>]*>/)[0]);
        const views = svg.match(/<line class="mp-profile-view"[^>]*>/g).map(numbers);
        expect(views.length).toBe(2);
        expect(svg.match(/<circle/g).length).toBe(2);
        const [fx1, fy1, fx2, fy2] = face;
        views.forEach(([x1, y1, x2, y2]) => {
            // ends on the face, at a right angle to it
            const cross = (x2 - fx1) * (fy2 - fy1) - (y2 - fy1) * (fx2 - fx1);
            expect(Math.abs(cross) / Math.hypot(fx2 - fx1, fy2 - fy1)).toBeLessThan(0.2);
            expect(Math.abs((x2 - x1) * (fx2 - fx1) + (y2 - y1) * (fy2 - fy1)) / Math.hypot(fx2 - fx1, fy2 - fy1)).toBeLessThan(0.2);
        });
        // the same scale both ways: the face keeps its slope
        expect(Math.atan2(fy2 - fy1, fx2 - fx1)).toBeCloseTo(Math.atan2(130, 34), 2);
        expect(svg).toContain(">209 m</text>");
        expect(Core.profileSvg(null, 320, 220)).toBe("");
    });
});

describe("geometric routes", () => {
    const OUTLINE = [[-85.0204779, 42.1034695], [-85.0202919, 42.103458], [-85.0203112, 42.1033089], [-85.0204646, 42.103322]];
    const geometricForm = over => Object.assign({}, Core.GEOMETRIC_DEFAULTS, {base: "214.47", top: "218.97"}, over);

    it("checks the form as a slope's, with the base and the top", () => {
        const r = Core.parseGeometricForm(geometricForm());
        expect(r.ok).toBe(true);
        expect(r.values).toMatchObject({height: 10, overlap_w: 80, base: 214.47, top: 218.97, roof: true, name: "luxodm-geometric"});
        expect(Core.parseGeometricForm(geometricForm({roof: "false"})).values.roof).toBe(false);
        expect(r.values.direction).toBeUndefined();
        expect(Core.parseGeometricForm(geometricForm({height: "1"})).errors.height).toBe("The distance from the walls must be between 2 and 500 m");
        expect(Core.parseGeometricForm(geometricForm({base: ""})).errors.base).toMatch(/^Give the heights of the base and of the top/);
        expect(Core.parseGeometricForm(geometricForm({top: "214.6"})).errors.top).toBe("The top must be between 0.5 and 500 m above the base");
    });

    it("says what is missing from the outline", () => {
        expect(Core.outlineError(null)).toBe("Draw the block's outline on the map");
        expect(Core.outlineError(OUTLINE.slice(0, 2))).toBe("Draw the block's outline on the map");
        expect(Core.outlineError(new Array(51).fill(OUTLINE[0]))).toBe("The outline has too many corners (at most 50)");
        expect(Core.outlineError(OUTLINE)).toBeNull();
    });

    it("sends the outline with the base and the top, once the form is complete", () => {
        const body = Core.geometricRequestBody(OUTLINE, geometricForm({height: "6.2", speed: "0.7", takeoff_altitude: "208.65"}), [42.1034, -85.020528], "m4t");
        expect(body).toMatchObject({route_type: "geometric", model: "m4t", height: 6.2, speed: 0.7, base: 214.47, top: 218.97,
                                    cameras: ["visable", "ir"], takeoff_ref_point: [42.1034, -85.020528, 208.65]});
        expect(body.outline).toEqual(OUTLINE);
        expect(body.roof).toBe(true);
        expect(Core.geometricRequestBody(OUTLINE, geometricForm({roof: "false"}), null, "m4t").roof).toBe(false);
        expect(Core.geometricRequestBody(OUTLINE, geometricForm({top: ""}), null, "m4t")).toBeNull();
        expect(Core.geometricRequestBody(OUTLINE.slice(0, 2), geometricForm(), null, "m4t")).toBeNull();
        expect(Core.geometricRequestBody(OUTLINE, geometricForm(), null, "m4e").cameras).toEqual(["visable"]);
    });

    it("says how high the block is and how the loops are flown", () => {
        const rows = Core.geometricSummaryRows({base: 214.47, top: 218.97, loops: 7, spacing: 0.635, height: 6.2, closest: 4.59,
                                                interval: 0.794, photos: 860, speed: 0.7, max_speed: 0.63, distance: 682, duration: 975,
                                                gsd: {visable: 0.002, ir: 0.0055}});
        expect(rows.slice(0, 4)).toEqual([{label: "Block", value: "4.5 m high (214.5 to 219 m)"}, {label: "Loops", value: "7"},
                                          {label: "Distance between loops", value: "0.64 m"},
                                          {label: "Distance from the walls", value: "6.2 m (4.6 m at the closest corner)"}]);
        expect(rows.map(r => r.label)).toContain("Pixel size, thermal camera");
        expect(rows.find(r => r.label === "Roof").value).toBe("Not mapped");
        const roof = Core.geometricSummaryRows({base: 214.47, top: 218.97, loops: 7, spacing: 0.635, height: 6.2, closest: 4.59,
                                                interval: 0.794, photos: 4599, speed: 0.7, max_speed: 0.63, distance: 3453, duration: 6430,
                                                roof_lines: 32, roof_spacing: 0.7936, roof_photos: 3739});
        expect(roof.find(r => r.label === "Roof").value).toBe("32 lines 0.79 m apart, 6.2 m above the top, 3739 photos (Smart Oblique)");
        expect(Core.geometricSummaryRows({base: 0, top: 3, loops: 1, spacing: 3, height: 6, closest: 6, interval: 1, photos: 9,
                                          speed: 1, max_speed: 1, distance: 9, duration: 9}).map(r => r.label)).not.toContain("Distance between loops");
    });

    it("draws the side view of a wall, each loop looking level at it", () => {
        const svg = Core.profileSvg({face: [[0, 218.97], [0, 214.47]], lines: [[6.2, 218.6], [6.2, 214.8]]}, 320, 220);
        const numbers = s => (s.match(/"-?[\d.]+"/g) || []).map(v => Number(v.slice(1, -1)));
        svg.match(/<line class="mp-profile-view"[^>]*>/g).map(numbers).forEach(([, y1, , y2]) => expect(y1).toBeCloseTo(y2, 1));
        expect(svg).toContain(">219 m</text>");
        expect(svg).not.toContain("mp-profile-roof");
    });

    it("draws the roof's lines above the top, looking straight down at it", () => {
        const svg = Core.profileSvg({face: [[0, 218.97], [0, 214.47]], lines: [[6.2, 218.6], [6.2, 214.8]],
                                     roof: [[-6.2, 225.17], [0, 225.17]]}, 320, 220);
        const numbers = s => (s.match(/"-?[\d.]+"/g) || []).map(v => Number(v.slice(1, -1)));
        const [x1, y1, x2, y2] = numbers(svg.match(/<line class="mp-profile-roof"[^>]*>/)[0]);
        expect(y1).toBeCloseTo(y2, 1);
        expect(x1).toBeLessThan(x2);
        // The view straight down, from the roof's line to the top
        const down = svg.match(/<line class="mp-profile-view"[^>]*>/g).map(numbers).find(([a, , c]) => a === c);
        expect(down[1]).toBeCloseTo(y1, 1);
        expect(down[3]).toBeGreaterThan(y1);
    });
});

describe('ASL without the takeoff point\'s ground height', () => {
  const ready = {asl: true, takeoff: true, altitude: '242.4', ellipsoidal: '208.2', fetching: false, failed: null};

  test('no hint when ASL is not picked or both heights are there', () => {
    expect(Core.aslHint(Object.assign({}, ready, {asl: false, altitude: ''}))).toBe('');
    expect(Core.aslHint(ready)).toBe('');
  });

  test('without a takeoff point the hint says to set it first', () => {
    expect(Core.aslHint({asl: true, takeoff: false, altitude: '', ellipsoidal: ''})).toMatch(/set the takeoff point, then fetch/);
  });

  test('with a takeoff point and no height the hint names the fetch button', () => {
    expect(Core.aslHint(Object.assign({}, ready, {altitude: '', ellipsoidal: ''}))).toBe('ASL needs the ground height at the takeoff point: Fetch from elevation data.');
  });

  test('a typed height without the fetched ellipsoidal one is not enough', () => {
    expect(Core.aslHint(Object.assign({}, ready, {ellipsoidal: ''}))).toMatch(/a typed height is not enough/);
  });

  test('while fetching, and after a failed fetch, the hint says so with the reason', () => {
    const missing = Object.assign({}, ready, {altitude: '', ellipsoidal: ''});
    expect(Core.aslHint(Object.assign({}, missing, {fetching: true}))).toMatch(/^Fetching/);
    expect(Core.aslHint(Object.assign({}, missing, {failed: 'The OpenTopography API key was refused'})))
      .toMatch(/could not be fetched: The OpenTopography API key was refused\. Try/);
  });

  test('the height is fetched without asking only in ASL, with a takeoff point, no height and no fetch on its way', () => {
    const missing = Object.assign({}, ready, {altitude: '', ellipsoidal: ''});
    expect(Core.aslAutoFetch(missing)).toBe(true);
    expect(Core.aslAutoFetch(Object.assign({}, missing, {asl: false}))).toBe(false);
    expect(Core.aslAutoFetch(Object.assign({}, missing, {takeoff: false}))).toBe(false);
    expect(Core.aslAutoFetch(Object.assign({}, missing, {fetching: true}))).toBe(false);
    expect(Core.aslAutoFetch(ready)).toBe(false);
    expect(Core.aslAutoFetch(Object.assign({}, ready, {ellipsoidal: ''}))).toBe(true);
  });

  test('the route\'s cached elevation is used only for the same takeoff point', () => {
    const cached = {lat: 42.103447, lon: -85.020518, orthometric: 242.4, ellipsoidal: 208.2};
    expect(Core.cachedElevationFor(cached, [42.103447, -85.020518])).toBe(cached);
    expect(Core.cachedElevationFor(cached, [42.103448, -85.020518])).toBeNull();
    expect(Core.cachedElevationFor(null, [42.1, -88.0])).toBeNull();
    expect(Core.cachedElevationFor(cached, null)).toBeNull();
  });
});

describe("the route's terrain: the lidar surface or COP30", () => {
    const at = 1795000000;

    it("defaults to the lidar surface in both editors", () => {
        expect(Core.DEFAULTS.terrain_source).toBe("lidar");
        expect(Core.WAYPOINT_DEFAULTS.terrain_source).toBe("lidar");
    });

    it("says what the kept terrain is: lidar, lidar filled from COP30, COP30 and why, or the imported file's", () => {
        expect(Core.terrainText(null, "lidar")).toBe("No terrain fetched yet");
        expect(Core.terrainText({source: "lidar", requested: "lidar", dataset: "Lidar", fetched_at: at}, "lidar")).toMatch(/^Lidar terrain \(10 m\) fetched /);
        expect(Core.terrainText({source: "lidar", requested: "lidar", dataset: "Lidar+COP30", filled: 0.123, fetched_at: at}, "lidar"))
            .toMatch(/^Lidar terrain \(10 m, 12% filled from COP30\) fetched /);
        expect(Core.terrainText({source: "cop30", requested: "lidar", dataset: "COP30", fallback: "no USGS lidar here", fetched_at: at}, "lidar"))
            .toMatch(/^COP30 terrain fetched .*: no USGS lidar here$/);
        expect(Core.terrainText({dataset: "ASTGTMV003", imported: true, fetched_at: at}, "lidar")).toBe("ASTGTMV003 terrain from the imported file");
    });

    it("says when the kept terrain was made for the other choice, and that the export fetches it again", () => {
        const lidar = {source: "lidar", requested: "lidar", dataset: "Lidar", fetched_at: at};
        expect(Core.terrainText(lidar, "cop30")).toMatch(/Fetched for the lidar surface: it is fetched again on export$/);
        const old = {dataset: "COP30", fetched_at: at};                               // kept before the choice existed
        expect(Core.terrainText(old, "lidar")).toMatch(/Fetched for COP30: it is fetched again on export$/);
        expect(Core.terrainText(old, "cop30")).not.toMatch(/fetched again/);
    });

    it("shows the build's progress", () => {
        expect(Core.buildingText({done: 1, units: 4})).toBe("Building the lidar surface for the terrain: 1 of 4 units…");
    });

    // A post standing in for fetch: answers in turn
    function poster(answers) {
        const calls = [];
        const post = (path, body) => {
            calls.push([path, body]);
            const [status, data] = answers.shift();
            return Promise.resolve({ok: status >= 200 && status < 300, status, json: () => Promise.resolve(data)});
        };
        return {post, calls};
    }

    it("asks again while the lidar units are built, then answers the terrain", async () => {
        const {post, calls} = poster([[202, {building: true, done: 0, units: 2}], [202, {building: true, done: 1, units: 2}], [200, {dataset: "Lidar"}]]);
        const waits = [], slept = [];
        const r = await Core.fetchUntilBuilt(post, "routes/1/terrain", {terrain_source: "lidar"},
                                             {onWait: d => waits.push(d.done), sleep: ms => { slept.push(ms); return Promise.resolve(); }, now: () => 0});
        expect(r).toEqual({ok: true, status: 200, data: {dataset: "Lidar"}});
        expect(waits).toEqual([0, 1]);
        expect(slept).toEqual([3000, 3000]);
        expect(calls.length).toBe(3);
        expect(calls[2]).toEqual(["routes/1/terrain", {terrain_source: "lidar"}]);
    });

    it("stops waiting after 5 minutes and says to fetch again later", async () => {
        const answers = Array.from({length: 10}, () => [202, {building: true, done: 0, units: 3}]);
        const {post, calls} = poster(answers);
        let t = 0;
        const r = await Core.fetchUntilBuilt(post, "p", {}, {now: () => t, sleep: () => { t += 120000; return Promise.resolve(); }});
        expect(r.ok).toBe(false);
        expect(r.timedOut).toBe(true);
        expect(r.data.error).toMatch(/still being built after 5 minutes: fetch the terrain again in a while/);
        expect(calls.length).toBe(4);                                                      // 0, 2, 4 and 6 minutes
    });

    it("hands a failure straight back", async () => {
        const {post} = poster([[502, {error: "The terrain service returned an error (503)", cached_covers: true}]]);
        const r = await Core.fetchUntilBuilt(post, "p", {}, {sleep: () => Promise.reject(new Error("no wait"))});
        expect(r).toEqual({ok: false, status: 502, data: {error: "The terrain service returned an error (503)", cached_covers: true}});
    });
});

describe("createSaver", () => {
    const flush = () => new Promise(r => setTimeout(r, 0));
    function setup(send) {
        const button = {disabled: true}, status = {textContent: ""};
        return {button, status, saver: Core.createSaver(button, status, send, () => true)};
    }

    it("saves and clears the unsaved state", async () => {
        const {button, status, saver} = setup(() => Promise.resolve());
        saver.setDirty(true);
        await saver.save();
        expect(saver.isDirty()).toBe(false);
        expect(button.disabled).toBe(true);
        expect(status.textContent).toBe("Saved");
    });

    it("keeps an edit made while the save was in flight unsaved", async () => {
        let finish;
        const {button, status, saver} = setup(() => new Promise(r => { finish = r; }));
        saver.setDirty(true);
        const saving = saver.save();
        saver.setDirty(true);                  // the user edits before the answer
        finish();
        await saving;
        expect(saver.isDirty()).toBe(true);
        expect(button.disabled).toBe(false);
        expect(status.textContent).toBe("Unsaved changes");
    });

    it("stays unsaved, with the button on, when the save fails", async () => {
        const {button, status, saver} = setup(() => Promise.reject(new Error("no")));
        saver.setDirty(true);
        await saver.save();
        await flush();
        expect(saver.isDirty()).toBe(true);
        expect(button.disabled).toBe(false);
        expect(status.textContent).toContain("Could not save");
    });

    it("does nothing when there is nothing to save", async () => {
        const send = jest.fn(() => Promise.resolve());
        const {saver} = setup(send);
        await saver.save();
        expect(send).not.toHaveBeenCalled();
    });
});

describe("rectangleCorners", () => {
    const close = (a, b) => { expect(a[0]).toBeCloseTo(b[0], 9); expect(a[1]).toBeCloseTo(b[1], 9); };
    const merc = p => [p[0] * Math.PI / 180, Math.log(Math.tan(Math.PI / 4 + p[1] * Math.PI / 360))];
    const start = [-85.020728, 42.1030], end = [-85.019728, 42.1040];

    it("draws along north and east when the map is not turned", () => {
        const [c1, c3] = Core.rectangleCorners(start, end, 0);
        close(c1, [end[0], start[1]]);
        close(c3, [start[0], end[1]]);
    });

    it("draws along the screen of a turned map, with square corners", () => {
        for (const bearing of [30, -45, 90, 137]) {
            const [c1, c3] = Core.rectangleCorners(start, end, bearing);
            const [s, e, a, c] = [start, end, c1, c3].map(merc);
            const dot = (u, v) => u[0] * v[0] + u[1] * v[1], sub = (u, v) => [u[0] - v[0], u[1] - v[1]];
            expect(dot(sub(a, s), sub(c, s))).toBeCloseTo(0, 12);         // square at the start
            expect(dot(sub(e, a), sub(a, s))).toBeCloseTo(0, 12);         // and at the corner beside it
            const b = bearing * Math.PI / 180;                              // start to c1 runs along the screen's horizontal
            const side = sub(a, s);
            expect(Math.abs(side[0] * Math.sin(b) + side[1] * Math.cos(b))).toBeLessThan(1e-12);
        }
    });

    it("is the same rectangle as a turned map's 90 degrees, its corners swapped", () => {
        const [c1, c3] = Core.rectangleCorners(start, end, 90);
        close(c1, [start[0], end[1]]);
        close(c3, [end[0], start[1]]);
    });
});

describe("failure", () => {
    const answer = (status, body, json) => ({status, json: () => json ? Promise.resolve(JSON.parse(body)) : Promise.reject(new SyntaxError("Unexpected token '<'"))});
    test("a refusal with a JSON error rejects with its message", async () => {
        await expect(Core.failure(answer(400, '{"error": "Fetch the terrain first"}', true), "The KML could not be made"))
            .rejects.toThrow("Fetch the terrain first");
    });
    test("an answer that is not JSON (a server error page) rejects with the fallback and the status", async () => {
        await expect(Core.failure(answer(500, "<html>", false), "The KML could not be made"))
            .rejects.toThrow("The KML could not be made (the server answered 500)");
    });
    test("JSON without an error rejects with the fallback", async () => {
        await expect(Core.failure(answer(502, "{}", true), "The mission could not be exported")).rejects.toThrow("The mission could not be exported");
    });
});
