"""Shared compute-device resolution for local model providers."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Literal

from multi_agentic_rag.exceptions import ConfigError

DevicePreference = Literal["cpu", "cuda", "auto"]


@dataclass(frozen=True)
class DeviceResolution:
    """Resolved device plus the reason used for diagnostics."""

    requested: str
    resolved: str
    cuda_available: bool | None
    reason: str


def resolve_device(requested: str, *, purpose: str = "local model") -> DeviceResolution:
    """Resolve ``cpu``, ``cuda``, or ``auto`` without importing heavyweight models.

    ``auto`` intentionally chooses CUDA only when ``torch.cuda.is_available()`` is
    true. Otherwise it resolves to CPU, which keeps clean Windows CPU installs from
    requiring ``accelerate`` merely because a config used ``auto``.
    """

    normalized = requested.strip().lower()
    if normalized not in {"cpu", "cuda", "auto"}:
        raise ConfigError(
            f"Unsupported device for {purpose}: {requested}. Use cpu, cuda, or auto."
        )
    cuda_available = _cuda_available()
    if normalized == "cpu":
        return DeviceResolution(
            requested=requested,
            resolved="cpu",
            cuda_available=cuda_available,
            reason=f"{purpose} device pinned to CPU.",
        )
    if normalized == "cuda":
        if cuda_available is not True:
            raise ConfigError(
                f"{purpose} requested CUDA, but torch.cuda.is_available() is not true. "
                "Use device=cpu or install a CUDA-enabled PyTorch build."
            )
        return DeviceResolution(
            requested=requested,
            resolved="cuda",
            cuda_available=True,
            reason=f"{purpose} device pinned to CUDA.",
        )
    resolved = "cuda" if cuda_available is True else "cpu"
    return DeviceResolution(
        requested=requested,
        resolved=resolved,
        cuda_available=cuda_available,
        reason=f"{purpose} device auto-selected {resolved}.",
    )


def _cuda_available() -> bool | None:
    try:
        torch = import_module("torch")
    except ModuleNotFoundError:
        return False
    except Exception:
        return None
    cuda = getattr(torch, "cuda", None)
    if cuda is None or not hasattr(cuda, "is_available"):
        return False
    try:
        return bool(cuda.is_available())
    except Exception:
        return None
