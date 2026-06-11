"""Cypher index and constraint definitions."""

INDEX_QUERIES = (
    "CREATE CONSTRAINT system_name IF NOT EXISTS FOR (s:System) REQUIRE s.system_name IS UNIQUE",
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.document_id IS UNIQUE",
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
    "CREATE CONSTRAINT requirement_id IF NOT EXISTS "
    "FOR (r:Requirement) REQUIRE r.requirement_id IS UNIQUE",
    "CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (f:Fact) REQUIRE f.fact_id IS UNIQUE",
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE",
    "CREATE CONSTRAINT delta_id IF NOT EXISTS FOR (d:Delta) REQUIRE d.delta_id IS UNIQUE",
    "CREATE INDEX fact_key IF NOT EXISTS FOR (f:Fact) ON (f.fact_key)",
    "CREATE INDEX document_status IF NOT EXISTS FOR (d:Document) ON (d.status)",
    "CREATE INDEX document_version IF NOT EXISTS FOR (d:Document) ON (d.version)",
    "CREATE INDEX chunk_status IF NOT EXISTS FOR (c:Chunk) ON (c.status)",
    "CREATE INDEX chunk_version IF NOT EXISTS FOR (c:Chunk) ON (c.version)",
    "CREATE INDEX fact_status IF NOT EXISTS FOR (f:Fact) ON (f.status)",
    "CREATE INDEX fact_version IF NOT EXISTS FOR (f:Fact) ON (f.version)",
)
