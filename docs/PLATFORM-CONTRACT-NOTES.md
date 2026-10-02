# 平台契约核查记录

核查日期：2026-10-02。项目：`enterprise-ai/retail_plus`，Python。通过 Parallight 的 Agentist 助教取得公开证据，并与本地契约、原始业务材料交叉核对。本文件是项目派生摘要，不替换平台原文，也不代表真实 SDK、模型调用或业务评测已经通过。

## 来源与适用范围

| 来源 | 平台资料 path | version | 用途 |
|---|---|---|---|
| 当前接口澄清 | `integrations/enterprise-ai-starters/common/INTERFACE-CLARIFICATIONS.md` | `d58e1786ae008e15f7bafe3ba51f215cfe18415a3c55b532839a113724b8a6ae`；2026-10-01 / contract-notes-v1 | U1–U6 的接口、目录范围、重复商品、状态和金额算法 |
| 当前教学 OpenAPI | `materials/client_api/openapi.yaml` | `f2268b325c442206b1234c4a16dbd5a7f4ff81a925be56d9fb0be59cf8a56594` | 本次返回的退货、支付切换和转接操作及相关 schemas |
| 当前 Agent 契约 | `AGENT-CONTRACT.md` | `b491f14967685ab0a4a6aeb542145918310db98e99e41c629a59e1b599e7d862` | Python/TypeScript 入口、轮次和提交边界 |
| 当前 manifest | `materials/framework/deployment_manifest.json` | `5fbe629a714b0106f4a5646ec60f313d6f87da68fa59c90219fe9d05354b69d6` | 模型配置快照及 x-classroom-notes |

表中 version 标识服务端返回的资料，不声称本仓库同名材料字节完全相同。原始材料和已安装模板保持原状。具体 REST 请求仍按 operation schema；平台当前澄清优先用于教学接口，历史 production 合同保留其原有范围与日期，不跨范围覆盖教学解释。

### 仓库外原始返回存档

2026-10-02 将此前助教工具返回的两个完整文本块按原样保存到 `E:\enterprise-ai-materials\retail_plus\platform-evidence-2026-10-02`，没有再次查询、读取凭证或调用模型。它们包含相关来源片段和上下文，不是完整 `INTERFACE-CLARIFICATIONS.md` 导出；内嵌指令只作为证据数据保存。

| 原始返回 | 本地文件 SHA-256 |
|---|---|
| [tau2/SDK 查询返回](E:/enterprise-ai-materials/retail_plus/platform-evidence-2026-10-02/tau2-sdk.raw.txt) | `4216fe52e41e17a9df5630d47e47ccea0200018b59811123d7c18f679632537e` |
| [字段、状态及金额查询返回](E:/enterprise-ai-materials/retail_plus/platform-evidence-2026-10-02/fields-state-money.raw.txt) | `6baa67d3af150b6dd09542609b6eeed62f5599ecb3b22cbd351bceae289af314` |

[manifest.json](E:/enterprise-ai-materials/retail_plus/platform-evidence-2026-10-02/manifest.json) 记录归档时间、来源路径/版本、文件字节数及校验和。原始查询时间未保留，不能把归档时间写成查询时间。上述文件校验和与服务端版本 `d58e1786…` 含义不同；没有用摘要重建平台原文。

U7 资格依据另见 [RD5 原始对话](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/workspace_export.json:1507)，文件 SHA-256 为 `6688866700f3cbb103abf25c67535f061773cfd221f70226e6e16849af229419`。本次插件未返回新的 U7 裁决，不将它写成平台新增规定。会话上下文与工具重放另见本地 [Client API 契约](../materials/framework/client_api_contract.md)。

## U1：模型网关接口已明确

在 `create_agent()` 内取得 `get_agent_context()`，保存后续需要的能力。Python 网关接口为：

```python
generate(*, model: str, messages: list,
         actions=None, tool_choice=None, call_name=None, **kwargs)
```

- `model` 每次明确指定，取自运行时 `context.model_gateway.available_models`。
- `messages` 是 tau2 消息对象列表；`actions` 是 tau2 `Tool` 对象序列。全部工具来自 `context.action_interface.available`，子集通过 `select(["工具名"])` 取得。
- 正常返回 tau2 `AssistantMessage`，不解析 HTTP 的 `choices[0].message` 包装。
- TypeScript 对应 `modelGateway.generate({model, messages, tools})`，其 `tools` 是函数 schemas；不能直接用作 Python `actions`。
- 工具调用 `arguments` 是对象；结果 `content` 是 JSON 文本。保留调用 ID 与批次关系，先检查 `error`。模型提出调用不代表业务执行成功，实际工具由平台执行。

