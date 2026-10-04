# M0 教学接口与运行时契约基线

2026-10-04 当前默认库存八 READ＋三个内部地址/支付/取消 WRITE，模型仍限 READ；schema 8。地址、整单支付切换和单一取消接入真实 user → 完整复述/确认 → 写前刷新 → 契约端点/强读回。其余默认生产器尚未开放，转接待 M4.4。支付先扣后退是政策要求；交易数组顺序不证明处理时序，单个 PUT 也不提供未声明的原子/回滚保证。取消保留逐 charge 原金额/原去向，历史 refund 受控审查，不净额或重复退款。当前有限离线范围见 [M4.3 取消交付](M4.3-DELIVERY.md)，支付语义边界见 [M4.2 交付](M4.2-DELIVERY.md)。共用工具预算 256 KiB/1 MiB 是项目 UTF-8 预算，写后交付失败保留 Unknown，不改变教学 REST 契约。

核对日期：2026-10-02。规范来源：[教学 OpenAPI](../materials/client_api/openapi.yaml)、[课堂覆盖说明](../materials/CLASSROOM.md)、[工具契约](../materials/framework/client_api_contract.md)、[Agent 契约](../materials/framework/agent_contract.md)、[部署 manifest](../materials/framework/deployment_manifest.json)，以及 [平台契约核查记录](PLATFORM-CONTRACT-NOTES.md)中的当前资料 path/version。本表记录 **当前可见契约**，不是声称真实部署所有响应变体均已测试。

## 14 个 HTTP 操作

`R` 表示不更改状态、契约允许自动重试；`W` 表示更改状态、不保证幂等、自动重试被禁止。`POST /v1/customers/search` 属于 R。路径标识符均需 URL 编码，含 `#` 的订单号必须编码为 `%23`。

| 类别 | 方法与路径 | 请求正文必需字段 | 200/201 响应的关键字段 | 主要对应规则 |
|---|---|---|---|---|
| R | `POST /v1/customers/search` | 邮箱，或姓名＋邮编完整组合；schema 不设统一 `required` | `customer_id` | ID-01 |
| R | `GET /v1/customers/{customer_id}` | — | `customer_id`、`name`、`email`、默认地址、支付方式、订单引用 | ID-01/02 |
| W | `PUT /v1/customers/{customer_id}/default-shipping-address` | 地址行 1、城市、区域、国家、邮编 | `customer_id`、`default_shipping_address` | AD-01 |
| R | `GET /v1/catalog/products` | — | `products[]` | IT-01、EX-01、U4 |
| R | `GET /v1/catalog/products/{product_id}` | — | `product_id`、`name`、`items[]` | IT-01、EX-01 |
| R | `GET /v1/catalog/items/{item_id}` | — | `item_id`、`options`、`available`、`price` 等 schema 字段 | IT-01、EX-01 |
| R | `GET /v1/orders/{order_id}` | — | `order_id`、`customer_id`、状态、商品、支付、履约 | ID-02、ST-01/02/03/04 |
| W | `PUT /v1/orders/{order_id}/shipping-address` | 同一完整地址结构 | `order_id`、`shipping_address` | AD-01 |
| W | `PUT /v1/orders/{order_id}/payment-method` | `payment_method_id` | `order_id`、`payments[]` | PY-01/02 |
| W | `POST /v1/orders/{order_id}/cancellations` | `reason` | `order_id`、`status=cancelled`、`cancellation`、支付明细 | CA-01/02、RF-01 |
| W | `POST /v1/orders/{order_id}/item-modifications` | `replacements[]`、`payment_method_id` | `status=pending (items modified)`、商品及支付明细 | IT-01/02、ST-02 |
| W | `POST /v1/orders/{order_id}/returns` | `item_ids[]`、`refund_payment_method_id` | `status=return requested`、`return_request` | RT-01/02 |
| W | `POST /v1/orders/{order_id}/exchanges` | `replacements[]`、`payment_method_id` | `status=exchange requested`、`exchange` | EX-01 |
| W | `POST /v1/conversations/{conversation_id}/transfers` | `summary` | **201**，`status=accepted`、`transfer_id` | HO-01 |

`replacements` 的条目是 `existing_item_id` 和 `replacement_item_id`；教学接口没有额外 line ID。地址结构必需字段为 `address_line_1`、`city`、`region`、`country`、`postal_code`，`address_line_2` 可按 schema 为字符串或 null。不要添加姓名、备注或 undocumented query 参数。一个操作可以由多个面向 Agent 的工具组合，但工具不得开放任意路径/方法透传。

