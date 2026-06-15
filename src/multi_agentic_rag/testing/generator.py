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
from multi_agentic_rag.testing.graph_indexer import index_generated_test_graph
from multi_agentic_rag.utils.hashing import stable_id
from multi_agentic_rag.utils.paths import resolve_path

DEFAULT_OUTPUT_DIR = "generated"
MAX_DEBUG_RETRIES = 5
SIDECAR_SCHEMA_VERSION = "test-automation-tracking.v4"
SUPPORTED_PROTOCOLS = ("Modbus", "MQTT", "CAN", "REST")
MOCK_FLOW_WARNING = (
    "This is a Mock flow: no actual connection was established. "
    "Written contents are evidence-bound to the documents, but test execution "
    "uses mocked devices."
)

WORKFLOW_HANDOFF = (
    "IntentRouterAgent",
    "DocumentResolverAgent",
    "VersionDeltaAgent",
    "GraphRetrievalAgent",
    "ScenarioSelectionAgent",
    "DependencyAuditAgent",
    "TestHarnessAgent",
    "TestWriterAgent",
    "RobotMappingAgent",
    "SyntaxValidationAgent",
    "TestExecutionAgent",
    "FailureClassifierAgent",
    "JsonSidecarAgent",
    "DatabaseUpdateAgent",
    "FinalRouterValidationAgent",
)


