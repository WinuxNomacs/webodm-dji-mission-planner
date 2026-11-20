// The layers button of the planner's map: a button under the zoom buttons that opens a small panel to choose the map
// (the basemaps of the project), the view (flat or with the terrain raised) and, for 3D, whether the ground is the
// lidar surface (trees and buildings, where USGS lidar exists) or the shape of the ground only. Plain DOM, no map library, so that it can
// be tested; planner.js puts it on the map as a control.
(function (root) {
    // opts: {basemaps: [{label}], selected: label, view3d: bool, lidar: bool, relief: bool, onBasemap(label), onView3d(bool),
    //        onLidar(bool), onRelief(bool)}
    // Returns {element, setSelected(label), setView3d(on), setLidar(on), open(), close(), isOpen()}
    function createLayersPanel(doc, opts) {
        var element = doc.createElement("div");
        element.className = "mp-layers-control maplibregl-ctrl maplibregl-ctrl-group";

        var button = doc.createElement("button");
        button.type = "button";
        button.className = "mp-layers-button";
        button.title = "Map layers";
        button.setAttribute("aria-label", "Map layers");
        button.setAttribute("aria-expanded", "false");
        button.innerHTML = '<i class="fa fa-layer-group"></i>';
        element.appendChild(button);

        var panel = doc.createElement("div");
        panel.className = "mp-layers-panel";
        panel.hidden = true;
        element.appendChild(panel);

        function heading(text) {
            var h = doc.createElement("div");
            h.className = "mp-layers-heading";
            h.textContent = text;
            panel.appendChild(h);
        }

        heading("Map");
        var radios = [];
        (opts.basemaps || []).forEach(function (bm) {
            var label = doc.createElement("label");
            label.className = "mp-layers-choice";
            var input = doc.createElement("input");
            input.type = "radio";
            input.name = "mp-basemap";
            input.value = bm.label;
            input.checked = bm.label === opts.selected;
            input.addEventListener("change", function () { if (input.checked && opts.onBasemap) opts.onBasemap(bm.label); });
            label.appendChild(input);
            label.appendChild(doc.createTextNode(" " + bm.label));
            panel.appendChild(label);
            radios.push(input);
        });

        heading("View");
        var views = doc.createElement("div");
        views.className = "mp-layers-views";
        var flat = doc.createElement("button"), tilted = doc.createElement("button");
        flat.type = tilted.type = "button";
        flat.className = tilted.className = "mp-layers-view";
        flat.textContent = "2D";
        tilted.textContent = "3D";
        flat.title = "Flat map, for drawing";
        tilted.title = "Tilted map with the terrain raised";
        views.appendChild(flat);
        views.appendChild(tilted);
        panel.appendChild(views);

        var lidarLabel = doc.createElement("label");
        lidarLabel.className = "mp-layers-lidar";
        lidarLabel.title = "In 3D, trees and buildings from USGS lidar where it exists (most of the US); elsewhere the shape of the ground only";
        var lidar = doc.createElement("input");
        lidar.type = "checkbox";
        lidar.checked = opts.lidar !== false;
        lidar.addEventListener("change", function () { if (opts.onLidar) opts.onLidar(lidar.checked); });
        lidarLabel.appendChild(lidar);
        lidarLabel.appendChild(doc.createTextNode(" Lidar surface (US)"));
        panel.appendChild(lidarLabel);

        var reliefLabel = doc.createElement("label");
        reliefLabel.className = "mp-layers-relief";
        reliefLabel.title = "In 3D, the ground coloured by its height (blue low, red high) under a stronger shading, with the photo faint over it: the shapes of trees and buildings, whatever the photo shows";
        var relief = doc.createElement("input");
        relief.type = "checkbox";
        relief.checked = !!opts.relief;
        relief.addEventListener("change", function () { if (opts.onRelief) opts.onRelief(relief.checked); });
        reliefLabel.appendChild(relief);
        reliefLabel.appendChild(doc.createTextNode(" Relief (3D)"));
        panel.appendChild(reliefLabel);

        function setView3d(on) {
            flat.classList.toggle("active", !on);
            tilted.classList.toggle("active", !!on);
            flat.setAttribute("aria-pressed", String(!on));
            tilted.setAttribute("aria-pressed", String(!!on));
        }
        flat.addEventListener("click", function () { setView3d(false); if (opts.onView3d) opts.onView3d(false); });
        tilted.addEventListener("click", function () { setView3d(true); if (opts.onView3d) opts.onView3d(true); });
        setView3d(!!opts.view3d);

        var open = false;
        function setOpen(value) {
            open = value;
            panel.hidden = !value;
            button.setAttribute("aria-expanded", String(value));
            element.classList.toggle("open", value);
        }
        button.addEventListener("click", function (e) { e.stopPropagation(); setOpen(!open); });
        // A click anywhere else, or Escape, closes it
        doc.addEventListener("click", function (e) { if (open && !element.contains(e.target)) setOpen(false); });
        doc.addEventListener("keydown", function (e) { if (open && e.key === "Escape") setOpen(false); });

        return {
            element: element,
            setSelected: function (label) { radios.forEach(function (r) { r.checked = r.value === label; }); },
            setView3d: setView3d,
            setLidar: function (on) { lidar.checked = !!on; },
            setRelief: function (on) { relief.checked = !!on; },
            open: function () { setOpen(true); },
            close: function () { setOpen(false); },
            isOpen: function () { return open; }
        };
    }

    var api = {createLayersPanel: createLayersPanel};
    root.MissionPlannerLayers = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
