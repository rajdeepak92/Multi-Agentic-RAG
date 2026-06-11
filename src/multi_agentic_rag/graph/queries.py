"""Named graph query templates."""

CURRENT_FACTS_QUERY = """
MATCH (:System {system_name: $system_name})-[:HAS_DOCUMENT]->(d:Document {status: 'active'})
MATCH (d)-[:HAS_CHUNK]->(c:Chunk)-[:SUPPORTS_FACT]->(f:Fact)
RETURN d, c, f
"""

DOCUMENT_LINEAGE_QUERY = """
MATCH (:System {system_name: $system_name})-[:HAS_DOCUMENT]->(d:Document)
OPTIONAL MATCH (newer:Document)-[:SUPERSEDES]->(d)
RETURN d, newer
ORDER BY d.version
"""

DELTA_QUERY = """
MATCH (delta:Delta {system_name: $system_name})
RETURN delta
ORDER BY delta.from_version, delta.to_version
"""

RELATED_SUBGRAPH_QUERY = """
MATCH (:System {system_name: $system_name})-[:HAS_DOCUMENT]->(d:Document {status: 'active'})
MATCH (d)-[:HAS_CHUNK]->(c:Chunk)
MATCH path = (c)-[*1..2]-(n)
WHERE toLower(coalesce(n.name, n.fact_key, n.requirement_id, n.value, ''))
    CONTAINS toLower($entity_text)
RETURN d, c, labels(n) AS labels, properties(n) AS properties, length(path) AS hops
ORDER BY hops ASC
LIMIT $max_records
"""
