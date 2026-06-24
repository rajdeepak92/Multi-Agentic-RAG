"""Generated artifact writers."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import yaml

from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import ArtifactManifest, EvidenceBundle, GeneratedUserStory
from multi_agentic_rag.utils.hashing import stable_hash, stable_id


class UserStoryArtifactWriter:
    """Write user-story YAML files and debug traces."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def write(
        self,
        story: GeneratedUserStory,
        *,
        system_name: str,
        kb_name: str,
        version: str,
        evidence: EvidenceBundle,
        model: str,
        prompt_version: str,
        validation_status: str,
        validation_messages: list[str],
    ) -> ArtifactManifest:
        """Write one user story and its debug JSON trace."""

        story_id = _safe_story_id(story.id)
        if self.settings.run_results_dir is not None:
            story_dir = self.settings.run_results_dir / "artifacts" / "user_stories"
            debug_dir = self.settings.run_results_dir / "debug"
            legacy_root = self.settings.user_story_output_dir / system_name / kb_name / version
        else:
            root = self.settings.user_story_output_dir / system_name / kb_name / version
            story_dir = root / "user_stories"
            debug_dir = root / "debug"
            legacy_root = root
        story_dir.mkdir(parents=True, exist_ok=True)
        debug_dir.mkdir(parents=True, exist_ok=True)
        yaml_path = story_dir / f"{story_id}.yaml"
        json_path = story_dir / f"{story_id}.json"
        debug_path = debug_dir / f"{story_id}.json"
        trace_path = debug_dir / f"{story_id}.trace.json"
        story_payload = story.model_dump(mode="json")
        yaml_path.write_text(
            yaml.safe_dump(story_payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        production_json_payload = {
            "schema_version": self.settings.user_story_schema_version,
            "story": story_payload,
            "traceability": {
                "system": system_name,
                "knowledge_base": kb_name,
                "version": version,
                "requirement_ids": story.traceability.get("requirement_ids", []),
                "fact_ids": story.traceability.get("fact_ids", []),
                "chunk_ids": story.traceability.get("chunk_ids", evidence.source_chunk_ids),
                "source_documents": story.traceability.get("source_documents", []),
                "source_pages": story.traceability.get("source_pages", []),
                "evidence_paths": story.traceability.get("evidence_paths", []),
            },
            "generation": {
                "run_id": self.settings.active_run_id,
                "provider": self.settings.reasoning_provider,
                "deployment": model,
                "prompt_version": prompt_version,
                "generation_mode": "structured",
            },
            "retrieval": {
                "query": evidence.query,
                "selected_evidence_ids": evidence.source_chunk_ids,
                "graph_paths": evidence.graph_paths,
                "ranked_results": [
                    {
                        "chunk_id": result.chunk_id,
                        "rank": result.rank,
                        "score": result.score,
                        "sources": result.sources,
                        "source_document": result.source_name,
                        "page": result.page,
                        "version": result.version,
                    }
                    for result in evidence.ranked_results
                ],
            },
            "validation": {
                "status": validation_status,
                "messages": validation_messages,
            },
            "publication": {
                "publication_allowed": validation_status == "passed",
                "artifact_status": "published" if validation_status == "passed" else "failed",
                "yaml_path": str(yaml_path),
                "json_path": str(json_path),
            },
            "fingerprints": {
                "configuration": stable_hash(
                    {
                        "schema_version": self.settings.user_story_schema_version,
                        "retrieval_sources": self.settings.retrieval_required_sources,
                        "embedding_model": self.settings.embedding_model,
                        "lexical_backend": self.settings.bm25_backend,
                    }
                ),
                "model": stable_hash(
                    {
                        "model": model,
                        "prompt_version": prompt_version,
                        "reasoning_provider": self.settings.reasoning_provider,
                    }
                ),
            },
            "warnings": [],
            "errors": [],
        }
        json_path.write_text(
            json.dumps(production_json_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        debug_payload: dict[str, Any] = {
            "story_id": story.id,
            "source_document_ids": sorted(
                {result.document_id for result in evidence.ranked_results}
            ),
            "source_document_version_ids": sorted(
                {result.document_version_id for result in evidence.ranked_results}
            ),
            "chunk_ids": evidence.source_chunk_ids,
            "graph_paths": evidence.graph_paths,
            "retrieval_scores": [
                {
                    "chunk_id": result.chunk_id,
                    "rank": result.rank,
                    "score": result.score,
                    "sources": result.sources,
                }
                for result in evidence.ranked_results
            ],
            "prompt_version": prompt_version,
            "model": model,
            "validation_result": {
                "status": validation_status,
                "messages": validation_messages,
            },
            "compatibility": {
                "legacy_layout_root": str(legacy_root),
            },
        }
        debug_path.write_text(
            json.dumps(debug_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        trace_payload = {
            "schema_version": "trace-manifest-v1",
            "artifact": {
                "story_id": story.id,
                "path": str(yaml_path),
                "debug_json_path": str(debug_path),
            },
            "workflow": {
                "run_id": self.settings.active_run_id,
                "generation": "user_story",
            },
            "source": {
                "document_version_ids": sorted(
                    {result.document_version_id for result in evidence.ranked_results}
                ),
                "chunk_ids": evidence.source_chunk_ids,
            },
            "requirements": story.traceability.get("requirement_ids", []),
            "evidence": {
                "graph_paths": evidence.graph_paths,
                "query": evidence.query,
                "version_scope": evidence.version_scope,
            },
            "story": {"id": story.id},
            "config_fingerprint": stable_hash(
                {
                    "schema_version": self.settings.user_story_schema_version,
                    "retrieval_sources": self.settings.retrieval_required_sources,
                    "embedding_model": self.settings.embedding_model,
                    "lexical_backend": self.settings.bm25_backend,
                }
            ),
            "model_fingerprint": stable_hash(
                {
                    "model": model,
                    "prompt_version": prompt_version,
                    "reasoning_provider": self.settings.reasoning_provider,
                }
            ),
            "created_at": datetime.now(UTC).isoformat(),
        }
        trace_path.write_text(
            json.dumps(trace_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return ArtifactManifest(
            artifact_id=stable_id(
                "artifact",
                system_name,
                kb_name,
                version,
                story.id,
                str(yaml_path),
            ),
            story_id=story.id,
            generated_file_path=str(yaml_path),
            debug_json_path=str(debug_path),
            trace_manifest_path=str(trace_path),
            source_chunk_ids=evidence.source_chunk_ids,
            model=model,
            prompt_version=prompt_version,
            validation_status="passed" if validation_status == "passed" else "failed",
        )


def _safe_story_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    cleaned = cleaned.strip(".-")
    return cleaned or "US-001"
