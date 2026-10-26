# 换货工具返回后的续轮审计

日期：2026-10-26。审计起点为 `ef7a032`，本轮实现提交为 `2a84a0d`；本页记录本轮观察、离线复现、代码加固及其适用边界。之前的工具设计和测试基线见 `docs/PREFERENCE-RANKING.md`、`docs/AGENT-COMPLETION.md`。

## 远程记录能够说明什么

用户提供的最新记录已经调用 `rank_preferred`，原商品与新 SKU 的对应关系、差价及客户确认相符；随后 `exchange_delivered_order_items` 得到 HTTP 200，记录在工具返回后结束，没有最终 Assistant。本轮不能继续把这条记录描述为“未使用排序工具”，也不能据此要求重复选择商品或重复写入。

现有远程 report/log 只有结果摘要、`checks:null` 等信息，没有实际 `termination_reason`、调度步数、宿主 `max_steps` 或写入后的推理错误明细。因此：

- 工具成功不等于整个会话已正常结束，也不保证完成后的下一次 Agent 回调发生。
- 没有最终 Assistant，与步骤上限、超时、后续模型调用异常或其他中断均可能相容；这些仍是待区分的路径。
- 本轮加固修复可证实的本地问题，不声称已经找到或解决这次远程失败的根因。

## 核对的运行时与契约

通过 `rg -uuu` 和直接读取检查了通常被忽略的 `.venv`。实际 Python import 来自 `.venv/Lib/site-packages/tau2`；`.venv/Lib/site-packages/tau2-1.0.1.dist-info/direct_url.json:1` 指向 `.venv/tau2-source-6e9f34c685d4`。以下已安装文件与该固定源码 `src/` 下对应文件的 SHA256 分别完全一致：

- `tau2/hyper/sandbox/candidate_server.py`
- `tau2/hyper/sandbox/sealed_runner.py`
- `tau2/orchestrator/orchestrator.py`

这只确认了本地已安装 SDK 与本地固定源码的一致性。远程报告给出了镜像标识 `hyper-lab-v1-2297563ae062b883e80e66e1225ff2babfb9bec2e88bf18f68bb092544f8ca5b`，但没有其内部 SDK 提交或逐文件哈希，不能据此把本地 SDK 行为称为已验证的课堂镜像行为。

`materials/framework/agent_contract.md:47` 要求 `get_init_state(message_history=None)` 与 `generate_next_message(message, state)`；`:65` 起明确允许可选 `is_stop`、`set_seed`、`stop`，未提供 `is_stop` 时默认不主动停止。`reference/platform-starter/agent/support_agent/application.py:12` 的示例仅实现两个必要方法，这种省略本身合法。

本地实际运行时也支持这些钩子：

- `candidate_server.py:445` 初始化工厂、传入历史，`:474` 保存 Agent state；`:485` 每轮调用 Agent 并更新同一份 state。
- `candidate_server.py:496` 将 `agent_is_stop` RPC 转给可选 `is_stop`，未提供时返回 `False`。
- `sealed_runner.py:871` 的 `SealedCandidateAgent` 在候选进程内初始化 Agent，host 只保留代理 state；`:884` 取回 Assistant 并由 host 重设时间戳；`:904` 经 RPC 查询 `is_stop`。

以上文件均位于 `.venv/Lib/site-packages/tau2/hyper/sandbox/`。当前 `finish_response` 转成最终文本再通过 `is_stop` 停止，符合这个协议；它必须先获得一次实际 Agent 回调才有机会生效。

## 真实 Orchestrator 的边界复现

`tests/test_agent_completion.py` 中 `test_native_orchestrator_reaches_agent_stop_after_rank_write_and_final_response` 使用合成订单、真实 SDK 和本地 REST runtime，模型响应由脚本替身提供。流程为：客户请求 → 组合上下文 → 两个排序结果 → 完整复述 → 客户确认 → 一次批量换货 → 最终回复。

