"""LangGraph workflow orchestration for high-level GraphRAG agents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

from multi_agentic_rag.agents.high_level import (
    AgentIngestDocument,
    AgentRetrieveAnswer,
    AgentUserStoryBuilder,
)
from multi_agentic_rag.domain import (
    AgentRunResult,
    AgentRunStatus,
    EvidenceBundle,
    QualityValidationReport,
    TaskIntent,
    TaskIntentType,
    WorkflowPlan,
    WorkflowRunRecord,
    WorkflowState,
    WorkflowStatus,
    WorkflowStepRecord,
)
from multi_agentic_rag.exceptions import MultiAgenticRagError
from multi_agentic_rag.llm import ReasoningClient
from multi_agentic_rag.utils.hashing import stable_id


class WorkflowAuditRepository(Protocol):
    """Audit repository contract used by the LangGraph runner."""

    async def begin_workflow_run(self, run: WorkflowRunRecord) -> None:
        """Persist a started workflow run."""

    async def finish_workflow_run(
        self,
        workflow_run_id: str,
        *,
        status: WorkflowStatus,
        intent_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Mark a workflow run finished."""

    async def record_workflow_step(self, step: WorkflowStepRecord) -> None:
        """Persist one workflow step."""


class IntentRouterAgent:
    """OpenAI-backed intent router with deterministic default merging."""

    def __init__(self, reasoning_client: ReasoningClient) -> None:
        self.reasoning_client = reasoning_client

    async def route(
        self,
        request: str,
        *,
        default_system: str | None,
        default_kb: str,
        default_version: str | None,
        default_documents: list[str],
    ) -> TaskIntent:
        """Route a request and recompute required missing slots."""

        intent = await self.reasoning_client.route_intent(
            request,
            defaults={
                "system": default_system,
                "kb": default_kb,
                "version": default_version,
                "documents": default_documents,
            },
        )
        if default_system and not intent.system:
            intent = intent.model_copy(update={"system": default_system})
        if default_kb and not intent.kb:
            intent = intent.model_copy(update={"kb": default_kb})
        if default_version and not intent.version:
            intent = intent.model_copy(update={"version": default_version})
        if default_documents and not intent.documents:
            intent = intent.model_copy(update={"documents": default_documents})
        return intent.model_copy(update={"missing_slots": _missing_slots(intent)})


class WorkflowPlannerAgent:
    """OpenAI-backed workflow planner."""

    def __init__(self, reasoning_client: ReasoningClient) -> None:
        self.reasoning_client = reasoning_client

    async def plan(self, intent: TaskIntent) -> WorkflowPlan:
        """Return a plan, falling back only when the model returns no steps."""

        plan = await self.reasoning_client.plan_workflow(intent)
        if plan.ordered_agents:
            return plan
        return default_workflow_plan(intent)


class FlowValidatorAgent:
    """Validate agent handoffs and mandatory outputs."""

    def validate(
        self,
        *,
        agent_name: str,
        intent: TaskIntent,
        result: AgentRunResult,
    ) -> QualityValidationReport:
        """Return a validation report for one completed agent step."""

        checks: dict[str, bool] = {"agent_completed": result.status == AgentRunStatus.SUCCEEDED}
        messages = list(result.messages)
        if result.status in {AgentRunStatus.FAILED, AgentRunStatus.BLOCKED}:
            return QualityValidationReport(status="failed", messages=messages, checks=checks)
        if agent_name == AgentRetrieveAnswer.name and result.status == AgentRunStatus.SUCCEEDED:
            checks["required_evidence"] = bool(result.evidence_ids)
        if agent_name == AgentUserStoryBuilder.name:
            checks["required_evidence"] = bool(result.evidence_ids)
            checks["required_artifacts"] = bool(result.artifact_paths)
        if agent_name == AgentIngestDocument.name:
            checks["ingest_result"] = "ingest_result" in result.payload
        if intent.intent_type == TaskIntentType.INGEST_THEN_BUILD_USER_STORIES:
            checks["composed_handoff"] = True
        status: Literal["passed", "failed"] = "passed" if all(checks.values()) else "failed"
        if status == "failed":
            messages.append(f"Flow validation failed after {agent_name}.")
        return QualityValidationReport(status=status, messages=messages, checks=checks)