所有 14 个操作声明强一致性、无分页、请求上限 1,048,576 字节、响应上限 4,194,304 字节。失败可能返回 400、404、405、409、413、422、502，错误形状为 `{"error":{"code":...,"message":...,"details":...}}`；以状态和 `code` 分类，不能仅按 message 文案判断。`400` 为请求结构，`404` 未找到，`409` 状态冲突，`422` 业务限制，`413` 请求超限，`502` 响应超限。`PUT` 也属于禁止自动重试的 W。写请求超时、5xx 或 2xx 正文无法验证时，最终业务状态仍可能不明确；可用同会话后续读取核实，但没有额外幂等 key 或轮询端点。

## 历史记录与教学接口的边界

原件：[系统导出](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/system_export.zip)、[Care Record 导出](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/api_contract.zip)。历史合同对业务规则和存储精度有参考价值；**请求字段和实际响应由教学 OpenAPI 决定**。

| 历史证据字段/形式 | 教学 API 字段/形式 | 适配处理 |
|---|---|---|
| `user_id` | `customer_id` | 只在读证据时解释对应关系；HTTP 请求用教学字段 |
| `payment_history` | `payments` | 区分 `transaction_type=payment/refund` 与每笔金额/方式 |
| `orders`、按 ID 索引的支付方式/规格 | `order_ids`、`payment_methods[]` / `items[]` | 只解释历史形状；请求按具体 operation schema，不做全局字段替换 |
| 历史地址字段 | `default_shipping_address` 或 `shipping_address` | 明确客户档案地址与订单地址的目标记录 |
| 历史扁平退换字段 | `return_request` / `exchange` 等教学响应结构 | 不把历史字段直接传给教学端点 |
| 历史分精度存储语义 | 教学金额正常为 JSON number | 数字字符串未有可复现部署证据；可做严格防御兼容并记异常，不能默认 0；当前 float/round 算法见 U6 |
| 历史 `shipped` guard | 教学订单的 `status` / `fulfillments` | 不凭空创建 shipped 字段；事实冲突时不执行订单写操作 |

## Agent 与模型网关

已核实：`agent.py` 工厂返回实现 `get_init_state(message_history=None)`、`generate_next_message(message,state)` 的实例；工厂时可使用 `get_agent_context()`；上下文公布 `action_interface`、`resources`、`model_gateway`、`runtime_config`。生成的助手消息文本与工具调用互斥。工具实例在新后端重放时，行为必须由其参数、后端和此前记录调用决定。工具转人工时的 `conversation_id` 来自可信 `self.client_api.context`。

面向 Agent 的工具名称、参数、说明和返回结构由本项目通过工具声明设计；内部候选动作、提示词和确认流程也由本项目实现。平台发现工具并驱动轮次，不会替 Agent 补齐模型调用和业务逻辑。网关载荷是否采用工具 schema、如何封装消息，由适配器根据支持的接口转换，不等于业务 schema 必须等待平台提供。

已在 M1 入口保留 context，但 t1 仍不调用模型。当前公开 Python 签名为 `generate(*, model: str, messages: list, actions=None, tool_choice=None, call_name=None, **kwargs)`。messages 为 tau2 消息对象列表，actions 为 Tool 对象序列；工具来自 action_interface.available 或 select(["工具名"])，正常返回 AssistantMessage。TypeScript 对照已取得，使用 tools 函数 schemas，不能混用为 Python actions。适配层恢复 SDK 消息、保留多个工具调用与 ID/批次关系；内部候选不是网关响应格式。JSON-only state 是本项目工程约束，平台定义为不透明对象。

usage 可为空；prompt_tokens 与 completion_tokens 都存在才相加，total_tokens 不保证存在。cost 为 0 不证明免费，credit_usage 依赖 rate card。上游固定 SDK 的消息、查询恢复和 Client API 异常 response 已本地验证；M2 追加真实 SDK＋fake 网关的 JSON/消息/Tool 往返与失败输出测试，当前 SDK 的 usage 为可选 dict，适配器同时兼容属性读取。课堂镜像一致性与真实网关联调仍待完成；tool_choice 的完整合法值、call_name 语义与 provider 具体异常尚未完整验证，适配器省略这些可选参数。详见 [U1 核查依据](PLATFORM-CONTRACT-NOTES.md)、[SDK 安装记录](M0-SDK-CHECK.md)及 [M2 交付记录](M2-DELIVERY.md)。

运行时 available_models 是实际允许列表；manifest 的 enterprise-haiku/max_tokens=1024 是配置快照，可用于合成测试，后续配置可能不同。固定参数应省略，由网关注入，不得自行覆盖或改小；one_of 每次必须明确选合法值。0.32 credits 不是允许列表、美元额度或费用授权，课堂未注入上游 credit rate card。联调核对实际配置与回执，收费调用仍需授权。

