from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from multi_agentic_rag import cli
from multi_agentic_rag.config import Settings

runner = CliRunner()


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        postgres_dsn="postgresql+asyncpg://user:pass@localhost/db",
        project_root=tmp_path,
        global_cache_dir=tmp_path / ".global_cache",
        model_cache_dir=tmp_path / ".global_cache" / "models",
        database_cache_dir=tmp_path / ".global_cache" / "db",
        vectorstore_cache_dir=tmp_path / ".global_cache" / "vectorstore",
        graph_cache_dir=tmp_path / ".global_cache" / "neo4j",
        hf_home=tmp_path / ".global_cache" / "models" / "huggingface",
        transformers_cache=tmp_path / ".global_cache" / "models" / "transformers",
        sentence_transformers_home=(
            tmp_path / ".global_cache" / "models" / "sentence_transformers"
        ),
        torch_home=tmp_path / ".global_cache" / "models" / "torch",
        hf_reason_cache_dir=tmp_path / ".global_cache" / "models" / "hf_reasoning",
        chroma_path=tmp_path / ".global_cache" / "vectorstore" / "chroma",
        multi_agentic_rag_home=tmp_path / ".global_cache" / "runtime",
        document_store_path=tmp_path / ".global_cache" / "runtime" / "documents",
        object_store_path=tmp_path / ".global_cache" / "runtime" / "objects",
        manifest_store_path=tmp_path / ".global_cache" / "runtime" / "manifests",
        _env_file=None,
    )


def test_delete_runtime_cache_removes_runtime_and_repo_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = _settings(tmp_path)
    settings.ensure_project_cache_paths()
    (settings.chroma_path / "data_level0.bin").write_text("cache", encoding="utf-8")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "item").write_text("cache", encoding="utf-8")

    deleted, skipped = cli._delete_runtime_cache(settings)

    assert skipped == []
    assert settings.global_cache_dir.resolve() in deleted
    assert (tmp_path / ".cache").resolve() in deleted
    assert not settings.global_cache_dir.exists()
    assert not (tmp_path / ".cache").exists()


def test_delete_runtime_cache_reports_locked_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = _settings(tmp_path)
    settings.ensure_project_cache_paths()
    (tmp_path / ".cache").mkdir()

    def fake_delete(path: Path) -> str | None:
        return "locked" if path == settings.global_cache_dir.resolve() else None

    monkeypatch.setattr(cli, "_delete_path_with_retries", fake_delete)

    deleted, skipped = cli._delete_runtime_cache(settings)

    assert deleted == [(tmp_path / ".cache").resolve()]
    assert skipped == [(settings.global_cache_dir.resolve(), "locked")]


def test_clean_postgres_state_all_scope_outputs_deleted_count(tmp_path, monkeypatch) -> None:
    repo = _FakePostgresRepository({"chunks": 2, "facts": 3})
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        cli.PostgresKnowledgeRepository,
        "from_settings",
        staticmethod(lambda settings: repo),
    )

    result = runner.invoke(cli.app, ["clean-postgres-state", "--all", "--yes"])

    assert result.exit_code == 0
    assert repo.calls == [{"system_name": None, "kb_name": None}]
    assert (tmp_path / ".global_cache").exists()
    assert "Clean PostgreSQL State" in result.output
    assert "PostgreSQL rows" in result.output
    assert "5" in result.output


