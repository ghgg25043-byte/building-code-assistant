const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeNode {
  constructor(tag = "div") {
    this.tagName = tag;
    this.children = [];
    this.options = [];
    this.listeners = {};
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.open = false;
    this.selectedIndex = 0;
    this.checked = false;
    this.classList = {add() {}, remove() {}};
  }
  append(...nodes) {
    this.children.push(...nodes);
    if (this.tagName === "select") this.options.push(...nodes);
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.options = [];
    this.append(...nodes);
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
  click() { this.clicked = true; }
  focus() { this.focused = true; }
  remove() {}
}

function walk(node, predicate) {
  if (predicate(node)) return node;
  for (const child of node.children) {
    const found = walk(child, predicate);
    if (found) return found;
  }
  return null;
}

function setSelect(node, value, label) {
  node.value = value;
  node.options = [{textContent: label}];
  node.selectedIndex = 0;
}

async function main() {
  const ids = new Map();
  for (const id of ["search-form", "question", "city", "building-use", "project-kind",
    "design-stage", "reviewer", "search-button", "preview-button", "export-button",
    "record-preview", "record-content", "status", "change-notice", "result-count", "assessment",
    "search-explanation", "city-note", "ai-note", "result-list", "model-state", "quality-box",
    "project-select", "project-name", "new-project", "export-workbook", "workbook-status",
    "delete-project", "clear-all-records", "use-model", "model-provider",
    "issue-list", "issue-ref", "review-status", "reviewed-by", "review-note", "example-notice"]) {
    ids.set(id, new FakeNode());
  }
  ids.get("question").value = "办公楼公共走廊净宽和消防疏散要求";
  ids.get("city").value = "上海市";
  ids.get("reviewer").value = "李工";
  setSelect(ids.get("building-use"), "non_residential", "非住宅民用建筑");
  setSelect(ids.get("project-kind"), "new", "新建");
  setSelect(ids.get("design-stage"), "scheme", "方案设计");

  const match = {
    standard: "DEMO-ARCH-001", article: "D-11", topic: "公共走廊净宽",
    summary: "走廊净宽的通用下限需结合场所核对。", check: "确认服务场所。",
    source_name: "本项目原创虚构练习资料", source_url: "https://example.com/demo-source.md", page: 14,
    match_reason: "关键词命中：公共走廊；仅用于定位候选条目。",
    evidence_status: "unreviewed_summary", building_use: "non_residential",
  };
  let searchResponse = {
    matches: [match],
    search_explanation: {
      applied_filters: ["按建筑用途标签初筛", "按宽度指标初筛"],
      recorded_only_filters: ["上海市仅记录", "新建仅记录", "方案设计仅记录"],
      uncovered_topics: ["消防疏散"],
    },
    assessment: {state: "partial", message: "仅覆盖走廊部分。", missing_context: ["服务场所"],
      checks: ["核对正式规范原文"], clarifications: [{question: "是否承担疏散功能？", reason: "需另查。"}]},
    coverage: "部分摘录", source_meta: {version_review: "待核验", announcement_url: "https://example.com/notice"},
    source_checked_on: "2026-09-26", model_ready: false, corpus_sha256: "corpus-a",
    source_fingerprint: "source-a", clause_fingerprints: {"DEMO-ARCH-001#D-11": "clause-a"},
  };
  let exportedBlob = null;
  const saved = new Map();
  const searchRequests = [];
  const searchHeaders = [];
  let sessionReady = false;
  const html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");
  const examples = [...html.matchAll(/data-example="([^"]+)" data-demo-label="([^"]+)"/g)].map((match) => {
    const button = new FakeNode("button");
    button.dataset = {example: match[1], demoLabel: match[2]};
    return button;
  });
  assert.equal(examples.length, 3, "The page offers three explicit demo questions");
  const context = vm.createContext({
    document: {
      getElementById: (id) => ids.get(id),
      querySelectorAll: (selector) => selector === "[data-example]" ? examples : [],
      createElement: (tag) => new FakeNode(tag),
      body: new FakeNode("body"),
    },
    fetch: async (url, options) => {
      if (url === "/api/search") {
        searchRequests.push(JSON.parse(options.body));
        searchHeaders.push(options.headers);
      }
      return {ok: true, json: async () => url === "/api/search" ? searchResponse : url === "/api/health" ?
        {local_token: "test-local-token", model_ready: sessionReady, model_provider: sessionReady ? "example.test" : null} : {
      corpus: {clause_count: 14, expert_reviewed_clauses: 0, version_verified: false, errors: [],
        corpus_sha256: "corpus-a", source_fingerprint: "source-a",
        clause_fingerprints: {"DEMO-ARCH-001#D-11": "clause-a"}},
      evaluation: {reviewed_count: 0}, expert_target: 50, developer_regression_cases: 12,
    }};
    },
    localStorage: {getItem: (key) => saved.get(key) || null, setItem: (key, value) => saved.set(key, value),
      removeItem: (key) => saved.delete(key)},
    confirm: () => true,
    URL: {createObjectURL: (blob) => { exportedBlob = blob; return "blob:test"; }, revokeObjectURL() {}},
    Blob, setTimeout: () => {}, Date, console,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8"), context);
  assert.equal(JSON.parse(saved.values().next().value).projects[0].reports.length, 0);
  await vm.runInContext("runSearch()", context);
  await new Promise(setImmediate);
  assert.equal(searchHeaders[0]["X-Local-Token"], "test-local-token");

  assert.equal(ids.get("result-count").textContent, "1 条候选");
  assert.equal(ids.get("issue-list").children.length, 1);
  assert.equal(ids.get("search-explanation").hidden, false);
  assert.match(ids.get("search-explanation").children.at(-1).textContent, /消防疏散/);
  assert.equal(ids.get("assessment").children[0].textContent, "仅覆盖了部分提问");
  assert.ok(walk(ids.get("assessment"), (node) => node.textContent.includes("是否承担疏散功能")));
  const card = ids.get("result-list").children[0];
  const decisionSelect = walk(card, (node) => node.tagName === "select");
  const reason = walk(card, (node) => node.tagName === "textarea");
  assert.ok(decisionSelect && reason);
  decisionSelect.value = "proposed";
  decisionSelect.listeners.change();
  reason.value = "服务场所已核对，仍需确认正式原文。";
  reason.listeners.input();
  ids.get("preview-button").listeners.click();
  assert.match(ids.get("record-content").textContent, /项目研读人：李工/);
  assert.match(ids.get("record-content").textContent, /项目研读决定：列入待核对依据/);
  assert.match(ids.get("record-content").textContent, /服务场所已核对/);
  assert.match(ids.get("record-content").textContent, /条号索引 · 待专业复核/);
  reason.value = "还需复核正式文本";
  reason.listeners.input();
  assert.match(ids.get("record-content").textContent, /还需复核正式文本/);
  ids.get("export-button").listeners.click();
  assert.match(await exportedBlob.text(), /项目研读决定：列入待核对依据/);

  searchResponse = {...searchResponse, matches: [{...match, match_reason: undefined, evidence_status: undefined}],
    search_explanation: undefined};
  await vm.runInContext("runSearch()", context);
  assert.equal(ids.get("issue-list").children.length, 2);
  assert.equal(JSON.parse(saved.values().next().value).projects[0].reports.length, 2);
  assert.match(ids.get("search-explanation").children.at(-2).textContent, /建筑用途/);
  assert.match(ids.get("result-list").children[0].children[1].textContent, /命中原因/);
  ids.get("issue-list").children[1].children[1].listeners.click();
  assert.match(ids.get("result-list").children[0].children.at(-1).children.at(-1).value, /还需复核正式文本/);
  ids.get("export-workbook").listeners.click();
  assert.match(await exportedBlob.text(), /问题记录：2 条/);
  vm.runInContext("currentQuality.corpus.clause_fingerprints['DEMO-ARCH-001#D-11'] = 'clause-updated'; renderIssueList(); renderChangeNotice()", context);
  assert.ok(walk(ids.get("issue-list"), (node) => node.textContent.includes("所引条目变化")));
  assert.equal(ids.get("change-notice").hidden, false);

  const savedBeforeDemo = saved.values().next().value;
  const requestCount = searchRequests.length;
  const preservedIds = ["city", "building-use", "project-kind", "design-stage", "project-name",
    "project-select", "issue-ref", "reviewer", "review-status", "reviewed-by", "review-note"];
  const inputValues = preservedIds.map((id) => ids.get(id).value);
  for (const button of examples) {
    button.listeners.click();
    assert.equal(ids.get("question").value, button.dataset.example);
    assert.equal(ids.get("example-notice").hidden, false);
    assert.match(ids.get("example-notice").textContent, /等待检索/);
    assert.equal(searchRequests.length, requestCount, "A demo choice must not start a search");
    assert.equal(saved.values().next().value, savedBeforeDemo, "Demo choices preserve saved workbooks");
    assert.deepEqual(preservedIds.map((id) => ids.get(id).value), inputValues,
      "Demo choices preserve the user's project conditions and review fields");
  }
  await vm.runInContext("runSearch()", context);
  assert.equal(searchRequests.at(-1).question, examples.at(-1).dataset.example);
  assert.equal(searchRequests.at(-1).city, "上海市");
  assert.equal(ids.get("example-notice").hidden, true);
  assert.equal(searchRequests.at(-1).use_model, false, "Model transmission stays off by default");
  sessionReady = true;
  await vm.runInContext("loadModelStatus()", context);
  assert.equal(ids.get("use-model").disabled, false);
  assert.match(ids.get("model-provider").textContent, /example\.test/);
  ids.get("use-model").checked = true;
  await vm.runInContext("runSearch()", context);
  assert.equal(searchRequests.at(-1).use_model, true, "Model transmission requires a fresh opt-in");
  assert.equal(ids.get("use-model").checked, false, "Opt-in resets after each search");
  vm.runInContext("delete projects[0].reports[0].response.source_meta.type; projects[0].reports[0].response.matches[0].summary = '旧版转述'; projects[0].reports[0].response.ai_note = '旧版提示'; saveWorkbooks(); initializeWorkbook()", context);
  assert.match(ids.get("workbook-status").textContent, /旧版生成的真实规范索引已从本地记录中移除/);
  assert.doesNotMatch(saved.values().next().value, /旧版转述|旧版提示/);
  ids.get("clear-all-records").listeners.click();
  assert.equal(saved.size, 0, "Clearing all records removes persistent browser data");
  assert.equal(ids.get("issue-list").children[0].textContent, "本项目尚无问题记录。");
  console.log("frontend smoke checks passed");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
