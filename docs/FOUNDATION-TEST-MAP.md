# M0/M1 基础规则测试与收尾记录

2026-10-05 当前见 [M5.2 商品修改](M5.2-DELIVERY.md)及[逐方法报告](FOUNDATION-RUN.json)，完整工作区实际 726/726，商品专项 65/65。以下 M0–M5.1 数字及阶段待办属历史快照。A/D/P/C/H/SEL/I 映射为实际合成组件执行，仍不代表 134 案例/522 AT 完整业务执行；M0.2 保留。

日期：2026-10-02。本表保留 M0/M1 收尾时的客户查询、内部候选协议、状态恢复、公共传输层及 U6 算术基线历史记录；下面“当前/本轮/待 M2”均指该历史阶段。随后用户明确开始 M2，最新 M2 源码提交快照 91/91、真实 SDK 包装内 13/13，以及 2026-10-03 三批 t1 接入报告、实现和保留事项见 [M2 交付记录](M2-DELIVERY.md)。历史 51 项不改写为新阶段测试数量；本表不能替代 [CASE-REQUIREMENTS](CASE-REQUIREMENTS.md) 的 522 个业务 AT 场景。

## 本次结果

完整工作区使用 `.venv\Scripts\python.exe -m unittest discover -s tests -v`，**51/51 通过**：索引 3、原有查询回归 6、M0 契约 6、M1 状态 15、M1 传输 9、M1 入口与打包 4、U6 金额兼容 8。此前 43 项保留，本轮新增 8 项纯函数边界测试；子测试分支不另计测试总数。

M0 契约测试只读取仓库内教学 OpenAPI，不依赖 M1 源码。契约断言锁定公开接口形状，不证明后端算法、真实写入或业务授权已经实现。U6 纯函数接受有限 JSON number，锁定顺序 float 差价及已计算余额的 round；它们尚未接入工具或工作流，不证明后端实跑结果。重复 ID 契约测试不证明后端匹配行为；金额函数的输入是调用者已解析的价格对，不选择订单实例。

历史收尾曾将 M0 文件复制到无 agent 源码的临时目录，执行 **9/9** 独立测试，并检查当时 13 份文档的 885 个链接/行号；这些是当时的记录，不作为本轮检查数量。后续已推送 M0 批次的独立快照测试为 **15/15**，见 [M0 交付记录](M0-DELIVERY.md)。本轮完整工作区为 51 项；134 个案例、522 个唯一场景及里程碑边界保持原范围。

本轮检查 7 份修改文档的 71 个本地链接/行号、本表 35 个实际测试方法名及测试总数，均通过；两份仓库外原始返回的字节数和 SHA-256 复核一致，`git diff --check` 通过。测试使用本地合成数据，没有模型或远程评测调用，M0.2/M0.4 和 M2 勾选状态保持原样。

## 规则与测试对应关系

以下方法名均对应实际测试函数；同一方法可以验证多个基础约束，不能因此重复统计覆盖数量。测试文件与方法是本地证据，远程通过数量另行记录。

