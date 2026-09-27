"""Run transparent retrieval regression checks; this is not an expert accuracy study."""

from __future__ import annotations

import json
from pathlib import Path

from search_engine import load_corpus, retrieve


def main() -> int:
    root = Path(__file__).resolve().parent
    cases = json.loads((root / "data" / "eval_cases.json").read_text(encoding="utf-8"))["cases"]
    corpus = load_corpus()
    passed = 0
    for case in cases:
        result = retrieve(case["question"], corpus, case.get("context"))
        articles = [item["article"] for item in result["matches"][:3]]
        expected = case.get("expected_articles", [])
        ok = (not articles if case.get("expect_no_evidence") else all(item in articles for item in expected))
        ok = ok and not any(item in articles for item in case.get("forbidden_articles", []))
        passed += bool(ok)
        print(f"{'通过' if ok else '失败'}  {case['question']}  -> {articles or '无候选'}")
    print(f"回归样本：{passed}/{len(cases)} 通过。样本未经建筑专业人员标注，不代表真实业务准确率。")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