审计通过内存包装构造函数，分别向同一场景注入 `max_steps`；没有改生产预算或已安装 SDK，没有调用真实模型。结果为：

| 注入上限 | 实际完成步数 | 轨迹末尾 | 最终终止原因 |
| --- | --- | --- | --- |
| `9` | `9` | 成功的换货 ToolMessage；下一接收者已为 Agent，但没有下一次回调 | `MAX_STEPS` |
| `10` | `10` | 已有最终 Assistant | `MAX_STEPS` |
| `11` | `10` | 已有最终 Assistant | `AGENT_STOP` |

`9` 的最后三条消息恰为客户确认、`exchange_delivered_order_items` 调用、`status="exchange requested"` 的成功结果。此时即使脚本已经预设下一条为 `finish_response`，也不会被读取。这说明仅增加结束动作不能修复“下一次 Agent 调用之前被宿主截断”的路径。

`10` 的结果还揭示另一个本地边界：在这个特定流程中，最终回复正好是第 10 步，`step()` 先设置 `AGENT_STOP`，随后终止检查又将原因覆盖为 `MAX_STEPS`。不能把“10 步内出现最终文本”写成“`max_steps=10` 可正常得到 `AGENT_STOP`”。上限为 `11` 时，同一流程在第 10 步正常保留 `AGENT_STOP`。这些数值来自人为控制的合成实验，均不是远程课堂限制。

对应源码为 `.venv/Lib/site-packages/tau2/orchestrator/orchestrator.py`：

- `:282` 的循环在每次 `step()` 后调用 `_check_termination()`。
- `:859` 生成并验证 Assistant，`:861` 查询 `is_stop`，`:865` 将 Assistant 加入轨迹。
- `:880` 执行工具，`:884` 将结果加入轨迹，再包装后送回 Agent。
- `:741` 仅在“将要执行环境工具”时跳过终止检查；工具已经返回、下一接收者为 Agent 时，`:745` 会检查上限，且不会因 `self.done` 已为真而跳过该赋值。

此前完成测试使用默认上限，且预设下一次 provider 一定返回 `finish_response`。它证明的是“后续回调实际发生且模型选择结束时，协议能够收尾”，不能证明远程在工具结果之后一定会再次调用 Agent，也不能证明真实模型一定选择结束动作。手写 `ProtocolAgent` 调用 CandidateServer 的测试也没有覆盖真实进程 IPC 的全部路径。

## 异常与评分的结论边界

后续模型调用异常同样可以留下“写入成功但没有最终 Assistant”：

- `agent/support_agent/application.py:68` 调用模型网关，异常保持可见，不生成假业务回复。
- `.venv/Lib/site-packages/tau2/hyper/sandbox/candidate_server.py:574` 将异常编码为 RPC 错误，`sealed_runner.py:410` 在 host 重新抛出。
- `.venv/Lib/site-packages/tau2/orchestrator/orchestrator.py:282` 的循环异常退出时仅执行资源清理，不补充最终回复。
- 空 Assistant 会在 `orchestrator.py:860` 的验证中抛错；空内容规则见 `.venv/Lib/site-packages/tau2/data_model/message.py:291`，此时还没执行 `is_stop`。

本地 `.venv/Lib/site-packages/tau2/evaluator/evaluator.py:141` 对不是 `AGENT_STOP` 或 `USER_STOP` 的运行直接返回 `reward=0.0`，不继续具体断言检查。这提供了一条可与“0 分且检查为空”相容的本地路径，但没有证据证明远程报告的 `checks:null` 就由该分支产生，也没有证明远程采用相同评分器版本。

换货投影也须单独判断。本地参考工具先按请求中对应的原／新商品检查并计算差价，随后将 `exchange_items` 与 `exchange_new_items` 独立排序（`.venv/Lib/site-packages/tau2/domains/retail/tools.py:253`、`:278`）。REST `_order_exchange` 再 `zip` 这两个数组（`.venv/Lib/site-packages/tau2/hyper/client_api/catalogs/retail.py:377`），因此展示出来的配对可能变化。REST 请求参数的原始配对转换见同文件 `:482`。

