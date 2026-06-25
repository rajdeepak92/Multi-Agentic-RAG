"""Native Azure OpenAI client construction helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from multi_agentic_rag.exceptions import ConfigError

if TYPE_CHECKING:
    from multi_agentic_rag.config import Settings


def normalize_azure_endpoint(endpoint: str) -> str:
    """Normalize and validate a native Azure OpenAI endpoint."""

    stripped = endpoint.strip().rstrip("/")
    if not stripped:
        raise ConfigError("AZURE_OPENAI_ENDPOINT is required for Azure OpenAI workflows.")
    parsed = urlparse(stripped)
    if parsed.scheme != "https":
        raise ConfigError("Azure OpenAI endpoint must use HTTPS.")
    if not parsed.hostname:
        raise ConfigError("Azure OpenAI endpoint must include a hostname.")
    if parsed.query or parsed.fragment:
        raise ConfigError("Azure OpenAI endpoint must not include a query string or fragment.")
    if parsed.path.startswith("/api/projects/") or parsed.path.startswith("/openai/v1"):
        raise ConfigError("Azure OpenAI endpoint must point at the resource root, not a sub-path.")
    if parsed.path not in {"", "/"}:
        raise ConfigError("Azure OpenAI endpoint must not include a non-root API path.")
    if parsed.params:
        raise ConfigError("Azure OpenAI endpoint must not include path parameters.")
    return f"{parsed.scheme}://{parsed.netloc}"


def build_azure_openai_client(settings: Settings) -> Any:
    """Create an AzureOpenAI SDK client from validated settings."""

    endpoint = getattr(settings, "azure_openai_endpoint", None)
    api_key = getattr(settings, "azure_openai_api_key", None)
    api_version = getattr(settings, "azure_openai_api_version", None)
    if not endpoint:
        raise ConfigError("AZURE_OPENAI_ENDPOINT is required for Azure OpenAI workflows.")
    if not api_key:
        raise ConfigError("AZURE_OPENAI_API_KEY is required for Azure OpenAI workflows.")
    if not api_version:
        raise ConfigError("AZURE_OPENAI_API_VERSION is required for Azure OpenAI workflows.")

    from openai import AzureOpenAI

    return AzureOpenAI(
        api_key=api_key,
        azure_endpoint=normalize_azure_endpoint(endpoint),
        api_version=api_version,
        timeout=settings.azure_openai_request_timeout_seconds,
        max_retries=settings.azure_openai_max_retries,
    )
