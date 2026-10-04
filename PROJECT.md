# 工程结构与开发方式

2026-10-04 当前 M0–M3 基础收尾见 [收尾记录](docs/M0-M3-CLOSEOUT.md)，问题分类依据见 [全面复核](docs/PENDING-ITEMS-AUDIT.md)。退款预计额、完整退货提案、稳定认领与显式会话端点适配已实现；完整业务流程属于后续 M4/M5。用户已进一步授权分批提交推送；各批验证与推送记录见收尾记录，M4.1 未开始。

## Python

```text
agent/
  agent.py                  # 平台工厂入口
  tools.py                  # 平台工具发现入口
  agent.json                # 协议、语言、场景
  support_agent/            # 可安装的本地 Python package
    application.py          # 决定下一轮回答或工具调用
    turns.py                # 轮次入口，转交只读会话逻辑
    read_session.py         # 身份范围、只读路由与完整结果批次
    protocol.py             # 内部消息、动作和候选校验
    state.py                # 每个会话独立的 JSON 状态
    proposals.py            # M3.2/M3.3 完整提案、局部确认和原 user 来源链
    tasks.py                # M3.4 内部请求计划、恢复与逐记录候选诊断
    write_session.py        # M3.5 可信端口、刷新、单次发送及未决 journal
    model_context.py        # 有界模型投影，原始证据与 state 不裁剪
    domain/customer.py      # 不依赖运行环境的业务规则
    domain/identity.py      # 独立验证输入与用户来源核验
    domain/money.py         # U6 顺序 float 差价与余额舍入基线
    domain/rules.py         # 可解释 JSON 规则结果，非写入授权
    domain/orders.py        # 精确状态与能力准入
    domain/catalog.py       # 选中规格、次数、原价与差价解析
    domain/policies.py      # 支付、退款去向及取消原因规则
    domain/task_graph.py    # 同单依赖与对称冲突，独立记录无隐式依赖
    domain/write_receipts.py # 履约审查、回执及可观察效果；不证明到账
    adapters/client_api.py      # 公共响应校验、错误分类与未知写结果
    adapters/customer_api.py    # 业务 API 传输与错误处理
    adapters/customer_tools.py  # 工具声明与注册
    adapters/read_api.py        # 六只读端点、归属与事实校验
    adapters/read_tools.py      # 带验证依据的可重放只读工具
    adapters/model_gateway.py   # JSON/SDK 转换与模型候选门控
    adapters/write_runtime.py   # 显式串行会话认领表与七个契约端点
tests/test_customer.py      # 无网络、无模型的单元测试
tests/test_money.py         # 公开金额算法的离线边界测试
tests/test_m2_*.py          # 只读 API、会话与真实 SDK 子进程检查
tests/test_m3_rules.py      # M3.1 状态、规格、金额与支付规则
tests/test_m3_proposals.py  # M3.2 完整确认、迁移、恢复和真实 SDK 检查
tests/test_m3_scoped_consent.py # M3.3 独立范围、追加/条件/撤回与旧确认保留
tests/test_m3_tasks.py      # M3.4 请求图、多订单候选、迁移与来源校验
tests/test_m3_writes.py     # M3.5 fake 发送/持久化协议、强读回、未知及恢复
pyproject.toml             # 本地 package 元数据
```

## TypeScript

本节描述安装模板的 TypeScript 变体；当前仓库为 Python 单语言实现，没有这些 `.ts` 文件。

`agent.ts` 和 `tools.ts` 是同样的薄入口。`agent/support-agent/` 按 `application.ts`、`state.ts`、`domain/customer.ts`、`adapters/customer-api.ts` 和 `adapters/customer-tools.ts` 划分模块；`contract.ts` 提供协议类型。项目根目录的 `package.json` 提供 `npm test`，`tests/customer.test.ts` 验证完整的用户消息 → 工具调用 → API 结果 → 回答流程。

## 一个功能应该如何增加

1. 从业务材料提取规则，先在 `domain/` 增加纯函数和本地测试。
2. 在 `adapters/` 添加业务 API 适配器，检查状态码；在工具模块声明只读/写入属性。
3. 在 `application` 中连接对话逻辑。真正的会话数据保存在 state 中，不放在模块全局变量；根据调用 ID 对应工具结果。
4. 写入操作前实现业务规则与用户确认；不要盲目重试会造成重复退款等副作用的操作。
5. 运行本地测试，然后提交整个 `agent/`。先做 t1 接入，再做公开练习或所选正式案例。查看实际结果与期望结果的差异。

