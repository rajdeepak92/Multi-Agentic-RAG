from __future__ import annotations

from pathlib import Path

from multi_agentic_rag import cli
from multi_agentic_rag.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        postgres_dsn="postgresql+asyncpg://user:pass@localhost/db",
        multi_agentic_rag_home=tmp_path / ".multi_agentic_rag",
        document_store_path=tmp_path / ".multi_agentic_rag" / "documents",
        object_store_path=tmp_path / ".multi_agentic_rag" / "objects",
        manifest_store_path=tmp_path / ".multi_agentic_rag" / "manifests",
        chroma_path=tmp_path / ".multi_agentic_rag" / "chroma",
    )


def test_delete_runtime_cache_removes_runtime_and_repo_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = _settings(tmp_path)
    settings.chroma_path.mkdir(parents=True)
    settings.document_store_path.mkdir(parents=True)
    (settings.chroma_path / "data_level0.bin").write_text("cache", encoding="utf-8")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "item").write_text("cache", encoding="utf-8")

    deleted, skipped = cli._delete_runtime_cache(settings)

    assert skipped == []
    assert settings.multi_agentic_rag_home.resolve() in deleted
    assert (tmp_path / ".cache").resolve() in deleted
    assert not settings.multi_agentic_rag_home.exists()
    assert not (tmp_path / ".cache").exists()


def test_delete_runtime_cache_reports_locked_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = _settings(tmp_path)
    settings.multi_agentic_rag_home.mkdir(parents=True)
    (tmp_path / ".cache").mkdir()

    def fake_delete(path: Path) -> str | None:
        return "locked" if path == settings.multi_agentic_rag_home.resolve() else None

    monkeypatch.setattr(cli, "_delete_path_with_retries", fake_delete)

    deleted, skipped = cli._delete_runtime_cache(settings)

    assert deleted == [(tmp_path / ".cache").resolve()]
    assert skipped == [(settings.multi_agentic_rag_home.resolve(), "locked")]
