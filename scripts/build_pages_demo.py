"""Build the public, fictional-only data used by GitHub Pages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "clauses.json"
DESTINATION = ROOT / "docs" / "demo-data.json"


def project(corpus: dict) -> dict:
    if corpus.get("source", {}).get("type") != "fictional_demo":
        raise ValueError("GitHub Pages 只允许使用虚构演示资料")
    if any(item.get("evidence_status") != "fictional_demo" for item in corpus.get("clauses", [])):
        raise ValueError("GitHub Pages 资料包含非虚构条目")
    source = corpus["source"]
    return {
        "dataset_id": corpus["dataset_id"],
        "scope": corpus["scope"],
        "synonyms": corpus.get("synonyms", {}),
        "unsupported_topics": corpus.get("unsupported_topics", []),
        "source": {key: source[key] for key in ("name", "url", "type", "standard")},
        "clauses": [
            {key: item[key] for key in ("article", "topic", "keywords", "check")}
            | {key: item[key] for key in ("building_use", "measure") if key in item}
            for item in corpus["clauses"]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed copy is stale")
    args = parser.parse_args()
    corpus = json.loads(SOURCE.read_text(encoding="utf-8"))
    expected = json.dumps(project(corpus), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not DESTINATION.exists() or DESTINATION.read_text(encoding="utf-8") != expected:
            print("GitHub Pages 演示资料未与虚构主语料同步")
            return 1
        print("GitHub Pages 虚构资料与主语料一致")
        return 0
    DESTINATION.write_text(expected, encoding="utf-8")
    print(f"已生成 {DESTINATION.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
