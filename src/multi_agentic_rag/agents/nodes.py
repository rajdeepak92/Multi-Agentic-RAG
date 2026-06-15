"""Service-backed LangGraph workflow nodes."""

from __future__ import annotations

from pathlib import Path
import py_compile
import re
from typing import Any

from multi_agentic_rag.agents.state import AgentStateDict
from multi_agentic_rag.config import get_settings
from multi_agentic_rag.coverage import DEFAULT_SCENARIO_COUNT, plan_requirement_coverage
from multi_agentic_rag.ingestion import ingest_document as ingest_document_service
from multi_agentic_rag.llm import IntentDecision, select_llm_client
from multi_agentic_rag.models import (
    AutomationTaskResult,
    ExecutionSummary,
    GeneratedArtifacts,
    TaskResult,
)
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
        _normalize_execution_mode(state)
        state["intent"] = state.get("input_type")
        state["execution_plan"] = {
            "intent": state.get("input_type"),
            "system_name": state.get("system_name"),
            "version": state.get("version"),
            "scenario_count": state.get("scenario_count"),
            "execution_mode": state.get("execution_mode"),
        }
        _handoff(state, "IntentRouterAgent", "DocumentResolverAgent", "explicit input_type provided")
        _trace(state, "IntentRouterAgent", "completed")
        return state

    request_text = state.get("user_query") or ""
    text = request_text.lower()
    requested_count = _extract_scenario_count(request_text)
    if requested_count:
        state["scenario_count"] = requested_count
    if _wants_force_run_all(text):
        state["force_run_all"] = True
    if _wants_mock(text):
        state["execution_mode"] = "mock"

    llm_decision = _llm_intent_decision(state, request_text)
    if llm_decision:
        _apply_intent_decision(state, llm_decision)
        if state.get("input_type"):
            _trace(
                state,
                "IntentRouterAgent",
                "completed",
                intent=state.get("input_type"),
                router="llm_with_python_fallback",
            )
            _handoff(
                state,
                "IntentRouterAgent",
                "DocumentResolverAgent",
                f"LLM selected {state.get('input_type')}",
            )
            return state
    elif _llm_routing_required(state) and request_text:
        state["input_type"] = "unknown"
        state.setdefault("errors", []).append(
            "Target GraphRAG task routing requires a structured LLM decision. "
            "Set LLM_PROVIDER=openai and configure OPENAI_API_KEY, or use an explicit CLI/API command."
        )
        _trace(state, "IntentRouterAgent", "failed", reason="llm_required")
        _handoff(state, "IntentRouterAgent", "DocumentResolverAgent", "LLM routing required")
        return state

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
    _normalize_execution_mode(state)
    state["intent"] = state.get("input_type")
    state["execution_plan"] = {
        "intent": state.get("input_type"),
        "system_name": state.get("system_name"),
        "version": state.get("version"),
        "scenario_count": state.get("scenario_count"),
        "execution_mode": state.get("execution_mode"),
    }
    _trace(
        state,
        "IntentRouterAgent",
        "completed",
        intent=state.get("input_type"),
        execution_mode=state.get("execution_mode"),
    )
    _handoff(
        state,
        "IntentRouterAgent",
        "DocumentResolverAgent",
        f"deterministic route selected {state.get('input_type')}",
    )
    return state


def document_resolver(state: AgentStateDict) -> AgentStateDict:
    """Validate document, system, version, and execution-mode routing inputs."""

    _trace(state, "DocumentResolverAgent", "started")
    input_type = state.get("input_type")
    if input_type in {
        "ask_question",
        "update_coverage",
        "generate_tests",
        "run_generated_tests",
        "last_result",
    } and not state.get("system_name"):
        return _error(state, "DocumentResolverAgent", "A system name is required.")
    if input_type == "ingest_document":
        if not state.get("source_path"):
            return _error(state, "DocumentResolverAgent", "A document path is required.")
        if not state.get("system_name") or not state.get("version"):
            return _error(
                state,
                "DocumentResolverAgent",
                "System name and version are required for ingestion.",
            )
    mode = _normalize_execution_mode(state)
    _trace(
        state,
        "DocumentResolverAgent",
        "completed",
        intent=input_type,
        system_name=state.get("system_name"),
        version=state.get("version"),
        execution_mode=mode,
    )
    _handoff(
        state,
        "DocumentResolverAgent",
        "IngestionAgent" if input_type == "ingest_document" else "VersionDeltaAgent",
        "document and execution context resolved",
    )
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
    _handoff(state, "IngestionAgent", "GraphBuilderAgent", "document ingestion completed")
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
        _handoff(state, "GraphBuilderAgent", "VersionDeltaAgent", "graph indexing status recorded")
    return state


