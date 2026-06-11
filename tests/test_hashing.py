from pathlib import Path

from multi_agentic_rag.utils.hashing import sha256_file, sha256_text, stable_id


def test_sha256_text_is_consistent() -> None:
    assert sha256_text("temperature threshold 80 C") == sha256_text(
        "temperature threshold 80 C"
    )


def test_stable_id_is_consistent() -> None:
    assert stable_id("doc", "SIIMCS", "v1", "a.pdf") == stable_id(
        "doc",
        "SIIMCS",
        "v1",
        "a.pdf",
    )


def test_sha256_file_is_consistent(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("content", encoding="utf-8")
    assert sha256_file(path) == sha256_file(path)
