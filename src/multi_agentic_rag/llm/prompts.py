"""Prompt registry for OpenAI reasoning calls."""

from __future__ import annotations

PROMPT_VERSION = "2026-06-20.v1"

EVIDENCE_RULES = """
Use only the supplied tool results and evidence. Do not invent facts, requirements,
versions, source documents, citations, or artifact paths. If the supplied evidence is
insufficient, return a refusal or failed validation in the requested schema.
""".strip()

INTENT_ROUTER_PROMPT = f"""
Classify the user's task for a strict GraphRAG document platform.

Allowed intent_type values:
- answer_query
- ingest_document
- build_user_stories
- ingest_then_build_user_stories
- test_scenario_generation
- test_case_writing
- test_case_execution
- coverage_generation

Extract system, kb, version, document paths, and target output when present.
Mark missing_slots for required values that are not present or supplied as defaults.
{EVIDENCE_RULES}
""".strip()

WORKFLOW_PLANNER_PROMPT = """
Create an ordered high-level agent plan for the classified task.

Use only these implemented agents:
- AgentIngestDocument
- AgentRetrieveAnswer
- AgentUserStoryBuilder

Future placeholders may be mentioned only when the task explicitly asks for them:
- AgentTestScenarioGenerator
- AgentTestCaseWriter
- AgentTestCaseExecutor
- AgentTestCoverageGenerator

For implemented composed flows, order state handoffs explicitly.
""".strip()

ANSWER_SYNTHESIS_PROMPT = f"""
Write a concise answer grounded only in the supplied validated evidence bundle.
Every factual statement must be supported by a source chunk ID in citations.
If the evidence does not answer the question, refuse.
{EVIDENCE_RULES}
""".strip()

USER_STORY_PROMPT = f"""
Generate implementation-ready user stories from the supplied validated evidence bundle.
Each story must preserve source traceability and must use the exact schema fields.
Keep acceptance criteria testable and avoid requirements not supported by evidence.
{EVIDENCE_RULES}
""".strip()

QUALITY_VALIDATION_PROMPT = f"""
Validate the generated artifact against the supplied evidence and schema.
Return failed if any claim lacks source chunk traceability.
{EVIDENCE_RULES}
""".strip()

FACT_ENRICHMENT_PROMPT = f"""
Review the supplied deterministic facts for one source chunk.

Your job is only to validate and annotate ambiguous facts. Do not replace the
canonical fact set, do not invent new source facts, and do not delete any
deterministic extraction result.

You may do three things when evidence supports it:
- suggest a canonical name for an entity or relationship
- flag uncertain relationships that should not be treated as exact
- suggest split candidates when one extracted fact actually contains multiple facts

Return only structured suggestions for the supplied fact IDs. If a fact is not
ambiguous, leave it out.
{EVIDENCE_RULES}
""".strip()
