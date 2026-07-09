"""Auto-generate gold set from TV_L_tables.json for salary cell lookups."""

import json
import re
from pathlib import Path

TABLES_PATH = Path("docs/TV_L_tables.json")
OUTPUT_PATH = Path("eval/table_gold.jsonl")

QUESTION_TEMPLATES = [
    "Was verdient {grade} in Stufe {stufe}?",
    "Wie hoch ist das Monatsentgelt für {grade} Stufe {stufe}?",
    "Welches Gehalt bekommt {grade} in Stufe {stufe}?",
]


def normalize_amount(raw: str) -> str:
    raw = raw.strip().replace("€", "").replace(" ", "").strip()
    if not raw:
        return ""
    parts = raw.replace(".", "").split(",")
    if len(parts) == 2:
        integer = parts[0]
        decimal = parts[1]
        if len(integer) > 3:
            integer = integer[:-3] + "." + integer[-3:]
        return f"{integer},{decimal}"
    return raw


def main():
    with open(TABLES_PATH) as f:
        data = json.load(f)

    gold = []
    seen = set()

    for table in data["tables"]:
        caption = table.get("caption", "").lower()
        if "entgelttabelle" not in caption:
            continue

        rows = table["rows"]
        if len(rows) < 2:
            continue

        stufe_labels = []
        for cell in rows[0]:
            cell = cell.strip()
            stufe_labels.append(cell if cell not in ("€", "") else "")

        for row in rows[1:]:
            grade = row[0].strip()
            if not grade or grade == "€":
                continue

            for col_idx in range(1, min(len(row), len(stufe_labels))):
                amount_raw = row[col_idx].strip()
                if not amount_raw or not re.search(r"\d{3,}", amount_raw):
                    continue

                stufe = stufe_labels[col_idx]
                if not stufe:
                    stufe = str(col_idx)

                amount = normalize_amount(amount_raw)
                key = (grade, stufe, amount)
                if key in seen:
                    continue
                seen.add(key)

                template_idx = len(gold) % len(QUESTION_TEMPLATES)
                question = QUESTION_TEMPLATES[template_idx].format(grade=grade, stufe=stufe)

                gold.append({
                    "question": question,
                    "grade": grade,
                    "stufe": stufe,
                    "expected_amount": amount,
                })

    # Ensure the known case is included
    known = {"question": "Was verdient E12 in Stufe 4?", "grade": "E 12", "stufe": "4", "expected_amount": "4.609,96"}
    if not any(g["grade"] == "E 12" and g["stufe"] == "4" for g in gold):
        gold.append(known)

    # Sample ~10: pick diverse grades AND stufen
    sampled = []
    keys_seen = set()
    # First pass: one per unique stufe across different grades
    for target_stufe in ["1", "2", "3", "4", "5", "6"]:
        for g in gold:
            if g["stufe"] == target_stufe and g["grade"] not in keys_seen and len(sampled) < 9:
                sampled.append(g)
                keys_seen.add(g["grade"])
                break
    # Fill remaining with unseen grades
    for g in gold:
        if g["grade"] not in keys_seen and len(sampled) < 9:
            sampled.append(g)
            keys_seen.add(g["grade"])
    # Always include E12/Stufe4
    sampled.append(known)

    with open(OUTPUT_PATH, "w") as f:
        for g in sampled:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    print(f"✅ Generated {len(sampled)} gold questions → {OUTPUT_PATH}")
    for g in sampled:
        print(f"  {g['question']}  → {g['expected_amount']} €")


if __name__ == "__main__":
    main()
