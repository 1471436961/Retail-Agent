# M0.2 全案例原子需求与验收设计

审查日期：2026-10-01。范围为当前绑定的 134 项公开说明，逐项阅读客户需求、期望结果和单列业务要求后形成；本文件不运行评测、不实现业务答案，也不改变 t1 或案例范围。

本次形成 **134/134 案例、522 条原子需求/验收场景**，覆盖全部 **139 个需求段落、176 个期望条目和 168 个单列业务条目**。来源原文件 SHA-256：`9c592d45d3aebacb7cbe13f7907558d5e0d1e2dd0577bdaf6f282adb0ba6fb55`。结构核对检查 ID 连续、场景编号唯一、所有 N/E/B 引用存在且无遗漏；内容拆解依据逐项阅读，不由结果标签自动生成。

每个 `Axxx-yy` 是本地需求及验收场景编号；`xxx` 为公开 ID，仅用于文档和未来测试，不进入 Agent 决策。每行描述一个可以检查的行为或条件分支，实际值来自合成 fixture/API。相同数字或关键词重复出现的业务条目保留各自来源，共用同一行为断言，不人为制造两个业务动作。

各案例的来源表中 `N1/N2` 指需求段落，`E1/E2/E3` 指原顺序的期望条目，`B1…` 指原顺序的单列业务要求；行内引用将三类来源分别连接到行为。`E` 是预期状态，不使尚未发生的用户选择或业务许可自动成立。客户侧“不要透露”“如果被询问才提出”的内容描述模拟客户行为，Agent 不得据此假定已收到该信息。

每行还列出下表的规则/API 组合。它们是实施与验收设计，不表示端点已经接入。每行未来测试场景 ID 为 `AT-` 加需求编号；目前所有场景均为**业务测试待实现、函数未关联、远程未运行**。现有 37 项底座测试不替代这些场景。需求分析完成与 M0.2 全部测试追踪完成分别记录。

## 规则、API 与阶段映射

公共前提 G 适用于每个案例：ID-01/02/03；用邮箱或完整姓名＋邮编独立搜索，已验证后读取本人档案/订单，跨客户不切换。失败/越权零敏感详情与零业务写入；禁止用客户 ID 或从档案读取的邮箱倒推验证。转接可使用可信会话上下文，不要求为不必要的详情查询先访问账户。

API 简称按[接口基线](API-CONTRACT-MAP.md)展开：身份搜索为 `POST /v1/customers/search`；档案为 `GET /v1/customers/{customer_id}`；订单为 `GET /v1/orders/{order_id}`；目录/产品/item 分别为 `GET /v1/catalog/products`、`GET /v1/catalog/products/{product_id}`、`GET /v1/catalog/items/{item_id}`；各订单写路径为 `/v1/orders/{order_id}/` 后接表中的操作名；默认地址为 `/v1/customers/{customer_id}/default-shipping-address`；转接为 `/v1/conversations/{conversation_id}/transfers`。完整参数、状态、异常与重试约束见基线，不引入额外端点。

公共写入前提 W 适用于每个合法写场景：CF-01/02、EN-01/02；完整提案与真实用户同意关联，改口失效，写前核验，成功/失败/未知分别记录。未知结果不自动重试；新工具实例可重放。只读咨询不套用 W。商品修改的清单收齐与最后补充询问按 CF-03 执行。

| 组合 | 规则 | 数据与 API | 实施阶段及通用验收 |
|---|---|---|---|
| O | ID-02、ST-01/03/04、MO-01 | 客户档案 GET、订单 GET | M2；自有订单消歧、实际状态/地址/商品/履约/成交信息，不猜他人订单 |
| SEL | IT-01、EX-01、BN-01、U4/U5 | 订单 GET、相关产品目录/产品/item GET | M2/M5；同产品、硬约束、库存、属性保留、偏好/回退与重复次数 |
| M | MO-01、IT-02、RF-01/02、PY-02、RT-01、EX-01 | 订单成交与 payments、档案方式/余额、目标 item 价格 | M3–M6；按具体动作计算和解释金额，不净额改写交易账本；渠道到账与申请受理区分 |
| F | CF-01/02/03 | 真实消息、提案版本和只读事实；本步骤不写 | M3/M6；追加、撤回、局部/条件同意使不匹配的旧确认失效 |
| I | IT-01/02、ST-01/02、CF-03、W | 订单/产品/item/档案 GET；POST item-modifications | M5；pending 整单完整列表一次修改，差价方式合法，提交后锁单 |
| T | RT-01/02、ST-03、W | 订单/item/档案 GET；POST returns | M5；delivered 完整退货列表一次申请，原方式或申请前合格礼品卡，由客户选 |
| X | EX-01、ST-03、W | 订单/产品/item/档案 GET；POST exchanges | M5；delivered 同产品可用规格、完整列表一次申请、已有差价方式 |
| C | CA-01/02、ST-01/04、RF-01、W | 订单/档案 GET；POST cancellations | M4；仅普通 pending、允许原因、整单确认、逐笔原路退款 |
| A | AD-01、ST-01/02、W | 订单/档案 GET；PUT order shipping-address | M4；完整地址、指定自有 pending 订单、不连带默认地址 |
| D | AD-01、W | 档案/自有订单 GET；PUT default-shipping-address | M4；完整默认地址、不连带订单地址 |
| P | PY-01/02、ST-01、W | 档案/订单 GET；PUT order payment-method | M4；一种不同已有方式、礼品卡整单足额，后端先扣新款再退旧款 |
| H | HO-01、EN-01/02 | 可信 context.conversation_id；POST transfers（201） | M4；真实受理才宣称转接，受理后结束业务工具流 |
| L | BN-01、ST-01/02/03/04、CF-01 | 必要的受控读取；不调用不存在/不允许的写操作 | M2–M6；能力/状态限制的具体理由，不误报已办理、不以替代动作绕过 |

G/W、金额与状态的适用规则按动作分流；组合 M 不把取消、退货、换货的退款目的地混用。目录计数/选购必须按 U4 验证订单相关范围，不能为匹配公开数字扩大权限。U5 只保留同一旧 item 的副本分别换不同目标的后端匹配边界；常规多件不受此阻塞。没有订单日期/预计送达字段时如实说明未知，不用列表顺序、物流号或本机时间编造事实。

## ID 0

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:13) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:17)

- A000-01 [N1; O] 核对指定自有订单的真实 delivered 状态及两件原商品。
- A000-02 [N1; SEL] 键盘要求有声段落轴、全尺寸、优先 RGB；仅该组合不可用时允许无背光回退，不放宽轴体和尺寸。
- A000-03 [N1; SEL] 温控器改为 Google Home 兼容，同产品且保留其他未要求变化的规格。
- A000-04 [N1,E1; X,M] 收齐两件可行替换、确认差价与已有方式后一次换货；不可回退到未授权规格。

## ID 1

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:27) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:31)

- A001-01 [N1; O] 从指定自有已送达订单定位键盘和温控器。
- A001-02 [N1; SEL] 键盘必须满足有声段落轴、RGB、全尺寸；缺货时保留键盘，不套用 ID 0 的无背光回退。
- A001-03 [N1; SEL] 温控器筛选 Google Home 兼容同产品规格，独立于键盘是否可换。
- A001-04 [N1,E1; X,F,M] 按可行及客户确认的最终范围一次换货，差价按实际清单计算。

## ID 2

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:41) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:45) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:49) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:50)

- A002-01 [N1,B1,B2; SEL] 在有权限且可确定范围的 T 恤目录中计算具体可选规格数并报告；计数单位与原文“种”一致，固定参考数只用于 fixture 断言。
- A002-02 [N1; O,T] 查明清洁机、耳机、智能手表所属自有订单及送达状态，逐单收齐退货清单。
- A002-03 [N1,E1; T,M] 获确认后按单一次开启这三类选定商品退货，合法退款去向；不遗漏计数查询或混入其他商品。

## ID 3

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:56) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:60) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:64) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:65)

- A003-01 [N1,B1,B2; SEL] 依据受控目录报告 T 恤可选规格数，不把结果标签中的商品修改代替查询。
- A003-02 [N1; O,SEL] 枚举全部可操作 pending 订单，仅选原本小码 T 恤；原尺码及 V 领保留，颜色改紫。
- A003-03 [N1; SEL] 聚酯纤维是优先材质，候选不足时澄清而非把偏好擅自当绝对条件或改变保留属性。
- A003-04 [N1,E1; I,M] 各单完整确认后一次规格修改，差价与方式分单记录，不处理非 pending 或非目标 T 恤。

## ID 4

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:71) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:75) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:79) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:80)

- A004-01 [N1,B1,B2; SEL] 从受控数据计算并报告 T 恤可选规格数量。
- A004-02 [N1; O,SEL] 全部普通 pending 订单中所有目标 T 恤改为紫色 S 码，不将原本小码当筛选条件；保留 V 领。
- A004-03 [N1; SEL] 优先聚酯纤维；缺候选时只按客户允许的回退处理。
- A004-04 [N1,E1; I,M] 分单完整清单、差价、支付方式与确认后一次提交，不遗漏原本其他尺码的目标 T 恤。

## ID 5

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:86) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:90)

- A005-01 [N1; SEL] 初始水瓶容量变大；台灯亮度变低，供电偏好电池→USB→AC。
- A005-02 [N1; F] 首次确认处客户缩小为仅台灯，旧双商品提案失效；改口本身不授权立即写入。
- A005-03 [N1; F,T] 若再次确认时客户撤回换货并改退水瓶，建立退货新提案，不保留台灯写授权。
- A005-04 [N1,E1; T,M] 按实际后续消息确认水瓶退货再提交，最终退款合法；不按案例 ID 提前猜最终分支或故意制造多次确认。

## ID 6

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:100) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:104)

- A006-01 [N1; SEL] 初始筛选更大水瓶及更低亮度台灯，台灯供电按电池→USB→AC 排序。
- A006-02 [N1; F] 客户在确认处改为只换台灯，取消水瓶候选及其旧确认。
- A006-03 [N1,E1; X,M] 重新完整确认台灯最终规格、差价和方式后一次换货；水瓶无写入。

## ID 7

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:114) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:118)

- A007-01 [N1; SEL] 初始筛选更大水瓶及更低亮度台灯，供电偏好 AC→电池→USB。
- A007-02 [N1; F] 确认处仅保留台灯，新提案不得含水瓶。
- A007-03 [N1,E1; X,M] 按新清单确认后一次换货，亮度降低及 AC 优先级可从候选轨迹验证。

## ID 8

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:128) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:132)