def version_delta(state: AgentStateDict) -> AgentStateDict:
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
        _handoff(state, "VersionDeltaAgent", "RetrievalRouterAgent", "version delta status recorded")
    elif state.get("input_type") in {
        "ask_question",
        "update_coverage",
        "generate_tests",
        "run_generated_tests",
    }:
        _trace(
            state,
            "VersionDeltaAgent",
            "completed",
            version=state.get("version"),
        )
        _handoff(state, "VersionDeltaAgent", "RetrievalRouterAgent", "version context resolved")
    return state


def compute_delta(state: AgentStateDict) -> AgentStateDict:
    """Backward-compatible alias for the previous coarse node name."""

    return version_delta(state)


def route_query(state: AgentStateDict) -> AgentStateDict:
    """Preserve backward-compatible query routing for direct query states."""

    if state.get("input_type") == "ask_question":
        _trace(state, "RetrievalRouterAgent", "completed")
        _handoff(state, "RetrievalRouterAgent", "GraphRetrievalAgent", "query route selected")
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
    _handoff(state, "EvidenceVerifierAgent", "DomainAnalyzerAgent", "evidence gate evaluated")
    return state


def domain_analyzer(state: AgentStateDict) -> AgentStateDict:
    """Summarize domain and protocol clues before automation planning."""

    input_type = state.get("input_type")
    if input_type not in {"generate_tests", "run_generated_tests", "update_coverage"}:
        return state
    coverage_records = state.get("coverage_records") or []
    evidence_text = " ".join(
        " ".join(record.get("evidence", [])) for record in coverage_records
    )
    protocols = _protocols_for_text(evidence_text)
    state["domain_analysis"] = {
        "protocols": protocols,
        "domain": _domain_for_protocols(protocols),
        "coverage_record_count": len(coverage_records),
    }
    _trace(
        state,
        "DomainAnalyzerAgent",
        "completed",
        protocols=protocols,
        domain=state["domain_analysis"]["domain"],
    )
    _handoff(state, "DomainAnalyzerAgent", "DependencyAuditAgent", "domain clues summarized")
    return state


def dependency_audit(state: AgentStateDict) -> AgentStateDict:
    """Record the execution-mode handoff before Python writes or runs tests."""

    if state.get("input_type") not in {"generate_tests", "run_generated_tests"}:
        return state
    settings = _settings_with_execution_mode(state)
    mode = settings.generated_test_execution_mode
    state["dependency_audit"] = {
        "agent": "DependencyAuditAgent",
        "execution_mode": mode,
        "mock_mode": mode == "mock",
        "status": "pending_test_generation",
        "mutation_allowed": False,
    }
    state["missing_dependencies"] = []
    _trace(state, "DependencyAuditAgent", "completed", execution_mode=mode)
    _handoff(
        state,
        "DependencyAuditAgent",
        "TestHarnessAgent",
        f"execution mode resolved as {mode}",
    )
    return state


def test_harness(state: AgentStateDict) -> AgentStateDict:
    """Expose the harness boundary before generated files are written."""

    if state.get("input_type") not in {"generate_tests", "run_generated_tests"}:
        return state
    state["test_harness"] = {
        "pytest_ini": "generated harness",
        "conftest": "generated harness",
        "robot_wrapper": "generated wrapper",
    }
    _trace(state, "TestHarnessAgent", "completed")
    _handoff(state, "TestHarnessAgent", "TestWriterAgent", "harness contract selected")
    return state


def test_writer(state: AgentStateDict) -> AgentStateDict:
    """Write generated testcase artifacts for generation requests."""

    if state.get("input_type") != "generate_tests" or state.get("errors"):
        return state
    task_result = _generate_tests(state)
    state["task_result"] = task_result.model_dump(mode="json")
    _handoff(state, "TestWriterAgent", "RobotMappingAgent", "pytest/json/robot artifacts written")
    return state


