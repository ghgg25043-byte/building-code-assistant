# 架构

项目有两条演示路径。GitHub Pages 首页读取构建时由 `scripts/build_pages_demo.py` 从 `data/clauses.json` 投影的 `docs/demo-data.json`；`docs/live-demo.js` 在浏览器内完成虚构条目检索、覆盖缺口提示和结果呈现。它不调用后端、不保存输入，也不调用模型。Pages 的前端逻辑由 `tests/pages_demo.js` 验证，CI 检查投影资料与源文件同步。

完整本地工作流由浏览器向本地 Python HTTP 服务提交问题及项目条件。`search_engine.py` 在原创虚构条目上检索并返回候选、匹配原因和覆盖缺口；`app.py` 生成核对清单。浏览器在本机 `localStorage` 中保存工作簿，可导出 Markdown。`quality.py` 检查语料结构和评测快照。

模型适配器默认关闭，只有单次主动勾选才发送问题、条件和最多 3 个虚构候选主题。适配器要求 HTTPS 或本机 HTTP，并只接受固定格式的 D 编号提示。它不生成真实规范依据或合规结论。

首次读取旧工作簿时，前端撤下旧版生成的候选索引，保留用户输入的问题和个人备注。这个本地迁移无法清除浏览器导出的旧文件或第三方副本。
