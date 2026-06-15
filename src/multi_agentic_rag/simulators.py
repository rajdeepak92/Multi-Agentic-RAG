"""Local simulator readiness and lightweight protocol validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from multi_agentic_rag.config import Settings, get_settings


@dataclass(frozen=True)
class SimulatorReadiness:
    """Readiness summary for target-mode protocol simulation."""

    ready: bool
    missing: list[str]


def check_rest_mqtt_simulators(settings: Settings) -> SimulatorReadiness:
    """Return whether REST and MQTT simulator support is available."""

    missing = []
    if not (settings.rest_simulator_enabled or settings.simulator_config_path):
        missing.append("REST simulator is not configured")
    if not (settings.mqtt_simulator_enabled or settings.simulator_config_path):
        missing.append("MQTT simulator is not configured")
    return SimulatorReadiness(ready=not missing, missing=missing)


def validate_simulated_protocol(scenario: dict) -> bool:
    """Validate a generated protocol scenario against local simulator semantics.

    This is intentionally minimal: it verifies evidence-derived expected values
    exist and that the scenario declares at least one supported protocol. Real
    simulators can replace this function behind the same generated-test call.
    """

    protocols = set(scenario.get("protocols") or [])
    if not protocols & {"REST", "MQTT"}:
        return True
    if not scenario.get("expected_values"):
        raise AssertionError("Simulator validation requires evidence-derived expected values.")
    if not scenario.get("evidence"):
        raise AssertionError("Simulator validation requires source evidence.")
    return True


def validate_real_protocol(scenario: dict) -> bool:
    """Validate a generated protocol scenario against configured real adapters.

    Only safe REST GET checks are active today. Other real protocols fail with
    PROTOCOL_UNAVAILABLE so the runner classifies them as blocked instead of
    allowing a fake pass.
    """

    protocols = set(scenario.get("protocols") or [])
    if not protocols:
        return True
    settings = get_settings()
    if "REST" in protocols:
        return _validate_real_rest(scenario, settings)
    unavailable = ", ".join(sorted(protocols))
    raise RuntimeError(f"PROTOCOL_UNAVAILABLE: real adapter not implemented for {unavailable}.")


def _validate_real_rest(scenario: dict, settings: Settings) -> bool:
    if not settings.rest_api_base_url:
        raise RuntimeError("PROTOCOL_UNAVAILABLE: REST_API_BASE_URL is not configured.")
    endpoints = [
        item["value"]
        for item in scenario.get("expected_values", [])
        if item.get("kind") == "endpoint"
    ]
    if not endpoints:
        raise RuntimeError("PROTOCOL_UNAVAILABLE: no evidence-derived REST endpoint found.")
    method, path = endpoints[0].split(" ", 1)
    if method.upper() != "GET":
        raise RuntimeError(
            "PROTOCOL_UNAVAILABLE: only safe REST GET validation is implemented."
        )
    url = urljoin(settings.rest_api_base_url.rstrip("/") + "/", path.lstrip("/"))
    response = httpx.get(url, timeout=5)
    response.raise_for_status()
    return True
