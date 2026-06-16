"""Vector store provider selection."""

from __future__ import annotations

from dataclasses import dataclass

from multi_agentic_rag.config import Settings
from multi_agentic_rag.storage.chroma_store import ChromaVectorStore
from multi_agentic_rag.storage.embedding_factory import select_embedding_function
from multi_agentic_rag.storage.registry import require_local_dev_mode
from multi_agentic_rag.storage.vector_store import VectorStore
from multi_agentic_rag.storage.weaviate_store import WeaviateVectorStore


@dataclass(frozen=True)
class VectorStoreSelection:
    """Selected vector store plus provider metadata."""

    provider: str
    store: VectorStore
    reason: str


def select_vector_store(settings: Settings) -> VectorStoreSelection:
    """Select the configured vector store with explicit local and managed options."""

    provider = settings.vector_store_provider.lower()
    if provider not in {"auto", "weaviate", "chroma"}:
        raise ValueError(f"Unsupported vector store provider: {settings.vector_store_provider}")
    embedding = select_embedding_function(settings)
    if provider in {"auto", "weaviate"} and settings.weaviate_url:
        return VectorStoreSelection(
            provider="weaviate",
            store=WeaviateVectorStore(
                url=settings.weaviate_url,
                api_key=settings.weaviate_api_key,
                collection_name=settings.weaviate_collection,
                hybrid_alpha=settings.weaviate_hybrid_alpha,
                embedding_function=embedding.embedding_function,
                embedding_provider=embedding.provider,
                embedding_model=embedding.model_name,
            ),
            reason=f"WEAVIATE_URL is configured; embeddings={embedding.provider}:{embedding.model_name}.",
        )
    if provider == "weaviate":
        raise RuntimeError("VECTOR_STORE_PROVIDER=weaviate requires WEAVIATE_URL.")
    require_local_dev_mode(settings, "VECTOR_STORE_PROVIDER=chroma")
    return VectorStoreSelection(
        provider="chroma",
        store=ChromaVectorStore(
            settings.chroma_path,
            embedding_function=embedding.embedding_function,
            embedding_provider=embedding.provider,
            embedding_model=embedding.model_name,
        ),
        reason=f"Configured local Chroma store selected; embeddings={embedding.provider}:{embedding.model_name}.",
    )
