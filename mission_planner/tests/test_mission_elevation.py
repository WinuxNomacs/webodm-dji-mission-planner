"""
Tests of the ground-elevation lookup for the ASL height mode (missions/elevation.py). requests is mocked
throughout - no real network calls in the test suite (the live OpenTopography endpoint/response shape was
confirmed by hand while designing this, against the coordinates of testkmz-oblique-asl.kmz).
"""
import os
from unittest.mock import patch

from django.test import SimpleTestCase

import requests

from .. import config
from ..missions import elevation
from ..missions.elevation import ElevationError, KeyRefused, check_api_key, fetch_ground_elevation


def response(status_code=200, json_body=None, raise_json=False):
    class FakeResponse:
        def __init__(self):
            self.status_code = status_code

        def json(self):
            if raise_json:
                raise ValueError("not json")
            return json_body
    return FakeResponse()


SUCCESS_ORTHOMETRIC = {"Status": "Success", "Elevation": 244.0}
SUCCESS_ELLIPSOIDAL = {"Status": "Success", "Elevation": 209.798309326172}


@patch.dict(os.environ, {"WO_OPENTOPOGRAPHY_API_KEY": "test-key"})
class TestFetchGroundElevation(SimpleTestCase):
    @patch(elevation.__name__ + ".requests.get")
    def test_fetches_both_datasets_and_returns_orthometric_and_ellipsoidal(self, get):
        get.side_effect = [response(json_body=SUCCESS_ORTHOMETRIC), response(json_body=SUCCESS_ELLIPSOIDAL)]
        result = fetch_ground_elevation(42.103447, -85.020518)
        self.assertEqual(result, {"orthometric": 244.0, "ellipsoidal": 209.798309326172})

        self.assertEqual(get.call_count, 2)
        datasets = [call.kwargs["params"]["dataset"] for call in get.call_args_list]
        self.assertEqual(datasets, ["SRTM_GL1", "SRTM_GL1_Ellip"])
        for call in get.call_args_list:
            self.assertEqual(call.kwargs["params"]["latitude"], 42.103447)
            self.assertEqual(call.kwargs["params"]["longitude"], -85.020518)
            self.assertEqual(call.kwargs["params"]["API_Key"], "test-key")

    @patch.dict(os.environ, {"WO_OPENTOPOGRAPHY_API_KEY": ""})
    @patch(config.__name__ + ".saved_api_key", return_value="")
    def test_refuses_to_fetch_without_a_configured_key(self, saved):
        with self.assertRaises(ElevationError) as ctx:
            fetch_ground_elevation(42.1, -88.1)
        self.assertIn("API key", str(ctx.exception))

    @patch(elevation.__name__ + ".requests.get")
    def test_a_non_200_response_is_an_elevation_error(self, get):
        get.return_value = response(status_code=502)
        with self.assertRaises(ElevationError) as ctx:
            fetch_ground_elevation(42.1, -88.1)
        self.assertIn("error", str(ctx.exception))

    @patch(elevation.__name__ + ".requests.get")
    def test_a_malformed_body_is_an_elevation_error(self, get):
        get.return_value = response(raise_json=True)
        with self.assertRaises(ElevationError):
            fetch_ground_elevation(42.1, -88.1)

    @patch(elevation.__name__ + ".requests.get")
    def test_a_failure_status_in_the_body_is_an_elevation_error(self, get):
        get.return_value = response(json_body={"Status": "Failure", "Message": "No data at this point"})
        with self.assertRaises(ElevationError) as ctx:
            fetch_ground_elevation(90.0, 0.0)
        self.assertIn("No data at this point", str(ctx.exception))

    @patch(elevation.__name__ + ".requests.get")
    def test_a_failure_message_that_repeats_the_key_is_shown_without_it(self, get):
        get.return_value = response(json_body={"Status": "Failure", "Message": "Rate limit reached for key test-key"})
        with self.assertRaises(ElevationError) as ctx:
            fetch_ground_elevation(42.1, -88.1)
        self.assertIn("Rate limit reached", str(ctx.exception))
        self.assertNotIn("test-key", str(ctx.exception))

    @patch(elevation.__name__ + ".requests.get")
    def test_a_body_that_is_not_an_object_is_an_elevation_error(self, get):
        for body in ([1, 2], "text", None):
            with self.subTest(body=body):
                get.return_value = response(json_body=body)
                with self.assertRaises(ElevationError):
                    fetch_ground_elevation(42.1, -88.1)

    @patch(elevation.__name__ + ".requests.get")
    def test_a_network_error_is_an_elevation_error(self, get):
        import requests
        get.side_effect = requests.ConnectionError("boom")
        with self.assertRaises(ElevationError) as ctx:
            fetch_ground_elevation(42.1, -88.1)
        self.assertIn("Could not reach", str(ctx.exception))

    @patch(elevation.__name__ + ".requests.get")
    def test_stops_after_the_first_failing_dataset_and_does_not_query_the_second(self, get):
        get.side_effect = [response(status_code=500)]
        with self.assertRaises(ElevationError):
            fetch_ground_elevation(42.1, -88.1)
        self.assertEqual(get.call_count, 1)

    @patch(elevation.__name__ + ".requests.get")
    def test_a_refused_key_says_so_and_where_to_change_it(self, get):
        get.return_value = response(status_code=401, json_body={"Status": "Unauthorized", "Elevation": None,
                                                                "Message": "Authentication failed. Invalid API key: test-key"})
        with self.assertRaises(ElevationError) as ctx:
            fetch_ground_elevation(42.1, -88.1)
        self.assertIn("refused the API key (401)", str(ctx.exception))
        self.assertIn("under Settings", str(ctx.exception))
        self.assertNotIn("test-key", str(ctx.exception))

    @patch(elevation.__name__ + ".requests.get")
    def test_an_unreachable_service_does_not_repeat_the_key_in_its_message(self, get):
        get.side_effect = requests.ConnectionError("Max retries exceeded with url: /API/v1/elevation?API_Key=test-key")
        with self.assertRaises(ElevationError) as ctx:
            fetch_ground_elevation(42.1, -88.1)
        self.assertNotIn("test-key", str(ctx.exception))


