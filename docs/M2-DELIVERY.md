# M2 身份与只读服务交付记录

2026-10-04 当前基础收尾见 [M0–M3 收尾](M0-M3-CLOSEOUT.md)。本文件为原阶段历史记录，以下“当前/未完成”和测试数指当时快照。当前 M0.4/M2.5 公开契约及固定 SDK 离线最小集成完成；M0.2 全业务执行仍未完成。最新逐方法报告为 353/353，不能改写历史数字或冒称远程业务通过。

首次记录：2026-10-02；最后更新：2026-10-03。用户本轮明确开始 M2，取代此前“暂不进入 M2”的阶段安排。基线为 `0886ab2`，工作区 `E:\Retail-Agent`，分支 `main`；源码与测试于 2026-10-03 按三批独立提交推送到 `1471436961/Retail-Agent` 的 `main`，本次第四批单独提交交付与共享文档。绑定仍为 `5147314e-f2da-4bac-924a-e2ad95e647e4`、retail_plus、Python、t1、case_ids=null。

## 实施范围与状态

| 项目 | 本轮实现 | 验收边界 |
|---|---|---|
| M2.1 身份 | 邮箱、完整姓名＋邮编两种独立验证；姓名/邮编可分轮收齐；保存用户输入来源、验证轮次和档案，验证后跨用户轮次保留；拒绝中途切客户 | 本地合成对话通过；客户 ID、订单线索或工具输出不能独立授权 |
| M2.2 自有订单 | 验证档案中的 order_ids 先于订单 GET；返回后再次核对 owner 与 order_id；读取全部自有引用后按精确状态筛选 | pending 与 pending (items modified) 分开；错配、未知状态、异常记录及超预算不返回部分结果；不完整描述要求明确 ID |
| M2.3 商品与履约 | 公共目录、产品、item 读取；分别呈现种类、变体、可用变体；保留规格、库存、当前价、原成交价与原履约分组 | 不要求曾购买公共目录商品；没有商品名到 ID 的猜测映射，不新增 quantity/行号；tracking ID 不被解释成发货事件 |
| M2.4 只读轮次 | 显式 ID 与档案/订单列表/目录查询路由；一次请求可先验证再读取；身份失败、其他客户或畸形结果安全回复；日期/ETA 未提供时说明未知 | 默认工厂使用确定性路由；泛化自然语言、复杂偏好比较和模型文字事实性尚未验收，不宣称完整业务案例通过 |
| M2.5 模型薄适配 | JSON history ↔ 真实 tau2 消息；真实 Tool 选择；公开 generate 调用；校验后转内部候选；多调用 ID、完整批次、error、正文与 JSON 状态往返 | 真实 SDK＋fake 网关离线验证通过；课堂镜像一致性、真实网关联调和费用授权未完成，M2.5 不整体勾选 |

本轮只读服务覆盖教学 API 的六个端点：`POST /v1/customers/search`、`GET /v1/customers/{customer_id}`、`GET /v1/orders/{order_id}`、`GET /v1/catalog/products`、`GET /v1/catalog/products/{product_id}`、`GET /v1/catalog/items/{item_id}`。搜索 POST 是只读验证。工具共 8 个：保留 `lookup_customer`，新增 `verify_customer`、`read_customer_profile`、`get_order`、`list_customer_orders`、`list_products`、`get_product`、`get_item`，均按真实 SDK 标注 READ。

评审收尾后，lookup_customer 保留 t1 工具签名，customer_api.verify_and_read_customer 委托 read_api.verify_customer；两条工具入口共用唯一严格验证实现。它不是“不能解锁私有读取”：完整档案匹配且存在真正用户输入时建立同一 identity_evidence，缺少 customer_id 的档案不再被接受。原始查询测试替身同步补齐显式 ID，未放宽验证。当前部署代码为 1 个搜索 POST 字面调用点及 6 个 GET 字面调用点（客户直接读取兼容方法另有一个 GET），与六个不同端点和八个工具的计数分别记录。

## 实现位置与状态控制