def robot_mapping(state: AgentStateDict) -> AgentStateDict:
    """Validate that Robot mapping output is present when tests were generated."""

    if state.get("input_type") not in {"generate_tests", "run_generated_tests"}:
        return state
    robot_file = _robot_file_path_from_state(state)
    status = "present" if robot_file and robot_file.exists() else "pending_execution_generation"
    state["robot_mapping"] = {
        "status": status,
        "robot_file": str(robot_file) if robot_file else "",
    }
    _trace(state, "RobotMappingAgent", "completed", result_status=status)
    _handoff(state, "RobotMappingAgent", "SyntaxValidationAgent", "robot mapping checked")
    return state


def syntax_validation(state: AgentStateDict) -> AgentStateDict:
    """Compile generated Python artifacts before reporting generation success."""

    if state.get("input_type") != "generate_tests" or state.get("errors"):
        return state
    test_file = _test_file_path_from_state(state)
    if not test_file:
        state["syntax_validation"] = {"status": "missing", "message": "No generated pytest file."}
        return _error(state, "SyntaxValidationAgent", "No generated pytest file.")
    try:
        py_compile.compile(str(test_file), doraise=True)
    except py_compile.PyCompileError as exc:
        state["syntax_validation"] = {"status": "failed", "message": str(exc)}
        return _error(state, "SyntaxValidationAgent", str(exc))
    state["syntax_validation"] = {"status": "passed", "file": str(test_file)}
    _trace(state, "SyntaxValidationAgent", "completed", result_status="passed", file=str(test_file))
    _handoff(state, "SyntaxValidationAgent", "TestExecutionAgent", "generated Python syntax passed")
    return state


def test_execution(state: AgentStateDict) -> AgentStateDict:
    """Execute or retrieve generated test results for execution requests."""

    if state.get("errors"):
        return state
    if state.get("input_type") == "run_generated_tests":
        task_result = _run_tests(state)
        state["task_result"] = task_result.model_dump(mode="json")
        _handoff(state, "TestExecutionAgent", "FailureClassifierAgent", "pytest execution completed")
    elif state.get("input_type") == "last_result":
        task_result = _last_result(state)
        state["task_result"] = task_result.model_dump(mode="json")
        _handoff(state, "TestExecutionAgent", "FailureClassifierAgent", "last result loaded")
    return state


def failure_classifier(state: AgentStateDict) -> AgentStateDict:
    """Summarize execution failure category for downstream reporting."""

    execution = state.get("test_execution") or {}
    result = execution.get("result") or {}
    if result:
        state["failure_classification"] = {
            "status": result.get("status"),
            "failure_category": result.get("failure_category"),
            "failure_reason": result.get("failure_reason"),
        }
        _trace(
            state,
            "FailureClassifierAgent",
            "completed",
            result_status=result.get("status"),
            failure_category=result.get("failure_category"),
        )
        _handoff(state, "FailureClassifierAgent", "JsonSidecarAgent", "execution classified")
    return state


def json_sidecar(state: AgentStateDict) -> AgentStateDict:
    """Validate generated JSON sidecar presence and schema after writes/runs."""

    if state.get("input_type") not in {"generate_tests", "run_generated_tests", "last_result"}:
        return state
    sidecar = _tracking_file_path_from_state(state)
    if not sidecar or not sidecar.exists():
        state["sidecar_status"] = {"status": "missing", "path": str(sidecar) if sidecar else ""}
        _trace(state, "JsonSidecarAgent", "completed", result_status="missing")
        return state
    state["sidecar_status"] = {
        "status": "present",
        "path": str(sidecar),
    }
    _trace(state, "JsonSidecarAgent", "completed", result_status="present", path=str(sidecar))
    _handoff(state, "JsonSidecarAgent", "DatabaseUpdateAgent", "sidecar checked")
    return state