- A008-01 [N1; SEL] 初始水瓶增容、台灯提高亮度，供电偏好电池→USB→AC。
- A008-02 [N1; F] 确认处用户只换台灯，旧双商品提案失效。
- A008-03 [N1,E1; X,M] 仅执行重新确认的更亮台灯，不能套用 ID 6 的更暗筛选。

## ID 9

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:142) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:146)

- A009-01 [N1; SEL] 初始水瓶增容、台灯提高亮度，供电偏好 AC→电池→USB。
- A009-02 [N1; F] 突然改为仅台灯后更新提案，不把这句话当对旧提案的同意。
- A009-03 [N1,E1; X,M] 新提案获确认后仅台灯换货；保留提高亮度和供电优先次序。

## ID 10

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:156) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:160) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:161)

- A010-01 [N1; O,T] 定位两笔自有订单全部可退商品，分别验证退款方式资格。
- A010-02 [N1; T,L,F] 不将另一订单的付款方式自动当本单合法退款方式；说明限制后等待客户选择本单原方式。
- A010-03 [N1,E1; T,M] 两单分别完整确认并登记退货，明确各单申请状态，不宣称渠道款项已到账。
- A010-04 [N1,E2; H] 只有两笔退货都获确认并核实处理结果后，按投诉意图转人工；愤怒本身不提前中止未完任务。

## ID 11

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:171) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:175)

- A011-01 [N1; O,T] 两笔订单分别收齐全部可退商品，退款资格按本单判断。
- A011-02 [N1; T,L,F] 拒绝不合法的跨单支付方式互换，解释后接受客户明确改选各自原方式。
- A011-03 [N1,E1; T,M] 各单按合法最终方案一次退货；不因骂人自动转人工或吞掉另一笔退货。

## ID 12

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:185) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:189) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:193) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:194)

- A012-01 [N1; O,F] 澄清“与游戏无关”的具体商品范围，不将客户尚未说出的键盘/鼠标排除条件当已知事实。
- A012-02 [N1,B1; T,C,L] 在用户作其他决定前说明相关订单无法退至指定 PayPal；取消与退货去向规则分别核验。
- A012-03 [N1; F,L] 用户拒绝所有替代退款方式时零退货、零取消，不以原路退款擅自满足请求。
- A012-04 [N1,E1,B2; H] 明确限制及客户投诉意图后实际转人工，不伪称 PayPal 退款已安排。

## ID 13

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:200) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:204)

- A013-01 [N1; O,F] 澄清游戏相关性，收齐客户确认的非游戏商品，隐藏排除信息不由 Agent 预知。
- A013-02 [N1; T] 退款优先 PayPal，若不合资格再询问/使用客户允许且合法的信用卡选项。
- A013-03 [N1,E1; T,M] 按真实状态和最终范围登记退货；不强行改去未允许方式或把键盘鼠标也退掉。

## ID 14

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:214) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:218)

- A014-01 [N1; O,F] 澄清“与游戏有关”的商品并验证键盘、鼠标及所在订单，不自动读取客户未披露的括号说明作为授权。
- A014-02 [N1; T,C] 按真实订单状态区分退货与取消，优先合法原支付方式；处理前分别说明范围。
- A014-03 [N1,E1; T,M] 对确认的已送达游戏商品登记退货，保留无关商品；实际 API 状态优于“取消或退回”的笼统措辞。

## ID 15

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:228) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:232)

- A015-01 [N1; O,SEL] 定位 pending 靴子，尺码改 8；询问未明确的材质要求，不自行挑材质。
- A015-02 [N1; SEL] 客户明确不在意防水，可在候选中放宽此属性，其他未放宽属性保留。
- A015-03 [N1,E1; I,M] 差价优先合法已有 PayPal，补款/退款方向按实际价格；完整确认后一次修改。

## ID 16

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:242) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:246) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:247) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:251) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:252)

- A016-01 [N1; O,C] 枚举全部普通 pending 订单，取消原因由客户“不再需要”语义得出，其他状态不得取消。
- A016-02 [N1; O,T] 只退已送达手表，其他已收商品保留，取消与退货分单建提案。
- A016-03 [N1,E1; C] 各 eligible pending 订单获确认后整单取消，逐笔原路退款。
- A016-04 [N1,E2; T] 手表清单与合法去向获确认后登记退货，不将取消授权套给退货。
- A016-05 [N1,B1,B2; M] 汇总实际允许范围的取消退款与手表退货预计额，分项与总额一致；不重复累计同一回执或宣称已到账。

## ID 17

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:258) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:262)

- A017-01 [N1; O,A] 定位指定自有 pending 订单，Suite 是地址行修正，其余完整地址字段从可靠记录保留。
- A017-02 [N1; F] 复述修改后的完整地址并确认，不只回读 Suite、不把初始请求当最终同意。
- A017-03 [N1,E1; A] 仅更新目标订单地址并核实，无默认地址及其他订单写入。

## ID 18

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:272) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:276)

- A018-01 [N1; O,T] 核对损坏办公椅的订单/商品及送达状态，先形成退货方案。
- A018-02 [N1; F] “再考虑”不是确认；用户改为同款换货时旧退货授权失效。
- A018-03 [N1; SEL,X] 查明同款是否可办且可用，不凭材料空白断言同款必可/不可换；仅实际不可行时启用灰色、固定扶手、皮革回退。
- A018-04 [N1,E1; X,M] 按客户确认的合法最终换货方案一次提交；零旧退货写入。

## ID 19

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:286) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:290) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:294) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:295) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:296) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:297)

- A019-01 [N1; O,T,X] 同时保留水瓶退货与宠物床/办公椅换最便宜版本的两项意图，核对是否同单及互斥。
- A019-02 [N1,B1,B3; M,T] 从水瓶原成交记录计算并说明退货可退款额，不以当前目录价代替。
- A019-03 [N1,B2,B4; SEL,M,X] 按同产品可用最便宜规格计算两件换货合计节省金额。
- A019-04 [N1; F] 仅当两项不能并办时比较实际节省，依据客户“最省钱”条件提出一种方案并确认，不先执行一半。
- A019-05 [N1,E1; T] 在原 fixture 的最终选择为退货；实际 Agent 随事实与用户同意处理，不能按 ID 固定选退货。

## ID 20

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:303) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:307)

- A020-01 [N1; O,SEL] 枚举目标订单，各商品同产品选最贵可用规格；鞋码必须保留，客户已放宽的其他功能可变。
- A020-02 [N1; L,F] 某单不允许升级时解释并继续下一个自有订单，不终止全部任务或绕过状态限制。
- A020-03 [N1; I,M] 优先已有足额礼品卡支付差价，不能使用时按客户允许回退到已有 PayPal，不混合支付。
- A020-04 [N1,E1; I] 各 eligible pending 订单收齐清单和确认后一次修改，不把“最贵”放大为跨产品替换。

## ID 21

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:317) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:321) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:325) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:326)

- A021-01 [N1; O,SEL] 解析鞋子目标编号并验证 item、同产品和可用性；不得无校验透传。
- A021-02 [N1; F,I] 最终确认处追加第二件，原单项清单失效，整单重新收齐后才允许写。
- A021-03 [N1; O,SEL] 找不到旧 item 时按用户线索核对是否 product 编号，在本人订单中定位具体实例，不猜造 item。
- A021-04 [N1,E1; I,M] 新完整清单和礼品卡差价获确认后一次提交，不能先改鞋再补第二件。
- A021-05 [N1,B1,B2; M] 核实全部更改后礼品卡实际余额，区分补款/退款及未知结果，不按原单项报价回答。

## ID 22

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:332) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:336) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:337)

- A022-01 [N1; O,F] 校验新地址完整必填字段，查全部可改订单和当前默认地址，保留原默认地址用于可能的后续改回。
- A022-02 [N1,E1; D] 确认后更新默认地址，独立核实结果。
- A022-03 [N1,E2; A] 仅 eligible pending 订单逐单改地址并核实，不能对其他状态承诺已改。
- A022-04 [N1; F,D] 已完成后客户后悔仅将默认地址改回原值，新提案重新确认；已改订单地址保留。

## ID 23

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:347) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:351) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:352)

- A023-01 [N1; O,SEL] 分别定位头盔、另一订单行李箱和新旧烤炉，不把全部商品视为同单同状态。
- A023-02 [N1; SEL] 头盔目标中号红色高透气；行李箱目标黑色软质两件套，套装规格不解释为修改订单数量。
- A023-03 [N1; O,SEL] 从已收到烤炉读取规格，用来筛选刚订购烤炉的同产品目标，不将参考订单也修改。
- A023-04 [N1,E1; X,M] 对已送达目标商品按单换货，清单、差价及方式独立确认。
- A023-05 [N1,E2; I,M] 对待处理烤炉一次商品修改，不能将换货确认或参考商品 ID 跨单套用。

## ID 24

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:362) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:366) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:370) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:371) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:372)

- A024-01 [N1; O,C] 读取烤炉事实准备取消提案；仍需合法取消原因及明确确认。
- A024-02 [N1,E1; F,L] 确认处客户决定保留时撤销提案，取消端点调用为零。
- A024-03 [N1,B1,B2,B3; O,SEL] 查询另一自有订单的两件 T 恤及各自材质，逐件报告，不用同一材质覆盖两件。

## ID 25

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:378) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:382) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:386) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:387)

- A025-01 [N1; O] 用本人订单目的州定位寄错订单，忘记订单号不构成身份验证或他人订单查询许可。
- A025-02 [N1,B1; O] 返回该订单真实履约物流号，多包裹时对应商品说明，不以物流号推断已发货状态。
- A025-03 [N1,B2; T,L] 在其他决定之前明确 amex 是否合资格，原 fixture 不合格时如实说明。
- A025-04 [N1,E1; F,L] 客户拒绝其他目的地后零退货/退款写入，宠物床保留，不擅自原路办理。
- A025-05 [N1; H] 后续实际提出条件式人工要求时按可信上下文转接；INFO 标签不能删掉此需求，也不表示无需工具。

## ID 26

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:393) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:397) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:398)

- A026-01 [N1; O] 按本人订单目的地定位寄往 Texas 的目标，返回真实物流号并澄清任何歧义。
- A026-02 [N1,E1; T,M] 列出除宠物床外的完整可退商品，确认合法方式后按单一次退货。
- A026-03 [E2; H] 公开期望单独要求人工处理：记录实际对话中的人工触发原因与时点，再完成真实转接，不能预设需求段已明确投诉。

## ID 27

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:408) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:412)

- A027-01 [N1; O,T,X] 同时收集水管/背包退货及靴子换货，核对同单的申请互斥。
- A027-02 [N1; SEL] 靴子仅改变防水属性，保留其他规格并验证可用。
- A027-03 [N1,E1; F,X,M] 仅在不能同时办理时按客户优先换货形成最终提案；确认后一次换货，未选退货零写入。

