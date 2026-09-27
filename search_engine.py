"""Evidence-first retriever for the deliberately limited demonstration corpus."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent / "data" / "clauses.json"


def load_corpus(path: Path = DATA_PATH) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    articles = [item["article"] for item in data["clauses"]]
    if len(articles) != len(set(articles)):
        raise ValueError("Duplicate article in corpus")
    for entry in data["clauses"]:
        if not all(entry.get(key) for key in ("article", "page", "topic", "summary", "keywords", "check")):
            raise ValueError(f"Incomplete article: {entry.get('article')}")
    return data


def _clean(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.lower())


def _grams(value: str) -> set[str]:
    cleaned = _clean(value)
    return {cleaned[index:index + length]
            for length in (2, 3)
            for index in range(max(0, len(cleaned) - length + 1))}


def _expand_query(question: str, corpus: dict) -> str:
    """Add a canonical term only when a curated synonym occurs in the question."""
    additions = [canonical for canonical, variants in corpus.get("synonyms", {}).items()
                 if any(variant in question for variant in variants)]
    return f"{question} {' '.join(additions)}"


def _mentions_article(question: str, article: str) -> bool:
    return re.search(rf"(?<![\d.]){re.escape(article)}(?![\d.])", question) is not None


def _score(question: str, clause: dict) -> float:
    query = _clean(question)
    if not query:
        return 0.0
    keywords = clause["keywords"]
    topic = _clean(clause["topic"])
    grams = _grams(question)
    clause_grams = _grams(" ".join([clause["topic"], *keywords, clause["summary"]]))
    overlap = len(grams & clause_grams)
    score = overlap / math.sqrt(max(1, len(grams) * len(clause_grams))) * 8
    for keyword in keywords:
        term = _clean(keyword)
        if len(term) >= 2 and term in query:
            score += 3.5 + min(len(term), 6) * 0.3
    if topic in query:
        score += 4
    if _mentions_article(question, clause["article"]):
        score += 20
    return score


def _building_use(question: str, context: dict) -> str:
    selected = context.get("building_use", "")
    if selected:
        return selected
    if "非住宅" in question or "住宅以外" in question:
        return "non_residential"
    if "住宅" in question:
        return "residential"
    if any(term in question for term in ("办公楼", "办公建筑", "写字楼", "商场", "商业建筑")):
        return "non_residential"
    return ""


def _question_measure(question: str) -> str:
    width = any(term in question for term in ("净宽", "宽度", "多宽"))
    height = any(term in question for term in ("净高", "高度", "多高"))
    slope = any(term in question for term in ("坡度", "坡比"))
    if width and not height:
        return "width"
    if height and not width:
        return "height"
    if slope and not width and not height:
        return "slope"
    return ""


def _uncovered_topics(question: str, corpus: dict) -> list[str]:
    return [topic["label"] for topic in corpus.get("unsupported_topics", [])
            if any(term in question for term in topic["terms"])]


def _supported_question(question: str, corpus: dict) -> str:
    """Keep only independently phrased parts outside known unsupported topics.

    A phrase such as '防火楼梯宽度' is not repurposed into a generic stair
    query. A separate question joined with '和' can still retrieve evidence.
    """
    if not _uncovered_topics(question, corpus):
        return question
    segments = re.split(r"[，,。；;、？?]|以及|同时|另外|还要|并且|和|与|及", question)
    return " ".join(segment.strip() for segment in segments
                    if segment.strip() and not _uncovered_topics(segment, corpus))


def _match_reason(question: str, entry: dict, corpus: dict) -> str:
    article = entry["article"]
    if _mentions_article(question, article):
        return f"问题中直接提及虚构条目 {article}；仅用于演示定位。"
    direct = [term for term in [entry["topic"], *entry["keywords"]]
              if len(_clean(term)) >= 2 and _clean(term) in _clean(question)]
    if direct:
        return f"关键词命中：{'、'.join(dict.fromkeys(direct[:2]))}；仅用于定位候选条目。"
    terms = {entry["topic"], *entry["keywords"]}
    for canonical, variants in corpus.get("synonyms", {}).items():
        if canonical in terms:
            for variant in variants:
                if variant in question:
                    return f"同义词映射：{variant} → {canonical}；仅用于定位候选条目。"
    return "条目主题与问题存在文字相关性；仅用于演示定位。"


def _search_explanation(question: str, context: dict, use: str,
                        measure: str, uncovered_topics: list[str]) -> dict:
    applied = []
    selected_use = context.get("building_use", "")
    use_labels = {"residential": "住宅建筑", "non_residential": "非住宅民用建筑",
                  "other_civil": "其他民用建筑"}
    if use:
        origin = "所选" if selected_use else "从问题识别的"
        if use == "residential":
            applied.append(f"建筑用途：按{origin}“住宅建筑”初筛，排除标为仅非住宅的条目；仍需人工核验。")
        else:
            applied.append(f"建筑用途：检查{origin}“{use_labels.get(use, use)}”与已有用途标签；本次没有按用途排除条目，不证明适用。")
    if measure:
        measure_labels = {"width": "宽度", "height": "高度", "slope": "坡度"}
        applied.append(f"问题指标：按“{measure_labels[measure]}”排除其他已标注指标的条目。")
    recorded = []
    if context.get("city"):
        recorded.append(f"项目所在地：{context['city']}（仅记录；未参与地方标准筛选）")
    if context.get("project_kind"):
        kind = {"new": "新建", "renovation": "改造"}.get(context["project_kind"], context["project_kind"])
        recorded.append(f"项目类型：{kind}（仅记录；未参与条款筛选）")
    if context.get("design_stage"):
        stage = {"concept": "概念", "scheme": "方案", "construction": "施工图"}.get(
            context["design_stage"], context["design_stage"])
        recorded.append(f"设计阶段：{stage}（仅记录；未参与条款筛选）")
    return {"applied_filters": applied, "recorded_only_filters": recorded,
            "uncovered_topics": uncovered_topics}


def retrieve(question: str, corpus: dict, context: dict | None = None, limit: int = 5) -> dict:
    """Return candidates and a visible coverage reason; never a compliance verdict."""
    question = question.strip()
    context = context or {}
    topics = _uncovered_topics(question, corpus)
    supported_question = _supported_question(question, corpus)
    use = _building_use(question, context)
    measure = _question_measure(supported_question)
    explanation = _search_explanation(question, context, use, measure, topics)
    if not question:
        return {"matches": [], "coverage_gap": "请输入具体问题。",
                "search_explanation": explanation}
    selected_use = context.get("building_use", "")
    non_residential_terms = ("非住宅", "住宅以外", "办公楼", "办公建筑", "写字楼", "商场", "商业建筑")
    mentioned_non_residential = any(term in question for term in non_residential_terms)
    mentioned_residential = "住宅" in question and not mentioned_non_residential
    if (mentioned_residential and selected_use == "non_residential") or (
            mentioned_non_residential and selected_use == "residential"):
        return {"matches": [], "coverage_gap": "问题描述与所选建筑用途冲突，请先核对项目条件。",
                "search_explanation": explanation}
    expanded = _expand_query(supported_question, corpus)
    ranked = []
    excluded = 0
    for entry in corpus["clauses"] if supported_question else []:
        if entry.get("building_use") == "non_residential" and use == "residential":
            excluded += 1
            continue
        if measure and entry.get("measure") and entry["measure"] != measure:
            continue
        ranked.append((_score(expanded, entry), entry))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["article"]))
    best_score = ranked[0][0] if ranked else 0
    matches = []
    for score, entry in ranked[:limit]:
        if score < max(2.35, best_score * 0.38):
            continue
        matches.append({
            "article": entry["article"],
            "topic": entry["topic"],
            "summary": entry["summary"],
            "check": entry["check"],
            "building_use": entry.get("building_use", "civil"),
            "page": entry["page"],
            "source_url": (corpus["source"]["url"] if corpus["source"].get("type") == "fictional_demo"
                           else f"{corpus['source']['url']}#page={entry['page']}"),
            "source_name": corpus["source"]["name"],
            "standard": corpus["source"]["standard"],
            "score": round(score, 2),
            "match_reason": _match_reason(supported_question, entry, corpus),
            "evidence_status": entry.get("evidence_status", "unreviewed_summary"),
        })
    gap = ""
    if topics:
        labels = "、".join(f"“{label}”" for label in topics)
        gap = (f"问题中的{labels}未被虚构演示资料覆盖；以下仅是其他部分的练习候选，真实问题需另查有权使用的正式资料。"
               if matches else f"当前资料库未收录{labels}所需的专项依据。")
    elif not matches:
        gap = "虚构演示资料中没有足够相关的候选条目；请重新描述练习问题。"
        if excluded and use == "residential":
            gap += " 已排除标记为仅适用于非住宅民用建筑的条目。"
    return {"matches": matches, "coverage_gap": gap,
            "search_explanation": explanation}


def search(question: str, corpus: dict, limit: int = 5) -> list[dict]:
    """Compatibility helper for simple callers and evaluation cases."""
    return retrieve(question, corpus, limit=limit)["matches"]