| 规则/约束 | 测试文件与方法 | 已验证范围 | 尚未覆盖的范围 |
|---|---|---|---|
| ID-01 独立验证先于详情 | [test_customer.py](../tests/test_customer.py)：`test_verification_precedes_details_and_rejects_mismatch`；[test_m1_client_api.py](../tests/test_m1_client_api.py)：`test_lookup_rejects_details_that_do_not_match_search` | 无邮箱时零请求；搜索 ID 不符时不读取对方详情；详情邮箱不符时拒绝结果 | 姓名＋邮编验证、完整多轮身份流程待 M2 |
| ID-02 会话隔离 | [test_m1_adapter.py](../tests/test_m1_adapter.py)：`test_interleaved_customer_sessions_do_not_mix_results`；[test_m1_state.py](../tests/test_m1_state.py)：`test_states_are_independent_and_non_json_values_are_rejected` | 两个客户会话交错执行，状态和返回记录独立 | 已验证身份持久化、会话中切换客户拒绝、自有订单核验待 M2；不把对象隔离当整条规则完成 |
| ID-03 失败不冒充验证成功 | [test_m1_state.py](../tests/test_m1_state.py)：`test_tool_error_does_not_claim_customer_is_missing`、`test_mismatched_or_duplicate_results_never_verify_identity` | 工具错误不宣称客户不存在；错配、重复或缺 ID 的结果不验证身份 | 全部失败分支的对话披露边界和业务零写入待业务测试 |
| EN-01 未知写结果不重试 | [test_m1_client_api.py](../tests/test_m1_client_api.py)：`test_transport_after_write_is_unknown_and_never_retried`、`test_write_502_is_uncertain_but_business_409_is_definite` | fake 写入后超时仍只请求一次；502 写结果未知，409 分类为确定失败 | 生产写工具、未知结果核实和工作流跨轮至多一次写待首个写工具 |
| EN-01 不把异常回执当成功 | [test_m1_client_api.py](../tests/test_m1_client_api.py)：`test_write_without_integer_status_is_unknown_even_with_checker`、`test_noninteger_read_status_is_rejected_not_coerced`、`test_invalid_success_body_is_not_treated_as_record` | 写响应缺整数状态码标未知；bool/string/float 状态不转为成功；非对象正文拒绝 | 回执各业务字段和记录变化校验待对应工具；公共层只校验状态和对象正文 |
| EN-02 新实例重放 | [test_m1_adapter.py](../tests/test_m1_adapter.py)：`test_factory_turns_and_toolkit_replay` | 两个新工具实例在相同合成后端执行相同查询，结果和 API 轨迹一致 | 生产写工具、确认证据重放及复杂轨迹待后续阶段 |
| M1.2 pending 与结果批次 | [test_m1_state.py](../tests/test_m1_state.py)：`test_unrelated_or_missing_tool_result_does_not_consume_as_success`、`test_new_user_turn_never_replays_pending_call`、`test_restoration_uses_the_same_result_batch_rules_as_live_turns` | 无关/缺失/重复/错配结果不成功；新用户消息不重发旧 pending；正常轮次和恢复结果判定一致 | 当前仅单 pending 查询；不证明并行多工具执行或业务写重放 |
| M1.2 JSON 与恢复边界 | [test_m1_state.py](../tests/test_m1_state.py)：`test_internal_history_rebuilds_pending_and_completed_state`、`test_malformed_state_is_rejected_at_the_boundary`、`test_invalid_restored_calls_never_create_pending_slots` | 内部历史恢复 pending/完成状态；畸形状态拒绝；非法恢复调用不建立 pending | 真实 SDK 历史对象、长会话摘要和容量验收仍待 Q2/Q3 |
| M1.4 候选约束与上限 | [test_m1_state.py](../tests/test_m1_state.py)：`test_candidate_gateway_gate_rejects_unknown_tools_and_mixed_messages`、`test_actual_single_message_call_limit_is_enforced`、`test_invalid_candidates_have_a_bounded_safe_fallback` | 未知工具/非法参数/文本和工具混合拒绝；单消息最多 8 调用；离线候选最多尝试 2 次后安全回复 | 真实网关异常与多步累计预算待 M2/Q4；数值是项目控制，不是平台上限 |
| M1.5 部署包隔离 | [test_m1_adapter.py](../tests/test_m1_adapter.py)：`test_clean_agent_package_does_not_need_repo_root_or_materials` | 上传源码扩展名、路径排除、文件/载荷限制及仓库外工作目录导入核心代码 | 使用 PYTHONPATH 指向 agent 的核心导入检查，不证明真实 SDK 或整个远程部署成功 |
| U3/U5 金额与数量契约 | [test_m0_contract.py](../tests/test_m0_contract.py)：`test_money_fields_declare_numbers_not_strings_or_booleans`、`test_item_lists_preserve_duplicates_without_line_or_quantity_fields` | 金额字段声明为 number；请求数组允许重复；ItemReplacement 封闭且没有 quantity/行号字段 | 同 ID 实例限制及真实后端匹配的业务验证待 M5/M6 |
| U6 差价顺序与最终舍入 | [test_money.py](../tests/test_money.py)：`test_published_midpoints_keep_python_float_rounding`、`test_total_is_rounded_once_and_duplicate_pairs_are_preserved`、`test_request_order_is_preserved_at_a_rounding_boundary`、`test_prices_keep_original_precision_and_refund_direction`、`test_empty_and_cancelled_estimates_are_zero` | 公开半程值；不逐行舍入、不去重、不排序；保留原始精度、收费/退款方向；空估算为零 | 已解析价格对的纯函数，不验证 ID 匹配、商品准入、空业务请求合法性或服务端回执；业务集成待 M3/M5/M6 |
| U3/U6 余额舍入与非法金额 | [test_money.py](../tests/test_money.py)：`test_updated_gift_card_balance_uses_published_rounding`、`test_non_json_and_nonfinite_numbers_are_rejected_not_defaulted`、`test_overflow_is_rejected_before_it_can_become_a_quote` | 已计算余额使用 Python round；bool、字符串、Decimal、非有限数及运算溢出拒绝，不默认零 | 不推断余额更新公式或其他未公开账务路径；余额准入与支付核实待业务流程 |
| M0.3 写入输入与转接契约 | [test_m0_contract.py](../tests/test_m0_contract.py)：`test_write_request_fields_are_closed_and_server_computes_amounts`、`test_transfer_receipt_requires_accepted_and_nonempty_id`；[test_m1_client_api.py](../tests/test_m1_client_api.py)：`test_transfer_success_requires_explicit_201` | 8 个写请求封闭字段集，不接受客户端价格/差价；转接声明 201/accepted/非空 ID；公共调用可显式要求 201 | 转接生产调用及回执字段验证、受理后结束工具流待 M4；schema 测试不是业务执行 |
| M0 来源索引稳定 | [test_case_trace.py](../tests/test_case_trace.py)：三个测试方法 | 分类重排结果稳定、未知/重复分类拒绝、材料计数变化拒绝 | 来源结构完整不证明业务场景通过 |