当前教学 U4 允许验证后查询与当前请求相关的公共目录，不限历史订单商品，仍禁止跨客户账户访问和未提供的新下单操作。U5 重复次数表达数量，修改逐次替换首个 ID 匹配项，差价也按 ID 匹配；无 quantity/行级选择器，同 ID 不同价格或属性无法精确指定。U6 差价按请求顺序 float 累加后 round(total, 2)，余额更新也 round；不以逐行舍入或未经验证的 Decimal ROUND_HALF_UP 替代，保留原始精度与顺序，以回执核实。

## 开发门槛与待决项

评审更新：2026-10-02。统一状态见 [待决事项寄存器](OPEN-ITEMS.md)，M0 证据见 [M0 交付记录](M0-DELIVERY.md)。既有三个 M0 提交已推送；本批更新平台契约和本地 SDK 证据。文中 M1 实现与验证仍是本地工作区进展，随 M1 另行提交。

- **M1 可做**：标准库纯决策、JSON 状态、fake API/gateway、调用 ID、错误分类、只读 t1 回归和重放测试。
- **M2 可做**：身份持久化、自有订单和相关商品查询；自定内部 model adapter 与结构化候选，使用 fake 覆盖非法输出与失败。真实网关绑定在联调时完成，不阻塞这些开发。
- **业务基线可做**：U3 正常字段与异常兼容策略、U4 当前请求相关公共目录、U5 数量/ID 匹配、U6 状态与已公开金额算法、U7 起点方式快照。M5 实施退货资格，M6 做组合回归。
- **具体边界保留**：U5 同 ID 不同价格/属性无法精确指定，U6 未知/矛盾状态及异常回执，U7 无法证明历史资格的并发新增；U1 可选参数/异常细节和 Q3 真实 SDK 验证。目录计数、常规同 ID 换不同目标和已公开半分算法不再整体列为未知。
- **M4 转接适配器**：公共 `request_object()` 已支持 `expected_status`，转接调用必须显式传 `expected_status=201, mutates=True`；默认 200 留给普通端点。显式 201 已有本地回归测试，但生产转接工具尚未接入。
- **多步工作流/写工具**：M2 已实现多 pending 完整批次及累计读取预算；模型当前每请求最多一次，常量 2 为未来多步保留，耗尽分支尚不可达。t1 共用严格验证，未接纳正文不能进入模型。未来累计模型预算通过统一入口验收；确认门控、未知写结果与重放随首个写工具验收，见 [M2 交付记录](M2-DELIVERY.md)。
- **真实模型/远程评测前**：完成 Python 网关与真实 SDK 联调，检查已发布允许模型及约束，确认实际调用配置和费用授权，并按用户明确授权的任务与案例范围运行。

本表没有修改网站绑定或评测范围，也不代表任何新的业务端点已接入 Agent。

## 2026-10-04 M4.3 取消默认流程

默认工具库存现为八 READ＋三个内部 WRITE（address_workflow/payment_workflow/cancellation_workflow）。取消工具继承真实 ClientAPIToolKitBase，唯一参数 session_json 受共用 UTF-8 预算约束；模型候选、绑定和投影仍只允许 READ，内部工具形状校验本身不证明宿主来源。

取消默认生产器先核实独立身份、自有订单、精确 pending、原因与 payment 明细，完整复述并绑定真实 user 确认，刷新后仅 POST `/v1/orders/{order_id}/cancellations`，body 恰好 reason。没有金额、退款去向、独立退款、job 或补偿接口。原因归一化使用 cancellation_reason_rule，不把价格、物流或品牌投诉擅自映射。受理回执须匹配 order_id/status/cancellation/payments，自有强读回须核实 cancelled、原因、原交易前缀和每笔原 charge 全额原路 refund 的次数；同方式重复 charge 不折叠。没有约定退款数组先后顺序，按多重集核对新增 refund；这不证明后端内部事务或处理器到账。

S06 当前 CR8 取消流程图与 S11 email_06 支持逐笔原路及取消/退款同一事务的业务要求。只发送一个契约端点并核对可见结果，不能由 fake 或数组推断课堂内部原子性。固定上游全历史循环与 RF-01 的差异仍受控：已有 refund 历史自动阻断并解释审查风险，不净额化、删除历史、重试或独立补退。取消总额仅将原 charge JSON 十进制表示精确求和显示，不舍入、不给后台传合计；与退货预计额和已公开差价/余额算法分别处理。
