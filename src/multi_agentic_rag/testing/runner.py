"""Generated pytest testcase runner."""

from __future__ import annotations

import json
import py_compile
from datetime import UTC, datetime
from pathlib import Path
import re
import subprocess
import sys

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.coverage import DEFAULT_SCENARIO_COUNT
from multi_agentic_rag.models import TestExecutionResult, TestRunResultRecord
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.testing.generator import (
    DEFAULT_OUTPUT_DIR,
    generate_testcases,
    tracking_file_for,
)
from multi_agentic_rag.testing.graph_indexer import index_test_run_graph
from multi_agentic_rag.utils.hashing import stable_id

MAX_DEBUG_RETRIES = 5


def run_testcases(
    *,
    system_name: str,
    version: str | None = None,
    scenario_count: int = DEFAULT_SCENARIO_COUNT,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    settings: Settings | None = None,
    max_attempts: int = MAX_DEBUG_RETRIES,
) -> TestExecutionResult:
    """Run tracked generated pytest artifacts, creating them first if needed."""

    settings = settings or get_settings()
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    generation = generate_testcases(
        system_name=system_name,
        version=version,
        scenario_count=scenario_count,
        force=False,
        output_dir=output_dir,
        settings=settings,
    )
    if not generation.supported or not generation.test_file:
        return TestExecutionResult(
            supported=False,
            action="unsupported",
            message=generation.message,
            warnings=generation.warnings,
            tracking_file_path=generation.tracking_file_path,
        )

    final_result: TestRunResultRecord | None = None
    graph_warnings: list[str] = []
    attempts = max(1, max_attempts)
    for attempt in range(1, attempts + 1):
        file_path = Path(generation.test_file.file_path)
        tracking_file_path = Path(
            generation.test_file.tracking_file_path or tracking_file_for(file_path)
        )
        if not file_path.exists():
            final_result = _blocked_result(
                generation.test_file.test_file_id,
                generation.test_file.run_id,
                system_name,
                version,
                str(file_path),
                blocker=f"Generated testcase file is missing: {file_path}",
            )
            registry.insert_test_run_result(final_result)
            graph_warning = index_test_run_graph(
                settings=settings,
                result=final_result,
                test_file=generation.test_file,
            )
            if graph_warning:
                graph_warnings.append(graph_warning)
            _record_tracking_run(
                tracking_file_path=tracking_file_path,
                result=final_result,
                attempt=attempt,
                failure_reason=final_result.dependency_blockers[0],
                fix_attempted=False,
            )
            return TestExecutionResult(
                supported=False,
                action="blocked",
                message=final_result.dependency_blockers[0],
                test_file=generation.test_file,
                result=final_result,
                tracking_file_path=str(tracking_file_path),
                attempts=attempt,
                warnings=[*final_result.dependency_blockers, *graph_warnings],
            )

        syntax_error = _syntax_error(file_path)
        if syntax_error:
            final_result = _failed_result(
                generation.test_file.test_file_id,
                generation.test_file.run_id,
                system_name,
                version,
                str(file_path),
                output=syntax_error,
            )
            registry.insert_test_run_result(final_result)
            graph_warning = index_test_run_graph(
                settings=settings,
                result=final_result,
                test_file=generation.test_file,
            )
            if graph_warning:
                graph_warnings.append(graph_warning)
            should_retry = attempt < attempts
            _record_tracking_run(
                tracking_file_path=tracking_file_path,
                result=final_result,
                attempt=attempt,
                failure_reason=syntax_error,
                fix_attempted=should_retry,
            )
            if should_retry:
                generation = generate_testcases(
                    system_name=system_name,
                    version=version,
                    scenario_count=scenario_count,
                    force=True,
                    output_dir=output_dir,
                    settings=settings,
                )
                continue
            break

        process = _run_pytest_file(file_path)
        output = "\n".join(part for part in [process.stdout, process.stderr] if part).strip()
        blockers = _dependency_blockers(output)
        passed, failed, skipped = _parse_pytest_counts(output)
        status = _execution_status(
            returncode=process.returncode,
            blockers=blockers,
            passed=passed,
            failed=failed,
            skipped=skipped,
        )
        failure_category = _failure_category(status=status, blockers=blockers, output=output)
        failure_reason = _failure_reason(status=status, blockers=blockers, output=output)
        final_result = TestRunResultRecord(
            result_id=stable_id(
                "test_result",
                generation.test_file.test_file_id,
                attempt,
                datetime.now(UTC).isoformat(),
            ),
            test_file_id=generation.test_file.test_file_id,
            run_id=generation.test_file.run_id,
            system_name=system_name,
            version=version,
            file_path=str(file_path),
            status=status,
            exit_code=process.returncode,
            passed=passed,
            failed=failed,
            skipped=skipped,
            failure_category=failure_category,
            failure_reason=failure_reason,
            dependency_blockers=blockers,
            output=output[-8000:],
            created_at=_utc_now(),
        )
        registry.insert_test_run_result(final_result)
        graph_warning = index_test_run_graph(
            settings=settings,
            result=final_result,
            test_file=generation.test_file,
        )
        if graph_warning:
            graph_warnings.append(graph_warning)
        should_retry = (
            status == "failed"
            and attempt < attempts
            and _fixable_generated_failure(output)
        )
        _record_tracking_run(
            tracking_file_path=tracking_file_path,
            result=final_result,
            attempt=attempt,
            failure_reason=failure_reason,
            fix_attempted=should_retry,
        )
        if status in {"passed", "blocked"} or not should_retry:
            break
        generation = generate_testcases(
            system_name=system_name,
            version=version,
            scenario_count=scenario_count,
            force=True,
            output_dir=output_dir,
            settings=settings,
        )

    if final_result is None:
        final_result = _blocked_result(
            generation.test_file.test_file_id,
            generation.test_file.run_id,
            system_name,
            version,
            generation.test_file.file_path,
            blocker="No pytest execution result was produced.",
        )
        registry.insert_test_run_result(final_result)
        graph_warning = index_test_run_graph(
            settings=settings,
            result=final_result,
            test_file=generation.test_file,
        )
        if graph_warning:
            graph_warnings.append(graph_warning)

    return TestExecutionResult(
        supported=True,
        action="executed",
        message=_execution_message(final_result),
        test_file=generation.test_file,
        result=final_result,
        tracking_file_path=generation.test_file.tracking_file_path,
        attempts=attempt,
        warnings=[*final_result.dependency_blockers, *graph_warnings],
    )