## ID 28

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:422) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:426) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:430) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:431)

- A028-01 [N1; O,T] 收齐滑板、水管、背包、键盘、床及所属订单，客户提出的处理次序与每单完整一次限制一起规划。
- A028-02 [N1; L,C] 待处理订单仅水管取消不受支持，客户明确拒绝整单取消时订单不变。
- A028-03 [N1,E1; T,F] 按客户指定的可行跨单次序确认退货；同一订单不得拆成多次申请，冲突时先解释/澄清。
- A028-04 [N1,B1,B2; M] 汇总实际退货范围预计额，不将未取消水管计入，不重复累计回执。

## ID 29

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:437) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:441) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:445) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:446) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:447) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:448)

- A029-01 [N1; SEL] 对滑板筛选更短、竹制同产品可用候选，不先按价格忽略长度和材质。
- A029-02 [N1,B1,B2,B3,B4; SEL,M] 多个选项时列出全部合资格选项及价格，再依据客户选择最贵；数字标记分别对应列表项。
- A029-03 [N1; O,SEL,F] 已收水管目标从本人 pending 订单中的水管规格核实；客户指出候选不对时继续查实，不预知隐藏目标编号。
- A029-04 [N1,E1; X,M,L] 两项收齐、确认后按单换货；参考 pending 订单和任何取消端点均无写入。

## ID 30

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:454) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:458) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:459) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:463)

- A030-01 [N1,B1; O] 先查询损坏平板所在自有订单的真实物流号，不能因有退货目标漏掉查询。
- A030-02 [N1; SEL,F,T,X] 平板优先可办同款换货，不可行时提出退货；等待实际事实和用户最终确认。
- A030-03 [N1,E1; T] fixture 中走平板退货，同时收集运动鞋退货，按所属订单完整申请，不遗漏最后一项。
- A030-04 [N1,E2; C,F] 只有平板最终退货时才处理配套充电器整单取消，核实状态/原因并独立确认。

## ID 31

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:469) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:473) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:474) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:478)

- A031-01 [N1,B1; O] 返回丢失平板订单的真实物流号；区分丢失申诉、退货和重新下单能力，不假造补发/赔付。
- A031-02 [N1; L,F] 无可证实的丢失赔付或重新下单权限时说明限制，不假称已经退款或重购。
- A031-03 [N1,E1; C] 用户接受不可行后的充电器取消须有合法原因和整单确认；靴子取消但保留水壶的部分取消不支持时该订单零写入。
- A031-04 [N1,E2; T] 运动鞋独立收齐确认后登记退货，不因其他请求失败吞掉此任务。

## ID 32

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:484) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:488) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:489) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:493)

- A032-01 [N1,B1; O] 查询丢失平板订单物流号，核实实际账户和订单。
- A032-02 [N1; L] 赔付/重下单不属于可见权限时说明，不编造已退款或重新购买。
- A032-03 [N1,E1; C,F] 按客户回退取消配套充电器，并收齐靴子与水壶所属订单的整单取消；每单核实允许原因、状态及确认。
- A032-04 [N1,E2; T] 对运动鞋登记独立退货；与 ID 31 不同，不能把靴子/水壶整单取消请求误判成仍要求保留水壶。

## ID 33

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:499) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:503) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:507) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:508)

- A033-01 [N1; O,F] 定位本人办公/徒步混合订单，澄清未记清的三件办公用品，不靠名称猜全部商品。
- A033-02 [N1,B1,B2; M] 算出选定办公用品的潜在原路退款总额并说明是方案金额，不冒称已取消/退款。
- A033-03 [N1; L,F] 部分取消不支持时遵循客户“保留订单”的选择，零整单取消、零擅自退货。
- A033-04 [N1,E1; O,D] 从本人订单取得父母在 Seattle 的完整地址，复述确认后仅更新默认地址，不更改订单。

## ID 34

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:514) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:518) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:522) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:523)

- A034-01 [N1; O,F] 定位办公与徒步混合订单，澄清要处理的办公商品，保留徒步范围。
- A034-02 [N1,B1,B2; M] 计算选定办公商品潜在退款额，明确是方案说明，不表示已退。
- A034-03 [N1; L] 部分取消不支持时保留订单，不以整单取消替代；“之后再退货”不是现在退货许可。
- A034-04 [N1,E1; A,F] 收齐 NYC 完整地址，确认后仅修改 eligible pending 订单地址，不套用 ID 33 的默认地址目标。

## ID 35

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:529) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:533) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:534)

- A035-01 [N1; O,SEL] 比较本人音箱的原成交价及防水属性，定位较贵且不防水的一件，不退另一件。
- A035-02 [N1,E1; T,M] 对选定音箱完整确认后登记退货，退款去向独立合法。
- A035-03 [N1; SEL] 另一订单笔记本由 17 英寸改 13 英寸，先保持其他规格找对应可用款。
- A035-04 [N1; SEL,F] 无完全对应款时列出合资格 13 英寸选项；i5 优于 i7，银/黑为颜色偏好，未定义两者优先级时不臆定。
- A035-05 [N1,E2; I,M] 最终笔记本规格与差价确认后一次修改，音箱退货确认不能跨单复用。

## ID 36

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:544) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:548) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:552) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:553) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:554) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:555)

- A036-01 [N1; P,L] 分摊两张卡的付款不受支持，不能用新增支付请求模拟分期或混合扣款。
- A036-02 [N1,B1,B2,B3,B4; O,M] 按订单成交价识别最贵商品，并报告商品名称和价格；重复标记分别关联同一查询事实。
- A036-03 [N1; L] 单件取消不支持，不能直接取消整单或减少数量。
- A036-04 [N1; SEL,M,F] 对全部商品找各自同产品最便宜可用款，计算修改后总额是否满足客户第一种预算上限。
- A036-05 [N1,E1; I] 仅可达预算且获完整确认时一次修改；不可行才讨论整单取消及合法原因，不代客户重新下单。

## ID 37

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:561) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:565) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:569) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:570) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:571) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:572)

- A037-01 [N1; P,L] 解释两卡分摊限制，不尝试混合付款。
- A037-02 [N1,B1,B2,B3,B4; O,M] 查明最贵商品名称和实际成交价，不仅答复订单总额。
- A037-03 [N1; L] 不支持只取消最贵一件，保留订单直至客户确定合法替代方案。
- A037-04 [N1; SEL,M] 全部商品各自选同产品最便宜可用款，按本例较高预算上限判定可行性；不能复用 ID 36 的固定阈值。
- A037-05 [N1,E1; I,F] 客户确认完整清单及金额后一次修改；若不可达才收集整单取消原因并确认。

## ID 38

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:578) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:582) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:586) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:587) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:588) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:589)

- A038-01 [N1; P,L] 解释混合付款和部分取消均不支持，零违规写入。
- A038-02 [N1,B1,B2,B3,B4; O,M] 说明最贵商品及成交价格，名称和金额分别可验证。
- A038-03 [N1; SEL,M] 计算各商品最便宜可用同产品规格的总额，与本例更低预算比较，不能先修改再发现超预算。
- A038-04 [N1,E1; C,F] 在原 fixture 中不可达预算，按用户最终选择收集允许原因并确认后整单取消；不从“额度不足”自动推断取消原因，也不自动重下单。

## ID 39

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:595) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:599) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:603) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:604)

- A039-01 [N1; O] 从本人最近订单确认新 Phoenix 地址；无可靠排序字段时澄清“最近”，不读取他人记录。
- A039-02 [N1,E1; D,F] 核对完整新地址并获确认，仅改用户默认地址。
- A039-03 [N1,B1,B2; SEL,M] 在合权限范围找有货的最低价 T 恤并报告实际价格，不把缺货款纳入最低价。
- A039-04 [N1; L] 解释客服不能代下新订单，查询便宜商品不等于购买授权或新增订单。

## ID 40

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:610) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:614) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:618) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:619) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:620) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:621)

- A040-01 [N1,B1,B3; O,M] 从已验证档案读取礼品卡余额，区分余额与本次可用额度。
- A040-02 [N1,B2,B4; O,P] 从最新自有订单 payments 和方式详情识别实际信用卡品牌，不按用户列举顺序猜测。
- A040-03 [N1; P,L,M] 礼品卡只有覆盖整单且为已有不同方式才可切换，不能仅抵扣余额或与卡混合付款。
- A040-04 [N1,E1; P,F] 礼品卡不合格时按客户回退选择已有 Visa，完整确认后切换并核实原款退款与 pending 状态。

## ID 41

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:627) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:631) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:632) / [E3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:633)

- A041-01 [N1; O,F] 用户账号名不是验证凭据；同时保留拼图修改与两单/档案地址纠正任务，先核对地址是否有误。
- A041-02 [N1; SEL,M] 拼图优先最低难度、最少片数同产品可用款，差价通过已有 PayPal；多目标排序不明确时澄清。
- A041-03 [N1,E1; A] 两笔 eligible pending 订单各自完整地址确认后更正，不把一个回执当两单成功。
- A041-04 [N1,E2; D] 档案默认地址独立确认并修改，不能因订单地址更新自动假设已同步。
- A041-05 [N1,E3; I,F] 虽用户先提拼图，先完成受其锁单影响的地址，再一次提交拼图修改；差价与清单确认完整。

## ID 42

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:643) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:647) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:648) / [E3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:649)

- A042-01 [N1; O,F] 账号名不替代验证，先检查档案及全部自有订单地址，仅错误且可改的目标进入提案。
- A042-02 [N1,E1; A] 各可改订单确认完整新地址后更正，其他状态解释限制。
- A042-03 [N1,E2; D] 档案地址独立确认后更新，无错记录不为凑结果重复写入。
- A042-04 [N1; O,SEL] 查看拼图真实状态/履约；在可修改时选择最低难度和最少片数，不能以未提供 shipped 字段当 false。
- A042-05 [N1,E3; I,M] 使用客户默认已有 PayPal，地址先于锁单商品修改，完整清单确认后一次提交。

## ID 43

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:659) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:663) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:667) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:668) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:669) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:670) / [B5](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:671) / [B6](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:672) / [B7](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:673) / [B8](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:674) / [B9](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:675) / [B10](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:676)

- A043-01 [N1,B1,B4; O] 从女儿相关自有订单履约读取真实物流号，并按后台事实答复运输/送达状态，不根据“尚未收到”造状态。
- A043-02 [N1,B2,B5,B6,B7,B8,B9; O] 报告目标订单完整配送地址，包含街道、Suite、城市、州和邮编；无遗漏或串到档案旧地址。
- A043-03 [N1,B3,B10; O,SEL] 读取订单中平板对应 item 的存储容量并报告，不把另一款平板规格套入。
- A043-04 [N1,E1; D,F] 将该订单中的女儿完整地址复述确认后设为默认地址，不更改已发订单。

