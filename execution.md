# MARAG Execution Guide

This guide explains how Multi-Agentic-RAG (MARAG) currently works for document
ingestion, document-grounded chat, coverage planning, dependency-aware pytest automation
generation, testcase execution, and result tracking.

MARAG is local-first. It does not use Docker. Neo4j, Weaviate, OpenAI, and
HuggingFace-backed models can be enabled, but the current automation
execution path can run with local Python, pytest, SQLite, and ingested evidence.

For the forward-looking roadmap toward GraphRAG-backed QA automation,
LangGraph workflows, domain adapters, mock/simulator-backed pytest generation,
and future Robot Framework mapping, see `STRATEGIC_UPDATE_PLAN.md`,
`UPDATED_GOAL.md`, `EXECUTION_FLOW.md`, and `TEST_GENERATION_STRATEGY.md`.

## 1. Supported Task Types

MARAG currently routes work into three practical task types:

1. Ingest documents and keep local stores up to date.
2. Generate dependency-aware automation-style pytest tests from an instructed document.
3. Answer informative chatbot questions from ingested document evidence.

The current task router uses service-backed LangGraph workflow wrappers and
delegates generation/execution to deterministic Python services. The generated
JSON records the agent-style handoff for deeper node decomposition later.

## 2. Fresh Windows Setup

Install these first:

- Python 3.12 or newer
- uv
- PowerShell
- Neo4j Desktop, optional for graph traversal
- Weaviate, optional for primary vector search
- OpenAI or Azure OpenAI key, optional for later LLM-backed generation

From PowerShell:

```powershell
cd "D:\Multi-Agentic-RAG"
python --version
uv --version
uv sync
```

Create `.env`. If `.env.example` exists in your checkout, copy it first:

```powershell
copy .env.example .env
notepad .env
```

Minimum local `.env`:

```env
MULTI_AGENTIC_RAG_HOME=.multi_agentic_rag
SQLITE_DB_PATH=.multi_agentic_rag/registry.db
OBJECT_STORE_PATH=.multi_agentic_rag/objects

VECTOR_STORE_PROVIDER=auto
WEAVIATE_URL=
CHROMA_PATH=.multi_agentic_rag/chroma
KEYWORD_INDEX_ENABLED=true

NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<your_neo4j_password>
GRAPHRAG_REQUIRED=true

EMBEDDING_PROVIDER=huggingface
DEFAULT_EMBEDDING_MODEL=BAAI/bge-m3

LLM_PROVIDER=none
OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_DEPLOYMENT=
```

Initialize and validate:

```powershell
uv run multi-agentic-rag init
uv run multi-agentic-rag doctor
uv run pytest -c pyproject.toml tests
```

Neo4j and Weaviate may warn if they are not running. That is a setup signal,
not a local test-generation blocker.

For real GraphRAG runs, keep `GRAPHRAG_REQUIRED=true` and start Neo4j before
ingestion. For deterministic tests or offline smoke runs only, use
`EMBEDDING_PROVIDER=hash` and `GRAPHRAG_REQUIRED=false`.

## 3. Document Inbox Convention

Use this source inbox convention:

```text
documents/inbox/PROJECT_1/
```

Example files:

```text
documents/inbox/PROJECT_1/PROJECT_1_BRD_V1.pdf
documents/inbox/PROJECT_1/PROJECT_1_PROTOCOL_V1.docx
```

MARAG copies managed source files into `.multi_agentic_rag/documents`, stores
parsed artifacts in `.multi_agentic_rag/objects`, stores metadata in SQLite,
indexes keywords with SQLite FTS5/BM25, writes vectors to Weaviate or Chroma,
and writes Neo4j graph data only when Neo4j is reachable.

## 4. Ingest Documents

Ingest one document:

```powershell
uv run multi-agentic-rag ingest-doc "documents\inbox\PROJECT_1\PROJECT_1_BRD_V1.pdf" --system PROJECT_1 --version v1
```

Ingest every supported file in a folder:

```powershell
uv run multi-agentic-rag ingest-folder "documents\inbox\PROJECT_1" --system PROJECT_1 --version v1
```

What happens:

- PDF/DOCX text is parsed.
- Text is chunked with source, page, system, and version metadata.
- Requirement, sensor, protocol, endpoint, threshold, topic, and test facts are extracted.
- Chunks and facts are stored in SQLite.
- Keyword and vector indexes are updated.
- Neo4j graph updates are attempted only if Neo4j is reachable.

