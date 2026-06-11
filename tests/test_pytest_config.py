from pathlib import Path
import tomllib


def test_pytest_config_limits_discovery_to_tests() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    pytest_config = config["tool"]["pytest"]["ini_options"]

    assert pytest_config["testpaths"] == ["tests"]
    assert pytest_config["pythonpath"] == ["src"]
    assert pytest_config["addopts"] == "-ra --strict-config --strict-markers"
    for ignored in (
        ".git",
        ".venv",
        ".multi_agentic_rag",
        ".cache",
        "generated",
        "**pycache**",
        "AppData",
        "site-packages",
        "archive-v0",
    ):
        assert ignored in pytest_config["norecursedirs"]
