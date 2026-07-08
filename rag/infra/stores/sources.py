"""Document source-connector interface — filesystem now, others stubbed (02.1 §8).

New DB/KB type later = new adapter, no core change — same pattern as VectorStore/
DocumentStore (01). Pull on schedule; push via webhook where the source supports it
(both deferred to 08 — the worker/scheduler infrastructure doesn't exist yet).
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SourceItem:
    item_id: str          # source-stable identity (path, record id, ...)
    fetch_ref: str         # what fetch() needs to retrieve the bytes
    content_hash: str | None = None


class DocumentSource(ABC):
    @abstractmethod
    def list_items(self) -> list[SourceItem]: ...

    @abstractmethod
    def new_or_changed(self, cursor: dict[str, str]) -> list[SourceItem]: ...

    @abstractmethod
    def fetch(self, item_id: str) -> bytes: ...


class FilesystemSource(DocumentSource):
    """Watches a directory of files. cursor = {item_id: content_hash} from the last scan."""

    def __init__(self, root: str, pattern: str = "*.pdf") -> None:
        self.root = Path(root)
        self.pattern = pattern

    def list_items(self) -> list[SourceItem]:
        return [
            SourceItem(item_id=str(path), fetch_ref=str(path))
            for path in sorted(self.root.glob(self.pattern))
        ]

    def new_or_changed(self, cursor: dict[str, str]) -> list[SourceItem]:
        changed = []
        for item in self.list_items():
            item.content_hash = self._hash(Path(item.fetch_ref))
            if cursor.get(item.item_id) != item.content_hash:
                changed.append(item)
        return changed

    def fetch(self, item_id: str) -> bytes:
        return Path(item_id).read_bytes()

    @staticmethod
    def _hash(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(8192), b""):
                h.update(block)
        return h.hexdigest()


class _StubSource(DocumentSource):
    """Base for not-yet-implemented adapters (02.1 §9) — interface exists, implementation
    lands when a real connector is needed."""

    def list_items(self) -> list[SourceItem]:
        raise NotImplementedError(f"{type(self).__name__} is a stub — adapter not implemented")

    def new_or_changed(self, cursor: dict[str, str]) -> list[SourceItem]:
        raise NotImplementedError(f"{type(self).__name__} is a stub — adapter not implemented")

    def fetch(self, item_id: str) -> bytes:
        raise NotImplementedError(f"{type(self).__name__} is a stub — adapter not implemented")


class S3Source(_StubSource):
    pass


class SqlSource(_StubSource):
    pass


class SqliteSource(_StubSource):
    pass


class ApiSource(_StubSource):
    pass


class SharePointSource(_StubSource):
    pass