独立排序后的展示问题，不能单独证明正确请求对应的后台状态错误，不能证明真实评分因此失败。之前的合成核对中，正确请求与参考动作产生的后台状态、DB 哈希可以一致；远程失败断言仍然缺失。

## 本轮代码加固与保留的执行边界

本轮生产代码的新增加固集中在 `agent/support_agent/application.py` 和 `agent/support_agent/state.py`：

1. 结束判断改为可持久化的消息元数据。`state.py:8` 定义带版本的 `retail_agent_control` 标记；`:19` 在转换显式 `finish_response` 时写入 `AssistantMessage.raw_data`，保留其余模型元数据；`:11` 由该标记、非空最终文本和无工具调用共同判断结束。JSON 序列化、SDK 消息往返和历史恢复后仍可识别，不再依赖 Agent 实例上一次回复的临时字符串。`:44` 恢复历史时也重建完成状态。
2. 显式拒绝供应方标记的不完整响应。`application.py` 的 `_require_complete_response` 检查 `raw_data.status == "incomplete"` 或 SDK 实际选中的 `choices[0].finish_reason == "length"`，在处理任何建议工具前抛出明确异常。未被采用的备选响应不会影响当前消息。部分生成的写工具或 `finish_response` 不会被派发，不伪造成功回复，也不自动重试。这个检查只针对实际收到的明确元数据，不推断供应方未提供的原因。

业务 API tools、原／新商品批量参数、REST 路由和宿主限制未作修改。所有对外业务读取和写入仍作为 Assistant 工具调用交给宿主执行；候选 Agent 不在 `generate_next_message` 内直接执行 READ 循环，也不在内部隐藏多轮模型调用。

保留宿主分派的原因是实际平台边界可审计：`.venv/Lib/site-packages/tau2/hyper/sandbox/sealed_runner.py:660` 在工具结果上附加 canonical Client API 的 `semantic_tool_calls`，`:680` 用这些操作回放；`:58` 在交给候选 Agent 的消息中移除 trusted-only semantic 元数据。本轮没有为了减少表面步数而绕过这条执行与记账路径。

上述加固改善完成信号的持久性，并阻止明确不完整响应中的工具执行；它不能强制宿主进行下一次回调，不能绕过步骤或时间限制，不能消除模型网关错误，也不构成远程案例已经修复或通过的证明。

## 验证与后续信息

本轮审计已完成实际 SDK／固定源码核对和上述 `9`、`10`、`11` 上限的纯离线合成复现。最终执行 `.venv/Scripts/python.exe -B -m unittest discover -s tests -v`：`Ran 67 tests in 13.719s`，独立汇总 `OK`，零失败／错误／跳过，退出码 0；日志为 `.test-tmp/continuation-audit-tests.log`。此前首次 66 项全绿后，代码复核发现不应由未选中的第二个模型候选的 `length` 状态拒绝有效的第一候选，修为仅检查 SDK 实际选中的第一项，并增加反向负控后完成这次 67 项运行。

新增 `tests/test_completion_boundary.py` 共 11 个方法，包含：真实 `ModelGateway → llm_utils.generate → completion` 响应解析（仅底层提供商和模型路由为替身）、不完整写调用拒绝、半句回复拒绝、未选中候选不误阻断、单次推理／零工具派发、完成元数据与原响应保留、全新 Agent 的历史恢复、正文及用户／工具消息不触发结束，以及 `9`／`10` 的宿主边界负控。它们没有以“写成功”代替“正常终止”，也没有将已知中断场景改成正常完成的预期。

本轮没有发起新的课堂评测，没有付费模型调用，也不会因为结果缺少原因而自动重跑。若后续取得远程原始终止原因、实际步数／上限、候选进程错误或工具返回后的模型调用记录，应据此区分具体路径，再判断是否需要新的生产修改。