class LangGraphWorkflowRunner:
    """LangGraph state machine for natural-language workflow execution."""

    def __init__(
        self,
        *,
        router: IntentRouterAgent,
        planner: WorkflowPlannerAgent,
        validator: FlowValidatorAgent | None = None,
        ingest_agent: AgentIngestDocument | None = None,
        answer_agent: AgentRetrieveAnswer | None = None,
        user_story_agent: AgentUserStoryBuilder | None = None,
        audit_repository: WorkflowAuditRepository | None = None,
    ) -> None:
        self.router = router
        self.planner = planner
        self.validator = validator or FlowValidatorAgent()
        self.ingest_agent = ingest_agent
        self.answer_agent = answer_agent
        self.user_story_agent = user_story_agent
        self.audit_repository = audit_repository

    async def run(
        self,
        request: str,
        *,
        system: str | None = None,
        kb: str = "default",
        version: str | None = None,
        documents: list[str] | None = None,
    ) -> WorkflowState:
        """Execute a natural-language task through LangGraph."""

        graph = self._build_graph()
        state = WorkflowState(
            workflow_run_id=stable_id(
                "workflow_run",
                request,
                system or "",
                kb,
                version or "",
                datetime.now(UTC).isoformat(),
            ),
            request=request,
            default_system=system,
            default_kb=kb,
            default_version=version,
            default_documents=documents or [],
        )
        result = await graph.ainvoke(state.model_dump(mode="json"))
        return WorkflowState.model_validate(result)

    def _build_graph(self) -> Any:
        from langgraph.graph import END, START, StateGraph

        graph = cast(Any, StateGraph)(dict)
        graph.add_node("route_intent", self._route_intent)
        graph.add_node("missing_slot_check", self._missing_slot_check)
        graph.add_node("plan_workflow", self._plan_workflow)
        graph.add_node("dispatch_agents", self._dispatch_agents)
        graph.add_node("final_response", self._final_response)
        graph.add_edge(START, "route_intent")
        graph.add_edge("route_intent", "missing_slot_check")
        graph.add_conditional_edges(
            "missing_slot_check",
            _route_after_missing_slot_check,
            {"plan": "plan_workflow", "final": "final_response"},
        )
        graph.add_edge("plan_workflow", "dispatch_agents")
        graph.add_edge("dispatch_agents", "final_response")
        graph.add_edge("final_response", END)
        return graph.compile()

    async def _route_intent(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = WorkflowState.model_validate(raw_state)
        if self.audit_repository:
            await self.audit_repository.begin_workflow_run(
                WorkflowRunRecord(
                    workflow_run_id=state.workflow_run_id,
                    system_name=state.default_system,
                    kb_name=state.default_kb,
                    version=state.default_version,
                    request=state.request,
                    status=WorkflowStatus.STARTED,
                )
            )
        try:
            intent = await self.router.route(
                state.request,
                default_system=state.default_system,
                default_kb=state.default_kb,
                default_version=state.default_version,
                default_documents=state.default_documents,
            )
        except MultiAgenticRagError as exc:
            state.status = WorkflowStatus.FAILED
            state.errors.append(str(exc))
            state.current_step = "intent_route"
            return state.model_dump(mode="json")
        state.intent = intent
        state.current_step = "intent_route"
        return state.model_dump(mode="json")

    async def _missing_slot_check(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = WorkflowState.model_validate(raw_state)
        if state.intent and state.intent.missing_slots:
            state.status = WorkflowStatus.BLOCKED
            state.errors.extend(
                f"Missing required slot: {slot}" for slot in state.intent.missing_slots
            )
        state.current_step = "missing_slot_check"
        return state.model_dump(mode="json")

    async def _plan_workflow(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = WorkflowState.model_validate(raw_state)
        if state.intent is None:
            state.status = WorkflowStatus.FAILED
            state.errors.append("Intent routing did not produce an intent.")
            return state.model_dump(mode="json")
        try:
            state.plan = await self.planner.plan(state.intent)
        except MultiAgenticRagError as exc:
            state.status = WorkflowStatus.FAILED
            state.errors.append(str(exc))
            state.current_step = "workflow_plan"
            return state.model_dump(mode="json")
        state.selected_agents = list(state.plan.ordered_agents)
        state.current_step = "workflow_plan"
        return state.model_dump(mode="json")

    async def _dispatch_agents(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = WorkflowState.model_validate(raw_state)
        if state.errors:
            state.current_step = "agent_dispatch"
            return state.model_dump(mode="json")
        if state.intent is None or state.plan is None:
            state.status = WorkflowStatus.FAILED
            state.errors.append("Workflow dispatch requires intent and plan.")
            return state.model_dump(mode="json")
        for index, agent_name in enumerate(state.plan.ordered_agents, start=1):
            result = await self._run_agent(agent_name, state.intent, state.request)
            state.agent_results.append(result)
            _extend_state_from_result(state, result)
            validation = self.validator.validate(
                agent_name=_canonical_agent_name(agent_name),
                intent=state.intent,
                result=result,
            )
            state.validation_reports.append(validation)
            if self.audit_repository:
                await self.audit_repository.record_workflow_step(
                    WorkflowStepRecord(
                        workflow_step_id=stable_id(
                            "workflow_step",
                            state.workflow_run_id,
                            index,
                            agent_name,
                        ),
                        workflow_run_id=state.workflow_run_id,
                        step_index=index,
                        agent_name=_canonical_agent_name(agent_name),
                        status=result.status,
                        ended_at=datetime.now(UTC),
                        messages=result.messages,
                        evidence_ids=result.evidence_ids,
                        artifact_paths=result.artifact_paths,
                        error_message="; ".join(result.messages)
                        if result.status
                        in {AgentRunStatus.FAILED, AgentRunStatus.BLOCKED}
                        else None,
                    )
                )
            if validation.status == "failed":
                state.status = WorkflowStatus.FAILED
                state.errors.extend(validation.messages)
                break
        if not state.errors and state.status == WorkflowStatus.STARTED:
            state.status = WorkflowStatus.SUCCEEDED
        state.current_step = "agent_dispatch"
        return state.model_dump(mode="json")

    async def _final_response(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = WorkflowState.model_validate(raw_state)
        if state.errors:
            state.final_response = "\n".join(state.errors)
        elif state.agent_results:
            state.final_response = "\n".join(
                message
                for result in state.agent_results
                for message in result.messages
                if message
            )
        else:
            state.final_response = "No workflow action was performed."
        if self.audit_repository:
            await self.audit_repository.finish_workflow_run(
                state.workflow_run_id,
                status=state.status,
                intent_type=state.intent.intent_type.value if state.intent else None,
                error_message="\n".join(state.errors) if state.errors else None,
            )
        state.current_step = "final_response"
        return state.model_dump(mode="json")

    async def _run_agent(
        self,
        agent_name: str,
        intent: TaskIntent,
        request: str,
    ) -> AgentRunResult:
        canonical = _canonical_agent_name(agent_name)
        if canonical == AgentIngestDocument.name and self.ingest_agent:
            return await self.ingest_agent.run(intent)
        if canonical == AgentRetrieveAnswer.name and self.answer_agent:
            return await self.answer_agent.run(intent, question=request)
        if canonical == AgentUserStoryBuilder.name and self.user_story_agent:
            return await self.user_story_agent.run(intent)
        return AgentRunResult(
            status=AgentRunStatus.BLOCKED,
            messages=[f"{canonical} is not implemented in this runtime."],
        )


def default_workflow_plan(intent: TaskIntent) -> WorkflowPlan:
    """Return a deterministic implemented-agent plan for an intent."""

    mapping = {
        TaskIntentType.ANSWER_QUERY: [AgentRetrieveAnswer.name],
        TaskIntentType.INGEST_DOCUMENT: [AgentIngestDocument.name],
        TaskIntentType.BUILD_USER_STORIES: [AgentUserStoryBuilder.name],
        TaskIntentType.INGEST_THEN_BUILD_USER_STORIES: [
            AgentIngestDocument.name,
            AgentUserStoryBuilder.name,
        ],
    }
    agents = mapping.get(intent.intent_type, [])
    return WorkflowPlan(
        ordered_agents=agents,
        required_tools=["retrieval.hybrid", "evidence.validate"],
        expected_outputs=[intent.intent_type.value],
        stop_conditions=["failed_validation", "missing_required_slot"],
    )


def _missing_slots(intent: TaskIntent) -> list[str]:
    missing: list[str] = []
    if not intent.system:
        missing.append("system")
    if intent.intent_type in {
        TaskIntentType.INGEST_DOCUMENT,
        TaskIntentType.INGEST_THEN_BUILD_USER_STORIES,
    }:
        if not intent.documents:
            missing.append("document")
        if not intent.version:
            missing.append("version")
    if intent.intent_type == TaskIntentType.BUILD_USER_STORIES and not intent.version:
        missing.append("version")
    return missing


def _route_after_missing_slot_check(raw_state: dict[str, Any]) -> str:
    state = WorkflowState.model_validate(raw_state)
    return "final" if state.errors else "plan"


def _canonical_agent_name(agent_name: str) -> str:
    normalized = agent_name.strip()
    prefix = normalized.split(":", 1)[0].strip()
    implemented = {
        AgentIngestDocument.name,
        AgentRetrieveAnswer.name,
        AgentUserStoryBuilder.name,
    }
    if prefix in implemented:
        return prefix
    if normalized in implemented:
        return normalized
    aliases = {
        "ingest_document": AgentIngestDocument.name,
        "answer_query": AgentRetrieveAnswer.name,
        "retrieve_answer": AgentRetrieveAnswer.name,
        "build_user_stories": AgentUserStoryBuilder.name,
        "user_story_builder": AgentUserStoryBuilder.name,
    }
    lowered = prefix.lower()
    if lowered in aliases:
        return aliases[lowered]
    for candidate in implemented:
        if candidate.lower() in normalized.lower():
            return candidate
    return normalized


def _extend_state_from_result(state: WorkflowState, result: AgentRunResult) -> None:
    evidence_payload = result.payload.get("evidence_bundle")
    if evidence_payload:
        state.evidence_bundles.append(EvidenceBundle.model_validate(evidence_payload))
    for artifact in result.payload.get("artifacts", []):
        from multi_agentic_rag.domain import ArtifactManifest

        state.artifacts.append(ArtifactManifest.model_validate(artifact))
