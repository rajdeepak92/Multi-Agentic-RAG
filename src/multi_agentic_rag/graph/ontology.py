"""Graph ontology constants for Option-4 architecture."""

NODE_LABELS = (
    "System",
    "Document",
    "Chunk",
    "Requirement",
    "Entity",
    "Sensor",
    "Device",
    "Protocol",
    "Topic",
    "TestCase",
    "Fact",
    "Delta",
    "Coverage",
)

RELATIONSHIP_TYPES = (
    "HAS_DOCUMENT",
    "HAS_CHUNK",
    "MENTIONS",
    "SUPPORTS_FACT",
    "DESCRIBES_REQUIREMENT",
    "THRESHOLD_FOR",
    "DETAILS_PROTOCOL",
    "IMPLEMENTS_PROTOCOL",
    "USES_TOPIC",
    "VERIFIED_BY",
    "TRACES_TO_REQUIREMENT",
    "SUPERSEDES",
    "FROM_DOCUMENT",
    "TO_DOCUMENT",
    "COVERS_REQUIREMENT",
)
