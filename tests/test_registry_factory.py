from pathlib import Path

from multi_agentic_rag.config import Settings
from multi_agentic_rag.storage.postgres_registry import PostgresRegistry
from multi_agentic_rag.storage.registry import select_registry
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry


def test_registry_factory_defaults_to_local_sqlite_registry() -> None:
    settings = Settings(_env_file=None)

    selection = select_registry(settings)

    assert selection.provider == "sqlite"
    assert isinstance(selection.registry, SQLiteRegistry)
    assert "local document-ingestion registry" in selection.reason


def test_registry_factory_selects_postgresql_without_connecting() -> None:
    settings = Settings(
        registry_provider="postgresql",
        postgres_dsn="postgresql+psycopg://user:pass@db.example.com:5432/marag",
    )

    selection = select_registry(settings)

    assert selection.provider == "postgresql"
    assert isinstance(selection.registry, PostgresRegistry)
    assert selection.registry.dsn == "postgresql://user:pass@db.example.com:5432/marag"


def test_registry_factory_selects_sqlite_only_for_explicit_local_dev(tmp_path: Path) -> None:
    settings = Settings(
        registry_provider="sqlite",
        sqlite_db_path=tmp_path / "registry.db",
        allow_local_dev_mode=True,
        marag_target_mode="local",
        graphrag_required=False,
    )

    selection = select_registry(settings)

    assert selection.provider == "sqlite"
    assert isinstance(selection.registry, SQLiteRegistry)


def test_registry_factory_rejects_sqlite_when_local_dev_is_disabled(tmp_path: Path) -> None:
    settings = Settings(
        registry_provider="sqlite",
        sqlite_db_path=tmp_path / "registry.db",
        allow_local_dev_mode=False,
    )

    try:
        select_registry(settings)
    except RuntimeError as exc:
        assert "ALLOW_LOCAL_DEV_MODE=true" in str(exc)
    else:
        raise AssertionError("Expected strict mode to reject SQLite fallback")


def test_registry_factory_requires_postgres_dsn() -> None:
    settings = Settings(registry_provider="postgresql", postgres_dsn=None)

    try:
        select_registry(settings)
    except RuntimeError as exc:
        assert "POSTGRES_DSN" in str(exc)
    else:
        raise AssertionError("Expected PostgreSQL registry to require POSTGRES_DSN")
