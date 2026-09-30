# 零售业务规则与证据台账

版本：规划初稿，2026-09-29。关联 [实施计划](E:/Retail-Agent/docs/IMPLEMENTATION-PLAN.md)。本文件整理已识别的现行规则；逐条测试编号、全部案例映射和运行时兼容结论在 M0 后续补齐，不能视为全部规则已编码或通过测试。

## 1. 证据使用方法

原始材料保持在 `E:\enterprise-ai-materials\retail_plus`。以下链接指向原件，ZIP 内成员以文字注明；开发不需要把原包复制进仓库。邮件必须阅读已解码正文及往来时间线，会议必须区分讨论、否决和最终决定，Slack 需去重并按裁决时间追踪。

| 来源编号 | 原始来源 | 用途及边界 |
|---|---|---|
| S01 | [身份 intake](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/intake_form.md) | 只采纳 Confirmed pilot decision；Proposed/TBD 不构成授权 |
| S02 | [Slack 导出](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/workspace_export.json) | 取消原因、退款去向、数量/拆单、邮箱规则的日期裁决；不能把历史讨论全部累加 |
| S03 | [确认与 QA 会议](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/meeting_transcript_01.vtt) | 2026-05-28，所有相关记录变更的复述、确认、客户改口与一次性提交 |
| S04 | [身份与服务会议](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/meeting_transcript_03.vtt) | 2026-05-28，身份失败边界与不支持操作的处理 |
| S05 | [当前流程总图 Frame 1](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/process_map_02.png) | 图标注更新 2026-07-28；状态准入、现行/旧规则区分 |
| S06 | [取消 Frame 2](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/process_map_03.png) | 原因、复述、明确确认、逐笔原路退款与时效 |
| S07 | [地址/支付 Frame 3](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/process_map_05.png) | 完整地址回读；已有单一支付方式、全额覆盖、先扣后退 |
| S08 | [商品修改 Frame 4](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/process_map_01.png) | 完整清单、一单一次、最后补充询问与等待、修改后锁单 |
| S09 | [决策与待议 Frame 5](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/process_map_04.png) | 审核历史；parked 项是未批准想法，不是额外操作权限 |
| S10 | [QA 培训 PDF](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/slide_deck.pdf) | 25 页，修订 2026-06-12；第 3 页说明标签，第 5/8/10/13 页为现行行为卡，第 25 页说明各规则归属 |
| S11 | [取消账务邮件](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/email_06.eml) | 后端取消与退款记录语义；不授权 Agent 自行写账本 |
| S12 | [逐 charge 退款邮件](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/email_11.eml) | 2026-04-16 裁决，用逐笔原金额、原支付方式替代 3 月净额记账 |
| S13 | [退款时效更新](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/email_12.eml) | 4 月裁决定于 5 月培训版采用 3–6 工作日，替代旧 6–9 工作日 |
| S14 | [支付切换退款时效](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/email_07.eml) | 切换退款适用同一支付渠道时效，不另设等发货再退款 |
| S15 | [支付切换状态](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/email_08.eml) | 成功切换后仍是 pending，不人为推进履约 |
| S16 | [先扣后退](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/email_09.eml) | 新方式整单扣款成功才退旧款；明确拒付时不改变订单 |
| S17 | [系统导出 ZIP](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/system_export.zip) | `policy_contracts.json` 中 active/published/production、effective 2026-05-29 的 CONTRACT-1001/1002/1003；其他合同须看范围，不能全部当订单权限 |
| S18 | [历史记录接口 ZIP](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/api_contract.zip) | `record_contract_notes.md` 为 2026-06-12 的 Care Record 合同；金额精度等语义有用，字段及 REST 路径不能覆盖教学 API |
| S19 | [商品修改帮助](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/screenshot_16.png) | 具体 item 与完整规格选择，不能按名称相似替换 |
| S20 | [退货帮助](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/screenshot_46.png) | 退货整单提交一次、不能随后追加，使用原订单成交信息 |
| S21 | [换货帮助](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/screenshot_54.png) | 同产品可用规格、选中具体组合并核实 |
| S22 | [选购约束帮助](E:/enterprise-ai-materials/retail_plus/extracted/materials/uploaded_materials/screenshot_57.png) | 硬约束、偏好和回退需区分；规格价格不能混用 |
| S23 | [教学说明](E:/Retail-Agent/materials/CLASSROOM.md) / [教学 OpenAPI](E:/Retail-Agent/materials/client_api/openapi.yaml) | 真实调用字段、已开放能力、状态码与响应行为；适配器以此为准 |
| S24 | [工具/API 契约](E:/Retail-Agent/materials/framework/client_api_contract.md) / [Agent 契约](E:/Retail-Agent/materials/framework/agent_contract.md) | 重放、重试、会话上下文、轮次协议和模型能力 |
| S25 | [公开案例](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md) | 134 个客户需求，尤其“业务要求”里的后续改口和追加；不包含可编码的后台参考答案 |

