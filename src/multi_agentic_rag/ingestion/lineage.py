"""Document lineage helpers."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from multi_agentic_rag.domain import DocumentRecord, DocumentStatus, DocumentVersionRecord
from multi_agentic_rag.exceptions import IngestionError
from multi_agentic_rag.utils.hashing import stable_id


def validate_source_version(source: Path, version: str) -> None:
    """Reject source/version mismatches when a filename contains a vN token.

    Args:
        source: Source document path.
        version: Version label supplied by the caller.

    Raises:
        IngestionError: If the filename suggests a different version.
    """

    source_version = _source_version_label(source.name)
    if not source_version:
        return
    if _normalize_version_label(source_version) != _normalize_version_label(version):
        raise IngestionError(
            f"Source filename suggests version {source_version}, but --version was {version}."
        )


def version_is_newer(candidate: str, current: str) -> bool:
    """Return whether candidate sorts after current using natural version numbers.

    Args:
        candidate: Proposed new version label.
        current: Existing active version label.

    Returns:
        `True` when candidate is newer than current.
    """

    return _version_sort_key(candidate) > _version_sort_key(current)


def coerce_ingestion_version(
    requested_version: str,
    previous_version: str | None,
) -> tuple[str, str | None]:
    """Return the effective version and warning for missing predecessor versions.

    A request for ``v2`` with no active ``v1`` is treated as ``v1``. A request
    for ``v7`` when ``v6`` is not active is treated as ``v6``. Non-numeric
    versions keep the requested label.

    Args:
        requested_version: Version label supplied by the user.
        previous_version: Currently active version label, if one exists.

    Returns:
        Tuple of effective version and optional warning message.
    """

    requested_number = _version_number(requested_version)
    if requested_number is None or requested_number <= 1:
        return requested_version, None
    expected_previous_number = requested_number - 1
    previous_number = _version_number(previous_version) if previous_version else None
    if previous_number is not None and requested_number <= previous_number:
        return requested_version, None
    if previous_number == expected_previous_number:
        return requested_version, None
    fallback_version = f"v{expected_previous_number}"
    missing = f"v{expected_previous_number}"
    if previous_version:
        warning = (
            f"Requested {requested_version}, but {missing} is not active "
            f"(current active version is {previous_version}); treating this ingest as "
            f"{fallback_version}."
        )
    else:
        warning = (
            f"Requested {requested_version}, but {missing} is not available; "
            f"treating this ingest as {fallback_version}."
        )
    return fallback_version, warning


def infer_document_type(source: Path, sample_text: str = "") -> str:
    """Infer SRS/BRD as metadata, not as a parser choice.

    Args:
        source: Source document path.
        sample_text: Optional extracted text used to identify BRD/SRS content.

    Returns:
        Inferred metadata label.
    """

    haystack = f"{source.stem} {sample_text[:1000]}".lower()
    if "srs" in haystack or "software requirement" in haystack:
        return "srs"
    if "brd" in haystack or "business requirement" in haystack:
        return "brd"
    return source.suffix.lower().lstrip(".") or "document"


def copy_managed_source(
    source: Path,
    *,
    documents_dir: Path,
    system_name: str,
    kb_name: str,
    version: str,
    content_hash: str,
) -> Path:
    """Copy a source document into the managed runtime directory.

    Args:
        source: Original source file.
        documents_dir: Root managed-document directory.
        system_name: Owning system namespace.
        kb_name: Knowledge-base context.
        version: Version label.
        content_hash: SHA-256 digest used in the managed filename.

    Returns:
        Path to the copied managed source file.
    """

    target_dir = documents_dir / _safe_name(system_name) / _safe_name(kb_name) / _safe_name(version)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{content_hash[:16]}_{source.name}"
    shutil.copy2(source, target)
    return target


def create_document_records(
    *,
    source: Path,
    managed_source: Path,
    system_name: str,
    kb_name: str,
    version: str,
    content_hash: str,
    document_type: str,
    previous_version_id: str | None,
) -> tuple[DocumentRecord, DocumentVersionRecord]:
    """Create deterministic document and version records.

    Args:
        source: Original source path.
        managed_source: Managed source copy path.
        system_name: Owning system namespace.
        kb_name: Knowledge-base context.
        version: Version label.
        content_hash: SHA-256 digest of source content.
        document_type: Inferred document type metadata.
        previous_version_id: Previous version superseded by this version, if any.

    Returns:
        Stable document record and version-specific document record.
    """

    document_id = stable_id("document", system_name, kb_name, source.name)
    document_version_id = stable_id("document_version", document_id, version, content_hash)
    document = DocumentRecord(
        document_id=document_id,
        system_name=system_name,
        kb_name=kb_name,
        source_name=source.name,
        document_type=document_type,
        metadata={"source_suffix": source.suffix.lower()},
    )
    document_version = DocumentVersionRecord(
        document_version_id=document_version_id,
        document_id=document_id,
        system_name=system_name,
        kb_name=kb_name,
        version=version,
        status=DocumentStatus.ACTIVE,
        source_path=str(managed_source),
        source_name=source.name,
        content_hash=content_hash,
        supersedes_version_id=previous_version_id,
        metadata={"document_type": document_type},
    )
    return document, document_version


def _version_sort_key(version: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", version)
    if numbers:
        return tuple(int(number) for number in numbers)
    return tuple(ord(character) for character in version.lower())


def _version_number(version: str | None) -> int | None:
    if not version:
        return None
    numbers = re.findall(r"\d+", version)
    if len(numbers) != 1:
        return None
    return int(numbers[0])


def _source_version_label(source_name: str) -> str | None:
    match = re.search(r"(?:^|[^a-z0-9])v(?P<number>\d+)(?:[^a-z0-9]|$)", source_name, re.I)
    return f"v{match.group('number')}" if match else None


def _normalize_version_label(version: str) -> str:
    numbers = re.findall(r"\d+", version)
    if numbers:
        return f"v{'.'.join(numbers)}"
    return version.lower()


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "default"
