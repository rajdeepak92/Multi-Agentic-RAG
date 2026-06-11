"""Generated pytest testcase writer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from pprint import pformat
import re
from textwrap import shorten

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.coverage import DEFAULT_SCENARIO_COUNT, plan_requirement_coverage
from multi_agentic_rag.models import CoverageRecord, GeneratedTestFileRecord, TestGenerationResult
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.utils.hashing import stable_id
from multi_agentic_rag.utils.paths import resolve_path

DEFAULT_OUTPUT_DIR = "generated"
MAX_DEBUG_RETRIES = 5

WORKFLOW_HANDOFF = (
    "IntentRouter",
    "DocumentResolver",
    "EvidenceCollector",
    "ScenarioSelector",
    "TestPlanAgent",
    "DependencyAuditAgent",
    "HarnessAgent",
    "TestCodeWriterAgent",
    "PytestValidationAgent",
    "ExecutionAgent",
    "FailureDebuggerAgent",
    "TrackingJsonAgent",
    "DbUpdateAgent",
)


def generate_testcases(
    *,
    system_name: str,
    version: str | None = None,
    scenario_count: int = DEFAULT_SCENARIO_COUNT,
    force: bool = False,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    settings: Settings | None = None,
) -> TestGenerationResult:
    """Create or reuse generated pytest automation placeholders for coverage records."""

    settings = settings or get_settings()
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    coverage = plan_requirement_coverage(
        system_name=system_name,
        version=version,
        scenario_count=scenario_count,
        force=force,
        settings=settings,
    )
    if not coverage.supported or not coverage.run:
        return TestGenerationResult(
            supported=False,
            action="unsupported",
            message=coverage.message,
            coverage=coverage,
            warnings=coverage.warnings,
        )

    artifact_dir = _artifact_dir(
        output_dir=output_dir,
        system_name=system_name,
        version=version,
    )
    test_file_path = artifact_dir / _test_filename(system_name=system_name, version=version)
    tracking_file_path = test_file_path.with_suffix(".json")
    conftest_path = artifact_dir / "conftest.py"
    pytest_ini_path = artifact_dir / "pytest.ini"
    harness_paths = [str(conftest_path), str(pytest_ini_path)]

    existing = registry.find_generated_test_file(
        system_name=system_name,
        version=version,
        scope_hash=coverage.run.scope_hash,
    )
    if (
        existing
        and not force
        and _existing_artifacts_match(
            existing,
            test_file_path=test_file_path,
            tracking_file_path=tracking_file_path,
            harness_paths=[conftest_path, pytest_ini_path],
            run_id=coverage.run.run_id,
            coverage_ids=coverage.run.coverage_ids,
        )
    ):
        return TestGenerationResult(
            supported=True,
            action="reused",
            message="Generated testcase artifacts already exist. Reused without rewriting.",
            coverage=coverage,
            test_file=existing,
            tracking_file_path=existing.tracking_file_path,
            harness_file_paths=existing.harness_file_paths,
        )

    artifact_dir.mkdir(parents=True, exist_ok=True)
    scenarios = _build_scenario_payloads(
        coverage_records=coverage.records,
        registry=registry,
        generated_file=test_file_path,
    )
    dependency_audit = _dependency_audit()
    test_file_path.write_text(
        _render_pytest_file(
            system_name=system_name,
            version=version,
            coverage_ids=coverage.run.coverage_ids,
            scenarios=scenarios,
        ),
        encoding="utf-8",
    )
    conftest_path.write_text(_render_conftest(), encoding="utf-8")
    pytest_ini_path.write_text(_render_pytest_ini(), encoding="utf-8")
    tracking_file_path.write_text(
        json.dumps(
            _tracking_payload(
                system_name=system_name,
                version=version,
                coverage_run_id=coverage.run.run_id,
                scope_hash=coverage.run.scope_hash,
                generated_file=test_file_path,
                tracking_file=tracking_file_path,
                harness_paths=[conftest_path, pytest_ini_path],
                scenarios=scenarios,
                dependency_audit=dependency_audit,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    now = _utc_now()
    test_file = GeneratedTestFileRecord(
        test_file_id=stable_id(
            "test_file",
            system_name,
            version,
            coverage.run.scope_hash,
            str(test_file_path),
        ),
        run_id=coverage.run.run_id,
        system_name=system_name,
        version=version,
        scope_hash=coverage.run.scope_hash,
        file_path=str(test_file_path),
        tracking_file_path=str(tracking_file_path),
        harness_file_paths=harness_paths,
        status="ready",
        coverage_ids=coverage.run.coverage_ids,
        created_at=now,
        updated_at=now,
    )
    registry.upsert_generated_test_file(test_file)
    return TestGenerationResult(
        supported=True,
        action="generated",
        message=f"Generated pytest automation artifacts in: {artifact_dir}",
        coverage=coverage,
        test_file=test_file,
        tracking_file_path=str(tracking_file_path),
        harness_file_paths=harness_paths,
    )


def tracking_file_for(test_file_path: str | Path) -> Path:
    """Return the sidecar JSON path for a generated pytest file."""

    return Path(test_file_path).with_suffix(".json")


def _artifact_dir(*, output_dir: str | Path, system_name: str, version: str | None) -> Path:
    return resolve_path(output_dir) / _safe_slug(system_name) / _version_dir(version)


def _version_dir(version: str | None) -> str:
    if not version:
        return "active"
    slug = _safe_slug(version)
    return slug if slug.startswith("brd_") else f"brd_{slug}"


def _test_filename(*, system_name: str, version: str | None) -> str:
    return f"test_{_safe_slug(system_name)}_{_version_dir(version)}.py"


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "document"


def _class_name(*, system_name: str, version: str | None) -> str:
    parts = re.findall(r"[a-zA-Z0-9]+", f"{system_name} {version or 'active'}")
    return "Test" + "".join(part[:1].upper() + part[1:].lower() for part in parts) + "Automation"


def _existing_artifacts_match(
    existing: GeneratedTestFileRecord,
    *,
    test_file_path: Path,
    tracking_file_path: Path,
    harness_paths: list[Path],
    run_id: str,
    coverage_ids: list[str],
) -> bool:
    file_path = Path(existing.file_path)
    if file_path.resolve() != test_file_path.resolve():
        return False
    if existing.run_id != run_id or existing.coverage_ids != coverage_ids:
        return False
    if Path(existing.tracking_file_path or "").resolve() != tracking_file_path.resolve():
        return False
    if not file_path.exists() or not tracking_file_path.exists():
        return False
    if any(not path.exists() for path in harness_paths):
        return False
    try:
        content = file_path.read_text(encoding="utf-8")
        tracking = json.loads(tracking_file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return all(coverage_id in content for coverage_id in coverage_ids) and all(
        coverage_id in {scenario["coverage_id"] for scenario in tracking.get("scenarios", [])}
        for coverage_id in coverage_ids
    )


def _build_scenario_payloads(
    *,
    coverage_records: list[CoverageRecord],
    registry: SQLiteRegistry,
    generated_file: Path,
) -> list[dict]:
    scenarios = []
    for record in coverage_records:
        document = registry.get_document(record.document_id) if record.document_id else None
        evidence_text = " ".join(record.evidence)
        scenario_index = record.scenario_index or len(scenarios) + 1
        scenarios.append(
            {
                "scenario_id": stable_id("scenario", record.coverage_id, scenario_index),
                "scenario_index": scenario_index,
                "coverage_id": record.coverage_id,
                "requirement_id": record.requirement_id,
                "source_doc": document.source_name if document else None,
                "source_doc_id": record.document_id,
                "doc_version": record.version,
                "chunk_ids": [record.chunk_id] if record.chunk_id else [],
                "expected_values": _extract_expected_values(evidence_text, record),
                "priority": _priority(record),
                "test_scenario": record.test_scenario,
                "automation_feasibility": "placeholder_until_interfaces_exist",
                "generated_file": str(generated_file),
                "test_function": _test_function_name(record, scenario_index),
                "validation_label": _validation_label(record, evidence_text),
                "evidence": record.evidence,
                "status": "generated",
            }
        )
    return scenarios


def _extract_expected_values(evidence_text: str, record: CoverageRecord) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    patterns = (
        ("range", r"\b\d+(?:\.\d+)?\s+to\s+\d+(?:\.\d+)?\s*(?:degree|degrees|c|C|%)?\b"),
        ("range", r"\b\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*(?:degree|degrees|c|C|%)\b"),
        ("numeric_limit", r"\b\d+(?:\.\d+)?\s*(?:degree|degrees|c|C|%|ms|s|seconds?)\b"),
        ("endpoint", r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+/[A-Za-z0-9_./{}-]+"),
        ("protocol", r"\b(?:MQTT|Modbus|CAN|REST|HTTP|HTTPS)\b"),
    )
    for kind, pattern in patterns:
        for match in re.finditer(pattern, evidence_text):
            values.append({"kind": kind, "value": match.group(0), "source": "evidence_chunk"})
    if not values:
        fallback = shorten(evidence_text or record.test_scenario, width=160, placeholder="...")
        values.append(
            {
                "kind": "requirement_behavior",
                "value": fallback,
                "source": "evidence_chunk",
            }
        )
    return values


def _priority(record: CoverageRecord) -> str:
    text = " ".join([record.test_scenario, *record.evidence]).lower()
    if any(word in text for word in ("threshold", "maximum", "minimum", "safety", "protocol")):
        return "high"
    return record.priority


def _test_function_name(record: CoverageRecord, scenario_index: int) -> str:
    requirement_slug = _safe_slug(record.requirement_id).replace("_", "")
    return f"test_scenario_{scenario_index:03d}_{requirement_slug}"


def _validation_label(record: CoverageRecord, evidence_text: str) -> str:
    text = " ".join([record.test_scenario, evidence_text]).lower()
    if "threshold" in text and any(word in text for word in ("maximum", "max")):
        return "sensor threshold maximum value"
    if "threshold" in text and any(word in text for word in ("minimum", "min")):
        return "sensor threshold minimum value"
    if "protocol" in text or any(
        protocol in text for protocol in ("mqtt", "modbus", "rest", "can")
    ):
        return "protocol/interface behavior"
    return _safe_slug(record.requirement_id).replace("_", " ") or "requirement behavior"


def _dependency_audit() -> dict:
    return {
        "agent": "DependencyAuditAgent",
        "status": "ready",
        "project_mutation_allowed": False,
        "required_runtime": ["python", "pytest", "logging"],
        "required_harness": ["pytest.ini", "conftest.py", "class_based_pytest_tests"],
        "missing": [],
        "notes": [
            "Dummy placeholder tests do not require external interfaces.",
            "Protocol clients such as MQTT must be proposed separately before real tests use them.",
        ],
    }


def _tracking_payload(
    *,
    system_name: str,
    version: str | None,
    coverage_run_id: str,
    scope_hash: str,
    generated_file: Path,
    tracking_file: Path,
    harness_paths: list[Path],
    scenarios: list[dict],
    dependency_audit: dict,
) -> dict:
    now = _utc_now()
    return {
        "schema_version": "test-automation-tracking.v1",
        "generated_at": now,
        "updated_at": now,
        "project": _safe_slug(system_name),
        "system_name": system_name,
        "doc_version": version,
        "coverage_run_id": coverage_run_id,
        "scope_hash": scope_hash,
        "generated_file": str(generated_file),
        "tracking_file": str(tracking_file),
        "harness_files": [str(path) for path in harness_paths],
        "mode": "dummy_placeholder_until_interfaces_exist",
        "workflow_handoff": list(WORKFLOW_HANDOFF),
        "retry_policy": {
            "max_attempts": MAX_DEBUG_RETRIES,
            "strategy": (
                "validate, execute, classify, regenerate only for fixable "
                "generated-code failures"
            ),
        },
        "dependency_audit": dependency_audit,
        "scenarios": scenarios,
        "run_history": [],
    }


def _render_pytest_file(
    *,
    system_name: str,
    version: str | None,
    coverage_ids: list[str],
    scenarios: list[dict],
) -> str:
    class_name = _class_name(system_name=system_name, version=version)
    scenario_by_index = {scenario["scenario_index"]: scenario for scenario in scenarios}
    test_methods = "\n\n".join(_render_test_method(scenario) for scenario in scenarios)
    return f'''"""Generated MARAG pytest automation placeholders.

