# LangGraph Orchestration Plan

## Principle

LLMs decide and plan only when enabled. Python agents execute the work.

Default local mode uses deterministic routing. When `LLM_PROVIDER` is `openai`
or `azure_openai`, the router asks for a structured `IntentDecision` and then
falls back to deterministic routing on any error.

## Target State

MARAG should decompose the current service-backed graph into these nodes:

1. `IntentRouterAgent`
2. `DocumentResolverAgent`
3. `IngestionAgent`
4. `VersionDeltaAgent`
5. `DomainAnalyzerAgent`
6. `CoverageAnalyzerAgent`
7. `ScenarioSelectionAgent`
8. `DependencyAuditAgent`
9. `TestHarnessAgent`
10. `TestWriterAgent`
11. `RobotMappingAgent`
12. `SyntaxValidationAgent`
13. `TestExecutionAgent`
14. `FailureClassifierAgent`
15. `JsonSidecarAgent`
16. `DatabaseUpdateAgent`
17. `EvidenceVerifierAgent`
18. `ReportGeneratorAgent`
19. `FinalRouterValidationAgent`

## State Schema

Shared state should carry:

- user request.
- interpreted intent.
- system/version/document path.
- active/superseded documents.
- deltas.
- domain profile.
- coverage records.
- selected scenarios.
- dependency audit.
- generated artifacts.
- execution result.
- sidecar status.
- DB update status.
- warnings/errors.

## Routing Rules

`IntentRouterAgent` classifies:

- `ingest_document`
- `generate_tests`
- `ask_question`
- `update_coverage`
- `run_generated_tests`
- `compare_versions`
- `regenerate_affected_tests`
- `last_result`

Current implementation supports deterministic and optional LLM-assisted routing
for query, coverage, generation, execution, and last result.

## Failure Paths

Failures must be explicit:

- missing document -> unsupported/blocked.
- no evidence -> unsupported.
- no requirement link -> no coverage claim.
- no graph in target mode -> unsupported.
- missing simulator/device -> blocked or skipped.
- generated syntax error -> generation error.
- assertion failure -> failed.

## Final Validation

For `generate_tests` and `run_generated_tests`, final validation should check:

- document/version resolved.
- coverage exists.
- pytest file exists.
- sidecar exists.
- Robot wrapper file exists.
- XML exists when execution ran.
- coverage report exists.
- DB rows were written.
- sidecar run history was updated.
- status counts are coherent.

Current implementation returns a structured automation task result with artifact
paths and execution summary. Future work should make this a dedicated final
LangGraph node.
