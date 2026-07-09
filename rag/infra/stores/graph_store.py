"""Neo4j-backed graph store for entity/relation storage and traversal."""

from neo4j import GraphDatabase

from rag.config import settings
from rag.infra.stores.base import GraphStore


class Neo4jGraphStore(GraphStore):
    def __init__(self) -> None:
        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        with self._driver.session() as s:
            s.run("CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.canonical)")
            s.run("CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.name)")

    def close(self) -> None:
        self._driver.close()

    def upsert_entities(self, entities: list[dict]) -> None:
        with self._driver.session() as s:
            for ent in entities:
                s.run(
                    """
                    MERGE (e:Entity {canonical: $canonical})
                    ON CREATE SET e.name = $name, e.type = $type,
                                  e.doc_ids = [$doc_id], e.chunk_ids = [$chunk_id],
                                  e.pages = [$page], e.doc_version = $doc_version
                    ON MATCH SET e.doc_ids = CASE WHEN NOT $doc_id IN e.doc_ids
                                   THEN e.doc_ids + $doc_id ELSE e.doc_ids END,
                                 e.chunk_ids = CASE WHEN NOT $chunk_id IN e.chunk_ids
                                   THEN e.chunk_ids + $chunk_id ELSE e.chunk_ids END,
                                 e.pages = CASE WHEN NOT $page IN e.pages
                                   THEN e.pages + $page ELSE e.pages END
                    """,
                    canonical=ent["canonical"],
                    name=ent.get("name", ent["canonical"]),
                    type=ent.get("type"),
                    doc_id=ent.get("doc_id", ""),
                    chunk_id=ent.get("chunk_id", ""),
                    page=ent.get("page", 0),
                    doc_version=ent.get("doc_version"),
                )

    def upsert_relations(self, relations: list[dict]) -> None:
        with self._driver.session() as s:
            for rel in relations:
                s.run(
                    """
                    MATCH (a:Entity {canonical: $from_entity})
                    MATCH (b:Entity {canonical: $to_entity})
                    MERGE (a)-[r:RELATES {type: $rel_type, chunk_id: $chunk_id}]->(b)
                    ON CREATE SET r.confidence = $confidence, r.doc_id = $doc_id,
                                  r.page = $page, r.doc_version = $doc_version
                    """,
                    from_entity=rel["from_entity"],
                    to_entity=rel["to_entity"],
                    rel_type=rel["relation_type"],
                    confidence=rel.get("confidence", 0.0),
                    chunk_id=rel.get("chunk_id", ""),
                    doc_id=rel.get("doc_id", ""),
                    page=rel.get("page", 0),
                    doc_version=rel.get("doc_version"),
                )

    def neighbors(self, entity_names: list[str], hops: int = 2,
                  allowed_levels: list[str] | None = None) -> list[dict]:
        if allowed_levels:
            # INV-2: per-hop ACL filter — any-of intersection on nodes AND edges
            query = """
                MATCH (e:Entity) WHERE e.canonical IN $names
                CALL (e) {
                    MATCH p=(e)-[*1..2]-(n:Entity)
                    RETURN p, n, relationships(p) AS rels
                    LIMIT 50
                }
                WITH DISTINCT n, rels, e
                UNWIND rels AS r
                WHERE (NOT exists(r.acl_levels) OR size(r.acl_levels) = 0
                       OR any(l IN r.acl_levels WHERE l IN $allowed))
                RETURN DISTINCT
                    e.canonical AS source,
                    n.canonical AS target,
                    n.name AS target_name,
                    n.type AS target_type,
                    r.type AS relation_type,
                    r.chunk_id AS chunk_id,
                    r.doc_id AS doc_id,
                    r.page AS page
                """
        else:
            query = """
                MATCH (e:Entity) WHERE e.canonical IN $names
                CALL (e) {
                    MATCH p=(e)-[*1..2]-(n:Entity)
                    RETURN p, n, relationships(p) AS rels
                    LIMIT 50
                }
                WITH DISTINCT n, rels, e
                UNWIND rels AS r
                RETURN DISTINCT
                    e.canonical AS source,
                    n.canonical AS target,
                    n.name AS target_name,
                    n.type AS target_type,
                    r.type AS relation_type,
                    r.chunk_id AS chunk_id,
                    r.doc_id AS doc_id,
                    r.page AS page
                """
        with self._driver.session() as s:
            result = s.run(query, names=entity_names,
                           allowed=allowed_levels or [])
            return [dict(record) for record in result]

    def clear(self) -> None:
        with self._driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")

    def count(self) -> dict:
        with self._driver.session() as s:
            entities = s.run("MATCH (e:Entity) RETURN count(e) AS c").single()["c"]
            relations = s.run("MATCH ()-[r:RELATES]->() RETURN count(r) AS c").single()["c"]
            return {"entities": entities, "relations": relations}
