# 零售业务规则与证据台账

版本：M0 规则基线，初稿 2026-09-29，评审更新 2026-10-02。关联 [实施计划](IMPLEMENTATION-PLAN.md)、[来源追踪](CASE-TRACE.md)、[全案例原子需求](CASE-REQUIREMENTS.md)与[待决事项](OPEN-ITEMS.md)。第 6 节已登记生效依据和正反例语义；全案例需求分析已完成，具体业务测试函数和真实运行时兼容结论仍待后续交付。

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
| S23 | [教学说明](../materials/CLASSROOM.md) / [教学 OpenAPI](../materials/client_api/openapi.yaml) | 真实调用字段、已开放能力、状态码与响应行为；适配器以此为准 |
| S24 | [工具/API 契约](../materials/framework/client_api_contract.md) / [Agent 契约](../materials/framework/agent_contract.md) | 重放、重试、会话上下文、轮次协议和模型能力 |
| S25 | [公开案例](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md) | 134 个客户需求，尤其“业务要求”里的后续改口和追加；不包含可编码的后台参考答案 |
| S26 | [平台契约核查记录](PLATFORM-CONTRACT-NOTES.md) | 2026-10-01 contract-notes-v1，2026-10-02 经 Agentist 助教核对；记录平台原始 path/version，明确 U1–U6；不冒充真实运行验证 |
| S27 | [退款源码证据](REFUND-IMPLEMENTATION-EVIDENCE.md) | 2026-10-03 静态读取官方固定提交 6e9f34c685d4 的公开 retail_plus/retail 实现；记录路径、文件哈希及与现行规则的差异，不证明课堂 REST 后端一致 |

## 2. 规则登记

“现行”表示已有来源支持当前业务语义，不表示已验证真实部署完全相同。工具请求仍须遵守 S23，部署差异要记录。

