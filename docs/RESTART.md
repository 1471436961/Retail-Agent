# 从 tau2 零售工具调用 agent 重新开始

2026-10-26。依据用户“该删的全删，重新开始”的要求实施。重建阶段只做本地验证；随后用户确认已在平台配置模型，并明确要求提交推送。代码提交为 `31066b6`，远程结果以这次推送对应的实际任务报告为准。

## 查阅的开源实现

1. [sierra-research/tau2-bench 的 LLMAgent](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/agent/llm_agent.py)：维护 system policy 与消息历史，把可用工具交给模型，原生工具结果回到历史。
2. [tau2 retail tools](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/domains/retail/tools.py)：身份搜索、查询及明确的业务操作函数，而不是调用者传入整份工作流快照。
3. [tau2 retail policy](https://github.com/sierra-research/tau2-bench/blob/main/data/tau2/domains/retail/policy.md)：身份、单客户、变更前复述确认、一次完整商品清单等对话政策。
4. [原 tau-bench tool-calling agent](https://github.com/sierra-research/tau-bench/blob/main/tau_bench/agents/tool_calling_agent.py)：同样以模型选择函数、环境执行、返回结果为主循环。

本项目重新实现这条运行链，调用课堂提供的模型网关和 REST 客户端；没有复制上游数据库代码到部署包、调用外部模型 SDK、加载任务答案或使用 ground-truth agent。许可放在部署目录。网页查阅日期为本页日期；上游 main 是可变引用，当前官方版本不冒充课堂镜像版本。实际本地测试使用现有安装 SDK。

## 分工

| 模型 | Python 工具／适配器 | 平台后端 |
|---|---|---|
| 识别普通语言里的身份、目标、否定、偏好、改口和确认 | 提供原生工具 schema，映射字段，URL 编码，返回实际结果 | 搜索客户和维护业务数据 |
| 选工具、查事实、追问缺项、收集完整清单、复述后等确认 | 保存 SDK 消息及工具 call ID；不生成假的 user 或候选 JSON | 校验订单状态、商品／支付资格并执行变更 |
| 根据工具结果继续判断、回复和转人工 | 数值计算、列表长度校验、一次请求与错误传播 | 评分与真实费用计量 |

明确取舍：身份来源、单客户范围、条件理解、复述及确认是模型必须遵守的政策，不声称有一套独立代码已经证明它理解正确。没有 `confirmed=True` 工具参数，也没有隐藏的确认生成器。后端业务约束不等于后端能证明用户真的确认；实际模型行为仍须评测。

## 删除和恢复

删除旧 `agent/support_agent/`（包括旧语义候选桥）、旧 `docs/` 里程碑／报告、旧 `tests/` 及夹具，以及 10 个旧专用需求／证据／批次脚本。重新建立当前文档和少量协议集成测试，重写根 README 与 PROJECT。保留原始官方材料、接入／上传脚本、现有绑定 YAML、许可证、Git 历史及本地 SDK。

删除前将 217 个受 Git 管理或未忽略的源文件保存到仓库内被忽略的 `.test-tmp/before-agent-restart-20261026.zip`，含上轮未提交的 import 修改；逐项解压读取并核对 SHA-256 通过。原始文件可从该快照或 Git 恢复。快照不上传、不提交，不包含仓库外权限文件或 `.venv/`。

旧 1163／522 计数不沿用到本实现，也不为保住旧通过数保留旧路由或改写旧预期。上一轮实际 t2 已由用户确认手动停止；其中 2 个案例为业务未通过，132 个未执行。截图只证明旧入口进入通用“语言理解不可用”分支；此前把“模型没有返回候选 JSON”直接定为唯一运行根因，证据不足，因为没有取得模型原始响应或异常栈。本次删掉该脆弱协议是架构决定，不将其包装为远程根因已唯一确证。

## 课堂接口适配

以保留的 `materials/client_api/openapi.yaml` 为提交契约。工具保留 tau2 熟悉的名称，但 `user_id` 参数映射到 REST 的 customer_id；name/zip 搜索映射 postal_code；地址映射 address_line_1／address_line_2／region／postal_code；两列原／新 item ID 按原顺序转换成 replacements，既不排序也不静默截短。转人工 ID 只取 ClientAPI.context。

公开工具派发统一输出 JSON 文本一次，避免已安装 Environment 将对象内的数字和布尔值递归转成字符串。正常金额、布尔值和 null 保持类型。工具不做封闭回执字段判定，不因新增无关字段把成功强制变 Unknown。未知变更结果不自动重试的要求写入政策；本实现不声明跨进程 exactly-once 或持久化去重。

计算器只解释有界数值 AST，不调用 eval。模型调用固定参数由平台注入；模型名称取运行时允许列表，`one_of` 明确选择一个允许值。没有固定 max_tokens 或本机模型密钥。模型错误不被吞成业务拒绝，也没有自动模型重试。

## 本地验证

测试通过真实的 ModelGateway 配置检查、固定参数注入和账本入口；替身放在底层推理函数。另经真实候选 broker 序列化消息与完整函数 schema，不是用 Mock 替掉整个 ModelGateway.generate。工具测试通过 ClientAPI、公开 REST catalog、实际上游 RetailTools 和 Environment.get_response，使用自造用户／商品／订单，直接断言后台状态。

本轮没有网络请求或真实模型推理。上述测试不证明描述理解、政策遵守、真实平台案例或成本。不存在“本地测试通过即可收口正式业务”的结论。

最终运行：`.venv/Scripts/python.exe -B -m unittest discover -s tests -v`，`Ran 20 tests in 11.491s`，独立汇总行 `OK`，零失败／错误／跳过，退出码 0。日志保存在被忽略的 `.test-tmp/restart-verified.log`。20 项由 18 个模型／工具协议集成检查和 2 个上传包检查组成；不是 20 个真实模型任务或正式业务案例。

隔离测试把部署目录复制到临时目录，用 `-I -B` 启动新解释器、移除 PYTHONPATH，确认入口／工具来自复制目录，读取复制的政策并通过实际 ModelGateway 调用一次底层替身；网络审计在导入 SDK 前安装。正式 Python 收集器实收且只收 `agent.py`、`tools.py`、`policy.md`、`agent.json`、`THIRD-PARTY-NOTICES.txt` 五项；当前原始字节总计 21,210，最大文件 11,224 字节。它们不依赖仓库的 tests、scripts、materials 或已删除的 support_agent。

开发首轮暴露 Windows 默认 GBK 解码政策失败，改为显式 UTF-8；付款测试误以最后一条交易为新付款，而上游最后一条实际为原路退款，改按 transaction_type 和 payment_method_id 查找并核对金额。生产付款算法及其预期业务结果未被修改。随后的完整运行通过；旧失败不计为通过。

`git diff --check` 通过。本页本地结果不扩大为模型质量、课堂通过、成本或事务到账的证据。Agent 沿用运行时注入的首个模型；用户已告知在平台配置 Kimi K2.6 国内 API，本项目没有在源码中覆盖平台模型、地址、密钥或案例范围。是否实际按该路由执行仍需平台运行证据。