Multiple documents can remain active under the same `system/version` scope.

## 5. Informative Chatbot Flow

Use this when the user wants information only:

```powershell
uv run multi-agentic-rag query "What are the covered areas of BRD V1?" --system PROJECT_1 --version v1
```

or through the task router:

```powershell
uv run multi-agentic-rag task "Tell me what is covered in BRD V1" --system PROJECT_1 --version v1
```

MARAG retrieves graph, vector, keyword, and registry evidence. It returns
evidence-linked answers and does not generate or execute test files for
read-only questions.

## 6. Coverage Planning

Generate requirement-linked scenarios:

```powershell
uv run multi-agentic-rag coverage-plan --system PROJECT_1 --version v1 --count 25
```

What happens:

- MARAG checks stored document evidence for the requested system/version.
- Requirement-linked evidence is mandatory.
- Each scenario is linked to a requirement ID, document ID, version, chunk ID,
  evidence text, and source hash.
- A `coverage_run` row is stored in SQLite.
- If the same document scope is already covered, MARAG reuses the prior run
  unless forced.

No evidence means no coverage claim.

## 7. Test-Automation Generation Flow

Generate pytest automation artifacts:

```powershell
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 5
```

Current generated layout:

```text
generated/
  project_1/
    brd_v1/
      test_project_1_brd_v1.py
      test_project_1_brd_v1.json
      conftest.py
      pytest.ini
```

The generated directory is ignored by normal project pytest discovery and by
git. MARAG executes generated tests explicitly through its runner.

The generation handoff recorded in JSON is:

```text
IntentRouter
DocumentResolver
EvidenceCollector
ScenarioSelector
TestPlanAgent
DependencyAuditAgent
HarnessAgent
TestCodeWriterAgent
PytestValidationAgent
ExecutionAgent
FailureDebuggerAgent
TrackingJsonAgent
DbUpdateAgent
```

The task router runs through LangGraph workflow wrappers. The individual
test-generation substeps are still implemented as deterministic services.

## 8. Generated Pytest Behavior

Generated tests are class-based pytest scripts.

Each test function:

- Checks that `coverage_id` exists.
- Checks that `requirement_id` exists.
- Checks that evidence is present.
- Checks that at least one source chunk ID is present.
- Checks that expected values were derived from evidence.
- Calls a dependency-aware validation helper.
- Blocks/skips when protocol, simulator, or device configuration is missing.
- In explicit mock mode, asserts deterministic evidence-derived checks.

The helper logs with precise levels:

- `DEBUG` for scenario data.
- `ERROR` for blocked dependency reasons.
- `INFO` for validation mode and label.

Current behavior does not call real MQTT, REST, CAN, Modbus, device, or
application interfaces unless configuration exists. Missing dependencies are
reported as blocked/skipped instead of fake passes.

Example generated log message:

```text
protocol/interface behavior validation executing in mock mode
```

## 9. Tracking JSON Contract

Each generated test file has a sidecar JSON file. For example:

```text
generated/project_1/brd_v1/test_project_1_brd_v1.json
```

The JSON stores:

- `schema_version`
- `system_name`
- `doc_version`
- `coverage_run_id`
- `scope_hash`
- `generated_test_file`
- `generated_file`
- `selected_scenarios`
- `requirements`
- `evidence_refs`
- `harness_files`
- `protocols`
- `domain`
- `dependency_audit`
- `retry_policy`
- `workflow_handoff`
- `scenarios`
- `run_history`

Each scenario stores:

- `requirement_id`
- `source_doc`
- `doc_version`
- `chunk_ids`
- `expected_values`
- `priority`
- `generated_file`
- `test_function`
- `evidence`
- `last_run_status` after execution

After execution, the runner adds `run_1`, `run_2`, and so on:

```json
{
  "state": "executed",
  "status": "PASS",
  "passed": 5,
  "failed": 0,
  "skipped": 0
}
```

For now, the JSON is the detailed trace artifact. SQLite also stores generated
test file records and test run result records. Later, the JSON schema can be
moved into a database trace table and kept only as an export artifact.

## 10. Dependency Audit Behavior

The generator does not freely mutate project dependencies.

