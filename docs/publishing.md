# 公开发布说明

当前公开版为 `v0.2.0-fictional`，只包含原创虚构资料。静态导览：https://ghgg25043-byte.github.io/building-code-assistant/。完整交互需本地运行 `python app.py`。

发布前执行单元测试、开发者回归评测、前端冒烟测试，并运行 `python scripts/package_preview.py` 生成白名单 ZIP；人工检查 ZIP 内无客户资料、密钥、真实规范内容或旧截图。GitHub release 源码归档以对应标签为准。

历史发布入口已撤下，公开主分支已重建。但第三方克隆、分叉及缓存可能继续保有旧资料，仓库维护者无法保证外部副本完全删除。
