# 离线运行与 AT 组件证据的有效性

当前 M5.3 默认退货流程使用 schema 11、八 READ＋六个内部 WRITE，模型只读；完整工作区 791/791，退货专项 65/65。来源、预计额、完整确认、Unknown 和 schema 10→11 前缀恢复见 [M5.3 交付](M5.3-DELIVERY.md)。T 组件映射来自实际执行；业务 AT 执行仍 0，历史章节不作为当前计数。

日期：2026-10-04。由 scripts/foundation_trace.py 生成 FOUNDATION-RUN.json / AT-TEST-TRACE.json；两者只是实际离线组件证据，不是完整业务 AT、远程评测或后台结算结果。业务范围始终 134 案例 / 522 AT。

## 发布与失效

每次 CLI 运行产生新的 run_id，先将当前追踪原子替换为 status=invalid、reason=run_in_progress。运行报告进入 running，实际 unittest 执行结束后记录逐方法结果。失败、错误、跳过、输入期间变化或引用方法未通过，都不能发布 valid 追踪；脚本返回 1，并留下失败报告及同运行的 invalid 标记。invalid 文件没有旧的通过 records/groups。

成功时先构造追踪，发布前再次标记 invalid，随后依次原子替换报告和追踪。报告 status=passed / exit_code=0，追踪 status=valid，两者具有相同 run_id。每个文件通过独占创建的同目录临时文件再 replace，临时文件最终清理；不假定两个文件之间有事务或跨进程锁。中断可能留下 invalid 或两者运行 ID 不匹配，不能视为当前成功。

读方必须同时加载两份文件、当前需求与 input_snapshot，再调用 validate_evidence_pair。只看旧追踪、valid 字段、相同 source_sha256 或绿色退出码都不足以判断当前证据。相同源码也可能下一次失败，run_id 防止将旧通过追踪与新报告混配。运行 ID 是本地关联标识，不是签名或外部真实性证明。

## 摘要覆盖范围