## ID 44

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:682) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:686) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:690) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:691)

- A044-01 [N1; O,SEL] 定位指定 pending 订单台灯，从同产品有货规格中选最低当前价。
- A044-02 [N1; I,M] 比较原成交价与目标价，确认已有礼品卡作为差价去向，不套用取消原路退款限制。
- A044-03 [N1,E1; I,F] 完整清单、差价和方式获确认后一次修改，订单进入 items modified。
- A044-04 [N1,B1,B2; M] 报告真实节省/退回金额及去向，不能将整单金额当台灯差价或称所有渠道即时到账。

## ID 45

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:697) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:701) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:705) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:706)

- A045-01 [N1; O,F] 缺 W 前缀时按本人订单引用与客户后续线索消歧，不任意尝试邻近订单。
- A045-02 [N1; SEL] 扫地机改桶式吸尘器必须属于同产品系列且可用；不能仅因客户意愿跨 product。
- A045-03 [N1; F,SEL] 多选项时才收集客户提出的无尘袋偏好；只有单选项时不预知隐藏偏好或无限追问。
- A045-04 [N1,E1; X,M] 说明差价并确认合法已有礼品卡去向后一次换货，不默认套原付款方式。
- A045-05 [B1,B2; M] 实际差价与来源金额断言对应；参考数字本身不证明付款/退款方向，方向从价格事实核验。

## ID 46

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:712) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:716) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:720) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:721) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:722) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:723)

- A046-01 [N1; O,F] 客户先错号再更正数字/前缀时仅从本人订单消歧，不对第一猜测直接写入。
- A046-02 [N1; O,SEL,F] 查明空气净化器和客户明确的扫地机器人，收齐同单完整退货列表。
- A046-03 [N1; M,L] 面对三天内退款要求解释真实渠道时效，不承诺缩短到客户期限。
- A046-04 [N1,E1; T] 选定商品和合法原路/礼品卡去向完整确认后一次退货。
- A046-05 [N1,B1,B3; M] 计算所选商品原成交退款总额，回应用户预计额而非只报已退状态。
- A046-06 [N1,B2,B4; O,M] 办理后计算同单保留商品的原成交合计，与已申请退款范围分开，不按新目录价重估。

## ID 47

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:729) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:733) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:737) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:738) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:739) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:740)

- A047-01 [N1; O,F] 核对错号、更正号与缺 W 线索，全部限定本人订单引用。
- A047-02 [N1; O,SEL] 净化器加客户澄清的桶式吸尘器，不能复用 ID 46 的扫地机器人选择。
- A047-03 [N1; M,L] 明确三天到账无法保证，按实际退款渠道说明政策时效。
- A047-04 [N1,E1; T,F] 完整退货列表与合法去向确认后一次申请，不拆同单两次办理。
- A047-05 [N1,B1,B3; M] 报告净化器和桶式吸尘器原成交退款合计。
- A047-06 [N1,B2,B4; O,M] 办理后回答剩余商品原成交合计，不能使用 ID 46 的固定合计。

## ID 48

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:746) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:750)

- A048-01 [N1; O,T] 查明已收空气净化器的自有订单、状态和原方式，收齐退货提案。
- A048-02 [N1,E1; T,F,M] 明确确认后申请净化器退货，退款回合法原方式，不夸称已到账。
- A048-03 [N1; L,F] 最后对吸尘器仅询问可否退货且未决定，只有查询/解释，零吸尘器退货写入；已有单次申请限制如实说明。

## ID 49

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:760) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:764)

- A049-01 [N1; O,SEL] 定位误选 IPX7 耳机及本人同单其他耳机，实查参照的防水等级。
- A049-02 [N1; SEL,F] 从实际用户交流澄清参照对象，“实际想要最便宜”未说出时不预知；收集完整选择后同产品匹配。
- A049-03 [N1,E1; X,M] 依最终明确规格和差价确认后一次换货，不能把其他耳机也修改或越过确认。

## ID 50

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:774) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:778) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:782) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:783)

- A050-01 [N1; O,F] 客户只描述撤销取消时定位本人已取消订单，缺商品名不要求客户提供非必要猜测。
- A050-02 [N1,B1; L] 明确已取消不可恢复，也不能承诺加急送达、重新下单或后台已安排撤销。
- A050-03 [N1,E1,B2; H] 客户坚持人工例外处理时真实转接，说明已知限制，不保证人工一定能破例。

## ID 51

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:789) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:793)

- A051-01 [N1; O,F] 猜测订单号不作为事实，从本人订单与数码相机描述消歧；核对实际状态而非只信“收到”。
- A051-02 [N1; T,M] 将相机完整范围及合法原退款方式形成提案，不因坚持请求省略确认。
- A051-03 [N1,E1; T] 仅真实已送达目标相机可一次申请退货，错误订单无写入。

## ID 52

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:803) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:807)

- A052-01 [N1; O,SEL] 读取原相机全部规格，在同产品可用候选中只变焦可变，其他规格保持。
- A052-02 [N1; SEL] 在严格保留属性的候选内最大化变焦，价格无上限不代表其他规格可变。
- A052-03 [N1,E1; X,M,F] 按真实差价、已有 PayPal 补款和客户确认登记换货；“尽快”不省略完整确认或保证送达日期。

## ID 53

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:817) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:821)

- A053-01 [N1; O,T] 核实损坏自行车的本人订单及 delivered，不增加材料未要求的拒绝理由。
- A053-02 [N1,E1; T,F] 确认自行车完整退货范围和实际原信用卡，登记一次退货。
- A053-03 [N1; M,L] 说明原成交退款金额和卡渠道时效，客户催促不改变政策、不把申请当退款到账。

## ID 54

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:831) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:835) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:836) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:840) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:841)

- A054-01 [N1; O] 枚举各自有订单状态及商品，分别判断可取消/退货范围，不把“能处理”理解为全状态都可写。
- A054-02 [N1; SEL,X,M] 靴子必须保留尺码材质，只在同产品更便宜可用款存在时讨论换货节省；无候选不退靴子。
- A054-03 [N1; L,F] “保留该订单并取消其他商品”的部分取消不支持时先澄清，不能删掉靴子或取消整单。
- A054-04 [N1,E1; C] 其他符合条件且有允许原因的 pending 整单确认后取消，不能将经济困难自动归成允许原因。
- A054-05 [N1,E2; T] 其余客户选定已送达商品确认后退货，保留靴子及不合政策部分。
- A054-06 [N1,B1,B2; M] 汇总合法最终处理范围退款/节省，分清可能靴子换货方案与实际已提交结果。

## ID 55

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:847) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:851) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:852)

- A055-01 [N1; O] 先列出本人各订单商品与真实状态，满足客户记不清商品的查询需要。
- A055-02 [N1,E1; C,F] 按客户顺序先取消真正 eligible pending 订单，询问允许原因并确认；未送达但 processed 不可取消。
- A055-03 [N1,E2; T,F,M] 再收齐每单已送达全部退货商品和合法方式，确认后分别一次申请，不把展示清单当已确认。

## ID 56

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:862) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:866)

- A056-01 [N1; O,L] 查询净化器真实订单/履约，送达时间仅在数据支持时答复，不能凭物流号造预计日。
- A056-02 [N1; L,F] 单件取消不支持，不把该请求自动扩大为整单取消。
- A056-03 [N1; SEL,M,I] 可修改时找同产品有货最便宜净化器，用档案查已有礼品卡并核对差价去向。
- A056-04 [N1,E1; I,F] 仅修改和礼品卡去向均可行且确认后一次提交；任一不满足时遵从零操作条件。

## ID 57

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:876) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:880) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:884) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:885)

- A057-01 [N1; O,L] 核实目标订单状态/履约，如无真实预计送达数据说明未知。
- A057-02 [N1,B1; L] 明确只能整单取消，不能单独取消净化器。
- A057-03 [N1,B2; C,M,L] 核实原付款信用卡并说明取消只能逐笔原路退款，不能改礼品卡。
- A057-04 [N1,E1; F,L] 客户把礼品卡退款设为整单取消前提，前提不成立则零取消、订单保留，不把早期意向当授权。

## ID 58

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:891) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:895)

- A058-01 [N1; O,SEL] 已送达咖啡机保留容量和类型，压力顺序 8→9→7 bar；三者均不可用时该件不换。
- A058-02 [N1; SEL] 同产品笔记本筛选 i7 或更高、最低价，客户放宽其余规格；处理器等级需可解释比较而非字符串排序。
- A058-03 [N1; X,M,F] 有补款先告知，优先足额已有礼品卡，不可用才按客户选择已有信用卡；情绪不替代确认。
- A058-04 [N1,E1; X] 两件最终范围收齐，按所属订单完整确认后一次换货；不把咖啡机缺候选变成整单放弃。

## ID 59

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:905) / [N2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:907) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:911) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:912) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:916) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:917) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:918) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:919)

- A059-01 [N1; O] 分别读取新旧两订单真实状态，解释实际差异；没有日期/队列事实时不推断为何等待较久。
- A059-02 [N1; L,F] 五天内处理保证无数据/能力支持时不能承诺；客户据此选择取消仍须允许原因，物流抱怨不能强行归类。
- A059-03 [N1,E1; C] 较早订单如 eligible pending 且原因/完整确认齐备才取消，不操作另一订单。
- A059-04 [N1,B1,B3; M] 计算被取消订单的真实退款额，并说明是取消原路退款而非延误赔偿。
- A059-05 [N2,E2; A,F] 对另一指定订单收齐客户新城市的完整地址，确认后更新核实；不保证未经提供的送达日期。
- A059-06 [N2,B2,B4; O,M] 地址更新后核对该单实际总额；地址变更本身不凭空改变商品价格。

## ID 60

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:925) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:929) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:933) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:934)

- A060-01 [N1; O,SEL] 定位指定 pending 无线耳机，颜色蓝，当前目标价须不高于原成交价。
- A060-02 [N1; F,SEL] 仅多候选时接收用户提出的不防水偏好；不预先将隐藏条件作为硬约束。
- A060-03 [N1,B1,B2; M] 明确报告目标耳机价格并验证不贵于原款，不只声称符合预算。
- A060-04 [N1,E1; I,F] 首条消息详情齐备且催促也不代替完整提案后的确认，最终清单一次修改。

## ID 61

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:940) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:944)

- A061-01 [N1; O,SEL] 指定 pending 耳机改蓝，其他未放宽规格保留；目标价不高于原成交价。
- A061-02 [N1; M,F] 解释候选实际价格和差价，首条完整请求仍须完整提案及后续同意。
- A061-03 [N1,E1; I] 确认最终合法规格后一次修改，不沿用 ID 60 未由此客户提出的不防水偏好。

