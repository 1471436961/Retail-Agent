# M7 接口与自然语言架构审计

审计日期：2026-10-08。对象：`E:\Retail-Agent` 重构前实现；基准提交 `254701659aefb07d53171fbc8a678f6f207e7063`。本页为重构前的历史诊断快照：审计阶段没有修改 Agent、固定业务夹具或预期，没有提交、推送、真实模型调用或远程评测。随后用户要求全面重构，实际修改与验证见 [重构记录](M7-REFACTOR.md)，以下“当前实现”均指该重构前快照。

## 结论

当前实现不能作为具备普通自然语言交互能力的零售 Agent 交付。存在两条独立的阻断链：默认入口没有启用模型，身份和业务解析主要依赖有限语法；真实 SDK 的工具结果序列化与应用的严格类型校验不兼容。此前主要合成对话测试绕过了后一个接口，并以邮箱、商品 ID、结构化 JSON 和固定确认措辞绕过了前一个理解问题。

这不是把业务实现放在辅助模块造成的。官方接口允许随包辅助源码，入口与工具继承关系存在；应修复运行链和语义链，而不是把全部代码搬回两个入口文件。

原计划 [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md#L22) 要求“模型理解自然语言与组织回复，确定性代码校验规则和控制执行”。默认运行路径没有落实前半部分。此前把有限语法长期保留为客户交互入口、再以固定输入验证业务规则，属于设计与验证范围的缺口。

## 证据范围

- 用户下载的完整报告：`E:\evaluation-d67137b4-14fb-494b-8c06-e04f92b686e1.json`，SHA-256 `ae9aa3944f7d3735f0d336e78d6b4c7d9c09497ffc15b1b1dac0cbb71a297c8e`。
- [GitHub 运行 37719441669](https://github.com/1471436961/Retail-Agent/actions/runs/37719441669)；[平台任务 d67137b4-14fb-494b-8c06-e04f92b686e1](https://agentist.org/lab/enterprise-ai?run=d67137b4-14fb-494b-8c06-e04f92b686e1)。用户手动取消；18 条已有结果：17 条 `candidate_error`、1 条失败、0 条通过；其余 116 条未运行。
- T-016 截图提供实际姓名/邮编对话及重复询问；完整报告没有运行异常堆栈，不能把 17 条异常全部归因为本地发现的序列化问题。
- 本地探针使用真实入口工厂、SDK 消息类型、ClientAPI 和 Environment，后台为合成 `MatrixBackend`；没有访问真实客户后台。语言探针使用测试侧 JSON 文本控制排除已发现的传输问题，并注入离线模型计数器观察路由，不构成真实模型理解效果测试。
- 临时复现程序与原始输出：`.test-tmp/m7_sdk_transport_probe.py`、`.test-tmp/m7_sdk_transport_probe.json`、`.test-tmp/m7_architecture_probe.py`、`.test-tmp/m7_architecture_probe.json`。它们是本地诊断文件，未进入正式 FOUNDATION/AT 证据发布；不增加 unittest 或业务 AT 通过数。

复现命令（仓库根目录，已安装的本地 SDK）：

```powershell
& .\.venv\Scripts\python.exe -B .test-tmp\m7_sdk_transport_probe.py
& .\.venv\Scripts\python.exe -B .test-tmp\m7_architecture_probe.py
```

## A01：真实 SDK 工具返回的类型发生改变（已复现，优先修复）

工具公开方法返回 `dict`，包含价格、布尔值和完整状态。例如 [customer_tools.py](../agent/support_agent/adapters/customer_tools.py#L24)。实际安装 SDK 的 `tau2/environment/environment.py` 中，`get_response` 调用 `to_json_str`；后者递归把数字和布尔值转成字符串。样本实际得到：

```json
{"price":"12.5","available":"True","schema":"12"}
```

应用接收工具结果时仍要求数值价格、布尔字段及整数 schema，因此拒绝有效订单/prepare 结果。相同合成换货请求的独立对照：

| 结果返回路径 | 合成 HTTP 调用 | 换货 POST | 最终订单状态 |
|---|---:|---:|---|
| 测试常用的手工 `json.dumps(dict)` | 14 | 1 | exchange requested |
| 当前真实 `Environment.get_response` | 8 | 0 | delivered |
| 测试侧先返回正确 JSON 文本，再经真实 SDK | 14 | 1 | exchange requested |

第二条路径订单读取报授权/验证不匹配，换货 prepare 不被接受，当前提案数为 0。本地探针没有复现未捕获异常；其结论是运行链不兼容，而不是远程异常堆栈已定位。

安装 SDK 与固定 SDK 源码的上述 `environment.py` 同 SHA-256：`33f0484e967038690b5fc25386eba6aa12d748199c1a6bdd8867e541153b337`。单文件相同不证明整个远程镜像一致。

修复方向：工具公共返回边界输出严格 JSON 文本，保持内部类型和严格校验；同步正确返回类型声明。不能全局把字符串猜回数字/布尔值，也不能放宽 `clone_state`、订单或回执校验。必须覆盖全部 15 个工具的实际 SDK 返回与 Agent 消费、恢复重放。

## A02：默认入口未启用模型，身份解析无法到达模型（已复现）

[agent.py](../agent/agent.py#L7) 创建 `CustomerAgent(context=get_agent_context())`；[application.py](../agent/support_agent/application.py#L15) 的 `model_adapter` 默认 `None`，没有从 context 构建适配器。

[read_session.py](../agent/support_agent/read_session.py#L552) 在未验证身份时直接返回固定询问；模型分支位于其后。即使显式注入适配器，身份理解失败仍不会调用它。[identity.py](../agent/support_agent/domain/identity.py#L93) 主要读取标签和 `my name is` 语法。

用截图中的原句复现：

> I'm Amira Caldwell, and my zip code is 70168. I'm afraid I don't remember my email address off the top of my head, so the name and zip code will have to work.

解析只得到 `postal_code=70168`；缺 first/last name，完整 proof 为 `None`；零工具调用、零 HTTP、离线模型计数为 0，回复仍要求邮箱或姓名与邮编。足以解释 T-016 的重复询问现象。

修复方向：模型从真实用户历史提取身份候选字段，保存原文轮次与依据；确定性代码校验字段、查询客户并独立核对后台匹配。模型不能宣布 `verified`，不能把 assistant 或工具数据当作用户提供的身份信息。多词姓名或拆分歧义应澄清，而不是强制两个英文单词。

## A03：现有模型适配器没有业务语义输出通路（代码核查及探针确认）

[model_gateway.py](../agent/support_agent/adapters/model_gateway.py#L10) 的政策是只读模型，输出为文本或读取工具调用。它不能输出可被规划器接纳的商品描述、约束、偏好、改口或针对某个已展示提案的确认语义。工作流有限语法路由先于模型；读后结果消费路径也未调用模型。

所以仅在工厂创建现有 `ModelAdapter`，不会让“改成 8 码皮靴”“换同容量红色杯子”等自然表达进入完整业务规划。

需要新增结构化语义层：真实用户历史 → 意图/字段/约束/改口候选 → 来源与类型校验 → 已有业务规划器。商品和支付方式的描述必须结合已授权读取的真实目录/档案消歧，不能要求客户知道后台 item/payment IDs；模型不能编造这些 ID。多轮累积应保留早先目标，最新改口覆盖同一目标的旧约束。

新语义记录必须参与恢复、来源核查和提案事实指纹。不能将模型生成的标准化 JSON 伪装成新的 `role=user` 消息，从而绕过现有来源校验。

## A04：有限语法问题横跨业务、地址、原因与转接（已复现）

以下是完成合成身份验证之后的探针；每条使用新会话。商品修改探针中的后台是合成杯子，靴子句用于检查路由分类，不作为真实靴子目录选择证据。

| 普通表达 | 当前观察 |
|---|---|
| I need to modify the boots in order #TEST1 to size 8, leather material… | 仅读取订单，未进入商品修改规划 |
| I want to exchange the mug…for a red one with the same capacity… | `complete_item_list_required`，要求原商品 ID 与规格 |
| I would like to return the mug… | 仅读取订单，未进入退货规划 |
| …to 123 Main St, Springfield, IL 62704, US. | `address_fields_required` |
| …cancel…because I accidentally placed it. | `clarify_cancellation_reason` |
| Could you get a supervisor to help me with this? | 转接意图为 `None`；只到离线模型文本回退 |
| Please use PayPal to pay for order #TEST1. | **正向控制：**成功产生支付方式切换提案 |

对应入口：[items_intake.py](../agent/support_agent/domain/items_intake.py#L14)、[returns_intake.py](../agent/support_agent/domain/returns_intake.py#L8)、[addresses.py](../agent/support_agent/domain/addresses.py#L21)、[policies.py](../agent/support_agent/domain/policies.py#L156)、[handoff_session.py](../agent/support_agent/handoff_session.py#L23)。

条件解析另有对照：`size: 8, material: leather, any waterproof` 能归一化；`I would like size 8 leather boots, and waterproofing does not matter to me.` 得到 `item_condition_unresolved`。这不是所有自然表达都失败，而是覆盖依赖碰中有限模板。

## A05：确认理解依赖固定措辞（已复现，当前表现为阻断）

[proposals.py](../agent/support_agent/proposals.py#L354) 与其集合回复分类使用有限确认语法。同一完整合成换货提案，分别新建会话测试：

- `yes`：发送一次换货 POST。
- `Yep, that's exactly what I want. Please go ahead.`：零 POST，提案进入 `needs_review`。

当前没有因此越权写入，但普通确认无法推进。修复需把模型的确认理解绑定真实最新 user、已展示的具体提案集合和版本。新增条件、否定、范围变化、过时复述仍必须失效并重新复述；不能直接用模型输出的 `confirmed=true` 授权。

## A06：主验收往返绕过真实接口，语言输入弱化（已确认）

[sdk_m6_checks.py](../tests/sdk_m6_checks.py#L65) 直接创建 `CustomerAgent()`；执行工具后 [手工构造 JSON ToolMessage](../tests/sdk_m6_checks.py#L110)，没有把真实 SDK 序列化后的结果交回 Agent。

[sdk_m3_checks.py](../tests/sdk_m3_checks.py#L381) 甚至明确记录 SDK 会转换数值/布尔值，并刻意把 SDK 重放格式与应用手工 JSON 往返分开。两段独立通过没有证明部署完整往返能通过。

M6.7 158 个对话、990 个 user 轮中：165 轮含 `{`，157 轮含 `@example.test`，205 轮精确为 `yes`。这些是文本特征计数，可能重叠，不能相加，也不据此自动认定某条 AT 无效。

T-016 对应本地场景 `case015_material_choice_refund/charge` 用 `a@example.test` 完成身份，然后提供 `boots_original`、`paypal_a` 与包含 hard/change/relax 的 JSON。远程截图使用姓名、邮编和普通语言；本地场景跳过了实际失败的理解步骤。

此前 `522/522` 应继续解释为固定合成断言通过，不扩大成真实自然语言 Agent 已就绪。本次不能宣称原子断言全部错误；需要保留业务规则回归，同时新增真实入口工厂、SDK 工具发现/派发/返回、普通语言和多轮语义的端到端测试。只有完整返回路径和理解路径都经过的测试才可支撑 M7 就绪判断。

## A07：SDK 实际工具发现对象与入口类不同（潜在维护风险）

[tools.py](../agent/tools.py#L3) 公开导入 `CustomerTools`，再定义空 `Tools` 子类。实际 SDK `candidate_server._find_subclass` 按 `dir(module)` 扫描，探针选择 `CustomerTools`。

两者目前没有方法差异，因此这不是当前故障原因。但以后仅覆写 `Tools` 的方法可能不被实际平台发现。修复时须让入口发现对象唯一明确，并测试真实 SDK 发现函数，不能只用 `Tools(...)` 的手工实例证明修复生效。

## 已检查且应保留的控制

- 工厂导出、消息接口、SDK 工具继承与 15 个工具注册存在；辅助模块随 `agent/` 收集。没有证据表明“入口文件短”是故障。
- 身份独立核对、客户/订单归属、严格参数键集、订单状态规则、价格与差价算法、完整复述、刷新与确认指纹、发送前认领、Unknown 不重发、写后自有读回应继续由确定性代码控制。
- 模型理解语言不等于模型拥有业务权限。接口、状态枚举与允许取消原因的规范值固定是合理的；把客户语言限制为这些内部格式才是问题。
- 没有在本次指定案例号/客户名检索中发现生产代码写入 T-016 专用答案。当前问题是固定语言模板与运行链缺口，不能称为已经证明“按评测案例硬编码答案”。
- 既有封闭回执、4096 字符完整复述拒绝、多对换货上游配对及共享内存认领边界继续有效，属于已披露限制。

## 修复顺序与验收门

1. **先修接口完整往返。** 明确 SDK 发现类；公共工具返回正确 JSON 文本；所有 15 工具经真实 SDK 返回至 Agent；读写、Unknown、重复回执和恢复均回归。不能用类型放宽替代修复。
2. **接通结构化身份理解。** 工厂接入平台网关；验证截图原句、同义表达、跨轮字段累积、改名/否定与歧义。后台查验仍决定身份是否成立。
3. **建立统一业务语义层。** 将普通语言的目标、商品条件、支付描述、取消原因、地址与转接请求转成带来源的候选，复用现有规划和权限控制；不要继续逐句扩充正则作为主方案。
4. **补确认与多轮恢复。** 将选择、范围、改口和同意绑定完整提案版本；模型候选、真实历史与恢复记录一致；未决写不能被模型清除。
5. **补部署路径测试，再申请远程实测。** 保留原规则断言，新增同义正控和否定/条件反控；检查 factory、SDK 派发及结果消费确实连在一起。远程异常需要原始堆栈区分，不能仅根据 `candidate_error` 猜测。未获新授权不自动发起付费评测。

本次审计不是生产修复完成声明；M7 正式业务验收仍未通过。