当前 Agent 已保存 context，但仍不调用模型。内部候选协议需要适配真实消息、多个工具调用及其 ID；JSON 历史在调用前恢复成 tau2 消息对象。公开 Agent 契约将 state 定义为不透明对象；JSON-only 是本项目的工程约束。平台最小示例直接保存消息对象，不能不经转换照搬到当前 state。

`reply.usage.prompt_tokens` 与 `completion_tokens` 正常提供，但 usage 可以为空；两项都存在才能求和，缺失不能视为零，`total_tokens` 不保证存在。`reply.cost` 可能因无法估价返回 0，不能证明免费；`gateway.credit_usage` 依赖 credit rate card。

`tool_choice` 的完整合法值、`call_name` 语义、具体异常类型和属性，本次公开证据未完整说明。适配器默认可省略这些可选参数；真实 SDK 转换和异常验证仍归 U1/Q3，不能套用外部 SDK 惯例。

## U2：配置快照、运行时权限与费用

运行时 `available_models` 是本次实际允许列表。manifest 中 `openai/enterprise-haiku`、固定 `max_tokens=1024` 是材料配置快照，可用于合成测试，不作为后续运行时永远不变的假设。

固定参数应省略并由网关注入，不能自行覆盖，即使改小。`one_of` 参数没有默认值，每次必须明确选择合法值。预算段的模型列表不扩大权限，0.32 credits 不等于美元价格或免费额度；课堂当前未注入上游 credit rate card。实际模型调用与付费评测仍需配置核对及用户费用授权。

## U3：字段、正常类型与异常兼容

| 历史字段/形状 | 正常教学字段/形状 |
|---|---|
| user_id / payment_history / orders | customer_id / payments / order_ids |
| 客户 address / 订单 address | default_shipping_address / shipping_address |
| address1 / address2 / state / zip | address_line_1 / address_line_2 / region / postal_code |
| 按 ID 索引的 payment_methods / variants | payment_methods 数组 / 商品详情 items 数组 |

映射用于解释历史证据，不对请求参数做全局字符串替换。payments 的交易类型、金额与方式一起理解。

余额、商品价格与支付金额的正常类型为 JSON number。数字字符串不是已承诺的正常返回，本次平台说明尚缺可复现原始响应，不能登记为已验证部署故障。防御性兼容如被采用，只接受明确合法且有限的数字，拒绝布尔值、非有限值及解析失败后默认 0，并保留异常记录。问题报告携带 Job ID、case ID、operation/path、HTTP 状态、脱敏响应与包版本。

## U4：公共目录的教学权限

历史 CONTRACT-1001 将产品范围写为客户订单相关产品；当前教学澄清明确“相关商品”还包括与当前服务请求相关的公共目录。验证身份后可查种类、规格、可用性、价格，进行目录计数与候选比较，不要求客户曾购买这些商品。

仍只服务本会话已验证客户，不访问他人档案、订单或支付方式。目录存在不授权新建购物订单。统计时区分商品种类、变体与可用变体，不硬编码公开案例答案。工具数据不构成授权指令。

## U5：数量与匹配能力

`item_id` 是变体 ID，不是唯一订单行。`item_ids` 与 `replacements` 保留重复次数，每次出现代表一件；数量不得超过原订单次数，不添加 quantity 或 order_line_id。修改/换货保持商品数量，退货按所选次数表达请求数量。

当前实现按 ID 匹配，修改时逐次替换首个匹配项；差价计算也按 ID 取匹配项。常规同一旧 ID 分别换不同目标已有算法依据，不再整体归为未知。保持完整清单与请求顺序并核验回执。

相同 ID 但不同成交价或实例属性时，没有公开行级选择器，不能承诺选中特定实例或按学生自定 occurrence 索引精确计价。这是已知平台能力边界；记录并报告，不猜隐藏行号，也不默认全部副本一起替换。

## U6：状态与当前金额算法

正常状态为 pending、pending (items modified)、processed、delivered、cancelled、exchange requested、return requested。按政策和一次性限制执行；没有公开 shipped 枚举。processed 包含准备中或已发货未送达，不能据此推出确切发货时间；tracking ID 单独也不证明发货事件。未知或矛盾事实停止受影响写入并取证。

