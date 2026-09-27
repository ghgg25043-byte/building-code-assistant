import json
import os
import threading
import unittest
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request
from unittest.mock import patch

from app import CORPUS, Handler, _safe_ai_note, ai_reading_note, assessment, model_endpoint_is_safe
from search_engine import retrieve, search


class SearchTests(unittest.TestCase):
    def test_representative_questions_find_expected_article_first(self):
        examples = {
            "办公楼公共走廊的净宽要求在哪里查": "D-11",
            "主入口室外台阶踏步宽高": "D-08",
            "屋顶设备用房是否计入建筑高度": "D-04",
            "楼梯休息平台宽度怎么定": "D-10",
            "机动车出入口靠近学校": "D-06",
            "屋面坡度排水要求": "D-13",
        }
        for question, article in examples.items():
            with self.subTest(question=question):
                self.assertEqual(search(question, CORPUS)[0]["article"], article)

    def test_uncovered_questions_do_not_get_invented_clauses(self):
        self.assertEqual(search("消防疏散距离是多少", CORPUS), [])
        self.assertEqual(search("物业费多少钱", CORPUS), [])

    def test_every_result_points_to_original_demo_source(self):
        articles = {entry["article"] for entry in CORPUS["clauses"]}
        for result in search("办公楼走廊宽度", CORPUS):
            self.assertIn(result["article"], articles)
            self.assertTrue(result["source_url"].endswith("/data/demo-source.md"))

    def test_residential_query_does_not_return_non_residential_width_clause(self):
        result = retrieve("住宅公共走廊净宽要求", CORPUS, {"building_use": "residential"})
        self.assertNotIn("D-11", [item["article"] for item in result["matches"]])
        self.assertTrue(result["coverage_gap"])

    def test_width_query_does_not_return_height_clause(self):
        articles = [item["article"] for item in retrieve("办公楼公共走道净宽", CORPUS)["matches"]]
        self.assertIn("D-11", articles)
        self.assertNotIn("D-05", articles)
        roof = [item["article"] for item in retrieve("屋面坡度排水要求", CORPUS)["matches"]]
        self.assertIn("D-13", roof)
        self.assertNotIn("D-03", roof)

    def test_conflicting_context_requires_clarification(self):
        result = retrieve("住宅公共走廊净宽", CORPUS, {"building_use": "non_residential"})
        self.assertEqual(result["matches"], [])
        self.assertIn("冲突", result["coverage_gap"])
        office = retrieve("办公楼公共走廊净宽", CORPUS, {"building_use": "residential"})
        self.assertEqual(office["matches"], [])
        self.assertIn("冲突", office["coverage_gap"])

    def test_mixed_covered_and_uncovered_question_returns_only_covered_candidates(self):
        result = retrieve("办公楼公共走廊净宽和消防疏散距离分别怎么查", CORPUS)
        self.assertEqual(result["matches"][0]["article"], "D-11")
        self.assertEqual(result["search_explanation"]["uncovered_topics"], ["真实消防与安全疏散规范要求"])
        self.assertIn("未被虚构演示资料覆盖", result["coverage_gap"])
        self.assertEqual(assessment(result["matches"], result["coverage_gap"],
                                    {"city": "", "building_use": "", "project_kind": "",
                                     "design_stage": ""}, result["search_explanation"])["state"], "partial")

    def test_unsupported_stair_question_is_not_recast_as_generic_stair(self):
        result = retrieve("防火楼梯宽度怎么定", CORPUS)
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["search_explanation"]["uncovered_topics"], ["真实消防与安全疏散规范要求"])

    def test_search_explanation_distinguishes_applied_and_recorded_only_fields(self):
        context = {"city": "上海市", "building_use": "non_residential",
                   "project_kind": "new", "design_stage": "scheme"}
        result = retrieve("公共走廊净宽", CORPUS, context)
        explanation = result["search_explanation"]
        self.assertTrue(any("建筑用途" in line for line in explanation["applied_filters"]))
        self.assertTrue(any("宽度" in line for line in explanation["applied_filters"]))
        self.assertEqual(len(explanation["recorded_only_filters"]), 3)
        self.assertTrue(all("仅记录" in line for line in explanation["recorded_only_filters"]))
        self.assertEqual(explanation["uncovered_topics"], [])
        self.assertIn("关键词命中", result["matches"][0]["match_reason"])
        self.assertEqual(result["matches"][0]["evidence_status"], "fictional_demo")

    def test_explicit_evidence_status_is_passed_through(self):
        corpus = deepcopy(CORPUS)
        target = next(item for item in corpus["clauses"] if item["article"] == "D-11")
        target["evidence_status"] = "expert_reviewed"
        result = retrieve("办公楼公共走廊净宽", corpus)
        self.assertEqual(result["matches"][0]["evidence_status"], "expert_reviewed")

    def test_direct_article_reason_is_not_an_applicability_claim(self):
        result = retrieve("请找第D-11条", CORPUS)
        match = result["matches"][0]
        self.assertEqual(match["article"], "D-11")
        self.assertIn("直接提及", match["match_reason"])
        self.assertIn("仅用于演示定位", match["match_reason"])
        self.assertEqual(search("请找第D-111条", CORPUS), [])


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def search_request(self, payload, headers=None):
        with request.urlopen(self.base + "/api/health", timeout=3) as response:
            token = json.load(response)["local_token"]
        return request.Request(self.base + "/api/search", data=json.dumps(payload).encode(),
                               headers={"Content-Type": "application/json", "X-Local-Token": token,
                                        **(headers or {})}, method="POST")

    def test_search_endpoint_returns_source_backed_result(self):
        req = self.search_request({"question": "办公楼公共走廊净宽", "city": "上海市"})
        with request.urlopen(req, timeout=3) as response:
            data = json.load(response)
        self.assertEqual(data["matches"][0]["article"], "D-11")
        self.assertIn("地方标准", data["city_note"])
        self.assertEqual(data["assessment"]["state"], "candidate_only")
        self.assertIn("虚构", data["source_meta"]["version_review"])
        self.assertIn("新建或改造", data["assessment"]["missing_context"])
        self.assertEqual(len(data["search_explanation"]["recorded_only_filters"]), 1)
        self.assertIn("上海市", data["search_explanation"]["recorded_only_filters"][0])
        self.assertEqual(data["matches"][0]["evidence_status"], "fictional_demo")
        self.assertIn("DEMO-ARCH-001#D-11", data["clause_fingerprints"])
        self.assertTrue(data["source_fingerprint"])
        self.assertTrue(any("疏散" in item["question"] for item in
                            data["assessment"]["clarifications"]))

    def test_search_endpoint_returns_partial_state_for_mixed_question(self):
        req = self.search_request({"question": "办公楼公共走廊净宽和消防疏散距离怎么查"})
        with request.urlopen(req, timeout=3) as response:
            data = json.load(response)
        self.assertEqual(data["assessment"]["state"], "partial")
        self.assertEqual(data["matches"][0]["article"], "D-11")
        self.assertEqual(data["search_explanation"]["uncovered_topics"], ["真实消防与安全疏散规范要求"])

    def test_empty_question_is_rejected(self):
        req = self.search_request({"question": "", "city": ""})
        with self.assertRaises(error.HTTPError) as context:
            request.urlopen(req, timeout=3)
        self.assertEqual(context.exception.code, 400)

    def test_invalid_project_context_is_rejected(self):
        req = self.search_request({"question": "走廊净宽", "building_use": "industrial"})
        with self.assertRaises(error.HTTPError) as context:
            request.urlopen(req, timeout=3)
        self.assertEqual(context.exception.code, 400)

    def test_cross_origin_missing_token_and_wrong_media_type_are_rejected(self):
        base = {"question": "公共走廊净宽"}
        cases = [
            (request.Request(self.base + "/api/search", data=json.dumps(base).encode(),
                             headers={"Content-Type": "application/json"}, method="POST"), 403),
            (self.search_request(base, {"Origin": "https://untrusted.example"}), 403),
            (self.search_request(base, {"Content-Type": "text/plain"}), 415),
        ]
        for req, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(error.HTTPError) as context:
                request.urlopen(req, timeout=3)
            self.assertEqual(context.exception.code, expected)

    def test_untrusted_host_cannot_read_session_token(self):
        req = request.Request(self.base + "/api/health", headers={"Host": "untrusted.example"})
        with self.assertRaises(error.HTTPError) as context:
            request.urlopen(req, timeout=3)
        self.assertEqual(context.exception.code, 403)

    def test_model_is_not_called_without_explicit_request(self):
        with patch("app.ai_reading_note") as model:
            req = self.search_request({"question": "公共走廊净宽"})
            with request.urlopen(req, timeout=3) as response:
                data = json.load(response)
        model.assert_not_called()
        self.assertIsNone(data["ai_note"])

    def test_explicit_model_request_calls_adapter(self):
        with patch("app.ai_reading_note", return_value="请核对虚构演示条目D-11；真实项目须另查有权使用的正式规范。") as model:
            req = self.search_request({"question": "公共走廊净宽", "use_model": True})
            with request.urlopen(req, timeout=3) as response:
                data = json.load(response)
        model.assert_called_once()
        self.assertIn("虚构演示条目D-11", data["ai_note"])