## ID 62

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:954) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:958) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:962) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:963) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:964) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:965)

- A062-01 [N1; L] 诗歌猜谜不产生零售工具调用，简洁回到订单诉求；无独立来源不把所有闲聊都当强制违规。
- A062-02 [N1,B1,B3; O,M] 查询本人所购音箱原成交价，不用目录现价代替。
- A062-03 [N1,B2,B4; O,SEL] 查询正确 item 的续航时长并报告，不能用价格推测续航。
- A062-04 [N1; L,SEL,F] 客户价高条件成立后解释部分取消/加商品不支持；在受控目录核对较低预算候选，不能自行新增或减量。
- A062-05 [N1,E1; L,M] 原 fixture 无符合预算候选且拒绝整单取消，零业务写入；总额保持原订单事实，未来退货意向不现在执行。

## ID 63

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:971) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:975) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:979) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:980) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:981) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:982) / [B5](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:983) / [B6](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:984)

- A063-01 [N1; L] 不用诗歌猜谜触发账户或订单写入，回到客户实际零售需求。
- A063-02 [N1,B1,B4; O,M] 报告原音箱成交价格，核对高价条件。
- A063-03 [N1,B2,B5; O,SEL] 报告原音箱续航，查询不可因后续修改漏答。
- A063-04 [N1; SEL,L,F] 本例预算较宽可找到同产品便宜规格；解释“取消旧件加新件”不支持，澄清为数量不变的合法规格替换并确认。
- A063-05 [N1,E1; I] 完整清单一次修改，零整单取消、零新增商品，不因期望 ITEM_MOD 跳过上述澄清。
- A063-06 [N1,B3,B6; O,M] 成功后读取并报告新订单真实总额，不能把差价当总额或使用未执行报价。

## ID 64

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:990) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:994) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:995)

- A064-01 [N1; O] 查相机所在自有订单及真实状态，区分待处理修改和已送达换货，不能同单调用两个写端点。
- A064-02 [N1; SEL,M] 在同产品可用防水款内以原成交价为预算上限，先最大化分辨率，再在最高分辨率并列款中选最低价。
- A064-03 [N1; SEL,F] 作决定前列出符合条件的选项及价格，不先写后解释筛选。
- A064-04 [N1,E1; X] 已送达目标按完整确认登记换货，保持各单结果独立。
- A064-05 [N1,E2; I] 普通 pending 目标按完整清单确认一次修改；用数据驱动状态分流，不从“双标签”推断单件要执行两次。

## ID 65

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1005) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1009) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1013)

- A065-01 [N1; O,SEL] 核实最近自有订单书架和价格，客户按价格挑相机的意图不等于同产品资格。
- A065-02 [N1,E1,B1; L] 明确书架不能跨产品换相机，零换货/商品修改；不为满足价格偏好绕过权限或声称已安排。

## ID 66

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1019) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1023)

- A066-01 [N1; O,L] 行李箱换外套属于跨产品修改，明确限制，不以同价或用户授权绕过。
- A066-02 [N1; O,T,F] 若客户回退单件退货，依据真实状态判定可否；pending 不能因客户叫退货而直接调用 returns。
- A066-03 [N1,E1; C,F] 前两项不可行后依据客户最终整单取消意图收集允许原因、完整复述并确认，再执行取消；不能直接把“遇到问题”当取消原因。

## ID 67

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1033) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1037) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1041) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1042)

- A067-01 [N1; O,F] 从本人订单事实定位最近订单，日期记不清时用可靠字段或澄清，不按引用列表顺序臆断最近。
- A067-02 [N1,B1,B2; O,M] 核对订单成交与 payments，答复实际已付总额，不能将退款记录累加为付款。
- A067-03 [E1; L] 纯查询零业务写入，不凭查询意图创建取消或更改支付提案。

## ID 68

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1048) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1052) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1056) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1057)

- A068-01 [N1; O,F] 独立核对本人最近订单，日期不明不降低身份/归属要求；与 ID 67 相似不代表共享会话。
- A068-02 [N1,B1,B2; O,M] 从该会话真实订单和支付记录报告已付总额，不沿用另一案例缓存或参考金额。
- A068-03 [E1; L] 纯金额查询无业务变更，读取失败不猜造金额。

## ID 69

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1063) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1067)

- A069-01 [N1; O,F] 从本人商品和模糊日期线索定位笔记本订单，客户说已收到不能覆盖 API 状态。
- A069-02 [N1; T,L] 按真实状态判断退货资格，未 delivered 不开退货；不擅加未发布的日期退货窗口。
- A069-03 [N1,E1; C,F] fixture 中走取消回退，必须询问允许原因；“别处更便宜”不能自动映射 no longer needed，须待客户表达合法最终原因及确认。

## ID 70

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1077) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1081) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1085) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1086)

- A070-01 [N1; O,SEL] 头盔硬条件中号及高透气，同产品可用；多颜色时蓝色为偏好，未明的“那个”先澄清对象。
- A070-02 [N1; X,M] 补差价优先合法原支付方式，读取真实目标价格，不把偏好当无需询问。
- A070-03 [N1,B1,B2; M] 报告当次实际需要补付的差价与方向，不把目标全价当应付金额。
- A070-04 [N1,E1; X,F] 完整规格、方式和金额确认后一次换货，不因催促跳过确认。

## ID 71

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1092) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1096) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1097)

- A071-01 [N1; O,A] 从本人档案读 Charlotte 默认完整地址，定位误填儿子地址的目标单，不改默认地址。
- A071-02 [N1; SEL] 初始台灯黑色、背包中号聚酯；背包多颜色时灰色优先，不擅改未请求属性。
- A071-03 [N1; F,I,M] 用户起初礼品卡，确认处改 PayPal 且仅背包，旧清单和旧方式授权同时失效。
- A071-04 [N1,E1; A] 独立确认后先完成仍可改的订单地址，不能先商品锁单。
- A071-05 [N1,E2; I,F] 收齐最新仅背包清单与 PayPal 差价并确认后一次修改，台灯无变更。

## ID 72

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1107) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1111) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1112)

- A072-01 [N1; O,A] 查询本人默认地址作为订单新地址，客户拒绝直接说地址时不猜地址、不改档案。
- A072-02 [N1; SEL] 初始台灯黑、背包中号聚酯且优先灰，查同产品库存和实际差价。
- A072-03 [N1; F,I] 最终改为仅背包与 PayPal，重新确认清单、方式和金额，旧授权不继续有效。
- A072-04 [N1,E1; A] 用户先说商品后说地址，执行仍按依赖先地址，不能按句子顺序先锁单。
- A072-05 [N1,E2; I] 一次提交最终背包清单并核实，台灯不改，默认地址不改。

## ID 73

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1122) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1126)

- A073-01 [N1; O,F] 查询最近目标订单完整商品，明确保留咖啡机，收齐其他实例而非去重名称。
- A073-02 [N1,E1; T,M] 仅已送达可退范围及合法方式确认后一次退货，咖啡机留在订单；不把全退意图变整单取消。

## ID 74

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1136) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1140) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1141)

- A074-01 [N1; O,SEL] 定位笔记本，硬条件 i9；存在多存储时偏好 256GB SSD，多颜色时偏好银色。
- A074-02 [N1; O,C,F] 用本人订单商品数量等事实定位另一个五件 pending 订单，歧义先澄清，取消原因为客户不再需要。
- A074-03 [N1,E1; C] 完整确认后取消目标整单，不将笔记本单也取消。
- A074-04 [N1,E2; I,M] 笔记本单清单、规格、差价与方式独立确认后一次修改，两项结果分别核实。

## ID 75

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1151) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1155)

- A075-01 [N1; O,SEL] 用订单及原耳机蓝色/8小时/IPX4 定位具体实例，不能匹配另一件近似耳机。
- A075-02 [N1; SEL] 新款黑色/4小时/不防水必须同时满足，同产品且有货，不能仅换颜色。
- A075-03 [N1,E1; X,M,F] 核对差价和已有方式，完整确认后一次换货并核实所有目标属性。

## ID 76

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1165) / [N2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1166) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1170) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1174) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1175)

- A076-01 [N1; O,L,F] 抓绒外套单件移除不支持，客户允许整单取消后以误下单原因建立完整提案。
- A076-02 [N1; SEL] 滑板目标枫木、34 英寸、带图案同产品可用款，按真实状态判断是否能修改。
- A076-03 [N1,E1; C,F] 滑板不可改时客户允许按不再需要取消；先辨别是否与外套同单，整单取消只执行一次，不再对取消单改商品。
- A076-04 [N2,B1,B2; O,M] 汇总本人以往订单全部烤炉原成交价格，保留重复件次数；不以取消当前订单为由漏答历史查询。

## ID 77

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1181) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1185)

- A077-01 [N1; O,SEL] 核对已收香水同产品规格，筛选可用的最大容量，未放宽香调等属性保留。
- A077-02 [N1; L] 客户已试用的事实不自行变成材料未定义的拒绝规则，也不编造一定能受理的后台事实。
- A077-03 [N1,E1; X,M,F] 最大容量合法候选、差价与方式获确认后一次换货，申请不表示新货已发出。

## ID 78

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1195) / [N2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1196) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1200) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1201) / [E3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1202)

- A078-01 [N1,N2; O] 将两项同单修改和另一单取消分开，来源地址订单也需自有；“几项要求”不能丢掉最后任务。
- A078-02 [N2,E1; A,F] 从指定参考自有订单读取完整地址，确认后先改目标 pending 订单地址，不改参考单。
- A078-03 [N2; SEL] 化妆套装从浅肤色/专业套装/Brand B 改深肤色/Brand A，专业 kit size 未要求改则保留；确认同 product。
- A078-04 [N2,E2; I,M] 地址已处理后对目标单完整清单、差价确认并一次修改。
- A078-05 [N2,E3; C,F] 另一目标单以误下单原因整单确认后取消，不能把前一单确认当取消授权。

## ID 79

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1212) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1216)

- A079-01 [N1; O,SEL] 从本人另一个新订单读取 1000ml 水瓶的真实 item/颜色/材质，作为 500ml 替换参考。
- A079-02 [N1; SEL] 优先完全相同规格；不可用时只放宽材质，容量 1L 和参考颜色仍是硬条件。
- A079-03 [N1,E1; I,M,F] 仅 pending 目标水瓶完整确认后一次修改，参考订单保留；缺候选不自行放宽颜色。

## ID 80

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1226) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1230)

- A080-01 [N1; O,SEL] 定位蓝/S/聚酯/V 领的原 T 恤，目标红/XXL/棉/圆领全部核对，同产品且有货。
- A080-02 [N1; X,M] 礼品卡来自已有方式，差价正负据价格算，正差价须足额；不混合付款。
- A080-03 [N1,E1; X,F] 完整目标清单和金额获确认后一次换货，不漏领型/材质变化。

