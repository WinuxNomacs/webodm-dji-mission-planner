const { offersRouteType, copyNote, importSummary, routeTypeLabel, formatUpdated, routeRow, init } = require('../routes_list');

describe("routeTypeLabel", () => {
    it("labels known types", () => {
        expect(routeTypeLabel("area")).toBe("Area Route");
        expect(routeTypeLabel("linear")).toBe("Linear Route");
        expect(routeTypeLabel("waypoint")).toBe("Waypoint Route");
        expect(routeTypeLabel("slope")).toBe("Slope Route");
        expect(routeTypeLabel("geometric")).toBe("Geometric Route");
    });

    it("falls back to the raw value for an unknown type", () => {
        expect(routeTypeLabel("something-new")).toBe("something-new");
    });

    it("labels a waypoint route with a shape as a POI route", () => {
        expect(routeTypeLabel("waypoint", {shape: {kind: "circle"}})).toBe("POI Route");
        expect(routeTypeLabel("waypoint", {})).toBe("Waypoint Route");
    });
});

describe("offersRouteType", () => {
    it("says whether the registry offers the model the route type", () => {
        expect(offersRouteType("m4t", "slope")).toBe(true);
        expect(offersRouteType("m30t", "geometric")).toBe(false);
        expect(offersRouteType("m30t", "linear")).toBe(true);
        expect(offersRouteType("nope", "area")).toBe(false);
    });
    test("a POI route is a waypoint route DJI Fly cannot fly: it faces a point of interest", () => {
        expect(offersRouteType("m4t", "poi")).toBe(true);
        expect(offersRouteType("mini4pro", "waypoint")).toBe(true);
        expect(offersRouteType("mini4pro", "poi")).toBe(false);
    });
});

describe("copyNote", () => {
    test("an oblique area copied for a DJI Fly drone becomes ortho, and says so", () => {
        const note = copyNote({model: "m4t", route_type: "area", settings: {height: "50", collection_mode: "oblique"}}, "air3");
        expect(note).toContain("DJI Fly takes ortho photos only: the copy is an ortho collection.");
        expect(copyNote({model: "m4t", route_type: "area", settings: {height: "50", collection_mode: "oblique"}}, "m4e")).not.toContain("ortho");
    });
    it("says a copy for the same model is exact", () => {
        expect(copyNote({model: "m4t", settings: {height: "50"}}, "m4t")).toBe("An exact copy.");
    });

    it("gives the new height that keeps the wide camera's ground sample distance", () => {
        const note = copyNote({model: "m4t", settings: {height: "50", lens_visible: "true", lens_ir: "true"}}, "m4e");
        expect(note).toContain("Height 50 m → 66.6 m, to keep 1.79 cm/pixel");
        expect(note).toContain("wide camera only");
        expect(copyNote({model: "m4e", settings: {height: "80"}}, "m4t")).toContain("Height 80 m → 60.06 m");
    });

    it("keeps the height of a thermal-only route", () => {
        const note = copyNote({model: "m4t", settings: {height: "40", lens_visible: "false", lens_ir: "true"}}, "m4e");
        expect(note).toContain("thermal photos only: the copy keeps its height (40 m)");
    });

    it("says a waypoint route's copy keeps its heights, as the server does", () => {
        const note = copyNote({model: "m4t", route_type: "waypoint", settings: {height: "50", lens_visible: "true"}}, "m4e");
        expect(note).toContain("the copy keeps their heights");
        expect(note).not.toContain("→");
    });

    it("says a single-line linear route's copy keeps its height, as the server does", () => {
        const note = copyNote({model: "m4t", route_type: "linear", settings: {height: "50", single_line: "true"}}, "m4e");
        expect(note).toContain("the copy keeps it");
        expect(note).not.toContain("→");
        expect(copyNote({model: "m4t", route_type: "linear", settings: {height: "50", single_line: "false"}}, "m4e")).toContain("→");
    });

    it("says the thermal camera is off but can be turned on in a copy for the Matrice 4T", () => {
        expect(copyNote({model: "m4e", settings: {}}, "m4t")).toContain("the thermal camera can be turned on");
    });
});

