const form = document.getElementById("search-form");
const question = document.getElementById("question");
const city = document.getElementById("city");
const buildingUse = document.getElementById("building-use");
const projectKind = document.getElementById("project-kind");
const designStage = document.getElementById("design-stage");
const reviewer = document.getElementById("reviewer");
const submitButton = document.getElementById("search-button");
const previewButton = document.getElementById("preview-button");
const exportButton = document.getElementById("export-button");
const recordPreview = document.getElementById("record-preview");
const recordContent = document.getElementById("record-content");
const status = document.getElementById("status");
const changeNotice = document.getElementById("change-notice");
const count = document.getElementById("result-count");
const assessment = document.getElementById("assessment");
const searchExplanation = document.getElementById("search-explanation");
const cityNote = document.getElementById("city-note");
const aiNote = document.getElementById("ai-note");
const list = document.getElementById("result-list");
const modelState = document.getElementById("model-state");
const qualityBox = document.getElementById("quality-box");
const projectSelect = document.getElementById("project-select");
const projectName = document.getElementById("project-name");
const newProjectButton = document.getElementById("new-project");
const exportWorkbookButton = document.getElementById("export-workbook");
const deleteProjectButton = document.getElementById("delete-project");
const clearAllRecordsButton = document.getElementById("clear-all-records");
const useModel = document.getElementById("use-model");
const modelProvider = document.getElementById("model-provider");
const workbookStatus = document.getElementById("workbook-status");
const issueList = document.getElementById("issue-list");
const issueRef = document.getElementById("issue-ref");
const reviewStatus = document.getElementById("review-status");
const reviewedBy = document.getElementById("reviewed-by");
const reviewNote = document.getElementById("review-note");
const exampleNotice = document.getElementById("example-notice");
let currentReport = null;
let searchSequence = 0;
let projects = [];
let activeProjectId = "";
let currentQuality = null;
const STORAGE_KEY = "building-code-assistant.workbooks.v1";
const INDEX_NOTICE = "原创虚构练习条目，仅用于演示信息检索；不代表任何真实规范要求。";
const decisionLabels = {pending: "待核对", proposed: "列入待核对依据", excluded: "排除"};
const handoffLabels = {draft: "研读草稿", ready: "待负责人复核", returned: "退回补证据", recorded: "已记录人工复核"};

function stringItems(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === "string" && item.trim()) : [];
}

function joinExplanations(items, fallback) {
  const text = items.length ? items.map((item) => item.replace(/[。；\s]+$/u, "")).join("；") : fallback;
  return `${text}。`;
}

function evidenceLabel(value) {
  if (value === "fictional_demo") return "原创虚构练习 · 无工程效力";
  if (value === "expert_reviewed") return "资料已登记专业复核";
  if (value === "unreviewed_summary" || !value) return "条号索引 · 待专业复核";
  return typeof value === "string" && /[\u3400-\u9fff]/.test(value) ? value : "条号索引 · 待专业复核";
}

function matchKey(match) {
  return `${match.standard || ""}#${match.article || ""}`;
}

function contextExplanation(data, context) {
  const provided = data.search_explanation || {};
  const applied = Array.isArray(provided.applied_filters) ? stringItems(provided.applied_filters) : null;
  const recorded = Array.isArray(provided.recorded_only_filters) ? stringItems(provided.recorded_only_filters) : null;
  return {
    applied: applied !== null ? applied : [context.building_use
      ? "建筑用途仅对已标记用途的条目做初步筛选，不构成适用性结论。"
      : "建筑用途未填写，未启用用途标签初筛。"],
    recorded: recorded !== null ? recorded : ["所在地、项目类型和设计阶段只随问题记录，不参与自动适用判断。"],
    uncovered: stringItems(provided.uncovered_topics),
  };
}

function element(tag, className, content) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (content !== undefined) item.textContent = content;
  return item;
}

function activeProject() {
  return projects.find((project) => project.id === activeProjectId) || null;
}

