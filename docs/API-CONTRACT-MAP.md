# M0 教学接口与运行时契约基线

核对日期：2026-09-30。规范来源：[教学 OpenAPI](../materials/client_api/openapi.yaml)、[课堂覆盖说明](../materials/CLASSROOM.md)、[工具契约](../materials/framework/client_api_contract.md)、[Agent 契约](../materials/framework/agent_contract.md)、[部署 manifest](../materials/framework/deployment_manifest.json)。本表记录 **当前可见契约**，不是声称真实部署所有响应变体均已测试。

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
| 历史地址字段 | `default_shipping_address` 或 `shipping_address` | 明确客户档案地址与订单地址的目标记录 |
| 历史扁平退换字段 | `return_request` / `exchange` 等教学响应结构 | 不把历史字段直接传给教学端点 |
| 金额按分存储的语义 | 教学 JSON number 及曾观察到的礼品卡余额数字字符串 | 读侧只兼容已见变体；写侧严格遵循 OpenAPI；未定义半分 tie-break 不自行制定 |
| 历史 `shipped` guard | 教学订单的 `status` / `fulfillments` | 不凭空创建 shipped 字段；事实冲突时不执行订单写操作 |

## Agent 与模型网关

已核实：`agent.py` 工厂返回实现 `get_init_state(message_history=None)`、`generate_next_message(message,state)` 的实例；工厂时可使用 `get_agent_context()`；上下文公布 `action_interface`、`resources`、`model_gateway`、`runtime_config`。生成的助手消息文本与工具调用互斥。工具实例在新后端重放时，行为必须由其参数、后端和此前记录调用决定。工具转人工时的 `conversation_id` 来自可信 `self.client_api.context`。

面向 Agent 的工具名称、参数、说明和返回结构由本项目通过工具声明设计；内部候选动作、提示词和确认流程也由本项目实现。平台发现工具并驱动轮次，不会替 Agent 补齐模型调用和业务逻辑。网关载荷是否采用工具 schema、如何封装消息，由适配器根据支持的接口转换，不等于业务 schema 必须等待平台提供。

已在 M1 入口保留工厂取得的 context，但 t1 当前路径仍是确定性查询，不调用模型。尚需联调的是 Python 网关调用入口的方法名和签名，以及结果、计量与异常的转换；本地材料不足以断言存在 `generate()` 或其他特定方法。内部 model adapter 与 fake 可先设计实现，平台差异限制在薄适配层。官方 TypeScript 示例若可取得，可以参考载荷语义与流程，再核对 Python 调用方式；本地目前没有该示例，取得它不是离线开发前提。公开上游 tau2 接口也不能替代教学注入接口的证据。

manifest 的 `allowed_agent_models` 已明确 `openai/enterprise-haiku` 及固定 `max_tokens=1024`，可据此设计与测试；`performance_requirements` 的 0.32 credits 段不是模型允许列表，也不是用户费用授权。课堂说明指出当前试点不采用上游额度预算评分。固定限制按契约可省略并由网关补充，`one_of` 限制必须明确选一项。联调时检查服务与清单是否一致；签名检查不等于执行模型调用，实际模型调用仍需费用授权。

## 开发门槛与待决项

评审更新：2026-10-01。统一状态见 [待决事项寄存器](OPEN-ITEMS.md)，M0 证据见 [M0 交付记录](M0-DELIVERY.md)。本批提交仅涵盖 M0；文中 M1 适配实现与验证是本地工作区进展，其源码、测试和 `M1-DELIVERY.md` 随 M1 另行提交。

- **M1 可做**：标准库纯决策、JSON 状态、fake API/gateway、调用 ID、错误分类、只读 t1 回归和重放测试。
- **M2 可做**：身份持久化、自有订单和相关商品查询；自定内部 model adapter 与结构化候选，使用 fake 覆盖非法输出与失败。真实网关绑定在联调时完成，不阻塞这些开发。
- **业务基线可做**：U3 的教学字段/读变体、U4 的客户订单相关商品权限、U5 的重复次数、U6 的状态与分精度计算、U7 的申请起点支付方式快照，均有材料依据。M5 实施退货资格，M6 做组合回归。
- **窄边界保留**：U4 中实际超出已知权限的需求、U5 中相同旧 item ID 的不同副本换成不同目标的后端匹配、U6 中履约事实矛盾或确需半分算法、U7 中无法证明申请前资格的外部并发新增。仅在相应分支缺乏证据时停止该动作，不关闭整个业务类别。
- **M4 转接适配器**：公共 `request_object()` 已支持 `expected_status`，转接调用必须显式传 `expected_status=201, mutates=True`；默认 200 留给普通端点。显式 201 已有本地回归测试，但生产转接工具尚未接入。
- **首次多步工作流/写工具**：接入实际跨工具轮次预算及确认门控；当前仅有单 pending 查询与离线候选重试，不能用单条消息的调用数上限代替多步预算。
- **真实模型/远程评测前**：完成 Python 网关与真实 SDK 联调，检查已发布允许模型及约束，确认实际调用配置和费用授权，并按用户明确授权的任务与案例范围运行。

本表没有修改网站绑定或评测范围，也不代表任何新的业务端点已接入 Agent。