| 规则 ID | 范围与规则 | 主要依据/裁决 | 实施与负例验收 |
|---|---|---|---|
| ID-01 | 身份必须独立验证：邮箱，或完整 first/last name＋postal code | S01 的已确认决定 | 客户 ID、订单号、电话、从档案反读的邮箱均不替代验证；详情读取不能先于验证 |
| ID-02 | 一个会话服务一个已验证客户；可处理本人的多项需求和多单 | S01；S17 CONTRACT-1001 | 不切换为配偶/室友账户；每个订单核对 customer_id，并避免展示他人详情 |
| ID-03 | 找不到/无法验证时说明无法验证，不泄露档案或确认订单存在 | S04 的 05-28 最终决定 | 引导使用允许的验证信息；不新增锁号、风控标记或“三次失败”规则 |
| CF-01 | 所有相关记录写变更都先完整复述并等待明确同意；查询不需要变更确认 | S03；S10 现行 C-5/A-3/I-6 | “只有金钱操作需确认”草案已被否决；未确认写调用为 0 |
| CF-02 | 确认对应当前具体提案，用户改口或关键事实变化使其失效 | S03；S10 第 8–10 页 | 早于复述的 yes、沉默、无关应答均不算；地址修正后重新读完整地址 |
| CF-03 | 商品修改前确认清单已完整，最后询问是否还要修改，并等客户回答 | S08；S10 第 13 页 I-6 | M5.2 完整清单复述＋最后询问在同一消息；统一渲染将补充询问放在消息末尾，不再追加集合确认问题，等待其后的真实 user 完整确认；追加/修正重建整份清单，不强行规定两轮重复 yes |
| ST-01 | pending 可按条件执行地址、支付、取消、规格修改；processed 不可办理这些动作 | S05；S17 CONTRACT-1001 | 写前刷新；客户主张已收到但后台 processed 时不能直接退货 |
| ST-02 | `pending (items modified)` 与普通 pending 不同，进入后无继续订单修改/取消权限，包含支付方式切换 | S08 Frame 4；S17 CONTRACT-1001 的 allowed_actions=[]、CONTRACT-1003 | 第二次追加、地址改动、支付切换或取消均零写入；没有 60 秒/15 分钟反悔窗口 |
| ST-03 | delivered 才能开启退换，申请后不能追加或通过另一操作绕过单次限制 | S17；S20/S21；S25 ID 120 | 同单退换冲突在首次提交前澄清；不假定两个端点可连续办理 |
| ST-04 | cancelled 不可恢复或再次取消 | S05；S17 | 可以查询解释已有状态；用户反悔不创建伪恢复操作 |
| CA-01 | 取消原因仅 no longer needed / ordered by mistake，自然同义表达可接受 | S02 04-29 CR8；S06 | 价格低、物流慢或 other 不强行映射到允许原因；解释并提供人工选项 |
| CA-02 | 获得取消原因后复述订单、金额、退款去向并取得明确确认 | S06；S10 第 5 页 C-2、第 8 页 C-5 | 可以先只读查状态；不能处理后才补问原因，不能复述前的同意直接算数 |
| AD-01 | 默认地址与订单地址分属不同记录；更新需完整相关字段与确认 | S03；S07；S23 | 不擅自同步两个地址；不把教学 schema 未支持的姓名/备注作为写字段 |
| PY-01 | 订单支付切换使用一个不同的已有方式；gift card 必须覆盖整单 | S07 | 不添加新方式、不组合两张卡补足；余额不足不试图部分扣款 |
| PY-02 | 支付切换由后端先全额扣新方式，成功才全额退款至原方式；成功后仍 pending | S15/S16 | 不自行调用两个独立支付动作；明确拒付时原订单不变；未知结果不等于明确拒付 |
| IT-01 | pending 商品变更限同产品的可用规格，整单完整列表一次提交 | S08；S17 CONTRACT-1003；S19 | 保留未要求变动的规格与商品次数；拒绝变数量和跨产品替换 |
| IT-02 | 商品修改按目标当前价格与订单原价计算总差价，使用一个已有方式 | S08 | 礼品卡覆盖全部正差价；不把整单总价当差价，也不自行创建退款/补款记录 |
| SEL-01 | 候选先硬条件、库存和原属性保留，再应用用户偏好/明确回退及优先级排序；并列无决策依据须询问 | S22 的非协商属性/整套规格/价格归属；S25 ID 8/18/35/41/64/70 的具体客户偏好与回退 | M5.1 纯筛选由 M5.2 有限真实 user 完整清单生产器调用，条件/回退原文与索引可恢复；无偏好匹配不是硬拒绝，读取/测量未知不是零库存，不自动放宽或以 item_id 破并列；提交前完整目录刷新和候选重核 |
| RT-01 | 退货一次提交完整选定 item 列表；金额依据原成交信息 | S20；S23 | 开启后不追加；item 列表不自动去重；申请成功不等于已到账 |
| RT-02 | 退货退款至原支付方式或申请开启前已保存在档案的礼品卡；存在选择时由客户选 | S02 05-04 RD5 | 不新发礼品卡，不改到其他银行卡或未用于该订单的 PayPal；候选资格需在流程起点记录 |
| EX-01 | 换货限同产品可用规格；差价方式是档案已有方式；换货退款不受 RT-02 的原路/礼品卡限制 | S02 05-04 RD5；S21 | 允许业务规则下的其他已存方式；提交时记录，之后不变；不足额/零差价仍按请求结构处理 |
| RF-01 | 取消退款逐 charge 按原金额退至各自原支付方式；即使同一方式也不把记录合并净额 | S12；S06 | 依据交易类型和真实回执核对，不自行改写后台账本或重复发起退款 |
| RF-02 | 礼品卡退款即时；卡/PayPal 告知 3–6 工作日，支付切换适用同矩阵 | S13/S14；S06/S07 | 旧 6–9 工作日已被当前材料替代；到账承诺区分后端退款记录与渠道结算 |
| MO-01 | 保留原始金额与交易类型；当前修改/换货差价按顺序 float 累加后 round(total, 2)，余额更新也 round；以回执核实 | S18 历史精度语义；S23/S26 当前算法 | 不逐行舍入求和，不以 ROUND_HALF_UP 或提前转整数分覆盖后端；不发明时间戳，未知金额不当 0 |
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

## 5. 实施原则与需联调的窄边界