## 2. 规则登记

“现行”表示已有来源支持当前业务语义，不表示已验证真实部署完全相同。工具请求仍须遵守 S23，部署差异要记录。

| 规则 ID | 范围与规则 | 主要依据/裁决 | 实施与负例验收 |
|---|---|---|---|
| ID-01 | 身份必须独立验证：邮箱，或完整 first/last name＋postal code | S01 的已确认决定 | 客户 ID、订单号、电话、从档案反读的邮箱均不替代验证；详情读取不能先于验证 |
| ID-02 | 一个会话服务一个已验证客户；可处理本人的多项需求和多单 | S01；S17 CONTRACT-1001 | 不切换为配偶/室友账户；每个订单核对 customer_id，并避免展示他人详情 |
| ID-03 | 找不到/无法验证时说明无法验证，不泄露档案或确认订单存在 | S04 的 05-28 最终决定 | 引导使用允许的验证信息；不新增锁号、风控标记或“三次失败”规则 |
| CF-01 | 所有相关记录写变更都先完整复述并等待明确同意；查询不需要变更确认 | S03；S10 现行 C-5/A-3/I-6 | “只有金钱操作需确认”草案已被否决；未确认写调用为 0 |
| CF-02 | 确认对应当前具体提案，用户改口或关键事实变化使其失效 | S03；S10 第 8–10 页 | 早于复述的 yes、沉默、无关应答均不算；地址修正后重新读完整地址 |
| CF-03 | 商品修改前确认清单已完整，最后询问是否还要修改，并等客户回答 | S08；S10 第 13 页 I-6 | 两项沟通可在同一轮完整表达；需要其后的客户回复，不强行规定两轮重复 yes |
| ST-01 | pending 可按条件执行地址、支付、取消、规格修改；processed 不可办理这些动作 | S05；S17 CONTRACT-1001 | 写前刷新；客户主张已收到但后台 processed 时不能直接退货 |
| ST-02 | `pending (items modified)` 与普通 pending 不同，进入后无继续订单修改/取消权限 | S08；S17 CONTRACT-1001/1003 | 第二次追加、地址改动或取消均零写入；没有 60 秒/15 分钟反悔窗口 |
| ST-03 | delivered 才能开启退换，申请后不能追加或通过另一操作绕过单次限制 | S17；S20/S21；S25 ID 120 | 同单退换冲突在首次提交前澄清；不假定两个端点可连续办理 |
| ST-04 | cancelled 不可恢复或再次取消 | S05；S17 | 可以查询解释已有状态；用户反悔不创建伪恢复操作 |
| CA-01 | 取消原因仅 no longer needed / ordered by mistake，自然同义表达可接受 | S02 04-29 CR8；S06 | 价格低、物流慢或 other 不强行映射到允许原因；解释并提供人工选项 |
| CA-02 | 获得取消原因后复述订单、金额、退款去向并取得明确确认 | S06；S10 第 5 页 C-2、第 8 页 C-5 | 可以先只读查状态；不能处理后才补问原因，不能复述前的同意直接算数 |
| AD-01 | 默认地址与订单地址分属不同记录；更新需完整相关字段与确认 | S03；S07；S23 | 不擅自同步两个地址；不把教学 schema 未支持的姓名/备注作为写字段 |
| PY-01 | 订单支付切换使用一个不同的已有方式；gift card 必须覆盖整单 | S07 | 不添加新方式、不组合两张卡补足；余额不足不试图部分扣款 |
| PY-02 | 支付切换由后端先全额扣新方式，成功才全额退款至原方式；成功后仍 pending | S15/S16 | 不自行调用两个独立支付动作；明确拒付时原订单不变；未知结果不等于明确拒付 |
| IT-01 | pending 商品变更限同产品的可用规格，整单完整列表一次提交 | S08；S17 CONTRACT-1003；S19 | 保留未要求变动的规格与商品次数；拒绝变数量和跨产品替换 |
| IT-02 | 商品修改按目标当前价格与订单原价计算总差价，使用一个已有方式 | S08 | 礼品卡覆盖全部正差价；不把整单总价当差价，也不自行创建退款/补款记录 |
| RT-01 | 退货一次提交完整选定 item 列表；金额依据原成交信息 | S20；S23 | 开启后不追加；item 列表不自动去重；申请成功不等于已到账 |
| RT-02 | 退货退款至原支付方式或申请开启前已保存在档案的礼品卡；存在选择时由客户选 | S02 05-04 RD5 | 不新发礼品卡，不改到其他银行卡或未用于该订单的 PayPal；候选资格需在流程起点记录 |
| EX-01 | 换货限同产品可用规格；差价方式是档案已有方式；换货退款不受 RT-02 的原路/礼品卡限制 | S02 05-04 RD5；S21 | 允许业务规则下的其他已存方式；提交时记录，之后不变；不足额/零差价仍按请求结构处理 |
| RF-01 | 取消退款逐 charge 按原金额退至各自原支付方式；即使同一方式也不把记录合并净额 | S12；S06 | 依据交易类型和真实回执核对，不自行改写后台账本或重复发起退款 |
| RF-02 | 礼品卡退款即时；卡/PayPal 告知 3–6 工作日，支付切换适用同矩阵 | S13/S14；S06/S07 | 旧 6–9 工作日已被当前材料替代；到账承诺区分后端退款记录与渠道结算 |
| MO-01 | 金额按分精确；交易 payment/refund 类型分开；不能发明交易时间戳 | S18；S23 | Decimal/整数分计算；JSON 写类型按教学 schema；舍入 tie-break 未定义不自行当政策固化 |
| BN-01 | 不改数量、不拆单、不改邮箱；不下新订单、不添加支付方式或做未列明动作 | S02 QS4/EM3；S17；S23；S25 | 网页自助说明不等于 Agent 写权限；禁止通过规格修改实现减数量 |
| HO-01 | 转人工使用可信会话 ID 和问题摘要；受理后不能继续业务操作 | S24；S25 ID 130 | 正确调用工具；适用提示为 `YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.`；失败或未知不冒称受理 |
| EN-01 | 写入及转接均禁止自动重试；成功写可强一致读取；未知结果需核实 | S23/S24 | PUT 也不例外；不编造幂等 key、异步 job 或新增端点 |
| EN-02 | 工具行为仅依赖后端、参数和本会话此前记录调用，可在新实例重放 | S24 | 无随机授权 token、时间窗口、外部文件状态或跨会话全局变量 |