def database_update(state: AgentStateDict) -> AgentStateDict:
    """Summarize SQLite/graph write status after generation or execution."""

    if state.get("input_type") not in {"generate_tests", "run_generated_tests", "last_result"}:
        return state
    status = "not_updated"
    if state.get("test_execution", {}).get("result"):
        status = "test_run_result_record_written"
    elif state.get("test_generation", {}).get("test_file"):
        status = "generated_test_file_record_written"
    state["db_update_status"] = status
    _trace(state, "DatabaseUpdateAgent", "completed", result_status=status)
    _handoff(state, "DatabaseUpdateAgent", "ReportGeneratorAgent", "database status summarized")
    return state


def report_generator(state: AgentStateDict) -> AgentStateDict:
    """Build a lightweight report summary before final validation."""

    if state.get("input_type") not in {
        "ask_question",
        "update_coverage",
        "generate_tests",
        "run_generated_tests",
        "last_result",
    }:
        return state
    state["report_summary"] = {
        "intent": state.get("input_type"),
        "sidecar_status": (state.get("sidecar_status") or {}).get("status", ""),
        "db_update_status": state.get("db_update_status") or "",
        "warnings": state.get("warnings") or [],
        "errors": state.get("errors") or [],
    }
    _trace(state, "ReportGeneratorAgent", "completed", intent=state.get("input_type"))
    _handoff(state, "ReportGeneratorAgent", "FinalRouterValidationAgent", "report summary built")
    return state


def final_router_validation(state: AgentStateDict) -> AgentStateDict:
    """Validate that requested actions produced the required artifacts/results."""

    input_type = state.get("input_type")
    checks: list[str] = []
    missing: list[str] = []
    if input_type == "generate_tests":
        required = {
            "pytest_file": _test_file_path_from_state(state),
            "json_sidecar": _tracking_file_path_from_state(state),
            "robot_file": _robot_file_path_from_state(state),
        }
        for name, path in required.items():
            checks.append(name)
            if not path or not path.exists():
                missing.append(name)
    elif input_type == "run_generated_tests":
        checks.extend(["test_execution", "json_sidecar", "db_update"])
        if not state.get("test_execution", {}).get("result"):
            missing.append("test_execution")
        sidecar = _tracking_file_path_from_state(state)
        if not sidecar or not sidecar.exists():
            missing.append("json_sidecar")
        if state.get("db_update_status") != "test_run_result_record_written":
            missing.append("db_update")
    elif input_type == "ask_question":
        checks.append("query_result")
        if not state.get("query_result"):
            missing.append("query_result")
    state["final_validation"] = {
        "status": "failed" if missing else "passed",
        "checks": checks,
        "missing": missing,
    }
    if missing:
        state.setdefault("warnings", []).append(
            "Final validation missing: " + ", ".join(missing)
        )
    _trace(
        state,
        "FinalRouterValidationAgent",
        "completed",
        result_status=state["final_validation"]["status"],
        missing=missing,
    )
    _handoff(state, "FinalRouterValidationAgent", "OutputAssembler", "final validation complete")
    return state


def build_task_result(state: AgentStateDict) -> AgentStateDict:
    """Assemble a TaskResult from prior fine-grained node outputs."""

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
    if state.get("task_result"):
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
    else:
        task_result = TaskResult(
            supported=False,
            intent=input_type or "unknown",
            message="Unsupported MARAG task.",
        )
    state["task_result"] = task_result.model_dump(mode="json")
    state["final_output"] = state["task_result"]
    return state


def route_after_evidence(state: AgentStateDict) -> str:
    """Route after evidence verification."""

    next_node = "final_report" if state.get("errors") else "continue"
    state["next_node"] = next_node
    return next_node


def route_after_dependency_audit(state: AgentStateDict) -> str:
    """Route after dependency audit."""

    next_node = "blocked" if state.get("missing_dependencies") else "continue"
    state["next_node"] = next_node
    return next_node


def route_after_syntax_validation(state: AgentStateDict) -> str:
    """Route after generated-code syntax validation."""

    if state.get("errors") and state.get("retry_count", 0) < 1:
        state["retry_count"] = state.get("retry_count", 0) + 1
        next_node = "retry"
    else:
        next_node = "continue"
    state["next_node"] = next_node
    return next_node


def route_after_execution(state: AgentStateDict) -> str:
    """Route after pytest execution."""

    result = (state.get("test_execution") or {}).get("result") or {}
    if result.get("status") == "failed" and state.get("retry_count", 0) < 1:
        state["retry_count"] = state.get("retry_count", 0) + 1
        next_node = "retry"
    else:
        next_node = "continue"
    state["next_node"] = next_node
    return next_node