function saveWorkbooks() {
  try {
    if (typeof localStorage === "undefined") throw new Error("unavailable");
    localStorage.setItem(STORAGE_KEY, JSON.stringify({activeProjectId, projects}));
    workbookStatus.textContent = "已保存在此浏览器 · 请定期导出备份";
    return true;
  } catch (error) {
    workbookStatus.textContent = "浏览器保存不可用；请立即导出项目记录，避免离开页面后丢失。";
    return false;
  }
}

function newProject(name = "未命名试点项目") {
  const project = {id: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    name, reports: [], createdAt: new Date().toISOString()};
  projects.unshift(project);
  activeProjectId = project.id;
  saveWorkbooks();
  renderWorkbook();
  return project;
}

function deleteCurrentProject() {
  const project = activeProject();
  if (!project || !confirm(`确定删除“${project.name}”及其中全部问题记录吗？此操作不能撤销，请先导出备份。`)) return;
  projects = projects.filter((entry) => entry.id !== project.id);
  searchSequence += 1;
  clearReport();
  clearInputs();
  if (projects.length) {
    activeProjectId = projects[0].id;
    saveWorkbooks();
    renderWorkbook();
    if (activeProject().reports[0]) showReport(activeProject().reports[0]);
  } else {
    newProject();
    localStorage.removeItem(STORAGE_KEY);
  }
  workbookStatus.textContent = "当前项目已删除；新操作前请留意浏览器内的空白项目。";
}

function clearAllRecords() {
  if (!confirm("确定清空本浏览器中的全部项目和问题记录吗？此操作不能撤销，请先导出备份。")) return;
  searchSequence += 1;
  projects = [];
  activeProjectId = "";
  clearReport();
  clearInputs();
  newProject();
  localStorage.removeItem(STORAGE_KEY);
  workbookStatus.textContent = "全部本地记录已清空。";
}

function reportChangeLabel(report) {
  const corpus = currentQuality && currentQuality.corpus;
  if (!corpus || !report.response) return "";
  const previous = report.response.clause_fingerprints || {};
  const current = corpus.clause_fingerprints || {};
  if (Object.keys(previous).some((key) => previous[key] !== current[key])) return "所引条目变化 · 待重核";
  if (report.response.source_fingerprint && corpus.source_fingerprint &&
      report.response.source_fingerprint !== corpus.source_fingerprint) return "来源信息变化 · 待重核";
  if (report.response.corpus_sha256 && report.response.corpus_sha256 !== corpus.corpus_sha256) {
    return "资料库变化 · 请核对版本";
  }
  if (!report.response.corpus_sha256) return "旧记录 · 请核对资料版本";
  return "";
}

function renderChangeNotice() {
  const change = currentReport ? reportChangeLabel(currentReport) : "";
  changeNotice.hidden = !change;
  if (change) changeNotice.textContent = `${change}。请重新运行虚构练习检索；旧记录不会自动改写。`;
}

function renderIssueList() {
  issueList.replaceChildren();
  const project = activeProject();
  const reports = project && Array.isArray(project.reports) ? project.reports : [];
  if (!reports.length) {
    issueList.append(element("span", "", "本项目尚无问题记录。"));
    return;
  }
  reports.forEach((report) => {
    const item = element("div", "issue-item");
    const info = element("div");
    info.append(element("strong", "", `${report.issueRef ? `${report.issueRef} · ` : ""}${report.question || "未命名问题"}`));
    info.append(element("span", "", `${handoffLabels[report.handoffStatus] || "研读草稿"} · ${report.createdAt || ""}`));
    const changed = reportChangeLabel(report);
    if (changed) info.append(element("span", "changed", changed));
    const open = element("button", "", "打开");
    open.type = "button";
    open.addEventListener("click", () => showReport(report));
    item.append(info, open);
    issueList.append(item);
  });
}

function renderWorkbook() {
  const project = activeProject();
  projectSelect.replaceChildren();
  projects.forEach((entry) => {
    const option = element("option", "", entry.name);
    option.value = entry.id;
    projectSelect.append(option);
  });
  projectSelect.value = activeProjectId;
  projectName.value = project ? project.name : "";
  renderIssueList();
}

