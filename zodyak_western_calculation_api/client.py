"""Small client for closed-app integration tests and future callers."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CalculationApiClientError(RuntimeError):
    """Raised when the calculation service cannot be reached or returns error."""


class CalculationApiClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                data = json.loads(exc.read().decode("utf-8"))
            except Exception as parse_exc:
                raise CalculationApiClientError(str(exc)) from parse_exc
            message = (data.get("error") or {}).get("message") or str(exc)
            raise CalculationApiClientError(message) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise CalculationApiClientError(str(exc)) from exc

        if not data.get("ok"):
            message = (data.get("error") or {}).get("message") or "calculation failed"
            raise CalculationApiClientError(message)
        return data["data"]

    def calculate_natal(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/natal", payload)

    def calculate_transits(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/transits", payload)

    def calculate_solar_return(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/solar-return", payload)

    def calculate_lunar_return(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/lunar-return", payload)

    def calculate_progressions(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/progressions", payload)

    def calculate_solar_arc(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/solar-arc", payload)

    def calculate_primary_directions(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/primary-directions", payload)

    def calculate_firdaria(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/firdaria", payload)

    def calculate_midpoints(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/midpoints", payload)

    def calculate_parans(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/parans", payload)

    def calculate_synastry(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/synastry", payload)

    def calculate_composite(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/composite", payload)

    def calculate_davison(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/davison", payload)

    def calculate_relocation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/relocation", payload)

    def calculate_astrocartography(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/astrocartography", payload)

    def calculate_local_space(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/local-space", payload)

    def calculate_horary(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/horary", payload)

    def calculate_electional(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/electional", payload)

    def calculate_mundane(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/mundane", payload)

    def calculate_rectification(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/rectification", payload)

    def calculate_forecast_layers(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/calculate/forecast-layers", payload)
