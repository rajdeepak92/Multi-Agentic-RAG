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