def generate_output(state: AgentStateDict) -> AgentStateDict:
    """Backward-compatible alias for the previous terminal node."""

    return build_task_result(state)


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
        force_run_all=bool(state.get("force_run_all")),
        output_dir=state.get("output_dir") or DEFAULT_OUTPUT_DIR,
        settings=_settings_with_execution_mode(state),
        execution_mode=state.get("execution_mode"),
    )
    state["test_generation"] = result.model_dump(mode="json")
    if result.test_file:
        paths = [result.test_file.file_path]
        paths.extend(result.test_file.harness_file_paths)
        if result.test_file.robot_file_path:
            paths.append(result.test_file.robot_file_path)
        state["generated_code_paths"] = paths
    _trace(state, "TestWriterAgent", "completed", supported=result.supported)
    return TaskResult(
        supported=result.supported,
        intent="generate_testcases",
        message=result.message,
        coverage=result.coverage,
        test_generation=result,
        automation=_automation_from_generation(state, result),
        warnings=[*(state.get("warnings") or []), *result.warnings],
    )


def _run_tests(state: AgentStateDict) -> TaskResult:
    _trace(state, "TestExecutionAgent", "started")
    result = run_testcases(
        system_name=state["system_name"] or "",
        version=state.get("version"),
        scenario_count=state.get("scenario_count") or DEFAULT_SCENARIO_COUNT,
        output_dir=state.get("output_dir") or DEFAULT_OUTPUT_DIR,
        settings=_settings_with_execution_mode(state),
        force_run_all=bool(state.get("force_run_all")),
        execution_mode=state.get("execution_mode"),
    )
    state["test_execution"] = result.model_dump(mode="json")
    if result.result:
        state.setdefault("test_results", []).append(result.result.model_dump(mode="json"))
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
        automation=_automation_from_execution(state, result),
        warnings=[*(state.get("warnings") or []), *result.warnings],
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
        automation=_automation_from_execution(state, result),
        warnings=[*(state.get("warnings") or []), *result.warnings],
    )


def _automation_from_generation(state: AgentStateDict, result) -> AutomationTaskResult:
    test_file = result.test_file
    artifacts = GeneratedArtifacts()
    reused = []
    affected = []
    if test_file:
        artifacts.pytest_files.append(test_file.file_path)
        if test_file.tracking_file_path:
            artifacts.json_sidecars.append(test_file.tracking_file_path)
        if test_file.robot_file_path:
            artifacts.robot_files.append(test_file.robot_file_path)
        if test_file.coverage_report_path:
            artifacts.coverage_reports.append(test_file.coverage_report_path)
        artifacts.reports.extend(test_file.report_file_paths)
        if result.action == "reused":
            reused.append(test_file.file_path)
        else:
            affected.append(test_file.file_path)
    return AutomationTaskResult(
        request_status="success" if result.supported else "failed",
        interpreted_intent="generate_tests",
        document_version=state.get("version"),
        active_version=state.get("version"),
        generated_artifacts=artifacts,
        affected_tests=affected,
        reused_tests=reused,
        execution_summary=ExecutionSummary(
            reused_from_previous_version=len(reused),
            skipped_unchanged=len(reused),
        ),
        db_update_status="success" if test_file else "not_updated",
        final_validation_status="success" if test_file else "failed",
        failure_reason=None if result.supported else result.message,
    )


