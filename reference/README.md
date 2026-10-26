# 原始平台接入包

`platform-starter/` 完整保留首次安装提交 `c37119d` 的 39 个文件，未经内容改写；来自本仓 Git 历史。它包含原始 agent.py／tools.py、support_agent 示例 package、原始测试、README、PROJECT、平台契约、OpenAPI、材料及当时的接入脚本。初次导出存在 Windows 换行转换；现已按 Git 原始对象字节恢复，逐文件 SHA-256 核对 39/39 相同。

这是原始模板的可查阅基线，不是当前部署目录。当前代码仍由项目根 `agent/` 加载，原 `support_agent/` 模块路径、入口、查询工具和状态字段已在生产目录恢复；原始模板的 t1 固定示例不重新接管业务对话。目录中的旧 binding YAML 不会作为根目录 GitHub 工作流运行，也不替换当前绑定。

当前适配依据及检查见 [平台兼容说明](../docs/PLATFORM-COMPATIBILITY.md)。原始文件不应再随业务重构删除；如果需要更新平台接入版本，应保留来源并逐项比较。