## 3. 支付与退款分流表

| 动作 | 金额基准 | 方式约束 | 成功表述边界 |
|---|---|---|---|
| 取消 | 按实际支付历史及正式逐笔退款规则 | 每笔原支付方式 | 核实 cancelled 与实际 payments；外部卡结算可能仍需等待 |
| 支付切换 | 新方式扣整单，旧方式退整单 | 一个不同的已有方式，礼品卡整单足额 | 后台确认切换后仍 pending；不说订单已发货 |
| pending 商品修改 | 所选旧商品成交价与目标规格当前价之差 | 一个已有方式；礼品卡补款足额 | 核实新商品、`pending (items modified)`、支付明细 |
| 退货 | 选定商品的原成交金额 | 原支付方式或合资格已有礼品卡 | 当前端点开启申请，不能提前断言已收货审核或退款到账 |
| 换货 | 所选旧商品与新规格差价 | 已有方式；退款可去原方式之外的已存方式 | 核实 exchange 申请、差价和已记录方式；不承诺新包裹已寄出 |

金额、资格、库存和状态来自实际响应。表中的财务语义指导 Agent 选择与解释，不要求 Agent 复制后端记账实现。

## 4. 必须排除的历史或不适用规则

| 历史材料/提议 | 当前处理 | 原因 |
|---|---|---|
| 取消自由文本、五原因、三原因、逐字复读脚本 | 不采用 | 被 CR8 两原因＋自然语义规则替代 |
| 将价格投诉解释成 no longer needed | 不采用 | 04-29 裁决明确堵住这种映射 |
| 逐商品立刻提交、之后还有反悔窗口 | 不采用 | 当前整单一次性列表；相关窗口处于 parked 或已否决状态 |
| 退款净额单行、旧 6–9 工作日 | 不采用 | 逐 charge 裁决和当前时效材料已替代 |
| 新发礼品卡、支票、奖励余额、混合支付补足 | 不采用 | 不属于当前允许的退货/支付范围 |
| 仅涉及金钱时要求确认 | 不采用 | 05-28 会议明确改为相关记录变更均需确认 |
| PDF G-1/G-4/C-8/A-6/G-7/I-9 卡自动作为现行强制要求 | 不采用这种推导 | 这些卡标为 CALIBRATION-ONLY；是否存在其他义务须找独立现行来源 |
| PDF R 类、W 类要求直接用于普通零售 | 不采用 | R 已退休；W 是 wholesale 范围，不跨范围套用 |
| 旧五个已存支付方式上限 | 不采用 | 当前记录合同无此上限 |
| 导出中的 draft/sandbox/internal-admin/retired 字段或动作 | 不采用 | 与当前 production customer-care surface 不同 |
| 上游 run_local_test、向 Client 申请开放退货接口 | 不执行 | 课堂适配已经提供接口；本项目没有这些上游工具 |