class ModelAdapterTests(unittest.TestCase):
    def test_model_endpoint_rejects_cleartext_remote_and_credentials(self):
        for endpoint, expected in [
            ("http://models.example/v1/chat/completions", False),
            ("https://user:password@models.example/v1/chat/completions", False),
            ("https://models.example/v1/chat/completions", True),
            ("http://127.0.0.1:1234/v1/chat/completions", True),
            ("https://[broken/v1/chat/completions", False),
        ]:
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {"LLM_API_URL": endpoint}):
                self.assertEqual(model_endpoint_is_safe(), expected)

    def test_model_note_rejects_new_figures_verdicts_and_unprovided_references(self):
        matches = search("公共走廊净宽", CORPUS)
        self.assertTrue(_safe_ai_note("请核对虚构演示条目D-11；真实项目须另查有权使用的正式规范。", matches))
        self.assertFalse(_safe_ai_note("请核对第D-11条已经废止。", matches))
        self.assertFalse(_safe_ai_note("请核对第D-11条可以直接用于施工图。", matches))
        self.assertFalse(_safe_ai_note("请核对第D-11条，走廊须宽1.30米。", matches))
        self.assertFalse(_safe_ai_note("请核对第D-11条，走廊须宽一米。", matches))
        self.assertFalse(_safe_ai_note("请核对第D-11条，走廊须宽两米。", matches))
        self.assertFalse(_safe_ai_note("请核对第D-11条，坡度为百分之二。", matches))
        self.assertFalse(_safe_ai_note("请核对第D-11条，该设计符合规范。", matches))
        self.assertFalse(_safe_ai_note("请核对第D-11条和第D-99条。", matches))
        self.assertFalse(_safe_ai_note("请核对《建筑设计防火规范》第D-11条。", matches))
        self.assertFalse(_safe_ai_note("这个项目可以采用。", matches))

    def test_configured_model_receives_only_question_and_retrieved_summaries(self):
        class FakeModel(BaseHTTPRequestHandler):
            seen = None

            def do_POST(self):
                FakeModel.seen = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                body = json.dumps({"choices": [{"message": {"content": "请核对虚构演示条目D-11；真实项目须另查有权使用的正式规范。"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {
                "LLM_API_URL": f"http://127.0.0.1:{server.server_port}/chat/completions",
                "LLM_API_KEY": "test-only-key",
                "LLM_MODEL": "mock-model",
            }):
                matches = search("公共走廊净宽", CORPUS)
                note = ai_reading_note("公共走廊净宽", matches)
            self.assertEqual(note, "请核对虚构演示条目D-11；真实项目须另查有权使用的正式规范。")
            self.assertIn("D-11", FakeModel.seen["messages"][1]["content"])
            self.assertNotIn("source_url", FakeModel.seen["messages"][1]["content"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