## ID 81

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1240) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1244)

- A081-01 [N1; O,F] 定位靴子、手表、键盘、充电器、夹克、跑鞋所属本人订单，并说明整单取消会包含哪些其他商品。
- A081-02 [N1; L,C] 单件取消不支持，但客户接受整单回退；原因不再需要，仍须确认完整整单范围。
- A081-03 [N1,E1; C,M] 各 eligible pending 单确认后只取消一次，退款逐笔原路，不自动将 delivered 商品也取消。

## ID 82

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1254) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1258)

- A082-01 [N1; O,M] 比较两台平板原成交价，明确较贵的一台及其订单，不能按当前价排序。
- A082-02 [N1; T,F] 检查信用卡退款资格，不合格时客户改变范围为该单全部商品且改 GC，旧单件方案失效。
- A082-03 [N1,E1; T,M] 资格可证实的已有礼品卡与完整全部商品清单确认后一次申请；回退触发前不擅自全退。

## ID 83

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1268) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1272)

- A083-01 [N1; O,M] 从原成交价定位较贵平板，另一台与其他商品不在初始退货范围。
- A083-02 [N1; T,F] 信用卡不合资格时仅改变去向到合格已有礼品卡，不套用 ID 82 的全单扩大范围。
- A083-03 [N1,E1; T,M] 重新完整确认较贵平板与合法去向后一次退货，其他商品保留。

## ID 84

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1282) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1286)

- A084-01 [N1; O,M,T] 初始以原成交价选较便宜平板和信用卡，先核验资格、不得提前申请。
- A084-02 [N1; F] 确认处改较贵平板且改礼品卡，商品范围、金额与方式旧确认一并失效。
- A084-03 [N1,E1; T,M] 重新计算较贵款退款，核实申请前合格礼品卡，确认新完整提案后一次退货。

## ID 85

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1296) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1300)

- A085-01 [N1; O,SEL] 查本人 pending 抓绒外套，目标大号、红色、半拉链同时满足，其他属性保留。
- A085-02 [N1; M,F] 明确差价与已有方式，收齐整单清单并完成最后补充询问及确认。
- A085-03 [N1,E1; I] 一次修改并核实目标规格，不以用户一句“想换”省略确认。

## ID 86

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1310) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1314) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1315)

- A086-01 [N1; O,SEL] 抓绒外套目标红色半拉链，未要求变尺码则保留；不能套用 ID 85 的大号。
- A086-02 [N1; O,F] 从本人订单查 Washington DC 完整地址，多个候选时澄清，不能要求用户必须再输入可验证已有地址。
- A086-03 [N1,E1; I,M] 外套清单、差价与方式获确认后一次商品修改。
- A086-04 [N1,E2; D] 默认地址独立完整确认后更新，商品修改锁单不影响该客户档案动作；不连带订单地址。

## ID 87

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1325) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1329) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1330)

- A087-01 [N1; O] 从本人订单定位 Washington DC 参考地址，枚举全部普通 pending 目标单。
- A087-02 [N1,E1; A,F] 全部目标订单逐单确认完整地址后更新核实，不修改不可改状态或漏单。
- A087-03 [N1,E2; D,F] 档案默认地址独立更新核实，不能用一个订单回执宣称所有地址已改。

## ID 88

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1340) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1344)

- A088-01 [N1; O,SEL] 书架改 4 英尺，颜色材质保留，按同产品库存事实判断可行性。
- A088-02 [N1; F,L] 无货才启用整单取消回退，不以商品读失败等同缺货，也不自动帮用户重新购买。
- A088-03 [N1,E1; C] 实际询问后取得客户误下单原因，完整确认再取消；隐藏回答不由 Agent 预知。

## ID 89

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1354) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1358) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1362) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1363) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1364) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1365) / [B5](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1366) / [B6](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1367) / [B7](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1368) / [B8](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1369)

- A089-01 [N1,B1,B5; SEL,M] 在合权限同产品有货规格中找最低价机械键盘，并报告其真实价格。
- A089-02 [N1,B2,B3,B4,B6,B7,B8; SEL] 逐项说明该最低价键盘轴体、背光及尺寸，不只给价格或混入另一候选属性。
- A089-03 [N1; F,X,T] 与客户阈值严格比较：低于才提出换货，否则提出当前键盘退货，临界等于不算低于。
- A089-04 [N1,E1; T,M] 原 fixture 走退货，确认清单与合法方式后一次申请；Agent 不能按固定参考价直接选分支。

## ID 90

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1375) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1379)

- A090-01 [N1; O,SEL] 先查所购相机是否已支持 10 倍变焦，已满足时不无故改商品。
- A090-02 [N1; SEL,M] 不满足时找同产品 10 倍候选，其他规格保留并核对可用性与价格上限。
- A090-03 [N1; C,F] 缺货分支原因不再需要；有货但超过预算分支原因误下单，两原因分别来自客户，不互换或强行归类。
- A090-04 [N1,E1; C] 最终取消必须普通 pending 且完整确认；等于预算不误判超额，不自动承诺替换成功。

## ID 91

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1389) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1393) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1394)

- A091-01 [N1; O,T] 保留两块滑板的次数，初始信用卡退货去向须合资格。
- A091-02 [N1; F,T] 确认处客户尚未同意而追加智能手表，更新清单并确认，旧滑板提案不得提交。
- A091-03 [N1; F,X,SEL] 电子阅读器从退货意向转同款换货；仅不可办同款时才改 32GB，澄清最终单一意图。
- A091-04 [N1; O,F,L] 查商品实际所属订单，退/换若同单互斥先澄清选择，不凭双标签假定两端点可连办。
- A091-05 [N1,E1; T] 最终退货单收齐滑板、手表等确认范围后各单一次申请，合法方式独立核验。
- A091-06 [N1,E2; X,M] 另一可行换货单最终规格与差价确认后申请；不同时退同一电子阅读器。

## ID 92

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1404) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1408)

- A092-01 [N1; O,T] 定位两块滑板及实际信用卡退款资格，重复实例不合并成一件。
- A092-02 [N1; F,T] 首次确认时追加智能手表和电子阅读器，未立即同意意味着旧清单不授权写入。
- A092-03 [N1,E1; T,M] 收齐最终清单分单重新确认后一次退货，不能先退滑板再同单追加其他件。

## ID 93

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1418) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1422)

- A093-01 [N1; O,F] 多台电脑时依用户后续回答定位原 15 英寸/32GB 那台，不预知未说出的原配置。
- A093-02 [N1; SEL] 目标 i7/8GB/1TB SSD 同时满足，未要求变的屏幕、颜色等保持。
- A093-03 [N1,E1; X,M] 原机、目标机、差价、已有方式完整确认后一次换货，不交换另一台原配置电脑。

## ID 94

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1432) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1436)

- A094-01 [N1; O,F] 待客户实际澄清后定位原 15 英寸/16GB 电脑，不沿用 ID 93 的 32GB 对象。
- A094-02 [N1; SEL] 同产品目标 i7/8GB/1TB SSD，其他属性按未放宽原则保留。
- A094-03 [N1,E1; X,M,F] 选定实例和完整新规格、差价确认后一次换货；相似案例不是共享客户状态。

## ID 95

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1446) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1450) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1454) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1455) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1456) / [B4](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1457) / [B5](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1458) / [B6](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1459)

- A095-01 [N1; O,F] 初始一台后用户澄清实际两台 15 英寸电脑，更新实例清单，不用一条 item 覆盖两台。
- A095-02 [N1; SEL] 两台分别匹配 i7/8GB/1TB SSD 同产品规格并保留未要求变化的属性。
- A095-03 [B1,B4; M] 逐件计算第一台补款，原成交价与目标价方向明确。
- A095-04 [B2,B5; M] 逐件计算另一台退款，不能合并 payments 或把退款标成需付。
- A095-05 [N1,B3,B6; M] 显示两笔差价及合计净额/方向；仅沟通汇总，不把跨单净额作为后台单笔扣退。
- A095-06 [N1,E1; X,F] 完整两件/各单清单、金额及方式确认后登记换货，结果逐单核实。

## ID 96

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1465) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1469) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1470)

- A096-01 [N1; O,A] 从本人订单定位 LA 目标单与 NYC 参考完整地址，不能把参考单也修改。
- A096-02 [N1; SEL] 音箱硬条件绿色，同产品可用款中最低价，其他未放宽规格保留。
- A096-03 [N1,E1; A,F] 目标地址完整确认后先更新核实，避免商品修改锁单。
- A096-04 [N1,E2; I,M] 最终音箱清单/差价/方式确认后一次修改，不能先锁单遗漏地址。

## ID 97

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1480) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1484) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1485)

- A097-01 [N1; O,A] 读取本人 NYC 参考地址并定位 LA 目标订单，两项同时出现均需保持任务。
- A097-02 [N1; SEL] 音箱选最低价绿色同产品可用规格，未变属性保留。
- A097-03 [N1,E1; A,F] 虽客户先说换商品，仍按依赖先完整确认并更新订单地址。
- A097-04 [N1,E2; I,M] 地址结果核实后一次商品修改；实际确认须覆盖最终清单和方式，不能由句子顺序决定写顺序。

## ID 98

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1495) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1499) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1500)

- A098-01 [N1; SEL,L] 自行车要更大车架，允许公路→山地不扩大同 product 权限，核验产品归属。
- A098-02 [N1; SEL] 拼图难度保留、片数相对原值增加 1000，主题优先动物；不是改订单数量。
- A098-03 [N1; O,SEL] 另一相机要求略低分辨率且其他属性不变，多个合格档位时澄清“略低”。
- A098-04 [N1; F,X,M] 确认处更换付款/退款卡，使旧方式和报价确认失效；按换货已有方式规则核验新卡。
- A098-05 [N1,E1; X] 各换货订单分别收齐清单确认后一次申请，不跨单复用授权。
- A098-06 [N1,E2; C,F] 另一订单滑板取消先查是整单还是部分；仅合法整单、允许原因和确认成立才取消，不能按 CANCEL 标签默认可删单件。

## ID 99

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1510) / [N2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1511) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1515)

- A099-01 [N1; SEL,L] 自行车更大车架且允许车型变化，仍核对同产品边界，不因客户同意跨产品。
- A099-02 [N1; SEL] 拼图难度不变、片数加 1000，主题优先艺术；不能沿用 ID 98 的动物优先。
- A099-03 [N2; O,SEL] 相机分辨率略低、其他属性保留，依据事实及用户交流确定目标。
- A099-04 [N2; X,M,F] 两单都优先合法已有 Visa 处理差价，完整清单/方式分别确认。
- A099-05 [N2; L] 用户仅取消滑板，不支持部分取消时零取消且保留其他商品，不擅自整单回退。
- A099-06 [N1,N2,E1; X] 各合法换货单一次申请并独立核实，未能取消滑板不吞掉其他合法任务。

