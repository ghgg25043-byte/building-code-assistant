# 公开发布说明

当前主分支只包含原创虚构资料。GitHub Pages 首页 https://ghgg25043-byte.github.io/building-code-assistant/ 提供浏览器内检索、部分覆盖与无资料三种交互状态；完整的人工核对工作簿需本地运行 `python app.py`。`v0.2.0-fictional` 标签对应首个虚构资料版本，不包含之后新增的在线交互。

发布前执行单元测试、开发者回归评测、前端冒烟测试、`python scripts/build_pages_demo.py --check`、`node tests/pages_demo.js` 和文档链接检查。运行 `python scripts/package_preview.py --out <新文件路径>` 生成白名单 ZIP，人工检查 ZIP 内无客户资料、密钥、真实规范内容或旧截图。GitHub release 源码归档以对应标签为准。

历史发布入口已撤下，公开主分支已重建。但第三方克隆、分叉及缓存可能继续保有旧资料，仓库维护者无法保证外部副本完全删除。