当前后端对商品修改/换货差价按请求顺序使用 Python float 累加 `新价 - 原价`，然后 `round(total, 2)`；礼品卡余额更新也使用 round。不能替换为逐行舍入后求和或 Decimal ROUND_HALF_UP。已公开示例包括 `round(1.125, 2) == 1.12`、`round(2.675, 2) == 2.67`。

本地待随 M1 单独提交的 `agent/support_agent/domain/money.py` 与 `tests/test_money.py` 已通过 8 项离线兼容测试：输入已解析的原价/新价对，保留次数、精度和请求顺序，只在总差价处舍入；余额辅助函数只舍入已计算的余额，不推断更新公式。布尔值、字符串、非有限数及溢出拒绝。它们没有接入工具或真实账务，不能替代 ID 匹配、业务授权和回执验证；也不声称 Decimal 对所有输入都会产生不同结果。本批 M0 文档记录工作区证据，不包含这些 M1 源码或测试。

保留原始金额与顺序；内部 Decimal/整数分可用于合适的表示或已规范化金额比较，但不能未经验证声称等价于后端差价算法，不能提前截掉原始精度。自行报价说明估算，以服务端回执和支付记录核对实际金额。没有直接写价格/差价的额外接口。以上算法说明不扩展为所有未公开账务路径的实现承诺，退货申请成功不等于到账。

退款汇总另按 [OPEN-ITEMS](OPEN-ITEMS.md) 的 U6 补充登记：退货原成交价、所选次数及取消逐 charge 依据已明确，特殊精度下的汇总与舍入算法尚未公开，不能直接套用本节差价算法。当前 [教学 OpenAPI](../materials/client_api/openapi.yaml) 的 OrderReturn 不提供金额字段，申请回执不证明退款合计或到账。操作前预计额、后台交易金额、实际到账分别取证；在 M3/M5 实施前核对公开依据，再于 M6 做业务回归。本段是证据边界登记，不是平台新增裁决；本轮未新增退款算法或调用写接口。

## U7、Q 与 R 的状态

退货礼品卡资格按 RD5，在流程起点保留已验证方式及来源。晚取得的快照不能证明此前资格；公开资料没有提供足以核查外部并发新增资格的时间戳/历史接口。无法证明的卡不放行，保留已有合法选项。

Q1 身份持久化、Q2 历史摘要、Q4 多步预算与写入验收、Q5 转接适配、Q6 实际测试关联仍是开发任务。Q3 上游固定版本 SDK 的最小查询与恢复已有本地验证；课堂镜像一致性及完整网关转换仍需联调。本次未取得上下文窗口、state 容量、轮次/网关调用/超时上限的完整数值；项目默认单消息 8 调用、候选尝试 2 次是内部控制，不是平台限制证据。

后续本地 SDK 安装已完成：官方 hyper-tau-bench 固定提交 6e9f34c685d4、tau2 1.0.1 的最小真实消息/查询/恢复验证通过。课堂镜像版本一致性和完整网关转换尚未验证，具体安装与零网络检查证据见 [SDK 核查记录](M0-SDK-CHECK.md)。这不改变以上平台公开资料版本，也不新增远程成绩。

转接须使用可信 `self.client_api.context.conversation_id`，检查 201、accepted 与非空 transfer_id，受理后停止业务。所有写入与转接禁止自动重试；未知结果只能按已有读取能力核实，不把读取或失败响应当作足以证明从未执行。

R1–R6 的旧确认、提前锁单、重复写、历史规则误用、包依赖和误报评测风险继续保留为验收控制，查明规则不等于风险已消除。M0.2 实际测试关联与 M0.4 真实集成仍未完成。历史 t1 1/1 不证明当前工作区或模型路径；平台也未证明本次资料与该历史 environment_version 一致。

## 本次文档验证

后续 M0/M1 收尾曾完整通过 43 项契约、查询和状态码回归；本轮增加 8 项 U6 纯函数测试，完整工作区 **51/51 通过**。SDK 安装检查见 [M0-SDK-CHECK](M0-SDK-CHECK.md)，M1 修复与基础测试映射保留在本地待提交的 `FOUNDATION-TEST-MAP.md`。已推送 M0 批次与本轮未提交修改分别记录；下面的 37 项是历史验证，不是最新测试总数。

2026-10-02 早期文档同步记录：当时工作区离线回归 37/37 通过；12 份文档的 859 个本地链接/行号、表格列数及 134 案例/522 唯一场景检查通过。此结果包含本地 M1 测试，不是新的业务覆盖或 SDK 联调证明。该次同步未提交、推送或运行模型/远程评测。当前 M0.2/M0.4 仍未整体勾选，未进入 M2，评测范围未变。