CF-01/02/03 的用户确认、提案版本绑定、改口失效及清单收齐尚未实现。公共适配器的合成写请求用于传输错误测试，不能算作公共写入前提 W 或任一写业务 AT 已覆盖。公共前提 G 目前也只有邮箱查询和状态隔离的部分基础证据。

## M1 最终评审

检查了工厂和平台入口、内部协议、状态与历史恢复、查询身份校验、公共传输层及部署包边界。当前查询底座的可复现问题已修复：存在 `raise_for_status()` 的响应原先可能绕过整数状态校验，导致缺失、字符串或浮点状态被接受，bool 被当成 int 分类。

新增两项回归在修复前出现 7 个失败子测试。修复要求写响应提供严格整数状态码；缺失/非法状态标记 `invalid_response` 且 `outcome_unknown=True`，不重试。读取拒绝非整数成功状态，同时保留旧只读替身的 `raise_for_status()` 异常传播和无状态码兼容；写入不适用该兼容。修复后完整 43 项通过，原有 6 项未改动。

Q1 身份持久化、Q2 摘要、Q4 多步预算、Q5 生产转接和 Q6 业务测试追踪继续按原阶段实施，没有通过缩小定义将它们标记完成。R1–R6 仍是业务验收控制。完整状态见 [OPEN-ITEMS](OPEN-ITEMS.md)。

## 真实教学 SDK 检查

2026-10-02 安装前，在未注入替身的独立 Python 3.12.13 进程调用 `importlib.util.find_spec('tau2')`，结果为 None。实际解释器为 `C:\Users\lenovo\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\python.exe`。已检索仓库 `materials/` 和 `E:\enterprise-ai-materials\retail_plus` 的 SDK/tau2 名称、wheel 和 tar.gz 包，没有找到对应教学 SDK 包。