class TestCheckApiKey(SimpleTestCase):
    """Trying a key before it is saved (the settings page): one request, the key's refusal told apart from an
    unreachable service, and the key never in a message. OpenTopography's refusal below is its answer to a made-up
    key, captured 2026-11-17 (it repeats the key)."""

    @patch(elevation.__name__ + ".requests.get")
    def test_a_key_answered_with_a_height_passes_with_one_request(self, get):
        get.return_value = response(json_body=SUCCESS_ORTHOMETRIC)
        check_api_key("good-key")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["params"]["API_Key"], "good-key")

    @patch(elevation.__name__ + ".requests.get")
    def test_a_refused_key_gives_opentopographys_message_without_the_key(self, get):
        get.return_value = response(status_code=401, json_body={
            "Status": "Unauthorized", "Message": "Authentication failed. Invalid API key: bad-key", "Elevation": None})
        with self.assertRaises(KeyRefused) as ctx:
            check_api_key("bad-key")
        self.assertEqual(str(ctx.exception), "Authentication failed. Invalid API key")

    @patch(elevation.__name__ + ".requests.get")
    def test_a_refusal_without_a_json_body_is_still_a_refusal(self, get):
        get.return_value = response(status_code=403, raise_json=True)
        with self.assertRaises(KeyRefused):
            check_api_key("bad-key")

    @patch(elevation.__name__ + ".requests.get")
    def test_an_unreachable_service_is_not_a_refusal_and_hides_the_key(self, get):
        get.side_effect = requests.ConnectionError("Max retries exceeded with url: /API/v1/elevation?API_Key=a-key")
        with self.assertRaises(ElevationError) as ctx:
            check_api_key("a-key")
        self.assertNotIsInstance(ctx.exception, KeyRefused)
        self.assertNotIn("a-key", str(ctx.exception))

    @patch(elevation.__name__ + ".requests.get")
    def test_another_error_or_an_answer_without_a_height_is_not_a_refusal(self, get):
        for res in (response(status_code=500), response(json_body={"Status": "Failure", "Message": "x"}),
                    response(json_body=[1, 2])):
            get.return_value = res
            with self.assertRaises(ElevationError) as ctx:
                check_api_key("a-key")
            self.assertNotIsInstance(ctx.exception, KeyRefused)