1. **目录查询范围（U4）**：S17 CONTRACT-1001（2026-05-29 生效）的历史 production 范围写为订单相关产品；S26 当前教学解释明确包括与本次请求相关的公共目录。验证后可做目录计数、规格/库存/价格查询与候选比较，不要求历史购买。两种来源保留适用范围；禁止跨客户账户访问、新下单和将工具数据当授权。
2. **重复商品实例（U5）**：item_id 是变体 ID；数组次数表达数量，不能去重或添加 quantity/line ID。S26 明确当前修改逐次替换首个匹配项，差价也按 ID 匹配；常规同一旧 ID 换不同目标已有依据。内部 occurrence 只帮助保留请求语义，不能承诺精确选择同 ID 不同价格/属性的实例；这类输入按平台能力边界记录报告。
3. **履约事实（U6）**：当前状态准入已明确，无 shipped 枚举；processed 不是精确发货事件，不能推断发货时间。历史 guard 不直接变为教学字段，tracking ID 单独不证明发货。未知状态或事实矛盾停止受影响写操作并取证。
4. **金额规范化（U3/U6）**：正常余额/价格/支付金额是 JSON number；数字字符串未有可复现部署证据，若做兼容仅作为严格防御策略并记录异常。S18 保留历史分精度语义；S26 当前算法是按请求顺序 float 累加差价后 round(total, 2)，余额更新也 round。Decimal/整数分不未经验证替代当前算法，不提前丢原始精度；报价标估算，以回执和支付记录核实，不推及未公开账务路径。

   S27 补充实现证据：固定上游退货不计算退款额，取消不计算统一合计；余额舍入与 float 字段类型不能推出结算合计算法。取消循环未筛选历史交易类型，与 RF-01 的逐 charge 依据存在差异，本项目仍将已有 refund 与付款分开。当前未证明上游对应课堂 REST 后端，不将其差异宣称为课堂已发现故障；也不因结算公式未取得而阻断原路申请或原价预计额。

   **项目预计额显示决策（2026-10-04）**：所选原成交价以 Decimal(str(price)) 精确合计次数，最后一次 half-up 到分，复述固定两位小数；保留 exact_price_sum、estimate_method 和 amount_is_estimate。选择 half-up 是用于可追溯的顾客预计额显示，使精确十进制中点向上取分；不是材料规定的后台结算公式。MO-01 的 ROUND_HALF_UP 反例针对替换已有修改/换货差价及余额算法，本路径没有替换 money.py，不把预计额作为 API 参数或退款到账证据。精确十进制 half-even 与 Python float round 也不是等价替代；0.005 / 0.015 / 1.005 的单件测试分别锁定 0.01 / 0.02 / 1.01。实际结算与渠道到账继续按权威记录表述，aggregation_contract_verified/settlement_verified 保持 False。不等待假定将来新增的公式才能完成当前支持范围。
   **取消与退货显示口径的区别（M4.3）**：取消复述的是已记录的逐笔原 charge，精确十进制合计、不舍入，保留原精度，至少显示两位；退货根据所选原成交价推导预计额，half-up 到分仍是上文明确标注的项目显示选择。区别来自已记录付款与原商品价格预计值的不同含义，不是历史遗漏，也不表示材料要求退货必须分位量化。两者金额均不作为对应 API 的参数，不声明后台结算公式或到账；不等待新增平台公式才实施当前合法流程。
5. **退货礼品卡资格（U7）**：S02 RD5 已明确申请开启前已保存的礼品卡可选，会话中新加卡不合格。M5.3 已冻结首个实际 user 退货请求前最近一次接纳档案的方式及历史索引；未验证身份时先提出请求，则以随后首个成功验证的档案作为本项目可操作流程起点，不由后续刷新替换。按历史前缀重算起点和候选资格，后加礼品卡不能通过重新复述回填；M6 回归，无须平台新增 opened 时间戳。外部并发新增且历史资格无法证明时不将其当合格，保留原路等已有合法选择，不用本机时钟推断。退款去向规则已接入默认生产器、提案事实绑定和发送前复核；原路 instrument 若已不在当前档案，按现有后端 instrument 范围要求选择合法已有方式或人工协助，不添加新方式。
6. **接口职责与联调（U1/U2）**：工具和内部候选由项目设计；S26 已公开 Python generate 签名、tau2 messages/actions、消息返回和主要 usage 字段，TypeScript tools 只作语义对照。上游固定版本 SDK 的本地查询/恢复与 Client API 异常最小验证通过，课堂镜像一致性和完整网关转换/异常仍待完成。运行时 available_models 优先于 manifest 快照；固定参数省略且不可覆盖，one_of 必选。credits 不扩大模型权限或授权费用，真实调用另需明确费用授权。

