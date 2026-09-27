"""Corpus governance and reproducible independent retrieval evaluation."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from search_engine import retrieve


ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / "data" / "eval_cases.json"
REVIEWS_PATH = ROOT / "data" / "expert_reviews.csv"
LEGACY_REVIEW_FIELDS = (
    "case_id", "origin", "question", "city", "building_use", "project_kind",
    "design_stage", "should_abstain", "expected_references", "citation_correct",
    "applicability_correct", "manual_minutes", "assistant_minutes", "reviewer",
    "reviewed_on", "expert_notes",
)
REVIEW_FIELDS = LEGACY_REVIEW_FIELDS + (
    "corpus_dataset_id", "corpus_sha256", "retriever_sha256",
    "result_references", "result_json", "result_recorded_on", "result_snapshot_id",
)


def _iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def _hash_json(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def corpus_fingerprint(corpus: dict) -> str:
    return _hash_json(corpus)


def source_fingerprint(corpus: dict) -> str:
    return _hash_json(corpus.get("source", {}))


def clause_fingerprints(corpus: dict) -> dict[str, str]:
    standard = corpus.get("source", {}).get("standard", "")
    return {f"{standard}#{item['article']}": _hash_json(item)
            for item in corpus.get("clauses", []) if item.get("article")}


def retriever_fingerprint() -> str:
    return hashlib.sha256((ROOT / "search_engine.py").read_bytes()).hexdigest()


def audit_corpus(corpus: dict) -> dict:
    """Structural audit. Passing does not approve source text or applicability."""
    errors: list[str] = []
    source = corpus.get("source", {})
    fictional = source.get("type") == "fictional_demo"
    for key in ("standard", "url", "announcement_url", "published", "effective",
                "checked_on", "content_rights", "location_review"):
        if not source.get(key):
            errors.append(f"来源缺少 {key}")
    for key in ("url", "announcement_url"):
        parsed = urlparse(source.get(key, ""))
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append(f"来源 {key} 不是有效 HTTPS 地址")
    for key in ("published", "effective", "checked_on"):
        if not _iso_date(source.get(key, "")):
            errors.append(f"来源 {key} 日期无效")
    if bool(source.get("version_verified_on")) != bool(source.get("version_reviewer")):
        errors.append("版本复核日期与复核人须同时填写")
    if source.get("version_verified_on") and not _iso_date(source["version_verified_on"]):
        errors.append("版本复核日期无效")

    articles = set()
    reviewed = unreviewed = location_verified = applicability_reviewed = 0
    for item in corpus.get("clauses", []):
        article = item.get("article", "")
        if not article:
            errors.append("条目缺少 article")
        if article in articles:
            errors.append(f"重复条号 {article}")
        articles.add(article)
        page = item.get("page")
        if not isinstance(page, int) or page < 1:
            errors.append(f"条号 {article} 缺少有效页码")
        for key in ("topic", "summary", "keywords", "check"):
            if not item.get(key):
                errors.append(f"条号 {article} 缺少 {key}")
        if item.get("building_use") not in (None, "civil", "non_residential"):
            errors.append(f"条号 {article} 的建筑用途标签无效")
        if item.get("measure") not in (None, "width", "height", "slope"):
            errors.append(f"条号 {article} 的度量标签无效")
        status = item.get("evidence_status")
        if fictional and status == "fictional_demo":
            if item.get("expert_reviewed_on") or item.get("reviewer"):
                errors.append(f"虚构条目 {article} 不应包含专业复核标识")
        elif status == "unreviewed_summary" and not fictional:
            unreviewed += 1
            if item.get("expert_reviewed_on") or item.get("reviewer"):
                errors.append(f"条号 {article} 标记未复核但填写了复核信息")
        elif status == "expert_reviewed_summary" and not fictional:
            if not item.get("reviewer") or not _iso_date(item.get("expert_reviewed_on")):
                errors.append(f"条号 {article} 专业复核缺少签名或日期")
            else:
                reviewed += 1
        else:
            errors.append(f"条号 {article} 的证据状态无效或缺失")
        location = item.get("source_location") or {}
        expected_document = "original_demo_markdown" if fictional else "source_excerpt_pdf"
        if (location.get("document") != expected_document or
                location.get("article") != article or location.get("page") != page):
            errors.append(f"条目 {article} 的资料定位不一致")
        if fictional and location.get("status") == "self_authored":
            pass
        elif location.get("status") == "verified_by_reviewer" and not fictional:
            if not location.get("reviewer") or not _iso_date(location.get("verified_on")):
                errors.append(f"条号 {article} 的摘录 PDF 定位核验缺少签名或日期")
            else:
                location_verified += 1
        elif location.get("status") != "carried_forward_unverified":
            errors.append(f"条号 {article} 的摘录 PDF 定位状态无效或缺失")
        applicability = item.get("applicability") or {}
        if applicability.get("building_use") != item.get("building_use", "civil_unspecified"):
            errors.append(f"条号 {article} 的适用用途元数据与检索标签不一致")
        conditions = applicability.get("conditions_to_verify")
        if not isinstance(conditions, list) or not conditions or not all(
                isinstance(value, str) and value.strip() for value in conditions):
            errors.append(f"条号 {article} 缺少待核验适用条件")
        if fictional and applicability.get("status") == "not_applicable_demo":
            pass
        elif applicability.get("status") == "reviewed_by_expert" and not fictional:
            if not applicability.get("reviewer") or not _iso_date(applicability.get("reviewed_on")):
                errors.append(f"条号 {article} 的适用条件复核缺少签名或日期")
            else:
                applicability_reviewed += 1
        elif applicability.get("status") != "unreviewed" or fictional:
            errors.append(f"条号 {article} 的适用条件状态无效或缺失")

    clause_count = len(corpus.get("clauses", []))
    version_verified = bool(source.get("version_verified_on") and source.get("version_reviewer"))
    warnings = []
    if fictional:
        warnings.append("本资料集完全虚构，不对应真实规范或工程要求；不得据此作项目判断")
    if not version_verified and not fictional:
        warnings.append("现行版本及后续修订尚未完成签名核验")
    if unreviewed:
        warnings.append(f"{unreviewed} 条为未经专业复核的自编摘要")
    if location_verified < clause_count and not fictional:
        warnings.append(f"{clause_count - location_verified} 条摘录 PDF 页码/条号定位尚未逐条核验")
    if applicability_reviewed < clause_count and not fictional:
        warnings.append(f"{clause_count - applicability_reviewed} 条适用条件尚未专业复核")
    return {
        "errors": errors, "warnings": warnings,
        "clause_count": clause_count,
        "expert_reviewed_clauses": reviewed,
        "unreviewed_summary_clauses": unreviewed,
        "source_location_verified_clauses": location_verified,
        "applicability_reviewed_clauses": applicability_reviewed,
        "version_verified": version_verified,
        "fictional_demo": fictional,
        "source_checked_on": source.get("checked_on"),
        "standard": source.get("standard"),
        "dataset_id": corpus.get("dataset_id"),
        "corpus_sha256": corpus_fingerprint(corpus),
        "source_fingerprint": source_fingerprint(corpus),
        "clause_fingerprints": clause_fingerprints(corpus),
        "local_standards_count": 0,
    }


def prepare_rows(corpus: dict, cases_path: Path = CASES_PATH,
                 blank_count: int = 0) -> list[dict]:
    """Prepare blind developer examples or empty rows for real field questions."""
    if blank_count < 0:
        raise ValueError("blank_count must not be negative")
    cases = ([{} for _ in range(blank_count)] if blank_count else
             json.loads(cases_path.read_text(encoding="utf-8"))["cases"])
    rows = []
    for index, case in enumerate(cases, 1):
        context = case.get("context", {})
        rows.append({
            "case_id": f"FIELD-{index:03d}" if blank_count else f"DEV-{index:03d}",
            "origin": "现场真实问题，待采集与独立标注" if blank_count else "开发者示例，待专业人员独立标注",
            "question": case.get("question", ""),
            "city": context.get("city", ""),
            "building_use": context.get("building_use", ""),
            "project_kind": context.get("project_kind", ""),
            "design_stage": context.get("design_stage", ""),
            "should_abstain": "", "expected_references": "",
            "citation_correct": "", "applicability_correct": "",
            "manual_minutes": "", "assistant_minutes": "",
            "reviewer": "", "reviewed_on": "", "expert_notes": "",
            "corpus_dataset_id": corpus.get("dataset_id", ""),
            "corpus_sha256": corpus_fingerprint(corpus),
            "retriever_sha256": "", "result_references": "", "result_json": "",
            "result_recorded_on": "", "result_snapshot_id": "",
        })
    return rows


def write_reviews(path: Path, rows: list[dict], overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing expert work: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_reviews(path: Path = REVIEWS_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not set(LEGACY_REVIEW_FIELDS).issubset(reader.fieldnames or []):
            raise ValueError("评测表缺少必需列")
        return [{key: row.get(key, "") or "" for key in REVIEW_FIELDS}
                for row in reader]


def _snapshot_payload(row: dict) -> dict:
    return {key: row.get(key, "") for key in (
        "case_id", "question", "city", "building_use", "project_kind", "design_stage",
        "should_abstain", "expected_references", "reviewer", "reviewed_on",
        "corpus_dataset_id", "corpus_sha256", "retriever_sha256",
        "result_references", "result_json", "result_recorded_on",
    )}


def _blind_label(row: dict) -> tuple[str, list[str]] | None:
    answer = (row.get("should_abstain") or "").strip().lower()
    expected = [part.strip() for part in
                (row.get("expected_references") or "").replace("，", ";").split(";")
                if part.strip()]
    if (not (row.get("question") or "").strip() or answer not in ("yes", "no") or
            not _iso_date((row.get("reviewed_on") or "").strip()) or
            not (row.get("reviewer") or "").strip() or
            (answer == "no" and not expected) or (answer == "yes" and expected)):
        return None
    return answer, expected


def capture_result_rows(rows: list[dict], corpus: dict) -> list[dict]:
    """Record assistant output after blind reference labels have been collected."""
    dataset_id = corpus.get("dataset_id", "")
    corpus_hash = corpus_fingerprint(corpus)
    retriever_hash = retriever_fingerprint()
    captured = []
    for original in rows:
        row = {key: original.get(key, "") or "" for key in REVIEW_FIELDS}
        if row["corpus_dataset_id"] and row["corpus_dataset_id"] != dataset_id:
            raise ValueError(f"{row['case_id']}: 评测表语料 ID 与当前语料不一致")
        if row["corpus_sha256"] and row["corpus_sha256"] != corpus_hash:
            raise ValueError(f"{row['case_id']}: 评测表语料指纹与当前语料不一致")
        if row["result_snapshot_id"]:
            raise ValueError(f"{row['case_id']}: 已有结果快照；请新建评测轮次，不覆盖旧结果")
        if row["result_json"] or row["result_references"] or row["result_recorded_on"]:
            raise ValueError(f"{row['case_id']}: 存在未签名的助手结果，请使用空白盲标表")
        row["corpus_dataset_id"] = dataset_id
        row["corpus_sha256"] = corpus_hash
        if row["question"].strip() and not _blind_label(row):
            raise ValueError(f"{row['case_id']}: 请先完成独立标注（应否拒答、参考条号、复核人和日期）")
        if not row["question"].strip() and any((row.get(key) or "").strip() for key in
              ("should_abstain", "expected_references", "reviewer", "reviewed_on")):
            raise ValueError(f"{row['case_id']}: 已填写标注但缺少问题")
        if row["question"].strip():
            context = {key: row.get(key, "") for key in
                       ("city", "building_use", "project_kind", "design_stage")}
            result = retrieve(row["question"], corpus, context)
            row["retriever_sha256"] = retriever_hash
            row["result_references"] = ";".join(
                f"{item['standard']}#{item['article']}"
                for item in result.get("matches", [])[:3])
            row["result_json"] = json.dumps(result, ensure_ascii=False, sort_keys=True)
            row["result_recorded_on"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            row["result_snapshot_id"] = _hash_json(_snapshot_payload(row))
        captured.append(row)
    return captured


def _validated_snapshot(row: dict) -> tuple[dict | None, str | None]:
    if not row.get("result_snapshot_id"):
        return None, "missing"
    try:
        result = json.loads(row.get("result_json", ""))
        references = ";".join(f"{item['standard']}#{item['article']}"
                              for item in result.get("matches", [])[:3])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None, "invalid_json"
    if references != row.get("result_references", ""):
        return None, "references_mismatch"
    if not row.get("corpus_sha256") or not row.get("retriever_sha256"):
        return None, "missing_fingerprint"
    if not row.get("result_recorded_on") or _hash_json(_snapshot_payload(row)) != row["result_snapshot_id"]:
        return None, "snapshot_mismatch"
    return result, None


def review_metrics(rows: list[dict], corpus: dict) -> dict:
    """Score only reviewed questions with intact, stored assistant output."""
    reviewed = []
    incomplete = []
    for row in rows:
        blind_label = _blind_label(row)
        if blind_label:
            reviewed.append((row, *blind_label))
        elif any((row.get(key) or "").strip() for key in
                 ("should_abstain", "expected_references", "citation_correct",
                  "applicability_correct", "manual_minutes", "assistant_minutes",
                  "reviewer", "reviewed_on", "expert_notes")):
            incomplete.append(row.get("case_id", "未编号"))

    expected_total = expected_hit = 0
    abstain_total = abstain_correct = 0
    nonabstain_total = nonabstain_has_candidates = 0
    citation_total = citation_correct = 0
    applicability_total = applicability_correct = 0
    time_pairs: list[tuple[float, float]] = []
    unsnapshotted = []
    invalid_snapshots = []
    captured_hashes = set()
    captured_retrievers = set()
    version_counts: dict[tuple[str, str], int] = {}
    outdated_snapshot_ids = []
    current_hash = corpus_fingerprint(corpus)
    current_retriever = retriever_fingerprint()
    current_version_scored_count = 0
    for row, answer, expected in reviewed:
        result, problem = _validated_snapshot(row)
        if problem:
            (unsnapshotted if problem == "missing" else invalid_snapshots).append(row.get("case_id", "未编号"))
            continue
        captured_hashes.add(row["corpus_sha256"])
        captured_retrievers.add(row["retriever_sha256"])
        version_key = (row["corpus_sha256"], row["retriever_sha256"])
        version_counts[version_key] = version_counts.get(version_key, 0) + 1
        if version_key != (current_hash, current_retriever):
            outdated_snapshot_ids.append(row.get("case_id", "未编号"))
            continue
        current_version_scored_count += 1
        references = [f"{item['standard']}#{item['article']}"
                      for item in result.get("matches", [])[:3]]
        if answer == "yes":
            abstain_total += 1
            abstain_correct += not references
        else:
            nonabstain_total += 1
            nonabstain_has_candidates += bool(references)
            expected_total += len(expected)
            expected_hit += sum(reference in references for reference in expected)
        citation_label = (row.get("citation_correct") or "").strip().lower()
        if citation_label in ("yes", "no"):
            citation_total += 1
            citation_correct += citation_label == "yes"
        applicability_label = (row.get("applicability_correct") or "").strip().lower()
        if applicability_label in ("yes", "no"):
            applicability_total += 1
            applicability_correct += applicability_label == "yes"
        try:
            manual = float(row.get("manual_minutes") or "")
            assistant = float(row.get("assistant_minutes") or "")
            if manual > 0 and assistant > 0:
                time_pairs.append((manual, assistant))
        except ValueError:
            pass
    snapshotted_count = len(reviewed) - len(unsnapshotted) - len(invalid_snapshots)
    return {
        "question_count": len(rows),
        "filled_question_count": sum(bool((row.get("question") or "").strip()) for row in rows),
        "field_question_count": sum(row.get("case_id", "").startswith("FIELD-") and
                                    bool((row.get("question") or "").strip()) for row in rows),
        "reviewed_count": len(reviewed),
        "snapshotted_reviewed_count": snapshotted_count,
        "current_version_scored_count": current_version_scored_count,
        "outdated_snapshot_ids": outdated_snapshot_ids,
        "mixed_snapshot_versions": len(version_counts) > 1,
        "snapshot_version_groups": [
            {"corpus_sha256": key[0], "retriever_sha256": key[1], "count": count}
            for key, count in sorted(version_counts.items())],
        "incomplete_ids": incomplete,
        "unsnapshotted_reviewed_ids": unsnapshotted,
        "invalid_snapshot_ids": invalid_snapshots,
        "evaluation_basis": "current_version_result_snapshots" if current_version_scored_count else "awaiting_current_version_snapshots",
        "current_corpus_sha256": current_hash,
        "current_retriever_sha256": current_retriever,
        "snapshot_corpus_sha256": sorted(captured_hashes),
        "snapshot_retriever_sha256": sorted(captured_retrievers),
        "current_corpus_matches_snapshots": (
            all(value == current_hash for value in captured_hashes)
            if captured_hashes else None),
        "current_retriever_matches_snapshots": (
            all(value == current_retriever for value in captured_retrievers)
            if captured_retrievers else None),
        "top3_reference_recall": expected_hit / expected_total if expected_total else None,
        "expected_reference_count": expected_total,
        "expected_reference_hits": expected_hit,
        "abstention_accuracy": abstain_correct / abstain_total if abstain_total else None,
        "abstention_cases": abstain_total,
        "nonabstain_candidate_rate": (
            nonabstain_has_candidates / nonabstain_total if nonabstain_total else None),
        "nonabstain_cases": nonabstain_total,
        "citation_correct_rate": citation_correct / citation_total if citation_total else None,
        "citation_reviewed_cases": citation_total,
        "applicability_correct_rate": (
            applicability_correct / applicability_total if applicability_total else None),
        "applicability_reviewed_cases": applicability_total,
        "time_compared_cases": len(time_pairs),
        "average_minutes_saved": (
            sum(manual - assistant for manual, assistant in time_pairs) / len(time_pairs)
            if time_pairs else None),
    }


def quality_snapshot(corpus: dict, reviews_path: Path = REVIEWS_PATH) -> dict:
    audit = audit_corpus(corpus)
    try:
        rows = read_reviews(reviews_path)
        metrics = review_metrics(rows, corpus)
    except (ValueError, OSError) as exc:
        audit["errors"].append(f"专业评测表不可读取：{exc}")
        metrics = review_metrics([], corpus)
    developer_cases = len(json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"])
    return {
        "corpus": audit,
        "evaluation": metrics,
        "developer_regression_cases": developer_cases,
        "expert_target": 50,
        "status": "资料与专业评测待完善",
    }