## ID 100

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1525) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1529) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1530)

- A100-01 [N1; O,F] 客户说“退回换成”时澄清实际是规格替换，读取行李箱和滑板真实状态，不机械选 returns。
- A100-02 [N1; SEL] 行李箱只变红色、其余保持；滑板目标 34 英寸/自定义图案，未要求变属性保留。
- A100-03 [N1,E1; I,M] 对真实 pending 商品按完整清单一次修改，差价使用合法已有信用卡；不执行同件退货再修改。
- A100-04 [N1,E2; T,F] 靴子是独立退货任务，真实 delivered、清单及合法方式确认后一次申请。

## ID 101

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1540) / [N2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1541) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1545) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1546)

- A101-01 [N1; O,A] 根据两块手表定位自有目标单，从另一自有订单提取 NYC 完整地址，歧义先澄清。
- A101-02 [N1; SEL] 原硅胶表带改金属，颜色多选优先白，其余未变属性保留。
- A101-03 [N2; O,F] 客户坚信净化器和音箱同单不作为证据，查实际自有订单分布，不能在错误目标单强行找商品。
- A101-04 [N2; SEL] 净化器大号、夜间模式、保留 HEPA 同时满足，原订单事实不足时先澄清。
- A101-05 [N1,E1; A,F] 手表单新地址完整确认后先改并核实，参考订单和默认地址不连带更新。
- A101-06 [N1,N2,E2; I,M] 各实际 pending 单收齐清单和方式/差价确认后一次修改；不因客户说同单造成漏单或重复锁单。

## ID 102

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1556) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1560) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1561) / [E3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1562)

- A102-01 [N1; O,A] 定位两手表 pending 单及自有 NYC 参考地址，完整地址先确认。
- A102-02 [N1; SEL] 硅胶→金属表带，多颜色优先白，不变未放宽属性。
- A102-03 [N1; O,SEL] 通过与运动鞋一起收到的线索定位已送达净化器，大号/夜间/HEPA 全部核验。
- A102-04 [N1,E1; A] 手表 pending 单先更新地址并核实，不改净化器订单地址。
- A102-05 [N1,E2; I,M,F] 手表最终清单与金额确认后一次 pending 修改。
- A102-06 [N1,E3; X,M,F] 已送达净化器另建换货提案，确认后申请，不将另一单的地址或确认授权复用。

## ID 103

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1572) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1576) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1577) / [E3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1578) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1582) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1583)

- A103-01 [N1; O,F,T] 客户开头叫“取消”的书架和拼图实际已收，核对同单后澄清为退货，不调用 cancellations。
- A103-02 [N1,E1; T,M] 同单书架/拼图一次完整申请，另一个与吸尘器同单的背包独立收齐确认退货。
- A103-03 [N1; O,A] 从本人档案读 Chicago 默认地址，定位 pending 单，完整确认该订单目标地址。
- A103-04 [N1,E2; A] 先完成 pending 地址更新，客户档案地址本身不变。
- A103-05 [N1,E3; I,SEL,M] pending 商品颜色改红，未指定其他属性保留；各单清单确认后一次修改，地址不遗漏。
- A103-06 [N1,B1,B2; O,L] 查询指定已取消自有订单已存在的物流号，缺失时如实说明，不为查物流恢复/取消订单。

## ID 104

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1589) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1593) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1594) / [E3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1595) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1599) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1600)

- A104-01 [N1; O,F,T] “取消”实际为已收书架/拼图退货，明确不同订单且包含全部目标实例，不沿用 ID 103 的同单假设。
- A104-02 [N1,E1; T,M] 分单收齐书架/拼图及与吸尘器同单的背包，各单完整确认后一次退货。
- A104-03 [N1; O,A] 本人档案中读取 Chicago 完整默认地址，目标 pending 订单独立确认。
- A104-04 [N1,E2; A] 虽先说红色商品，执行先地址，默认地址记录保持原值。
- A104-05 [N1,E3; I,SEL,M] 红色同产品有货替换、其他属性保留，整单清单与方式/差价确认后一次锁单修改。
- A104-06 [N1,B1,B2; O,L] 提供真实已取消订单的已有物流号，不编造订单仍可配送或已恢复。

## ID 105

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1606) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1610) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1614)

- A105-01 [N1; O,SEL] 两个原玻璃/2L/电磁炉茶壶保留两个实例，即使 item ID 相同也不去重。
- A105-02 [N1; SEL] 第一件改陶瓷/燃气，未要求改容量则保留 2L；另一件改 1.5L/燃气，未要求改材质则保留玻璃。
- A105-03 [N1; SEL,L] 验证相同旧 item 副本分配不同目标的后端匹配 U5；无证据不猜“所有副本都替换”或虚构 line ID。
- A105-04 [N1,E1,B1; X,M,F] 两件逐件目标、数量与合计差价获完整确认，语义可表达后一次申请；验收必须验证两件均正确，不能仅核对一条结果。

## ID 106

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1620) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1624) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1628)

- A106-01 [N1; O,SEL] 从原 T 恤尺码按产品实际尺码顺序减一码，不能按字符串/数字盲减。
- A106-02 [N1; SEL,F] 核实棉材质要求/偏好及多颜色时黑色偏好，其他未放宽属性保留，缺候选先澄清。
- A106-03 [N1,E1,B1; X,M] 完整小一码规格及差价/方式确认后办理换货，参考“应办理”不绕过合法性。

## ID 107

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1634) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1638) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1642)

- A107-01 [N1; O,SEL,F] 用本人订单查靴子原规格，客户优先同规格新品；是否允许及有货按契约/事实判断，不编造强制拒绝理由。
- A107-02 [N1; SEL] 实际不允许同款换货后才启用 9码/皮革/防水回退，其他未放宽属性保留。
- A107-03 [N1; O,SEL,F] 另一订单拼图片数比原值少 500、难度保持；“更花哨”主题需要可用选项与客户澄清。
- A107-04 [N1,E1,B1; X,M] 两个订单独立清单/方式/金额确认并分别一次换货，不能仅完成靴子或跨单共用确认。

## ID 108

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1648) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1652) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1656) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1657)

- A108-01 [N1; O,F] 查最近 delivered 订单完整清单，明确只保留一台平板电脑，其余实例均纳入；多台平板时澄清保留哪台。
- A108-02 [N1; O,T] 电子阅读器明确在退货范围，不因与平板同类而误保留。
- A108-03 [N1,E1; T,F] 完整范围与合法去向确认后按单一次申请，不遗漏其他商品或把全订单取消。
- A108-04 [B1,B2; M] 计算实际选定原成交退款额并报告，保留平板不计入退款。

## ID 109

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1663) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1667) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1668) / [E3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1669) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1673) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1674)

- A109-01 [N1; O,F] 用本人 Houston 行李箱订单辨认 Orchard Avenue 为新地址、Ironwood Road 为旧地址，不能按路名固定猜新旧。
- A109-02 [N1,E1,B1; A] 从新地址参考单取完整地址，目标旧地址 pending 单确认后先改；不改参考单。
- A109-03 [N1,E2,B1; D] 同一新地址用于档案默认地址，独立确认更新核实，不用订单回执代替。
- A109-04 [N1; SEL] 平板按同产品有货最低价筛选，未明确放宽属性时按保留原则/澄清处理。
- A109-05 [N1,E3,B2; I,M,F] pending 商品整单清单及差价确认后一次修改，涉及同单地址必须先完成。

## ID 110

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1680) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1684) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1685) / [E3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1686) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1690) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1691) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1692)

- A110-01 [N1; O,F] 本例新旧方向与 ID 109 相反：从本人平板订单查 Ironwood Road 新地址，Orchard Avenue 为旧；不靠案例 ID 固定路名。
- A110-02 [N1,E1,B1; A] 目标旧地址订单确认完整新地址后更新，参考订单不连带变化。
- A110-03 [N1,E2,B2; D] 用户默认地址独立完整确认后更新核实。
- A110-04 [N1; SEL] 待处理平板选同产品有货最便宜款，保持未放宽规格或询问合法替代。
- A110-05 [N1,E3,B3; I,M,F] 收齐目标单清单/差价/方式，地址先于同单锁单修改，逐项核实两个地址与商品结果。

## ID 111

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1698) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1702) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1703) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1707)

- A111-01 [N1; O,A] 从自有订单资料查 NYC 完整地址，定位笔记本目标单，不能猜客户拒绝直接说出的地址。
- A111-02 [N1; SEL] 笔记本目标 i5/256GB SSD/space grey，同产品可用，未请求规格保留。
- A111-03 [N1; O,SEL] 手表黑色表盘且保留皮革表带，核对与笔记本是否同单，不默认为同单。
- A111-04 [N1,E2,B1; A,F] 笔记本订单地址完整确认后先更新核实。
- A111-05 [N1,E1,B1; I,M] 商品按实际所属 pending 单收齐完整替换列表、差价与方式，一次修改；综合业务条目拆成地址和商品两个可独立检查的结果。

## ID 112

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1713) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1717) / [E2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1718)

- A112-01 [N1; O,A] 自有订单查 NYC 完整地址并定位笔记本单，参考地址记录不修改。
- A112-02 [N1; SEL] 客户给笔记本目标编号时核实是具体 item、同产品且有货，不能无验证透传。
- A112-03 [N1; O,SEL] 手表黑表盘、皮革表带保留，按所属订单收集实例。
- A112-04 [N1,E2; A,F] 目标笔记本地址先独立完整确认并修改。
- A112-05 [N1,E1; I,M] 各实际 pending 单完整清单与差价/方式确认后一次修改，不遗漏手表或在锁单后才改地址。

## ID 113

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1728) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1732) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1736)

- A113-01 [N1; O,C] 枚举全部本人普通 pending 订单，items modified 或 processed 不纳入取消权限。
- A113-02 [N1; F,C] 原文未给取消原因，必须收集允许原因并说明每单范围/金额/原路去向，不预设 no longer needed。
- A113-03 [N1,E1,B1; C,M] 各 eligible 单确认后分别一次取消，结果逐单说明，不以单笔成功宣称全部完成。

## ID 114

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1742) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1746) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1750)

- A114-01 [N1; O,P] 查目标单真实 pending 状态、原信用卡 payments 和已有 PayPal；“发货前”不将 processed 当可切换。
- A114-02 [N1,E1; P,F] 明确整单金额、新方式扣款/旧方式退款并确认后切换，核实仍 pending，不自建两笔支付 API。
- A114-03 [B1; M] 来源只有金额标记：与本单整单付款/退款上下文及 fixture 对照，方向由实际支付事实证明，不能单凭数字造到账承诺。