- [identity.py](../agent/support_agent/domain/identity.py)：独立验证输入、跨轮字段提取、用户来源与档案一致性。
- [read_api.py](../agent/support_agent/adapters/read_api.py)、[read_tools.py](../agent/support_agent/adapters/read_tools.py)：六端点封装、归属/响应字段校验、真实工具声明。每次新工具实例携带同一组验证输入重新搜索并核对档案，不依赖 Toolkit 内存缓存。
- [read_session.py](../agent/support_agent/read_session.py)：会话范围绑定、只读路由、批次登记/消费与事实回复；[state.py](../agent/support_agent/state.py) 通过同一批次逻辑恢复，历史工具不会再次执行。旧单查询消费实现已移除，避免身份重置与双重恢复口径。
- [model_gateway.py](../agent/support_agent/adapters/model_gateway.py)：真实消息/Tool 转换、运行时模型允许列表、one_of 选择、固定参数省略、用量与异常边界；[application.py](../agent/support_agent/application.py) 可显式注入适配器，默认工厂未启用真实模型。

状态 schema_version 保持 1，并为旧 M1 状态补默认字段。旧状态中只有 `verified=True`、缺少独立输入和档案证据时，不开放私有读取。pending 支持最多 8 个调用，单条结果批次须完整、唯一且 ID 对应，全部验证后才接纳任何事实；失败、缺失、重复、迟到结果不会自动重发工具。新用户消息结束旧 pending，保留已验证身份。

当前执行路径为单助手消息最多 8 个工具调用、单用户请求累计最多 12 个读取调用、单次列表最多 32 个订单；模型仅在确定性路由无法解释请求时尝试一次，工具结果回复由程序生成，迟到结果也不触发模型。MAX_MODEL_CALLS_PER_REQUEST=2 是为未来多步生成保留的内部上限，当前每个用户请求从 0 开始且最多增加到 1，所以累计达到 2 的耗尽分支目前不可达，未声称已验收。新增流程回归验证“当前实际最多 1 次、下一用户请求重新计数、工具结果轮次不调用”，不人为修改马上被重置的计数来制造覆盖。未来启用多步生成时必须通过统一预算入口落实累计耗尽及失败计数的可达测试。

上述数值都是项目控制，不是平台限制。模型计数指适配器调用尝试（含异常），不代表底层 provider HTTP 请求或计费次数；一次工具调用也可包含搜索、档案和多个订单 HTTP 请求。history/operations 的长会话摘要与容量验收仍归 Q2。

## 实际测试结果

最新使用本项目 `.venv\Scripts\python.exe -m unittest discover -s tests -v`，**91/91 通过，零跳过，Python 原生退出码 0**：原有 51 项回归通过；只读 API 15、会话 23、SDK 验收入口 2（一个子进程包装、一个缺失解释器失败回归）。子测试不另计数量。初次 M2 为 82/82，第一轮修复为 87/87，本轮再增加 4 个主测试。

真实 SDK 包装测试在独立进程执行 [sdk_m2_checks.py](../tests/sdk_m2_checks.py) 的 **13/13，零跳过**，已包含在主套件的一个包装测试内，不能相加为 104 项。环境为 Python 3.12.13、tau2 1.0.1、上游固定提交 `6e9f34c685d40fa7a9f5935d8970af6fd9d5f118`；子进程禁用 dotenv、设置离线变量并通过进程审计拒绝网络。真实 SDK 对象用于工厂/工具/消息/Client API，模型网关和 API transport 为 fake；零真实模型调用。此前 10/10 为初次 M2、12/12 为第一轮正文边界修复，本轮增加真实档案工具端到端检查。缺少项目 .venv 解释器、子进程失败或任何子检查跳过都使完整 M2 验收失败，不再 skip；仅运行标准库测试时可用 unittest 的 -p 选择对应领域文件，不能将那种运行宣称为完整 M2 验收。

