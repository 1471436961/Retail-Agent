# Retail Agent

基于 Sierra Research tau2 零售 agent 的工具调用模式，为 Agentist 的 Python／`retail_plus` 接口实现。2026-10-26 按用户要求重新开始，旧规则工作流与验收体系已退出当前项目。

```text
用户原话／工具结果
        ↓
平台模型网关（完整对话 + 零售政策 + 工具定义）
        ↓
普通回复，或一次原生工具调用
        ↓
平台执行 tools.py → Client API → 真实业务后端
        ↓
工具结果回到模型，继续决定下一步
```

## 实现

- [agent/agent.py](agent/agent.py)：模型调用与消息历史。模型由平台运行时提供；没有固定句式、意图正则、候选 JSON、业务路由器或自建状态机。
- [agent/tools.py](agent/tools.py)：16 个模型可调用工具。身份搜索、档案／订单／目录查询、地址／支付／商品修改、取消、退换货、转人工及计算。
- [agent/policy.md](agent/policy.md)：业务政策与对话要求。描述理解、跨轮信息、完整清单、条件与确认由模型负责；端点资格和数据库更新由平台后端执行。
- [agent/agent.json](agent/agent.json)：Python／retail_plus 部署声明。
- [agent/THIRD-PARTY-NOTICES.txt](agent/THIRD-PARTY-NOTICES.txt)：开源参考及 MIT 许可。

工具使用 SDK `@is_tool` 原生 schema，没有 `session_json`、内部提案版本或客户要遵守的特殊命令。用户原话直接进入模型；平台网关错误保留异常，不伪装成业务结论。工具调用没有自动重试。

## 本地验证

Windows PowerShell，使用已有 SDK 环境：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

测试拒绝网络访问。使用真实 SDK 的 `ModelGateway`、候选模型代理序列化、`ClientAPI`、`Environment` 及上游 `RetailTools`，数据由测试独立构造，模型底层响应为脚本替身。它们检查接线和工具行为，不证明实际模型理解质量、正式案例通过或零费用。

当前结果与设计见 [docs/RESTART.md](docs/RESTART.md)。旧 1163 方法／522 条合成断言不是这次重建的通过证据。

## 远程评测

保留现有 `.github/workflows/hyper-lab.yml`、`hyper-lab.yml` 和官方 `scripts/` 接入客户端。push 的任务与范围由网站已保存绑定决定，不能从 `lab_eval.py` 的默认 task 推断。提交前核对网站范围和费用授权。

```powershell
.\.venv\Scripts\python.exe scripts/git-evaluate.py push --set-upstream origin main
```

这条命令会实际推送并可能触发收费评测，只在用户明确授权后运行。权限 JSON、原始 ZIP、`.venv/` 和恢复快照均不进入部署包。Agent 使用平台注入的默认模型，模型路由及密钥由平台管理。

## 开源参考

依据官方 [tau2 LLMAgent](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/agent/llm_agent.py)、[零售工具](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/domains/retail/tools.py)和[零售政策](https://github.com/sierra-research/tau2-bench/blob/main/data/tau2/domains/retail/policy.md)重新设计，并用本项目 [OpenAPI](materials/client_api/openapi.yaml)适配课堂 REST 字段。上游当前公开任务数量不用于推断本平台 134 案例的范围或镜像版本。