Generated tests always require the local pytest harness:

- Python
- pytest
- logging
- generated `pytest.ini`
- generated `conftest.py`

If a BRD scenario requires MQTT, REST, CAN, Modbus, or another interface,
MARAG records the missing endpoint, simulator, or client configuration in the
dependency audit and run result. Project dependency changes still require an
approved implementation step.

## 11. Execute Generated Testcases

Run generated testcases:

```powershell
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 5
```

What happens:

1. MARAG generates or reuses the artifact set.
2. The runner validates the generated Python file with `py_compile`.
3. The runner executes pytest from the generated artifact folder.
4. Pytest uses the generated `pytest.ini` and `conftest.py`.
5. The runner parses passed, failed, and skipped counts.
6. The runner classifies dependency/service blockers.
7. SQLite receives the execution result.
8. The sidecar JSON receives `run_1` or the next run key.

Current successful example:

```text
executed: Test run passed: 5 passed, 0 failed, 0 skipped.
```

## 12. Failure And Retry Behavior

The retry loop is controlled:

```text
generate
validate syntax
run pytest
classify failure
regenerate only if failure is fixable generated-code failure
retry up to 5 attempts
record result in SQLite and JSON
```

Missing modules, refused connections, timeouts, and unavailable protocol
services are recorded as blockers. MARAG does not rewrite generated code
repeatedly for an environment failure.

After fixing an environment issue, rerun:

```powershell
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 5
```

## 13. Last Result Without Rerun

Read the latest stored result:

```powershell
uv run multi-agentic-rag last-results --system PROJECT_1 --version v1
```

This reads SQLite and does not execute pytest.

## 14. Natural-Language Task Examples

Generate testcases:

```powershell
uv run multi-agentic-rag task "Generate 5 testcases for BRD V1" --system PROJECT_1 --version v1 --count 5
```

Run testcases:

```powershell
uv run multi-agentic-rag task "Run the testcases for BRD V1" --system PROJECT_1 --version v1 --count 5
```

Show prior result:

```powershell
uv run multi-agentic-rag task "Show me the last test result for BRD V1" --system PROJECT_1 --version v1
```

Ask a read-only question:

```powershell
uv run multi-agentic-rag task "What threshold is defined in BRD V1?" --system PROJECT_1 --version v1
```

Task routing behavior:

- Requests to generate/write/create testcases route to testcase generation.
- Requests to run/execute testcases route to testcase execution.
- Requests for last/previous results route to stored result lookup.
- Other document questions route to evidence-based retrieval.

## 15. New Version Flow

When a newer document arrives:

```text
documents/inbox/PROJECT_1/PROJECT_1_BRD_V2.pdf
```

Run:

```powershell
uv run multi-agentic-rag ingest-doc "documents\inbox\PROJECT_1\PROJECT_1_BRD_V2.pdf" --system PROJECT_1 --version v2
uv run multi-agentic-rag delta --system PROJECT_1 --from v1 --to v2
uv run multi-agentic-rag coverage-plan --system PROJECT_1 --version v2 --count 5
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v2 --count 5
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v2 --count 5
```

V2 artifacts are written under:

```text
generated/project_1/brd_v2/
```

MARAG keeps old evidence, preserves prior V1 results, computes deltas from
stored facts, and creates separate V2 coverage/test artifacts.

## 16. API Happy Path

Start API:

```powershell
uv run multi-agentic-rag api
```

Useful endpoints:

- `POST /documents/ingest`
- `POST /query`
- `POST /tasks`
- `POST /coverage/plan`
- `POST /tests/generate`
- `POST /tests/run`
- `POST /tests/last-result`

Example task request:

```json
{
  "request": "Generate 5 testcases for BRD V1",
  "system": "PROJECT_1",
  "version": "v1",
  "scenario_count": 5
}
```

## 17. What MARAG Does Not Do Silently

- It does not hard-delete old evidence.
- It does not claim coverage without requirement-linked evidence.
- It does not regenerate existing coverage for the same document hash unless forced.
- It does not run tests when the user only asks for last results.
- It does not hide missing dependencies; blockers are reported and stored.
- It does not mutate dependencies from inside testcase generation.
- It does not treat superseded evidence as current truth unless a version is requested.
- It does not call real external interfaces unless the required dependency
  configuration is present.
