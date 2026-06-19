# Graph Schema

## Labels

- `System`
- `Document`
- `DocumentVersion`
- `Chunk`
- `Fact`
- `Requirement`
- `Entity`
- `Delta`

## Relationships

- `(:System)-[:HAS_DOCUMENT]->(:Document)`
- `(:Document)-[:HAS_VERSION]->(:DocumentVersion)`
- `(:DocumentVersion)-[:HAS_CHUNK]->(:Chunk)`
- `(:Chunk)-[:SUPPORTS_FACT]->(:Fact)`
- `(:Fact)-[:TRACES_TO_REQUIREMENT]->(:Requirement)`
- `(:Chunk)-[:MENTIONS]->(:Entity)`
- `(:DocumentVersion)-[:SUPERSEDES]->(:DocumentVersion)`
- `(:Delta)-[:FROM_VERSION]->(:DocumentVersion)`
- `(:Delta)-[:TO_VERSION]->(:DocumentVersion)`

## Constraints

```cypher
CREATE CONSTRAINT system_name IF NOT EXISTS FOR (n:System) REQUIRE n.system_name IS UNIQUE;
CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.document_id IS UNIQUE;
CREATE CONSTRAINT document_version_id IF NOT EXISTS FOR (n:DocumentVersion) REQUIRE n.document_version_id IS UNIQUE;
CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.chunk_id IS UNIQUE;
CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (n:Fact) REQUIRE n.fact_id IS UNIQUE;
CREATE CONSTRAINT requirement_key IF NOT EXISTS FOR (n:Requirement) REQUIRE (n.system_name, n.requirement_id) IS UNIQUE;
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.entity_id IS UNIQUE;
CREATE CONSTRAINT delta_id IF NOT EXISTS FOR (n:Delta) REQUIRE n.delta_id IS UNIQUE;
```