function initializeWorkbook() {
  let migrated = false;
  try {
    if (typeof localStorage !== "undefined") {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (stored && Array.isArray(stored.projects)) {
        projects = stored.projects.filter((item) => item && typeof item.id === "string" &&
          typeof item.name === "string" && Array.isArray(item.reports));
        activeProjectId = stored.activeProjectId;
        projects.forEach((project) => (project.reports || []).forEach((report) => {
          const response = report.response || {};
          if (response.source_meta?.type !== "fictional_demo") {
            const reasons = Object.values(report.decisions || {}).map((decision) => decision?.reason).filter(Boolean);
            if (reasons.length) report.reviewNote = [report.reviewNote, ...reasons.map((reason) => `旧记录个人备注：${reason}`)].filter(Boolean).join("\n").slice(0, 2000);
            report.decisions = {};
            report.response = {matches: [], assessment: {state: "no_evidence", message: "旧版生成的候选索引已撤下；请使用虚构资料重新检索。", checks: []},
              source_meta: {type: "fictional_demo", version_review: "旧版生成内容已撤下"}, coverage: "旧版候选已撤下"};
            migrated = true;
          }
        }));
      }
    }
  } catch (error) {
    workbookStatus.textContent = "旧工作簿无法读取；请检查浏览器存储。";
  }
  if (!projects.length) newProject();
  if (!activeProject()) activeProjectId = projects[0].id;
  renderWorkbook();
  const latest = activeProject().reports[0];
  if (latest) showReport(latest);
  if (migrated) {
    saveWorkbooks();
    workbookStatus.textContent = "旧版生成的真实规范索引已从本地记录中移除；个人备注已保留，请重新检索。";
  }
}

async function loadModelStatus() {
  try {
    const response = await fetch("/api/health", {cache: "no-store"});
    if (!response.ok) throw new Error("unavailable");
    const session = await response.json();
    useModel.disabled = !session.model_ready;
    modelProvider.textContent = session.model_ready
      ? `发送目标：${session.model_provider}。`
      : "未配置可用模型，外发选项已禁用。";
  } catch (error) {
    useModel.disabled = true;
    modelProvider.textContent = "模型配置状态不可用，外发选项已禁用。";
  }
}

function touchReport() {
  if (!currentReport) return;
  currentReport.updatedAt = new Date().toISOString();
  saveWorkbooks();
  renderIssueList();
  refreshOpenPreview();
}

async function loadQuality() {
  try {
    const response = await fetch("/api/quality");
    if (!response.ok) throw new Error("质量状态暂不可用");
    const data = await response.json();
    currentQuality = data;
    renderIssueList();
    renderChangeNotice();
    qualityBox.replaceChildren(element("strong", "", "资料与评测状态"));
    const lines = [
      `已收录原创虚构练习条目 ${data.corpus.clause_count} 条 · 无真实规范效力`,
      `独立标注 ${data.evaluation.reviewed_count}/${data.expert_target} 道目标题 · 当前版本有效 ${data.evaluation.current_version_scored_count || 0} 道`,
      `开发者回归样本 ${data.developer_regression_cases} 道（不代表业务准确率）`,
      data.corpus.fictional_demo ? "完全虚构，不对应真实规范或工程要求" : (data.corpus.version_verified ? "版本核验已登记" : "现行版本与后续修订待核验"),
    ];
    lines.forEach((line) => qualityBox.append(element("p", "", line)));
    if (data.evaluation.current_version_scored_count) {
      const value = data.evaluation.top3_reference_recall;
      qualityBox.append(element("p", "quality-metric",
        value === null ? "已标注样本暂无可计算的召回率" :
          `已标注样本前 3 条召回：${(value * 100).toFixed(0)}%（样本量有限）`));
    }
    if (data.evaluation.mixed_snapshot_versions) {
      qualityBox.append(element("p", "quality-error", "评测快照涉及不同语料或检索版本；页面指标仅统计当前版本。"));
    }
    if ((data.evaluation.outdated_snapshot_ids || []).length) {
      qualityBox.append(element("p", "", `${data.evaluation.outdated_snapshot_ids.length} 道旧版本快照未计入当前指标。`));
    }
    if (data.corpus.errors.length) {
      qualityBox.append(element("p", "quality-error", `资料或评测表问题：${data.corpus.errors.length} 项`));
    }
  } catch (error) {
    qualityBox.replaceChildren(element("strong", "", "资料与评测状态"));
    qualityBox.append(element("p", "", error.message || "暂不可用"));
  }
}

