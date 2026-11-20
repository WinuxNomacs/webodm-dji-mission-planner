const { createSearchPanel } = require('../search_panel');

let panel, calls, host;
const make = (over = {}) => {
    calls = {search: []};
    host = document.createElement("div");
    document.body.appendChild(host);
    panel = createSearchPanel(document, Object.assign({onSearch: q => calls.search.push(q)}, over));
    host.appendChild(panel.element);
    return panel;
};
afterEach(() => { document.body.removeChild(host); });

const button = () => panel.element.querySelector(".mp-search-button");
const panelEl = () => panel.element.querySelector(".mp-search-panel");
const input = () => panel.element.querySelector(".mp-search-input");
const submit = () => panel.element.querySelector(".mp-search-submit");
const errorEl = () => panel.element.querySelector(".mp-search-error");
const click = el => el.dispatchEvent(new MouseEvent("click", {bubbles: true}));
const submitForm = () => panel.element.querySelector("form").dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));

describe("search button", () => {
    const links = href => Array.from(document.head.querySelectorAll('link[rel="preconnect"]')).filter(l => l.href.startsWith(href));

    it("connects to the suggestion service once, when the panel first opens", () => {
        make({preconnect: "https://suggest.example"});
        expect(links("https://suggest.example").length).toBe(0);
        panel.open();
        panel.close();
        panel.open();
        expect(links("https://suggest.example").length).toBe(1);
        expect(links("https://suggest.example")[0].getAttribute("crossorigin")).toBe("anonymous");
    });

    it("is a button on the map, closed at first", () => {
        make();
        expect(panel.element.className).toContain("maplibregl-ctrl-group");
        expect(button().title).toBe("Search for an address or coordinates");
        expect(button().getAttribute("aria-expanded")).toBe("false");
        expect(panelEl().hidden).toBe(true);
        expect(panel.isOpen()).toBe(false);
        expect(errorEl().hidden).toBe(true);
    });

    it("opens and closes its panel with the button", () => {
        make();
        click(button());
        expect(panelEl().hidden).toBe(false);
        expect(button().getAttribute("aria-expanded")).toBe("true");
        expect(panel.element.classList.contains("open")).toBe(true);
        click(button());
        expect(panelEl().hidden).toBe(true);
    });

    it("closes when something else is clicked, or on Escape, but not when its own panel is clicked", () => {
        make();
        panel.open();
        click(panelEl());
        expect(panel.isOpen()).toBe(true);
        click(document.body);
        expect(panel.isOpen()).toBe(false);

        panel.open();
        document.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter"}));
        expect(panel.isOpen()).toBe(true);
        document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape"}));
        expect(panel.isOpen()).toBe(false);
    });
});

describe("searching", () => {
    it("announces the typed query on submit", () => {
        make();
        input().value = "1600 Amphitheatre Parkway";
        submitForm();
        expect(calls.search).toEqual(["1600 Amphitheatre Parkway"]);
    });

    it("trims the query and does nothing when it is empty", () => {
        make();
        input().value = "   ";
        submitForm();
        expect(calls.search).toEqual([]);

        input().value = "  40.7128, -74.0060  ";
        submitForm();
        expect(calls.search).toEqual(["40.7128, -74.0060"]);
    });

    it("clears a previous error when a new search is submitted", () => {
        make();
        panel.setError("No results found for that address.");
        expect(errorEl().hidden).toBe(false);
        input().value = "Paris";
        submitForm();
        expect(errorEl().hidden).toBe(true);
    });
});

describe("loading and error feedback", () => {
    it("shows a spinner and disables the button while loading", () => {
        make();
        panel.setLoading(true);
        expect(submit().disabled).toBe(true);
        expect(submit().innerHTML).toContain("fa-spin");
        panel.setLoading(false);
        expect(submit().disabled).toBe(false);
        expect(submit().innerHTML).toContain("fa-search");
    });

    it("shows and clears an error message", () => {
        make();
        panel.setError("Could not reach the address search service.");
        expect(errorEl().hidden).toBe(false);
        expect(errorEl().textContent).toBe("Could not reach the address search service.");
        panel.setError("");
        expect(errorEl().hidden).toBe(true);
    });
});