统一状态见 [OPEN-ITEMS.md](OPEN-ITEMS.md)。以上已知规则直接进入开发；剩余边界只限制具体缺乏依据的动作，不阻塞整个业务阶段。

本文件中的规则编号是项目内部追踪编号，不是平台评分器的内部规则 ID。后续每次修改规则应保留来源、受影响测试及变更原因，不以新的提示词直接覆盖已有业务结论。

## 6. M0 生效与正反例审查

下表的“日期”是可见证据的决定/更新日期，不在没有依据时臆造正式上线日。“现行”表示该规则有目前适用的业务或教学契约依据；第 5 节列明的边界仍须核实。正反例是本地待实现的测试语义，不能把本表当成测试已通过记录。

| 规则 | 状态；证据日期/来源 | 被替代或明确排除的旧口径 | 正例 / 反例测试语义 |
|---|---|---|---|
| ID-01 | 现行；4 月确认，S01 | 仅用客户 ID、电话或订单号验证 | 邮箱搜索后读本人档案 / 仅 ID 时零详情读取 |
| ID-02 | 现行；S01、S17 于 05-29 生效 | 中途切换家人账户 | 本人两订单分别服务 / 室友订单零详情与零写 |
| ID-03 | 现行；05-28 S04 | 近似匹配提示、第三次失败锁号草案 | 失败时提供允许信息指引 / 不提示账户是否存在 |
| CF-01 | 现行；05-28 S03 | 只有金钱变更才确认的草案 | 地址变更完整复述并获同意 / 查询不强索确认、无同意零写 |
| CF-02 | 现行；05-28 S03、06-12 S10 | 复述前的 yes、沉默、限时默认同意 | 同意最新完整提案 / 改口后旧提案零写 |
| CF-03 | 现行；06-12 S10、07-28 S08 | 逐条立刻提交、短时补单窗口 | 收齐清单并等待最后回复 / 客户仍考虑时零提交 |
| ST-01 | 现行；05-29 S17、07-28 S05 | 将 processed 当 pending | pending 符合条件可提案 / processed 零订单写 |
| ST-02 | 现行；05-29 S17、07-28 S08 | 商品修改后仍按普通 pending 处理 | 一次整单提交 / 再改商品、地址、支付或取消零写 |
| ST-03 | 现行；05-29 S17、S20/S21 | 未送达即可退换、同单多次追加 | delivered 后提交完整列表 / 后续追加零写 |
| ST-04 | 现行；05-29 S17、07-28 S05 | 已取消订单可恢复 | 查询解释取消事实 / 不调用伪恢复操作 |
| CA-01 | 现行；04-29 CR8，S02/S06 | 自由文本、五/三原因、严格逐字匹配 | 自然语言“改变主意”映射允许原因 / 价格投诉不改类 |
| CA-02 | 现行；06-12 S10、07-28 S06 | 先处理后补问理由、先同意后复述 | 原因→复述→确认→写 / 缺任一步零取消写 |
| AD-01 | 现行；05-28 S03、06-12 S10、S07 | 仅回读修正字段、默认地址自动同步订单 | 完整地址回读后改正确记录 / 修正未重读或串记录零写 |
| PY-01 | 现行；07-28 S07 | 混合支付、临时新增方式 | 单一已有方式且礼品卡足额 / 两卡凑额拒绝 |
| PY-02 | 现行；05 月 S15/S16、07-28 S07 | 先退后扣、等发货才退旧款 | 成功后仍 pending / 新扣拒付时不称已切换 |
| IT-01 | 现行；05-29 S17、S19、07-28 S08 | 跨产品替换、数量修改 | 同产品可用规格整单一次 / 跨产品或缺货不提交 |
| IT-02 | 现行；07-28 S08 | 将整单总价当补差价、礼品卡部分覆盖 | 订单旧价与新规格现价求差 / 余额不足不混合方式 |
| RT-01 | 现行；S20、S23 | 开启退货后再追加商品 | 原成交商品完整列表 / 申请后追加零写 |
| RT-02 | 现行；05-04 RD5，S02 | 任意新卡或会话中新加礼品卡 | 原方式或合格旧礼品卡由客户选择 / 新卡拒绝 |
| EX-01 | 现行；05-04 RD5，S02/S21 | 将退货的退款去向限制直接套给换货 | 同产品可用规格与已有方式 / 事后更换已提交方式零写 |