describe("importSummary", () => {
    it("gives the aircraft, type, height and overlaps of an ortho route", () => {
        expect(importSummary({model: "m4t", settings: {lens_visible: "true", lens_ir: "true", height: "100.5", altitude_mode: "agl",
                                                       overlap_h: "80", overlap_w: "70", collection_mode: "ortho"}})).toEqual([
            ["Aircraft", "Matrice 4T, wide + thermal cameras"], ["Type", "Ortho"], ["Height", "100.5 m above the ground (AGL)"],
            ["Overlap", "80% forward, 70% side"]
        ]);
    });

    it("adds the gimbal pitch and the oblique overlaps of an oblique route", () => {
        const rows = importSummary({model: "m4e", settings: {lens_visible: "true", lens_ir: "false", height: "50", altitude_mode: "asl",
                                                             overlap_h: "80", overlap_w: "70", collection_mode: "oblique", gimbal_pitch: "-45",
                                                             inclined_overlap_h: "75", inclined_overlap_w: ""}});
        expect(rows).toContainEqual(["Aircraft", "Matrice 4E, wide camera"]);
        expect(rows).toContainEqual(["Type", "Oblique, gimbal at -45°"]);
        expect(rows).toContainEqual(["Height", "50 m above the takeoff ground, flown above sea level (ASL)"]);
        expect(rows).toContainEqual(["Oblique", "75% forward, 70% side"]);
    });

    it("gives a slope route's corners and its distance from the face", () => {
        const rows = importSummary({model: "m4t", route_type: "slope", settings: {lens_visible: "true", lens_ir: "true", height: "28.1",
                                                                                 overlap_h: "80", overlap_w: "80", corners: [[0, 0, 1], [1, 0, 1], [1, 1, 2]]}});
        expect(rows).toContainEqual(["Type", "Slope, 3 corners"]);
        expect(rows).toContainEqual(["Height", "28.1 m from the face"]);
    });

    it("gives a geometric route's corners, its height and its distance from the walls", () => {
        const rows = importSummary({model: "m4t", route_type: "geometric", settings: {lens_visible: "true", lens_ir: "true", height: "6.2",
                                                                                     overlap_h: "80", overlap_w: "80", base: "214.47157", top: "218.97157",
                                                                                     outline: [[0, 0], [1, 0], [1, 1], [0, 1]]}});
        expect(rows).toContainEqual(["Type", "Geometric, 4 corners, 4.5 m high, roof and walls"]);
        expect(rows).toContainEqual(["Height", "6.2 m from the walls"]);
        const walls = importSummary({model: "m4t", route_type: "geometric", settings: {lens_visible: "true", height: "6.2", roof: "false",
                                                                                      base: "0", top: "3", outline: [[0, 0], [1, 0], [1, 1]]}});
        expect(walls).toContainEqual(["Type", "Geometric, 3 corners, 3 m high, walls only"]);
    });

    it("describes an imported waypoint route by its points and height mode, without overlaps", () => {
        expect(importSummary({route_type: "waypoint", model: "m4t", settings: {lens_visible: "true", lens_ir: "false", height: "40",
                                                                               height_mode: "alt", points: [{}, {}, {}]}})).toEqual([
            ["Aircraft", "Matrice 4T, wide camera"], ["Type", "Waypoint, 3 points"], ["Height", "40 m above the takeoff point (ALT)"]
        ]);
        expect(importSummary({route_type: "waypoint", model: "m4t", settings: {height_mode: "agl", points: [{}], shape: {}}}))
            .toContainEqual(["Type", "POI, 1 points"]);
    });

    it("describes an imported linear route by its line and strip", () => {
        const rows = importSummary({route_type: "linear", model: "m4e", settings: {lens_visible: "true", height: "60", altitude_mode: "alt",
                                                                                  line: [[0, 0], [1, 1]], left_extend: "20", right_extend: "30",
                                                                                  single_line: "false", overlap_h: "80", overlap_w: "70"}});
        expect(rows).toContainEqual(["Type", "Linear, 2 points, strip 20 m left, 30 m right"]);
        expect(rows).toContainEqual(["Height", "60 m above the takeoff point (ALT)"]);
        expect(rows).toContainEqual(["Overlap", "80% forward, 70% side"]);
        expect(importSummary({route_type: "linear", model: "m4e", settings: {line: [[0, 0], [1, 1]], single_line: "true"}}))
            .toContainEqual(["Type", "Linear, 2 points, one line"]);
    });

    it("names a thermal-only route's camera", () => {
        expect(importSummary({model: "m4t", settings: {lens_visible: "false", lens_ir: "true"}})[0]).toEqual(["Aircraft", "Matrice 4T, thermal camera"]);
    });
});