## 依赖与运行边界

M0–M3 内部基础范围完成，最新完整工作区 353/353、零跳过、原生退出码 0。默认工厂仍八 READ、零注册 WRITE；显式 SessionWriteRuntime 支持可信串行会话、共享认领表及完整 journal 恢复，默认不注入。claim_identity 绑定版本/记录而非历史位置，只有严格 True 允许发送；Unknown 不重发，匹配回执及自有强读回后才释放依赖。SDK 入口返回真实 AssistantMessage 与对应 state。跨进程崩溃/丢失 state 的去重不在当前保证内，具体业务生产器和工具路由尚未实施。M0.2 完整业务 AT 执行随 M4–M6 补齐，134/522 不变；当前追踪明确区分组件通过与业务未执行。详见 [收尾记录](docs/M0-M3-CLOSEOUT.md)和[逐方法运行报告](docs/FOUNDATION-RUN.json)。

Windows 本地离线测试可使用 `pwsh -NoProfile -File .\scripts\test-local.ps1`：使用项目解释器，临时目录限定在仓库内，原生退出码保留，调用方环境不变。两个测试文件的四处临时目录调用已通过共享 helper 避开 Windows 0o700 的特殊 ACL 设置，直接运行 unittest 也生效；其他系统保持标准临时目录行为。评审会话现已报告原命令在受限模式实跑 266/266、零跳过、退出码 0，无提权、无重定向或注入；本会话此前的启动失败和非受限通过保留来源区分，见 [本地测试入口](docs/LOCAL-TEST-RUNNER.md)。脚本是可选便利入口。

退款依据的后续取证见 [退款源码证据](docs/REFUND-IMPLEMENTATION-EVIDENCE.md)：固定上游退货仅登记申请，取消无统一合计且未过滤历史交易类型。适用版本的实现代码可以作为计算依据，但尚未核实课堂 REST 对应关系；本项目保留原价/次数与逐 charge 来源，不从余额舍入推导合计，不照搬全历史退款循环。

文档链接约定：仓库内文档和教学契约使用相对于当前文档的路径；仓库外业务材料使用本机绝对路径作来源追溯。引用外部原文时可保留行号，内部文档链接直接指向文件，避免绑定开发机盘符。

工具名称、参数、说明和返回结构，以及内部候选、任务、确认与提示词，由项目自行设计。平台驱动工厂、轮次和工具执行，Agent 负责模型调用、业务校验和执行控制。Python generate 签名、tau2 messages/actions、消息返回及 TypeScript tools 对照已核查，见 [平台契约记录](docs/PLATFORM-CONTRACT-NOTES.md)。M2 已实现可显式注入的模型适配层并用真实 SDK＋fake 网关验证；默认工厂不启用真实模型，真实网关联调尚未完成。JSON-only state 是项目工程约束，平台定义为不透明对象；消息恢复和网关转换位于薄适配层，状态见 [实施事项寄存器](docs/OPEN-ITEMS.md)。

验证后可查与当前请求相关的公共目录，不限历史订单商品，仍不访问他人账户。重复 item 保留次数和请求顺序，按 ID 匹配的实例限制如实说明；修改/换货差价遵循 float 累加后 round，以回执核实，不用逐行舍入或 ROUND_HALF_UP 覆盖后端。实际模型使用运行时允许列表，固定参数省略且不可覆盖，费用仍需授权。

- Python 需要 3.12+；纯业务规则测试只使用标准库。`tau2` 由远程环境提供；本地安装这个 package 不会自动安装评测框架。
- TypeScript 需要 Node 24，使用原生类型擦除和显式 `.ts` 相对导入。这里的多模块目录是真正运行的本地模块，不依赖构建别名或 npm workspace 链接。
- `pyproject.toml` / `package.json` 是开发配置，不是授权远程安装依赖。远程不会执行 `pip install`、`npm install` 或项目脚本。不得上传 `node_modules` 或虚拟环境。
- 仅递归提交 `agent/`，最多 128 文件、单文件 256 KiB、合计 2 MiB。放在它之外的共享代码不会运行；应将其移入该目录。
- 示例无模型调用，也没有真实客户凭证。本地测试使用合成数据；真正的 t1 通过环境 API 查询，而不是返回写死的客户信息。
- README 和本文件随所选中文/英文版本切换。代码标识符、测试断言及业务 API 不随阅读语言变化。

