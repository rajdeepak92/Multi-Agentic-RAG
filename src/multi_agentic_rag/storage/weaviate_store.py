"""Weaviate vector store adapter using the public HTTP API."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import httpx

from multi_agentic_rag.models import ChunkRecord
from multi_agentic_rag.storage.chroma_store import HashEmbeddingFunction


class WeaviateVectorStore:
    """Weaviate adapter for hybrid vector plus BM25 retrieval.

    The adapter uses explicit vectors so local tests can keep the deterministic
    hash embedding and production can later swap in a higher-quality embedder
    without changing retrieval contracts.
    """

    name = "weaviate"

    def __init__(
        self,
        *,
        url: str,
        api_key: str | None = None,
        collection_name: str = "MultiAgenticRagChunk",
        hybrid_alpha: float = 0.65,
        embedding_function: Any | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.collection_name = self._validate_collection_name(collection_name)
        self.hybrid_alpha = hybrid_alpha
        self.embedding_function = embedding_function or HashEmbeddingFunction()
        self.timeout_seconds = timeout_seconds

    def index_chunks(self, chunks: list[ChunkRecord]) -> None:
        if not chunks:
            return
        self._ensure_schema()
        headers = self._headers()
        with httpx.Client(timeout=self.timeout_seconds, headers=headers) as client:
            for chunk in chunks:
                payload = {
                    "class": self.collection_name,
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id)),
                    "properties": self._properties(chunk),
                    "vector": self.embedding_function.embed_query(chunk.text),
                }
                response = client.put(
                    f"{self.url}/v1/objects/{self.collection_name}/{payload['id']}",
                    json=payload,
                )
                response.raise_for_status()

    def query(
        self,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        vector = self.embedding_function.embed_query(query_text)
        graph_query = self._graphql_query(
            query_text=query_text,
            vector=vector,
            filters=filters or {},
            top_k=top_k,
        )
        response = httpx.post(
            f"{self.url}/v1/graphql",
            headers=self._headers(),
            json={"query": graph_query},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(json.dumps(payload["errors"], sort_keys=True))
        records = payload.get("data", {}).get("Get", {}).get(self.collection_name, [])
        return [
            {
                "chunk_id": record.get("chunk_id"),
                "text": record.get("text"),
                "metadata": {
                    "document_id": record.get("document_id"),
                    "system_name": record.get("system_name"),
                    "version": record.get("version"),
                    "status": record.get("status"),
                    "source_name": record.get("source_name"),
                    "page": record.get("page"),
                    "section_title": record.get("section_title") or "",
                    "chunk_index": record.get("chunk_index"),
                    "content_hash": record.get("content_hash"),
                },
                "score": record.get("_additional", {}).get("score"),
                "distance": record.get("_additional", {}).get("distance"),
            }
            for record in records
        ]

    def check_connection(self) -> tuple[bool, str]:
        try:
            response = httpx.get(
                f"{self.url}/v1/.well-known/ready",
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except Exception as exc:
            return False, str(exc)
        return True, "Weaviate connection verified."

    def _ensure_schema(self) -> None:
        headers = self._headers()
        with httpx.Client(timeout=self.timeout_seconds, headers=headers) as client:
            response = client.get(f"{self.url}/v1/schema/{self.collection_name}")
            if response.status_code == 200:
                return
            if response.status_code != 404:
                response.raise_for_status()
            create_response = client.post(
                f"{self.url}/v1/schema",
                json={
                    "class": self.collection_name,
                    "description": "multi-agentic-rag evidence chunks",
                    "vectorizer": "none",
                    "properties": [
                        {"name": "chunk_id", "dataType": ["text"]},
                        {"name": "document_id", "dataType": ["text"]},
                        {"name": "system_name", "dataType": ["text"]},
                        {"name": "version", "dataType": ["text"]},
                        {"name": "status", "dataType": ["text"]},
                        {"name": "source_name", "dataType": ["text"]},
                        {"name": "page", "dataType": ["int"]},
                        {"name": "section_title", "dataType": ["text"]},
                        {"name": "chunk_index", "dataType": ["int"]},
                        {"name": "content_hash", "dataType": ["text"]},
                        {"name": "text", "dataType": ["text"]},
                    ],
                },
            )
            create_response.raise_for_status()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _properties(chunk: ChunkRecord) -> dict[str, Any]:
        return {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "system_name": chunk.system_name,
            "version": chunk.version,
            "status": chunk.status.value,
            "source_name": chunk.source_name,
            "page": chunk.page,
            "section_title": chunk.section_title or "",
            "chunk_index": chunk.chunk_index,
            "content_hash": chunk.content_hash,
            "text": chunk.text,
        }

    def _graphql_query(
        self,
        *,
        query_text: str,
        vector: list[float],
        filters: dict[str, Any],
        top_k: int,
    ) -> str:
        vector_text = ", ".join(f"{value:.8f}" for value in vector)
        where_clause = self._where_clause(filters)
        where_text = f"where: {where_clause}" if where_clause else ""
        query_json = json.dumps(query_text)
        alpha = min(max(self.hybrid_alpha, 0.0), 1.0)
        return f"""
        {{
          Get {{
            {self.collection_name}(
              hybrid: {{query: {query_json}, vector: [{vector_text}], alpha: {alpha}}}
              limit: {max(1, top_k)}
              {where_text}
            ) {{
              chunk_id
              document_id
              system_name
              version
              status
              source_name
              page
              section_title
              chunk_index
              content_hash
              text
              _additional {{
                score
                distance
              }}
            }}
          }}
        }}
        """

    @staticmethod
    def _where_clause(filters: dict[str, Any]) -> str:
        operands = []
        for key, value in filters.items():
            if value is None:
                continue
            if isinstance(value, int):
                operands.append(
                    f'{{path: ["{key}"], operator: Equal, valueInt: {value}}}'
                )
            else:
                operands.append(
                    f'{{path: ["{key}"], operator: Equal, valueText: {json.dumps(str(value))}}}'
                )
        if not operands:
            return ""
        if len(operands) == 1:
            return operands[0]
        return "{operator: And, operands: [" + ", ".join(operands) + "]}"

    @staticmethod
    def _validate_collection_name(collection_name: str) -> str:
        if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", collection_name):
            raise ValueError(
                "Weaviate collection names must be GraphQL-safe, e.g. MultiAgenticRagChunk."
            )
        return collection_name