| 范围 | 实际测试文件与关键方法 | 验证结果 |
|---|---|---|
| 六端点与独立验证 | [test_m2_reads.py](../tests/test_m2_reads.py)：`test_six_read_paths_and_encoded_order_id_are_used_without_writes`、`test_email_and_name_postal_search_precede_profile_details`、`test_partial_mixed_or_boolean_verification_has_zero_requests` | 先验证再读档案；路径编码；缺失/非法验证零请求 |
| 持久身份与恢复 | [test_m2_session.py](../tests/test_m2_session.py)：`test_verified_identity_persists_without_resupplying_email`、`test_name_and_postal_fields_can_be_collected_across_user_turns`、`test_history_restores_identity_and_pending_owned_read_without_reissue` | 跨轮身份、分轮输入与 pending 恢复，不重放 API |
| A121-01/03 的越权原则 | [test_m2_reads.py](../tests/test_m2_reads.py)：`test_roommate_order_is_rejected_before_order_get`、`test_owned_reference_with_wrong_returned_owner_or_id_is_rejected`；[test_m2_session.py](../tests/test_m2_session.py)：`test_cross_customer_switch_and_roommate_order_are_blocked` | 其他客户引用在 GET 前拒绝；owner 再检查；不透露对方记录。A121-02 的完整取消业务尚待写流程，不能据此把案例整体标通过 |
| A126-01/02/03 的身份失败原则 | [test_m2_session.py](../tests/test_m2_session.py)：`test_customer_id_or_order_hint_alone_has_zero_private_calls`、`test_failed_verification_does_not_expose_approximate_accounts` | 订单/扣款线索不替代验证；失败不展示近似账户、不宣称已退款；重复扣款业务调查尚未实现 |
| 精确状态与商品事实 | [test_m2_reads.py](../tests/test_m2_reads.py)：`test_exact_status_filter_keeps_modified_pending_distinct`、`test_catalog_is_public_but_still_requires_verification`；[test_m2_session.py](../tests/test_m2_session.py)：`test_product_counts_and_original_catalog_prices_are_distinct` | 公共目录权限、不同状态/计数/价格来源、未知日期 |
| 畸形结果与完整批次 | [test_m2_reads.py](../tests/test_m2_reads.py)：`test_bad_order_amount_payment_or_fulfillment_is_rejected`；[test_m2_session.py](../tests/test_m2_session.py)：`test_multi_read_results_require_complete_unique_matching_batch`、`test_malformed_history_and_non_object_order_results_fail_closed` | 布尔/字符串金额、错误履约类型、空/重复/错配批次与畸形历史拒绝 |
| 真实 SDK 往返 | [sdk_m2_checks.py](../tests/sdk_m2_checks.py)：`test_model_reply_calls_round_trip_into_json_state_and_real_tool_results`、`test_json_history_restores_real_messages_ids_errors_and_batches`、`test_native_client_and_fresh_toolkits_replay_same_owned_read` | 原 state 不变、新 state 可 JSON 化；真实 Tool/消息、双调用、反序结果、error 与新实例重放 |
| 网关候选与计量 | [sdk_m2_checks.py](../tests/sdk_m2_checks.py)：`test_writes_unknown_tools_foreign_accounts_or_orders_are_rejected`、`test_allowlist_fixed_options_and_one_of_are_checked_before_calls`、`test_empty_bad_output_and_provider_exception_never_create_calls`、`test_usage_missing_is_unknown_not_zero_and_cost_zero_is_only_reported` | 写/未知工具/越权、非法模型参数与异常输出拒绝；usage 缺失不当作 0，reported_cost=0 不证明免费 |
| 唯一严格验证 | [test_m2_reads.py](../tests/test_m2_reads.py)：`test_legacy_lookup_requires_the_same_explicit_profile_identity` | 旧入口同样拒绝无 ID/错误 ID 档案及非法邮箱，接受合法大小写/边缘空白归一输入 |
| 正文与恢复顺序 | [test_m2_session.py](../tests/test_m2_session.py)：`test_rejected_bodies_are_removed_from_live_and_restored_history`、`test_rejected_batch_discards_even_its_valid_result_body`、`test_restoration_cannot_use_future_user_text_as_verification_source` | 错误/归属错配/畸形正文以及失败批次中的合法部分均不留存；后来的 user 输入不能补早期验证。修复前这组新增回归捕获 5 个失败分支 |
| 旧状态的模型输入 | [sdk_m2_checks.py](../tests/sdk_m2_checks.py)：`test_rejected_legacy_history_is_not_replayed_as_model_facts`、`test_direct_message_conversion_removes_error_body_but_keeps_id` | fake 网关捕获真实 SDK 消息，证明旧错误及归属错配原文未发出；保留调用 ID/error，原 state 不变；异常 UserMessage 输出仍拒绝 |
| SDK 必须执行 | [test_m2_sdk.py](../tests/test_m2_sdk.py)：`test_missing_sdk_interpreter_is_failure_not_skip` | 缺少解释器触发失败；包装要求非零子检查数、零跳过与零网络尝试成功标记 |
| 档案读取完整路径 | [test_m2_session.py](../tests/test_m2_session.py)：`test_profile_query_reads_formats_and_refreshes_only_verified_customer`、`test_profile_result_mismatch_preserves_identity_without_disclosing_body`；[sdk_m2_checks.py](../tests/sdk_m2_checks.py)：`test_real_agent_profile_tool_reads_and_formats_the_verified_customer` | 两种验证来源、用户查询→档案工具→搜索/读取→格式化→缓存刷新；错配不泄露、不替换原身份依据；真实 SDK Agent/工具/消息与 JSON 状态往返 |
| 重复目录 ID | [test_m2_reads.py](../tests/test_m2_reads.py)：`test_duplicate_product_and_variant_ids_are_rejected_at_read_boundary` | 目录与产品读取遇到重复 product/item ID 都拒绝；验证先于读取，防止计数和候选受重复数据影响 |
| 当前模型调用行为 | [test_m2_session.py](../tests/test_m2_session.py)：`test_current_model_flow_calls_once_per_request_and_never_on_tool_results` | 不靠预置计数：正常请求产生一次候选读取，工具返回与迟到结果零追加模型调用；下一请求重新计数。原不重放测试将 API 计数快照移到 initial_state 之前 |

