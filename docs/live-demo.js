"use strict";

// Browser-only demonstration. It reads the generated fictional dataset and never
// calls an API or stores the visitor's question.
(function (root) {
  function clean(value) {
    return String(value || "").toLowerCase().replace(/[^\p{L}\p{N}_]/gu, "");
  }

  function grams(value) {
    const text = clean(value);
    const result = new Set();
    for (const size of [2, 3]) {
      for (let index = 0; index <= text.length - size; index += 1) {
        result.add(text.slice(index, index + size));
      }
    }
    return result;
  }

  function uncoveredTopics(question, corpus) {
    return (corpus.unsupported_topics || [])
      .filter((item) => item.terms.some((term) => question.includes(term)))
      .map((item) => item.label);
  }

  function supportedQuestion(question, corpus) {
    if (!uncoveredTopics(question, corpus).length) return question;
    return question.split(/[，,。；;、？?]|以及|同时|另外|还要|并且|和|与|及/u)
      .filter((segment) => segment.trim() && !uncoveredTopics(segment, corpus).length)
      .join(" ");
  }

  function buildingUse(question, selected) {
    if (selected) return selected;
    if (/(非住宅|住宅以外)/u.test(question)) return "non_residential";
    if (question.includes("住宅")) return "residential";
    if (/(办公楼|办公建筑|写字楼|商场|商业建筑)/u.test(question)) return "non_residential";
    return "";
  }

  function questionMeasure(question) {
    const width = /(净宽|宽度|多宽)/u.test(question);
    const height = /(净高|高度|多高)/u.test(question);
    const slope = /(坡度|坡比)/u.test(question);
    if (width && !height) return "width";
    if (height && !width) return "height";
    if (slope && !width && !height) return "slope";
    return "";
  }

  function mentionsArticle(question, article) {
    const escaped = article.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(?<![\\d.])${escaped}(?![\\d.])`, "u").test(question);
  }

  function score(question, item) {
    const query = clean(question);
    if (!query) return 0;
    const queryGrams = grams(question);
    const itemGrams = grams([item.topic, ...item.keywords].join(" "));
    let overlap = 0;
    queryGrams.forEach((gram) => { if (itemGrams.has(gram)) overlap += 1; });
    let value = overlap / Math.sqrt(Math.max(1, queryGrams.size * itemGrams.size)) * 8;
    item.keywords.forEach((keyword) => {
      const term = clean(keyword);
      if (term.length >= 2 && query.includes(term)) value += 3.5 + Math.min(term.length, 6) * 0.3;
    });
    if (query.includes(clean(item.topic))) value += 4;
    if (mentionsArticle(question, item.article)) value += 20;
    return value;
  }

  function matchReason(question, item, corpus) {
    if (mentionsArticle(question, item.article)) return `问题直接提及虚构条目 ${item.article}。`;
    const direct = [item.topic, ...item.keywords].filter((term) => clean(term).length >= 2 && clean(question).includes(clean(term)));
    if (direct.length) return `关键词命中：${[...new Set(direct)].slice(0, 2).join("、")}。`;
    for (const [canonical, variants] of Object.entries(corpus.synonyms || {})) {
      if ([item.topic, ...item.keywords].includes(canonical)) {
        const variant = variants.find((term) => question.includes(term));
        if (variant) return `同义词映射：${variant} → ${canonical}。`;
      }
    }
    return "条目主题与问题的文字有一定相关性。";
  }

  function retrieve(question, corpus, context = {}) {
    if (corpus?.source?.type !== "fictional_demo") throw new Error("仅允许虚构演示资料");
    const query = String(question || "").trim();
    if (!query) return {state: "no_evidence", matches: [], gap: "请先输入一个练习问题。", uncovered: []};
    const uncovered = uncoveredTopics(query, corpus);
    const supported = supportedQuestion(query, corpus);
    const selected = context.building_use || "";
    const nonResidential = /(非住宅|住宅以外|办公楼|办公建筑|写字楼|商场|商业建筑)/u.test(query);
    const residential = query.includes("住宅") && !nonResidential;
    if ((residential && selected === "non_residential") || (nonResidential && selected === "residential")) {
      return {state: "no_evidence", matches: [], uncovered,
        gap: "问题描述与所选建筑用途冲突，请先核对练习条件。"};
    }
    const use = buildingUse(query, selected);
    const measure = questionMeasure(supported);
    const additions = Object.entries(corpus.synonyms || {})
      .filter(([, variants]) => variants.some((variant) => supported.includes(variant)))
      .map(([canonical]) => canonical);
    const expanded = `${supported} ${additions.join(" ")}`;
    const ranked = (supported ? corpus.clauses : [])
      .filter((item) => !(item.building_use === "non_residential" && use === "residential"))
      .filter((item) => !(measure && item.measure && item.measure !== measure))
      .map((item) => ({item, score: score(expanded, item)}))
      .sort((left, right) => right.score - left.score || left.item.article.localeCompare(right.item.article));
    const threshold = Math.max(2.35, (ranked[0]?.score || 0) * 0.38);
    const matches = ranked.slice(0, 5).filter((entry) => entry.score >= threshold)
      .map(({item, score: value}) => ({...item, score: Math.round(value * 100) / 100,
        reason: matchReason(supported, item, corpus)}));
    const state = matches.length ? (uncovered.length ? "partial" : "candidate_only") : "no_evidence";
    const gap = uncovered.length
      ? (matches.length ? `“${uncovered.join("、")}”未被虚构资料覆盖；候选只对应问题的其他部分。` :
        `虚构资料未收录“${uncovered.join("、")}”所需内容。`)
      : (matches.length ? "找到虚构练习候选；不能据此作出项目判断。" : "虚构资料中没有足够相关的候选条目。");
    return {state, matches, gap, uncovered};
  }

  if (typeof module !== "undefined" && module.exports) module.exports = {retrieve};
  if (typeof document === "undefined") return;

  const form = document.getElementById("demo-form");
  if (!form) return;
  const question = document.getElementById("demo-question");
  const use = document.getElementById("demo-use");
  const status = document.getElementById("demo-status");
  const cards = document.getElementById("demo-results");
  const count = document.getElementById("demo-count");
  const loading = document.getElementById("demo-loading");
  let corpus = null;

  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  }

  function render(result) {
    const labels = {candidate_only: "找到虚构候选", partial: "仅覆盖部分问题", no_evidence: "没有充分候选"};
    status.className = `result-state ${result.state}`;
    status.replaceChildren(node("strong", "", labels[result.state]), node("span", "", result.gap));
    count.textContent = `${result.matches.length} 条虚构候选`;
    cards.replaceChildren();
    result.matches.forEach((match) => {
      const card = node("article", "result-card");
      const meta = node("div", "card-meta");
      meta.append(node("span", "article-id", `${corpus.source.standard} · ${match.article}`),
        node("span", "fiction-tag", "原创虚构 · 无工程效力"));
      card.append(meta, node("h3", "", match.topic),
        node("p", "", `命中原因：${match.reason}`),
        node("p", "", `练习记录：${match.check}`));
      const link = node("a", "source-link", "查看原创虚构资料 ↗");
      link.href = corpus.source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      card.append(link);
      cards.append(card);
    });
    if (!result.matches.length) cards.append(node("p", "empty-copy", "这个原型会停在资料缺口处，不编造规范条目或工程数值。"));
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!corpus) return;
    render(retrieve(question.value, corpus, {building_use: use.value}));
  });
  document.querySelectorAll("[data-demo-question]").forEach((button) => {
    button.addEventListener("click", () => {
      question.value = button.dataset.demoQuestion;
      use.value = "";
      form.requestSubmit();
      question.focus();
    });
  });

  fetch("demo-data.json", {cache: "no-store"})
    .then((response) => { if (!response.ok) throw new Error("资料加载失败"); return response.json(); })
    .then((data) => {
      if (data?.source?.type !== "fictional_demo" || !data.dataset_id?.startsWith("fictional_")) {
        throw new Error("资料类型不符合演示要求");
      }
      corpus = data;
      loading.hidden = true;
      form.querySelector("button[type=submit]").disabled = false;
      render(retrieve(question.value, corpus));
    })
    .catch(() => {
      loading.textContent = "虚构资料暂时无法加载。请稍后刷新，或使用本地 Python 版本。";
    });
})(typeof globalThis !== "undefined" ? globalThis : this);
