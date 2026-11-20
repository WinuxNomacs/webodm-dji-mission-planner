"""
The saved routes' storage (routes.py): rows of WebODM's plugin data, ids from their primary keys, saves of the named
fields only, terrain folders removed with their route or swept after their owner's deletion.
"""
import os
import shutil

from django.contrib.auth.models import User
from django.test import Client

from app.models import PluginDatum
from app.plugins import disable_plugin, enable_plugin
from app.plugins.data_store import UserDataStore
from app.plugins.functions import get_plugins_persistent_path
from app.tests.classes import BootTestCase

from .. import routes
from .test_mission_planner_plugin import API, terrain_info, terrain_tif


class TestRouteStorage(BootTestCase):
    def setUp(self):
        super().setUp()
        enable_plugin("mission_planner")
        self.user = User.objects.get(username="testuser")
        self.other = User.objects.get(username="testuser2")
        self.client = Client()
        self.client.login(username="testuser", password="test1234")

    def tearDown(self):
        for route in routes.all():
            route.delete()
        disable_plugin("mission_planner")

    def test_a_route_is_a_row_of_its_owners_plugin_data_keyed_by_its_id(self):
        route = routes.create(self.user, name="Field", route_type="slope", model="m4e", settings={"height": "40"})
        datum = PluginDatum.objects.get(pk=route.id)
        self.assertEqual((datum.key, datum.user), ("mission_planner::route:%d" % route.id, self.user))
        self.assertEqual({k: datum.json_value[k] for k in ("name", "route_type", "model", "settings")},
                         {"name": "Field", "route_type": "slope", "model": "m4e", "settings": {"height": "40"}})

    def test_ids_are_unique_across_users(self):
        ids = [routes.create(owner, name="R%d" % i).id for i in range(3) for owner in (self.user, self.other)]
        self.assertEqual(len(set(ids)), 6)

    def test_a_user_lists_only_their_routes_the_most_recently_changed_first(self):
        first = routes.create(self.user, name="First")
        second = routes.create(self.user, name="Second")
        routes.create(self.other, name="Theirs")
        first.name = "First, renamed"
        first.save(("name",))
        self.assertEqual([r.id for r in routes.list_for(self.user)], [first.id, second.id])

    def test_the_plugins_other_data_is_not_a_route(self):
        UserDataStore("mission_planner", self.user).set_string("routes-view", "table")
        UserDataStore("other_plugin", self.user).set_json("route:1", {"name": "Not ours"})
        self.assertEqual(routes.list_for(self.user), [])
        self.assertEqual(self.client.get(API + "routes").json(), [])

    def test_a_save_writes_only_the_fields_it_names(self):
        route = routes.create(self.user, name="Mine", settings={"height": "50"})
        stale = routes.get(route.id)                    # another tab, loaded before the terrain came
        route.save_terrain(terrain_tif(), terrain_info())
        stale.settings = {"height": "60"}
        stale.save(("settings",))
        route.refresh_from_db()
        self.assertEqual(route.settings, {"height": "60"})
        self.assertEqual(route.terrain_info["name"], "wgs84_COP30_N42W086_dem.tif")
        self.assertEqual(route.read_terrain(), terrain_tif())

    def test_saving_a_deleted_route_does_not_bring_it_back(self):
        route = routes.create(self.user, name="Mine")
        stale = routes.get(route.id)
        route.delete()
        stale.name = "Back?"
        with self.assertRaises(routes.RouteGone):
            stale.save(("name",))
        self.assertEqual(routes.count(), 0)

    def test_the_api_answers_404_to_a_save_of_a_deleted_route(self):
        route = routes.create(self.user, name="Mine")
        self.assertEqual(self.client.delete(API + "routes/%d" % route.id).status_code, 204)
        res = self.client.patch(API + "routes/%d" % route.id, '{"name": "Back?"}', content_type="application/json")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(routes.count(), 0)

    def test_a_terrain_fetched_for_a_route_deleted_meanwhile_leaves_no_file(self):
        route = routes.create(self.user, name="Mine")
        stale = routes.get(route.id)
        route.delete()
        with self.assertRaises(routes.RouteGone):
            stale.save_terrain(terrain_tif(), terrain_info())
        self.assertEqual(os.listdir(routes.terrain_folder(route.id)), [])

    def test_two_terrain_fetches_at_once_leave_only_the_terrain_saved_last(self):
        route = routes.create(self.user, name="Mine")
        first, second = routes.get(route.id), routes.get(route.id)     # both loaded before either saves
        first.save_terrain(terrain_tif(), terrain_info())
        second.save_terrain(terrain_tif(), terrain_info())
        self.assertEqual(os.listdir(routes.terrain_folder(route.id)), [os.path.basename(second.terrain_path())])
        self.assertEqual(routes.get(route.id).read_terrain(), terrain_tif())

    def test_a_deleted_users_terrain_folders_are_swept_after_the_next_route_delete(self):
        gone = User.objects.create_user(username="leaving", password="x")
        theirs = routes.create(gone, name="Theirs")
        theirs.save_terrain(terrain_tif(), terrain_info())
        folder = os.path.dirname(theirs.terrain_path())
        mine = routes.create(self.user, name="Mine")
        mine.save_terrain(terrain_tif(), terrain_info())
        kept = routes.create(self.user, name="Kept")
        kept.save_terrain(terrain_tif(), terrain_info())

        gone.delete()                                   # their rows go with them, the folder stays
        self.assertIsNone(routes.get(theirs.id))
        self.assertTrue(os.path.isdir(folder))
        mine.delete()
        self.assertFalse(os.path.exists(folder))
        self.assertFalse(os.path.exists(routes.terrain_folder(mine.id)))
        self.assertEqual(kept.read_terrain(), terrain_tif())

    def test_terrain_survives_the_removal_of_the_plugins_own_folder(self):
        # deleting a plugin installed from a zip (how an upload is upgraded) removes media/plugins/mission_planner
        installed = get_plugins_persistent_path("mission_planner")
        self.assertIn("..", os.path.relpath(routes.terrain_root(), installed))
        route = routes.create(self.user, name="Mine")
        route.save_terrain(terrain_tif(), terrain_info())
        os.makedirs(installed, exist_ok=True)
        shutil.rmtree(installed)                        # as app.plugins.functions.delete_plugin does
        self.assertEqual(routes.get(route.id).read_terrain(), terrain_tif())

    def test_a_route_with_an_unreadable_value_opens_with_its_defaults(self):
        route = routes.create(self.user, name="Mine")
        PluginDatum.objects.filter(pk=route.id).update(json_value=["not", "an", "object"])
        route.refresh_from_db()
        self.assertEqual((route.name, route.route_type, route.model, route.settings), ("", "area", "m4t", {}))
        self.assertIsNone(route.read_terrain())

    def test_a_missing_terrain_file_reads_as_no_terrain(self):
        route = routes.create(self.user, name="Mine")
        route.save_terrain(terrain_tif(), terrain_info())
        os.remove(route.terrain_path())
        self.assertIsNone(route.read_terrain())