describe("formatUpdated", () => {
    it("formats a valid ISO date", () => {
        expect(formatUpdated("2026-01-02T03:04:05Z")).not.toBe("");
    });

    it("returns an empty string for a bad date", () => {
        expect(formatUpdated("not-a-date")).toBe("");
    });
});

describe("routeRow", () => {
    it("links to the route's editor and escapes the name", () => {
        const html = routeRow({id: 7, name: "<b>evil</b>", route_type: "area", updated_at: "2026-01-02T03:04:05Z"}, "/plugins/mission_planner/");
        expect(html).toContain('href="/plugins/mission_planner/route/7"');
        expect(html).toContain("&lt;b&gt;evil&lt;/b&gt;");
        expect(html).not.toContain("<b>evil</b>");
        expect(html).toContain("Area Route");
    });

    it("shows a placeholder for an unnamed route", () => {
        expect(routeRow({id: 1, name: "", route_type: "area", updated_at: "2026-01-02T03:04:05Z"}, "/plugins/mission_planner/")).toContain("(untitled)");
    });

    it("shows a waypoint route with a shape as a POI route", () => {
        expect(routeRow({id: 2, name: "Tower", route_type: "waypoint", settings: {shape: {kind: "circle"}}, updated_at: "2026-01-02T03:04:05Z"},
                        "/plugins/mission_planner/")).toContain("<td>POI Route</td>");
    });

    it("offers a copy action alongside delete", () => {
        const html = routeRow({id: 7, name: "Mine", route_type: "area", updated_at: "2026-01-02T03:04:05Z"}, "/plugins/mission_planner/");
        expect(html).toContain('class="mp-route-copy" data-id="7"');
        expect(html).toContain('class="mp-route-delete" data-id="7"');
    });

    it("offers a rename action", () => {
        const html = routeRow({id: 7, name: "Mine", route_type: "area", updated_at: "2026-01-02T03:04:05Z"}, "/plugins/mission_planner/");
        expect(html).toContain('class="mp-route-rename" data-id="7"');
    });
});

