"""
Tests of the plugin's settings (config.py) and its administrators' settings page (plugin.py's settings_page): the
OpenTopography key, from WebODM's environment first, else saved on the page after OpenTopography accepted it.
OpenTopography is never called: check_api_key is replaced.
"""
import os
from unittest import mock

from django.test import Client

from app.models import PluginDatum
from app.plugins import disable_plugin, enable_plugin
from app.tests.classes import BootTestCase

from .. import config
from .. import plugin as mission_planner_plugin
from ..missions.elevation import ElevationError, KeyRefused

PAGE = "/plugins/mission_planner/settings"
LIST = "/plugins/mission_planner/"
KEY = "0123456789abcdef0123456789abcdef"
NO_ENV = {config.ENV_KEY: ""}


def check(side_effect=None):
    return mock.patch.object(mission_planner_plugin, "check_api_key", side_effect=side_effect)


class SettingsTestCase(BootTestCase):
    def setUp(self):
        super().setUp()
        disable_plugin("mission_planner")
        enable_plugin("mission_planner")
        self.admin = Client()
        self.admin.login(username="testsuperuser", password="test1234")
        self.user = Client()
        self.user.login(username="testuser", password="test1234")

    def tearDown(self):
        disable_plugin("mission_planner")

    def save(self, key=KEY, client=None):
        return (client or self.admin).post(PAGE, {"action": "save", "api_key": key})


@mock.patch.dict(os.environ, NO_ENV)
class TestSettingsAccess(SettingsTestCase):
    def test_anonymous_users_are_sent_to_the_login_page(self):
        for res in (Client().get(PAGE), Client().post(PAGE, {"action": "save", "api_key": KEY})):
            self.assertEqual(res.status_code, 302)
            self.assertIn("/login/", res["Location"])
        self.assertEqual(config.saved_api_key(), "")

    def test_users_who_are_not_administrators_are_refused_the_page_and_the_save(self):
        self.assertEqual(self.user.get(PAGE).status_code, 403)
        with check() as checked:
            self.assertEqual(self.save(client=self.user).status_code, 403)
            checked.assert_not_called()
        config.save_api_key(KEY)
        self.assertEqual(self.user.post(PAGE, {"action": "remove"}).status_code, 403)
        self.assertEqual(config.saved_api_key(), KEY)

    def test_only_administrators_see_the_settings_button_on_the_mission_planner_page(self):
        self.assertIn('id="mp-settings-link"', self.admin.get(LIST).content.decode())
        self.assertNotIn('id="mp-settings-link"', self.user.get(LIST).content.decode())

    def test_the_page_needs_the_csrf_token(self):
        admin = Client(enforce_csrf_checks=True)
        admin.login(username="testsuperuser", password="test1234")
        with check():
            self.assertEqual(admin.post(PAGE, {"action": "save", "api_key": KEY}).status_code, 403)
        self.assertEqual(config.saved_api_key(), "")


