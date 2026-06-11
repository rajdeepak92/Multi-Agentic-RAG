"""Natural-language task routing for MARAG happy paths."""

from __future__ import annotations

from pathlib import Path

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.coverage import DEFAULT_SCENARIO_COUNT, plan_requirement_coverage
from multi_agentic_rag.models import TaskResult
from multi_agentic_rag.retrieval import answer_query
from multi_agentic_rag.testing import (
    DEFAULT_OUTPUT_DIR,
    generate_testcases,
    get_last_test_result,
    run_testcases,
)


def handle_task(
    user_request: str,
    *,
    system_name: str | None = None,
    version: str | None = None,
    scenario_count: int = DEFAULT_SCENARIO_COUNT,
    output_dir: str | Path | None = None,
    settings: Settings | None = None,
) -> TaskResult:
    """Route a user request to query, coverage, testcase generation, or execution."""

    settings = settings or get_settings()
    text = user_request.lower()
    if not system_name:
        return TaskResult(
            supported=False,
            intent="missing_system",
            message="A system name is required to route MARAG tasks.",
        )

    if _wants_last_result(text):
        result = get_last_test_result(system_name=system_name, version=version, settings=settings)
        return TaskResult(
            supported=result.supported,
            intent="last_result",
            message=result.message,
            test_execution=result,
            last_result=result.result,
            warnings=result.warnings,
        )
    if _wants_run(text):
        result = run_testcases(
            system_name=system_name,
            version=version,
            scenario_count=scenario_count,
            output_dir=output_dir or DEFAULT_OUTPUT_DIR,
            settings=settings,
        )
        return TaskResult(
            supported=result.supported,
            intent="run_testcases",
            message=result.message,
            test_execution=result,
            warnings=result.warnings,
        )
    if _wants_test_generation(text):
        result = generate_testcases(
            system_name=system_name,
            version=version,
            scenario_count=scenario_count,
            output_dir=output_dir or DEFAULT_OUTPUT_DIR,
            settings=settings,
        )
        return TaskResult(
            supported=result.supported,
            intent="generate_testcases",
            message=result.message,
            coverage=result.coverage,
            test_generation=result,
            warnings=result.warnings,
        )
    if _wants_coverage_generation(text):
        result = plan_requirement_coverage(
            system_name=system_name,
            version=version,
            scenario_count=scenario_count,
            settings=settings,
        )
        return TaskResult(
            supported=result.supported,
            intent="generate_coverage",
            message=result.message,
            coverage=result,
            warnings=result.warnings,
        )

    result = answer_query(
        user_request,
        system_name=system_name,
        version=version,
        settings=settings,
    )
    return TaskResult(
        supported=result.supported,
        intent="query",
        message=result.answer,
        query=result,
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
