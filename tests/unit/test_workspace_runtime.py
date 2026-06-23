from __future__ import annotations

import json
import logging

import pytest

from multi_agentic_rag.common_defs import (
    BASE_CONFIG_NAME,
    GENERATED_DIR_NAME,
    GLOBAL_CACHE_DIR_NAME,
)
from multi_agentic_rag.exceptions import ConfigError
from multi_agentic_rag.runtime.config_loader import (
    apply_project_config,
    resolve_config_value,
)
from multi_agentic_rag.runtime.device import resolve_device
from multi_agentic_rag.runtime.logging import configure_runtime_logging
from multi_agentic_rag.runtime.path_resolver import resolve_ingestion_inputs
from multi_agentic_rag.runtime.project import initialize_project_root, resolve_project_root
from multi_agentic_rag.runtime.run_context import create_run_context
from multi_agentic_rag.runtime.secrets import redact_secrets


def test_project_root_init_creates_config_dirs_and_gitignore(tmp_path) -> None:
    project_root = initialize_project_root(tmp_path / "repo")

    gitignore = (project_root / ".gitignore").read_text(encoding="utf-8")

    assert (project_root / BASE_CONFIG_NAME).exists()
    assert (project_root / "documents").is_dir()
    assert (project_root / GLOBAL_CACHE_DIR_NAME).is_dir()
    assert (project_root / GENERATED_DIR_NAME).is_dir()
    assert "/base_config.json" not in gitignore
    assert "/.global_cache/" in gitignore


def test_apply_project_config_uses_env_over_config_and_does_not_rewrite(tmp_path) -> None:
    project_root = initialize_project_root(tmp_path / "repo")
    config_path = project_root / BASE_CONFIG_NAME
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["embeddings"]["model"] = "config-model"
    config_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    original = config_path.read_text(encoding="utf-8")
    env = {"EMBEDDING_MODEL": "env-model"}

    resolution = apply_project_config(project_root, environ=env)

    assert env["EMBEDDING_MODEL"] == "env-model"
    assert env["PROJECT_ROOT"] == str(project_root)
    assert resolution.config["embeddings"]["model"] == "config-model"
    assert config_path.read_text(encoding="utf-8") == original


def test_resolve_project_root_finds_base_config_without_workspace_marker(tmp_path) -> None:
    project_root = initialize_project_root(tmp_path / "repo")
    child = project_root / "documents" / "nested"
    child.mkdir(parents=True)

    assert resolve_project_root(cwd=child) == project_root


def test_resolve_project_root_accepts_explicit_config_path(tmp_path) -> None:
    project_root = initialize_project_root(tmp_path / "repo with spaces")

    assert (
        resolve_project_root(explicit_config_path=project_root / BASE_CONFIG_NAME)
        == project_root
    )


def test_apply_project_config_rejects_paths_outside_project(tmp_path) -> None:
    project_root = initialize_project_root(tmp_path / "repo")
    config_path = project_root / BASE_CONFIG_NAME
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["paths"]["cache_dir"] = str(tmp_path / "outside")
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ConfigError, match="outside PROJECT_ROOT"):
        apply_project_config(project_root, environ={})


def test_device_auto_uses_cpu_when_cuda_is_unavailable(monkeypatch) -> None:
    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class FakeTorch:
        cuda = FakeCuda()

    monkeypatch.setattr(
        "multi_agentic_rag.runtime.device.import_module",
        lambda name: FakeTorch,
    )

    assert resolve_device("auto", purpose="test").resolved == "cpu"


def test_device_cuda_fails_when_unavailable(monkeypatch) -> None:
    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class FakeTorch:
        cuda = FakeCuda()

    monkeypatch.setattr(
        "multi_agentic_rag.runtime.device.import_module",
        lambda name: FakeTorch,
    )

    with pytest.raises(ConfigError, match="requested CUDA"):
        resolve_device("cuda", purpose="test")


def test_resolve_config_value_precedence(monkeypatch) -> None:
    monkeypatch.setenv("QA_VALUE", "env")

    assert resolve_config_value("x.y", cli_value="cli", env_name="QA_VALUE")[0] == "cli"
    assert resolve_config_value("x.y", env_name="QA_VALUE")[0] == "env"
    assert resolve_config_value("x.y", config={"x": {"y": "config"}})[0] == "config"
    assert resolve_config_value("x.y", default="default")[0] == "default"


def test_run_context_creates_expected_layout_and_redacts_manifest(tmp_path) -> None:
    project_root = initialize_project_root(tmp_path / "repo")

    context = create_run_context(project_root, command="qa-doctor")
    context.write_manifest(secret_payload={"postgres_dsn": "postgresql://u:pw@example/db"})

    assert context.run_id.startswith("RUN_")
    assert (context.run_dir / "logs" / "run.log").parent.is_dir()
    assert (context.run_dir / "results" / "artifacts" / "user_stories").is_dir()
    assert (context.run_dir / "results" / "debug").is_dir()
    manifest = context.manifest_path.read_text(encoding="utf-8")
    assert "pw" not in manifest
    assert "***" in manifest


def test_runtime_logging_redacts_file_logs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://user:secret@example/db")
    log_path = tmp_path / "run.log"
    configure_runtime_logging(level="INFO", log_path=log_path)

    logging.getLogger("test").error("dsn=%s", "postgresql://user:secret@example/db")

    text = log_path.read_text(encoding="utf-8")
    assert "secret" not in text
    assert "***" in text


def test_redact_secrets_handles_nested_payloads() -> None:
    payload = {"token": "abc", "safe": ["postgresql://u:pw@example/db"]}

    redacted = redact_secrets(payload)

    assert redacted["token"] == "***"
    assert redacted["safe"] == ["postgresql://u:***@example/db"]


def test_path_resolver_accepts_single_file_and_rejects_metadata_conflict(tmp_path) -> None:
    source = tmp_path / "PROJECT_1_BRD_v1.md"
    source.write_text("REQ-1", encoding="utf-8")

    item = resolve_ingestion_inputs(source, system="PROJECT_1", version="v1")[0]

    assert item.system == "PROJECT_1"
    assert item.version == "v1"
    with pytest.raises(ConfigError, match="System conflict"):
        resolve_ingestion_inputs(source, system="OTHER", version="v1")


def test_path_resolver_rejects_mixed_directory_without_manifest(tmp_path) -> None:
    (tmp_path / "PROJECT_1_BRD_v1.md").write_text("REQ-1", encoding="utf-8")
    (tmp_path / "PROJECT_2_BRD_v1.md").write_text("REQ-2", encoding="utf-8")

    with pytest.raises(ConfigError, match="mixed systems or versions"):
        resolve_ingestion_inputs(tmp_path)


def test_path_resolver_manifest_disambiguates_directory_batch(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("REQ-1", encoding="utf-8")
    (docs / "b.md").write_text("REQ-2", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {"path": "a.md", "system": "PROJECT_1", "version": "v1", "kb": "default"},
                    {"path": "b.md", "system": "PROJECT_2", "version": "v2", "kb": "default"},
                ]
            }
        ),
        encoding="utf-8",
    )

    items = resolve_ingestion_inputs(docs, manifest_path=manifest)

    assert [(item.path.name, item.system, item.version) for item in items] == [
        ("a.md", "PROJECT_1", "v1"),
        ("b.md", "PROJECT_2", "v2"),
    ]
