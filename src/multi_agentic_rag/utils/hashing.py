"""Compatibility re-export for canonical identity helpers."""

from __future__ import annotations

from multi_agentic_rag.identity import sha256_file, sha256_text, stable_hash, stable_id

__all__ = ["sha256_file", "sha256_text", "stable_hash", "stable_id"]
