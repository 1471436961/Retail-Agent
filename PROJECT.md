# 项目结构

生产代码与策略仅在 `agent/`。保留原始多模块布局：

```text
agent/
  agent.py                         # create_agent()，取得平台上下文
  tools.py                         # Tools(CustomerTools)，平台发现入口
  support_agent/
    application.py                 # CustomerAgent，模型决定工具／回复／显式结束
    state.py                       # SessionState、JSON 消息历史
    config.py                      # 随包 agent.json 与 policy.md
    adapters/customer_tools.py     # 原生工具声明
    adapters/customer_api.py       # 注入的 ClientAPI
    domain/customer.py             # 原始示例辅助函数，当前对话不调用
    domain/preferences.py          # 结构化偏好过滤与确定性排序
  policy.md
  agent.json
  THIRD-PARTY-NOTICES.txt
```

`tests/test_agent.py` 检查模型／工具协议及本地 SDK／零售后端；所有请求／响应再由原始平台 OpenAPI 独立核查，不能只根据上游模拟后端推断兼容。`tests/test_interface_compatibility.py` 检查原入口签名、模块、工具、状态以及多工具结果往返；原始 `tests/test_customer.py` 六项检查也已恢复。`tests/test_preferences.py` 验证模型传入不同优先级时排序随之改变、硬约束／库存过滤、无隐含价格或 ID 排序，以及排序结果回到模型后再复述确认并整单提交的接线。`materials/` 保留官方接口资料；`scripts/` 保留官方提交与终端客户端。

`tests/test_agent_completion.py` 另经真实 CandidateServer 轮次／停止协议和 Orchestrator 验证正常路径的最终回复与 AGENT_STOP；模型底层响应为离线替身，预先安排了下一次回调及结束选择。`tests/test_completion_boundary.py` 独立验证被截断响应、完成标记恢复和宿主在写后终止的负控；合成上限不代表远程设置。组合身份工具、模型显式结束动作和 20 个注册工具／16 个模型可见动作的分工见 [docs/AGENT-COMPLETION.md](docs/AGENT-COMPLETION.md)，后续失败分析见 [会话审计](docs/TOOL-CONTINUATION-AUDIT.md)。不通过用户原文的关键词推断任务已完成。

首次下载的 39 个文件原样保存在 `reference/platform-starter/`，不能随业务重构再删除。这里的 t1 示例和旧 binding 仅供参考，不参与当前部署。当前接口适配及验证见 [docs/PLATFORM-COMPATIBILITY.md](docs/PLATFORM-COMPATIBILITY.md)；重建历史见 [docs/RESTART.md](docs/RESTART.md)。

不要重新添加自然语言意图解析器、客户命令语法、模型候选 JSON、工作流快照参数或与模拟输出绑定的大型验收器。描述理解、选择工具、追问和确认判断交给模型；工具代码只承担参数形状、REST 映射、执行与计算等明确职责。
