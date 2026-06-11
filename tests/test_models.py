from multi_agentic_rag.models import DeltaRecord, DocumentRecord, DocumentStatus


def test_document_model_tracks_lineage() -> None:
    document = DocumentRecord(
        document_id="doc_1",
        system_name="SIIMCS",
        version="v2",
        status=DocumentStatus.ACTIVE,
        source_path="brd_v2.pdf",
        source_name="brd_v2.pdf",
        content_hash="abc",
        supersedes="doc_0",
    )

    assert document.status == DocumentStatus.ACTIVE
    assert document.supersedes == "doc_0"


def test_delta_contract_contains_evidence() -> None:
    delta = DeltaRecord(
        delta_id="delta_1",
        system_name="SIIMCS",
        from_version="v1",
        to_version="v2",
        change_type="modified",
        change_magnitude="major",
        old_value="80 C",
        new_value="95 C",
        risk_level="high",
        evidence=["old evidence", "new evidence"],
    )

    assert delta.evidence
    assert delta.risk_level == "high"
