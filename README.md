# Retail Agent

参考 Sierra Research tau2 的工具调用模式，为 Agentist 的 Python／`retail_plus` 平台接口实现。平台契约、OpenAPI 和课程材料优先；不假设课堂环境与开源 tau2 完全相同。

生产目录已恢复首次下载的 `agent/support_agent/` 模块路径，`agent.py`／`tools.py` 保持薄入口，原始客户查询工具和状态字段继续兼容。首次下载的 39 个原始文件另完整保存在 [原始平台模板](reference/platform-starter/)，供逐项比较。详见 [平台兼容说明](docs/PLATFORM-COMPATIBILITY.md)。

```text
用户原话／工具结果
        ↓
平台模型网关（完整对话 + 零售政策 + 工具定义）
        ↓
普通回复，或原生工具调用
        ↓
平台执行 tools.py → support_agent 适配器 → Client API
        ↓
工具结果回到模型，继续决定下一步
```

## 实现

- [agent/agent.py](agent/agent.py)：零参数 `create_agent()` 工厂，在此获取平台上下文并返回 `CustomerAgent`。
- [agent/tools.py](agent/tools.py)：`Tools(CustomerTools)`，作为平台工具发现入口。
- [agent/support_agent/application.py](agent/support_agent/application.py)：平台模型调用与历史管理。用户原话直接进入模型，没有固定句式、意图正则、候选 JSON 或业务路由器。
- [agent/support_agent/adapters/customer_tools.py](agent/support_agent/adapters/customer_tools.py)：18 个模型工具，包含原始 `lookup_customer(customer_id, email="")`，以及身份搜索、查询、偏好排序、地址／支付／商品修改、取消、退换货、转人工与计算。
- [agent/support_agent/domain/preferences.py](agent/support_agent/domain/preferences.py)：只读 `rank_preferred` 执行器。模型从用户说明中提取硬约束和有序排序规则；工具按传入规则筛选、比较，不添加默认的价格或商品 ID 优先级。同分候选保持并列。
- [agent/support_agent/state.py](agent/support_agent/state.py)：保留 `turn`／`pending_call_id`／`customer_id`，增加 JSON 消息历史；完整保存多工具调用与结果的 ID。
- [agent/policy.md](agent/policy.md)：业务政策与对话要求。描述理解、跨轮信息、完整清单、条件与确认由模型负责；端点资格和数据库更新由平台后端执行。
- [agent/agent.json](agent/agent.json)：Python／retail_plus 部署声明。
- [agent/THIRD-PARTY-NOTICES.txt](agent/THIRD-PARTY-NOTICES.txt)：开源参考及 MIT 许可。

工具使用 SDK `@is_tool` 原生 schema，没有 `session_json`、内部提案版本或客户要遵守的特殊命令。原 `domain/customer.py` 辅助函数为兼容原文件保留，当前对话入口不调用其中的正则或固定回复。平台网关错误保留异常，工具调用没有自动重试。

## 本地验证

Windows PowerShell，使用已有 SDK 环境：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

测试拒绝网络访问。使用真实 SDK 的 `ModelGateway`、候选模型代理序列化、`ClientAPI`、`Environment` 及上游 `RetailTools`，数据由测试独立构造，模型底层响应为脚本替身。它们检查接线和工具行为，不证明实际模型理解质量、正式案例通过或零费用。

当前排序工具与验证见 [偏好排序](docs/PREFERENCE-RANKING.md)，原接口修复见 [平台兼容修复](docs/PLATFORM-COMPATIBILITY.md)，重建历史见 [docs/RESTART.md](docs/RESTART.md)。旧 1163 方法／522 条合成断言不是这次重建的通过证据。

## 远程评测

保留现有 `.github/workflows/hyper-lab.yml`、`hyper-lab.yml` 和官方 `scripts/` 接入客户端。push 的任务与范围由网站已保存绑定决定，不能从 `lab_eval.py` 的默认 task 推断。提交前核对网站范围和费用授权。

```powershell
.\.venv\Scripts\python.exe scripts/git-evaluate.py push --set-upstream origin main
```

这条命令会实际推送并可能触发收费评测，只在用户明确授权后运行。权限 JSON、原始 ZIP、`.venv/` 和恢复快照均不进入部署包。Agent 使用平台注入的默认模型，模型路由及密钥由平台管理。

## 开源参考

依据官方 [tau2 LLMAgent](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/agent/llm_agent.py)、[零售工具](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/domains/retail/tools.py)和[零售政策](https://github.com/sierra-research/tau2-bench/blob/main/data/tau2/domains/retail/policy.md)重新设计，并用本项目 [OpenAPI](materials/client_api/openapi.yaml)适配课堂 REST 字段。上游当前公开任务数量不用于推断本平台 134 案例的范围或镜像版本。