def _automation_from_execution(state: AgentStateDict, result) -> AutomationTaskResult:
    test_file = result.test_file
    run_result = result.result
    artifacts = GeneratedArtifacts()
    if test_file:
        artifacts.pytest_files.append(test_file.file_path)
        if test_file.tracking_file_path:
            artifacts.json_sidecars.append(test_file.tracking_file_path)
        if test_file.robot_file_path:
            artifacts.robot_files.append(test_file.robot_file_path)
        if test_file.coverage_report_path:
            artifacts.coverage_reports.append(test_file.coverage_report_path)
        artifacts.reports.extend(test_file.report_file_paths)
    if run_result and run_result.xml_report_path:
        artifacts.xml_reports.append(run_result.xml_report_path)
    passed = run_result.passed if run_result else 0
    failed = run_result.failed if run_result else 0
    skipped = run_result.skipped if run_result else 0
    blocked = run_result.blocked if run_result else 0
    skipped_unchanged = (
        run_result.output.count("Skipped unchanged") if run_result and run_result.output else 0
    )
    summary = ExecutionSummary(
        executed=passed + failed + skipped,
        passed=passed,
        failed=failed,
        skipped=skipped,
        blocked=blocked,
        skipped_unchanged=skipped_unchanged,
        reused_from_previous_version=skipped_unchanged,
    )
    blocked_tests = [run_result.file_path] if run_result and run_result.status == "blocked" else []
    failed_tests = [run_result.file_path] if run_result and run_result.status == "failed" else []
    return AutomationTaskResult(
        request_status="success" if result.supported else "failed",
        interpreted_intent="run_generated_tests",
        document_version=state.get("version"),
        active_version=state.get("version"),
        generated_artifacts=artifacts,
        blocked_tests=blocked_tests,
        failed_tests=failed_tests,
        execution_summary=summary,
        db_update_status="success" if run_result else "not_updated",
        final_validation_status="success" if run_result else "failed",
        failure_reason=run_result.failure_reason if run_result else result.message,
    )


def _wants_last_result(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "last result",
            "last test result",
            "last testcase result",
            "previous result",
            "previous test result",
            "show result",
            "show me the result",
        )
    ) or ("last" in text and "result" in text and any(word in text for word in ("test", "run")))


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


def _wants_force_run_all(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "force run all",
            "run all",
            "execute all",
            "full execution",
            "force full",
        )
    )


def _wants_mock(text: str) -> bool:
    return "--mock" in text or any(
        phrase in text
        for phrase in (
            "mock mode",
            "mock flow",
            "mock device",
            "mock execution",
            "dummy device",
        )
    )


def _extract_scenario_count(text: str) -> int | None:
    match = re.search(
        r"\b(?P<count>\d{1,3})\s+(?:testcases?|test\s+cases?|tests?|scenarios?)\b",
        text,
        flags=re.I,
    )
    if not match:
        return None
    count = int(match.group("count"))
    return count if 1 <= count <= 250 else None


def _llm_intent_decision(state: AgentStateDict, request_text: str) -> IntentDecision | None:
    settings = _settings(state)
    client = select_llm_client(settings)
    if getattr(client, "provider", "none") == "none":
        return None
    ready, message = client.check_ready()
    if not ready:
        state.setdefault("warnings", []).append(f"LLM router unavailable: {message}")
        return None
    instructions = (
        "Classify the MARAG user request into exactly one intent: ingest_document, "
        "generate_tests, ask_question, update_coverage, run_generated_tests, "
        "compare_versions, regenerate_affected_tests, or last_result. "
        "Return structured fields only. Python agents will perform all actions. "
        "Set execution_mode to mock only when the user explicitly asks for --mock, "
        "mock flow, mock devices, or dummy device execution. In mock mode no real "
        "device connection is established and generated tests must be labeled as "
        "mocked. For real mode, report missing device/simulator inputs instead of "
        "assuming connectivity."
    )
    context = {
        "request": request_text,
        "system_name": state.get("system_name"),
        "version": state.get("version"),
        "scenario_count": state.get("scenario_count"),
        "execution_mode": state.get("execution_mode"),
        "source_path": state.get("source_path"),
    }
    try:
        return client.parse(
            instructions=instructions,
            user_input=str(context),
            schema=IntentDecision,
        )
    except Exception as exc:
        state.setdefault("warnings", []).append(f"LLM router fallback used: {exc}")
        return None


