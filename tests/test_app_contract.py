import os
import unittest
from unittest.mock import patch

from zodyak_western_calculation_api import create_app


REFERENCE_PAYLOAD = {
    "person": {"id": "reference", "name": "Reference"},
    "birth": {
        "year": 2000,
        "month": 1,
        "day": 1,
        "hour": 12,
        "minute": 0,
        "second": 0,
        "timezone_id": "UTC",
        "lat": 51.4779,
        "lon": 0.0,
        "place": "Greenwich",
        "time_confidence": "high",
    },
    "options": {
        "zodiac": "tropical",
        "house_system": "placidus",
        "node_type": "true",
        "orb_profile": "modern_standard_v1",
    },
}

REFERENCE_BIRTH_B = {
    "year": 2001,
    "month": 2,
    "day": 3,
    "hour": 6,
    "minute": 30,
    "second": 0,
    "timezone_id": "UTC",
    "lat": 40.7128,
    "lon": -74.006,
    "place": "New York",
    "time_confidence": "high",
}

REFERENCE_PAIR_PAYLOAD = {
    "person_a": {
        "id": "reference-a",
        "name": "Reference A",
        "birth": REFERENCE_PAYLOAD["birth"],
    },
    "person_b": {
        "id": "reference-b",
        "name": "Reference B",
        "birth": REFERENCE_BIRTH_B,
    },
    "options": REFERENCE_PAYLOAD["options"],
}


class CalculationApiContractTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_healthz_returns_license_block(self):
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["engine"], "zodyak-western-calculation-api")
        self.assertEqual(data["license"]["service_license"], "AGPL-3.0-or-later")
        self.assertEqual(data["license"]["ephemeris_license_mode"], "agpl")

    def test_license_endpoint_names_boundary(self):
        response = self.client.get("/license")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        boundary = data["data"]["license"]["source_boundary"]
        self.assertIn("technical calculation service only", boundary)
        self.assertIn("vault", boundary)
        self.assertIn("prompts", boundary)
        self.assertTrue(
            data["data"]["license"]["source"]["agpl_network_source_obligation"]
        )

    def test_source_endpoint_exposes_corresponding_source_offer(self):
        with patch.dict(os.environ, {"WESTERN_CALC_SOURCE_CODE_URL": ""}):
            response = self.client.get("/source")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        source = data["data"]["source"]
        self.assertTrue(source["agpl_network_source_obligation"])
        self.assertFalse(source["source_code_url_configured"])
        self.assertEqual(source["source_code_url"], "")
        self.assertEqual(source["source_code_url_env"], "WESTERN_CALC_SOURCE_CODE_URL")
        self.assertEqual(source["service_license_file"], "LICENSE")
        self.assertEqual(source["notice_file"], "NOTICE")
        self.assertIn("WESTERN_CALC_SOURCE_CODE_URL", source["message"])

    def test_source_endpoint_uses_configured_public_source_url(self):
        with patch.dict(
            os.environ,
            {
                "WESTERN_CALC_SOURCE_CODE_URL": (
                    "https://github.com/progresifastroloji/zodyak-western-calculation-api"
                )
            },
        ):
            response = self.client.get("/source")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        source = data["data"]["source"]
        self.assertTrue(source["source_code_url_configured"])
        self.assertEqual(
            source["source_code_url"],
            "https://github.com/progresifastroloji/zodyak-western-calculation-api",
        )
        self.assertIn("source_code_url", source["message"])

    def test_schema_endpoint_lists_reserved_calculation_contract(self):
        response = self.client.get("/schema")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        schema = data["data"]["schema"]
        paths = {item["path"]: item for item in schema["endpoints"]}
        self.assertEqual(paths["/calculate/natal"]["status"], "available")
        self.assertEqual(paths["/calculate/transits"]["status"], "available")
        self.assertEqual(
            paths["/calculate/forecast-layers"]["status"],
            "available",
        )
        self.assertEqual(paths["/calculate/solar-return"]["status"], "available")
        self.assertEqual(paths["/calculate/lunar-return"]["status"], "available")
        self.assertEqual(paths["/calculate/progressions"]["status"], "available")
        self.assertEqual(paths["/calculate/solar-arc"]["status"], "available")
        self.assertEqual(
            paths["/calculate/primary-directions"]["status"],
            "available",
        )
        self.assertEqual(paths["/calculate/firdaria"]["status"], "available")
        self.assertEqual(paths["/calculate/midpoints"]["status"], "available")
        self.assertEqual(paths["/calculate/parans"]["status"], "available")
        self.assertEqual(paths["/calculate/synastry"]["status"], "available")
        self.assertEqual(paths["/calculate/composite"]["status"], "available")
        self.assertEqual(paths["/calculate/davison"]["status"], "available")
        self.assertEqual(paths["/calculate/relocation"]["status"], "available")
        self.assertEqual(
            paths["/calculate/astrocartography"]["status"],
            "available",
        )
        self.assertEqual(paths["/calculate/local-space"]["status"], "available")
        self.assertEqual(paths["/calculate/horary"]["status"], "available")
        self.assertEqual(paths["/calculate/electional"]["status"], "available")
        self.assertEqual(paths["/calculate/mundane"]["status"], "available")
        self.assertEqual(paths["/calculate/rectification"]["status"], "available")
        self.assertIn("planets", paths["/calculate/natal"]["success_data_keys"])
        self.assertIn("vault writes", schema["closed_system_exclusions"])

    def test_calculate_natal_returns_technical_chart_json(self):
        response = self.client.post("/calculate/natal", json=REFERENCE_PAYLOAD)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        chart = data["data"]
        self.assertEqual(chart["meta"]["engine"], "progressive-western-chart")
        self.assertEqual(chart["meta"]["ephemeris"]["library"], "Swiss Ephemeris")
        self.assertIn("planets", chart)
        self.assertIn("houses", chart)
        self.assertIn("aspects", chart)

    def test_calculate_transits_returns_technical_period_json(self):
        payload = {
            **REFERENCE_PAYLOAD,
            "transit": {
                "start_date": "2001-01-01",
                "end_date": "2001-01-03",
                "timezone_id": "UTC",
                "transit_hour": 12,
            },
        }

        response = self.client.post("/calculate/transits", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        transit = data["data"]
        self.assertEqual(transit["status"], "available")
        self.assertEqual(transit["period"]["day_count"], 3)
        self.assertEqual(len(transit["snapshots"]), 3)
        self.assertIn("exact_aspects", transit)

    def test_calculate_endpoints_require_json_object(self):
        response = self.client.post("/calculate/transits", data="not-json")

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["error"]["code"], "invalid_request")

    def test_calculate_solar_return_returns_technical_json(self):
        payload = {**REFERENCE_PAYLOAD, "return_year": 2001}

        response = self.client.post("/calculate/solar-return", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        solar_return = data["data"]
        self.assertEqual(solar_return["status"], "available")
        self.assertEqual(solar_return["return_year"], 2001)
        self.assertIn("sr_chart", solar_return)

    def test_calculate_lunar_return_returns_technical_json(self):
        payload = {**REFERENCE_PAYLOAD, "return_date": "2001-01-02"}

        response = self.client.post("/calculate/lunar-return", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        lunar_return = data["data"]
        self.assertEqual(lunar_return["status"], "available")
        self.assertEqual(lunar_return["return_date_requested"], "2001-01-02")
        self.assertIn("lr_chart", lunar_return)

    def test_calculate_progressions_returns_technical_json(self):
        payload = {
            **REFERENCE_PAYLOAD,
            "progressions": {"target_date": "2001-01-02"},
        }

        response = self.client.post("/calculate/progressions", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        progressions = data["data"]
        self.assertEqual(progressions["status"], "available")
        self.assertEqual(progressions["target_date"], "2001-01-02")

    def test_calculate_solar_arc_returns_technical_json(self):
        payload = {
            **REFERENCE_PAYLOAD,
            "solar_arc": {"target_date": "2001-01-02"},
        }

        response = self.client.post("/calculate/solar-arc", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        solar_arc = data["data"]
        self.assertEqual(solar_arc["status"], "available")
        self.assertEqual(solar_arc["target_date"], "2001-01-02")

    def test_calculate_primary_directions_returns_technical_json(self):
        payload = {
            **REFERENCE_PAYLOAD,
            "primary_directions": {"target_date": "2001-01-02"},
        }

        response = self.client.post("/calculate/primary-directions", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        primary_directions = data["data"]
        self.assertEqual(primary_directions["status"], "available")
        self.assertEqual(primary_directions["target_date"], "2001-01-02")

    def test_calculate_firdaria_returns_technical_json(self):
        payload = {
            **REFERENCE_PAYLOAD,
            "firdaria": {"target_date": "2001-01-02"},
        }

        response = self.client.post("/calculate/firdaria", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        firdaria = data["data"]
        self.assertEqual(firdaria["status"], "available")
        self.assertEqual(firdaria["target_date"], "2001-01-02")
        self.assertIn("current_major", firdaria)

    def test_calculate_midpoints_returns_technical_json(self):
        response = self.client.post("/calculate/midpoints", json=REFERENCE_PAYLOAD)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        midpoints = data["data"]
        self.assertEqual(midpoints["status"], "available")
        self.assertGreater(midpoints["midpoints_count"], 0)
        self.assertIn("dial_45", midpoints)

    def test_calculate_parans_returns_technical_json(self):
        response = self.client.post("/calculate/parans", json=REFERENCE_PAYLOAD)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        parans = data["data"]
        self.assertEqual(parans["status"], "available")
        self.assertIn("parans_count", parans)
        self.assertIn("stars_skipped", parans)

    def test_calculate_synastry_returns_technical_json(self):
        response = self.client.post("/calculate/synastry", json=REFERENCE_PAIR_PAYLOAD)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        synastry = data["data"]
        self.assertEqual(synastry["status"], "available")
        self.assertIn("interaspects", synastry)
        self.assertIn("house_overlay", synastry)

    def test_calculate_composite_returns_technical_json(self):
        response = self.client.post("/calculate/composite", json=REFERENCE_PAIR_PAYLOAD)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        composite = data["data"]
        self.assertEqual(composite["status"], "available")
        self.assertIn("points", composite)
        self.assertIn("angles", composite)

    def test_calculate_davison_returns_technical_json(self):
        response = self.client.post("/calculate/davison", json=REFERENCE_PAIR_PAYLOAD)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        davison = data["data"]
        self.assertEqual(davison["status"], "available")
        self.assertIn("davison_chart", davison)
        self.assertIn("davison_moment", davison)

    def test_calculate_relocation_returns_technical_json(self):
        payload = {
            **REFERENCE_PAYLOAD,
            "relocation": {
                "lat": 41.0082,
                "lon": 28.9784,
                "timezone_id": "Europe/Istanbul",
                "place": "Istanbul",
            },
        }

        response = self.client.post("/calculate/relocation", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        relocation = data["data"]
        self.assertEqual(relocation["status"], "available")
        self.assertIn("relocated_chart", relocation)
        self.assertIn("angle_comparison", relocation)

    def test_calculate_astrocartography_returns_technical_json(self):
        payload = {
            **REFERENCE_PAYLOAD,
            "astrocartography": {
                "interest_points": [
                    {"name": "Istanbul", "lat": 41.0082, "lon": 28.9784}
                ]
            },
        }

        response = self.client.post("/calculate/astrocartography", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        astrocartography = data["data"]
        self.assertEqual(astrocartography["status"], "available")
        self.assertIn("lines", astrocartography)
        self.assertIn("interest_points", astrocartography)

    def test_calculate_local_space_returns_technical_json(self):
        response = self.client.post("/calculate/local-space", json=REFERENCE_PAYLOAD)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        local_space = data["data"]
        self.assertEqual(local_space["status"], "available")
        self.assertIn("items", local_space)
        self.assertIn("skipped", local_space)

    def test_calculate_horary_returns_technical_json(self):
        payload = {
            "person": {"id": "reference", "name": "Reference"},
            "horary": {
                "question": "Bu ortaklık ilerler mi?",
                "category": "marriage",
                "question_datetime_utc": "2026-06-25T12:00:00Z",
                "location": {
                    "lat": 41.0082,
                    "lon": 28.9784,
                    "timezone_id": "Europe/Istanbul",
                    "place": "Istanbul",
                },
            },
        }

        response = self.client.post("/calculate/horary", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        horary = data["data"]
        self.assertEqual(horary["status"], "available")
        self.assertIn("full_chart", horary)
        self.assertIn("significators", horary)

    def test_calculate_electional_returns_technical_json(self):
        payload = {
            "electional": {
                "purpose": "contract",
                "window_start": "2026-07-01T00:00:00Z",
                "window_end": "2026-07-01T02:00:00Z",
                "step_minutes": 60,
                "top_n": 2,
                "location": {
                    "lat": 41.0082,
                    "lon": 28.9784,
                    "timezone_id": "Europe/Istanbul",
                    "place": "Istanbul",
                },
            },
            "options": REFERENCE_PAYLOAD["options"],
        }

        response = self.client.post("/calculate/electional", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        electional = data["data"]
        self.assertEqual(electional["status"], "available")
        self.assertIn("window", electional)
        self.assertIn("top_candidates", electional)

    def test_calculate_mundane_returns_technical_json(self):
        payload = {
            "mundane": {
                "event_type": "aries_ingress",
                "year": 2026,
                "location": {
                    "lat": 41.0082,
                    "lon": 28.9784,
                    "timezone_id": "Europe/Istanbul",
                    "place": "Istanbul",
                },
            },
            "options": REFERENCE_PAYLOAD["options"],
        }

        response = self.client.post("/calculate/mundane", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        mundane = data["data"]
        self.assertEqual(mundane["status"], "available")
        self.assertEqual(mundane["event_type"], "aries_ingress")
        self.assertIn("events", mundane)

    def test_calculate_rectification_returns_technical_json(self):
        payload = {
            "birth_base": {
                "year": 2000,
                "month": 1,
                "day": 1,
                "lat": 51.4779,
                "lon": 0.0,
                "timezone_id": "UTC",
                "place": "Greenwich",
                "time_confidence": "approximate",
            },
            "search_window": {
                "start_time": "11:58:00",
                "end_time": "12:02:00",
                "step_minutes": 2,
            },
            "birth_window": {
                "timezone_id": "UTC",
                "source_quality": "approximate",
            },
            "events": [
                {
                    "date": "2020-01-01",
                    "type": "career",
                    "description": "career milestone",
                }
            ],
            "options": REFERENCE_PAYLOAD["options"],
        }

        response = self.client.post("/calculate/rectification", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        rectification = data["data"]
        self.assertEqual(
            rectification["status"],
            "implemented_layered_rectification_evidence",
        )
        self.assertGreaterEqual(rectification["candidate_count"], 1)
        self.assertIn("candidate_rankings", rectification)

    def test_forecast_layers_returns_technical_bundle_json(self):
        payload = {
            **REFERENCE_PAYLOAD,
            "target_date": "2001-01-02",
            "transit": {
                "start_date": "2001-01-01",
                "end_date": "2001-01-03",
                "timezone_id": "UTC",
                "transit_hour": 12,
            },
        }

        response = self.client.post(
            "/calculate/forecast-layers",
            json=payload,
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        bundle = data["data"]
        self.assertEqual(bundle["target_date"], "2001-01-02")
        self.assertEqual(bundle["transit_period"]["period"]["day_count"], 3)
        self.assertEqual(bundle["lunar_return"]["status"], "available")
        self.assertEqual(bundle["progressions"]["status"], "available")
        self.assertEqual(bundle["solar_arc"]["status"], "available")
        self.assertEqual(bundle["primary_directions"]["status"], "available")


if __name__ == "__main__":
    unittest.main()