以上是合成离线阶段证据；随后分批推送取得的 t1 接入报告另列于下，未运行正式业务评测；522 个业务 AT 的原始范围不变，未将原则级测试计为完整案例成功。

初次 M2 曾检查 8 份文档/115 个本地链接/24 个测试方法引用，部署包 21 个文件、69,892 字节；这是评审前历史数据。本轮修改后另复核链接、实际方法、语法与部署容量，最新检查结果见本节末尾，不沿用旧字节数。当时部署包隔离回归保持通过，暂存区为空。

第一轮修复曾检查 9 份文档、125 个本地链接、本表 31 个方法引用、87 个主测试及 12 个 SDK 子检查；部署包为 21 文件、70,673 字节。这些是前轮历史数据，最新检查另记录。

2026-10-02 评审收尾检查通过：9 份文档、129 个本地链接、本表 36 个实际测试方法引用；91 个主测试及 13 个 SDK 子检查的源码计数一致；20 份 Python 源码语法解析通过。部署包为 21 个文件、70,824 字节，未超过限制；git diff --check 通过，暂存区为空。

## 2026-10-03 分批提交与远程接入证据

| 提交与范围 | 独立提交快照 | 同一 SHA 的远程结果 |
|---|---|---|
| `9634556a52d0bddb32005e2d9d3dc3296392121d`：严格身份验证、六端点只读工具与读取回归（8 文件） | 66/66，零跳过、退出码 0 | [Actions 37091070485](https://github.com/1471436961/Retail-Agent/actions/runs/37091070485)；[Job f45a17e3](https://agentist.org/lab/enterprise-ai?run=f45a17e3-ccd5-48bb-bd95-e3c8afdc2149)：t1 1/1 通过，失败 0、错误 0 |
| `758164e8052e60f5c3d75fa0c039efced16eee4c`：会话身份持久化、安全历史恢复与会话回归（6 文件） | 89/89，零跳过、退出码 0 | [Actions 37091195502](https://github.com/1471436961/Retail-Agent/actions/runs/37091195502)；[Job 1679dc08](https://agentist.org/lab/enterprise-ai?run=1679dc08-416b-4fb6-a92f-744ac41f0cf2)：t1 1/1 通过，失败 0、错误 0 |
| `33f9012e66aacab8664be9c730b51e0ade3d911a`：模型适配边界与真实 SDK 离线验收（3 文件） | 91/91，零跳过、退出码 0 | [Actions 37091320270](https://github.com/1471436961/Retail-Agent/actions/runs/37091320270)；[Job 4799d3d4](https://agentist.org/lab/enterprise-ai?run=4799d3d4-cb02-47ae-b800-ff8b7cc7db80)：t1 1/1 通过，失败 0、错误 0 |
| 本次第四批：9 份实施、交付与共享文档 | 仅文档链接、行号与暂存安全检查；沿用上一批 91/91 源码验收 | 不含 agent/ 或工作流变更，不触发自动 t1 |

各批验证均对暂存树导出的独立源码快照运行，不借用尚未提交的后续源码。第三批真实 SDK 包装测试实际执行，内部 13 项、零跳过、fake 模型网关、零网络尝试；不与主套件 91 项相加。

三个报告均核对 commit_sha、GitHub run_id 与绑定任务 t1；只覆盖 public-customer-lookup 接入检查，不能作为 M2 自有订单、目录、历史恢复或模型业务效果的远程覆盖证明。默认工厂仍未启用模型，M2.5 不整体勾选；522 个业务 AT 范围保持原样。

本次沿用已有 Git 凭证和临时进程代理，未安装 gh、读取权限文件或 .env、修改全局 Git 配置。每次暂存只含对应批次文件，凭证、原始 ZIP、平台 raw 存档及 .venv 均未暂存。

## 评审后的历史与摘要边界

正常工具结果先经完整批次与范围校验，再写 history；只有整批成功保留原正文。工具错误、错配、未知/孤立结果和失败批次改为受控 read_result_status；保留 ID 与批次，失败批次统一 error=True，归属错配保留 error=False，恢复仍分别判为 failed/unknown，不误称业务成功。原 provider 文本、被拒绝客户资料和失败批次中的部分事实不保存。

initial_state 按前缀顺序复核历史，同样消除未接纳正文；不允许未来用户输入替历史调用补验证。模型适配器在出站前重新恢复/核验历史，防止旧 JSON 状态残留正文进入模型，直接 SDK 消息转换也清除 error 正文。旧 JSON state 原对象不被修改；本轮没有后台批量迁移或清理已经持久化的外部状态。

Q2 保留为未实现，具体设计见 [身份依据保留设计](STATE-EVIDENCE-RETENTION.md)：保护真正用户原文、完整验证链、pending/确认/去重证据与原始轮次；先缩减模型投影，若需裁剪 state 则须版本迁移和验收，不能用助手摘要替身份授权。计划模块树已对齐 read_api/read_tools/read_session；共享会话接口由同一维护者协调，后续写工具不重复实现验证。

## 保留事项与下一阶段边界

M2.1–M2.4 按上述离线范围完成，M2 整体仍未完成：M2.5 真实网关与课堂镜像联调保留；生产工厂的模型选择/启用须先核对运行时配置并获得费用授权。非法工具候选受到程序校验，但合法自由文本不能仅靠提示词证明事实性，模型自然语言路径另需真实联调验收。

M0.2 全量实际测试追踪、M0.4 平台集成、Q2 长会话摘要，以及 M3 起的提案/确认/写入均未提前完成；本轮未进入 M3。资料仍在 `E:\enterprise-ai-materials\retail_plus`，权限文件仍在仓库外；没有读取权限文件/.env、修改绑定或评测范围。2026-10-03 三批源码与测试已分别提交推送，只等待每次推送产生的同一 GitHub 任务，没有另行 evaluate、改变绑定或扩大范围。当前三个 M2 t1 结果见上表；历史 M1 报告见 [M1 交付记录](M1-DELIVERY.md)，两者都只作为接入证据。