@mock.patch.dict(os.environ, NO_ENV)
class TestSavingTheKey(SettingsTestCase):
    def test_without_a_key_the_page_says_none_is_set(self):
        html = self.admin.get(PAGE).content.decode()
        self.assertIn("No key is set.", html)
        self.assertNotIn('id="mp-key-remove"', html)

    def test_a_key_opentopography_accepts_is_saved_used_and_never_shown(self):
        with check() as checked:
            res = self.save("  " + KEY + " ")
        checked.assert_called_once_with(KEY)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res["Location"], PAGE + "?done=saved")
        self.assertEqual(config.opentopography_api_key(), KEY)
        self.assertEqual(config.api_key_source(), "saved")
        # one global row of the plugin's, not a user's
        datum = PluginDatum.objects.get(key="mission_planner::opentopography_api_key")
        self.assertIsNone(datum.user)
        html = self.admin.get(res["Location"]).content.decode()
        self.assertIn("tried with OpenTopography and saved", html)
        self.assertIn("A key is saved here", html)
        self.assertIn('id="mp-key-remove"', html)
        self.assertNotIn(KEY, html)
        self.assertNotIn(KEY, self.admin.get(LIST).content.decode())

    def test_a_key_opentopography_refuses_is_not_saved_and_its_message_is_shown(self):
        config.save_api_key("older-key")
        with check(KeyRefused("Authentication failed. Invalid API key")):
            res = self.save()
        self.assertEqual(res.status_code, 400)
        html = res.content.decode()
        self.assertIn("OpenTopography refused this key: Authentication failed. Invalid API key. It was not saved.", html)
        self.assertNotIn(KEY, html)
        self.assertEqual(config.saved_api_key(), "older-key")

    def test_when_opentopography_cannot_be_reached_the_key_is_not_saved(self):
        with check(ElevationError("Could not reach OpenTopography: timed out")):
            res = self.save()
        self.assertEqual(res.status_code, 400)
        self.assertIn("could not be tried: Could not reach OpenTopography: timed out. It was not saved; try again later.",
                      res.content.decode())
        self.assertEqual(config.saved_api_key(), "")

    def test_an_empty_or_malformed_key_is_refused_without_asking_opentopography(self):
        with check() as checked:
            for key, message in (("", "Enter a key."), ("   ", "Enter a key."), ("two words", "not an OpenTopography API key"),
                                 ("x" * 257, "not an OpenTopography API key"), ("a\x00b", "not an OpenTopography API key")):
                res = self.save(key)
                self.assertEqual(res.status_code, 400, key)
                self.assertIn(message, res.content.decode())
            checked.assert_not_called()
        self.assertEqual(config.saved_api_key(), "")

    def test_a_saved_key_can_be_replaced_and_removed(self):
        with check():
            self.save("first-key")
            self.save(KEY)
        self.assertEqual(config.saved_api_key(), KEY)
        res = self.admin.post(PAGE, {"action": "remove"})
        self.assertEqual(res["Location"], PAGE + "?done=removed")
        self.assertIn("The saved key was removed.", self.admin.get(res["Location"]).content.decode())
        self.assertEqual(config.opentopography_api_key(), "")
        self.assertFalse(PluginDatum.objects.filter(key="mission_planner::opentopography_api_key").exists())

    def test_an_unknown_action_changes_nothing(self):
        config.save_api_key(KEY)
        res = self.admin.post(PAGE, {"action": "other", "api_key": "x"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(config.saved_api_key(), KEY)

    def test_the_key_is_not_one_of_the_routes(self):
        from .. import routes
        config.save_api_key(KEY)
        self.assertEqual(routes.count(), 0)


class TestTheEnvironmentWins(SettingsTestCase):
    @mock.patch.dict(os.environ, {config.ENV_KEY: " env-key "})
    def test_the_environments_key_is_used_over_the_saved_one(self):
        config.save_api_key(KEY)
        self.assertEqual(config.opentopography_api_key(), "env-key")
        self.assertEqual(config.api_key_source(), "environment")

    @mock.patch.dict(os.environ, {config.ENV_KEY: "env-key"})
    def test_the_page_says_the_environment_sets_it_and_saves_nothing(self):
        html = self.admin.get(PAGE).content.decode()
        self.assertIn("Set by WebODM's environment", html)
        self.assertIn(config.ENV_KEY, html)
        self.assertNotIn("env-key", html)
        self.assertRegex(html, r'id="mp-api-key"[^>]*disabled')
        with check() as checked:
            res = self.save()
            checked.assert_not_called()
        self.assertEqual(res.status_code, 400)
        self.assertIn("nothing was saved", res.content.decode())
        self.assertEqual(config.saved_api_key(), "")

    @mock.patch.dict(os.environ, NO_ENV)
    def test_without_the_environments_key_the_saved_one_is_used(self):
        config.save_api_key(KEY)
        self.assertEqual(config.opentopography_api_key(), KEY)