function renderAssessment(data) {
  assessment.replaceChildren();
  const review = data.assessment || {};
  const stateLabels = {
    no_evidence: "当前无充分候选依据",
    partial: "仅覆盖了部分提问",
  };
  assessment.append(element("strong", "", stateLabels[review.state] || "候选依据仍需核验"));
  if (review.message) assessment.append(element("p", "", review.message));
  const missing = stringItems(review.missing_context);
  if (missing.length) assessment.append(element("p", "", `建议补充：${missing.join("、")}。`));
  const clarifications = Array.isArray(review.clarifications) ? review.clarifications : [];
  if (clarifications.length) {
    const box = element("div", "clarification-list");
    box.append(element("strong", "", "核对前请确认"));
    clarifications.forEach((entry) => {
      if (entry && typeof entry.question === "string") {
        box.append(element("p", "", `${entry.question} ${entry.reason || ""}`));
      }
    });
    assessment.append(box);
  }
  const details = element("details", "review-details");
  details.append(element("summary", "", "展开练习清单与资料说明"));
  const checks = element("ul");
  stringItems(review.checks).forEach((check) => checks.append(element("li", "", check)));
  if (checks.children.length) details.append(checks);
  const sourceMeta = data.source_meta || {};
  details.append(element("p", "version-line", `资料状态：${sourceMeta.version_review || "虚构演示"}。编写日期：${data.source_checked_on || "未登记"}。`));
  if (sourceMeta.announcement_url && sourceMeta.type !== "fictional_demo") {
    const announcement = element("a", "", "查看资料来源 ↗");
    announcement.href = sourceMeta.announcement_url;
    announcement.target = "_blank";
    announcement.rel = "noopener noreferrer";
    details.append(announcement);
  }
  assessment.append(details);
  assessment.hidden = false;
}

function renderSearchExplanation(data, context) {
  searchExplanation.replaceChildren();
  const explanation = contextExplanation(data, context);
  const useFromQuestion = !context.building_use && explanation.applied.some((item) =>
    item.includes("建筑用途") && (item.includes("从问题识别") || item.includes("从问题初筛")));
  const heading = element("div", "condition-heading");
  heading.append(element("strong", "", "本次输入条件"));
  heading.append(element("span", "", "系统如何使用这些条件"));
  searchExplanation.append(heading);
  const grid = element("div", "condition-grid");
  [
    ["建筑用途", context.building_use ? context.building_use_label : (useFromQuestion ? "未选择 · 从问题识别" : context.building_use_label),
      context.building_use ? "标签初筛" : (useFromQuestion ? "从问题初筛" : "未启用初筛")],
    ["所在地", context.city || "未填写", context.city ? "仅记录" : "未参与判断"],
    ["项目类型", context.project_kind_label, context.project_kind ? "仅记录" : "未参与判断"],
    ["设计阶段", context.design_stage_label, context.design_stage ? "仅记录" : "未参与判断"],
  ].forEach(([label, value, effect]) => {
    const item = element("div", "condition-item");
    item.append(element("span", "condition-label", label));
    item.append(element("strong", "condition-value", value));
    item.append(element("span", "condition-effect", effect));
    grid.append(item);
  });
  searchExplanation.append(grid);
  searchExplanation.append(element("p", "condition-detail", `实际筛选：${joinExplanations(explanation.applied, "未执行已标注的条件筛选")}`));
  searchExplanation.append(element("p", "condition-detail", `仅记录：${joinExplanations(explanation.recorded, "本次未填写可记录的附加条件")}`));
  if (explanation.uncovered.length) {
    searchExplanation.append(element("p", "condition-gap", `当前资料未覆盖：${explanation.uncovered.join("、")}`));
  }
  searchExplanation.hidden = false;
}

