# 工程结构与开发方式

## Python

```text
agent/
  agent.py                  # 平台工厂入口
  tools.py                  # 平台工具发现入口
  agent.json                # 协议、语言、场景
  support_agent/            # 可安装的本地 Python package
    application.py          # 决定下一轮回答或工具调用
    turns.py                # 不依赖 tau2 的轮次决策
    protocol.py             # 内部消息、动作和候选校验
    state.py                # 每个会话独立的 JSON 状态
    domain/customer.py      # 不依赖运行环境的业务规则
    domain/money.py         # U6 顺序 float 差价与余额舍入基线
    adapters/client_api.py      # 公共响应校验、错误分类与未知写结果
    adapters/customer_api.py    # 业务 API 传输与错误处理
    adapters/customer_tools.py  # 工具声明与注册
tests/test_customer.py      # 无网络、无模型的单元测试
tests/test_money.py         # 公开金额算法的离线边界测试
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

文档链接约定：仓库内文档和教学契约使用相对于当前文档的路径；仓库外业务材料使用本机绝对路径作来源追溯。引用外部原文时可保留行号，内部文档链接直接指向文件，避免绑定开发机盘符。

工具名称、参数、说明和返回结构，以及内部候选、任务、确认与提示词，由项目自行设计。平台驱动工厂、轮次和工具执行，Agent 负责模型调用、业务校验和执行控制。Python generate 签名、tau2 messages/actions、消息返回及 TypeScript tools 对照已核查，见 [平台契约记录](docs/PLATFORM-CONTRACT-NOTES.md)。当前模型仍未接入，fake 不替代真实 SDK 验证。JSON-only state 是项目工程约束，平台定义为不透明对象；消息恢复和网关转换在薄适配层实现，状态见 [实施事项寄存器](docs/OPEN-ITEMS.md)。

验证后可查与当前请求相关的公共目录，不限历史订单商品，仍不访问他人账户。重复 item 保留次数和请求顺序，按 ID 匹配的实例限制如实说明；修改/换货差价遵循 float 累加后 round，以回执核实，不用逐行舍入或 ROUND_HALF_UP 覆盖后端。实际模型使用运行时允许列表，固定参数省略且不可覆盖，费用仍需授权。

- Python 需要 3.12+；纯业务规则测试只使用标准库。`tau2` 由远程环境提供；本地安装这个 package 不会自动安装评测框架。
- TypeScript 需要 Node 24，使用原生类型擦除和显式 `.ts` 相对导入。这里的多模块目录是真正运行的本地模块，不依赖构建别名或 npm workspace 链接。
- `pyproject.toml` / `package.json` 是开发配置，不是授权远程安装依赖。远程不会执行 `pip install`、`npm install` 或项目脚本。不得上传 `node_modules` 或虚拟环境。
- 仅递归提交 `agent/`，最多 128 文件、单文件 256 KiB、合计 2 MiB。放在它之外的共享代码不会运行；应将其移入该目录。
- 示例无模型调用，也没有真实客户凭证。本地测试使用合成数据；真正的 t1 通过环境 API 查询，而不是返回写死的客户信息。
- README 和本文件随所选中文/英文版本切换。代码标识符、测试断言及业务 API 不随阅读语言变化。

M0 交付证据见 [M0-DELIVERY](docs/M0-DELIVERY.md)，SDK 来源与接口核查见 [M0-SDK-CHECK](docs/M0-SDK-CHECK.md)。当前源码独立提交快照 **51 项测试通过**，含新增 8 项 U6 算术兼容测试，基础规则映射见 [FOUNDATION-TEST-MAP](docs/FOUNDATION-TEST-MAP.md)。`domain/money.py` 只按已解析价格对做兼容估算、舍入已计算余额，尚未接入业务工具。本地 `.venv` 已安装官方 hyper-tau-bench 固定提交 6e9f34c685d4 的 tau2 1.0.1（Python 3.12.13），真实 SDK 最小接口/查询/恢复验证通过。课堂镜像版本一致性、M2.5 完整 JSON/SDK 转换和真实网关验证仍保留；生产写入、确认流程和完整业务 AT 尚未实施。原始平台返回存档与范围见 [平台契约记录](docs/PLATFORM-CONTRACT-NOTES.md)。M0 文档与三批 M1 源码已分别推送，每批 t1 1/1 通过；最新结果对应 ba53f46，完整报告与阶段边界见 [M1-DELIVERY](docs/M1-DELIVERY.md)。本提交只收尾交付与共享文档，未进入 M2。直接使用 `.venv\Scripts\python.exe` 运行本地测试，不需要修改执行策略或全局 Python。
