"""Public deployment readiness checks for the AGPL calculation service."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .app import schema_payload, source_payload


PACKAGE_DIR = Path(__file__).resolve().parent
FORBIDDEN_IMPORT_MARKERS = (
    "from " + "western_",
    "import " + "western_",
)
FORBIDDEN_PRIVATE_MARKERS = (
    "/Documents/" + "batı astrolojisi/",
    "/Documents/" + "progresifastrolog/",
    "Astro" + "GPT",
    "Obs" + "idian",
)


def _scan_package_files() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        relative_path = str(path.relative_to(PACKAGE_DIR))
        for marker in FORBIDDEN_IMPORT_MARKERS:
            if marker in text:
                findings.append(
                    {
                        "code": "closed_app_import_marker",
                        "file": relative_path,
                        "marker": marker,
                    }
                )
        for marker in FORBIDDEN_PRIVATE_MARKERS:
            if marker in text:
                findings.append(
                    {
                        "code": "private_workspace_marker",
                        "file": relative_path,
                        "marker": marker,
                    }
                )
    return findings


def check_public_readiness(require_source_url: bool = False) -> dict[str, Any]:
    source = source_payload()
    schema = schema_payload()
    endpoints = schema.get("endpoints", [])
    unavailable = [
        endpoint
        for endpoint in endpoints
        if endpoint.get("status") != "available"
    ]
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if require_source_url and not source.get("source_code_url_configured"):
        failures.append(
            {
                "code": "missing_source_url",
                "message": (
                    "WESTERN_CALC_SOURCE_CODE_URL must point to the public "
                    "corresponding source for the exact deployed version."
                ),
            }
        )
    elif not source.get("source_code_url_configured"):
        warnings.append(
            {
                "code": "source_url_not_configured",
                "message": (
                    "Set WESTERN_CALC_SOURCE_CODE_URL before public deployment."
                ),
            }
        )

    for endpoint in unavailable:
        failures.append(
            {
                "code": "unavailable_endpoint",
                "path": endpoint.get("path"),
                "status": endpoint.get("status"),
            }
        )

    failures.extend(_scan_package_files())

    return {
        "ok": not failures,
        "source": source,
        "endpoint_count": len(endpoints),
        "failures": failures,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check whether the AGPL calculation service is ready for public deployment."
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="Require WESTERN_CALC_SOURCE_CODE_URL to be configured.",
    )
    args = parser.parse_args(argv)

    result = check_public_readiness(require_source_url=args.public)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
