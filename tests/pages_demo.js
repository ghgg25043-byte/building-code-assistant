"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {retrieve} = require("../docs/live-demo.js");

const root = path.resolve(__dirname, "..");
const corpus = JSON.parse(fs.readFileSync(path.join(root, "docs/demo-data.json"), "utf8"));
const cases = JSON.parse(fs.readFileSync(path.join(root, "data/eval_cases.json"), "utf8")).cases;

assert.equal(corpus.source.type, "fictional_demo");
assert.equal(corpus.clauses.length, 14);
for (const item of cases) {
  const result = retrieve(item.question, corpus, item.context || {});
  const articles = result.matches.map((match) => match.article);
  for (const expected of item.expected_articles) {
    assert.ok(articles.includes(expected), `${item.question}: missing ${expected}`);
  }
  for (const forbidden of item.forbidden_articles || []) {
    assert.ok(!articles.includes(forbidden), `${item.question}: unexpected ${forbidden}`);
  }
  if (item.expect_no_evidence) assert.equal(result.state, "no_evidence", item.question);
}

const partial = retrieve("办公楼公共走廊净宽和消防疏散距离有哪些要求？", corpus);
assert.equal(partial.state, "partial");
assert.equal(partial.matches[0].article, "D-11");
assert.ok(partial.uncovered.length);
assert.equal(retrieve("请找D-111", corpus).matches.length, 0);
assert.throws(() => retrieve("走廊", {...corpus, source: {...corpus.source, type: "real"}}), /仅允许虚构/);

console.log("GitHub Pages fictional demo checks passed");
