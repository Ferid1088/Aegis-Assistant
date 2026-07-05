"""Convert a PDF via Docling → {stem}_docling.json + {stem}_tables.json."""

import json
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling_core.types.doc.document import DoclingDocument


def check_text_layer(result) -> None:
    for page in result.pages:
        if not getattr(page, "cells", None):
            print(f"⚠️  Page {page.page_no}: no text layer detected (scanned?)")


def export_tables(doc: DoclingDocument, source: str) -> list[dict]:
    ref_lookup = {item.self_ref: item for item in doc.texts}

    tables = []
    for idx, table in enumerate(doc.tables):
        page_no = table.prov[0].page_no if table.prov else 0

        caption_texts = []
        for cap_ref in table.captions:
            cap_item = ref_lookup.get(cap_ref.cref)
            if cap_item and hasattr(cap_item, "text"):
                caption_texts.append(cap_item.text)

        data = table.data
        columns = []
        rows_out = []
        if data and data.table_cells:
            grid: dict[int, dict[int, str]] = {}
            for cell in data.table_cells:
                r, c = cell.start_row_offset_idx, cell.start_col_offset_idx
                grid.setdefault(r, {})[c] = cell.text

            if grid:
                sorted_rows = sorted(grid.keys())
                first_row = sorted_rows[0]
                num_cols = data.num_cols
                columns = [grid.get(first_row, {}).get(c, "") for c in range(num_cols)]
                for r in sorted_rows[1:]:
                    rows_out.append([grid.get(r, {}).get(c, "") for c in range(num_cols)])

        tables.append({
            "index": idx,
            "table_nr": idx + 1,
            "page": page_no,
            "caption": " ".join(caption_texts) if caption_texts else "",
            "columns": columns,
            "rows": rows_out,
        })
    return tables


def convert(pdf_path: Path) -> tuple[Path, Path]:
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    check_text_layer(result)

    doc = result.document
    stem = pdf_path.stem
    out_dir = pdf_path.parent

    docling_path = out_dir / f"{stem}_docling.json"
    doc.save_as_json(docling_path)

    tables = export_tables(doc, pdf_path.name)
    tables_path = out_dir / f"{stem}_tables.json"
    tables_path.write_text(
        json.dumps({"source": pdf_path.name, "tables": tables}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"✅ Converted {pdf_path.name} → {docling_path.name}, {tables_path.name}")
    return docling_path, tables_path
