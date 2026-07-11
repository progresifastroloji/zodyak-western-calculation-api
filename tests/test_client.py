import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from zodyak_western_calculation_api.client import (
    CalculationApiClient,
    CalculationApiClientError,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class CalculationApiClientTest(unittest.TestCase):
    def test_calculate_natal_posts_json_and_returns_data(self):
        recorded = {}

        def fake_urlopen(request, timeout):
            recorded["url"] = request.full_url
            recorded["timeout"] = timeout
            recorded["body"] = json.loads(request.data.decode("utf-8"))
            recorded["content_type"] = request.headers["Content-type"]
            return FakeResponse({"ok": True, "data": {"chart": "ok"}})

        client = CalculationApiClient("http://calc.example/", timeout=7)

        with patch(
            "zodyak_western_calculation_api.client.urlopen",
            side_effect=fake_urlopen,
        ):
            result = client.calculate_natal({"person": {"name": "Reference"}})

        self.assertEqual(result, {"chart": "ok"})
        self.assertEqual(recorded["url"], "http://calc.example/calculate/natal")
        self.assertEqual(recorded["timeout"], 7)
        self.assertEqual(recorded["content_type"], "application/json")
        self.assertEqual(recorded["body"]["person"]["name"], "Reference")

    def test_http_error_json_becomes_client_error_message(self):
        error_body = BytesIO(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "calculation_failed",
                        "message": "birth data is missing",
                    },
                }
            ).encode("utf-8")
        )
        http_error = HTTPError(
            "http://calc.example/calculate/natal",
            400,
            "Bad Request",
            {},
            error_body,
        )
        client = CalculationApiClient("http://calc.example")

        with patch(
            "zodyak_western_calculation_api.client.urlopen",
            side_effect=http_error,
        ):
            with self.assertRaisesRegex(
                CalculationApiClientError,
                "birth data is missing",
            ):
                client.calculate_natal({})


if __name__ == "__main__":
    unittest.main()