M5.4 默认换货生产器已承接 EX-01/ST-03/MO-01：完整原单位→同产品可用规格、有符号差价、一个已有方式以及后一次真实完整确认。负差价不套用 RT-02；正差价礼品卡覆盖全额，零差价不省略方式。申请已核实后不追加或改方式。原单位互换在换货申请中可表达，pending 商品修改的逐步匹配限制仍保留；这不是取消 U5 次数/歧义校验。回执按替换对多重集保留对应关系，不能用独立排序的旧/新 ID 冒充正确配对；申请回执不证明退款或发货。详见 [M5.4 交付](M5.4-DELIVERY.md)。
| RF-01 | 现行；04-16 S12、07-28 S06 | 3 月净额单行退款 | 两笔 charge 对应两笔原路退款 / 不合并为净额 |
| RF-02 | 现行；4 月决议、5 月培训版 S13，S14 | 旧 6–9 工作日 | 卡/PayPal 3–6 工作日、礼品卡即时 / 不说全部即时到账 |
| MO-01 | 历史精度 S18；当前 S23/S26 | 旧五卡上限、虚构时间戳、修改/换货差价逐行舍入或将差价/余额改用 ROUND_HALF_UP | 顺序累加/round 与回执及交易类型一致；项目原价预计额显示另见 §4 / 不默认未知为零或覆盖后端算法 |
| BN-01 | 现行；04-10 EM3、04-27 QS4，S02/S17 | 退休的广泛订单编辑面 | 允许的规格变更 / 改数量、拆单、改邮箱零写 |
| HO-01 | 现行；S24/S25 | 用户或模型提供 conversation_id | 可信会话 ID 转接后终止 / 失败时不说受理 |
| EN-01 | 现行；S23/S24 | 把 PUT 当可自动重试 | 只读有界重试 / 写超时至多一次且标结果未知 |
| EN-02 | 现行；S24 | 随机、时间、跨会话缓存作为工具判断 | 新实例重放同轨迹 / 外部状态改变不得影响结果 |

全体案例的条件、改口、偏好及 N/E/B 需求已在 [CASE-REQUIREMENTS](CASE-REQUIREMENTS.md) 拆成 522 条规则/API/阶段关联的验收场景；[CASE-TRACE](CASE-TRACE.md) 保留自动生成的来源索引。下一步随业务实施将 AT 场景连接实际测试函数及运行结果，不把文档断言当已通过测试。

## M4.4 / M4.5 的 HO-01 实施范围

有限完整中英文的显式 user 转人工请求直接授权会话转接，不授权订单写入；未验证会话可转接但摘要如实记录未验证，不先读取私有档案。投诉/辱骂不自动触发；混合、条件或执行先后需澄清。summary 仅由已接纳事实、真实诉求、已核实完成/未决操作和阻塞 code 派生。只有 HTTP 201 与封闭 accepted/非空 transfer_id 回执才显示规定受理提示；accepted/Unknown/pending 禁止后续业务和模型调用，明确 rejected 后的新显式请求可重试。真实工具结果丢失按 Unknown，不能声称零发送。见 [M4.4](M4.4-DELIVERY.md)与[五端点矩阵](M4.5-DELIVERY.md)。不证明人工已响应或退款到账；共享进程表及完整 journal 是去重前提。
