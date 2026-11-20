// The search button of the planner's map: a button under the layers button that opens a small panel to type an
// address or "latitude, longitude" and jump the map there, with suggestions under the box as one types. Plain DOM, no
// map library or network calls, so that it can be tested; planner.js puts it on the map as a control and does the
// actual coordinate parsing/geocoding.
(function (root) {
    var MIN_CHARS = 3, DELAY_MS = 150, MAX_SUGGESTIONS = 5;

    // Whether a suggestion still matches what is typed: every word of it in its label or the place it is in
    function matches(s, query) {
        var text = (s.label + " " + (s.detail || "")).toLowerCase();
        return query.toLowerCase().split(/\s+/).every(function (word) { return text.indexOf(word) !== -1; });
    }

    // opts: {onSearch(query), suggest(query) -> Promise<[{label, detail, center, bbox}]>, onPick(suggestion),
    // preconnect: the suggestion service's origin, connected to when the panel first opens so that the first answer comes sooner}.
    // Returns {element, setLoading(bool), setError(message), open(), close(), isOpen()}
    function createSearchPanel(doc, opts) {
        var element = doc.createElement("div");
        element.className = "mp-search-control maplibregl-ctrl maplibregl-ctrl-group";

        var button = doc.createElement("button");
        button.type = "button";
        button.className = "mp-search-button";
        button.title = "Search for an address or coordinates";
        button.setAttribute("aria-label", "Search for an address or coordinates");
        button.setAttribute("aria-expanded", "false");
        button.innerHTML = '<i class="fa fa-search"></i>';
        element.appendChild(button);

        var panel = doc.createElement("div");
        panel.className = "mp-search-panel";
        panel.hidden = true;
        element.appendChild(panel);

        var form = doc.createElement("form");
        var input = doc.createElement("input");
        input.type = "text";
        input.className = "mp-search-input";
        input.placeholder = "Address or latitude, longitude";
        input.autocomplete = "off";
        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-expanded", "false");
        form.appendChild(input);

        var busy = doc.createElement("i");
        busy.className = "mp-search-busy fa fa-circle-notch fa-spin";
        busy.hidden = true;
        form.appendChild(busy);

        var submit = doc.createElement("button");
        submit.type = "submit";
        submit.className = "mp-search-submit";
        submit.innerHTML = '<i class="fa fa-search"></i>';
        form.appendChild(submit);
        panel.appendChild(form);

        var list = doc.createElement("ul");
        list.className = "mp-search-list";
        list.setAttribute("role", "listbox");
        list.hidden = true;
        panel.appendChild(list);

        var error = doc.createElement("div");
        error.className = "mp-search-error";
        error.hidden = true;
        panel.appendChild(error);

        // -- suggestions ------------------------------------------------------------------------------------------------

        var shown = [], active = -1, timer = null, asked = 0, cache = {};

        function showList(suggestions) {
            shown = (suggestions || []).slice(0, MAX_SUGGESTIONS);
            active = -1;
            list.innerHTML = "";
            shown.forEach(function (s, i) {
                var item = doc.createElement("li");
                item.className = "mp-search-item";
                item.setAttribute("role", "option");
                var label = doc.createElement("span");
                label.className = "mp-search-label";
                label.textContent = s.label;
                item.appendChild(label);
                if (s.detail) {
                    var detail = doc.createElement("span");
                    detail.className = "mp-search-detail";
                    detail.textContent = s.detail;
                    item.appendChild(detail);
                }
                item.addEventListener("click", function () { pick(i); });
                list.appendChild(item);
            });
            list.hidden = !shown.length;
            input.setAttribute("aria-expanded", String(shown.length > 0));
        }
        function hideList() { showList([]); }
        function listShown() { return !list.hidden; }

        function setActive(i) {
            active = i;
            Array.prototype.forEach.call(list.children, function (item, j) {
                item.classList.toggle("active", j === i);
                item.setAttribute("aria-selected", String(j === i));
            });
        }

        // Whatever is still on its way is no longer wanted
        function forget() {
            if (timer) clearTimeout(timer);
            timer = null;
            asked++;
            busy.hidden = true;
        }

        function pick(i) {
            var s = shown[i];
            if (!s) return;
            forget();
            input.value = s.label;
            hideList();
            error.hidden = true;
            if (opts.onPick) opts.onPick(s);
        }

        // Answers are kept for the page's life; only the latest question's answer is shown
        function ask(query) {
            if (Object.prototype.hasOwnProperty.call(cache, query)) { showList(cache[query]); return; }
            var mine = ++asked;
            busy.hidden = false;
            Promise.resolve(opts.suggest(query)).then(function (suggestions) {
                cache[query] = suggestions || [];
                if (mine === asked) { busy.hidden = true; showList(cache[query]); }
            }, function () {
                if (mine === asked) { busy.hidden = true; hideList(); }        // no service: no list, Enter still searches
            });
        }

        // Until the new answer comes, the matches shown are narrowed to those that still match
        input.addEventListener("input", function () {
            forget();
            var query = input.value.trim();
            if (!opts.suggest || query.length < MIN_CHARS) { hideList(); return; }
            showList(shown.filter(function (s) { return matches(s, query); }));
            timer = setTimeout(function () { timer = null; ask(query); }, DELAY_MS);
        });

        input.addEventListener("keydown", function (e) {
            if (!listShown()) return;
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                var n = shown.length;
                setActive(e.key === "ArrowDown" ? (active + 1) % n : (active <= 0 ? n : active) - 1);
            } else if (e.key === "Enter" && active >= 0) {
                e.preventDefault();
                pick(active);
            }
        });

        form.addEventListener("submit", function (e) {
            e.preventDefault();
            var query = input.value.trim();
            if (!query) return;
            forget();
            hideList();
            error.hidden = true;
            if (opts.onSearch) opts.onSearch(query);
        });

        // -- opening and closing ----------------------------------------------------------------------------------------

        var open = false, connected = false;
        function preconnect() {
            if (connected || !opts.preconnect || !doc.head) return;
            connected = true;
            var link = doc.createElement("link");
            link.rel = "preconnect";
            link.href = opts.preconnect;
            link.crossOrigin = "anonymous";            // as fetch asks, or the browser opens another connection
            doc.head.appendChild(link);
        }
        function setOpen(value) {
            open = value;
            if (value) preconnect();
            panel.hidden = !value;
            button.setAttribute("aria-expanded", String(value));
            element.classList.toggle("open", value);
            if (value) input.focus();
            else { forget(); hideList(); }
        }
        button.addEventListener("click", function (e) { e.stopPropagation(); setOpen(!open); });
        // A click anywhere else closes it - same convention as the layers panel. A picked suggestion is gone from the
        // page by the time its click gets here: not a click elsewhere
        doc.addEventListener("click", function (e) {
            if (open && !element.contains(e.target) && doc.documentElement.contains(e.target)) setOpen(false);
        });
        // Escape closes the list, then the panel, and goes no further: not to a dialog the map is in (hence the capture
        // phase, before the dialog hears it)
        doc.addEventListener("keydown", function (e) {
            if (!open || e.key !== "Escape" || !doc.documentElement.contains(element)) return;
            e.preventDefault();
            e.stopPropagation();
            if (listShown()) hideList(); else setOpen(false);
        }, true);

        return {
            element: element,
            setLoading: function (loading) {
                submit.disabled = !!loading;
                submit.innerHTML = loading ? '<i class="fa fa-circle-notch fa-spin"></i>' : '<i class="fa fa-search"></i>';
            },
            setError: function (message) { error.textContent = message || ""; error.hidden = !message; },
            open: function () { setOpen(true); },
            close: function () { setOpen(false); },
            isOpen: function () { return open; }
        };
    }

    var api = {createSearchPanel: createSearchPanel};
    root.MissionPlannerSearch = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
