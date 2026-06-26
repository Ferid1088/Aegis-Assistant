from rag.storage.base import GraphStore


class Neo4jGraphStore(GraphStore):
    def upsert_entities(self, entities: list[dict]) -> None:
        raise NotImplementedError("Graph store not implemented until phase 5")

    def upsert_relations(self, relations: list[dict]) -> None:
        raise NotImplementedError("Graph store not implemented until phase 5")

    def neighbors(self, entity_names: list[str], hops: int) -> list[dict]:
        raise NotImplementedError("Graph store not implemented until phase 5")