def get_last_test_result(
    *,
    system_name: str,
    version: str | None = None,
    settings: Settings | None = None,
) -> TestExecutionResult:
    """Return the last stored testcase result without executing anything."""

    settings = settings or get_settings()
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    result = registry.get_latest_test_result(system_name=system_name, version=version)
    if not result:
        return TestExecutionResult(
            supported=False,
            action="not_found",
            message="No previous test run result found for this system/version.",
        )
    test_file = registry.get_generated_test_file(result.test_file_id)
    return TestExecutionResult(
        supported=True,
        action="last_result",
        message=_execution_message(result),
        test_file=test_file,
        result=result,
        tracking_file_path=test_file.tracking_file_path if test_file else None,
        attempts=1,
        warnings=result.dependency_blockers,
    )


def _run_pytest_file(file_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", file_path.name],
        cwd=str(file_path.parent),
        capture_output=True,
        text=True,
        check=False,
    )


def _syntax_error(file_path: Path) -> str | None:
    try:
        py_compile.compile(str(file_path), doraise=True)
    except py_compile.PyCompileError as exc:
        return str(exc)
    return None


def _blocked_result(
    test_file_id: str,
    run_id: str,
    system_name: str,
    version: str | None,
    file_path: str,
    *,
    blocker: str,
) -> TestRunResultRecord:
    return TestRunResultRecord(
        result_id=stable_id("test_result", test_file_id, _utc_now()),
        test_file_id=test_file_id,
        run_id=run_id,
        system_name=system_name,
        version=version,
        file_path=file_path,
        status="blocked",
        exit_code=None,
        passed=0,
        failed=0,
        skipped=0,
        failure_category="DEPENDENCY_MISSING",
        failure_reason=blocker,
        dependency_blockers=[blocker],
        output=blocker,
        created_at=_utc_now(),
    )


def _failed_result(
    test_file_id: str,
    run_id: str,
    system_name: str,
    version: str | None,
    file_path: str,
    *,
    output: str,
    failure_category: str = "GENERATION_ERROR",
) -> TestRunResultRecord:
    return TestRunResultRecord(
        result_id=stable_id("test_result", test_file_id, _utc_now()),
        test_file_id=test_file_id,
        run_id=run_id,
        system_name=system_name,
        version=version,
        file_path=file_path,
        status="failed",
        exit_code=None,
        passed=0,
        failed=1,
        skipped=0,
        failure_category=failure_category,
        failure_reason=output,
        dependency_blockers=[],
        output=output,
        created_at=_utc_now(),
    )