## ID 115

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1756) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1760) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1764)

- A115-01 [N1; O,P,M] 查 pending 订单总额与已有礼品卡余额，比较是否能整单覆盖，不与信用卡混付。
- A115-02 [N1,E1,B1; L] 原 fixture 礼品卡不足时明确未切换，支付写调用为零，原订单方式保留。

## ID 116

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1770) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1774) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1778) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1779) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1780)

- A116-01 [N1; O,C] 核实指定自有普通 pending 单，客户“不再需要”映射允许原因，不另要求逐字脚本。
- A116-02 [N1,E1; C,F] 复述订单、金额、原路去向并获同意后取消，逐笔退款核实。
- A116-03 [B1,B3; M] 报告实际退款额，按真实 charge 金额计算，不用目录现价。
- A116-04 [B2; M] 按原卡/PayPal 渠道说明 3–6 工作日，cancelled 不等于渠道已到账。

## ID 117

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1786) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1790) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1794)

- A117-01 [N1; O,SEL] 已收键盘只去背光，轴体和尺寸保持，同产品有货。
- A117-02 [N1,E1; X,F] 完整新规格、差价与已有方式确认后一次换货，原键盘不退货再重下单。
- A117-03 [B1; M] 单列数字与本例实际差价核对，付款/退款方向用原成交与目标价验证，标记不单独构成方向证据。

## ID 118

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1800) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1804) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1808)

- A118-01 [N1; O,SEL] 定位黑色智能表原实例，仅换金色，皮革表带与 AMOLED 必须保留。
- A118-02 [N1,E1; X,F] 同产品可用候选和完整差价/方式确认后一次换货，不替换显示屏或表带。
- A118-03 [B1; M] 数字标记关联本例实际差价，方向及回执按订单/目标事实核对，不猜应补还是应退。

## ID 119

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1814) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1818) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1822)

- A119-01 [N1; O,SEL] 保留原 1L 玻璃及 1.5L 陶瓷两个不同旧规格实例，不能集合合并。
- A119-02 [N1; SEL] 第一件目标 1.5L 不锈钢/电磁炉，第二件目标 2L 不锈钢/电磁炉；逐件对应，不交换目标。
- A119-03 [N1,E1; I,F] 两件完整清单、总差价与已有方式确认后一次 pending 修改，常规不同旧 item 不等待 U5 特殊匹配。
- A119-04 [B1; M] 分别计算差价再汇总，来源数字作为 fixture 金额核对；方向由实际价格支持。

## ID 120

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1828) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1832) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1836) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1837)

- A120-01 [N1; O,SEL] 已收骑行头盔红色、原尺码保留，客户明确不在意透气等级，可放宽该属性。
- A120-02 [N1,E1; X,M,F] 差价使用合法已有礼品卡，完整确认后第一次换货申请并核实。
- A120-03 [B2; M] 金额标记与头盔实际差价/方向核对，不把客户“应退”当后台必为负差价。
- A120-04 [B1; L,O] 首次提交后同单意式咖啡机追加换货零写入，明确拒绝且不承诺进一步换货；不能通过新提案重置单次限制。

## ID 121

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1843) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1847) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1851) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1852)

- A121-01 [N1; O,L] 以当前客户身份核对自有订单引用，不通过室友名字/订单号替其验证或中途切账户。
- A121-02 [N1,E1,B1; L] 目标属于室友时拒绝取消，订单写调用为零。
- A121-03 [B2; L] 不向当前客户透露室友订单商品或费用，不为解释拒绝先读取并展示敏感详情。

## ID 122

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1858) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1862) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1866) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1867)

- A122-01 [N1; O,T] 定位已送达电水壶与游戏鼠标，收齐完整退货范围而不处理其他商品。
- A122-02 [B1; T,F,L] 明确原 fixture 信用卡不合资格、原 PayPal 合法；客户去向选择仍需真实确认，不能解释完就默认已授权。
- A122-03 [N1,E1; T] 最终清单与合法原 PayPal 获确认后一次申请。
- A122-04 [B2; M] 数字标记关联选定商品原成交退款合计，核对事实，不以整数/小数形式差异改变金额。

## ID 123

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1873) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1877)

- A123-01 [N1; O,P,M] 目标普通 pending 单核对原信用卡、已有不同礼品卡及整单足额条件。
- A123-02 [N1; F,P] 完整说明新方式整单扣款、原信用卡全额退款及渠道时效，再关联明确同意。
- A123-03 [N1,E1; P] 以确认的一个合法礼品卡切换并核实仍 pending，不部分扣款、不自行补退款。

## ID 124

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1887) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1891) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1895) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1896)

- A124-01 [N1; O,T] 已送达订单仅退运动鞋，意式咖啡机保留。
- A124-02 [N1; T,F] 客户拒绝 PayPal 但指定礼品卡，核实申请前已有资格；不合格时不能偷偷原路申请。
- A124-03 [N1,E1; T] 运动鞋清单及合法礼品卡去向确认后一次申请，咖啡机零退货。
- A124-04 [N1,B1,B2; M] 按运动鞋原成交信息报告礼品卡将获退款金额，区分申请/退款记录和实际余额。

## ID 125

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1902) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1906) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1910) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1911) / [B3](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1912)

- A125-01 [N1; O,SEL] pending 键盘线性轴和 80% 尺寸保留，只无背光→RGB，核对同产品可用规格。
- A125-02 [N1,E1; I,F] 完整清单、差价和已有 PayPal 确认后一次修改，订单进入 items modified。
- A125-03 [N1,B1,B3; M] 核对并说明键盘实际向 PayPal 退款的差价，不把目标价当退款额。
- A125-04 [B2; L,O] 后续 LED 灯泡修改零写入、不承诺再次修改；也不能用地址/支付/取消绕过锁单状态。

## ID 126

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1918) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1922) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1926) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1927)

- A126-01 [N1; O] 客户怀疑重复扣款时先独立验证，不以怀疑或订单线索直接读账户。
- A126-02 [B1; L] 无匹配账户时明确身份未验证，提供允许验证方式指引，不提示近似匹配账户或编造锁号规则。
- A126-03 [N1,E1,B2; L] 未验证零账户/订单敏感详情和零写入，不假称重复扣款已查实或已退款。

## ID 127

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1933) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1937) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1941) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1942)

- A127-01 [N1; O,C] 目标自有普通 pending 单，客户误下单原因合法；范围为整单而非单件。
- A127-02 [N1,E1; C,F] 完整订单金额和原路退款去向获确认后取消，核对实际退款记录。
- A127-03 [B1,B2; M] 实际原礼品卡逐笔退款合计与原文金额断言对应，说明礼品卡即时语义；未核实结果不冒称余额已增加。

## ID 128

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1948) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1952) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1956)

- A128-01 [N1; O] 从本人新地址订单/用户提供的完整地址核对 Charlotte 目标，客户仍提“订单一致”不使已送达订单可修改。
- A128-02 [N1,B1; L] 后台 delivered 时明确订单地址不可改，订单地址写调用为零。
- A128-03 [N1,E1; D,F] 仅档案默认地址完整确认后更新到新地址并核实，不能声称两个记录都已修改。

## ID 129

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1962) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1966) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1970)

- A129-01 [N1; O,P] 指定普通 pending 单核对原 Mastercard 与不同的已有 PayPal，未发现已有方式时不新增。
- A129-02 [N1,E1; P,F] 整单金额、扣新退旧及目标方式确认后切换，核实订单仍 pending。
- A129-03 [B1; M] 原信用卡退款告知 3–6 工作日，不能混成 PayPal 新扣款或即时礼品卡到账。

## ID 130

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1976) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1980) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1984) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1985)

- A130-01 [N1; H,L] 客户只愿与真人讨论费用，保留此意图，不强行继续模型客服或先读取非必要敏感详情。
- A130-02 [N1,E1,B1; H] 用可信 conversation_id 和适当摘要实际转接，检查 201 accepted；模型/用户提供的 ID 不透传。
- A130-03 [B2; H] 真实受理语义下逐字输出规定英文提示；失败/未知不伪称已转接，受理后业务 API 次数为零。

## ID 131

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1991) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1995) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:1999) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:2000)

- A131-01 [N1; O,SEL] pending 香水 30ml→同款东方香调 100ml，同产品且可用，其他未变属性保留。
- A131-02 [B1; L,P] 用户需要新增方式时解释只能网站添加，客服无新增 API；不接受未验证的新方式 ID 直接写入。
- A131-03 [B2; M] 来源数字与该规格修改的实际差价对照，方向和可支付性按订单/档案事实核实。
- A131-04 [N1,E1; I,F] 可用已有合法方式及完整清单获确认后一次修改；新增方式诉求不使合法修改任务被静默丢弃。

## ID 132

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:2006) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:2010) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:2014) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:2015)

- A132-01 [N1,E1,B1; L] 解释客服不能修改档案邮箱，零邮箱写入、零不存在端点调用；不为说明能力先读取不必要账户资料。
- A132-02 [B2; L] 不宣称已经或已安排更改邮箱，不用人工/后台隐含动作假造已完成。

## ID 133

[N1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:2021) / [E1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:2025) / [B1](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:2029) / [B2](E:/enterprise-ai-materials/retail_plus/test-cases-5147314e-f2da-4bac-924a-e2ad95e647e4-zh.md:2030)

- A133-01 [N1; O,SEL] 两个相同绿色背包保留两个实例，识别移除一件是数量变更而非规格替换。
- A133-02 [N1,B1; L] 明确不能改数量或单独取消重复件，只可讨论整单取消；说明选项不等于客户已经授权。
- A133-03 [N1,E1,B2; L,F] 客户未选整单取消时订单不变，零删件/商品修改/整单取消写入。

## 需求分析的完成边界

全体案例均拆解 N/E/B 三类来源；G/W 与每行组合连接规则、数据/API、实施阶段和允许/禁止的轨迹。具体金额、编号、地址仅在仓库外来源及未来 fixture 中核验，不进入运行决策。

仍需在相关实施阶段将每个 AT 场景绑定实际测试文件/函数及运行结果。裸金额标记（如 114、117–120、122、131）保留原始来源，方向及用途必须与真实 fixture/API 对照；本分析不将没有语义标签的数字强行裁决为补款或退款。26 的人工要求来自 E，120/125 的后续追加拒绝来自 B，不能因为 N 未写而遗漏，也不能让 Agent 预知未发生的客户消息。

本文件完成需求与验收设计，不声称业务实现、全部测试关联或远程评测完成；M0.4 的真实网关联调仍单独保留。
