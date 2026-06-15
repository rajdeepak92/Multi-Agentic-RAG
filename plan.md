# MARAG Phase 2 Plan: Agentic QA Automation Framework

  ## Summary

  - Evolve MARAG from deterministic GraphRAG + pytest scaffold into an agentic QA automation framework
    where the LLM makes structured decisions and Python agents execute deterministic work.

  - Keep local-first defaults: SQLite, Chroma, Neo4j Desktop, Typer/FastAPI, pytest. Keep Docker,
    Kubernetes, PostgreSQL, OpenSearch, MinIO/S3, managed embeddings, and production auth optional/future.

  - User-selected defaults: OpenAI primary, Azure OpenAI compatible path, Robot Framework generation only,
    REST + MQTT simulators first.

  - Current validated gaps: live .env still uses hash embeddings, LLM_PROVIDER=none,
    GRAPHRAG_REQUIRED=false, no reranker, no real simulator adapters, task routing is keyword-based, graph
    is traceability/basic retrieval rather than planning backbone.

  - Important correction: Neo4j should not be treated as a document extractor. Extraction remains
    deterministic + optional LLM fallback; Neo4j becomes the graph store and graph-backed reasoning/
    planning source.

  ## Key Implementation Changes

  - Target-mode readiness:
      - Add doctor --target-graphrag to fail unless Neo4j is reachable, GRAPHRAG_REQUIRED=true,
        EMBEDDING_PROVIDER=huggingface, BAAI/bge-m3 can embed, reranker can load, and configured LLM
        credentials match LLM_PROVIDER.

      - Update live .env to EMBEDDING_PROVIDER=huggingface, VECTOR_STORE_PROVIDER=chroma,
        GRAPHRAG_REQUIRED=true, LLM_PROVIDER=openai; keep tests explicitly pinned to hash embeddings.

      - Add a scoped clean-system-state --system PROJECT_1 command that cleans SQLite rows, Chroma chunk
        IDs, Neo4j nodes, and managed .multi_agentic_rag artifacts before re-ingest.

  - LLM decision brain:
      - Add src/multi_agentic_rag/llm/ with provider-neutral LLMClient, OpenAI Responses implementation,
        Azure-compatible adapter, prompts, and Pydantic schemas.

      - Use OpenAI Responses API for structured model calls; official docs position Responses as the direct
        model request path for tool and multimodal workflows, while app-owned orchestration can remain in
        MARAG/LangGraph. Use Structured Outputs for schema-adherent decisions and reasoning models through
        Responses for multi-step workflows.

      - Keep Azure OpenAI behind the same interface; Microsoft currently recommends Responses as the
        primary Azure OpenAI agent client and Chat Completions only for broader compatibility or existing
        integrations.

      - LLM outputs must be decisions only: IntentDecision, ExtractionFallbackResult, ScenarioPlan,
        AnswerDraft, FailureDebugPlan, and FinalValidationResult. Python agents perform all file, DB,
        graph, and execution mutations.

  - Small reusable agents:
      - Split the coarse agents/nodes.py into agent modules: intent_router_agent.py,
        document_resolver_agent.py, ingestion_agent.py, version_delta_agent.py, domain_analyzer_agent.py,
        coverage_analyzer_agent.py, scenario_selection_agent.py, dependency_audit_agent.py,
        test_harness_agent.py, test_writer_agent.py, robot_mapping_agent.py, syntax_validation_agent.py,
        test_execution_agent.py, failure_classifier_agent.py, json_sidecar_agent.py,
        database_update_agent.py, evidence_verifier_agent.py, report_generator_agent.py, and
        final_router_validation_agent.py.

      - LangGraph owns state and handoff. LLM nodes classify and plan. Tool nodes call existing ingestion,
        retrieval, graph, coverage, generation, execution, and registry services.

      - Add conditional routing for ingest_document, generate_tests, ask_question, compare_versions,
        regenerate_affected_tests, run_generated_tests, last_result, and update_coverage.

  - Hybrid GraphRAG retrieval:
      - Make graph-backed retrieval first for relationship and planning questions, vector retrieval second
        for semantic recall, BM25 third for exact IDs/protocols/constants, registry lookup for
        deterministic facts and deltas.

      - Do not use graph-only retrieval. Neo4j misses fuzzy phrasing; vector search misses exact
        engineering constants; BM25 misses semantic paraphrase. Hybrid retrieval is required.

      - Add explicit-version graph queries, relationship path retrieval, generated-test lineage retrieval,
        and coverage-impact retrieval.

      - Implement BGE reranking with a lazy BGEReranker using BAAI/bge-reranker-v2-m3; target mode fails if
        it cannot load, smoke/local-test mode may use NoopReranker.

  - Knowledge graph and extraction:
      - Extend ontology with ScopeArea, Capability, Endpoint, Register, Signal, Simulator, Adapter,
        GeneratedRobot, Report, and lifecycle/status properties.

      - Add stable semantic fact identity separate from value-specific fact_id: semantic_key = system +
        requirement/domain + entity + metric/action. This lets threshold 10 -> 20 become modified, not
        unrelated add/remove.

      - Deterministic extractors run first. LLM fallback fills missing structured facts only when evidence
        chunks exist and must return schema-validated facts with source chunk refs.

      - Neo4j stores extracted facts/entities/paths and powers scenario selection; it does not parse PDFs
        itself.

  - Version-aware test evolution:
      - Add impact classification: facts as unchanged, modified, added, removed; scenarios/tests as
        reusable, needs_data_update, needs_code_update, needs_regeneration, new_required, superseded.

      - Add SQLite-compatible migrations for semantic keys, lifecycle status, previous/superseded links,
        artifact type, robot paths, xml/report paths, impact status, execution scope, and duration.

      - Generation defaults: reuse unchanged passed tests, update data/assertions for modified facts,
        generate only for added facts, mark removed tests superseded, execute only affected tests unless
        force_run_all=true.

      - Preserve all v1 artifacts and DB rows. Never hard-delete historical coverage or generated tests.

  - Test automation and simulators:
      - Keep pytest as the execution foundation. Replace placeholder assertions with adapter-backed
        assertions where simulator/client support exists.

      - Add domain_plugins/ with domain pack schema and adapters. First active adapters: REST simulator/
        client using httpx, MQTT simulator/client using an in-memory simulator plus optional real broker
        adapter later.

      - Modbus and CAN get plugin contracts and BLOCKED behavior first; real adapters come after REST/MQTT
        stabilize.

      - Robot Framework generation becomes active but non-executing: generate .robot, .resource, and
        keyword scaffold files when enabled; sidecar records robot_status=generated. Robot execution
        remains future.

  - Output contracts:
      - Add AutomationTaskResult as the final task result shape with interpreted intent, document/version
        status, generated pytest/robot/sidecar/xml/report paths, affected/reused/skipped/blocked/failed
        tests, pass/fail/skip/blocked summary, DB update status, and final validation status.

      - Upgrade sidecar to test-automation-tracking.v3; read v2 for compatibility. Include document
        lineage, changed/unchanged facts, version impact, robot paths, xml/report paths, coverage reuse/
        update/gaps, run history, and DB update status.

      - Add CLI/API flags: --execute/--dry-run, --force-run-all, --robot/--no-robot, --target-graphrag,
        --clean-system-state, and natural-language count extraction for task.

  - Documentation outputs:
      - Create/update: STRATEGIC_UPDATE_PLAN.md, TARGET_ARCHITECTURE.md, VERSION_AWARE_TEST_STRATEGY.md,
        TEST_AUTOMATION_STRATEGY.md, LANGGRAPH_ORCHESTRATION_PLAN.md, DOMAIN_PLUGIN_STRATEGY.md,
        ARCHITECTURE_TARGET.mermaid, and targeted README.md wording.

      - Docs must label current vs planned behavior accurately and must not imply mandatory Docker,
        Kubernetes, PostgreSQL, OpenSearch, MinIO/S3, Weaviate, Azure/OpenAI embeddings, Robot execution,
        or production MCP.

  ## Structural Risks To Avoid

  - LLM overreach: never let the model directly write files or DB rows; it produces structured decisions
    and Python agents execute.

  - Fake PASS: simulator unavailable must be BLOCKED/SKIP, not passed document-contract checks.
  - Graph-only planning: Neo4j is essential for relationships but insufficient without BGE and BM25.
  - Dirty state: existing PROJECT_1 rows are contaminated; cleanup plus clean V1/V2 re-ingest is required
    before proving behavior.

  - Agent fragmentation: many agent files must share one typed state and one final validator, or handoffs
    will drift.

  - Robot too early: generate Robot artifacts now, but do not add Robot execution until pytest adapters and
    result classification are stable.

  - Azure/OpenAI drift: keep provider interface narrow and schema-driven; do not leak provider-specific
    response shapes outside llm/.

  ## Test Plan And Acceptance

  - Unit tests:
      - LLM provider selection and structured-output parsing with mocked OpenAI/Azure responses.
      - Intent parsing for counts, versions, dry-run, force-run-all, last result, regenerate affected
        tests.

      - Stable semantic fact keys and V1/V2 fact impact classification.
      - Graph explicit-version retrieval and graph-backed scenario ranking.
      - BGE embedding/reranker smoke tests gated behind target-mode markers; normal tests use hash.
      - Sidecar v3 validation plus v2 backward compatibility.
      - REST/MQTT simulator PASS, missing simulator BLOCKED, real endpoint missing PROTOCOL_UNAVAILABLE.
      - Robot file generation without requiring Robot execution.

  - Integration tests:
      - Clean PROJECT_1 -> ingest V1 -> generate tests -> ingest V2 -> update only changed tests -> run
        affected only -> preserve superseded v1 records.

      - Natural-language task "Generate 15 tests for BRD v2" performs resolution, ingestion-if-needed,
        delta, reuse, generation, optional execution, DB/sidecar/report update, and final validation.

  - Required commands after implementation:
      - uv sync --locked
      - uv run pytest -c pyproject.toml tests
      - uv run multi-agentic-rag doctor --target-graphrag
      - uv run multi-agentic-rag graph-check
      - uv run multi-agentic-rag validate-real-brd
      - Clean re-ingest/run proof for PROJECT_1 from repo root only.

  ## Assumptions And Open Questions

  - Defaults locked from this planning turn: OpenAI primary, Azure compatible, Robot generation only, REST
  - Open questions for manager/client:
      - Which OpenAI model and budget/latency profile should be approved for routing vs extraction vs
        answer synthesis?

      - Which real application interface should REST/MQTT simulators eventually mirror?
      - What reporting format is client-facing first: Markdown, JSON, CSV, JUnit XML, or Excel?
      - Does the client require Robot execution in a fixed milestone, or is Robot generation enough for
        Phase 2?

      - Are documents allowed to be sent to OpenAI/Azure for LLM fallback extraction, or must sensitive
        chunks stay local unless explicitly approved?