function renderMatch(match) {
  const card = element("article", "result-card");
  const top = element("div", "card-top");
  const identity = element("div", "card-identity");
  identity.append(element("span", "article-chip", `${match.standard || "虚构资料"} · ${match.article || "?"}`));
  identity.append(element("h3", "", match.topic || "候选条文"));
  top.append(identity);
  top.append(element("span", "evidence-chip", evidenceLabel(match.evidence_status)));
  card.append(top);
  card.append(element("p", "match-reason", `命中原因：${match.match_reason || "条目主题与提问相关，具体适用条件仍需人工核对。"}`));
  card.append(element("p", "summary", `资料说明：${match.summary || "请打开来源核对条文内容。"}`));
  card.append(element("p", "check", `适用条件待核对：${match.check || "请核对项目条件与正式规范文本。"}`));
  if (match.building_use === "non_residential") {
    card.append(element("p", "scope-tag", "适用范围标签：非住宅民用建筑"));
  }
  const source = element("div", "source");
  source.append(element("span", "", `来源：${match.source_name || "待核对"}`));
  if (match.source_url) {
    const link = element("a", "", "打开原创虚构资料 ↗");
    link.href = match.source_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    source.append(link);
  }
  card.append(source);
  const decision = element("div", "decision");
  decision.append(element("div", "decision-title", "练习研读决定 · 真实项目须另查正式规范"));
  const controls = element("div", "decision-controls");
  const label = element("label", "", `${match.article} 的处理`);
  const select = element("select");
  select.setAttribute("aria-label", `${match.article} 的练习研读决定`);
  Object.entries(decisionLabels).forEach(([value, text]) => {
    const option = element("option", "", text);
    option.value = value;
    select.append(option);
  });
  const key = matchKey(match);
  if (!currentReport.decisions[key]) currentReport.decisions[key] = {status: "pending", reason: "", updatedAt: ""};
  select.value = currentReport.decisions[key].status;
  select.addEventListener("change", () => {
    if (currentReport && currentReport.decisions[key]) {
      currentReport.decisions[key].status = select.value;
      currentReport.decisions[key].updatedAt = new Date().toLocaleString("zh-CN");
      touchReport();
    }
  });
  controls.append(label, select);
  decision.append(controls);
  const reasonLabel = element("label", "reason-label", "研读理由或待核对问题");
  const reason = element("textarea", "decision-reason");
  reason.rows = 2;
  reason.maxLength = 240;
  reason.placeholder = "例如：练习中还需记录走廊服务空间。";
  reason.setAttribute("aria-label", `${match.article} 的研读理由或待核对问题`);
  reason.value = currentReport.decisions[key].reason || "";
  reason.addEventListener("input", () => {
    if (currentReport && currentReport.decisions[key]) {
      currentReport.decisions[key].reason = reason.value.trim();
      currentReport.decisions[key].updatedAt = new Date().toLocaleString("zh-CN");
      touchReport();
    }
  });
  decision.append(reasonLabel, reason);
  card.append(decision);
  return card;
}

function fieldLabel(select) {
  return select.options[select.selectedIndex].textContent;
}

