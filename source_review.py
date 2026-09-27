"""Prepare and structurally audit a human source-review register.

This tool never promotes entries into the searchable corpus automatically.
Only a qualified reviewer can verify the official text and applicability.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from search_engine import load_corpus


ROOT = Path(__file__).resolve().parent
DEFAULT_PATH = ROOT / "data" / "source_review_blank.csv"
FIELDS = (
    "standard", "article", "topic", "excerpt_url", "official_notice_url",
    "official_text_url", "official_page_or_section", "version_status",
    "version_checked_on", "version_reviewer", "text_location_checked",
    "text_location_reviewer", "text_location_checked_on", "applicability_notes",
    "applicability_reviewer", "applicability_checked_on", "summary_checked",
    "summary_reviewer", "summary_checked_on", "use_permission_notes", "review_notes",
)


def template_rows(corpus: dict) -> list[dict[str, str]]:
    source = corpus["source"]
    rows = []
    for clause in corpus["clauses"]:
        row = dict.fromkeys(FIELDS, "")
        row.update({
            "standard": source["standard"], "article": clause["article"],
            "topic": clause["topic"],
            "excerpt_url": source["url"] if source.get("type") == "fictional_demo" else f"{source['url']}#page={clause['page']}",
            "official_notice_url": "" if source.get("type") == "fictional_demo" else source["announcement_url"],
        })
        rows.append(row)
    return rows


def write_template(path: Path, corpus: dict) -> None:
    if path.exists():
        raise FileExistsError(f"不会覆盖现有专业登记表：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(template_rows(corpus))


def read_register(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError("资料复核登记表缺少必需列")
        return [{key: (row.get(key) or "").strip() for key in FIELDS} for row in reader]


def _date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def audit_register(rows: list[dict[str, str]], corpus: dict) -> dict:
    """Check record completeness, not whether a professional judgment is true."""
    expected = {(corpus["source"]["standard"], item["article"])
                for item in corpus["clauses"]}
    seen = set()
    missing = []
    ready = []
    for row in rows:
        key = (row["standard"], row["article"])
        reasons = []
        if key in seen:
            reasons.append("重复条目")
        seen.add(key)
        if key not in expected:
            reasons.append("不在当前资料库")
        official = urlparse(row["official_text_url"])
        if official.scheme != "https" or not official.netloc:
            reasons.append("正式文本链接缺失或不是 HTTPS")
        if not row["official_page_or_section"]:
            reasons.append("正式文本位置未填写")
        if row["version_status"] != "current_verified":
            reasons.append("现行版本未由专业人员确认")
        if not row["version_reviewer"] or not _date(row["version_checked_on"]):
            reasons.append("版本复核缺少签名或有效日期")
        for label, prefix in (("正式文本定位", "text_location"),
                              ("摘要", "summary")):
            if row[f"{prefix}_checked"] != "yes" or not row[f"{prefix}_reviewer"] or not _date(row[f"{prefix}_checked_on"]):
                reasons.append(f"{label}尚无完整复核记录")
        if (not row["applicability_notes"] or not row["applicability_reviewer"] or
                not _date(row["applicability_checked_on"])):
            reasons.append("适用条件尚无完整复核记录")
        if not row["use_permission_notes"]:
            reasons.append("资料使用权限未记录")
        if reasons:
            missing.append({"reference": f"{key[0]}#{key[1]}", "missing": reasons})
        else:
            ready.append(f"{key[0]}#{key[1]}")
    absent = sorted(expected - seen)
    return {
        "record_count": len(rows), "ready_for_manual_release_review": ready,
        "ready_count": len(ready), "incomplete": missing,
        "absent_references": [f"{standard}#{article}" for standard, article in absent],
        "note": "仅检查登记字段；不验证链接内容、条文准确性、现行状态或使用授权。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="建筑规范正式资料人工复核登记")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="生成不含虚构复核结论的空白登记表")
    prepare.add_argument("--out", type=Path, default=DEFAULT_PATH)
    audit = sub.add_parser("audit", help="检查人工登记字段是否齐全")
    audit.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    corpus = load_corpus()
    try:
        if args.command == "prepare":
            write_template(args.out, corpus)
            print(f"已生成 {len(corpus['clauses'])} 条空白复核记录：{args.out}")
        else:
            result = audit_register(read_register(args.path), corpus)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["incomplete"] or result["absent_references"] else 0
    except (FileExistsError, OSError, ValueError) as exc:
        print(exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
