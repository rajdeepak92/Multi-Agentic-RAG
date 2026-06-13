"""Service-backed LangGraph workflow nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from multi_agentic_rag.agents.state import AgentStateDict
from multi_agentic_rag.config import get_settings
from multi_agentic_rag.coverage import DEFAULT_SCENARIO_COUNT, plan_requirement_coverage
from multi_agentic_rag.ingestion import ingest_document as ingest_document_service
from multi_agentic_rag.models import TaskResult
from multi_agentic_rag.retrieval import answer_query
from multi_agentic_rag.testing import (
    DEFAULT_OUTPUT_DIR,
    generate_testcases,
    get_last_test_result,
    run_testcases,
)


def route_input(state: AgentStateDict) -> AgentStateDict:
    """Route initial input into a supported MARAG workflow."""

    _trace(state, "IntentRouterAgent", "started")
    if state.get("input_type"):
        _trace(state, "IntentRouterAgent", "completed")
        return state

    text = (state.get("user_query") or "").lower()
    if state.get("source_path"):
        state["input_type"] = "ingest_document"
    elif _wants_last_result(text):
        state["input_type"] = "last_result"
    elif _wants_run(text):
        state["input_type"] = "run_generated_tests"
    elif _wants_test_generation(text):
        state["input_type"] = "generate_tests"
    elif _wants_coverage_generation(text):
        state["input_type"] = "update_coverage"
    elif state.get("user_query"):
        state["input_type"] = "ask_question"
    else:
        state["input_type"] = "unknown"
        state.setdefault("errors", []).append("No supported MARAG input was provided.")
    _trace(state, "IntentRouterAgent", "completed", intent=state.get("input_type"))
    return state


def ingest_document(state: AgentStateDict) -> AgentStateDict:
    """Ingest a document when the workflow intent requests ingestion."""

    if state.get("input_type") != "ingest_document":
        return state
    _trace(state, "IngestionAgent", "started")
    source_path = state.get("source_path")
    system_name = state.get("system_name")
    version = state.get("version")
    if not source_path:
        return _error(state, "IngestionAgent", "No document path -> no ingestion.")
    if not system_name or not version:
        return _error(state, "IngestionAgent", "System name and version are required.")
    try:
        result = ingest_document_service(
            source_path,
            system_name=system_name,
            version=version,
            settings=_settings(state),
        )
    except Exception as exc:
        return _error(state, "IngestionAgent", str(exc))
    state["ingest_result"] = result.model_dump(mode="json")
    state["documents"] = [result.document.model_dump(mode="json")]
    _trace(state, "IngestionAgent", "completed")
    return state


def build_graph(state: AgentStateDict) -> AgentStateDict:
    """Record graph-build handoff state.

    Graph writes are performed by ingestion when Neo4j is configured. This node
    exists so the workflow trace has an explicit graph-builder boundary.
    """

    if state.get("input_type") == "ingest_document":
        ingest_result = state.get("ingest_result") or {}
        _trace(
            state,
            "GraphBuilderAgent",
            "completed",
            neo4j_available=ingest_result.get("neo4j_available"),
        )
    return state


def compute_delta(state: AgentStateDict) -> AgentStateDict:
    """Record delta handoff state.

    Deterministic delta calculation is performed during ingestion.
    """

    if state.get("input_type") == "ingest_document":
        ingest_result = state.get("ingest_result") or {}
        _trace(
            state,
            "DeltaAgent",
            "completed",
            deltas_created=ingest_result.get("deltas_created"),
        )
    return state


def route_query(state: AgentStateDict) -> AgentStateDict:
    """Preserve backward-compatible query routing for direct query states."""

    if state.get("input_type") == "ask_question":
        _trace(state, "RetrievalRouterAgent", "completed")
    return state


def retrieve_context(state: AgentStateDict) -> AgentStateDict:
    """Collect evidence or coverage context for downstream workflow steps."""

    input_type = state.get("input_type")
    if input_type == "ask_question":
        return _retrieve_query_context(state)
    if input_type in {"generate_tests", "run_generated_tests", "update_coverage"}:
        return _retrieve_coverage_context(state)
    return state


def verify_evidence(state: AgentStateDict) -> AgentStateDict:
    """Reject outputs that do not have required evidence."""

    input_type = state.get("input_type")
    _trace(state, "EvidenceVerifierAgent", "started")
    if input_type == "ask_question" and not state.get("retrieved_context"):
        state.setdefault("errors", []).append("No evidence available for output generation.")
    if input_type in {"generate_tests", "run_generated_tests", "update_coverage"} and not state.get(
        "coverage_records"
    ):
        state.setdefault("errors", []).append(
            "No requirement evidence found. No coverage claim can be made."
        )
    _trace(state, "EvidenceVerifierAgent", "completed")
    return state


def generate_output(state: AgentStateDict) -> AgentStateDict:
    """Run the selected terminal workflow action and assemble a TaskResult."""

    input_type = state.get("input_type")
    if state.get("errors"):
        task_result = TaskResult(
            supported=False,
            intent=input_type or "unknown",
            message="; ".join(state.get("errors") or []),
            warnings=state.get("errors") or [],
        )
        state["task_result"] = task_result.model_dump(mode="json")
        state["final_output"] = state["task_result"]
        return state

    if input_type == "ingest_document":
        message = "Document ingestion completed."
        task_result = TaskResult(supported=True, intent=input_type, message=message)
    elif input_type == "ask_question":
        query = state.get("query_result") or {}
        task_result = TaskResult.model_validate(
            {
                "supported": bool(query.get("supported")),
                "intent": "query",
                "message": query.get("answer", ""),
                "query": query,
                "warnings": query.get("warnings", []),
            }
        )
    elif input_type == "update_coverage":
        coverage = state.get("coverage_result") or {}
        task_result = TaskResult.model_validate(
            {
                "supported": bool(coverage.get("supported")),
                "intent": "generate_coverage",
                "message": coverage.get("message", ""),
                "coverage": coverage,
                "warnings": coverage.get("warnings", []),
            }
        )
    elif input_type == "generate_tests":
        task_result = _generate_tests(state)
    elif input_type == "run_generated_tests":
        task_result = _run_tests(state)
    elif input_type == "last_result":
        task_result = _last_result(state)
    else:
        task_result = TaskResult(
            supported=False,
            intent=input_type or "unknown",
            message="Unsupported MARAG task.",
        )
    state["task_result"] = task_result.model_dump(mode="json")
    state["final_output"] = state["task_result"]
    _trace(state, "ReportGeneratorAgent", "completed", intent=task_result.intent)
    return state


def _retrieve_query_context(state: AgentStateDict) -> AgentStateDict:
    _trace(state, "EvidenceCollectorAgent", "started")
    query = state.get("user_query") or ""
    result = answer_query(
        query,
        system_name=state.get("system_name"),
        version=state.get("version"),
        settings=_settings(state),
    )
    state["query_result"] = result.model_dump(mode="json")
    state["retrieved_context"] = [item.model_dump(mode="json") for item in result.evidence]
    _trace(state, "EvidenceCollectorAgent", "completed", supported=result.supported)
    return state


def _retrieve_coverage_context(state: AgentStateDict) -> AgentStateDict:
    _trace(state, "ScenarioSelectionAgent", "started")
    system_name = state.get("system_name")
    if not system_name:
        return _error(state, "ScenarioSelectionAgent", "A system name is required.")
    result = plan_requirement_coverage(
        system_name=system_name,
        version=state.get("version"),
        scenario_count=state.get("scenario_count") or DEFAULT_SCENARIO_COUNT,
        settings=_settings(state),
    )
    state["coverage_result"] = result.model_dump(mode="json")
    state["coverage_records"] = [record.model_dump(mode="json") for record in result.records]
    _trace(state, "ScenarioSelectionAgent", "completed", supported=result.supported)
    return state


def _generate_tests(state: AgentStateDict) -> TaskResult:
    _trace(state, "TestWriterAgent", "started")
    result = generate_testcases(
        system_name=state["system_name"] or "",
        version=state.get("version"),
        scenario_count=state.get("scenario_count") or DEFAULT_SCENARIO_COUNT,
        output_dir=state.get("output_dir") or DEFAULT_OUTPUT_DIR,
        settings=_settings(state),
    )
    state["test_generation"] = result.model_dump(mode="json")
    _trace(state, "TestWriterAgent", "completed", supported=result.supported)
    return TaskResult(
        supported=result.supported,
        intent="generate_testcases",
        message=result.message,
        coverage=result.coverage,
        test_generation=result,
        warnings=result.warnings,
    )


def _run_tests(state: AgentStateDict) -> TaskResult:
    _trace(state, "TestExecutionAgent", "started")
    result = run_testcases(
        system_name=state["system_name"] or "",
        version=state.get("version"),
        scenario_count=state.get("scenario_count") or DEFAULT_SCENARIO_COUNT,
        output_dir=state.get("output_dir") or DEFAULT_OUTPUT_DIR,
        settings=_settings(state),
    )
    state["test_execution"] = result.model_dump(mode="json")
    _trace(
        state,
        "FailureClassifierAgent",
        "completed",
        result_status=result.result.status if result.result else None,
    )
    return TaskResult(
        supported=result.supported,
        intent="run_testcases",
        message=result.message,
        test_execution=result,
        warnings=result.warnings,
    )


def _last_result(state: AgentStateDict) -> TaskResult:
    result = get_last_test_result(
        system_name=state["system_name"] or "",
        version=state.get("version"),
        settings=_settings(state),
    )
    state["test_execution"] = result.model_dump(mode="json")
    return TaskResult(
        supported=result.supported,
        intent="last_result",
        message=result.message,
        test_execution=result,
        last_result=result.result,
        warnings=result.warnings,
    )


def _wants_last_result(text: str) -> bool:
    return any(phrase in text for phrase in ("last result", "previous result", "show result"))


def _wants_run(text: str) -> bool:
    run_words = ("run", "rerun", "re-run", "execute")
    test_words = ("test", "testcase", "test case", "pytest")
    return any(word in text for word in run_words) and any(word in text for word in test_words)


def _wants_test_generation(text: str) -> bool:
    action_words = ("generate", "write", "create")
    test_words = ("testcase", "test case", "pytest", "test file")
    return any(word in text for word in action_words) and any(word in text for word in test_words)


def _wants_coverage_generation(text: str) -> bool:
    action_words = ("generate", "create", "write")
    coverage_words = ("coverage", "scenario", "scenarios")
    return any(word in text for word in action_words) and any(
        word in text for word in coverage_words
    )


def _trace(state: AgentStateDict, node: str, status: str, **metadata: Any) -> None:
    state.setdefault("workflow_trace", []).append(
        {"node": node, "status": status, "metadata": metadata}
    )


def _settings(state: AgentStateDict):
    return state.get("_settings") or get_settings()


def _error(state: AgentStateDict, node: str, message: str) -> AgentStateDict:
    state.setdefault("errors", []).append(message)
    _trace(state, node, "failed", error=message)
    return state