function reportMarkdown(report, projectLabel = (activeProject() || {}).name || "未命名项目") {
  const {question: query, context, response, decisions, createdAt} = report;
  const review = response.assessment || {};
  const sourceMeta = response.source_meta || {};
  const explanation = contextExplanation(response, context);
  const matches = Array.isArray(response.matches) ? response.matches : [];
  const lines = [
    "# 建筑规范检索核验记录",
    "",
    `项目：${projectLabel}`,
    `图纸或问题编号：${report.issueRef || "未填写"}`,
    `生成时间：${createdAt}`,
    `项目研读人：${report.reviewer || "未填写"}`,
    `交接状态：${handoffLabels[report.handoffStatus] || "研读草稿"}`,
    `复核记录人：${report.reviewedBy || "未填写"}`,
    `交接意见：${report.reviewNote || "未填写"}`,
    "说明：交接状态和项目研读决定由用户手工记录，不代表条文资料经过专业复核或项目合规。",
    `设计问题：${query}`,
    `所在地：${context.city || "未填写"}`,
    `建筑用途：${context.building_use_label}`,
    `项目类型：${context.project_kind_label}`,
    `设计阶段：${context.design_stage_label}`,
    "",
    "## 输入条件的实际作用",
    `执行的初筛：${joinExplanations(explanation.applied, "未执行已标注的条件筛选")}`,
    `仅记录的条件：${joinExplanations(explanation.recorded, "本次未填写可记录的附加条件")}`,
    `未覆盖专题：${explanation.uncovered.join("、") || "未标记"}`,
    "建筑用途只用于条目标签初筛；所在地、项目类型和设计阶段不参与自动适用判断。",
    "",
    `结果状态：${review.message || "仍需人工核验"}`,
    `未补充条件：${stringItems(review.missing_context).join("、") || "无"}`,
    `资料覆盖：${response.coverage || "未说明"}`,
    `版本核验：${sourceMeta.version_review || "待核验"}`,
    `虚构资料编写日期：${response.source_checked_on || "未登记"}`,
    `资料库指纹：${response.corpus_sha256 || "未记录"}`,
    `资料变化提示：${reportChangeLabel(report) || "当前未发现本地资料变化；仍须核对正式现行来源"}`,
    "",
    "## 候选依据与项目研读决定",
  ];
  if (!matches.length) lines.push("当前资料中没有足够相关的候选条文。");
  matches.forEach((match) => {
    const decision = decisions[matchKey(match)] || {status: "pending", reason: "", updatedAt: ""};
    lines.push(
      "",
      `### ${match.standard} ${match.article} · ${match.topic}`,
      `证据状态：${evidenceLabel(match.evidence_status)}`,
      `命中原因：${match.match_reason || "旧版接口未提供命中原因"}`,
      `资料说明：${match.summary || "未提供"}`,
      `适用条件待核对：${match.check || "未提供"}`,
      `来源：${match.source_name || "待核对"}`,
      `来源链接：${match.source_url || "未提供"}`,
      `项目研读决定：${decisionLabels[decision.status] || "待核对"}`,
      `研读理由：${decision.reason || "未填写"}`,
      `决定记录时间：${decision.updatedAt || "尚未作出决定"}`
    );
  });
  const clarifications = Array.isArray(review.clarifications) ? review.clarifications : [];
  if (clarifications.length) lines.push("", "## 核对前需确认", ...clarifications.map((item) =>
    `- ${item.question || "待补充条件"} ${item.reason || ""}`));
  lines.push("", "## 核验清单", ...stringItems(review.checks).map((item) => `- [ ] ${item}`));
  lines.push("", "本记录基于完全虚构资料，不对应真实规范或工程要求，不构成项目合规结论。");
  return lines.join("\n");
}

function refreshOpenPreview() {
  if (currentReport && !recordPreview.hidden && recordPreview.open) {
    recordContent.textContent = reportMarkdown(currentReport);
  }
}

