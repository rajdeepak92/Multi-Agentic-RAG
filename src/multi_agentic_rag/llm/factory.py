"""Reasoning-client factory."""

from __future__ import annotations

from typing import Literal

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.exceptions import ConfigError
from multi_agentic_rag.llm.azure_openai import AzureOpenAIReasoningClient
from multi_agentic_rag.llm.gemini_reasoning import GeminiReasoningClient
from multi_agentic_rag.llm.hf_reasoning import HuggingFaceReasoningClient
from multi_agentic_rag.llm.openai_reasoning import OpenAIReasoningClient
from multi_agentic_rag.llm.structured import ReasoningClient

ReasoningModelSelector = Literal["openai", "azure_openai", "hf", "huggingface", "gemini"]


def build_reasoning_client(
    settings: Settings | None = None,
    model_selector: ReasoningModelSelector | None = None,
) -> ReasoningClient:
    """Build the selected structured reasoning backend."""

    loaded_settings = settings or get_settings()
    if model_selector is None:
        model_selector = loaded_settings.reasoning_provider
    if model_selector == "huggingface":
        model_selector = "hf"
    if model_selector == "openai":
        return OpenAIReasoningClient(loaded_settings)
    if model_selector == "azure_openai":
        return AzureOpenAIReasoningClient(loaded_settings)
    if model_selector == "hf":
        return HuggingFaceReasoningClient(loaded_settings)
    if model_selector == "gemini":
        return GeminiReasoningClient(loaded_settings)
    raise ConfigError(f"Unsupported reasoning model selector: {model_selector}")