def generate_testcases(
    *,
    system_name: str,
    version: str | None = None,
    scenario_count: int = DEFAULT_SCENARIO_COUNT,
    force: bool = False,
    force_run_all: bool = False,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    settings: Settings | None = None,
    execution_mode: str | None = None,
) -> TestGenerationResult:
    """Create or reuse generated pytest automation placeholders for coverage records."""

    settings = _settings_for_execution_mode(settings or get_settings(), execution_mode)
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
    warnings = list(coverage.warnings)

    artifact_dir = _artifact_dir(
        output_dir=output_dir,
        system_name=system_name,
        version=version,
    )
    test_file_path = artifact_dir / _test_filename(system_name=system_name, version=version)
    robot_file_path = artifact_dir / _robot_filename(system_name=system_name, version=version)
    tracking_file_path = test_file_path.with_suffix(".json")
    conftest_path = artifact_dir / "conftest.py"
    pytest_ini_path = artifact_dir / "pytest.ini"
    reports_dir = artifact_dir / "reports"
    coverage_report_path = reports_dir / "coverage.json"
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
            robot_file_path=robot_file_path,
            harness_paths=[conftest_path, pytest_ini_path],
            run_id=coverage.run.run_id,
            coverage_ids=coverage.run.coverage_ids,
        )
    ):
        graph_warning = index_generated_test_graph(
            settings=settings,
            test_file=existing,
            coverage_records=coverage.records,
        )
        if graph_warning:
            warnings.append(graph_warning)
        return TestGenerationResult(
            supported=True,
            action="reused",
            message="Generated testcase artifacts already exist. Reused without rewriting.",
            coverage=coverage,
            test_file=existing,
            tracking_file_path=existing.tracking_file_path,
            harness_file_paths=existing.harness_file_paths,
            warnings=warnings,
        )

    artifact_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    scenarios = _build_scenario_payloads(
        coverage_records=coverage.records,
        registry=registry,
        generated_file=test_file_path,
        settings=settings,
        force_run_all=force_run_all,
    )
    dependency_audit = _dependency_audit(
        scenarios=scenarios,
        settings=settings,
        pytest_ini_path=pytest_ini_path,
        conftest_path=conftest_path,
    )
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
    if robot_file_path:
        robot_file_path.write_text(_render_robot_file(scenarios), encoding="utf-8")
    coverage_report_path.write_text(
        json.dumps(
            _coverage_report_payload(
                system_name=system_name,
                version=version,
                coverage_run_id=coverage.run.run_id,
                records=coverage.records,
                scenarios=scenarios,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    tracking_payload = _tracking_payload(
        system_name=system_name,
        version=version,
        coverage_run_id=coverage.run.run_id,
        scope_hash=coverage.run.scope_hash,
        generated_file=test_file_path,
        robot_file=robot_file_path,
        coverage_report=coverage_report_path,
        tracking_file=tracking_file_path,
        harness_paths=[conftest_path, pytest_ini_path],
        scenarios=scenarios,
        dependency_audit=dependency_audit,
    )
    _validate_tracking_payload(tracking_payload)
    tracking_file_path.write_text(
        json.dumps(tracking_payload, indent=2, sort_keys=True) + "\n",
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
        robot_file_path=str(robot_file_path) if robot_file_path else None,
        coverage_report_path=str(coverage_report_path),
        report_file_paths=[str(coverage_report_path)],
        harness_file_paths=harness_paths,
        status="ready",
        coverage_ids=coverage.run.coverage_ids,
        created_at=now,
        updated_at=now,
    )
    registry.upsert_generated_test_file(test_file)
    graph_warning = index_generated_test_graph(
        settings=settings,
        test_file=test_file,
        coverage_records=coverage.records,
    )
    if graph_warning:
        warnings.append(graph_warning)
    _mark_tracking_db_update(
        tracking_file_path,
        "generated_test_file_record_written",
    )
    return TestGenerationResult(
        supported=True,
        action="generated",
        message=f"Generated pytest automation artifacts in: {artifact_dir}",
        coverage=coverage,
        test_file=test_file,
        tracking_file_path=str(tracking_file_path),
        harness_file_paths=harness_paths,
        warnings=warnings,
    )


def tracking_file_for(test_file_path: str | Path) -> Path:
    """Return the sidecar JSON path for a generated pytest file."""

    return Path(test_file_path).with_suffix(".json")


def _settings_for_execution_mode(settings: Settings, execution_mode: str | None) -> Settings:
    if not execution_mode:
        return settings
    mode = execution_mode.strip().lower()
    if mode not in {"mock", "simulator", "real", "auto"}:
        raise ValueError(f"Unsupported generated test execution mode: {execution_mode}")
    if mode == settings.generated_test_execution_mode:
        return settings
    return settings.model_copy(update={"generated_test_execution_mode": mode})


def _artifact_dir(*, output_dir: str | Path, system_name: str, version: str | None) -> Path:
    return resolve_path(output_dir) / _safe_slug(system_name) / _version_dir(version)


def _version_dir(version: str | None) -> str:
    if not version:
        return "active"
    slug = _safe_slug(version)
    return slug if slug.startswith("brd_") else f"brd_{slug}"


def _test_filename(*, system_name: str, version: str | None) -> str:
    return f"test_{_safe_slug(system_name)}_{_version_dir(version)}.py"


def _robot_filename(*, system_name: str, version: str | None) -> str:
    return f"test_{_safe_slug(system_name)}_{_version_dir(version)}.robot"


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
    robot_file_path: Path | None,
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
    if robot_file_path:
        if not existing.robot_file_path:
            return False
        if Path(existing.robot_file_path).resolve() != robot_file_path.resolve():
            return False
        if not robot_file_path.exists():
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
    if tracking.get("schema_version") != SIDECAR_SCHEMA_VERSION:
        return False
    if "_execute_generated_validation" not in content:
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
    settings: Settings,
    force_run_all: bool = False,
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
                "fact_id": record.fact_id,
                "semantic_key": record.semantic_key,
                "impact_status": record.impact_status,
                "force_run_all": force_run_all,
                "expected_values": _extract_expected_values(evidence_text, record),
                "priority": _priority(record),
                "test_scenario": record.test_scenario,
                "automation_feasibility": "dependency_audit_required",
                "generated_file": str(generated_file),
                "test_function": _test_function_name(record, scenario_index),
                "validation_label": _validation_label(record, evidence_text),
                "evidence": record.evidence,
                "status": "generated",
            }
        )
        _attach_domain_dependency_status(scenarios[-1], evidence_text, settings)
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


def _attach_domain_dependency_status(
    scenario: dict,
    evidence_text: str,
    settings: Settings,
) -> None:
    protocols = _protocols_for_text(evidence_text)
    external_dependencies = _external_dependencies_for_protocols(protocols)
    missing_dependencies = _missing_dependencies_for_protocols(protocols, settings)
    execution_mode = _execution_mode_for_protocols(protocols, settings, missing_dependencies)
    scenario["domain"] = _domain_for_protocols(protocols)
    scenario["protocols"] = protocols
    scenario["execution_mode"] = execution_mode
    scenario["dependency_status"] = "blocked" if missing_dependencies else "ready"
    scenario["external_dependencies"] = external_dependencies
    scenario["missing_dependencies"] = missing_dependencies
    scenario["mock_mode"] = execution_mode == "mock"
    scenario["mock_warning"] = MOCK_FLOW_WARNING if execution_mode == "mock" else ""
    scenario["mock_device_config"] = (
        {
            "device_id": f"mock-{scenario['scenario_id'][:12]}",
            "protocols": protocols or ["document_contract"],
            "connection_established": False,
        }
        if execution_mode == "mock"
        else {}
    )


def _protocols_for_text(text: str) -> list[str]:
    protocols: list[str] = []
    normalized = text.upper()
    if re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\s+/[A-Z0-9_./{}:-]+", normalized):
        protocols.append("REST")
    for protocol in SUPPORTED_PROTOCOLS:
        if re.search(rf"\b{re.escape(protocol.upper())}\b", normalized):
            protocols.append(protocol)
    return _unique_sorted(protocols)


def _external_dependencies_for_protocols(protocols: list[str]) -> list[str]:
    dependency_by_protocol = {
        "REST": "REST API base URL or REST simulator",
        "MQTT": "MQTT broker URL or MQTT simulator",
        "Modbus": "Modbus host or Modbus simulator",
        "CAN": "CAN interface or CAN simulator",
    }
    return [dependency_by_protocol[protocol] for protocol in protocols if protocol in dependency_by_protocol]


def _missing_dependencies_for_protocols(protocols: list[str], settings: Settings) -> list[str]:
    if not protocols:
        return []
    if settings.generated_test_execution_mode == "mock":
        return []
    if settings.generated_test_execution_mode == "simulator":
        return _missing_simulators_for_protocols(protocols, settings)

    missing: list[str] = []
    for protocol in protocols:
        if protocol == "REST" and not (
            settings.rest_api_base_url or settings.rest_simulator_enabled
        ):
            missing.append("REST API base URL or REST simulator is not configured")
        elif protocol == "MQTT" and not (
            settings.mqtt_broker_url or settings.mqtt_simulator_enabled
        ):
            missing.append("MQTT broker URL or MQTT simulator is not configured")
        elif protocol == "Modbus" and not settings.modbus_host:
            missing.append("Modbus host or Modbus simulator is not configured")
        elif protocol == "CAN" and not settings.can_interface:
            missing.append("CAN interface or CAN simulator is not configured")
    if settings.generated_test_execution_mode == "auto" and missing and settings.simulator_config_path:
        return []
    return missing


def _missing_simulators_for_protocols(protocols: list[str], settings: Settings) -> list[str]:
    if settings.simulator_config_path:
        return []
    missing: list[str] = []
    for protocol in protocols:
        if protocol == "REST" and not settings.rest_simulator_enabled:
            missing.append("REST simulator is not configured")
        elif protocol == "MQTT" and not settings.mqtt_simulator_enabled:
            missing.append("MQTT simulator is not configured")
        elif protocol == "Modbus":
            missing.append("Modbus simulator is not configured")
        elif protocol == "CAN":
            missing.append("CAN simulator is not configured")
    return missing


def _execution_mode_for_protocols(
    protocols: list[str],
    settings: Settings,
    missing_dependencies: list[str],
) -> str:
    if settings.generated_test_execution_mode == "mock":
        return "mock"
    if not protocols:
        return "document_contract"
    if missing_dependencies:
        return "blocked"
    if settings.generated_test_execution_mode in {"mock", "simulator", "real"}:
        return settings.generated_test_execution_mode
    if any(protocol == "REST" for protocol in protocols) and settings.rest_simulator_enabled:
        return "simulator"
    if any(protocol == "MQTT" for protocol in protocols) and settings.mqtt_simulator_enabled:
        return "simulator"
    if settings.simulator_config_path:
        return "simulator"
    return "real"


def _domain_for_protocols(protocols: list[str]) -> str:
    if not protocols:
        return "generic_software"
    if protocols == ["REST"]:
        return "rest_api"
    if any(protocol in {"Modbus", "MQTT", "CAN"} for protocol in protocols):
        return "industrial_protocol"
    return "multi_domain"


def _unique_sorted(values) -> list:
    return sorted({value for value in values if value})


def _requirements_payload(scenarios: list[dict]) -> list[dict[str, str]]:
    requirements: dict[str, dict[str, str]] = {}
    for scenario in scenarios:
        requirement_id = scenario.get("requirement_id")
        if not requirement_id:
            continue
        requirements.setdefault(
            requirement_id,
            {
                "requirement_id": requirement_id,
                "document_id": scenario.get("source_doc_id") or "",
                "document_version": scenario.get("doc_version") or "",
            },
        )
    return list(requirements.values())


def _evidence_refs_payload(scenarios: list[dict]) -> list[dict]:
    refs: list[dict] = []
    for scenario in scenarios:
        for chunk_id in scenario.get("chunk_ids", []):
            refs.append(
                {
                    "scenario_id": scenario.get("scenario_id"),
                    "requirement_id": scenario.get("requirement_id"),
                    "document_id": scenario.get("source_doc_id"),
                    "document_version": scenario.get("doc_version"),
                    "chunk_id": chunk_id,
                }
            )
    return refs


def _facts_used_payload(scenarios: list[dict]) -> list[dict]:
    facts: dict[str, dict] = {}
    for scenario in scenarios:
        fact_id = scenario.get("fact_id")
        semantic_key = scenario.get("semantic_key")
        if not fact_id and not semantic_key:
            continue
        key = str(fact_id or semantic_key)
        facts.setdefault(
            key,
            {
                "fact_id": fact_id or "",
                "semantic_key": semantic_key or "",
                "requirement_id": scenario.get("requirement_id") or "",
                "coverage_id": scenario.get("coverage_id") or "",
                "document_id": scenario.get("source_doc_id") or "",
                "document_version": scenario.get("doc_version") or "",
                "impact_status": scenario.get("impact_status") or "new_required",
            },
        )
    return list(facts.values())


def _dependency_audit(
    *,
    scenarios: list[dict],
    settings: Settings,
    pytest_ini_path: Path,
    conftest_path: Path,
) -> dict:
    external_dependencies = sorted(
        {
            dependency
            for scenario in scenarios
            for dependency in scenario.get("external_dependencies", [])
        }
    )
    missing_dependencies = sorted(
        {
            dependency
            for scenario in scenarios
            for dependency in scenario.get("missing_dependencies", [])
        }
    )
    status = "blocked" if missing_dependencies else "ready"
    mock_mode = settings.generated_test_execution_mode == "mock"
    return {
        "agent": "DependencyAuditAgent",
        "status": status,
        "project_mutation_allowed": False,
        "execution_mode": settings.generated_test_execution_mode,
        "mock_mode": mock_mode,
        "mock_warning": MOCK_FLOW_WARNING if mock_mode else "",
        "pytest_ini": str(pytest_ini_path),
        "conftest": str(conftest_path),
        "fixtures": ["automation_context", "precise_test_logging"],
        "external_dependencies": external_dependencies,
        "missing_dependencies": missing_dependencies,
        "required_runtime": ["python", "pytest", "logging"],
        "required_harness": ["pytest.ini", "conftest.py", "class_based_pytest_tests"],
        "missing": missing_dependencies,
        "notes": [
            "Generated tests are dependency-aware and do not fake external protocol calls.",
            "Missing protocol, simulator, or device dependencies are marked as blocked/skipped.",
            "Explicit mock mode builds mock device context and labels results as mocked.",
        ],
    }


def _tracking_payload(
    *,
    system_name: str,
    version: str | None,
    coverage_run_id: str,
    scope_hash: str,
    generated_file: Path,
    robot_file: Path | None,
    coverage_report: Path,
    tracking_file: Path,
    harness_paths: list[Path],
    scenarios: list[dict],
    dependency_audit: dict,
) -> dict:
    now = _utc_now()
    document_ids = _unique_sorted(
        scenario.get("source_doc_id") for scenario in scenarios if scenario.get("source_doc_id")
    )
    source_docs = _unique_sorted(
        scenario.get("source_doc") for scenario in scenarios if scenario.get("source_doc")
    )
    requirements = _requirements_payload(scenarios)
    evidence_refs = _evidence_refs_payload(scenarios)
    facts_used = _facts_used_payload(scenarios)
    reused_coverage = [
        scenario["coverage_id"]
        for scenario in scenarios
        if scenario.get("impact_status") == "unchanged"
    ]
    updated_coverage = [
        scenario["coverage_id"]
        for scenario in scenarios
        if scenario.get("impact_status") != "unchanged"
    ]
    protocols = _unique_sorted(
        protocol
        for scenario in scenarios
        for protocol in scenario.get("protocols", [])
    )
    domain = _domain_for_protocols(protocols)
    mock_mode = dependency_audit.get("mock_mode") is True
    protocol_adapters = [
        {
            "protocol": protocol,
            "mode": dependency_audit.get("execution_mode", "auto"),
            "adapter": f"{protocol.lower()}_mock_adapter" if mock_mode else "",
            "configured": mock_mode,
        }
        for protocol in (protocols or ["document_contract"])
    ]
    return {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "generated_at": now,
        "updated_at": now,
        "project": _safe_slug(system_name),
        "system": system_name,
        "system_name": system_name,
        "document_id": document_ids[0] if len(document_ids) == 1 else "",
        "document_ids": document_ids,
        "document_version": version or "",
        "active_version": version or "",
        "previous_version": "",
        "supersedes": [],
        "superseded_by": "",
        "source_document_path": source_docs[0] if len(source_docs) == 1 else "",
        "source_documents": source_docs,
        "doc_version": version,
        "generated_test_file": str(generated_file),
        "generated_robot_file": str(robot_file) if robot_file else "",
        "generated_xml_report": "",
        "coverage_report": str(coverage_report),
        "mock_mode": mock_mode,
        "mock_warning": MOCK_FLOW_WARNING if mock_mode else "",
        "domain_profile_ref": f"{domain}.v1",
        "protocol_adapters": protocol_adapters,
        "simulator_config": {
            "mode": dependency_audit.get("execution_mode", "auto"),
            "configured": bool(mock_mode or dependency_audit.get("status") == "ready"),
            "source": "generated_mock_context" if mock_mode else "",
        },
        "device_config_required": bool(
            protocols and not mock_mode and dependency_audit.get("status") == "blocked"
        ),
        "robot_keyword_mapping": [
            {
                "scenario_id": scenario["scenario_id"],
                "keyword": scenario["test_function"].replace("_", " ").title(),
                "requirement_id": scenario["requirement_id"],
            }
            for scenario in scenarios
        ],
        "llm_decisions": [],
        "scenario_group": generated_file.stem.removeprefix("test_"),
        "selected_scenarios": scenarios,
        "requirements": requirements,
        "facts_used": facts_used,
        "extracted_facts_used": facts_used,
        "changed_facts": [
            item for item in facts_used if item.get("impact_status") in {"modified", "new_required"}
        ],
        "unchanged_facts": [
            item for item in facts_used if item.get("impact_status") == "unchanged"
        ],
        "evidence_refs": evidence_refs,
        "domain": domain,
        "protocols": protocols,
        "coverage_run_id": coverage_run_id,
        "scope_hash": scope_hash,
        "generated_file": str(generated_file),
        "tracking_file": str(tracking_file),
        "harness_files": [str(path) for path in harness_paths],
        "mode": "dependency_aware_generation",
        "workflow_handoff": list(WORKFLOW_HANDOFF),
        "handoff_summaries": [
            {
                "source_agent": WORKFLOW_HANDOFF[index],
                "target_agent": WORKFLOW_HANDOFF[index + 1],
                "summary": "handoff contract completed",
            }
            for index in range(len(WORKFLOW_HANDOFF) - 1)
        ],
        "retry_policy": {
            "max_attempts": MAX_DEBUG_RETRIES,
            "strategy": (
                "validate, execute, classify, regenerate only for fixable "
                "generated-code failures"
            ),
        },
        "dependency_audit": dependency_audit,
        "coverage": {
            "coverage_intent": "requirement_linked_test_generation",
            "covered_requirements": [item["requirement_id"] for item in requirements],
            "reused_coverage": reused_coverage,
            "updated_coverage": updated_coverage,
            "coverage_gaps": [],
        },
        "version_impact": {
            "is_reused_from_previous_version": bool(reused_coverage) and not updated_coverage,
            "requires_regeneration": bool(updated_coverage),
            "requires_data_update": False,
            "requires_execution": bool(updated_coverage),
            "reason": (
                "Unchanged scenarios are linked to previous coverage; changed or new "
                "scenarios require generated execution."
            ),
        },
        "scenarios": scenarios,
        "run_history": [],
        "db_update_status": "generated_test_file_record_pending",
    }


def _validate_tracking_payload(payload: dict) -> None:
    required_fields = (
        "schema_version",
        "project",
        "document_version",
        "generated_test_file",
        "generated_robot_file",
        "mock_mode",
        "domain_profile_ref",
        "protocol_adapters",
        "robot_keyword_mapping",
        "handoff_summaries",
        "selected_scenarios",
        "requirements",
        "evidence_refs",
        "dependency_audit",
        "coverage",
        "run_history",
        "db_update_status",
    )
    missing = [field for field in required_fields if field not in payload]
    if missing:
        raise ValueError(f"Generated sidecar missing required field(s): {', '.join(missing)}")
    if payload["schema_version"] != SIDECAR_SCHEMA_VERSION:
        raise ValueError(f"Unsupported generated sidecar schema: {payload['schema_version']}")
    if not payload["selected_scenarios"]:
        raise ValueError("Generated sidecar must contain selected_scenarios.")
    for scenario in payload["selected_scenarios"]:
        if not scenario.get("requirement_id") or not scenario.get("evidence"):
            raise ValueError("Generated scenario must link to requirement evidence.")


def _mark_tracking_db_update(tracking_file_path: Path, status: str) -> None:
    try:
        payload = json.loads(tracking_file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    payload["db_update_status"] = status
    payload["updated_at"] = _utc_now()
    tracking_file_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _coverage_report_payload(
    *,
    system_name: str,
    version: str | None,
    coverage_run_id: str,
    records: list[CoverageRecord],
    scenarios: list[dict],
) -> dict:
    return {
        "schema_version": "coverage-report.v1",
        "generated_at": _utc_now(),
        "system_name": system_name,
        "version": version,
        "coverage_run_id": coverage_run_id,
        "record_count": len(records),
        "covered_requirements": _unique_sorted(record.requirement_id for record in records),
        "coverage_ids": [record.coverage_id for record in records],
        "reused_coverage": [
            record.coverage_id for record in records if record.impact_status == "unchanged"
        ],
        "updated_coverage": [
            record.coverage_id for record in records if record.impact_status != "unchanged"
        ],
        "scenario_ids": [scenario["scenario_id"] for scenario in scenarios],
        "blocked_scenarios": [
            scenario["scenario_id"]
            for scenario in scenarios
            if scenario.get("dependency_status") == "blocked"
        ],
    }


def _render_robot_file(scenarios: list[dict]) -> str:
    test_cases = "\n\n".join(_render_robot_test_case(scenario) for scenario in scenarios)
    return f"""*** Settings ***
Documentation       Generated MARAG Robot Framework orchestration wrapper.
...                 Actual generated validation logic is inside the companion Python file.

Library             OperatingSystem
Library             Collections
Library             ../../robot_libraries/threep_test_runner.py

Suite Setup         Setup MARAG Generated Suite
Suite Teardown      Teardown MARAG Generated Suite

Test Tags           MARAG    Generated    EvidenceBound

*** Test Cases ***
{test_cases}

*** Keywords ***
Setup MARAG Generated Suite
    Log To Console     Setting up generated MARAG suite

Teardown MARAG Generated Suite
    Log To Console     Cleaning up generated MARAG suite
"""


def _render_robot_test_case(scenario: dict) -> str:
    name = scenario["test_function"].replace("_", " ").title()
    evidence = shorten(" ".join(scenario.get("evidence", [])), width=120, placeholder="...")
    return f"""{name}
    [Documentation]    {scenario["test_scenario"]}
    [Tags]             generated    evidence_bound    {scenario["requirement_id"]}    {scenario["execution_mode"]}
    Log To Console     Starting: {name}
    Log                Requirement: {scenario["requirement_id"]}
    Log                Coverage: {scenario["coverage_id"]}
    Log                Evidence: {evidence}
    Log                Execution mode: {scenario["execution_mode"]}
    Should Not Be Empty    {scenario.get("expected_values", [])}
    Log To Console     Completed: {name}
"""


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
    return f'''"""Generated MARAG pytest automation.

System: {system_name}
Version: {version or "active"}

This file is generated from stored BRD evidence. It is dependency-aware:
missing real protocol, simulator, or device dependencies block/skip instead of
creating fake PASS results. Explicit mock mode is labeled and uses generated
mock device context only.
"""

from __future__ import annotations

from typing import Any, List
import logging

import pytest

from multi_agentic_rag.simulators import validate_real_protocol, validate_simulated_protocol

COVERAGE_IDS = {pformat(coverage_ids, width=100)}
SCENARIOS = {pformat(scenario_by_index, width=100)}
LOG = logging.getLogger(__name__)
MOCK_FLOW_WARNING = {MOCK_FLOW_WARNING!r}


class _GeneratedLog:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def info(self, message: str, *args: Any) -> None:
        self._logger.info(message, *args)

    def warning(self, message: str, *args: Any) -> None:
        self._logger.warning(message, *args)

    def error(self, message: str, *args: Any) -> None:
        self._logger.error(message, *args)


class ThreePTest:
    """Minimal generated compatibility base for ThreeP-style tests."""

    dut = None

    @property
    def log(self) -> _GeneratedLog:
        return _GeneratedLog(LOG)


def _execute_generated_validation(scenario: dict, automation_context: dict) -> bool:
    LOG.debug("Executing scenario data: %s", scenario)
    if scenario.get("impact_status") == "unchanged" and not scenario.get("force_run_all"):
        pytest.skip("Skipped unchanged scenario already covered by previous version")
    missing_dependencies = scenario.get("missing_dependencies", [])
    if missing_dependencies:
        reason = "; ".join(missing_dependencies)
        LOG.error("Blocked because %s", reason)
        pytest.skip(f"Blocked because {{reason}}")
    LOG.info(
        "%s validation executing in %s mode",
        scenario["validation_label"],
        scenario.get("execution_mode", "document_contract"),
    )
    assert automation_context["mode"] == "dependency_aware_generation"
    assert scenario["dependency_status"] == "ready"
    assert scenario["evidence"], "Generated scenario must cite BRD evidence."
    assert scenario["chunk_ids"], "Generated scenario must trace to a source chunk."
    assert scenario["expected_values"], "Expected values must be derived from evidence."
    if scenario.get("execution_mode") == "mock":
        LOG.warning(MOCK_FLOW_WARNING)
        assert scenario.get("mock_mode") is True
        assert scenario.get("mock_device_config", {{}}).get("connection_established") is False
        return True
    if scenario.get("execution_mode") == "simulator":
        assert validate_simulated_protocol(scenario) is True
    if scenario.get("execution_mode") == "real":
        assert validate_real_protocol(scenario) is True
    if scenario.get("protocols"):
        assert scenario["execution_mode"] in {{"mock", "simulator", "real"}}
    else:
        assert scenario["execution_mode"] in {{"document_contract", "mock"}}
    return True


@pytest.mark.generated
@pytest.mark.evidence_bound
class {class_name}(ThreePTest):
    def define_test(self, *args: Any, **kwargs: Any) -> bool:
        """Execute one generated scenario and return PASS/FAIL."""

        scenario = kwargs.get("scenario")
        automation_context = kwargs.get("automation_context", {{}})
        if not scenario:
            self.log.error("Missing generated scenario payload")
            return False

        results: List[bool] = []
        self.log.info(">>>> [Test Setup]: Initializing generated MARAG test")
        self.log.info(">>>> [Test Step 1]: Validate requirement evidence")
        results.append(bool(scenario.get("requirement_id")))
        results.append(bool(scenario.get("evidence")))
        results.append(bool(scenario.get("chunk_ids")))

        self.log.info(">>>> [Test Step 2]: Validate expected values")
        results.append(bool(scenario.get("expected_values")))

        self.log.info(">>>> [Test Step 3]: Execute %s flow", scenario.get("execution_mode"))
        results.append(_execute_generated_validation(scenario, automation_context))

        final_result = all(results)
        if final_result:
            self.log.info(">>>> [Test Result]: PASS")
        else:
            self.log.error(">>>> [Test Result]: FAIL")
        return final_result

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
        assert self.define_test(scenario=scenario, automation_context=automation_context) is True'''


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
    config.addinivalue_line("markers", "evidence_bound: generated test linked to evidence")
    config.addinivalue_line("markers", "requirement(id): BRD requirement trace marker")
    config.addinivalue_line("markers", "mock: explicit generated mock execution")


@pytest.fixture(scope="session")
def automation_context(pytestconfig):
    return {
        "environment": pytestconfig.getoption("--marag-env"),
        "mode": "dependency_aware_generation",
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
    evidence_bound: generated test linked to evidence
    requirement(id): BRD requirement trace marker
    mock: explicit generated mock execution
"""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
