// The layers button of the planner's map: a button under the zoom buttons that opens a small panel to choose the map
// (the basemaps of the project), the view (flat or with the terrain raised) and, for 3D, whether the ground is the
// lidar surface (trees and buildings, where USGS lidar exists) or the shape of the ground only, and, with `tasks`, one of
// the user's WebODM tasks over the route with its DSM and orthophoto (task_layers.js fills it). Plain DOM, no map
// library, so that it can be tested; planner.js puts it on the map as a control.
(function (root) {
    // opts: {basemaps: [{label}], selected: label, view3d: bool, lidar: bool, relief: bool, onBasemap(label), onView3d(bool),
    //        onLidar(bool), onRelief(bool), tasks: bool, onTask(id | null), onTaskDsm(bool), onTaskOrthophoto(bool)}
    // Returns {element, setSelected(label), setView3d(on), setLidar(on), open(), close(), isOpen(),
    //          setTasks([{id, name, project_name}], selectedId), setTaskLayers({dsm, orthophoto, dsmEnabled,
    //          orthophotoEnabled}), setTaskNote(text)}
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

        // One of the user's WebODM tasks over the route: a list to pick one (or none), and its two layers
        var taskSelect = null, taskDsm = null, taskOrtho = null, taskNote = null;
        function checkbox(className, text, title, onChange) {
            var label = doc.createElement("label");
            label.className = className;
            label.title = title;
            var input = doc.createElement("input");
            input.type = "checkbox";
            input.disabled = true;
            input.addEventListener("change", function () { if (onChange) onChange(input.checked); });
            label.appendChild(input);
            label.appendChild(doc.createTextNode(" " + text));
            panel.appendChild(label);
            return input;
        }
        if (opts.tasks) {
            heading("WebODM task");
            taskSelect = doc.createElement("select");
            taskSelect.className = "mp-layers-task form-control input-sm";
            taskSelect.setAttribute("aria-label", "WebODM task shown on the map");
            taskSelect.addEventListener("change", function () { if (opts.onTask) opts.onTask(taskSelect.value || null); });
            panel.appendChild(taskSelect);
            taskDsm = checkbox("mp-layers-task-dsm", "DSM (3D ground)",
                               "In 3D, the ground inside the task is its DSM: as new as the flight, matched to the ground around it", opts.onTaskDsm);
            taskOrtho = checkbox("mp-layers-task-ortho", "Orthophoto",
                                 "The task's orthophoto over the basemap, in 2D and 3D", opts.onTaskOrthophoto);
            taskNote = doc.createElement("div");
            taskNote.className = "mp-layers-task-note help-block";
            panel.appendChild(taskNote);
        }
        function setTasks(tasks, selected) {
            if (!taskSelect) return;
            taskSelect.innerHTML = "";
            var none = doc.createElement("option");
            none.value = "";
            none.textContent = tasks.length ? "None" : "None over the route";
            taskSelect.appendChild(none);
            tasks.forEach(function (t) {
                var o = doc.createElement("option");
                o.value = t.id;
                o.textContent = t.name + (t.project_name ? " (" + t.project_name + ")" : "");
                taskSelect.appendChild(o);
            });
            taskSelect.value = selected || "";
            taskSelect.disabled = !tasks.length;
        }
        function setTaskLayers(s) {
            if (!taskSelect) return;
            taskDsm.checked = !!(s.dsm && s.dsmEnabled);
            taskDsm.disabled = !s.dsmEnabled;
            taskOrtho.checked = !!(s.orthophoto && s.orthophotoEnabled);
            taskOrtho.disabled = !s.orthophotoEnabled;
        }
        setTasks([], null);

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
            setTasks: setTasks,
            setTaskLayers: setTaskLayers,
            setTaskNote: function (text) { if (taskNote) taskNote.textContent = text || ""; },
            open: function () { setOpen(true); },
            close: function () { setOpen(false); },
            isOpen: function () { return open; }
        };
    }

    var api = {createLayersPanel: createLayersPanel};
    root.MissionPlannerLayers = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : {});
