"""Graph ontology constants for Option-4 architecture."""

NODE_LABELS = (
    "System",
    "Document",
    "Chunk",
    "Requirement",
    "Entity",
    "Fact",
    "Delta",
    "Coverage",
)

RELATIONSHIP_TYPES = (
    "HAS_DOCUMENT",
    "HAS_CHUNK",
    "MENTIONS",
    "SUPPORTS_FACT",
    "SUPERSEDES",
    "FROM_DOCUMENT",
    "TO_DOCUMENT",
    "COVERS_REQUIREMENT",
)