def _dependency_blockers(output: str) -> list[str]:
    blockers = []
    patterns = (
        r"Blocked because .+",
        r"Skipped because .+",
        r"PROTOCOL_UNAVAILABLE: .+",
        r"ModuleNotFoundError: No module named '([^']+)'",
        r"ImportError: (.+)",
        r"ConnectionRefusedError: (.+)",
        r"TimeoutError: (.+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, output):
            blockers.append(match.group(0))
    return blockers


def _parse_pytest_counts(output: str) -> tuple[int, int, int]:
    passed = _first_count(output, "passed")
    failed = _first_count(output, "failed")
    skipped = _first_count(output, "skipped")
    return passed, failed, skipped


def _first_count(output: str, label: str) -> int:
    match = re.search(rf"(\d+)\s+{label}", output)
    return int(match.group(1)) if match else 0


def _execution_status(
    *,
    returncode: int,
    blockers: list[str],
    passed: int,
    failed: int,
    skipped: int,
) -> str:
    if blockers:
        return "blocked"
    if failed:
        return "failed"
    if skipped and not passed:
        return "skipped"
    if returncode == 0:
        return "passed"
    return "failed"


def _failure_reason(*, status: str, blockers: list[str], output: str) -> str | None:
    if status == "passed":
        return None
    if blockers:
        return "; ".join(blockers)
    for line in output.splitlines():
        if line.startswith(("E   ", "FAILED ", "ERROR ")):
            return line[:500]
    return output[-500:] if output else "pytest failed without output"


def _failure_category(*, status: str, blockers: list[str], output: str) -> str | None:
    if status == "passed":
        return None
    joined_blockers = " ".join(blockers)
    if any(protocol in joined_blockers for protocol in ("MQTT", "Modbus", "CAN", "REST")):
        return "PROTOCOL_UNAVAILABLE"
    if blockers:
        return "DEPENDENCY_MISSING"
    if "SyntaxError" in output or "PyCompileError" in output:
        return "GENERATION_ERROR"
    if "AssertionError" in output or "assert " in output or "FAILED " in output:
        return "ASSERTION_FAILURE"
    if status == "skipped":
        return "DEPENDENCY_MISSING"
    return "ENVIRONMENT_ERROR"


def _fixable_generated_failure(output: str) -> bool:
    if _dependency_blockers(output):
        return False
    non_fixable = ("ConnectionRefusedError", "TimeoutError", "No route to host")
    return not any(marker in output for marker in non_fixable)


def _record_tracking_run(
    *,
    tracking_file_path: Path,
    result: TestRunResultRecord,
    attempt: int,
    failure_reason: str | None,
    fix_attempted: bool,
) -> None:
    if not tracking_file_path.exists():
        return
    try:
        payload = json.loads(tracking_file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    timestamp = _utc_now()
    status = {
        "passed": "PASS",
        "failed": "FAIL",
        "blocked": "BLOCKED",
        "skipped": "SKIP",
    }.get(result.status, result.status.upper())
    run_payload = {
        "state": "executed",
        "timestamp": timestamp,
        "run_id": result.result_id,
        "command": f"{sys.executable} -m pytest {Path(result.file_path).name}",
        "status": status,
        "result_id": result.result_id,
        "attempt": attempt,
        "exit_code": result.exit_code,
        "passed": result.passed,
        "failed": result.failed,
        "skipped": result.skipped,
        "failure_category": result.failure_category,
        "dependency_blockers": result.dependency_blockers,
        "failure_reason": failure_reason,
        "fix_attempted": fix_attempted,
        "stdout_path": "",
        "stderr_path": "",
    }
    payload[f"run_{attempt}"] = run_payload
    payload.setdefault("run_history", []).append(run_payload)
    payload["updated_at"] = timestamp
    payload["db_update_status"] = "test_run_result_record_written"
    for scenario in payload.get("scenarios", []):
        scenario["last_run_status"] = status
        scenario["last_run_id"] = result.result_id
    for scenario in payload.get("selected_scenarios", []):
        scenario["last_run_status"] = status
        scenario["last_run_id"] = result.result_id
    tracking_file_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _execution_message(result: TestRunResultRecord) -> str:
    return (
        f"Test run {result.status}: {result.passed} passed, "
        f"{result.failed} failed, {result.skipped} skipped."
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
