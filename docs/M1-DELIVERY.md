# M1 本地交付记录

首次记录：2026-10-01；最后更新：2026-10-02。仓库 `E:\Retail-Agent`，分支 `main`；绑定为 `5147314e-f2da-4bac-924a-e2ad95e647e4`、`retail_plus`、Python、t1。本记录涵盖当前查询的协议、状态与离线测试底座；规则、案例与接口基线见 [M0 交付记录](M0-DELIVERY.md)。

2026-10-02 文档同步：[平台契约记录](PLATFORM-CONTRACT-NOTES.md)已明确 generate、消息/工具、用量、目录、数量和金额基线。接口澄清本身不证明真实 SDK 或模型路径已验证；本轮分批提交及 t1 证据另列于下，不扩大 M1 完成范围。

## 完成范围

| 任务 | 当前产物与验收范围 |
|---|---|
| M1.1 | 保留工厂与工具入口；内部协议、状态和轮次决策不依赖 tau2 |
| M1.2 | JSON 状态隔离、结构校验、单 pending 查询、共享结果消费逻辑；平台/内部查询历史可恢复，无 I/O 或重发 |
| M1.3 | 两个合成客户与订单、状态化 fake API、脚本式候选提供器及原有 6 项回归 |
| M1.4 | 响应错误分类、未知工具与非法参数拒绝、单消息调用上限、离线候选尝试上限；真实模型与多步工具预算待接入 |
| M1.5 | 新工具实例和后端重放当前只读查询；干净目录导入及上传源码范围/JSON 载荷体积检查 |

本轮另补 U6 金额纯函数兼容基线，作为公开算法的提前验证：仅计算已解析价格对的估算差价、舍入已计算余额，没有接入工具或业务工作流；不提前勾选 M3/M5，不推断订单实例匹配或其他账务公式。

M1 已勾选范围只限当前查询和离线协议底座；首次业务写入的验收尚未实施。M2 可基于已有内部候选协议继续设计模型适配与业务 schema；M0.4 仅约束真实网关绑定，不阻塞离线开发。替身测试通过不能证明真实模型兼容。

## 变更文件

| 分组 | 文件 |
|---|---|
| 入口与轮次 | `agent/agent.py`、`agent/support_agent/application.py`、`agent/support_agent/protocol.py`、`agent/support_agent/turns.py`、`agent/support_agent/state.py` |
| 规则与传输 | `agent/support_agent/domain/customer.py`、`agent/support_agent/domain/money.py`、`agent/support_agent/adapters/client_api.py`、`agent/support_agent/adapters/customer_api.py` |
| 离线测试 | `tests/fakes.py`、`tests/test_m1_client_api.py`、`tests/test_m1_state.py`、`tests/test_m1_adapter.py`、`tests/test_money.py` |
| 共享规划与问题状态 | `docs/IMPLEMENTATION-PLAN.md`、`docs/OPEN-ITEMS.md` |
| 工程与阶段交付 | `PROJECT.md`、`docs/M1-DELIVERY.md` |

共享规划与问题状态同时服务 M0，不代表两阶段分别修改或重复提交这些文件。

## 验证证据

- 2026-10-01 使用本地 Python 3.12 执行完整回归 `python -m unittest discover -s tests -v`：**37/37 通过**。该总数包含 M0 和 M1 测试；原有 6 个回归测试保留。
- 正常结果消费与恢复共用同一函数；测试覆盖合法、重复、缺失、错误、身份不匹配和无关结果，以及扁平历史中的重复回执。
- 内部完整查询历史可以重建 pending 与完成状态；畸形状态在入口抛 `InvalidState`，无效历史调用不创建 pending 槽。
- 两客户交错会话返回各自邮箱、客户 ID 与订单引用；客户 ID 与独立邮箱不匹配时没有加载对方详情。
- 公共请求适配器显式指定 201 时可处理转接受理响应；未知写结果不自动重试的规则通过 fake 后端验证。
- 打包测试涵盖上传器接受的源码扩展名、目录排除、单文件限制及序列化 JSON 载荷大小，并从仓库外干净目录导入核心代码。

本地适配测试使用 tau2 替身，不能独立证明真实教学 SDK 或模型网关兼容。本轮三批 M1 源码已分别提交、推送并取得对应 SHA 的 t1 报告；证明当前接入查询可运行，不证明模型网关、业务写入或全部案例通过。历史报告继续保留，不替代本轮结果。

### 2026-10-02 分批提交与远程接入验证

用户明确授权区分 M0/M1，M1 分多次提交和推送。目标 `1471436961/retail-agent` / `main`，绑定 `5147314e-f2da-4bac-924a-e2ad95e647e4`，retail_plus / Python / t1 / case_ids=null，范围未改动。

