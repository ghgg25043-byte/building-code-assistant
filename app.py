"""Local building-workflow retrieval demo with entirely fictional source data."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request
from urllib.parse import urlparse

from search_engine import load_corpus, retrieve
from quality import clause_fingerprints, corpus_fingerprint, quality_snapshot, source_fingerprint


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
CORPUS = load_corpus()
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
LOCAL_TOKEN = secrets.token_urlsafe(32)


def model_endpoint_is_safe() -> bool:
    try:
        endpoint = urlparse(os.environ.get("LLM_API_URL", ""))
        hostname = endpoint.hostname
        return (endpoint.scheme == "https" or
                (endpoint.scheme == "http" and hostname in {"localhost", "127.0.0.1", "::1"})) and bool(hostname) and not endpoint.username and not endpoint.password
    except ValueError:
        return False


def model_ready() -> bool:
    return all(os.environ.get(name) for name in ("LLM_API_URL", "LLM_API_KEY", "LLM_MODEL")) and model_endpoint_is_safe()


def assessment(matches: list[dict], coverage_gap: str, context: dict,
               search_explanation: dict | None = None,
               question: str = "") -> dict:
    missing = []
    if not context["city"]:
        missing.append("项目所在地")
    if not context["building_use"]:
        missing.append("建筑用途")
    if not context["project_kind"]:
        missing.append("新建或改造")
    if not context["design_stage"]:
        missing.append("设计阶段")
    checks = ["当前候选只对应虚构练习资料", "真实项目另查有权使用的正式规范并由专业人员核验"]
    uncovered = (search_explanation or {}).get("uncovered_topics", [])
    if uncovered:
        checks.append(f"对未覆盖的{'、'.join(uncovered)}另查正式专项依据")
    checks.extend(match["check"] for match in matches[:3])
    state = "no_evidence" if not matches else ("partial" if uncovered else "candidate_only")
    articles = {match["article"] for match in matches}
    clarifications = []
    if "D-11" in articles:
        clarifications.append({
            "question": "这条走廊是否同时承担消防疏散功能？",
            "reason": "当前资料不覆盖消防专项要求；该问题需要另行核对正式专项依据。",
        })
    if articles.intersection({"D-09", "D-10"}):
        clarifications.append({
            "question": "楼梯用于日常交通，还是同时承担疏散功能？",
            "reason": "当前候选只用于定位公共楼梯条目，疏散要求需要另查。",
        })
    if articles.intersection({"D-03", "D-04"}) and "建筑高度" in question:
        clarifications.append({
            "question": "建筑高度问题涉及不同屋面、地坪，还是屋顶设备用房？",
            "reason": "先明确所问情形；虚构条目不能回答真实规范要求。",
        })
    if not context["building_use"]:
        clarifications.append({
            "question": "项目属于哪一类民用建筑？",
            "reason": "建筑用途当前仅参与标签初筛，具体适用性仍需专业核验。",
        })
    return {
        "state": state,
        "message": coverage_gap or "找到虚构练习候选；不能据此作出项目合规结论。",
        "missing_context": missing,
        "checks": list(dict.fromkeys(checks)),
        "clarifications": clarifications,
    }


def _safe_ai_note(note: str, matches: list[dict]) -> bool:
    """Accept only a fixed, app-controlled reading prompt for a returned article."""
    allowed_articles = {item["article"] for item in matches[:3]}
    return any(note == f"请核对虚构演示条目{article}；真实项目须另查有权使用的正式规范。"
               for article in allowed_articles)


def ai_reading_note(question: str, matches: list[dict], context: dict | None = None) -> str | None:
    if not matches or not model_ready():
        return None
    evidence = [{"article": item["article"], "topic": item["topic"],
                 "check": item["check"]}
                for item in matches[:3]]
    messages = [
        {"role": "system", "content": (
            "只从候选卡片选择一个与问题最相关的条号。输出必须严格符合唯一格式："
            "请核对虚构演示条目X；真实项目须另查有权使用的正式规范。"
            "其中X必须是候选卡片的D编号。不要输出其他文字、数值、结论或解释。"
        )},
        {"role": "user", "content": json.dumps({"问题": question, "项目条件": context or {},
                                               "候选卡片": evidence}, ensure_ascii=False)},
    ]
    payload = {"model": os.environ["LLM_MODEL"], "messages": messages,
               "temperature": 0, "max_tokens": 300}
    api_request = request.Request(
        os.environ["LLM_API_URL"],
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
        method="POST",
    )
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        with request.build_opener(NoRedirect).open(api_request, timeout=20) as response:
            data = json.load(response)
        note = data["choices"][0]["message"]["content"]
        if not isinstance(note, str):
            return None
        note = note.strip()
        if not _safe_ai_note(note, matches):
            return None
        return note
    except (error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError) as exc:
        print(f"Model request failed: {type(exc).__name__}")
        return None


class Handler(BaseHTTPRequestHandler):
    def _trusted_host(self) -> bool:
        return self.headers.get("Host", "") in {
            f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._trusted_host():
            self._json(403, {"error": "仅允许本机访问"})
            return
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(200, {"ok": True, "model_ready": model_ready(),
                             "local_token": LOCAL_TOKEN,
                             "model_provider": urlparse(os.environ.get("LLM_API_URL", "")).hostname if model_ready() else None,
                             "corpus_count": len(CORPUS["clauses"]),
                             "corpus_scope": CORPUS["scope"]})
            return
        if path == "/api/quality":
            self._json(200, quality_snapshot(CORPUS))
            return
        filename = "index.html" if path == "/" else path.removeprefix("/static/")
        if path != "/" and not path.startswith("/static/"):
            self.send_error(404)
            return
        target = (STATIC / filename).resolve()
        if not target.is_relative_to(STATIC) or not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._trusted_host():
            self._json(403, {"error": "仅允许本机访问"})
            return
        if urlparse(self.path).path != "/api/search":
            self.send_error(404)
            return
        origin = self.headers.get("Origin")
        if (origin and origin != f"http://{self.headers['Host']}") or self.headers.get("X-Local-Token") != LOCAL_TOKEN:
            self._json(403, {"error": "本机请求校验失败"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._json(415, {"error": "仅接受 JSON 请求"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 4096:
                self._json(400, {"error": "请求内容过长或为空"})
                return
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("invalid body")
            question = body.get("question", "")
            city = body.get("city", "")
            building_use = body.get("building_use", "")
            project_kind = body.get("project_kind", "")
            design_stage = body.get("design_stage", "")
            use_model = body.get("use_model", False)
            if not isinstance(use_model, bool):
                raise ValueError("invalid use_model")
            if not all(isinstance(value, str) for value in
                       (question, city, building_use, project_kind, design_stage)):
                raise ValueError("invalid field type")
            question = question.strip()
            city = city.strip()
            if not question or len(question) > 300 or len(city) > 60:
                self._json(400, {"error": "请填写300字以内的问题；地区不超过60字"})
                return
            if building_use not in ("", "residential", "non_residential", "other_civil"):
                raise ValueError("invalid building_use")
            if project_kind not in ("", "new", "renovation"):
                raise ValueError("invalid project_kind")
            if design_stage not in ("", "concept", "scheme", "construction"):
                raise ValueError("invalid design_stage")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "请求格式不正确"})
            return
        context = {"city": city, "building_use": building_use,
                   "project_kind": project_kind, "design_stage": design_stage}
        result = retrieve(question, CORPUS, context)
        matches = result["matches"]
        review = assessment(matches, result["coverage_gap"], context,
                            result["search_explanation"], question)
        note = ai_reading_note(question, matches, context) if use_model else None
        self._json(200, {
            "matches": matches,
            "search_explanation": result["search_explanation"],
            "assessment": review,
            "context": context,
            "ai_note": note,
            "model_ready": model_ready(),
            "model_requested": use_model,
            "coverage": CORPUS["scope"],
            "city_note": (f"已记录项目所在地：{city}。当前资料库未收录地方标准，仍需核对当地要求。"
                          if city else "未填写项目所在地；涉及地方要求时需补充城市。"),
            "source_checked_on": CORPUS["source"]["checked_on"],
            "corpus_sha256": corpus_fingerprint(CORPUS),
            "source_fingerprint": source_fingerprint(CORPUS),
            "clause_fingerprints": {key: value for key, value in clause_fingerprints(CORPUS).items()
                                    if key in {f"{item['standard']}#{item['article']}" for item in matches}},
            "source_meta": {
                "type": CORPUS["source"].get("type"),
                "announcement_url": CORPUS["source"]["announcement_url"],
                "version_review": CORPUS["source"]["version_review"],
                "content_rights": CORPUS["source"]["content_rights"],
                "published": CORPUS["source"]["published"],
                "effective": CORPUS["source"]["effective"],
            },
        })


if __name__ == "__main__":
    print(f"建筑规范检索助手运行于 http://{HOST}:{PORT}")
    print(f"资料库：{len(CORPUS['clauses'])} 个条号索引；模型已配置：{'是' if model_ready() else '否'}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
