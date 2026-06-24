"""Public user-story generation agent backed by a compiled LangGraph workflow."""

from __future__ import annotations

from multi_agentic_rag.agents.user_stories.graph import (
    UserStoryGraphRuntime,
    build_user_story_graph,
)
from multi_agentic_rag.agents.user_stories.schemas import (
    UserStoryGenerationRequest,
    UserStoryGenerationResult,
)
from multi_agentic_rag.exceptions import (
    GenerationTokenLimitError,
    MultiAgenticRagError,
    StructuredGenerationError,
    UserStoryGenerationError,
    UserStoryQualityError,
)

_USER_STORY_ERROR_TYPES: dict[str, type[UserStoryGenerationError]] = {
    "GenerationTokenLimitError": GenerationTokenLimitError,
    "StructuredGenerationError": StructuredGenerationError,
    "UserStoryGenerationError": UserStoryGenerationError,
    "UserStoryQualityError": UserStoryQualityError,
}


class UserStoryGenerationAgent:
    """High-level agent that generates evidence-grounded enterprise user stories."""

    def __init__(self, runtime: UserStoryGraphRuntime) -> None:
        self.runtime = runtime
        self.graph = build_user_story_graph(runtime)

    async def run(self, request: UserStoryGenerationRequest) -> UserStoryGenerationResult:
        """Execute user-story generation through the compiled StateGraph."""

        state = await self.graph.ainvoke({"request": request})
        result = UserStoryGenerationResult.model_validate(state.get("result"))
        if result.status == "failed":
            detail = "; ".join(result.messages) or "User-story generation failed."
            failure_type = state.get("failure_error_type")
            if isinstance(failure_type, str) and failure_type in _USER_STORY_ERROR_TYPES:
                raise _USER_STORY_ERROR_TYPES[failure_type](detail)
            raise MultiAgenticRagError(detail)
        return result
