"""Prepare blind expert review sheets, audit source metadata, and score reviewed questions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quality import (
    REVIEWS_PATH, audit_corpus, capture_result_rows, prepare_rows,
    read_reviews, review_metrics, write_reviews,
)
from search_engine import load_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description="建筑规范检索助手资料审核与专业评测")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="生成不含开发者答案的专家标注表")
    prepare.add_argument("--out", type=Path, default=REVIEWS_PATH)
    prepare.add_argument("--blank", type=int, default=0,
                         help="生成指定数量的空白现场问题行；不填入虚构问题")
    snapshot = sub.add_parser("snapshot", help="盲标完成后冻结助手输出到新 CSV")
    snapshot.add_argument("path", type=Path, help="已填写独立参考答案的 CSV")
    snapshot.add_argument("--out", type=Path, required=True, help="另存带助手输出的 CSV")
    score = sub.add_parser("score", help="统计已由专业人员完成标注的行")
    score.add_argument("path", nargs="?", type=Path, default=REVIEWS_PATH)
    sub.add_parser("audit", help="检查规范资料元数据与复核状态")
    args = parser.parse_args()
    corpus = load_corpus()
    if args.command == "prepare":
        try:
            rows = prepare_rows(corpus, blank_count=args.blank)
            write_reviews(args.out, rows)
        except (FileExistsError, ValueError) as exc:
            print(exc)
            return 2
        kind = "空白现场问题采集行" if args.blank else "开发者示例盲标样本"
        print(f"已生成 {len(rows)} 道{kind}：{args.out}")
        print("请先由专业人员独立填写问题、应否拒答、参考条号、签名和日期；不要查看助手结果。")
    elif args.command == "snapshot":
        try:
            rows = read_reviews(args.path)
            captured = capture_result_rows(rows, corpus)
            write_reviews(args.out, captured)
        except (FileExistsError, ValueError) as exc:
            print(exc)
            return 2
        captured_count = sum(bool(row["result_snapshot_id"]) for row in captured)
        print(f"已冻结 {captured_count} 道问题的助手输出：{args.out}")
        print("结果 JSON 和结果指纹在新 CSV 右侧；可继续填写引用/适用性评判与用时。")
    elif args.command == "score":
        metrics = review_metrics(read_reviews(args.path), corpus)
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        if not metrics["reviewed_count"]:
            print("尚无完成的专业标注，不能计算业务准确率。")
        elif not metrics["snapshotted_reviewed_count"]:
            print("已有独立标注，但尚无有效助手结果快照，不能计算业务准确率。")
        if metrics["invalid_snapshot_ids"]:
            print("部分结果快照指纹不符，已排除这些题；请核对 CSV 是否修改了问题、条件或结果。")
        if metrics["outdated_snapshot_ids"]:
            print("旧语料或旧检索程序的快照未计入当前版本指标；请查看 snapshot_version_groups 并按轮次保存评测表。")
    else:
        audit = audit_corpus(corpus)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 1 if audit["errors"] else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
