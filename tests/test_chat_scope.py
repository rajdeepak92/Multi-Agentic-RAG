from multi_agentic_rag.retrieval import answer_query


def test_document_scoped_chat_rejects_missing_system() -> None:
    result = answer_query("What is the current threshold?")

    assert not result.supported
    assert "requires --system" in result.answer


def test_document_scoped_chat_rejects_framework_questions() -> None:
    result = answer_query("Explain the framework architecture", system_name="PROJECT_1")

    assert not result.supported
    assert "out-of-scope" in result.answer