## 5. 仍需定案的边界

1. **目录查询范围**：S17 限定为已验证客户订单相关产品；S25 含目录计数和选购需求。先逐例检查相关性，不能仅凭有 listProducts 就做匿名全目录服务，也不能粗暴删除公开需求。残余冲突记录在实施计划 U4。
2. **重复商品实例**：教学替换列表使用 item_id 对，不能自动理解成可识别所有行实例。保留多重列表，通过文档/测试验证表达方式；不以集合去重解决歧义。
3. **shipped 的映射**：历史动作 guard 有 shipped，教学响应没有该字段。使用真实 status 和履约信息，不创造字段或把缺字段当 false；冲突状态阻止相关写操作。
4. **金额响应差异**：教学示例/既有运行出现数字字符串余额，历史合同强调 JSON number。读取适配可处理有证据的数字字符串；发出的请求仍遵守教学 schema，不擅自把所有 number 变成字符串。
5. **退货礼品卡资格时间**：保存申请流程开始时可用方式，防止中途新加方式被当作原有。若真实运行定义的“request opened”时点与材料不同，必须明确记录再调整，不用本机时钟推断。
6. **网关与真实 SDK**：业务证据无法定义 Python SDK；按实施计划 U1/U2 单独验证。

本文件中的规则编号是项目内部追踪编号，不是平台评分器的内部规则 ID。后续每次修改规则应保留来源、受影响测试及变更原因，不以新的提示词直接覆盖已有业务结论。