describe("init", () => {
    const HTML = `
        <div id="mp-routes" data-api="/api/plugins/mission_planner/" data-public="/plugins/mission_planner/">
            <input name="csrfmiddlewaretoken" value="tok">
            <label for="mp-new-model">Select Model:</label>
            <select id="mp-new-model"><option value="m4t">DJI Matrice 4T</option><option value="m4e">DJI Matrice 4E</option><option value="m30">DJI Matrice 30</option></select>
            <li><button id="mp-new-area"></button></li>
            <li><button id="mp-new-linear"></button></li>
            <li><button id="mp-new-slope"></button></li>
            <li><button id="mp-new-geometric"></button></li>
            <li><button id="mp-new-waypoint"></button></li>
            <li><button id="mp-new-poi"></button></li>
            <div id="mp-routes-message"></div>
            <table id="mp-routes-table" hidden><tbody id="mp-routes-body"></tbody></table>
            <div id="mp-copy-dialog" hidden>
                <strong id="mp-copy-name"></strong>
                <select id="mp-copy-model"><option value="m4t">DJI Matrice 4T</option><option value="m4e">DJI Matrice 4E</option><option value="m30">DJI Matrice 30</option></select>
                <p id="mp-copy-note"></p>
                <button id="mp-copy-cancel"></button>
                <button id="mp-copy-confirm"></button>
            </div>
            <a id="mp-import-kmz"></a>
            <input type="file" id="mp-import-file" hidden>
            <div id="mp-import-dialog" hidden>
                <strong id="mp-import-name"></strong>
                <dl id="mp-import-summary"></dl>
                <button id="mp-import-close"></button>
                <button id="mp-import-open"></button>
            </div>
        </div>`;

    const jsonResponse = (data, ok = true) => Promise.resolve({ok, json: () => Promise.resolve(data)});
    const flush = () => new Promise(r => setTimeout(r, 0));

    beforeEach(() => {
        document.body.innerHTML = HTML;
        window.prompt = jest.fn(() => "New area route");   // most tests don't care about naming; override per-test as needed
    });

    it("offers in the New Route menu only the route types of the chosen model", () => {
        init(document, jest.fn(() => jsonResponse([])));
        const hidden = () => ["area", "linear", "waypoint", "poi", "slope", "geometric"]
            .filter(t => document.getElementById("mp-new-" + t).closest("li").hidden);
        expect(hidden()).toEqual([]);
        const model = document.getElementById("mp-new-model");
        model.value = "m30";
        model.dispatchEvent(new Event("change", {bubbles: true}));
        expect(hidden()).toEqual(["slope", "geometric"]);
    });

    it("remembers the chosen model for the next visit, and ignores one no longer listed or unreadable storage", () => {
        window.localStorage.clear();
        init(document, jest.fn(() => jsonResponse([])));
        const model = document.getElementById("mp-new-model");
        model.value = "m30";
        model.dispatchEvent(new Event("change", {bubbles: true}));
        document.body.innerHTML = HTML;
        init(document, jest.fn(() => jsonResponse([])));
        expect(document.getElementById("mp-new-model").value).toBe("m30");
        expect(document.getElementById("mp-new-slope").closest("li").hidden).toBe(true);

        window.localStorage.setItem("mission-planner:model", "gone");
        document.body.innerHTML = HTML;
        init(document, jest.fn(() => jsonResponse([])));
        expect(document.getElementById("mp-new-model").value).toBe("m4t");

        const getItem = jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
        document.body.innerHTML = HTML;
        expect(() => init(document, jest.fn(() => jsonResponse([])))).not.toThrow();
        getItem.mockRestore();
        window.localStorage.clear();
    });

    it("does nothing when the page has no routes root", async () => {
        document.body.innerHTML = "";
        const fetchFn = jest.fn();
        init(document, fetchFn);
        expect(fetchFn).not.toHaveBeenCalled();
    });

    it("loads and renders the user's routes", async () => {
        const fetchFn = jest.fn(() => jsonResponse([{id: 3, name: "My area", route_type: "area", updated_at: "2026-01-02T03:04:05Z"}]));
        init(document, fetchFn);
        await flush();

        expect(fetchFn).toHaveBeenCalledWith("/api/plugins/mission_planner/routes", {credentials: "same-origin"});
        expect(document.getElementById("mp-routes-table").hidden).toBe(false);
        expect(document.getElementById("mp-routes-body").innerHTML).toContain("My area");
    });

    it("shows a message and keeps the table hidden when there are no routes", async () => {
        const fetchFn = jest.fn(() => jsonResponse([]));
        init(document, fetchFn);
        await flush();

        expect(document.getElementById("mp-routes-table").hidden).toBe(true);
        expect(document.getElementById("mp-routes-message").textContent).toMatch(/no routes/i);
    });

    it("prompts for a name, posts a new area route for the default model and navigates to its editor", async () => {
        const navigate = jest.fn();
        window.prompt = jest.fn(() => "My survey");
        const fetchFn = jest.fn()
            .mockImplementationOnce(() => jsonResponse([]))                          // the initial load() on init
            .mockImplementationOnce(() => jsonResponse({id: 9, route_type: "area"})); // the create POST
        init(document, fetchFn, navigate);
        await flush();

        document.getElementById("mp-new-area").dispatchEvent(new MouseEvent("click", {bubbles: true}));
        await flush();

        expect(window.prompt).toHaveBeenCalledWith("Name this route:", "New area route");
        const [url, opts] = fetchFn.mock.calls[1];
        expect(url).toBe("/api/plugins/mission_planner/routes");
        expect(opts.method).toBe("POST");
        expect(JSON.parse(opts.body)).toEqual({name: "My survey", route_type: "area", model: "m4t"});
        expect(opts.headers["X-CSRFToken"]).toBe("tok");
        expect(navigate).toHaveBeenCalledWith("/plugins/mission_planner/route/9");
    });

    it("posts a new waypoint route under its own default name and navigates to its editor", async () => {
        const navigate = jest.fn();
        window.prompt = jest.fn(() => "");
        const fetchFn = jest.fn()
            .mockImplementationOnce(() => jsonResponse([]))
            .mockImplementationOnce(() => jsonResponse({id: 12, route_type: "waypoint"}));
        init(document, fetchFn, navigate);
        await flush();

        document.getElementById("mp-new-waypoint").dispatchEvent(new MouseEvent("click", {bubbles: true}));
        await flush();

        expect(window.prompt).toHaveBeenCalledWith("Name this route:", "New waypoint route");
        expect(JSON.parse(fetchFn.mock.calls[1][1].body)).toEqual({name: "New waypoint route", route_type: "waypoint", model: "m4t"});
        expect(navigate).toHaveBeenCalledWith("/plugins/mission_planner/route/12");
    });

    it("posts a new POI route as a waypoint route with a shape, facing the POI in smooth curves above the ground", async () => {
        const navigate = jest.fn();
        window.prompt = jest.fn(() => "");
        const fetchFn = jest.fn()
            .mockImplementationOnce(() => jsonResponse([]))
            .mockImplementationOnce(() => jsonResponse({id: 14, route_type: "waypoint"}));
        init(document, fetchFn, navigate);
        await flush();

        document.getElementById("mp-new-poi").dispatchEvent(new MouseEvent("click", {bubbles: true}));
        await flush();

        expect(window.prompt).toHaveBeenCalledWith("Name this route:", "New POI route");
        const body = JSON.parse(fetchFn.mock.calls[1][1].body);
        expect(body).toMatchObject({name: "New POI route", route_type: "waypoint", model: "m4t",
                                    settings: {heading_mode: "towardPOI", turn_mode: "curve", height_mode: "agl"}});
        expect(body.settings.shape.kind).toBe("circle");
        expect(navigate).toHaveBeenCalledWith("/plugins/mission_planner/route/14");
    });

    it("posts a new linear route under its own default name and navigates to its editor", async () => {
        const navigate = jest.fn();
        window.prompt = jest.fn(() => "");
        const fetchFn = jest.fn()
            .mockImplementationOnce(() => jsonResponse([]))
            .mockImplementationOnce(() => jsonResponse({id: 13, route_type: "linear"}));
        init(document, fetchFn, navigate);
        await flush();

        document.getElementById("mp-new-linear").dispatchEvent(new MouseEvent("click", {bubbles: true}));
        await flush();

        expect(window.prompt).toHaveBeenCalledWith("Name this route:", "New linear route");
        expect(JSON.parse(fetchFn.mock.calls[1][1].body)).toEqual({name: "New linear route", route_type: "linear", model: "m4t"});
        expect(navigate).toHaveBeenCalledWith("/plugins/mission_planner/route/13");
    });

    it("posts a new slope route under its own default name and navigates to its editor", async () => {
        const navigate = jest.fn();
        window.prompt = jest.fn(() => "");
        const fetchFn = jest.fn()
            .mockImplementationOnce(() => jsonResponse([]))
            .mockImplementationOnce(() => jsonResponse({id: 15, route_type: "slope"}));
        init(document, fetchFn, navigate);
        await flush();

        document.getElementById("mp-new-slope").dispatchEvent(new MouseEvent("click", {bubbles: true}));
        await flush();

        expect(window.prompt).toHaveBeenCalledWith("Name this route:", "New slope route");
        expect(JSON.parse(fetchFn.mock.calls[1][1].body)).toEqual({name: "New slope route", route_type: "slope", model: "m4t"});
        expect(navigate).toHaveBeenCalledWith("/plugins/mission_planner/route/15");
    });

    it("posts a new geometric route under its own default name", async () => {
        const navigate = jest.fn();
        window.prompt = jest.fn(() => "");
        const fetchFn = jest.fn()
            .mockImplementationOnce(() => jsonResponse([]))
            .mockImplementationOnce(() => jsonResponse({id: 16, route_type: "geometric"}));
        init(document, fetchFn, navigate);
        await flush();

        document.getElementById("mp-new-geometric").dispatchEvent(new MouseEvent("click", {bubbles: true}));
        await flush();

        expect(JSON.parse(fetchFn.mock.calls[1][1].body)).toEqual({name: "New geometric route", route_type: "geometric", model: "m4t"});
        expect(navigate).toHaveBeenCalledWith("/plugins/mission_planner/route/16");
    });

    it("posts whichever aircraft model is selected", async () => {
        const fetchFn = jest.fn()
            .mockImplementationOnce(() => jsonResponse([]))
            .mockImplementationOnce(() => jsonResponse({id: 9, route_type: "area"}));
        init(document, fetchFn);
        await flush();

        document.getElementById("mp-new-model").value = "m4e";
        document.getElementById("mp-new-area").dispatchEvent(new MouseEvent("click", {bubbles: true}));
        await flush();

        expect(JSON.parse(fetchFn.mock.calls[1][1].body)).toEqual({name: "New area route", route_type: "area", model: "m4e"});
    });

    it("falls back to the default name when a blank name is entered", async () => {
        window.prompt = jest.fn(() => "   ");
        const fetchFn = jest.fn()
            .mockImplementationOnce(() => jsonResponse([]))
            .mockImplementationOnce(() => jsonResponse({id: 9, route_type: "area"}));
        init(document, fetchFn);
        await flush();

        document.getElementById("mp-new-area").dispatchEvent(new MouseEvent("click", {bubbles: true}));
        await flush();

        expect(JSON.parse(fetchFn.mock.calls[1][1].body).name).toBe("New area route");
    });

    it("does not create a route when naming is cancelled", async () => {
        window.prompt = jest.fn(() => null);
        const fetchFn = jest.fn(() => jsonResponse([]));
        init(document, fetchFn);
        await flush();
        const calls = fetchFn.mock.calls.length;

        document.getElementById("mp-new-area").dispatchEvent(new MouseEvent("click", {bubbles: true}));
        await flush();

        expect(fetchFn.mock.calls.length).toBe(calls);
    });

    describe("copy", () => {
        const oneRoute = () => jsonResponse([{id: 5, name: "Field survey", route_type: "area", model: "m4e", updated_at: "2026-01-02T03:04:05Z"}]);

        async function loadOneRoute(fetchFn, navigate) {
            init(document, fetchFn, navigate);
            await flush();
            document.querySelector(".mp-route-copy").dispatchEvent(new MouseEvent("click", {bubbles: true}));
        }

        it("opens the dialog defaulted to the route's own model", async () => {
            await loadOneRoute(jest.fn(() => oneRoute()));
            expect(document.getElementById("mp-copy-dialog").hidden).toBe(false);
            expect(document.getElementById("mp-copy-name").textContent).toBe("Field survey");
            expect(document.getElementById("mp-copy-model").value).toBe("m4e");
            expect(document.getElementById("mp-copy-note").textContent).toBe("An exact copy.");
        });

        it("says what a copy for the other model changes when that model is chosen", async () => {
            await loadOneRoute(jest.fn(() => oneRoute()));
            const model = document.getElementById("mp-copy-model");
            model.value = "m4t";
            model.dispatchEvent(new Event("change", {bubbles: true}));
            expect(document.getElementById("mp-copy-note").textContent).toContain("m → ");
        });

        it("offers only the models that fly the route's type", async () => {
            init(document, jest.fn(() => jsonResponse([{id: 6, name: "Dam face", route_type: "slope", model: "m4e", updated_at: "2026-01-02T03:04:05Z"}])));
            await flush();
            document.querySelector(".mp-route-copy").dispatchEvent(new MouseEvent("click", {bubbles: true}));
            const options = {};
            [].forEach.call(document.getElementById("mp-copy-model").options, o => { options[o.value] = o.disabled; });
            expect(options).toEqual({m4t: false, m4e: false, m30: true});
        });

        it("cancels without making a copy request", async () => {
            const fetchFn = jest.fn(() => oneRoute());
            await loadOneRoute(fetchFn);
            const calls = fetchFn.mock.calls.length;

            document.getElementById("mp-copy-cancel").dispatchEvent(new MouseEvent("click", {bubbles: true}));
            expect(document.getElementById("mp-copy-dialog").hidden).toBe(true);
            expect(fetchFn.mock.calls.length).toBe(calls);
        });

        it("closes when the backdrop (not the dialog box) is clicked", async () => {
            await loadOneRoute(jest.fn(() => oneRoute()));
            document.getElementById("mp-copy-dialog").dispatchEvent(new MouseEvent("click", {bubbles: true}));
            expect(document.getElementById("mp-copy-dialog").hidden).toBe(true);
        });

        it("copies for the same model by default and navigates to the new route", async () => {
            const navigate = jest.fn();
            const fetchFn = jest.fn()
                .mockImplementationOnce(() => oneRoute())
                .mockImplementationOnce(() => jsonResponse({id: 11, route_type: "area", model: "m4e"}));
            await loadOneRoute(fetchFn, navigate);

            document.getElementById("mp-copy-confirm").dispatchEvent(new MouseEvent("click", {bubbles: true}));
            await flush();

            const [url, opts] = fetchFn.mock.calls[1];
            expect(url).toBe("/api/plugins/mission_planner/routes/5/copy");
            expect(opts.method).toBe("POST");
            expect(JSON.parse(opts.body)).toEqual({model: "m4e"});
            expect(opts.headers["X-CSRFToken"]).toBe("tok");
            expect(navigate).toHaveBeenCalledWith("/plugins/mission_planner/route/11");
        });

        it("copies for a different model when one is chosen", async () => {
            const fetchFn = jest.fn()
                .mockImplementationOnce(() => oneRoute())
                .mockImplementationOnce(() => jsonResponse({id: 12, route_type: "area", model: "m4t"}));
            await loadOneRoute(fetchFn);

            document.getElementById("mp-copy-model").value = "m4t";
            document.getElementById("mp-copy-confirm").dispatchEvent(new MouseEvent("click", {bubbles: true}));
            await flush();

            expect(JSON.parse(fetchFn.mock.calls[1][1].body)).toEqual({model: "m4t"});
        });

        it("shows a message when the copy request fails", async () => {
            const fetchFn = jest.fn()
                .mockImplementationOnce(() => oneRoute())
                .mockImplementationOnce(() => jsonResponse({error: "nope"}, false));
            await loadOneRoute(fetchFn);

            document.getElementById("mp-copy-confirm").dispatchEvent(new MouseEvent("click", {bubbles: true}));
            await flush();

            expect(document.getElementById("mp-routes-message").textContent).toMatch(/could not copy/i);
        });
    });

    describe("delete", () => {
        const routesList = [{id: 3, name: "My area", route_type: "area", updated_at: "2026-01-02T03:04:05Z"}];

        it("reloads the list after a delete", async () => {
            window.confirm = jest.fn(() => true);
            const fetchFn = jest.fn((url, opts) => opts && opts.method === "DELETE" ? Promise.resolve({ok: true, status: 204}) : jsonResponse(routesList));
            init(document, fetchFn);
            await flush();
            document.querySelector(".mp-route-delete").click();
            await flush();
            expect(fetchFn).toHaveBeenCalledTimes(3);           // load, delete, load
        });

        it("says so when the server refuses the delete, instead of silently reloading", async () => {
            window.confirm = jest.fn(() => true);
            const fetchFn = jest.fn((url, opts) => opts && opts.method === "DELETE" ? Promise.resolve({ok: false, status: 403}) : jsonResponse(routesList));
            init(document, fetchFn);
            await flush();
            document.querySelector(".mp-route-delete").click();
            await flush();
            expect(fetchFn).toHaveBeenCalledTimes(2);           // no reload
            expect(document.getElementById("mp-routes-message").textContent).toContain("Could not delete the route");
        });
    });

    describe("rename", () => {
        const oneRoute = () => jsonResponse([{id: 5, name: "Field survey", route_type: "area", model: "m4e", updated_at: "2026-01-02T03:04:05Z"}]);

        it("prompts with the current name, and reloads the list on success", async () => {
            window.prompt = jest.fn(() => "New name");
            const fetchFn = jest.fn()
                .mockImplementationOnce(() => oneRoute())                             // initial load()
                .mockImplementationOnce(() => Promise.resolve({ok: true}))            // the PATCH
                .mockImplementationOnce(() => oneRoute());                            // load() again afterwards
            init(document, fetchFn);
            await flush();

            document.querySelector(".mp-route-rename").dispatchEvent(new MouseEvent("click", {bubbles: true}));
            await flush();

            expect(window.prompt).toHaveBeenCalledWith("Rename route:", "Field survey");
            const [url, opts] = fetchFn.mock.calls[1];
            expect(url).toBe("/api/plugins/mission_planner/routes/5");
            expect(opts.method).toBe("PATCH");
            expect(JSON.parse(opts.body)).toEqual({name: "New name"});
            expect(opts.headers["X-CSRFToken"]).toBe("tok");
            expect(fetchFn.mock.calls.length).toBe(3);      // the list was reloaded
        });

        it("does nothing when renaming is cancelled", async () => {
            window.prompt = jest.fn(() => null);
            const fetchFn = jest.fn(() => oneRoute());
            init(document, fetchFn);
            await flush();
            const calls = fetchFn.mock.calls.length;

            document.querySelector(".mp-route-rename").dispatchEvent(new MouseEvent("click", {bubbles: true}));
            await flush();

            expect(fetchFn.mock.calls.length).toBe(calls);
        });

        it("does nothing when the name is left blank or unchanged", async () => {
            const fetchFn = jest.fn(() => oneRoute());
            init(document, fetchFn);
            await flush();
            const calls = fetchFn.mock.calls.length;

            window.prompt = jest.fn(() => "   ");
            document.querySelector(".mp-route-rename").dispatchEvent(new MouseEvent("click", {bubbles: true}));
            await flush();
            expect(fetchFn.mock.calls.length).toBe(calls);

            window.prompt = jest.fn(() => "Field survey");
            document.querySelector(".mp-route-rename").dispatchEvent(new MouseEvent("click", {bubbles: true}));
            await flush();
            expect(fetchFn.mock.calls.length).toBe(calls);
        });

        it("shows a message when the rename request fails", async () => {
            window.prompt = jest.fn(() => "New name");
            const fetchFn = jest.fn()
                .mockImplementationOnce(() => oneRoute())
                .mockImplementationOnce(() => Promise.resolve({ok: false}));
            init(document, fetchFn);
            await flush();

            document.querySelector(".mp-route-rename").dispatchEvent(new MouseEvent("click", {bubbles: true}));
            await flush();

            expect(document.getElementById("mp-routes-message").textContent).toMatch(/could not rename/i);
        });
    });
    describe("import", () => {
        const ROUTE = {id: 12, name: "TestAreaRoute", route_type: "area", model: "m4t", updated_at: "2026-01-02T03:04:05Z",
                       settings: {lens_visible: "true", lens_ir: "true", height: "100.5", altitude_mode: "agl", overlap_h: "80", overlap_w: "70"}};
        const choose = (name) => {
            const input = document.getElementById("mp-import-file");
            Object.defineProperty(input, "files", {value: [new File(["kmz"], name)], configurable: true});
            input.dispatchEvent(new Event("change"));
        };

        it("opens the file chooser from the menu", async () => {
            init(document, jest.fn(() => jsonResponse([])));
            const click = jest.fn();
            document.getElementById("mp-import-file").click = click;
            document.getElementById("mp-import-kmz").click();
            expect(click).toHaveBeenCalled();
        });

        it("uploads the chosen file and shows what the imported route flies", async () => {
            const fetchFn = jest.fn((url, opts) => opts.method === "POST" ? jsonResponse(ROUTE, true) : jsonResponse([]));
            init(document, fetchFn);
            await flush();
            choose("TestAreaRoute.kmz");
            await flush();

            const [url, opts] = fetchFn.mock.calls[1];
            expect(url).toBe("/api/plugins/mission_planner/routes/import");
            expect(opts.headers).toEqual({"X-CSRFToken": "tok"});
            expect(opts.body.get("file").name).toBe("TestAreaRoute.kmz");
            expect(document.getElementById("mp-import-dialog").hidden).toBe(false);
            expect(document.getElementById("mp-import-name").textContent).toBe("TestAreaRoute");
            expect(document.getElementById("mp-import-summary").textContent).toContain("100.5 m above the ground (AGL)");
        });

        it("opens the imported route", async () => {
            const fetchFn = jest.fn((url, opts) => opts.method === "POST" ? jsonResponse(ROUTE, true) : jsonResponse([]));
            const navigate = jest.fn();
            init(document, fetchFn, navigate);
            choose("TestAreaRoute.kmz");
            await flush();
            document.getElementById("mp-import-open").click();
            expect(navigate).toHaveBeenCalledWith("/plugins/mission_planner/route/12");
        });

        it("reloads the list when the dialog is closed instead", async () => {
            const fetchFn = jest.fn((url, opts) => opts.method === "POST" ? jsonResponse(ROUTE, true) : jsonResponse([ROUTE]));
            init(document, fetchFn);
            choose("TestAreaRoute.kmz");
            await flush();
            document.getElementById("mp-import-close").click();
            await flush();
            expect(document.getElementById("mp-import-dialog").hidden).toBe(true);
            expect(fetchFn).toHaveBeenCalledTimes(3);
            expect(document.getElementById("mp-routes-body").innerHTML).toContain("TestAreaRoute");
        });

        it("says why a file is refused, without a dialog", async () => {
            const fetchFn = jest.fn((url, opts) => opts.method === "POST" ? jsonResponse({error: "Smart Oblique missions cannot be imported"}, false) : jsonResponse([]));
            init(document, fetchFn);
            await flush();
            choose("m4e-test-area.kmz");
            await flush();
            expect(document.getElementById("mp-routes-message").textContent).toBe("Could not import m4e-test-area.kmz: Smart Oblique missions cannot be imported.");
            expect(document.getElementById("mp-import-dialog").hidden).toBe(true);
        });
    });
});