describe("suggestions", () => {
    const PARIS = {label: "Paris", detail: "Île-de-France, France", center: [2.35, 48.85], bbox: [2.22, 48.81, 2.47, 48.9]};
    const ROMA = {label: "Via Roma 12", detail: "Trento, Italy", center: [11.1, 46.1], bbox: null};
    let asked, answers, picked;

    // suggest answers with what answers[query] holds: an array, a promise, or an Error to reject with
    const makeSuggesting = () => {
        asked = []; answers = {}; picked = [];
        return make({
            suggest: q => { asked.push(q); const a = answers[q]; return a instanceof Error ? Promise.reject(a) : Promise.resolve(a || []); },
            onPick: s => picked.push(s)
        });
    };
    const type = text => { input().value = text; input().dispatchEvent(new Event("input", {bubbles: true})); };
    const key = (k, target = input()) => {
        const e = new KeyboardEvent("keydown", {key: k, bubbles: true, cancelable: true});
        target.dispatchEvent(e);
        return e;
    };
    const list = () => panel.element.querySelector(".mp-search-list");
    const items = () => Array.from(list().querySelectorAll(".mp-search-item"));
    const settle = async () => { jest.advanceTimersByTime(150); await Promise.resolve(); await Promise.resolve(); };

    beforeEach(() => { jest.useFakeTimers(); });
    afterEach(() => { jest.useRealTimers(); });

    it("are asked for 150 ms after typing stops, from the third character", async () => {
        makeSuggesting();
        panel.open();
        answers.Paris = [PARIS];
        type("Pa");
        await settle();
        expect(asked).toEqual([]);
        type("Par");
        jest.advanceTimersByTime(100);
        type("Paris");
        jest.advanceTimersByTime(149);
        expect(asked).toEqual([]);
        await settle();
        expect(asked).toEqual(["Paris"]);
        expect(items().map(i => i.textContent)).toEqual(["ParisÎle-de-France, France"]);
        expect(list().hidden).toBe(false);
        expect(input().getAttribute("aria-expanded")).toBe("true");
    });

    it("show at most five, each with its name and the place it is in", async () => {
        makeSuggesting();
        answers.Roma = Array(7).fill(ROMA);
        type("Roma");
        await settle();
        expect(items().length).toBe(5);
        expect(items()[0].querySelector(".mp-search-label").textContent).toBe("Via Roma 12");
        expect(items()[0].querySelector(".mp-search-detail").textContent).toBe("Trento, Italy");
    });

    it("drop an older answer that arrives after a newer keystroke", async () => {
        makeSuggesting();
        let slow;
        answers.Par = new Promise(r => { slow = r; });
        answers.Paris = [PARIS];
        type("Par");
        await settle();
        type("Paris");
        await settle();
        slow([ROMA]);
        await Promise.resolve(); await Promise.resolve();
        expect(items().map(i => i.querySelector(".mp-search-label").textContent)).toEqual(["Paris"]);
    });

    it("are asked once per query and kept for the page's life", async () => {
        makeSuggesting();
        answers.Paris = [PARIS];
        type("Paris");
        await settle();
        type("Pari");
        await settle();
        type("Paris");
        await settle();
        expect(asked).toEqual(["Paris", "Pari"]);
        expect(items().length).toBe(1);
    });

    it("show no list when there are none, or the service cannot be reached", async () => {
        makeSuggesting();
        answers.Nowhere = [];
        answers.Offline = new Error("offline");
        type("Nowhere");
        await settle();
        expect(list().hidden).toBe(true);
        type("Offline");
        await settle();
        expect(list().hidden).toBe(true);
        expect(errorEl().hidden).toBe(true);
    });

    it("are picked with the arrow keys and Enter, which flies there without searching", async () => {
        makeSuggesting();
        answers.Roma = [ROMA, PARIS];
        type("Roma");
        await settle();
        key("ArrowDown");
        key("ArrowDown");
        key("ArrowDown");
        expect(items()[0].classList.contains("active")).toBe(true);
        key("ArrowUp");
        expect(items()[1].classList.contains("active")).toBe(true);
        expect(key("Enter").defaultPrevented).toBe(true);
        expect(picked).toEqual([PARIS]);
        expect(calls.search).toEqual([]);
        expect(input().value).toBe("Paris");
        expect(list().hidden).toBe(true);
    });

    it("are picked with a click, which keeps the panel open", async () => {
        makeSuggesting();
        panel.open();
        answers.Roma = [ROMA];
        type("Roma");
        await settle();
        click(items()[0]);
        expect(picked).toEqual([ROMA]);
        expect(panel.isOpen()).toBe(true);
    });

    it("Enter with none chosen still searches the typed text, and closes the list", async () => {
        makeSuggesting();
        answers.Roma = [ROMA];
        type("Roma");
        await settle();
        expect(key("Enter").defaultPrevented).toBe(false);
        submitForm();
        expect(calls.search).toEqual(["Roma"]);
        expect(picked).toEqual([]);
        expect(list().hidden).toBe(true);
    });

    it("that are still on their way when the search is submitted are not shown", async () => {
        makeSuggesting();
        answers.Roma = [ROMA];
        type("Roma");
        submitForm();
        await settle();
        expect(asked).toEqual([]);
        expect(list().hidden).toBe(true);
    });

    it("Escape closes the list first, then the panel, and reaches nothing under it", async () => {
        makeSuggesting();
        panel.open();
        answers.Roma = [ROMA];
        type("Roma");
        await settle();
        const reached = [];
        host.addEventListener("keydown", e => reached.push(e.key));
        key("Escape");
        expect(list().hidden).toBe(true);
        expect(panel.isOpen()).toBe(true);
        key("Escape");
        expect(panel.isOpen()).toBe(false);
        expect(reached).toEqual([]);
        key("Escape");
        expect(reached).toEqual(["Escape"]);
    });

    it("are narrowed to those that still match while the next answer is on its way", async () => {
        makeSuggesting();
        const TRENTO = {label: "Trento", detail: "Trentino, Italy", center: [11.12, 46.07], bbox: null};
        answers.Tre = [ROMA, TRENTO, PARIS];
        answers["Tre ital"] = new Promise(() => {});
        type("Tre");
        await settle();
        expect(items().length).toBe(3);
        type("Tre ital");
        expect(items().map(i => i.querySelector(".mp-search-label").textContent)).toEqual(["Via Roma 12", "Trento"]);
        type("Trex");
        expect(list().hidden).toBe(true);
    });

    it("show a spinner in the box while an answer is on its way", async () => {
        makeSuggesting();
        let slow;
        answers.Roma = new Promise(r => { slow = r; });
        const busy = () => panel.element.querySelector(".mp-search-busy");
        expect(busy().hidden).toBe(true);
        type("Roma");
        expect(busy().hidden).toBe(true);
        await settle();
        expect(busy().hidden).toBe(false);
        slow([ROMA]);
        await Promise.resolve(); await Promise.resolve();
        expect(busy().hidden).toBe(true);
        answers.Paris = new Promise(() => {});
        type("Paris");
        await settle();
        expect(busy().hidden).toBe(false);
        submitForm();
        expect(busy().hidden).toBe(true);
    });

    it("are cleared when the panel closes", async () => {
        makeSuggesting();
        panel.open();
        answers.Roma = [ROMA];
        type("Roma");
        await settle();
        panel.close();
        panel.open();
        expect(list().hidden).toBe(true);
    });
});
