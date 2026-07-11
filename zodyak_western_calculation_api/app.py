"""AGPL Western calculation service shell.

This module intentionally contains only the public technical API boundary.
Private vault writes, interpretation prompts, and customer methodology must stay
outside this service.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from flask import Flask, jsonify, request

from .western_chart import ChartCalculationError, ChartInputError, calculate_core_chart
from .western_transit import (
    TransitCalculationError,
    TransitInputError,
    calculate_transit_period,
)
from .western_solar_return import SolarReturnError, calculate_solar_return
from .western_lunar_return import LunarReturnError, calculate_lunar_return
from .western_primary_directions import (
    PrimaryDirectionsCalculationError,
    PrimaryDirectionsInputError,
    calculate_primary_directions,
)
from .western_progressions import (
    ProgressionsCalculationError,
    ProgressionsInputError,
    calculate_progressions,
)
from .western_solar_arc import (
    SolarArcCalculationError,
    SolarArcInputError,
    calculate_solar_arc,
)
from .western_firdaria import (
    FirdariaCalculationError,
    FirdariaInputError,
    calculate_firdaria,
)
from .western_midpoints import (
    MidpointsCalculationError,
    MidpointsInputError,
    calculate_midpoints,
)
from .western_parans import (
    ParansCalculationError,
    ParansInputError,
    calculate_parans,
)
from .western_synastry import (
    SynastryCalculationError,
    SynastryInputError,
    calculate_synastry,
)
from .western_composite import (
    CompositeCalculationError,
    CompositeInputError,
    calculate_composite,
)
from .western_davison import (
    DavisonCalculationError,
    DavisonInputError,
    calculate_davison,
)
from .western_relocation import (
    RelocationCalculationError,
    RelocationInputError,
    calculate_relocation,
)
from .western_astrocartography import (
    AstrocartographyCalculationError,
    AstrocartographyInputError,
    calculate_astrocartography,
)
from .western_local_space import (
    LocalSpaceCalculationError,
    LocalSpaceInputError,
    calculate_local_space,
)
from .western_horary import (
    HoraryCalculationError,
    HoraryInputError,
    calculate_horary,
)
from .western_electional import (
    ElectionalCalculationError,
    ElectionalInputError,
    calculate_electional,
)
from .western_mundane import (
    MundaneCalculationError,
    MundaneInputError,
    calculate_mundane,
)
from .western_rectification import (
    RectificationCalculationError,
    RectificationInputError,
    calculate_rectification_analysis,
)


ENGINE_NAME = "zodyak-western-calculation-api"
ENGINE_VERSION = "0.1.0"
SERVICE_LICENSE = "AGPL-3.0-only"
EPHEMERIS_NAME = "Swiss Ephemeris"


def source_payload() -> dict[str, Any]:
    source_code_url = os.environ.get("WESTERN_CALC_SOURCE_CODE_URL", "").strip()
    source_commit = os.environ.get("WESTERN_CALC_SOURCE_COMMIT", "").strip()
    release_tag = os.environ.get("WESTERN_CALC_RELEASE_TAG", "").strip()
    source_archive_url = os.environ.get("WESTERN_CALC_SOURCE_ARCHIVE_URL", "").strip()
    build_date = os.environ.get("WESTERN_CALC_BUILD_DATE", "").strip()
    exact_source_configured = bool(source_code_url and (source_commit or release_tag))
    return {
        "source_code_url": source_code_url,
        "source_code_url_configured": bool(source_code_url),
        "source_code_url_env": "WESTERN_CALC_SOURCE_CODE_URL",
        "source_commit": source_commit,
        "source_commit_configured": bool(source_commit),
        "source_commit_env": "WESTERN_CALC_SOURCE_COMMIT",
        "release_tag": release_tag,
        "release_tag_configured": bool(release_tag),
        "release_tag_env": "WESTERN_CALC_RELEASE_TAG",
        "source_archive_url": source_archive_url,
        "source_archive_url_configured": bool(source_archive_url),
        "source_archive_url_env": "WESTERN_CALC_SOURCE_ARCHIVE_URL",
        "build_date": build_date,
        "build_date_configured": bool(build_date),
        "build_date_env": "WESTERN_CALC_BUILD_DATE",
        "exact_source_configured": exact_source_configured,
        "service_license_file": "LICENSE",
        "notice_file": "NOTICE",
        "agpl_network_source_obligation": True,
        "message": (
            "Corresponding source code is tied to the running service version."
            if exact_source_configured
            else (
                "Set WESTERN_CALC_SOURCE_COMMIT or WESTERN_CALC_RELEASE_TAG "
                "to identify the exact corresponding source for this deployment."
            )
            if source_code_url
            else (
                "Set WESTERN_CALC_SOURCE_CODE_URL before public deployment "
                "to the corresponding source code for the running service version."
            )
        ),
    }


def license_payload() -> dict[str, Any]:
    mode = os.environ.get("WESTERN_CALC_EPHEMERIS_LICENSE_MODE", "agpl").strip().lower()
    return {
        "service_license": SERVICE_LICENSE,
        "ephemeris": EPHEMERIS_NAME,
        "ephemeris_license_mode": mode,
        "source": source_payload(),
        "source_boundary": (
            "technical calculation service only; vault, methodology, prompts, "
            "customer records, and interpretation copy are outside this service"
        ),
        "notices": [
            "Swiss Ephemeris is distributed by Astrodienst under AGPL or Professional License.",
            "Public AGPL deployments must provide corresponding source code to network users.",
        ],
    }


def success(data: dict[str, Any], status: int = 200):
    return jsonify(
        {
            "ok": True,
            "engine": ENGINE_NAME,
            "engine_version": ENGINE_VERSION,
            "license": license_payload(),
            "data": data,
        }
    ), status


def error(code: str, message: str, status: int):
    return jsonify(
        {
            "ok": False,
            "engine": ENGINE_NAME,
            "engine_version": ENGINE_VERSION,
            "license": license_payload(),
            "error": {
                "code": code,
                "message": message,
            },
        }
    ), status


def require_json_payload() -> dict[str, Any] | None:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def not_implemented_contract(endpoint: str):
    payload = require_json_payload()
    if payload is None:
        return error("invalid_request", "JSON object body is required.", 400)
    return error(
        "not_implemented",
        (
            f"{endpoint} contract is reserved, but the calculation engine has "
            "not been migrated into the AGPL service yet."
        ),
        501,
    )


def schema_payload() -> dict[str, Any]:
    return {
        "version": "0.1.0",
        "endpoints": [
            {
                "method": "GET",
                "path": "/healthz",
                "status": "available",
                "description": "service health and license metadata",
            },
            {
                "method": "GET",
                "path": "/license",
                "status": "available",
                "description": "AGPL and Swiss Ephemeris license metadata",
            },
            {
                "method": "GET",
                "path": "/source",
                "status": "available",
                "description": "corresponding source code offer for AGPL deployments",
            },
            {
                "method": "GET",
                "path": "/schema",
                "status": "available",
                "description": "machine-readable API contract",
            },
            {
                "method": "POST",
                "path": "/calculate/natal",
                "status": "available",
                "description": "technical natal chart JSON; no vault writes or interpretation",
                "success_data_keys": [
                    "meta",
                    "planets",
                    "houses",
                    "angles",
                    "aspects",
                    "natal_derivatives",
                    "aspect_patterns",
                    "house_system_comparison",
                    "advanced_natal",
                    "package_status",
                    "missing",
                ],
            },
            {
                "method": "POST",
                "path": "/calculate/transits",
                "status": "available",
                "description": "technical transit period JSON",
                "success_data_keys": [
                    "period",
                    "daily",
                    "exact_aspects",
                    "active_patterns",
                    "meta",
                ],
            },
            {
                "method": "POST",
                "path": "/calculate/forecast-layers",
                "status": "available",
                "description": "technical forecast layer bundle JSON",
                "success_data_keys": [
                    "transit_period",
                    "lunar_return",
                    "progressions",
                    "solar_arc",
                    "primary_directions",
                ],
            },
            {
                "method": "POST",
                "path": "/calculate/solar-return",
                "status": "available",
                "description": "technical solar return JSON",
                "success_data_keys": ["status", "return_year", "sr_chart"],
            },
            {
                "method": "POST",
                "path": "/calculate/lunar-return",
                "status": "available",
                "description": "technical lunar return JSON",
                "success_data_keys": ["status", "return_date_requested", "lr_chart"],
            },
            {
                "method": "POST",
                "path": "/calculate/progressions",
                "status": "available",
                "description": "technical secondary progressions JSON",
                "success_data_keys": ["status", "target_date", "progressed_chart"],
            },
            {
                "method": "POST",
                "path": "/calculate/solar-arc",
                "status": "available",
                "description": "technical solar arc directions JSON",
                "success_data_keys": ["status", "target_date", "solar_arc_chart"],
            },
            {
                "method": "POST",
                "path": "/calculate/primary-directions",
                "status": "available",
                "description": "technical primary directions JSON",
                "success_data_keys": ["status", "target_date", "directions"],
            },
            {
                "method": "POST",
                "path": "/calculate/firdaria",
                "status": "available",
                "description": "technical Firdaria time-lord JSON",
                "success_data_keys": ["status", "target_date", "current_major"],
            },
            {
                "method": "POST",
                "path": "/calculate/midpoints",
                "status": "available",
                "description": "technical midpoint and 45-degree dial JSON",
                "success_data_keys": ["status", "midpoints", "dial_45"],
            },
            {
                "method": "POST",
                "path": "/calculate/parans",
                "status": "available",
                "description": "technical parans JSON",
                "success_data_keys": ["status", "parans", "stars_skipped"],
            },
            {
                "method": "POST",
                "path": "/calculate/synastry",
                "status": "available",
                "description": "technical synastry JSON",
                "success_data_keys": ["status", "interaspects", "house_overlay"],
            },
            {
                "method": "POST",
                "path": "/calculate/composite",
                "status": "available",
                "description": "technical midpoint composite JSON",
                "success_data_keys": ["status", "points", "angles"],
            },
            {
                "method": "POST",
                "path": "/calculate/davison",
                "status": "available",
                "description": "technical Davison relationship chart JSON",
                "success_data_keys": ["status", "davison_chart", "davison_moment"],
            },
            {
                "method": "POST",
                "path": "/calculate/relocation",
                "status": "available",
                "description": "technical relocation chart JSON",
                "success_data_keys": ["status", "relocated_chart", "angle_comparison"],
            },
            {
                "method": "POST",
                "path": "/calculate/astrocartography",
                "status": "available",
                "description": "technical astrocartography lines JSON",
                "success_data_keys": ["status", "lines", "interest_analysis"],
            },
            {
                "method": "POST",
                "path": "/calculate/local-space",
                "status": "available",
                "description": "technical local space azimuth JSON",
                "success_data_keys": ["status", "items", "skipped"],
            },
            {
                "method": "POST",
                "path": "/calculate/horary",
                "status": "available",
                "description": "technical horary chart JSON",
                "success_data_keys": ["status", "full_chart", "significators"],
            },
            {
                "method": "POST",
                "path": "/calculate/electional",
                "status": "available",
                "description": "technical electional candidate scan JSON",
                "success_data_keys": ["status", "window", "top_candidates"],
            },
            {
                "method": "POST",
                "path": "/calculate/mundane",
                "status": "available",
                "description": "technical mundane event chart JSON",
                "success_data_keys": ["status", "events", "event_type"],
            },
            {
                "method": "POST",
                "path": "/calculate/rectification",
                "status": "available",
                "description": "technical birth-time rectification candidate evidence JSON",
                "success_data_keys": [
                    "status",
                    "candidate_rankings",
                    "top_candidates",
                    "candidate_windows",
                ],
            },
        ],
        "closed_system_exclusions": [
            "vault writes",
            "customer files",
            "methodology notes",
            "GPT prompts",
            "interpretation copy",
            "commercial packaging",
        ],
    }


def forecast_target_date(payload: dict[str, Any]) -> str:
    forecast = payload.get("forecast") or {}
    transit = payload.get("transit") or {}
    for value in (
        payload.get("target_date"),
        forecast.get("target_date") if isinstance(forecast, dict) else None,
        transit.get("start_date") if isinstance(transit, dict) else None,
    ):
        if value:
            return str(value)
    return date.today().isoformat()


def payload_with_layer_defaults(payload: dict[str, Any], target_date: str) -> dict[str, Any]:
    lunar_return = payload.get("lunar_return") or {}
    progressions = payload.get("progressions") or {}
    solar_arc = payload.get("solar_arc") or {}
    primary_directions = payload.get("primary_directions") or {}
    return {
        **payload,
        "return_date": payload.get("return_date") or lunar_return.get("return_date") or target_date,
        "progressions": {
            **(progressions if isinstance(progressions, dict) else {}),
            "target_date": (
                progressions.get("target_date")
                if isinstance(progressions, dict)
                else None
            )
            or target_date,
        },
        "solar_arc": {
            **(solar_arc if isinstance(solar_arc, dict) else {}),
            "target_date": (
                solar_arc.get("target_date")
                if isinstance(solar_arc, dict)
                else None
            )
            or target_date,
        },
        "primary_directions": {
            **(primary_directions if isinstance(primary_directions, dict) else {}),
            "target_date": (
                primary_directions.get("target_date")
                if isinstance(primary_directions, dict)
                else None
            )
            or target_date,
        },
    }


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/healthz")
    def healthz():
        return success({"status": "healthy"})

    @app.get("/license")
    def license_status():
        return success({"license": license_payload()})

    @app.get("/source")
    def source_status():
        return success({"source": source_payload()})

    @app.get("/schema")
    def schema_status():
        return success({"schema": schema_payload()})

    @app.post("/calculate/natal")
    def calculate_natal():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            chart = calculate_core_chart(payload)
        except ChartInputError as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        return success(chart)

    @app.post("/calculate/transits")
    def calculate_transits():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            chart = calculate_core_chart(payload)
            transit = calculate_transit_period(payload, chart)
        except (ChartInputError, TransitInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except TransitCalculationError as exc:
            return error("transit_calculation_error", str(exc), 500)
        return success(transit)

    @app.post("/calculate/solar-return")
    def calculate_solar_return_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            solar_return = calculate_solar_return(payload)
        except (ChartInputError, SolarReturnError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        return success(solar_return)

    @app.post("/calculate/lunar-return")
    def calculate_lunar_return_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            chart = calculate_core_chart(payload)
            lunar_return = calculate_lunar_return(payload, chart)
        except (ChartInputError, LunarReturnError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        return success(lunar_return)

    @app.post("/calculate/progressions")
    def calculate_progressions_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            chart = calculate_core_chart(payload)
            progressions = calculate_progressions(payload, chart)
        except (ChartInputError, ProgressionsInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except ProgressionsCalculationError as exc:
            return error("progressions_calculation_error", str(exc), 500)
        return success(progressions)

    @app.post("/calculate/solar-arc")
    def calculate_solar_arc_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            chart = calculate_core_chart(payload)
            solar_arc = calculate_solar_arc(payload, chart)
        except (ChartInputError, SolarArcInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except SolarArcCalculationError as exc:
            return error("solar_arc_calculation_error", str(exc), 500)
        return success(solar_arc)

    @app.post("/calculate/primary-directions")
    def calculate_primary_directions_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            chart = calculate_core_chart(payload)
            primary_directions = calculate_primary_directions(payload, chart)
        except (ChartInputError, PrimaryDirectionsInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except PrimaryDirectionsCalculationError as exc:
            return error("primary_directions_calculation_error", str(exc), 500)
        return success(primary_directions)

    @app.post("/calculate/firdaria")
    def calculate_firdaria_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            chart = calculate_core_chart(payload)
            firdaria = calculate_firdaria(payload, chart)
        except (ChartInputError, FirdariaInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except FirdariaCalculationError as exc:
            return error("firdaria_calculation_error", str(exc), 500)
        return success(firdaria)

    @app.post("/calculate/midpoints")
    def calculate_midpoints_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            chart = calculate_core_chart(payload)
            midpoints = calculate_midpoints(payload, chart)
        except (ChartInputError, MidpointsInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except MidpointsCalculationError as exc:
            return error("midpoints_calculation_error", str(exc), 500)
        return success(midpoints)

    @app.post("/calculate/parans")
    def calculate_parans_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            chart = calculate_core_chart(payload)
            parans = calculate_parans(payload, chart)
        except (ChartInputError, ParansInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except ParansCalculationError as exc:
            return error("parans_calculation_error", str(exc), 500)
        return success(parans)

    @app.post("/calculate/synastry")
    def calculate_synastry_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            synastry = calculate_synastry(payload)
        except (ChartInputError, SynastryInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except SynastryCalculationError as exc:
            return error("synastry_calculation_error", str(exc), 500)
        return success(synastry)

    @app.post("/calculate/composite")
    def calculate_composite_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            composite = calculate_composite(payload)
        except (ChartInputError, CompositeInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except CompositeCalculationError as exc:
            return error("composite_calculation_error", str(exc), 500)
        return success(composite)

    @app.post("/calculate/davison")
    def calculate_davison_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            davison = calculate_davison(payload)
        except (ChartInputError, DavisonInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except DavisonCalculationError as exc:
            return error("davison_calculation_error", str(exc), 500)
        return success(davison)

    @app.post("/calculate/relocation")
    def calculate_relocation_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            relocation = calculate_relocation(payload)
        except (ChartInputError, RelocationInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except RelocationCalculationError as exc:
            return error("relocation_calculation_error", str(exc), 500)
        return success(relocation)

    @app.post("/calculate/astrocartography")
    def calculate_astrocartography_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            astrocartography = calculate_astrocartography(payload)
        except (ChartInputError, AstrocartographyInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except AstrocartographyCalculationError as exc:
            return error("astrocartography_calculation_error", str(exc), 500)
        return success(astrocartography)

    @app.post("/calculate/local-space")
    def calculate_local_space_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            local_space = calculate_local_space(payload)
        except (ChartInputError, LocalSpaceInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except LocalSpaceCalculationError as exc:
            return error("local_space_calculation_error", str(exc), 500)
        return success(local_space)

    @app.post("/calculate/horary")
    def calculate_horary_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            horary = calculate_horary(payload)
        except (ChartInputError, HoraryInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except HoraryCalculationError as exc:
            return error("horary_calculation_error", str(exc), 500)
        return success(horary)

    @app.post("/calculate/electional")
    def calculate_electional_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            electional = calculate_electional(payload)
        except (ChartInputError, ElectionalInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except ElectionalCalculationError as exc:
            return error("electional_calculation_error", str(exc), 500)
        return success(electional)

    @app.post("/calculate/mundane")
    def calculate_mundane_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            mundane = calculate_mundane(payload)
        except (ChartInputError, MundaneInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except MundaneCalculationError as exc:
            return error("mundane_calculation_error", str(exc), 500)
        return success(mundane)

    @app.post("/calculate/rectification")
    def calculate_rectification_endpoint():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        try:
            analysis = calculate_rectification_analysis(payload)
        except (ChartInputError, RectificationInputError) as exc:
            return error("invalid_request", str(exc), 400)
        except (ChartCalculationError, RectificationCalculationError) as exc:
            code = getattr(exc, "code", "rectification_calculation_error")
            return error(code, str(exc), 422)
        return success(analysis)

    @app.post("/calculate/forecast-layers")
    def calculate_forecast_layers():
        payload = require_json_payload()
        if payload is None:
            return error("invalid_request", "JSON object body is required.", 400)
        target_date = forecast_target_date(payload)
        layer_payload = payload_with_layer_defaults(payload, target_date)
        try:
            chart = calculate_core_chart(layer_payload)
            transit_period = calculate_transit_period(layer_payload, chart)
            lunar_return = calculate_lunar_return(layer_payload, chart)
            progressions = calculate_progressions(layer_payload, chart)
            solar_arc = calculate_solar_arc(layer_payload, chart)
            primary_directions = calculate_primary_directions(layer_payload, chart)
        except (
            ChartInputError,
            TransitInputError,
            LunarReturnError,
            ProgressionsInputError,
            SolarArcInputError,
            PrimaryDirectionsInputError,
        ) as exc:
            return error("invalid_request", str(exc), 400)
        except ChartCalculationError as exc:
            return error("chart_calculation_error", str(exc), 422)
        except TransitCalculationError as exc:
            return error("transit_calculation_error", str(exc), 500)
        except ProgressionsCalculationError as exc:
            return error("progressions_calculation_error", str(exc), 500)
        except SolarArcCalculationError as exc:
            return error("solar_arc_calculation_error", str(exc), 500)
        except PrimaryDirectionsCalculationError as exc:
            return error("primary_directions_calculation_error", str(exc), 500)
        return success(
            {
                "target_date": target_date,
                "transit_period": transit_period,
                "lunar_return": lunar_return,
                "progressions": progressions,
                "solar_arc": solar_arc,
                "primary_directions": primary_directions,
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("WESTERN_CALC_HOST", "127.0.0.1"),
        port=int(os.environ.get("WESTERN_CALC_PORT", "5010")),
        debug=os.environ.get("WESTERN_CALC_DEBUG", "").strip().lower()
        in {"1", "true", "yes"},
    )
