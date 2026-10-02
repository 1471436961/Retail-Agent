# M0.4 本地 SDK 安装与接口核查

日期：2026-10-02。项目 `E:\Retail-Agent`，Python 3.12.13；此记录属于平台接入基线，不标记 M0.4 全部完成，不进入 M2，也不改变 retail_plus/Python/t1 绑定。

## 安装来源与环境

- 来源：[Sierra 官方 hyper-tau-bench](https://github.com/sierra-research/hyper-tau-bench)，固定提交 `6e9f34c685d40fa7a9f5935d8970af6fd9d5f118`。
- 包版本：tau2 1.0.1，包含 `tau2.hyper.agent_context`、`tau2.hyper.client_api` 和 `tau2.data_model.message`；不能用普通 tau2-bench 分支替代这些扩展。
- 安装位置：`E:\Retail-Agent\.venv`；解释器 `.venv\Scripts\python.exe`。未安装到全局 Python，未修改全局 Git 配置或 PowerShell 执行策略。
- 直接 Git 安装因上游资料文件名含 `?`，在 Windows 检出失败。改为从已验证提交导出 src 子树，加同一提交的原始 pyproject.toml、README.md、LICENSE，构建安装；框架源码未修改，未读取上游业务资料或答案正文。
- src ZIP SHA-256：`938f3a8bdcf843dde97dd2a9202ab17bf8c02005a504cb09ab75802b8cc36b20`。
- 按上游约束将 openai 限定为不高于 2.20.0，实际安装 2.20.0；78 个包的 `uv pip check` 全部兼容。

源码导出、缓存、依赖快照 `installed-packages.txt` 和不含凭证的来源记录 `local-sdk-install.json` 均位于被 Git 忽略的 `.venv/`；不提交该目录或 SDK ZIP。权限文件和原始业务材料继续保存在仓库外。

## 已验证的基础接口

在未注入 tau2 替身的独立进程中检查：

1. 实际导入 AssistantMessage、ToolCall、ToolMessage、MultiToolMessage、UserMessage、ToolType、is_tool、ClientAPIToolKitBase 和上下文接口。
2. ModelGateway.generate 的真实签名为 `generate(self, *, model, messages, actions=None, tool_choice=None, call_name=None, **kwargs)`；未调用该方法或 provider。
3. ClientAPI.request 接受 method/path 及 query/body/headers；ClientAPIResponse 有 status_code/body/headers/elapsed_seconds。
4. SDK 的 ClientAPIResponse.raise_for_status() 错误携带 `response` 对象。

还在包含本地待提交 M1 的工作区验证了真实 SDK 工厂/context、工具 schema 注册、合成查询往返和真实平台消息历史恢复：2 次本地 ClientAPI 查询、零模型调用和零网络尝试。该验证依赖本地 M1 实现，**不是本批 M0 提交中的业务代码验收**。同理，完整工作区 43/43 回归包含待提交的 M1 测试，不能当作本批独立测试数量。

检查进程设置 `PYTHON_DOTENV_DISABLED=1`、`LITELLM_LOCAL_MODEL_COST_MAP=True`、`LITELLM_TELEMETRY=False`、`HF_HUB_OFFLINE=1`，并用进程审计拒绝网络连接；未读取权限文件或 .env。真实上下文要求至少一个模型配置，合成验证只使用未调用的名称，不代表模型授权。

## 未完成的联调边界

已验证的是上游固定版本，不是课堂镜像版本一致性。完整模型消息/工具转换、可选参数、网关异常和真实调用仍待 M2/联调，真实调用须先核对实际配置与费用授权。没有新的远程成绩，M0.4 仍保持未整体勾选，状态见 [OPEN-ITEMS](OPEN-ITEMS.md)。

此安装只包含框架源码和依赖，没有导出上游业务数据。SDK 默认 data 目录缺失的提示不影响本次接口验证，也不证明本地具备完整评测环境。

在项目根目录直接使用虚拟环境解释器，不需要激活脚本或改变执行策略：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_m0_contract.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_case_trace.py -v
```

M0 契约 6 项与索引 3 项均可独立运行；交付证据与剩余范围见 [M0-DELIVERY](M0-DELIVERY.md)。
