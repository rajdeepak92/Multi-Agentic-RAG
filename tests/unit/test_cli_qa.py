from __future__ import annotations

import json

from typer.testing import CliRunner

import multi_agentic_rag.cli as cli
from multi_agentic_rag.runtime.config_loader import apply_project_config

runner = CliRunner()


def test_root_help_hides_workspace_and_cuda_cleanup_flags() -> None:
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "--workspace" not in result.output
    assert "--cuda" not in result.output
    assert "--cuda-required" not in result.output
    assert " init " not in result.output
    assert "ingest" in result.output
    assert "user-stories" in result.output
    assert "ingest-and-user-stories" in result.output
    assert "requirements" in result.output
    assert "requirements-audit" in result.output
    assert "requirements-rebuild" in result.output
    assert "chroma-reindex" in result.output


def test_base_config_reasoning_provider_projects_to_environment(tmp_path) -> None:
    config_path = tmp_path / "base_config.json"
    config_path.write_text(
        json.dumps(
            {
                "paths": {"cache_dir": ".global_cache", "generated_dir": "generated"},
                "reasoning": {"provider": "gemini"},
            }
        ),
        encoding="utf-8",
    )
    env: dict[str, str] = {}

    resolution = apply_project_config(tmp_path, environ=env)

    assert resolution.config_path == config_path
    assert env["REASONING_PROVIDER"] == "gemini"


def test_alembic_revision_status_reports_migration_behind(monkeypatch) -> None:
    def fake_run_alembic(args: list[str]) -> tuple[int, str]:
        if args == ["current"]:
            return 0, "20260620_0003"
        if args == ["heads"]:
            return 0, "20260620_0004 (head)"
        raise AssertionError(args)

    monkeypatch.setattr(cli, "_run_alembic", fake_run_alembic)

    ready, detail = cli._alembic_revision_status("postgresql://u:pw@example/db")

    assert ready is False
    assert "current=20260620_0003, head=20260620_0004" in detail
    assert "uv run --no-sync alembic upgrade head" in detail


def test_alembic_revision_status_reports_possible_wrong_dsn_and_redacts(monkeypatch) -> None:
    def fake_run_alembic(args: list[str]) -> tuple[int, str]:
        if args == ["current"]:
            return 0, ""
        if args == ["heads"]:
            return 0, "20260620_0004 (head)"
        raise AssertionError(args)

    monkeypatch.setattr(cli, "_run_alembic", fake_run_alembic)

    ready, detail = cli._alembic_revision_status("postgresql://u:pw@example/db")

    assert ready is False
    assert "verify the DSN points at the migrated database" in detail
    assert "pw" not in detail
    assert "***" in detail