| 阶段/提交 | 独立快照测试 | 对应推送的终端结果 |
|---|---|---|
| M0 `40f6ae0`：4 份平台证据、退款边界和规划文档 | 15/15；875 个文档链接/行号检查通过 | 不含 agent/ 或工作流变更，不触发自动 t1 |
| M1 `4e5728f`：公共传输、未知写结果分类与回归 | 24/24 | [Actions 36975489858](https://github.com/1471436961/Retail-Agent/actions/runs/36975489858)；[Job 9aa0b674](https://agentist.org/lab/enterprise-ai?run=9aa0b674-de06-4ee3-be06-cef74ce0dd8f)：t1 1/1 通过，失败 0、错误 0 |
| M1 `62eb206`：协议、JSON 状态/历史恢复、轮次入口与回归 | 43/43 | [Actions 36975637348](https://github.com/1471436961/Retail-Agent/actions/runs/36975637348)；[Job 48bb0f2b](https://agentist.org/lab/enterprise-ai?run=48bb0f2b-ad64-4bf0-a55e-13dc727911e2)：t1 1/1 通过，失败 0、错误 0 |
| M1 `ba53f46`：U6 纯函数与 8 项金额兼容测试 | 51/51 | [Actions 36975790435](https://github.com/1471436961/Retail-Agent/actions/runs/36975790435)；[Job 47391bf0](https://agentist.org/lab/enterprise-ai?run=47391bf0-67d1-49e4-8bbe-f43255c0d1a0)：t1 1/1 通过，失败 0、错误 0 |
| M1 本提交：PROJECT、两份阶段记录、测试映射及共享状态文档同步 | 沿用 ba53f46 的 51 项源码快照验收；本提交只改文档 | 不含 agent/ 或工作流变更，不另行提交 evaluate |

每个源码批次独立推送，等待同一 SHA、main、push 事件、hyper-lab.yml 的终端结果后才继续。报告 artifact 的 commit_sha 与 github.run_id 均核对一致；三个工作流结论均为 success，案例 public-customer-lookup 的 identity_verified_before_details 为 true。三次均运行同一个接入案例，不能累计为三个不同业务案例通过；最后的 ba53f46 报告对应当前完整源码。

未找到可用 gh，使用已有 Git 推送和 GitHub API 查询；下载报告只在内存中使用已有 Git Credential Manager 授权，不读取 Enterprise-AI.json 或 .env，不保存或输出 Git 凭证，不安装工具或改全局配置。权限文件、业务 ZIP、平台 raw 存档及 .venv 未暂存。当前 Agent 没有模型调用，本轮仅运行模板说明的免费 t1，未进入 M2、未实施退款合计算法或运行 p1/t2。

## 未解决问题与下一阶段入口条件

### 2026-10-02 收尾验证

完整离线回归 **51/51 通过**：此前 43 项保留，本轮新增 8 项金额兼容测试，覆盖公开半程值、最终舍入、顺序敏感、原始精度/退款方向、空估算、余额舍入及非法数值/溢出拒绝。原有 6 项回归未改动。规则到真实测试函数、验证边界、最终评审和已推送/待提交清单见 [基础测试映射与收尾记录](FOUNDATION-TEST-MAP.md)。

最终评审修复了公共请求适配器接受缺失/非整数写响应状态的问题：写回执必须有严格整数状态码，否则标记结果未知且不重试；读取保留旧替身错误传播并拒绝非整数成功状态。随后已安装官方 hyper-tau-bench 固定提交 6e9f34c685d4 的 tau2 1.0.1 到项目 .venv，真实 SDK 最小工厂/工具注册/查询/恢复/响应异常验证通过，安装时新环境回归为 43/43，当前完整套件为 51/51。上述最初离线收尾未推送或运行远程任务；之后本轮已获授权分批推送并取得三份 t1 报告。Q3/M0.4 保留课堂版本一致性及完整模型转换/网关联调边界，M2 未启动。

1. M2.1 首先实现 Q1：保持本会话验证身份，记录来源并拒绝跨客户切换。
2. 首次多步工作流按 Q4 设置实际累计预算，不能以单消息 8 个调用上限代替跨工具轮次预算。
3. 首个写工具同时交付零越权写、确认状态绑定、工具重放及未知结果至多一次写四类测试。
4. M4 转接调用显式设置 `expected_status=201, mutates=True`，并核实受理后结束工具流。
5. 长会话摘要按 Q2 保留未决请求、确认与操作证据；不得为减少容量而静默丢失授权信息。
6. 工厂/轮次、generate 和 Client API 响应属性已有契约；上游真实 SDK 的查询/消息恢复及响应异常最小验证通过。Q3/M2.5 明确登记 JSON state → 真实 tau2 消息/Tool → fake 网关 → 内部结果 → JSON state 的离线往返验收，保留多调用 ID、批次和错误标志；完整转换尚未实现。JSON-only 是项目工程约束。U4 公共目录、U5 首个 ID 匹配与 U6 float/round 已明确，具体能力限制见 [M0 交付记录](M0-DELIVERY.md)。

以上身份、摘要、多步预算、确认与转接调用均为项目开发任务；不能因尚未实现而归为外部接口未知。内部模型接口与 fake 可在 M2 实现，真实模型调用仍需完成联调和费用授权。

共享接口维护范围为 `application.py`、`turns.py`、`state.py`、`protocol.py`，新增业务工具时一并制定接口。提交推送、模型费用及远程任务范围继续遵守用户的明确授权。