| 字段 | 范围 |
|---|---|
| source_sha256 | agent/**/*.py、tests/**/*.py、tests/fixtures/*.json、agent/agent.json 与生成脚本自身；包括相对路径和文件字节，不含缓存 |
| requirements_sha256 | CASE-REQUIREMENTS.md 的 UTF-8 读取文本，按文本换行规范化；保留原 AT 编号及来源 |
| specification_sha256 / specification_files | 以下显式允许列表每个文件的字节 SHA-256，以及路径/摘要映射的总体 SHA-256 |

关键规格允许列表：

- materials/CLASSROOM.md
- materials/client_api/openapi.yaml
- materials/framework/agent_contract.md
- materials/framework/client_api_contract.md
- materials/framework/scenario_contract.md
- materials/framework/deployment_manifest.json
- docs/POLICY-REGISTER.md
- docs/API-CONTRACT-MAP.md
- docs/PLATFORM-CONTRACT-NOTES.md
- docs/REFUND-IMPLEMENTATION-EVIDENCE.md

开始与结束比较全部输入快照，包括代码、需求及选定规格。规格改变后旧报告不能证明新规格下通过，须重新运行；即使只是文字修改也一样。该范围不覆盖任意其他文档、所有业务材料、仓库外 raw/ZIP、权限文件或凭证，不称全仓规格快照。报告不读取 Enterprise-AI.json、.env、Git 凭证。

## 运行与范围

使用项目解释器运行 `-B scripts/foundation_trace.py`。普通 unittest 命令仍可运行，但不会刷新这两份证据。缺真实 SDK 解释器按原包装测试失败，不静默跳过；SDK 子检查已经包含于主包装测试，不与主计数重复相加。测试使用 fake API/网关，成功路径不调用真实模型或网络。

追踪中 related_components_passed 表示相关方法实际执行通过；business_result=not_executed、business_test_ids=[]、remote_result=not_run 和 business_ats_executed=0 继续保留。改变发布协议不意味着完整业务已验收，也不启用业务写路由。

## M4.1 地址组件与当前 M4.2 支付证据

[M4.1 交付](M4.1-DELIVERY.md)列出已接入默认轮次的两类地址流程、完整复述/确认、各自 PUT/强读回，以及只读 prepare 恢复、execute Unknown、逐记录混合结果与工具预算回归。实际用例见 [地址流程](../tests/test_m4_addresses.py)和[评审回归](../tests/test_m4_address_review.py)。A/D 仅关联这些实际执行的组件；发布器改动本身不开写，但 M4.1 阶段注册一个内部地址 WRITE；当前 M4.2 增至两个内部地址/支付 WRITE，模型仍限八 READ。完整公开业务 AT 执行数仍为 0，不把合成地址流程或 t1 历史绿色当作全部地址案例通过。

[M4.2 交付](M4.2-DELIVERY.md)及[支付回归](../tests/test_m4_payments.py)覆盖默认真实 user、整单原 charge、已有方式/足额/客户指定回退、复述确认、一个 PUT、退款记录及状态强读回，拒付、Unknown、丢失批次、交叉路由、共享认领和旧 schema 恢复。P 映射现关联这些实际方法；真实 SDK 子进程另验收 native 消息/Tool/ClientAPI/fake 支付往返，拒绝网络，子检查不额外累加。M4.1 的 421/421 为历史基线，当前报告/追踪刷新到本批实际执行快照；不将其转为公开业务 AT 或实际渠道到账证明。

M4.2 评审修订增加匹配的逆序交易列表与回执/读回排列不一致两侧、确切状态/读失败 code、原始方式 ID、准备异常恢复、运行时错误金额及未决记录阻断。先扣后退是政策要求；数组排列不是执行时序证据，单个 PUT 也不是原子性证明，详见交付记录。


## M4.3 当前取消组件

[M4.3 交付](M4.3-DELIVERY.md)与[取消回归](../tests/test_m4_cancellations.py)覆盖原因澄清、精确 pending、自有事实、完整逐 charge 原路复述/确认、单一 POST/回执强读回、409/422、Unknown、共享认领、跨流程互斥和真实 schema 7→8 恢复。模型仍八 READ，默认库存三个内部 WRITE；取消专项 63 项，完整工作区 544/544。C 类映射引用这些实际执行的方法，完整公开业务 AT 执行数仍 0，不把合成结果或 t1 记成公开取消案例通过。M4.2 的 481/481 保留历史来源；当前报告和追踪通过 run_id/source/specification 同时校验。

## M4.4 / M4.5 当前转接与五端点组件

[M4.4](M4.4-DELIVERY.md)的[转接专项](../tests/test_m4_handoffs.py)覆盖真实 user 来源、可信会话路径、201/accepted/非空 ID、已核实与 Unknown 摘要、受理后零业务/模型派发、共享表及迁移；H 映射从只验 schema 扩展到真实默认轮次。真实 SDK 子进程使用 native 消息/Tool/ClientAPI 和 fake transport，网络禁止，子检查不额外累加。

[M4.5](M4.5-DELIVERY.md)的[矩阵](../tests/test_m4_matrix.py)对默认地址/订单地址/支付/取消/转接五端点执行同一正常、409/422、写后超时、缺字段、丢失/错配批次与改口检查；子测试不另计方法数。完整公开业务 AT 执行仍 0，134/522 不变；成功计数须来自本轮 FOUNDATION-RUN 与 AT-TEST-TRACE 的 run_id/source/specification 成对校验，不能沿用 M4.3 的 544。

M4.4 评审收尾新增两条摘要文本隔离测试，断言伪造完成/身份/去向/到账文字不能改写派生字段，Unknown 业务不被升级或重发。[真实 SDK 子检查](../tests/sdk_m3_checks.py)另外用基础 Environment 的真实记录格式验证隔离 fake 后端的严格重建、原 live claims 拒绝重复 POST，以及 GENERIC/False 仍执行但不比对回执的行为；这些检查包含于原主包装项，不另加计数。canonical 历史恢复与 SDK 评测重建是不同入口，不能将后者的执行当成前者的重发，也不能靠 GENERIC 标签提供去重。JSON 数据标签不证明下游消费方免疫提示注入。

## M5.1 当前候选组件

[M5.1 交付](M5.1-DELIVERY.md)与[候选专项](../tests/test_m5_candidates.py)覆盖硬条件、库存、原属性保留、软偏好、显式回退、按优先级最优组和并列询问，真实 user JSON 的内部应用入口消费已接纳完整目录，最新失败不能当零候选。SEL 组件映射已引用实际筛选及来源守卫方法；该 M5.1 阶段默认商品生产器尚未实施；当前 M5.2 接线见下节，退换仍待 M5.3/M5.4。组件通过不代表完整公开业务 AT；当前配对报告是唯一运行基线。

评审收尾增加回退分支自己的 change/relax、eq/in 禁用 order、数值输入错误与测量缺口区分、已排除未知不影响 trace 的区分性测试；排序比较失败诊断保留尚待比较组并明确未选定。助手复制 user JSON 仍不得成为请求来源。M5.1 阶段登记的自然语言条件归因与完整复述约定现已由 M5.2 落地，见下节。

## M5.2 完整商品组件

[M5.2 交付](M5.2-DELIVERY.md)与[商品专项](../tests/test_m5_items.py)覆盖真实 user 条件与索引、完整清单、回退/并列、原价差价、最后询问与后一次确认、单一 POST、回执及自有强读回、追加/改口、刷新竞争候选、锁单、Unknown 和 schema 9→10 来源恢复。I 映射关联实际执行方法，纯筛选由默认商品生产器调用；五个内部 WRITE 均不在模型八 READ 白名单。M5.2 当时完整工作区 726/726，专项 65/65；报告和追踪必须成对校验，business_ats_executed=0。

## M5.3 完整退货申请组件

[M5.3 交付](M5.3-DELIVERY.md)与[退货专项](../tests/test_m5_returns.py)覆盖真实请求来源、开启礼品卡来源冻结、原价预计额、合法去向、完整确认、一次 POST、回执和自有强读回、Unknown 及 schema 10→11 前缀恢复。T 映射引用实际执行的方法，未将申请核实登记为退款结算/到账或完整公开业务 AT。

评审收尾分别检验重复单位原价求和、非字典序混合 ID 的排序容忍、回执及强读回少一份/多一份拒绝、唯一去向确认前零 POST、多单位超限与畸形支付档案诊断。单元模型门拒绝共享名字，真实 SDK 工具库存对照另验证这些名字实际注册，两者共同提供证据；完整通过计数仅取配对报告。

后续收尾统一有序业务 WORKFLOW_KINDS，handoff 独立；专项对每个实际业务 dispatch 重建 pending，并逐 peer 验证拒绝重叠批次。唯一去向以银行卡/起点合格礼品卡两个子场景检验真实完整确认。原 SDK 包装显式断言 M5_RETURNS 完成 marker，不额外计数。