def _apply_intent_decision(state: AgentStateDict, decision: IntentDecision) -> None:
    if decision.system_name and not state.get("system_name"):
        state["system_name"] = decision.system_name
    if decision.version and not state.get("version"):
        state["version"] = decision.version
    if decision.scenario_count:
        state["scenario_count"] = decision.scenario_count
    if decision.execution_mode:
        mode = decision.execution_mode.strip().lower()
        if mode in {"mock", "simulator", "real", "auto"}:
            state["execution_mode"] = mode
    if decision.force_run_all:
        state["force_run_all"] = True
    state["intent_decision"] = decision.model_dump(mode="json")
    if decision.missing_inputs:
        state.setdefault("errors", []).extend(decision.missing_inputs)
        return
    intent_map = {
        "ask_question": "ask_question",
        "compare_versions": "ask_question",
        "generate_tests": "generate_tests",
        "regenerate_affected_tests": "generate_tests",
        "ingest_document": "ingest_document",
        "last_result": "last_result",
        "run_generated_tests": "run_generated_tests",
        "update_coverage": "update_coverage",
    }
    state["input_type"] = intent_map.get(decision.intent)


def _trace(state: AgentStateDict, node: str, status: str, **metadata: Any) -> None:
    state.setdefault("workflow_trace", []).append(
        {"node": node, "status": status, "metadata": metadata}
    )


def _handoff(state: AgentStateDict, source: str, target: str, summary: str) -> None:
    state.setdefault("handoff_summaries", []).append(
        {
            "source_agent": source,
            "target_agent": target,
            "summary": summary,
        }
    )


def _settings(state: AgentStateDict):
    return state.get("_settings") or get_settings()


def _settings_with_execution_mode(state: AgentStateDict):
    settings = _settings(state)
    mode = _normalize_execution_mode(state)
    if mode and mode != settings.generated_test_execution_mode:
        return settings.model_copy(update={"generated_test_execution_mode": mode})
    return settings


def _llm_routing_required(state: AgentStateDict) -> bool:
    settings = _settings(state)
    return settings.marag_target_mode == "target-graphrag" or settings.graphrag_required


def _normalize_execution_mode(state: AgentStateDict) -> str:
    settings = _settings(state)
    mode = (state.get("execution_mode") or settings.generated_test_execution_mode or "auto").lower()
    if mode not in {"mock", "simulator", "real", "auto"}:
        state.setdefault("warnings", []).append(
            f"Unsupported execution mode {mode!r}; falling back to auto."
        )
        mode = "auto"
    state["execution_mode"] = mode
    return mode


def _test_file_path_from_state(state: AgentStateDict) -> Path | None:
    generation = state.get("test_generation") or {}
    test_file = generation.get("test_file") or {}
    file_path = test_file.get("file_path") if isinstance(test_file, dict) else None
    if not file_path:
        execution = state.get("test_execution") or {}
        test_file = execution.get("test_file") or {}
        file_path = test_file.get("file_path") if isinstance(test_file, dict) else None
    return Path(file_path) if file_path else None


def _tracking_file_path_from_state(state: AgentStateDict) -> Path | None:
    for key in ("test_generation", "test_execution"):
        payload = state.get(key) or {}
        direct = payload.get("tracking_file_path")
        if direct:
            return Path(direct)
        test_file = payload.get("test_file") or {}
        file_path = test_file.get("tracking_file_path") if isinstance(test_file, dict) else None
        if file_path:
            return Path(file_path)
    return None


def _robot_file_path_from_state(state: AgentStateDict) -> Path | None:
    for key in ("test_generation", "test_execution"):
        payload = state.get(key) or {}
        test_file = payload.get("test_file") or {}
        file_path = test_file.get("robot_file_path") if isinstance(test_file, dict) else None
        if file_path:
            return Path(file_path)
    return None


def _protocols_for_text(text: str) -> list[str]:
    protocols: list[str] = []
    normalized = text.upper()
    if re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\s+/[A-Z0-9_./{}:-]+", normalized):
        protocols.append("REST")
    for protocol in ("Modbus", "MQTT", "CAN", "REST"):
        if re.search(rf"\b{re.escape(protocol.upper())}\b", normalized):
            protocols.append(protocol)
    return sorted({protocol for protocol in protocols if protocol})


def _domain_for_protocols(protocols: list[str]) -> str:
    if not protocols:
        return "generic_software"
    if protocols == ["REST"]:
        return "rest_api"
    if any(protocol in {"Modbus", "MQTT", "CAN"} for protocol in protocols):
        return "industrial_protocol"
    return "multi_domain"


def _error(state: AgentStateDict, node: str, message: str) -> AgentStateDict:
    state.setdefault("errors", []).append(message)
    _trace(state, node, "failed", error=message)
    return state
