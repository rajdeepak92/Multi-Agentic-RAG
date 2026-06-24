"""Reasoning client interfaces."""

from multi_agentic_rag.llm.azure_openai import (
    AzureDeploymentRouter,
    AzureOpenAICapabilityManifest,
    AzureOpenAIReasoningClient,
    azure_preflight,
)
from multi_agentic_rag.llm.factory import ReasoningModelSelector, build_reasoning_client
from multi_agentic_rag.llm.gemini_reasoning import GeminiReasoningClient
from multi_agentic_rag.llm.hf_reasoning import (
    HF_REASONING_GPU_INSTALL_HINT,
    HFDependencyStatus,
    HFReasoningEnvironmentReport,
    HuggingFaceReasoningClient,
    format_hf_reasoning_preflight_error,
    inspect_hf_reasoning_environment,
    validate_hf_reasoning_environment,
)
from multi_agentic_rag.llm.openai_reasoning import (
    OpenAIReasoningClient,
)
from multi_agentic_rag.llm.structured import GenerationConfig, ReasoningClient

__all__ = [
    "HuggingFaceReasoningClient",
    "GeminiReasoningClient",
    "GenerationConfig",
    "HF_REASONING_GPU_INSTALL_HINT",
    "HFDependencyStatus",
    "HFReasoningEnvironmentReport",
    "AzureDeploymentRouter",
    "AzureOpenAICapabilityManifest",
    "AzureOpenAIReasoningClient",
    "OpenAIReasoningClient",
    "ReasoningClient",
    "ReasoningModelSelector",
    "build_reasoning_client",
    "azure_preflight",
    "format_hf_reasoning_preflight_error",
    "inspect_hf_reasoning_environment",
    "validate_hf_reasoning_environment",
]