def test_clean_postgres_state_system_kb_scope(tmp_path, monkeypatch) -> None:
    repo = _FakePostgresRepository({"chunks": 4})
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        cli.PostgresKnowledgeRepository,
        "from_settings",
        staticmethod(lambda settings: repo),
    )

    result = runner.invoke(
        cli.app,
        [
            "clean-postgres-state",
            "--system",
            "PROJECT_1",
            "--kb",
            "default",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert repo.calls == [{"system_name": "PROJECT_1", "kb_name": "default"}]


def test_clean_chroma_state_outputs_deleted_count(tmp_path, monkeypatch) -> None:
    repo = _FakeChromaRepository(deleted=7)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        cli.ChromaVectorRepository,
        "from_settings",
        staticmethod(lambda settings: repo),
    )

    result = runner.invoke(
        cli.app,
        ["clean-chroma-state", "--system", "PROJECT_1", "--yes"],
    )

    assert result.exit_code == 0
    assert repo.calls == [{"system_name": "PROJECT_1", "kb_name": None}]
    assert repo.closed is True
    assert "Clean Chroma State" in result.output
    assert "Chroma vectors" in result.output
    assert "7" in result.output


def test_clean_neo4j_state_outputs_deleted_count(tmp_path, monkeypatch) -> None:
    repo = _FakeNeo4jRepository(deleted=9)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(cli, "Neo4jGraphRepository", lambda settings: repo)

    result = runner.invoke(cli.app, ["clean-neo4j-state", "--all", "--yes"])

    assert result.exit_code == 0
    assert repo.calls == [{"system_name": None, "kb_name": None}]
    assert repo.closed is True
    assert "Clean Neo4j State" in result.output
    assert "Neo4j nodes" in result.output
    assert "9" in result.output


@pytest.mark.parametrize(
    ("command", "args", "message"),
    [
        ("clean-postgres-state", [], "Provide --system or --all"),
        (
            "clean-chroma-state",
            ["--all", "--system", "PROJECT_1"],
            "Use either --all or --system",
        ),
        ("clean-neo4j-state", ["--all", "--kb", "default"], "--kb can only be used"),
    ],
)
def test_individual_cleanup_commands_reject_invalid_scopes(command, args, message) -> None:
    result = runner.invoke(cli.app, [command, *args, "--yes"])

    assert result.exit_code == 1
    assert message in result.output


def test_clean_chroma_state_confirmation_decline_skips_backend(tmp_path, monkeypatch) -> None:
    repo = _FakeChromaRepository(deleted=7)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        cli.ChromaVectorRepository,
        "from_settings",
        staticmethod(lambda settings: repo),
    )

    result = runner.invoke(
        cli.app,
        ["clean-chroma-state", "--system", "PROJECT_1"],
        input="n\n",
    )

    assert result.exit_code == 1
    assert repo.calls == []


def test_clean_system_state_still_cleans_all_backends(tmp_path, monkeypatch) -> None:
    postgres_repo = _FakePostgresRepository({"chunks": 2, "facts": 3})
    chroma_repo = _FakeChromaRepository(deleted=7)
    neo4j_repo = _FakeNeo4jRepository(deleted=9)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        cli.PostgresKnowledgeRepository,
        "from_settings",
        staticmethod(lambda settings: postgres_repo),
    )
    monkeypatch.setattr(
        cli.ChromaVectorRepository,
        "from_settings",
        staticmethod(lambda settings: chroma_repo),
    )
    monkeypatch.setattr(cli, "Neo4jGraphRepository", lambda settings: neo4j_repo)

    result = runner.invoke(
        cli.app,
        ["clean-system-state", "--system", "PROJECT_1", "--kb", "default", "--yes"],
    )

    assert result.exit_code == 0
    assert postgres_repo.calls == [{"system_name": "PROJECT_1", "kb_name": "default"}]
    assert chroma_repo.calls == [{"system_name": "PROJECT_1", "kb_name": "default"}]
    assert neo4j_repo.calls == [{"system_name": "PROJECT_1", "kb_name": "default"}]
    assert "PostgreSQL rows" in result.output
    assert "Chroma vectors" in result.output
    assert "Neo4j nodes" in result.output


class _FakePostgresRepository:
    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts
        self.calls: list[dict[str, str | None]] = []

    async def clear(
        self,
        *,
        system_name: str | None = None,
        kb_name: str | None = None,
    ) -> dict[str, int]:
        self.calls.append({"system_name": system_name, "kb_name": kb_name})
        return self.counts


class _FakeChromaRepository:
    def __init__(self, *, deleted: int) -> None:
        self.deleted = deleted
        self.calls: list[dict[str, str | None]] = []
        self.closed = False

    def clear(
        self,
        *,
        system_name: str | None = None,
        kb_name: str | None = None,
    ) -> int:
        self.calls.append({"system_name": system_name, "kb_name": kb_name})
        return self.deleted

    def close(self) -> None:
        self.closed = True


class _FakeNeo4jRepository:
    def __init__(self, *, deleted: int) -> None:
        self.deleted = deleted
        self.calls: list[dict[str, str | None]] = []
        self.closed = False

    def check_connection(self) -> tuple[bool, str]:
        return True, "ok"

    def clear(
        self,
        *,
        system_name: str | None = None,
        kb_name: str | None = None,
    ) -> int:
        self.calls.append({"system_name": system_name, "kb_name": kb_name})
        return self.deleted

    def close(self) -> None:
        self.closed = True