随后按用户明确要求安装：已从 [Sierra 官方 hyper-tau-bench](https://github.com/sierra-research/hyper-tau-bench) 固定提交 `6e9f34c685d40fa7a9f5935d8970af6fd9d5f118` 安装 **tau2 1.0.1** 到 `E:\Retail-Agent\.venv`，解释器为 `.venv\Scripts\python.exe`（Python 3.12.13）。不是普通 tau2-bench 分支；包含实际的 `tau2.hyper.agent_context` 与 `tau2.hyper.client_api`。

直接 Git 安装因上游资料文件名含 `?` 而在 Windows 检出失败。改为从已验证提交导出 `src` 子树，再读取同一提交的原始 pyproject.toml、README.md 和 LICENSE 构建安装；没有修改框架源码或 Git 配置。src ZIP SHA-256 为 `938f3a8bdcf843dde97dd2a9202ab17bf8c02005a504cb09ab75802b8cc36b20`。安装源码、缓存和依赖均在被忽略的 `.venv/` 内；未读取上游业务答案或资料正文。按上游约束将 openai 限定到不高于 2.20.0，实际为 2.20.0。

`uv pip check` 核对 78 个包，全部兼容；在此虚拟环境重跑现有离线套件 **43/43 通过**。另用未注入 tau2 替身的独立进程验证真实消息类、ModelGateway.generate 签名、ClientAPI.request 签名及 status_code/body/headers/elapsed_seconds；工厂 context、工具 schema 注册、查询往返、真实平台消息历史恢复、SDK 异常 response 属性均通过。传输使用合成记录，实际 ClientAPI 处理 2 次本地查询；模型调用和网络尝试均为 0。

离线验证设置 `PYTHON_DOTENV_DISABLED=1`、`LITELLM_LOCAL_MODEL_COST_MAP=True`、`LITELLM_TELEMETRY=False`、`HF_HUB_OFFLINE=1`，并用进程审计拒绝网络连接；未读取权限文件或 .env。构建上下文时需要至少一个模型配置，验证只使用未调用的合成名称，不是允许启用模型的证据。安装未包含上游业务数据，SDK 的默认 data 目录缺失提示不影响本次接口/查询验证，不代表具备本地完整评测环境。

此结果证明上游固定版本的最小 SDK 兼容，尚未证明它与课堂镜像版本完全一致；真实网关尚未接线或调用，完整响应转换和异常覆盖仍待 M2/联调。Q3 改为最小本地验证通过、课堂环境与网关验证待完成，M0.4 不整体勾选。

在自己的 PowerShell 中无需修改执行策略，可直接运行：

```powershell
& 'E:\Retail-Agent\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

## 本轮分批提交与推送记录

此前 M0 三次提交 `cd0377a`、`3bce8f8`、`afa6102` 已推送且未包含 M1 源码。之后按用户明确授权继续分批提交、逐批推送，阶段边界如下：

1. M0 `40f6ae0`：`M0-DELIVERY`、`OPEN-ITEMS`、`PLATFORM-CONTRACT-NOTES`、`IMPLEMENTATION-PLAN` 四份文档；独立快照 15/15，不含 agent/，未触发自动评测。
2. M1 `4e5728f`：公共 Client API、客户查询传输、fake 与传输回归；独立快照 24/24，Actions 36975489858 / t1 1/1 通过。
3. M1 `62eb206`：平台入口、内部协议、状态/历史恢复、轮次与对应回归；依赖代码保持在同一批，独立快照 43/43，Actions 36975637348 / t1 1/1 通过。
4. M1 `ba53f46`：`money.py`、`test_money.py`；独立快照 51/51，Actions 36975790435 / t1 1/1 通过。未接入业务执行，不提前勾选 M3/M5。
5. M1 本提交：`PROJECT.md`、`docs/IMPLEMENTATION-PLAN.md`、`docs/OPEN-ITEMS.md`、`docs/M0-DELIVERY.md`、`docs/M1-DELIVERY.md`、`docs/PLATFORM-CONTRACT-NOTES.md`、`docs/FOUNDATION-TEST-MAP.md`，同步实际源码交付和最新 51 项测试计数。仅文档，不再触发自动评测。

三份报告都经过 commit_sha/run_id 对应校验；逐批 Job、Actions 和网页链接见 [M1 交付记录](M1-DELIVERY.md)。重复运行同一个 t1 案例不增加不同业务场景的覆盖数。原始平台返回存档始终位于仓库外，具体路径、版本和校验和见 [平台契约记录](PLATFORM-CONTRACT-NOTES.md)。

目标仓库为 `1471436961/retail-agent`，分支 `main`；绑定 `5147314e-f2da-4bac-924a-e2ad95e647e4`，场景 retail_plus，语言 Python，任务 t1，case_ids=null，保持原绑定范围。权限文件 `E:\Enterprise-AI.json` 和原始业务材料保持仓库外。

第 2–4 批中的 agent 变更命中现有 [hyper-lab.yml](../.github/workflows/hyper-lab.yml) 的 main/agent 路径条件，各自只等待推送产生的同一任务，没有另行提交 evaluate。t1 接入结果与本地 51 项分别记录，不能当完整业务成绩。未来模型调用或收费评测仍先核对配置与费用授权；本轮没有修改绑定、服务开关或生产部署。


## M4.3 当前取消组件

[M4.3 交付](M4.3-DELIVERY.md)与[取消回归](../tests/test_m4_cancellations.py)覆盖原因澄清、精确 pending、自有事实、完整逐 charge 原路复述/确认、单一 POST/回执强读回、409/422、Unknown、共享认领、跨流程互斥和真实 schema 7→8 恢复。模型仍八 READ，默认库存三个内部 WRITE；取消专项 63 项，完整工作区 544/544。C 类映射引用这些实际执行的方法，完整公开业务 AT 执行数仍 0，不把合成结果或 t1 记成公开取消案例通过。M4.2 的 481/481 保留历史来源；当前报告和追踪通过 run_id/source/specification 同时校验。

## M5.2 完整商品组件

[M5.2 交付](M5.2-DELIVERY.md)与[商品专项](../tests/test_m5_items.py)覆盖真实 user 条件与索引、完整清单、回退/并列、原价差价、最后询问与后一次确认、单一 POST、回执及自有强读回、追加/改口、刷新竞争候选、锁单、Unknown 和 schema 9→10 来源恢复。I 映射关联实际执行方法，纯筛选由默认商品生产器调用；五个内部 WRITE 均不在模型八 READ 白名单。当前完整工作区 726/726，专项 65/65；报告和追踪必须成对校验，business_ats_executed=0。
