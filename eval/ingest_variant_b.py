"""Variant B ingestion: structured per-row table chunks + identical non-table chunks.

Ingests into a SEPARATE collection (documents_tabstruct) so collection A is untouched.
Non-table chunks are copied byte-identical from the existing collection A.
Table chunks are rebuilt from TV_L_tables.json with clean, signal-rich per-row text.
"""

import json
import re
import sys
import uuid
from pathlib import Path

# Executed as `uv run python eval/ingest_variant_b.py`, Python sets sys.path[0] to
# this script's own directory (eval/), not the repo root -- `rag` isn't an installed
# package (no [build-system] in pyproject.toml), so without this the `from rag...`
# imports below raise ModuleNotFoundError regardless of the caller's cwd. Same fix
# already applied in eval/eval_report.py for the same reason.
sys.path.insert(0, str(Path(__file__).parent.parent))

from qdrant_client import QdrantClient, models as qm

from rag.config import settings
from rag.infra.models.llm import get_embedder, get_sparse_embedder
from rag.domain.models import ChunkRecord


COLLECTION_B = settings.qdrant_collection + "_tabstruct"


def _normalize_amount(raw: str) -> str:
    """'4609,96' -> '4.609,96 €'"""
    raw = raw.strip().replace("€", "").strip()
    if not raw or raw == "-":
        return ""
    parts = raw.replace(".", "").split(",")
    if len(parts) == 2:
        integer = parts[0]
        decimal = parts[1]
        if len(integer) > 3:
            integer = integer[:-3] + "." + integer[-3:]
        return f"{integer},{decimal} €"
    return raw + " €"


def _grade_variants(grade: str) -> str:
    """'E 12' -> 'E 12 (E12)'"""
    compact = grade.replace(" ", "")
    if compact != grade:
        return f"{grade} ({compact})"
    spaced = re.sub(r"([A-Za-z]+)(\d)", r"\1 \2", grade)
    if spaced != grade:
        return f"{grade} ({spaced})"
    return grade


def _detect_stufe_labels(first_row: list[str]) -> list[str]:
    """Detect Stufe labels from the header row."""
    labels = []
    for cell in first_row:
        cell = cell.strip()
        if cell in ("€", ""):
            labels.append("")
        else:
            labels.append(cell)
    return labels


def _is_salary_table(table: dict) -> bool:
    """Heuristic: salary table has Entgelt/Entgelttabelle in caption + monetary values."""
    caption = table.get("caption", "").lower()
    if "entgelttabelle" not in caption and "entgeltbeträge" not in caption:
        return False
    if len(table["rows"]) < 2:
        return False
    for row in table["rows"][1:3]:
        has_money = any(re.search(r"\d{3,4},\d{2}", cell) for cell in row if cell)
        if has_money:
            return True
    return False


def build_structured_table_chunks(tables_path: Path) -> list[ChunkRecord]:
    with open(tables_path) as f:
        data = json.load(f)

    source = data["source"]
    chunks = []

    for table in data["tables"]:
        table_nr = table["table_nr"]
        page = table["page"]
        caption = table["caption"]

        if not _is_salary_table(table):
            continue

        rows = table["rows"]
        if len(rows) < 2:
            continue

        stufe_labels = _detect_stufe_labels(rows[0])

        # Per-row chunks
        for row in rows[1:]:
            grade = row[0].strip()
            if not grade or grade == "€":
                continue

            grade_display = _grade_variants(grade)

            for col_idx in range(1, len(row)):
                amount_raw = row[col_idx].strip()
                if not amount_raw or amount_raw == "-":
                    continue

                stufe = stufe_labels[col_idx] if col_idx < len(stufe_labels) else str(col_idx)
                amount = _normalize_amount(amount_raw)
                if not amount:
                    continue

                amount_num_match = re.search(r"[\d.,]+", amount)
                amount_num = float(amount_raw.replace(".", "").replace(",", ".")) if amount_num_match else 0.0

                content = f"Entgeltgruppe {grade_display}, Stufe {stufe}: {amount} (Monatsentgelt, TV-L)"

                chunk_id = str(uuid.uuid4())
                chunks.append(ChunkRecord(
                    chunk_id=chunk_id,
                    type="table_row",
                    content=content,
                    source_file=source,
                    doc_id="variant_b",
                    doc_version="TV-L 2018",
                    page_numbers=[page],
                    heading_path=[caption] if caption else [],
                    bboxes=[],
                    keywords=[grade.replace(" ", ""), grade, f"Stufe {stufe}"],
                    summary=None,
                ))

        # Whole-table chunk (markdown grid)
        md_lines = []
        if caption:
            md_lines.append(caption)
            md_lines.append("")
        header = "| " + " | ".join(stufe_labels or [c for c in (["Gruppe"] + [f"Stufe {i}" for i in range(1, 7)])]) + " |"
        md_lines.append(header)
        md_lines.append("|" + "---|" * len(stufe_labels) if stufe_labels else "")
        for row in rows[1:]:
            md_lines.append("| " + " | ".join(row) + " |")
        md_content = "\n".join(md_lines)

        chunks.append(ChunkRecord(
            chunk_id=str(uuid.uuid4()),
            type="table",
            content=md_content,
            source_file=source,
            doc_id="variant_b",
            doc_version="TV-L 2018",
            page_numbers=[page],
            heading_path=[caption] if caption else [],
            bboxes=[],
        ))

    return chunks


