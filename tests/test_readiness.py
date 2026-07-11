import unittest
from unittest.mock import patch

from zodyak_western_calculation_api.readiness import check_public_readiness


class ReadinessCheckTest(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_readiness_warns_without_source_url_in_local_mode(self):
        result = check_public_readiness(require_source_url=False)

        self.assertTrue(result["ok"])
        self.assertEqual(result["endpoint_count"], 25)
        self.assertEqual(result["warnings"][0]["code"], "source_url_not_configured")
        self.assertEqual(result["failures"], [])

    @patch.dict("os.environ", {}, clear=True)
    def test_public_readiness_requires_source_url(self):
        result = check_public_readiness(require_source_url=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["code"], "missing_source_url")

    @patch.dict(
        "os.environ",
        {
            "WESTERN_CALC_SOURCE_CODE_URL": (
                "https://github.com/progresifastroloji/zodyak-western-calculation-api"
            )
        },
        clear=True,
    )
    def test_public_readiness_requires_exact_source_version(self):
        result = check_public_readiness(require_source_url=True)

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["failures"][0]["code"],
            "missing_exact_source_version",
        )


if __name__ == "__main__":
    unittest.main()