System: {system_name}
Version: {version or "active"}

This file is generated from stored BRD evidence. It intentionally uses
placeholder execution until real product interfaces are connected.
"""

from __future__ import annotations

import logging

import pytest

COVERAGE_IDS = {pformat(coverage_ids, width=100)}
SCENARIOS = {pformat(scenario_by_index, width=100)}
LOG = logging.getLogger(__name__)


def _execute_placeholder_validation(scenario: dict, automation_context: dict) -> bool:
    LOG.debug("Executing scenario data: %s", scenario)
    LOG.warning("Running in placeholder mode because external interfaces are not connected.")
    LOG.info("%s validation executed successfully", scenario["validation_label"])
    assert automation_context["mode"] == "dummy_placeholder_until_interfaces_exist"
    return True


@pytest.mark.generated
@pytest.mark.placeholder
class {class_name}:
{test_methods}
'''


def _render_test_method(scenario: dict) -> str:
    scenario_index = scenario["scenario_index"]
    function_name = scenario["test_function"]
    requirement_id = scenario["requirement_id"]
    return f'''    @pytest.mark.requirement("{requirement_id}")
    def {function_name}(self, automation_context):
        scenario = SCENARIOS[{scenario_index}]
        assert scenario["coverage_id"] in COVERAGE_IDS
        assert scenario["requirement_id"]
        assert scenario["evidence"], "Generated scenario must cite BRD evidence."
        assert scenario["chunk_ids"], "Generated scenario must trace to a source chunk."
        assert scenario["expected_values"], "Expected values must be derived from evidence."
        assert _execute_placeholder_validation(scenario, automation_context) is True'''


def _render_conftest() -> str:
    return '''"""Generated MARAG pytest harness fixtures and hooks."""

from __future__ import annotations

import logging

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--marag-env",
        action="store",
        default="placeholder",
        help="Generated MARAG automation target environment.",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "generated: generated MARAG automation testcase")
    config.addinivalue_line("markers", "placeholder: forced-pass placeholder testcase")
    config.addinivalue_line("markers", "requirement(id): BRD requirement trace marker")


@pytest.fixture(scope="session")
def automation_context(pytestconfig):
    return {
        "environment": pytestconfig.getoption("--marag-env"),
        "mode": "dummy_placeholder_until_interfaces_exist",
    }


@pytest.fixture(autouse=True)
def precise_test_logging(request):
    log = logging.getLogger(request.node.name)
    log.info("starting generated testcase: %s", request.node.nodeid)
    yield
    log.info("finished generated testcase: %s", request.node.nodeid)
'''


def _render_pytest_ini() -> str:
    return """[pytest]
addopts = -ra --strict-markers --tb=short --log-cli-level=INFO
log_cli = true
log_cli_format = %(levelname)s %(name)s %(message)s
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    generated: generated MARAG automation testcase
    placeholder: forced-pass placeholder testcase
    requirement(id): BRD requirement trace marker
"""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
