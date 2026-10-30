"""Compare a CLI-generated, read-only bibliography snapshot with Crossref."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bibliography_utils as bibliography


def write_report(results, destination):
    def cell(value):
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")

    counts = Counter(row["status"] for row in results)
    fields = Counter(field for row in results for field in row["changes"])
    lines = ["# 書誌情報監査", "", "本番DBの読み取りスナップショットとCrossrefを照合。DBは未更新。",
             "IDはDBのIDです。外部RIS等の連番とは一致しないためDOIを照合キーにしています。", "",
             f"対象: {len(results)}件", "", "## 照合結果", "", "| 状態 | 件数 |", "|---|---:|"]
    lines.extend(f"| {cell(status)} | {count} |" for status, count in counts.items())
    lines.extend(["", "更新候補は誤りの確定ではありません。著者のフルネーム化、表記統一、刊行年の差などを含みます。",
                  "", "## 項目別の差分", "", "| 項目 | 件数 |", "|---|---:|"])
    lines.extend(f"| {field} | {count} |" for field, count in fields.items())
    lines.extend(["", "## DOIの修正候補", "", "| 変更前 | 変更後 |", "|---|---|"])
    lines.extend(f"| {cell(row['paper'].get('doi'))} | {cell(row['candidate'].get('doi'))} |" for row in results if "doi" in row["changes"])
    lines.extend(["", "## 文献ごとの差分", "", "| DB ID | DOI | 項目 | 変更前 | 変更後 |", "|---|---|---|---|---|"])
    lines.extend(f"| {cell(row['paper']['id'])} | {cell(row['paper'].get('doi'))} | {field} | {cell(row['paper'].get(field))} | {cell(value)} |" for row in results for field, value in row["changes"].items())
    lines.extend(["", "## 未照合", "", "| DB ID | DOI | 理由 |", "|---|---|---|"])
    lines.extend(f"| {cell(row['paper']['id'])} | {cell(row['paper'].get('doi'))} | {cell(row.get('error', row['status']))} |" for row in results if row["status"] in {"DOIなし", "取得失敗"})
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("db_backups"))
    parser.add_argument("--retry-report", type=Path)
    args = parser.parse_args()
    rows = json.loads(args.source.read_text(encoding="utf-8-sig"))
    for row in rows:
        row["author_list"] = [
            {"family": a["last_name"], "given": a.get("first_name") or ""}
            if a.get("last_name") else {"literal": a.get("literal_name") or ""}
            for a in row.get("author_rows") or []
        ]

    cached = {}
    if args.retry_report:
        cached = {row["paper"]["item_id"]: row for row in json.loads(args.retry_report.read_text(encoding="utf-8"))}

    def review(row):
        previous = cached.get(row["item_id"])
        if previous and previous.get("candidate"):
            return bibliography.review_paper(row, previous["candidate"])
        return bibliography.build_review([row])[0]

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(review, rows))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / f"bibliography_review_{stamp}.json"
    destination.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_report(results, destination.with_suffix(".md"))
    counts = {status: sum(r["status"] == status for r in results) for status in sorted({r["status"] for r in results})}
    print(json.dumps({"records": len(rows), "counts": counts, "report": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
