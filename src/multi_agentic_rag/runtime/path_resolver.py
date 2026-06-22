"""Document path and ingestion-batch resolution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multi_agentic_rag.common_defs import SUPPORTED_DOCUMENT_SUFFIXES
from multi_agentic_rag.exceptions import ConfigError

DOCUMENT_TYPE_TOKENS = {"BRD", "SRS", "FRD", "PRD", "REQ", "SPEC"}
VERSION_RE = re.compile(r"^v\d+(?:[._-]\d+)?$", re.IGNORECASE)


@dataclass(frozen=True)
class BatchDocumentInput:
    """One resolved document ingestion item."""

    path: Path
    system: str
    version: str
    kb: str = "default"


def resolve_ingestion_inputs(
    input_path: Path,
    *,
    system: str | None = None,
    version: str | None = None,
    kb: str = "default",
    manifest_path: Path | None = None,
    recursive: bool = True,
    atomic_batch: bool = False,
    supported_suffixes: tuple[str, ...] = SUPPORTED_DOCUMENT_SUFFIXES,
) -> list[BatchDocumentInput]:
    """Resolve a file or directory into deterministic document ingestion items."""

    root = input_path.expanduser().resolve()
    if manifest_path is not None:
        return _resolve_manifest(root, manifest_path.expanduser().resolve(), kb=kb)
    if root.is_file():
        return [_resolve_file(root, system=system, version=version, kb=kb)]
    if not root.is_dir():
        raise ConfigError(f"Document path does not exist: {root}")

    pattern = "**/*" if recursive else "*"
    files = sorted(
        path.resolve()
        for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() in supported_suffixes
    )
    if not files:
        raise ConfigError(f"No supported documents found under {root}.")
    resolved = [_resolve_file(path, system=system, version=version, kb=kb) for path in files]
    systems = {item.system for item in resolved}
    versions = {item.version for item in resolved}
    if len(systems) > 1 or len(versions) > 1:
        raise ConfigError(
            "Directory ingestion resolved mixed systems or versions. "
            "Provide an ingestion manifest to disambiguate."
        )
    if atomic_batch:
        # Metadata validation has already happened for every file before persistence starts.
        return resolved
    return resolved


def _resolve_manifest(root: Path, manifest_path: Path, *, kb: str) -> list[BatchDocumentInput]:
    if not manifest_path.exists():
        raise ConfigError(f"Ingestion manifest does not exist: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid ingestion manifest JSON: {manifest_path}") from exc
    documents = payload.get("documents") if isinstance(payload, dict) else None
    if not isinstance(documents, list) or not documents:
        raise ConfigError("Ingestion manifest must contain a non-empty documents array.")
    items: list[BatchDocumentInput] = []
    for raw in documents:
        if not isinstance(raw, dict):
            raise ConfigError("Each ingestion manifest document must be an object.")
        path_value = raw.get("path")
        if not path_value:
            raise ConfigError("Each ingestion manifest document requires path.")
        path = Path(str(path_value))
        if not path.is_absolute():
            path = root / path
        items.append(
            _resolve_file(
                path.resolve(),
                system=_required_manifest_value(raw, "system"),
                version=_required_manifest_value(raw, "version"),
                kb=str(raw.get("kb") or kb),
            )
        )
    return items


def _resolve_file(
    path: Path,
    *,
    system: str | None,
    version: str | None,
    kb: str,
) -> BatchDocumentInput:
    if not path.exists() or not path.is_file():
        raise ConfigError(f"Document file does not exist: {path}")
    if path.suffix.lower() not in SUPPORTED_DOCUMENT_SUFFIXES:
        raise ConfigError(f"Unsupported document extension: {path.suffix}")
    inferred = infer_metadata_from_filename(path)
    inferred_system = inferred.get("system")
    inferred_version = inferred.get("version")
    if system and inferred_system and system != inferred_system:
        raise ConfigError(
            f"System conflict for {path.name}: CLI/config={system}, filename={inferred_system}."
        )
    if version and inferred_version and version.lower() != inferred_version.lower():
        raise ConfigError(
            f"Version conflict for {path.name}: CLI/config={version}, filename={inferred_version}."
        )
    resolved_system = system or inferred_system
    resolved_version = version or inferred_version
    if not resolved_system:
        raise ConfigError(f"System is required for {path.name}.")
    if not resolved_version:
        raise ConfigError(f"Version is required for {path.name}.")
    return BatchDocumentInput(path=path, system=resolved_system, version=resolved_version, kb=kb)


def infer_metadata_from_filename(path: Path) -> dict[str, str]:
    """Infer PROJECT_1 and v1 from names such as PROJECT_1_BRD_v1.pdf."""

    tokens = re.split(r"[_\s-]+", path.stem)
    version_index = next(
        (index for index, token in enumerate(tokens) if VERSION_RE.match(token)),
        None,
    )
    if version_index is None:
        return {}
    system_tokens = tokens[:version_index]
    if system_tokens and system_tokens[-1].upper() in DOCUMENT_TYPE_TOKENS:
        system_tokens = system_tokens[:-1]
    if not system_tokens:
        return {"version": tokens[version_index]}
    return {
        "system": "_".join(system_tokens),
        "version": tokens[version_index],
    }


def _required_manifest_value(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not value:
        raise ConfigError(f"Each ingestion manifest document requires {key}.")
    return str(value)
