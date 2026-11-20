from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext_lazy as _

from app.models import Basemap
from app.plugins import PluginBase, Menu, MountPoint

from . import config, lidar, luxodm_import, routes
from .missions import drones
from .missions.elevation import ElevationError, KeyRefused, check_api_key
from .api import BlockHeightsView, ExportView, FaceHeightsView, KmlView, LidarSurfaceView, LidarTileView, PlanView, RouteCopyView, RouteDetailView, RouteElevationView, RouteImportView, RouteListCreateView, RoutePointElevationsView, RouteTerrainView, SUPPORTED_ROUTE_TYPES


class Plugin(PluginBase):
    def main_menu(self):
        return [Menu(_("DJI Mission Planner"), self.public_url(""), "fa fa-route fa-fw")]

    def api_mount_points(self):
        return [
            MountPoint('plan$', PlanView.as_view()),
            MountPoint('export$', ExportView.as_view()),
            MountPoint('kml$', KmlView.as_view()),
            MountPoint('face-heights$', FaceHeightsView.as_view()),
            MountPoint('block-heights$', BlockHeightsView.as_view()),
            MountPoint('routes$', RouteListCreateView.as_view()),
            MountPoint('routes/import$', RouteImportView.as_view()),
            MountPoint(r'routes/(?P<pk>[0-9]+)$', RouteDetailView.as_view()),
            MountPoint(r'routes/(?P<pk>[0-9]+)/copy$', RouteCopyView.as_view()),
            MountPoint(r'routes/(?P<pk>[0-9]+)/elevation$', RouteElevationView.as_view()),
            MountPoint(r'routes/(?P<pk>[0-9]+)/point-elevations$', RoutePointElevationsView.as_view()),
            MountPoint(r'routes/(?P<pk>[0-9]+)/terrain$', RouteTerrainView.as_view()),
            MountPoint('lidar/surface$', LidarSurfaceView.as_view()),
            MountPoint(r'lidar/tiles/(?P<z>[0-9]{1,2})/(?P<x>[0-9]{1,7})/(?P<y>[0-9]{1,7})\.png$', LidarTileView.as_view()),
        ]

    def app_mount_points(self):
        common = {
            'title': _("DJI Mission Planner"),
            'public': self.public_url(""),
            'api': "/api/plugins/{}/".format(self.get_name()),
            # the aircraft (drones.json): planner_core.js reads them from the page, the templates list them
            'drones': drones.DATA,
        }

        @login_required
        def routes_list(request):
            return render(request, self.template_path("routes_list.html"), dict(common,
                is_admin=request.user.is_superuser))

        @login_required
        def settings(request):
            return settings_page(request, self.template_path("settings.html"), dict(common,
                title=_("DJI Mission Planner settings")))

        @login_required
        def route_editor(request, route_id):
            route = routes.get_for(request.user, route_id)
            if route is None:
                raise Http404("No such route")
            if route.route_type not in SUPPORTED_ROUTE_TYPES:
                # Cannot happen via the UI today (only Area, Linear, Waypoint, Slope and Geometric Routes can be created) - future-proofing for
                # when a route_type has no editor of its own yet.
                raise Http404("This route type does not have an editor yet")
            # A waypoint route has its own editor: points clicked on the map instead of an area
            template = "waypoint_planner.html" if route.route_type == "waypoint" else "planner.html"
            return render(request, self.template_path(template), dict(common,
                # the same layers as the map of the tasks: Administration > Basemaps
                basemaps=Basemap.get_cached_basemaps(),
                route_id=route.id,
                route=route,
                drone=drones.DRONES.get(route.model),
            ))

        return [
            MountPoint('$', routes_list),
            MountPoint(r'route/(?P<route_id>[0-9]+)$', route_editor),
            MountPoint('settings$', settings),
        ]


MAX_KEY_LENGTH = 256


IMPORT_REPORT = "mission_planner_import_report"


def settings_page(request, template, context):
    """
    The administrators' settings page: the OpenTopography key, the lidar surface's size (with a button to clear it), and the import of LuxODM's routes. The page says where the key in use comes from and
    never shows it. Saving tries the key with OpenTopography first (missions.elevation.check_api_key), and keeps it
    only when OpenTopography answers with a height. WebODM's environment wins, so nothing is saved while it sets one.
    The import's report is kept in the session for the page the import redirects to, so reloading that page imports
    nothing again.
    """
    if not request.user.is_superuser:
        raise PermissionDenied()
    error = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "remove":
            config.remove_api_key()
            return redirect(request.path + "?done=removed")
        if action == "clear_lidar":
            if lidar.clear():
                return redirect(request.path + "?done=lidar_cleared")
            error = _("The lidar surface is being built: try again when it is done.")
        elif action == "import":
            upload = request.FILES.get("routes_file")
            if upload is None:
                error = _("Choose a LuxODM routes export to import.")
            else:
                try:
                    checked = luxodm_import.read(upload.read(luxodm_import.MAX_FILE_BYTES + 1))
                except luxodm_import.ImportRefused as e:
                    error = _("The file was not imported: %(message)s.") % {"message": str(e)}
                else:
                    request.session[IMPORT_REPORT] = luxodm_import.import_routes(checked)
                    return redirect(request.path + "?done=imported")
        elif action == "save":
            key = request.POST.get("api_key", "").strip()
            if config.environment_api_key():
                error = _("WebODM's environment sets the key (WO_OPENTOPOGRAPHY_API_KEY): nothing was saved.")
            elif not key:
                error = _("Enter a key.")
            elif len(key) > MAX_KEY_LENGTH or any(c.isspace() or not c.isprintable() for c in key):
                error = _("That is not an OpenTopography API key (no spaces, at most %(n)d characters).") % {
                    "n": MAX_KEY_LENGTH}
            else:
                try:
                    check_api_key(key)
                except KeyRefused as e:
                    error = _("OpenTopography refused this key: %(message)s. It was not saved.") % {"message": str(e)}
                except ElevationError as e:
                    error = _("The key could not be tried: %(message)s. It was not saved; try again later.") % {
                        "message": str(e)}
                else:
                    config.save_api_key(key)
                    return redirect(request.path + "?done=saved")
        else:
            error = _("Unknown action.")
    done = request.GET.get("done") if request.method == "GET" else None
    report = request.session.pop(IMPORT_REPORT, None) if done == "imported" else None
    lidar_units, lidar_size = lidar.usage()
    return render(request, template, dict(context,
        lidar_units=lidar_units,
        lidar_size=filesizeformat(lidar_size),
        lidar_cap=filesizeformat(lidar.MAX_BYTES),
        report=report,
        imported=sum(1 for line in report if line["id"]) if report else 0,
        source=config.api_key_source(),
        env_name=config.ENV_KEY,
        error=error,
        done=done if done in ("saved", "removed", "lidar_cleared") or (done == "imported" and report is not None) else None,
    ), status=400 if error else 200)
