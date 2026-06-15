"""Optional LLM client wrappers for structured MARAG decisions."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from multi_agentic_rag.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    """Provider-neutral structured decision client."""

    provider: str

    def parse(self, *, instructions: str, user_input: str, schema: type[T]) -> T: ...

    def check_ready(self) -> tuple[bool, str]: ...


class DisabledLLMClient:
    """No-op client used by default local mode."""

    provider = "none"

    def parse(self, *, instructions: str, user_input: str, schema: type[T]) -> T:
        _ = (instructions, user_input, schema)
        raise RuntimeError("LLM_PROVIDER=none; structured LLM decisions are disabled.")

    def check_ready(self) -> tuple[bool, str]:
        return True, "LLM provider is disabled for local/default mode."


class OpenAIResponsesClient:
    """OpenAI Responses API client for structured decisions."""

    provider = "openai"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def parse(self, *, instructions: str, user_input: str, schema: type[T]) -> T:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        response = client.responses.parse(
            model=self.settings.default_llm_model,
            instructions=instructions,
            input=user_input,
            text_format=schema,
        )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise RuntimeError("OpenAI response did not include parsed structured output.")
        return parsed

    def check_ready(self) -> tuple[bool, str]:
        if not self.settings.openai_api_key:
            return False, "OPENAI_API_KEY is required when LLM_PROVIDER=openai."
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.settings.openai_api_key)
            if not hasattr(client, "responses"):
                return False, "Installed OpenAI SDK does not expose Responses API."
        except Exception as exc:
            return False, str(exc)
        return True, f"OpenAI Responses client configured for {self.settings.default_llm_model}."


class AzureOpenAIResponsesClient(OpenAIResponsesClient):
    """Azure-compatible Responses client placeholder.

    The interface is intentionally the same as OpenAI. This path validates
    configuration now and can be extended with Azure-specific client wiring
    without touching agent nodes.
    """

    provider = "azure_openai"

    def parse(self, *, instructions: str, user_input: str, schema: type[T]) -> T:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            api_key=self.settings.azure_openai_api_key,
            azure_endpoint=self.settings.azure_openai_endpoint,
            api_version=self.settings.azure_openai_api_version,
        )
        response = client.responses.parse(
            model=self.settings.azure_openai_deployment,
            instructions=instructions,
            input=user_input,
            text_format=schema,
        )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise RuntimeError("Azure OpenAI response did not include parsed structured output.")
        return parsed

    def check_ready(self) -> tuple[bool, str]:
        missing = [
            name
            for name, value in (
                ("AZURE_OPENAI_ENDPOINT", self.settings.azure_openai_endpoint),
                ("AZURE_OPENAI_API_KEY", self.settings.azure_openai_api_key),
                ("AZURE_OPENAI_DEPLOYMENT", self.settings.azure_openai_deployment),
            )
            if not value
        ]
        if missing:
            return False, "Missing Azure OpenAI setting(s): " + ", ".join(missing)
        try:
            from openai import AzureOpenAI

            client = AzureOpenAI(
                api_key=self.settings.azure_openai_api_key,
                azure_endpoint=self.settings.azure_openai_endpoint,
                api_version=self.settings.azure_openai_api_version,
            )
            if not hasattr(client, "responses"):
                return False, "Installed OpenAI SDK does not expose Azure Responses API."
        except Exception as exc:
            return False, str(exc)
        return True, "Azure OpenAI Responses client is configured."


def select_llm_client(settings: Settings | None = None) -> LLMClient:
    """Select the configured LLM client."""

    settings = settings or get_settings()
    if settings.llm_provider == "none":
        return DisabledLLMClient()
    if settings.llm_provider == "openai":
        return OpenAIResponsesClient(settings)
    if settings.llm_provider == "azure_openai":
        return AzureOpenAIResponsesClient(settings)
    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")