M0 交付证据见 [M0-DELIVERY](docs/M0-DELIVERY.md)，SDK 来源见 [M0-SDK-CHECK](docs/M0-SDK-CHECK.md)。M1 独立提交快照历史基线为 **51/51**，基础规则见 [FOUNDATION-TEST-MAP](docs/FOUNDATION-TEST-MAP.md)；M2 源码提交快照为 **91/91**，实现了跨轮身份、六只读端点与模型适配往返，详见 [M2-DELIVERY](docs/M2-DELIVERY.md)。2026-10-03 用户明确开始 M3，首批 M3.1 增加 39 项规则测试，完整离线回归 **130/130**；状态、规格、差价、支付与退款依据见 [M3.1-DELIVERY](docs/M3.1-DELIVERY.md)。源码与测试由 cd71a21 推送，对应 t1 工作流成功，报告正文计数尚未单独核实；交付文档随后由 9b323d3 推送。上述为首批历史验收；2026-10-04 已补预计额、完整退货提案与来源门控，当前范围见收尾记录。

随后实施 M3.2 内部提案版本、完整确认与来源恢复，该批历史离线回归 **176/176**，零跳过、原生退出码 0，见 [M3.2-DELIVERY](docs/M3.2-DELIVERY.md)。真实 SDK 的 M2 子检查及新增 M3 集成检查均已包含在主包装测试内，不重复相加；网关为 fake、拒绝网络。默认只读路由不自动构造业务提案，尚无业务写工具；当时局部/条件确认、任务依赖、写前刷新保留；后续 M3 已完成这些内部结构，完整报价生产器仍属 M4/M5。M3.2 源码 610f488、文档 769bcee 均已提交推送；对应工作流成功，正文案例计数未单独核实，回执见 M3.2 交付记录。本地仍为官方固定提交 6e9f34c685d4 的 tau2 1.0.1、Python 3.12.13；课堂镜像一致性和真实网关联调保留，默认真实模型关闭。money.py 已被规格规则复用，完整业务 AT 未验收。原始平台存档仍在仓库外，见 [平台契约记录](docs/PLATFORM-CONTRACT-NOTES.md)。M0/M1 已分批推送，历史 t1 报告见 [M1-DELIVERY](docs/M1-DELIVERY.md)；M2 三个源码批次各自 t1 1/1 通过，SHA 与回执见 M2 交付记录。这些结果只证明接入兼容，不覆盖完整业务或真实模型效果。直接使用 `.venv\Scripts\python.exe -m unittest discover -s tests -q` 运行本地测试，不需要修改执行策略或全局 Python。

2026-10-03 随后按授权完成 M3.3 内部完整操作集合的局部确认、追加/缩减/撤回/条件与支付/报价失效，该批源码实跑 **221/221**、零跳过、原生退出码 0；schema 3 保留可核验的原 user 范围同意与旧版本来源，见 [M3.3-DELIVERY](docs/M3.3-DELIVERY.md)。源码 abac040、文档 3460329 已推送，自动工作流成功，报告正文案例计数未单独核实；无真实模型调用。

随后按用户授权实现 M3.4 内部同单依赖/冲突及独立记录候选诊断，源码提交后实跑 **266/266**、零跳过、原生退出码 0，新主测试 45 项，见 [M3.4-DELIVERY](docs/M3.4-DELIVERY.md)。schema 4 的任务计划来源复用严格身份与原 proposals 台账；同单地址/支付须先于商品锁单，取消/退换冲突先澄清。候选不是写入授权，前置任务确认不等于完成；该批当时的结果 reducer、依赖释放及写前刷新已在 M3.5 内部实现，完整业务报价生产器仍属 M4/M5。默认只读路由不自动创建业务任务，八 READ、零 WRITE；测试环境 53ee070、源码 2413049 已逐批推送，t1 接入回执见交付记录。没有真实模型或另行 evaluate。
