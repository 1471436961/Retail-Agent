# 平台接口修复与原始模板恢复

本页记录 `595cfa4` 接口修复时的 17 工具／14 文件／34 项测试基线。后续新增只读偏好排序后为 18 工具／15 文件；当前验证见 [偏好排序说明](PREFERENCE-RANKING.md)，下列原始运行数字不作为新增排序工具的验证结果。

2026-10-26。此前重建删除了原生产模块、移除了示例工具和状态字段，并添加了拒绝多个工具调用的限制。这些改动不应只归档说明。本轮已修复生产代码，按本项目平台契约验证；tau2 开源实现仅作参考。本轮没有提交、推送或发起远程评测。

## 已修复的接口

| 项目 | 当前实现及验证 |
|---|---|
| 原目录 | 恢复 `agent/support_agent/` 全部九个原模块路径；业务实现放回 application、adapters、state、config |
| Agent 入口 | `agent.py:create_agent()` 保持零参数；返回 `CustomerAgent`，保留 `get_init_state(message_history=None)` 与 `generate_next_message(message, state)` |
| 平台上下文 | 仅由工厂调用 `get_agent_context()`，传入实例并在后续轮次复用；调用注入的模型网关 |
| 工具入口 | `tools.py:Tools(CustomerTools)`；实际 SDK 发现返回该类，继承 `ClientAPIToolKitBase`，工具仍以 `@is_tool` 声明 |
| 原查询工具 | 恢复 `lookup_customer(customer_id: str, email: str = "")`；先校验邮箱搜索结果，再读取客户；声称 ID 不匹配时不得读取详情 |
| 原状态字段 | 保留导出的 `SessionState`、`initial_state()` 与 `turn`／`pending_call_id`／`customer_id`；新增 `messages` 保存完整 JSON 消息历史 |
| 消息协议 | 实际 SDK `AssistantMessage` 与状态组成返回二元组；JSON 往返保留工具调用参数、ID 和对应结果；多个工具调用及其全部结果都可继续运行 |
| 部署 | 恢复本地 setuptools 的 `support_agent*` 包发现；官方上传收集器收取 14 文件，独立复制目录可导入、创建并运行 Agent |

当前 17 个模型工具包含原查询工具及扩展零售工具。模型负责理解用户、选工具、追问与确认；Python 适配器负责 REST 字段、执行及数值计算。原 `domain/customer.py` 的示例函数为原模块兼容而保留，当前 `CustomerAgent` 不导入其中的身份正则和固定回复，不重新启用旧 t1 解析逻辑。

原三字段状态可接受新的用户轮次；新状态是 JSON 可序列化对象。原模板未保存的过去消息不能从三个字段凭空恢复。多工具调用的全部 ID 位于 `messages`；兼容字段 `pending_call_id` 在恰有一个调用时记录该 ID，其余为 null。

## 原始材料与平台依据

首次安装提交 `c37119d` 的 39 个文件完整保存在 [reference/platform-starter](../reference/platform-starter/)。逐字节复核发现初次导出含 Windows CRLF 转换；本轮已改用 Git 原始对象字节恢复，39/39 文件 SHA-256 与该提交对象相同。原始六项 `tests/test_customer.py` 也已恢复到当前测试目录。reference 中的旧 binding 仅供历史核对，不替换根工作流或当前平台绑定。

根 `AGENT-CONTRACT.md`、`materials/` 中 OpenAPI／原始材料、官方脚本及根工作流此前一直保留。接口依据依次是本项目平台契约、下载的 OpenAPI 与课程材料；不以开源 tau2 的参数或本地后端行为替代这些资料。

工具只通过注入的 `ClientAPI` 请求公开端点；`customer_id`、`postal_code`、`replacements`、`refund_payment_method_id` 和完整地址字段按本地 OpenAPI 映射。政策显式以 UTF-8 读取。模型取平台运行时允许列表，不硬编码模型 API、密钥或 token 设置。

## 本地验证

测试使用实际 SDK `ModelGateway`、候选 broker 序列化、工具发现、`ClientAPI` 与 `Environment`，模型底层响应为脚本替身。每次集成 REST 请求及响应再按下载的 OpenAPI 3.1.0 校验；直接覆盖全部 14 个公开 HTTP 操作，并验证错误的上游字段与字符串化数字／布尔值不能通过原 schema。

接口专项验证原模块、工厂和方法签名、原查询行为、原状态字段、JSON 往返、多调用与全部结果配对；隔离测试从实际部署目录创建 Agent 并通过网关请求一次底层替身。恢复的原六项测试同时执行。这些检查不替代真实模型质量或远程案例成绩。

最终执行 `.venv/Scripts/python.exe -B -m unittest discover -s tests -v`：`Ran 34 tests in 20.627s`、独立汇总行 `OK`，零失败／错误／跳过，退出码 0。日志为 `.test-tmp/interface-repair.log`。34 项由 18 项模型／工具集成、3 项 OpenAPI、6 项原始测试、5 项接口兼容和 2 项包检查组成。

官方收集器实际收取 14 文件，源码原始字节合计 27,495、最大文件 11,870 字节，满足文件数／单文件／总文本预算。reference、测试和文档不进入部署包。`git diff --check` 通过。测试禁止网络访问，不读取个人权限文件，不发生真实模型调用或收费评测。
