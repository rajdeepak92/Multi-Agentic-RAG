# mypy: ignore-errors
"""Neo4j GraphRAG projection adapter."""

from __future__ import annotations

import re
from contextlib import suppress
from importlib import import_module
from typing import Any

from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import (
    ArtifactManifest,
    ChunkRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    DocumentVersionRecord,
    FactRecord,
    GraphMatch,
    RequirementCandidateRecord,
    RequirementConflictRecord,
    RequirementEvidenceRecord,
    RequirementRecord,
    SourceSegmentRecord,
)
from multi_agentic_rag.utils.hashing import stable_id

CONSTRAINTS = [
    "CREATE CONSTRAINT system_name IF NOT EXISTS FOR (n:System) REQUIRE n.system_name IS UNIQUE",
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.document_id IS UNIQUE",
    (
        "CREATE CONSTRAINT document_version_id IF NOT EXISTS "
        "FOR (n:DocumentVersion) REQUIRE n.document_version_id IS UNIQUE"
    ),
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.chunk_id IS UNIQUE",
    "CREATE CONSTRAINT segment_id IF NOT EXISTS FOR (n:Segment) REQUIRE n.segment_id IS UNIQUE",
    (
        "CREATE CONSTRAINT candidate_id IF NOT EXISTS "
        "FOR (n:Candidate) REQUIRE n.candidate_id IS UNIQUE"
    ),
    "CREATE CONSTRAINT passage_id IF NOT EXISTS FOR (n:Passage) REQUIRE n.passage_id IS UNIQUE",
    "CREATE CONSTRAINT sentence_id IF NOT EXISTS FOR (n:Sentence) REQUIRE n.sentence_id IS UNIQUE",
    "CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (n:Fact) REQUIRE n.fact_id IS UNIQUE",
    (
        "CREATE CONSTRAINT requirement_pk IF NOT EXISTS "
        "FOR (n:Requirement) REQUIRE n.requirement_pk IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT evidence_span_id IF NOT EXISTS "
        "FOR (n:EvidenceSpan) REQUIRE n.evidence_id IS UNIQUE"
    ),
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.entity_id IS UNIQUE",
    "CREATE CONSTRAINT delta_id IF NOT EXISTS FOR (n:Delta) REQUIRE n.delta_id IS UNIQUE",
    "CREATE CONSTRAINT conflict_id IF NOT EXISTS FOR (n:Conflict) REQUIRE n.conflict_id IS UNIQUE",
    (
        "CREATE CONSTRAINT retrieval_run_id IF NOT EXISTS "
        "FOR (n:RetrievalRun) REQUIRE n.retrieval_run_id IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT evidence_pack_id IF NOT EXISTS "
        "FOR (n:EvidencePack) REQUIRE n.evidence_pack_id IS UNIQUE"
    ),
    "CREATE CONSTRAINT artifact_id IF NOT EXISTS FOR (n:Artifact) REQUIRE n.artifact_id IS UNIQUE",
    "CREATE CONSTRAINT user_story_id IF NOT EXISTS FOR (n:UserStory) REQUIRE n.story_key IS UNIQUE",
]
ENTITY_LABELS = {
    "sensor": "Sensor",
    "device": "Device",
    "protocol": "Protocol",
    "topic": "Topic",
}
FACT_ENTITY_RELATIONSHIPS = {
    "threshold": "THRESHOLD_FOR",
    "protocol": "IMPLEMENTS_PROTOCOL",
    "protocol_detail": "DETAILS_PROTOCOL",
    "topic": "USES_TOPIC",
}
GRAPH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "with",
}
GRAPH_SYNONYM_GROUPS = (
    {"temperature", "temp"},
    {"threshold", "limit", "range"},
    {"alert", "alarm", "notification"},
    {"sensor", "instrument"},
)
REQUIREMENT_ID_PATTERN = re.compile(
    r"\b(?:BR[-_\s]?[A-Z]{2,10}[-_\s]?\d+|AC[-_\s]?\d+|"
    r"REQ[-_\s]?\d+|BRD[-_\s]?\d+|SRS[-_\s]?\d+|FRS[-_\s]?\d+|"
    r"NFR[-_\s]?[A-Z0-9-]+|AUTO[-_\s]?[A-Z0-9-]+|DOD[-_\s]?[A-Z0-9-]+)\b",
    re.IGNORECASE,
)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class Neo4jGraphRepository:
    """Neo4j adapter using idempotent MERGE queries."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the Neo4j adapter.

        Args:
            settings: Runtime configuration containing Neo4j URI, credentials,
                database name, and required/fallback behavior.
        """

        self.settings = settings
        self._driver: Any | None = None

    @property
    def configured(self) -> bool:
        """Return whether enough Neo4j settings exist to attempt a connection."""

        return bool(self.settings.neo4j_uri)

    def check_connection(self) -> tuple[bool, str]:
        """Verify Neo4j connectivity."""

        if not self.configured:
            return False, "NEO4J_URI is not configured."
        try:
            self._get_driver().verify_connectivity()
        except Exception as exc:
            return False, str(exc)
        return True, "Neo4j connection verified."

    def create_constraints(self) -> None:
        """Create GraphRAG constraints."""

        with self.session() as session:
            for query in CONSTRAINTS:
                session.run(query)

    def clear(
        self,
        *,
        system_name: str | None = None,
        kb_name: str | None = None,
    ) -> int:
        """Delete graph nodes from Neo4j.

        Args:
            system_name: Optional system scope. When omitted, all graph nodes
                are deleted.
            kb_name: Optional knowledge-base scope within the selected system.

        Returns:
            Number of Neo4j nodes deleted.
        """

        cypher = """
        MATCH (n)
        WHERE ($system_name IS NULL OR n.system_name = $system_name)
          AND ($kb_name IS NULL OR n.kb_name = $kb_name)
        WITH collect(n) AS nodes, count(n) AS deleted_count
        FOREACH (node IN nodes | DETACH DELETE node)
        RETURN deleted_count
        """
        with self.session() as session:
            record = session.run(
                cypher,
                {"system_name": system_name, "kb_name": kb_name},
            ).single()
        return int(record["deleted_count"] if record else 0)

    def upsert_graph(
        self,
        *,
        document: DocumentRecord,
        document_version: DocumentVersionRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
        requirements: list[RequirementRecord] | None = None,
        requirement_evidence: list[RequirementEvidenceRecord] | None = None,
        segments: list[SourceSegmentRecord] | None = None,
        requirement_candidates: list[RequirementCandidateRecord] | None = None,
        requirement_conflicts: list[RequirementConflictRecord] | None = None,
    ) -> None:
        """Project the ingestion bundle into Neo4j.

        Args:
            document: Stable document lineage record.
            document_version: Version record for the newly ingested source.
            chunks: Chunk nodes to connect to the document version.
            facts: Fact, requirement, and entity evidence extracted from chunks.
            deltas: Change records between the previous active version and the
                ingested version.
        """

        self.create_constraints()
        with self.session() as session:
            for query, params in self.build_ingestion_cypher(
                document=document,
                document_version=document_version,
                chunks=chunks,
                facts=facts,
                deltas=deltas,
                requirements=requirements or [],
                requirement_evidence=requirement_evidence or [],
                segments=segments or [],
                requirement_candidates=requirement_candidates or [],
                requirement_conflicts=requirement_conflicts or [],
            ):
                session.run(query, params)

    def upsert_user_story_artifact(
        self,
        *,
        manifest: ArtifactManifest,
        story_payload: dict[str, Any],
        system_name: str,
        kb_name: str,
        version: str,
    ) -> None:
        """Project generated user-story artifact lineage into Neo4j."""

        self.create_constraints()
        with self.session() as session:
            for query, params in self.build_user_story_artifact_cypher(
                manifest=manifest,
                story_payload=story_payload,
                system_name=system_name,
                kb_name=kb_name,
                version=version,
            ):
                session.run(query, params)

    def upsert_requirement_ledger(
        self,
        *,
        requirements: list[RequirementRecord],
        requirement_evidence: list[RequirementEvidenceRecord],
    ) -> None:
        """Project canonical requirement ledger rows into Neo4j."""

        self.create_constraints()
        with self.session() as session:
            for requirement in requirements:
                query, params = _requirement_statement(requirement)
                session.run(query, params)
            for evidence in requirement_evidence:
                query, params = _requirement_evidence_statement(evidence)
                session.run(query, params)

    def related_chunk_ids(
        self,
        *,
        query_text: str,
        system_name: str,
        kb_name: str,
        version: str | None,
        active_only: bool | None = None,
        top_k: int,
    ) -> list[str]:
        """Return chunk IDs related to matching facts or requirements.

        Args:
            query_text: Query text matched against projected fact keys and
                values.
            system_name: System filter for graph traversal.
            kb_name: Knowledge-base filter for graph traversal.
            version: Optional version filter. When omitted, any projected
                version for the system and knowledge base can match.
            active_only: Whether to restrict traversal to active evidence. When
                omitted, active evidence is used unless a specific version is
                requested.
            top_k: Maximum number of distinct chunk IDs to return.

        Returns:
            Chunk identifiers ordered by Neo4j's matching order.
        """

        chunk_ids: list[str] = []
        seen: set[str] = set()
        for match in self.related_chunk_matches(
            query_text=query_text,
            system_name=system_name,
            kb_name=kb_name,
            version=version,
            active_only=active_only,
            top_k=top_k,
        ):
            if match.chunk_id in seen:
                continue
            seen.add(match.chunk_id)
            chunk_ids.append(match.chunk_id)
        return chunk_ids

    def related_chunk_matches(
        self,
        *,
        query_text: str,
        system_name: str,
        kb_name: str,
        version: str | None,
        active_only: bool | None = None,
        top_k: int,
    ) -> list[GraphMatch]:
        """Return graph-aware chunk matches with path metadata."""

        if active_only is None:
            active_only = version is None
        query = _normalize_graph_query(query_text)
        if not query["terms"] and not query["requirement_ids"]:
            return []
        cypher = _graph_match_cypher(has_version=bool(version), active_only=active_only)
        with self.session() as session:
            records = session.run(
                cypher,
                {
                    "terms": query["terms"],
                    "requirement_ids": query["requirement_ids"],
                    "system_name": system_name,
                    "kb_name": kb_name,
                    "version": version,
                    "active_status": DocumentStatus.ACTIVE.value,
                    "graph_limit": max(top_k * 8, top_k),
                },
            )
            return [_graph_match_from_record(record) for record in records]

    def run_graph_check(self) -> tuple[bool, str]:
        """Safely verify read/write/delete behavior."""

        available, message = self.check_connection()
        if not available:
            return False, message
        test_system = "__multi_agentic_rag_graph_check__"
        try:
            self.create_constraints()
            with self.session() as session:
                session.run(
                    "MERGE (s:System {system_name: $system_name})",
                    {"system_name": test_system},
                )
                record = session.run(
                    "MATCH (s:System {system_name: $system_name}) RETURN count(s) AS count",
                    {"system_name": test_system},
                ).single()
                session.run(
                    "MATCH (s:System {system_name: $system_name}) DETACH DELETE s",
                    {"system_name": test_system},
                )
            if int(record["count"] if record else 0) != 1:
                return False, "Temporary graph-check node was not readable."
        except Exception as exc:
            return False, str(exc)
        return True, "Neo4j graph-check PASS."

    def build_ingestion_cypher(
        self,
        *,
        document: DocumentRecord,
        document_version: DocumentVersionRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
        requirements: list[RequirementRecord] | None = None,
        requirement_evidence: list[RequirementEvidenceRecord] | None = None,
        segments: list[SourceSegmentRecord] | None = None,
        requirement_candidates: list[RequirementCandidateRecord] | None = None,
        requirement_conflicts: list[RequirementConflictRecord] | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Build idempotent Cypher statements for tests and execution.

        Args:
            document: Stable document lineage record.
            document_version: Version record to attach to the document.
            chunks: Chunk nodes to merge and link to the version.
            facts: Fact nodes and derived requirement/entity relationships.
            deltas: Delta nodes and version relationships.

        Returns:
            Ordered Cypher statement and parameter pairs. The order preserves
            dependencies between document, chunk, fact, and delta nodes.
        """

        statements: list[tuple[str, dict[str, Any]]] = [
            (
                """
                MERGE (s:System {system_name: $system_name})
                SET s.kb_name = $kb_name
                MERGE (d:Document {document_id: $document_id})
                SET d.system_name = $system_name,
                    d.kb_name = $kb_name,
                    d.source_name = $source_name,
                    d.document_type = $document_type
                MERGE (s)-[:HAS_DOCUMENT]->(d)
                MERGE (v:DocumentVersion {document_version_id: $document_version_id})
                SET v.document_id = $document_id,
                    v.system_name = $system_name,
                    v.kb_name = $kb_name,
                    v.version = $version,
                    v.status = $status,
                    v.content_hash = $content_hash,
                    v.source_path = $source_path,
                    v.supersedes_version_id = $supersedes_version_id,
                    v.superseded_by_version_id = $superseded_by_version_id
                MERGE (d)-[:HAS_VERSION]->(v)
                """,
                {
                    **document.model_dump(mode="json"),
                    **document_version.model_dump(mode="json"),
                    "status": document_version.status.value,
                },
            )
        ]
        if document_version.supersedes_version_id:
            statements.append(
                (
                    """
                    MATCH (new:DocumentVersion {document_version_id: $new_version_id})
                    MATCH (old:DocumentVersion {document_version_id: $old_version_id})
                    SET old.status = $superseded_status,
                        old.superseded_by_version_id = $new_version_id
                    MERGE (new)-[:SUPERSEDES]->(old)
                    """,
                    {
                        "new_version_id": document_version.document_version_id,
                        "old_version_id": document_version.supersedes_version_id,
                        "superseded_status": DocumentStatus.SUPERSEDED.value,
                    },
                )
            )
            statements.append(
                (
                    """
                    MATCH (old:DocumentVersion {document_version_id: $old_version_id})
                    MATCH (old)-[:HAS_CHUNK]->(c:Chunk)
                    SET c.status = $superseded_status
                    """,
                    {
                        "old_version_id": document_version.supersedes_version_id,
                        "superseded_status": DocumentStatus.SUPERSEDED.value,
                    },
                )
            )
            statements.append(
                (
                    """
                    MATCH (old:DocumentVersion {document_version_id: $old_version_id})
                    MATCH (old)-[:HAS_CHUNK]->(:Chunk)-[:HAS_PASSAGE]->(p:Passage)
                    SET p.status = $superseded_status
                    """,
                    {
                        "old_version_id": document_version.supersedes_version_id,
                        "superseded_status": DocumentStatus.SUPERSEDED.value,
                    },
                )
            )
            statements.append(
                (
                    """
                    MATCH (old:DocumentVersion {document_version_id: $old_version_id})
                    MATCH (old)-[:HAS_CHUNK]->(:Chunk)-[:HAS_SENTENCE]->(s:Sentence)
                    SET s.status = $superseded_status
                    """,
                    {
                        "old_version_id": document_version.supersedes_version_id,
                        "superseded_status": DocumentStatus.SUPERSEDED.value,
                    },
                )
            )
            statements.append(
                (
                    """
                    MATCH (old:DocumentVersion {document_version_id: $old_version_id})
                    MATCH (old)-[:HAS_CHUNK]->(:Chunk)-[:SUPPORTS_FACT]->(f:Fact)
                    SET f.status = $superseded_status
                    """,
                    {
                        "old_version_id": document_version.supersedes_version_id,
                        "superseded_status": DocumentStatus.SUPERSEDED.value,
                    },
                )
            )
            statements.append(
                (
                    """
                    MATCH (r:Requirement {document_version_id: $old_version_id})
                    SET r.status = $superseded_status
                    """,
                    {
                        "old_version_id": document_version.supersedes_version_id,
                        "superseded_status": DocumentStatus.SUPERSEDED.value,
                    },
                )
            )
        for segment in segments or []:
            statements.append(_segment_statement(segment))
        for chunk in chunks:
            statements.append(
                (
                    """
                    MATCH (v:DocumentVersion {document_version_id: $document_version_id})
                    MERGE (c:Chunk {chunk_id: $chunk_id})
                    SET c.document_id = $document_id,
                        c.system_name = $system_name,
                        c.kb_name = $kb_name,
                        c.version = $version,
                        c.status = $status,
                        c.page = $page,
                        c.chunk_index = $chunk_index,
                        c.content_hash = $content_hash
                    MERGE (v)-[:HAS_CHUNK]->(c)
                    MERGE (p:Passage {passage_id: $passage_id})
                    SET p.chunk_id = $chunk_id,
                        p.document_id = $document_id,
                        p.document_version_id = $document_version_id,
                        p.system_name = $system_name,
                        p.kb_name = $kb_name,
                        p.version = $version,
                        p.status = $status,
                        p.page = $page,
                        p.chunk_index = $chunk_index,
                        p.text = $text
                    MERGE (c)-[:HAS_PASSAGE]->(p)
                    WITH c, p
                    UNWIND $sentences AS sentence
                    MERGE (s:Sentence {sentence_id: sentence.sentence_id})
                    SET s.chunk_id = $chunk_id,
                        s.document_id = $document_id,
                        s.document_version_id = $document_version_id,
                        s.system_name = $system_name,
                        s.kb_name = $kb_name,
                        s.version = $version,
                        s.status = $status,
                        s.page = $page,
                        s.chunk_index = $chunk_index,
                        s.sentence_index = sentence.sentence_index,
                        s.text = sentence.text
                    MERGE (p)-[:HAS_SENTENCE]->(s)
                    MERGE (c)-[:HAS_SENTENCE]->(s)
                    """,
                    _chunk_projection_params(chunk),
                )
            )
        for fact in facts:
            statements.extend(_fact_statements(fact))
        for requirement in requirements or []:
            statements.append(_requirement_statement(requirement))
        for evidence in requirement_evidence or []:
            statements.append(_requirement_evidence_statement(evidence))
        for candidate in requirement_candidates or []:
            statements.append(_candidate_statement(candidate))
        for conflict in requirement_conflicts or []:
            statements.append(_conflict_statement(conflict))
        for delta in deltas:
            statements.append(
                (
                    """
                    MERGE (delta:Delta {delta_id: $delta_id})
                    SET delta.system_name = $system_name,
                        delta.kb_name = $kb_name,
                        delta.from_version = $from_version,
                        delta.to_version = $to_version,
                        delta.fact_key = $fact_key,
                        delta.change_type = $change_type,
                        delta.risk_level = $risk_level
                    WITH delta
                    MATCH (from_v:DocumentVersion {document_version_id: $from_document_version_id})
                    MATCH (to_v:DocumentVersion {document_version_id: $to_document_version_id})
                    MERGE (delta)-[:FROM_VERSION]->(from_v)
                    MERGE (delta)-[:TO_VERSION]->(to_v)
                    """,
                    delta.model_dump(mode="json"),
                )
            )
        return statements

    def build_user_story_artifact_cypher(
        self,
        *,
        manifest: ArtifactManifest,
        story_payload: dict[str, Any],
        system_name: str,
        kb_name: str,
        version: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Build Cypher for generated user-story lineage."""

        story_id = str(story_payload.get("id") or manifest.story_id or manifest.artifact_id)
        story_key = stable_id("user_story", system_name, kb_name, version, story_id)
        return [
            (
                """
                MERGE (a:Artifact {artifact_id: $artifact_id})
                SET a.system_name = $system_name,
                    a.kb_name = $kb_name,
                    a.version = $version,
                    a.artifact_type = 'user_story',
                    a.path = $generated_file_path,
                    a.debug_json_path = $debug_json_path,
                    a.model = $model,
                    a.prompt_version = $prompt_version,
                    a.validation_status = $validation_status
                MERGE (us:UserStory {story_key: $story_key})
                SET us.system_name = $system_name,
                    us.kb_name = $kb_name,
                    us.version = $version,
                    us.story_id = $story_id,
                    us.title = $title,
                    us.status = $story_status,
                    us.priority = $priority,
                    us.persona = $persona,
                    us.user_story = $user_story
                MERGE (us)-[:WRITTEN_TO]->(a)
                WITH us, a
                OPTIONAL MATCH (v:DocumentVersion {
                    system_name: $system_name,
                    kb_name: $kb_name,
                    version: $version
                })
                FOREACH (_ IN CASE WHEN v IS NULL THEN [] ELSE [1] END |
                    MERGE (us)-[:DERIVED_FROM_VERSION]->(v)
                    MERGE (a)-[:DERIVED_FROM_VERSION]->(v)
                )
                WITH us, a
                UNWIND $source_chunk_ids AS chunk_id
                OPTIONAL MATCH (c:Chunk {chunk_id: chunk_id})
                FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                    MERGE (us)-[:TRACES_TO_CHUNK]->(c)
                    MERGE (a)-[:TRACES_TO_CHUNK]->(c)
                )
                WITH us, a
                UNWIND $covered_requirement_ids AS requirement_id
                OPTIONAL MATCH (r:Requirement)
                WHERE r.system_name = $system_name
                  AND r.kb_name = $kb_name
                  AND r.version = $version
                  AND (
                    r.canonical_id = requirement_id
                    OR r.requirement_id = requirement_id
                  )
                FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END |
                    MERGE (us)-[:COVERS]->(r)
                    MERGE (r)-[:COVERED_BY]->(us)
                )
                """,
                {
                    **manifest.model_dump(mode="json"),
                    "system_name": system_name,
                    "kb_name": kb_name,
                    "version": version,
                    "story_key": story_key,
                    "story_id": story_id,
                    "title": str(story_payload.get("title") or ""),
                    "story_status": str(story_payload.get("status") or ""),
                    "priority": str(story_payload.get("priority") or ""),
                    "persona": str(story_payload.get("persona") or ""),
                    "user_story": str(story_payload.get("user_story") or ""),
                    "covered_requirement_ids": _story_requirement_ids(story_payload),
                },
            )
        ]

    def session(self) -> Any:
        """Open a Neo4j session using the configured database when provided."""

        driver = self._get_driver()
        if self.settings.neo4j_database:
            return driver.session(database=self.settings.neo4j_database)
        return driver.session()

    def close(self) -> None:
        """Close the cached Neo4j driver if it has been opened."""

        if self._driver is not None:
            with suppress(Exception):
                self._driver.close()
            self._driver = None

    def _get_driver(self) -> Any:
        if self._driver is None:
            module = import_module("neo4j")
            auth = None
            if self.settings.neo4j_username or self.settings.neo4j_password:
                auth = (self.settings.neo4j_username, self.settings.neo4j_password)
            self._driver = module.GraphDatabase.driver(self.settings.neo4j_uri, auth=auth)
        return self._driver


def _normalize_graph_query(query_text: str) -> dict[str, list[str]]:
    requirement_ids = {
        match.group(0).replace("_", "-").lower()
        for match in REQUIREMENT_ID_PATTERN.finditer(query_text)
    }
    terms: set[str] = set()
    for token in TOKEN_PATTERN.findall(query_text.lower()):
        if token in GRAPH_STOPWORDS:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        terms.add(token)
        if token.endswith("s") and len(token) > 3:
            terms.add(token[:-1])
        for group in GRAPH_SYNONYM_GROUPS:
            if token in group:
                terms.update(group)
    for requirement_id in requirement_ids:
        terms.add(requirement_id)
    return {
        "terms": sorted(terms),
        "requirement_ids": sorted(requirement_ids),
    }


def _story_requirement_ids(story_payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    direct = story_payload.get("covered_requirement_ids")
    if isinstance(direct, list):
        ids.extend(str(item) for item in direct if item)
    traceability = story_payload.get("traceability")
    if isinstance(traceability, dict):
        for key in ("requirement_ids", "covered_requirement_ids", "requirements"):
            value = traceability.get(key)
            if isinstance(value, list):
                ids.extend(str(item) for item in value if item)
            elif isinstance(value, str) and value:
                ids.append(value)
    return sorted(set(ids))


def _graph_match_cypher(*, has_version: bool, active_only: bool) -> str:
    version_vc = _version_filter("v", "c") if has_version else ""
    version_vce = _version_filter("v", "c", "e") if has_version else ""
    version_vcf = _version_filter("v", "c", "f") if has_version else ""
    version_vcfr = _version_filter("v", "c", "f", "r") if has_version else ""
    version_vcr = _version_filter("v", "c", "r") if has_version else ""
    version_related = _version_filter("v", "c", "e", "ef", "r", "f") if has_version else ""
    active_vc = _active_filter("v", "c") if active_only else ""
    active_vce = _active_filter("v", "c", "e") if active_only else ""
    active_vcf = _active_filter("v", "c", "f") if active_only else ""
    active_vcfr = _active_filter("v", "c", "f", "r") if active_only else ""
    active_vcr = _active_filter("v", "c", "r") if active_only else ""
    active_related = _active_filter("v", "c", "e", "ef", "r", "f") if active_only else ""
    return f"""
    WITH $terms AS terms, $requirement_ids AS requirement_ids
    CALL (terms, requirement_ids) {{
      WITH terms, requirement_ids
      MATCH (v:DocumentVersion)-[:HAS_CHUNK]->(c:Chunk)-[:MENTIONS]->(e:Entity)
      WHERE v.system_name = $system_name
        AND v.kb_name = $kb_name
        AND c.system_name = $system_name
        AND c.kb_name = $kb_name
        AND e.system_name = $system_name
        AND e.kb_name = $kb_name
        {version_vce}
        {active_vce}
      WITH v, c, e, terms,
           toLower(coalesce(e.name, '') + ' ' + coalesce(e.entity_type, '')) AS searchable
      WITH v, c, e, [term IN terms WHERE searchable CONTAINS term] AS matched_terms
      WHERE size(matched_terms) > 0
      RETURN c.chunk_id AS chunk_id,
             1.50 + (0.25 * size(matched_terms)) AS score,
             'entity match: ' + coalesce(e.entity_type, 'entity') + ':' +
             coalesce(e.name, '') AS reason,
             [
               'DocumentVersion:' + v.version,
               'Entity:' + coalesce(e.name, ''),
               'Chunk:' + c.chunk_id
             ] AS path,
             matched_terms AS matched_terms

      UNION ALL

      WITH terms, requirement_ids
      MATCH (v:DocumentVersion)-[:HAS_CHUNK]->(c:Chunk)-[:SUPPORTS_FACT]->(f:Fact)
      WHERE v.system_name = $system_name
        AND v.kb_name = $kb_name
        AND c.system_name = $system_name
        AND c.kb_name = $kb_name
        AND f.system_name = $system_name
        AND f.kb_name = $kb_name
        {version_vcf}
        {active_vcf}
      WITH v, c, f, terms,
           toLower(
             coalesce(f.fact_key, '') + ' ' +
             coalesce(f.fact_type, '') + ' ' +
             coalesce(f.value, '') + ' ' +
             coalesce(properties(f).evidence, '') + ' ' +
             coalesce(properties(f).requirement_id, '')
           ) AS searchable
      WITH v, c, f, [term IN terms WHERE searchable CONTAINS term] AS matched_terms
      WHERE size(matched_terms) > 0
      RETURN c.chunk_id AS chunk_id,
             1.80 + (0.20 * size(matched_terms)) AS score,
             'fact match: ' + coalesce(f.fact_key, '') AS reason,
             [
               'DocumentVersion:' + v.version,
               'Fact:' + coalesce(f.fact_key, ''),
               'Chunk:' + c.chunk_id
             ] AS path,
             matched_terms AS matched_terms

      UNION ALL

      WITH terms, requirement_ids
      MATCH (v:DocumentVersion)-[:HAS_CHUNK]->(c:Chunk)-[:SUPPORTS_FACT]->(f:Fact)
            -[:TRACES_TO_REQUIREMENT|DESCRIBES_REQUIREMENT]->(r:Requirement)
      WHERE v.system_name = $system_name
        AND v.kb_name = $kb_name
        AND c.system_name = $system_name
        AND c.kb_name = $kb_name
        AND f.system_name = $system_name
        AND f.kb_name = $kb_name
        AND r.system_name = $system_name
        AND r.kb_name = $kb_name
        {version_vcfr}
        {active_vcfr}
      WITH v, c, f, r, terms, requirement_ids,
           toLower(coalesce(r.requirement_id, '')) AS requirement_id,
           toLower(
             coalesce(r.requirement_id, '') + ' ' +
             coalesce(r.text, '') + ' ' +
             coalesce(f.fact_key, '') + ' ' +
             coalesce(f.value, '')
           ) AS searchable
      WITH v, c, r, requirement_id,
           [term IN terms WHERE searchable CONTAINS term] AS matched_terms,
           requirement_id IN requirement_ids AS matched_requirement_id
      WHERE size(matched_terms) > 0 OR matched_requirement_id
      RETURN c.chunk_id AS chunk_id,
             2.30 + (0.25 * size(matched_terms)) +
             CASE WHEN matched_requirement_id THEN 1.00 ELSE 0.00 END AS score,
             'requirement match: ' + coalesce(r.requirement_id, '') AS reason,
             [
               'DocumentVersion:' + v.version,
               'Requirement:' + coalesce(r.requirement_id, ''),
               'Chunk:' + c.chunk_id
             ] AS path,
             matched_terms +
             CASE WHEN matched_requirement_id THEN [requirement_id] ELSE [] END AS matched_terms

      UNION ALL

      WITH terms, requirement_ids
      MATCH (v:DocumentVersion)-[:DECLARES]->(r:Requirement)-[:SUPPORTED_BY]->(c:Chunk)
      WHERE v.system_name = $system_name
        AND v.kb_name = $kb_name
        AND c.system_name = $system_name
        AND c.kb_name = $kb_name
        AND r.system_name = $system_name
        AND r.kb_name = $kb_name
        {version_vcr}
        {active_vcr}
      WITH v, c, r, terms, requirement_ids,
           toLower(coalesce(r.requirement_id, '')) AS requirement_id,
           toLower(coalesce(r.canonical_id, '')) AS canonical_id,
           toLower(
             coalesce(r.requirement_id, '') + ' ' +
             coalesce(r.canonical_id, '') + ' ' +
             coalesce(r.requirement_type, '') + ' ' +
             coalesce(r.category, '') + ' ' +
             coalesce(r.title, '') + ' ' +
             coalesce(r.text, '')
           ) AS searchable
      WITH v, c, r, requirement_id, canonical_id,
           [term IN terms WHERE searchable CONTAINS term] AS matched_terms,
           requirement_id IN requirement_ids OR canonical_id IN requirement_ids
             AS matched_requirement_id
      WHERE size(matched_terms) > 0 OR matched_requirement_id
      RETURN c.chunk_id AS chunk_id,
             2.45 + (0.25 * size(matched_terms)) +
             CASE WHEN matched_requirement_id THEN 1.00 ELSE 0.00 END AS score,
             'ledger requirement match: ' +
             coalesce(r.canonical_id, r.requirement_id, '') AS reason,
             [
               'DocumentVersion:' + v.version,
               'Requirement:' + coalesce(r.canonical_id, r.requirement_id, ''),
               'Chunk:' + c.chunk_id
             ] AS path,
             matched_terms +
             CASE
               WHEN matched_requirement_id
               THEN [coalesce(canonical_id, requirement_id)]
               ELSE []
             END
               AS matched_terms

      UNION ALL

      WITH terms, requirement_ids
      MATCH (ef:Fact)-[]->(e:Entity)
      MATCH (ef)-[:TRACES_TO_REQUIREMENT|DESCRIBES_REQUIREMENT]->(r:Requirement)
            <-[:TRACES_TO_REQUIREMENT|DESCRIBES_REQUIREMENT]-(f:Fact)<-[:SUPPORTS_FACT]-(c:Chunk)
            <-[:HAS_CHUNK]-(v:DocumentVersion)
      WHERE v.system_name = $system_name
        AND v.kb_name = $kb_name
        AND c.system_name = $system_name
        AND c.kb_name = $kb_name
        AND e.system_name = $system_name
        AND e.kb_name = $kb_name
        AND ef.system_name = $system_name
        AND ef.kb_name = $kb_name
        AND f.system_name = $system_name
        AND f.kb_name = $kb_name
        AND r.system_name = $system_name
        AND r.kb_name = $kb_name
        {version_related}
        {active_related}
      WITH v, c, e, r, terms,
           toLower(coalesce(e.name, '') + ' ' + coalesce(e.entity_type, '')) AS searchable
      WITH v, c, e, r, [term IN terms WHERE searchable CONTAINS term] AS matched_terms
      WHERE size(matched_terms) > 0
      RETURN c.chunk_id AS chunk_id,
             2.00 + (0.20 * size(matched_terms)) AS score,
             'entity requirement expansion: ' + coalesce(e.name, '') AS reason,
             [
               'DocumentVersion:' + v.version,
               'Entity:' + coalesce(e.name, ''),
               'Requirement:' + coalesce(r.requirement_id, ''),
               'Chunk:' + c.chunk_id
             ] AS path,
             matched_terms AS matched_terms

      UNION ALL

      WITH terms, requirement_ids
      MATCH (v:DocumentVersion)-[:HAS_CHUNK]->(c:Chunk)
      WHERE v.system_name = $system_name
        AND v.kb_name = $kb_name
        AND c.system_name = $system_name
        AND c.kb_name = $kb_name
        {version_vc}
        {active_vc}
        AND size(requirement_ids) > 0
      WITH v, c, requirement_ids,
           toLower(coalesce(c.chunk_id, '')) AS chunk_key
      WITH v, c,
           [
             requirement_id IN requirement_ids
             WHERE chunk_key CONTAINS requirement_id
           ] AS matched_terms
      WHERE size(matched_terms) > 0
      RETURN c.chunk_id AS chunk_id,
             1.00 + (0.10 * size(matched_terms)) AS score,
             'chunk id match' AS reason,
             ['DocumentVersion:' + v.version, 'Chunk:' + c.chunk_id] AS path,
             matched_terms AS matched_terms
    }}
    RETURN DISTINCT chunk_id, score, reason, path, matched_terms
    ORDER BY score DESC, chunk_id ASC
    LIMIT $graph_limit
    """


def _version_filter(*aliases: str) -> str:
    return "\n".join(f"        AND {alias}.version = $version" for alias in aliases)


def _active_filter(*aliases: str) -> str:
    return "\n".join(f"        AND {alias}.status = $active_status" for alias in aliases)


def _graph_match_from_record(record: Any) -> GraphMatch:
    return GraphMatch(
        chunk_id=str(record["chunk_id"]),
        score=float(record["score"] or 0.0),
        reason=str(record["reason"] or ""),
        path=[str(part) for part in record["path"] or []],
        matched_terms=[str(term) for term in record["matched_terms"] or []],
    )


def _requirement_statement(requirement: RequirementRecord) -> tuple[str, dict[str, Any]]:
    requirement_pk = requirement.requirement_pk or stable_id(
        "requirement",
        requirement.system_name,
        requirement.kb_name,
        requirement.version,
        requirement.canonical_id or requirement.requirement_id,
        requirement.document_version_id,
    )
    payload = {
        **requirement.model_dump(mode="json"),
        "requirement_pk": requirement_pk,
        "canonical_id": requirement.canonical_id or requirement.requirement_id,
        "requirement_type": requirement.requirement_type.value,
        "status": requirement.status.value,
    }
    return (
        """
        MATCH (v:DocumentVersion {document_version_id: $document_version_id})
        OPTIONAL MATCH (c:Chunk {chunk_id: $chunk_id})
        MERGE (r:Requirement {requirement_pk: $requirement_pk})
        SET r.system_name = $system_name,
            r.kb_name = $kb_name,
            r.version = $version,
            r.status = $status,
            r.document_id = $document_id,
            r.document_version_id = $document_version_id,
            r.chunk_id = $chunk_id,
            r.requirement_id = $requirement_id,
            r.canonical_id = $canonical_id,
            r.requirement_type = $requirement_type,
            r.category = $category,
            r.title = $title,
            r.text = $text,
            r.normalized_text = $normalized_text,
            r.story_driving = $story_driving,
            r.coverage_required = $coverage_required,
            r.extraction_method = $extraction_method,
            r.confidence = $confidence,
            r.semantic_key = $semantic_key,
            r.source_name = $source_name,
            r.page = $page,
            r.section_title = $section_title
        MERGE (v)-[:DECLARES]->(r)
        FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
            MERGE (r)-[:SUPPORTED_BY]->(c)
            MERGE (c)-[:SUPPORTS_REQUIREMENT]->(r)
        )
        """,
        payload,
    )


def _requirement_evidence_statement(
    evidence: RequirementEvidenceRecord,
) -> tuple[str, dict[str, Any]]:
    payload = evidence.model_dump(mode="json")
    return (
        """
        MATCH (r:Requirement {requirement_pk: $requirement_pk})
        OPTIONAL MATCH (c:Chunk {chunk_id: $chunk_id})
        MERGE (ev:EvidenceSpan {evidence_id: $requirement_evidence_id})
        SET ev.requirement_pk = $requirement_pk,
            ev.chunk_id = $chunk_id,
            ev.document_version_id = $document_version_id,
            ev.source_name = $source_name,
            ev.page = $page,
            ev.section_title = $section_title,
            ev.start_offset = $start_offset,
            ev.end_offset = $end_offset,
            ev.evidence_text = $evidence_text,
            ev.extraction_method = $extraction_method,
            ev.confidence = $confidence
        MERGE (r)-[:HAS_EVIDENCE]->(ev)
        FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
            MERGE (ev)-[:FROM_CHUNK]->(c)
        )
        """,
        payload,
    )


def _fact_statements(fact: FactRecord) -> list[tuple[str, dict[str, Any]]]:
    payload = {**fact.model_dump(mode="json"), "status": fact.status.value}
    statements: list[tuple[str, dict[str, Any]]] = [
        (
            """
            MATCH (c:Chunk {chunk_id: $chunk_id})
            MERGE (f:Fact {fact_id: $fact_id})
            SET f.fact_key = $fact_key,
                f.fact_type = $fact_type,
                f.value = $value,
                f.unit = $unit,
                f.evidence = $evidence,
                f.requirement_id = $requirement_id,
                f.status = $status,
                f.version = $version,
                f.semantic_key = $semantic_key,
                f.system_name = $system_name,
                f.kb_name = $kb_name,
                f.document_id = $document_id,
                f.document_version_id = $document_version_id,
                f.chunk_id = $chunk_id
            MERGE (c)-[:SUPPORTS_FACT]->(f)
            """,
            payload,
        )
    ]
    linked_requirement_id = fact.value if fact.fact_type == "requirement" else fact.requirement_id
    if linked_requirement_id:
        linked_requirement_pk = stable_id(
            "requirement",
            fact.system_name,
            fact.kb_name,
            fact.version,
            linked_requirement_id,
            fact.document_version_id,
        )
        requirement_relationship = (
            "DESCRIBES_REQUIREMENT"
            if fact.fact_type == "requirement"
            else "TRACES_TO_REQUIREMENT"
        )
        statements.append(
            (
                f"""
                MATCH (f:Fact {{fact_id: $fact_id}})
                MERGE (r:Requirement {{requirement_pk: $linked_requirement_pk}})
                SET r.system_name = $system_name,
                    r.kb_name = $kb_name,
                    r.version = $version,
                    r.status = $status,
                    r.document_id = $document_id,
                    r.document_version_id = $document_version_id,
                    r.chunk_id = $chunk_id,
                    r.requirement_id = $linked_requirement_id,
                    r.canonical_id = coalesce(r.canonical_id, $linked_requirement_id),
                    r.text = $evidence
                MERGE (f)-[:{requirement_relationship}]->(r)
                """,
                {
                    **payload,
                    "linked_requirement_id": linked_requirement_id,
                    "linked_requirement_pk": linked_requirement_pk,
                },
            )
        )
    for entity in _entities_from_fact(fact):
        relationship = entity.pop("relationship")
        label = entity.pop("label")
        relationship_clause = (
            f"MERGE (f)-[:{relationship}]->(e)" if relationship else ""
        )
        statements.append(
            (
                f"""
                MATCH (c:Chunk {{chunk_id: $chunk_id}})
                MATCH (f:Fact {{fact_id: $fact_id}})
                MERGE (e:Entity:{label} {{entity_id: $entity_id}})
                SET e.entity_type = $entity_type,
                    e.name = $name,
                    e.system_name = $system_name,
                    e.kb_name = $kb_name,
                    e.version = $version,
                    e.status = $status,
                    e.document_id = $document_id,
                    e.document_version_id = $document_version_id,
                    e.chunk_id = $chunk_id
                MERGE (c)-[:MENTIONS]->(e)
                {relationship_clause}
                WITH c, e
                OPTIONAL MATCH (c)-[:HAS_PASSAGE]->(p:Passage)
                FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
                    MERGE (p)-[:MENTIONS]->(e)
                )
                WITH c, e
                OPTIONAL MATCH (c)-[:HAS_SENTENCE]->(s:Sentence)
                FOREACH (_ IN CASE WHEN s IS NULL THEN [] ELSE [1] END |
                    MERGE (s)-[:MENTIONS]->(e)
                )
                """,
                {**payload, **entity},
            )
        )
    return statements


def _chunk_projection_params(chunk: ChunkRecord) -> dict[str, Any]:
    return {
        **chunk.model_dump(mode="json"),
        "status": chunk.status.value,
        "passage_id": stable_id("passage", chunk.chunk_id),
        "sentences": _sentence_rows(chunk),
    }


def _segment_statement(segment: SourceSegmentRecord) -> tuple[str, dict[str, Any]]:
    payload = {**segment.model_dump(mode="json"), "status": segment.status.value}
    return (
        """
        MATCH (v:DocumentVersion {document_version_id: $document_version_id})
        MERGE (seg:Segment {segment_id: $segment_id})
        SET seg.document_id = $document_id,
            seg.document_version_id = $document_version_id,
            seg.system_name = $system_name,
            seg.kb_name = $kb_name,
            seg.version = $version,
            seg.status = $status,
            seg.source_name = $source_name,
            seg.page = $page,
            seg.segment_index = $segment_index,
            seg.segment_type = $segment_type,
            seg.section_title = $section_title,
            seg.start_offset = $start_offset,
            seg.end_offset = $end_offset,
            seg.text = $text
        MERGE (v)-[:HAS_SEGMENT]->(seg)
        WITH seg
        UNWIND $chunk_ids AS chunk_id
        MATCH (c:Chunk {chunk_id: chunk_id})
        MERGE (seg)-[:CONTAINS_CHUNK]->(c)
        MERGE (c)-[:IN_SEGMENT]->(seg)
        """,
        payload,
    )


def _candidate_statement(candidate: RequirementCandidateRecord) -> tuple[str, dict[str, Any]]:
    payload = {
        **candidate.model_dump(mode="json"),
        "status": candidate.status.value,
        "requirement_type": candidate.requirement_type.value,
    }
    return (
        """
        OPTIONAL MATCH (seg:Segment {segment_id: $segment_id})
        OPTIONAL MATCH (c:Chunk {chunk_id: $chunk_id})
        OPTIONAL MATCH (r:Requirement {requirement_pk: $canonical_id})
        MERGE (cand:Candidate {candidate_id: $candidate_id})
        SET cand.document_id = $document_id,
            cand.document_version_id = $document_version_id,
            cand.segment_id = $segment_id,
            cand.chunk_id = $chunk_id,
            cand.system_name = $system_name,
            cand.kb_name = $kb_name,
            cand.version = $version,
            cand.status = $status,
            cand.requirement_type = $requirement_type,
            cand.canonical_id = $canonical_id,
            cand.proposed_requirement_id = $proposed_requirement_id,
            cand.text = $text,
            cand.normalized_text = $normalized_text,
            cand.evidence_text = $evidence_text,
            cand.scope = $scope,
            cand.confidence = $confidence,
            cand.semantic_key = $semantic_key,
            cand.rejection_reason = $rejection_reason
        FOREACH (_ IN CASE WHEN seg IS NULL THEN [] ELSE [1] END |
            MERGE (seg)-[:HAS_CANDIDATE]->(cand)
        )
        FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
            MERGE (cand)-[:FROM_CHUNK]->(c)
        )
        """,
        payload,
    )


def _conflict_statement(conflict: RequirementConflictRecord) -> tuple[str, dict[str, Any]]:
    payload = {**conflict.model_dump(mode="json"), "status": conflict.status.value}
    return (
        """
        MERGE (conflict:Conflict {conflict_id: $conflict_id})
        SET conflict.system_name = $system_name,
            conflict.kb_name = $kb_name,
            conflict.version = $version,
            conflict.document_version_id = $document_version_id,
            conflict.semantic_key = $semantic_key,
            conflict.claims = $claims,
            conflict.status = $status,
            conflict.summary = $summary
        WITH conflict
        UNWIND $requirement_pks AS requirement_pk
        MATCH (r:Requirement {requirement_pk: requirement_pk})
        MERGE (conflict)-[:INVOLVES_REQUIREMENT]->(r)
        MERGE (r)-[:HAS_CONFLICT]->(conflict)
        """,
        payload,
    )


def _sentence_rows(chunk: ChunkRecord) -> list[dict[str, Any]]:
    candidates = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", chunk.text.strip())
        if sentence.strip()
    ]
    if not candidates and chunk.text.strip():
        candidates = [chunk.text.strip()]
    return [
        {
            "sentence_id": stable_id("sentence", chunk.chunk_id, index, sentence),
            "sentence_index": index,
            "text": sentence,
        }
        for index, sentence in enumerate(candidates)
    ]


def _entities_from_fact(fact: FactRecord) -> list[dict[str, str | None]]:
    entity_type: str | None = None
    name: str | None = None
    if fact.fact_type == "threshold":
        sensor = _validated_llm_name(fact) or str(fact.metadata.get("sensor") or "").lower()
        if sensor:
            entity_type = "sensor"
            name = sensor
    elif fact.fact_type == "protocol_detail":
        protocol = _validated_llm_name(fact) or str(fact.metadata.get("protocol") or "").strip()
        if not protocol and fact.fact_key.startswith("protocol_detail:"):
            protocol = fact.fact_key.split(":", 2)[1]
        if protocol:
            entity_type = "protocol"
            name = _normalize_protocol_name(protocol)
    elif fact.fact_type in ENTITY_LABELS:
        entity_type = fact.fact_type
        preferred_name = _validated_llm_name(fact) or fact.value
        name = (
            _normalize_protocol_name(preferred_name)
            if entity_type == "protocol"
            else preferred_name
        )
    if not entity_type or not name:
        return []
    label = ENTITY_LABELS[entity_type]
    return [
        {
            "entity_id": stable_id(
                "entity",
                fact.system_name,
                fact.kb_name,
                entity_type,
                name.lower(),
            ),
            "entity_type": entity_type,
            "name": name,
            "label": label,
            "relationship": FACT_ENTITY_RELATIONSHIPS.get(fact.fact_type),
        }
    ]


def _validated_llm_name(fact: FactRecord) -> str | None:
    if str(fact.metadata.get("llm_review_status") or "").lower() != "validated":
        return None
    candidate = fact.metadata.get("llm_canonical_name")
    if isinstance(candidate, str):
        candidate = candidate.strip()
        if candidate:
            return candidate
    return None


def _normalize_protocol_name(value: str) -> str:
    normalized = value.strip()
    return normalized.upper() if normalized.lower() in {"mqtt", "can", "rest"} else normalized