def copy_non_table_chunks(client: QdrantClient) -> list[dict]:
    """Copy non-table points from collection A as-is."""
    all_points = []
    offset = None
    while True:
        pts, offset = client.scroll(
            settings.qdrant_collection,
            scroll_filter=qm.Filter(must=[
                qm.FieldCondition(key="type", match=qm.MatchValue(value="text"))
            ]),
            limit=50,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        all_points.extend(pts)
        if offset is None:
            break
    return all_points


def ingest_variant_b():
    tables_path = Path("docs/TV_L_tables.json")
    if not tables_path.exists():
        print("❌ docs/TV_L_tables.json not found. Run ingestion first.")
        return

    client = QdrantClient(path=settings.qdrant_path)

    # Build structured table chunks
    table_chunks = build_structured_table_chunks(tables_path)
    print(f"📊 Built {len(table_chunks)} structured table chunks "
          f"({sum(1 for c in table_chunks if c.type == 'table_row')} rows, "
          f"{sum(1 for c in table_chunks if c.type == 'table')} whole-table)")

    # Copy non-table chunks from A
    non_table_points = copy_non_table_chunks(client)
    print(f"📄 Copied {len(non_table_points)} non-table chunks from collection A")

    # Create collection B
    if client.collection_exists(COLLECTION_B):
        client.delete_collection(COLLECTION_B)
    client.create_collection(
        COLLECTION_B,
        vectors_config={
            "dense": qm.VectorParams(size=1024, distance=qm.Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": qm.SparseVectorParams(),
        },
    )

    # Re-insert non-table chunks (byte-identical vectors + payload)
    if non_table_points:
        points_b = []
        for p in non_table_points:
            points_b.append(qm.PointStruct(
                id=p.id,
                vector=p.vector,
                payload=p.payload,
            ))
        for i in range(0, len(points_b), 50):
            client.upsert(COLLECTION_B, points_b[i:i + 50])
    print(f"✅ Inserted {len(non_table_points)} non-table chunks into {COLLECTION_B}")

    # Embed and insert structured table chunks
    embedder = get_embedder()
    sparse_embedder = get_sparse_embedder()

    batch_size = 20
    for i in range(0, len(table_chunks), batch_size):
        batch = table_chunks[i:i + batch_size]
        texts = [c.content for c in batch]
        dense_vecs = [v.tolist() for v in embedder.embed(texts)]
        sparse_vecs = [
            {"indices": sv.indices.tolist(), "values": sv.values.tolist()}
            for sv in sparse_embedder.embed(texts)
        ]

        points = []
        for rec, d_vec, s_vec in zip(batch, dense_vecs, sparse_vecs):
            points.append(qm.PointStruct(
                id=rec.chunk_id,
                vector={
                    "dense": d_vec,
                    "sparse": qm.SparseVector(
                        indices=s_vec["indices"],
                        values=s_vec["values"],
                    ),
                },
                payload={
                    "chunk_id": rec.chunk_id,
                    "type": rec.type,
                    "content": rec.content,
                    "source_file": rec.source_file,
                    "doc_id": rec.doc_id,
                    "doc_version": rec.doc_version,
                    "page_numbers": rec.page_numbers,
                    "heading_path": rec.heading_path,
                    "bboxes": [],
                    "keywords": rec.keywords,
                    "summary": rec.summary,
                },
            ))
        client.upsert(COLLECTION_B, points)

    total = client.count(COLLECTION_B).count
    print(f"\n🎉 Collection B ({COLLECTION_B}): {total} total chunks")
    client.close()


if __name__ == "__main__":
    ingest_variant_b()