function downloadMarkdown(content, filename) {
  const blob = new Blob([content], {type: "text/markdown;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportReport() {
  if (!currentReport) return;
  previewReport();
  downloadMarkdown(reportMarkdown(currentReport),
    `建筑规范核验记录-${new Date().toISOString().slice(0, 10)}.md`);
}

function exportWorkbook() {
  const project = activeProject();
  if (!project) return;
  const reports = project.reports.map((report) => reportMarkdown(report, project.name));
  const content = [`# ${project.name} · 建筑规范研读工作簿`, "",
    `导出时间：${new Date().toLocaleString("zh-CN")}`,
    `问题记录：${reports.length} 条`,
    "说明：本工作簿只记录检索和人工研读过程，不构成项目合规结论。",
    "", ...reports.flatMap((report, index) => [`---\n\n## 问题 ${index + 1}\n\n${report}`, ""])].join("\n");
  downloadMarkdown(content, `建筑规范项目工作簿-${new Date().toISOString().slice(0, 10)}.md`);
}

function previewReport() {
  if (!currentReport) return;
  recordContent.textContent = reportMarkdown(currentReport);
  recordPreview.hidden = false;
  recordPreview.open = true;
}

function clearReport() {
  currentReport = null;
  previewButton.disabled = true;
  exportButton.disabled = true;
  recordPreview.hidden = true;
  recordContent.textContent = "";
  list.replaceChildren();
  count.textContent = "等待检索";
  assessment.hidden = true;
  searchExplanation.hidden = true;
  aiNote.hidden = true;
  cityNote.hidden = true;
  changeNotice.hidden = true;
  status.textContent = "输入问题，开始检索候选依据。";
}

function clearInputs() {
  exampleNotice.hidden = true;
  question.value = "";
  city.value = "";
  buildingUse.value = "";
  projectKind.value = "";
  designStage.value = "";
  issueRef.value = "";
  reviewer.value = "";
  reviewStatus.value = "draft";
  reviewedBy.value = "";
  reviewNote.value = "";
}

function showReport(report) {
  exampleNotice.hidden = true;
  currentReport = report;
  const context = report.context || {};
  const data = report.response || {};
  const matches = Array.isArray(data.matches) ? data.matches : [];
  question.value = report.question || "";
  city.value = context.city || "";
  buildingUse.value = context.building_use || "";
  projectKind.value = context.project_kind || "";
  designStage.value = context.design_stage || "";
  issueRef.value = report.issueRef || "";
  reviewer.value = report.reviewer || "";
  reviewStatus.value = report.handoffStatus || "draft";
  reviewedBy.value = report.reviewedBy || "";
  reviewNote.value = report.reviewNote || "";
  previewButton.disabled = false;
  exportButton.disabled = false;
  recordPreview.hidden = true;
  modelState.textContent = data.ai_note ? "AI 条号提示已生成" : "本地条号检索";
  renderSearchExplanation(data, context);
  renderAssessment(data);
  count.textContent = `${matches.length} 条候选`;
  list.replaceChildren();
  if (!matches.length) {
    status.textContent = "未找到足够相关的已收录条目。";
    const empty = element("div", "empty-state");
    empty.append(element("strong", "", "需要扩大资料范围或补充条件"));
    empty.append(element("span", "", "虚构资料没有相关条目；真实项目请另查有权使用的正式规范。"));
    list.append(empty);
  } else {
    status.textContent = "以下为原创虚构练习候选，无真实规范效力。";
    matches.forEach((match) => list.append(renderMatch(match)));
  }
  if (data.city_note && !data.search_explanation) {
    cityNote.textContent = data.city_note;
    cityNote.hidden = false;
  } else cityNote.hidden = true;
  if (data.ai_note) {
    aiNote.replaceChildren(element("strong", "", "AI 虚构条目提示 · 无工程效力"));
    aiNote.append(element("span", "", data.ai_note));
    aiNote.hidden = false;
  } else aiNote.hidden = true;
  renderIssueList();
  renderChangeNotice();
}

async function runSearch() {
  const query = question.value.trim();
  if (!query) {
    status.textContent = "请输入一个具体设计问题。";
    return;
  }
  exampleNotice.hidden = true;
  const sequence = ++searchSequence;
  const requestModel = useModel.checked;
  useModel.checked = false;
  submitButton.disabled = true;
  previewButton.disabled = true;
  exportButton.disabled = true;
  clearReport();
  status.classList.remove("error");
  status.textContent = "正在检索原创虚构练习条目…";
  list.replaceChildren();
  count.textContent = "检索中";
  assessment.hidden = true;
  searchExplanation.hidden = true;
  aiNote.hidden = true;
  cityNote.hidden = true;
  const context = {
    city: city.value.trim(),
    building_use: buildingUse.value,
    project_kind: projectKind.value,
    design_stage: designStage.value,
    building_use_label: fieldLabel(buildingUse),
    project_kind_label: fieldLabel(projectKind),
    design_stage_label: fieldLabel(designStage),
  };
  try {
    const sessionResponse = await fetch("/api/health", {cache: "no-store"});
    if (!sessionResponse.ok) throw new Error("本机连接校验失败");
    const session = await sessionResponse.json();
    const response = await fetch("/api/search", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Local-Token": session.local_token},
      body: JSON.stringify({question: query, city: context.city, building_use: context.building_use,
        project_kind: context.project_kind, design_stage: context.design_stage,
        use_model: requestModel && session.model_ready})
    });
    const data = await response.json();
    if (sequence !== searchSequence) return;
    if (!response.ok) throw new Error(data.error || "检索失败");
    const report = {id: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      question: query, context, response: data, decisions: {}, reviewer: reviewer.value.trim(),
      issueRef: issueRef.value.trim(), handoffStatus: "draft", reviewedBy: "", reviewNote: "",
      createdAt: new Date().toLocaleString("zh-CN")};
    activeProject().reports.unshift(report);
    showReport(report);
    saveWorkbooks();
  } catch (error) {
    if (sequence !== searchSequence) return;
    status.classList.add("error");
    status.textContent = error.message || "检索失败，请稍后重试。";
    count.textContent = "未完成";
  } finally {
    if (sequence === searchSequence) submitButton.disabled = false;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  runSearch();
});
exportButton.addEventListener("click", exportReport);
previewButton.addEventListener("click", previewReport);
exportWorkbookButton.addEventListener("click", exportWorkbook);
deleteProjectButton.addEventListener("click", deleteCurrentProject);
clearAllRecordsButton.addEventListener("click", clearAllRecords);
newProjectButton.addEventListener("click", () => {
  searchSequence += 1;
  newProject();
  clearReport();
  clearInputs();
  projectName.focus();
});
projectSelect.addEventListener("change", () => {
  searchSequence += 1;
  activeProjectId = projectSelect.value;
  saveWorkbooks();
  renderWorkbook();
  const latest = activeProject().reports[0];
  if (latest) showReport(latest);
  else {
    clearReport();
    clearInputs();
  }
});
projectName.addEventListener("input", () => {
  const project = activeProject();
  if (!project) return;
  project.name = projectName.value.trim() || "未命名试点项目";
  for (const option of projectSelect.options) {
    if (option.value === project.id) option.textContent = project.name;
  }
  saveWorkbooks();
  refreshOpenPreview();
});
issueRef.addEventListener("input", () => {
  if (currentReport) {
    currentReport.issueRef = issueRef.value.trim();
    touchReport();
  }
});
reviewer.addEventListener("input", () => {
  if (currentReport) {
    currentReport.reviewer = reviewer.value.trim();
    touchReport();
  }
});
reviewStatus.addEventListener("change", () => {
  if (!currentReport) return;
  if (reviewStatus.value === "recorded" && (!reviewedBy.value.trim() || !reviewNote.value.trim())) {
    reviewStatus.value = currentReport.handoffStatus || "draft";
    workbookStatus.textContent = "记录人工复核前，请填写复核记录人和交接意见。";
    return;
  }
  currentReport.handoffStatus = reviewStatus.value;
  touchReport();
});
reviewedBy.addEventListener("input", () => {
  if (currentReport) {
    currentReport.reviewedBy = reviewedBy.value.trim();
    if (currentReport.handoffStatus === "recorded" && !currentReport.reviewedBy) {
      currentReport.handoffStatus = "ready";
      reviewStatus.value = "ready";
    }
    touchReport();
  }
});
reviewNote.addEventListener("input", () => {
  if (currentReport) {
    currentReport.reviewNote = reviewNote.value.trim();
    if (currentReport.handoffStatus === "recorded" && !currentReport.reviewNote) {
      currentReport.handoffStatus = "ready";
      reviewStatus.value = "ready";
    }
    touchReport();
  }
});
document.querySelectorAll("[data-example]").forEach((button) => {
  button.addEventListener("click", () => {
    question.value = button.dataset.example;
    exampleNotice.textContent = `已填入“${button.dataset.demoLabel}”演示问题，等待检索。所在地和其他项目条件保持原样；点击“检索相关条文”后，结果保存到当前项目。现有研读记录未修改。`;
    exampleNotice.hidden = false;
    question.focus();
  });
});
initializeWorkbook();
if (!currentReport) modelState.textContent = "本地条号检索";
loadQuality();
loadModelStatus();
