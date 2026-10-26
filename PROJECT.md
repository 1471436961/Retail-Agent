# 项目结构

生产代码与策略仅在 `agent/`。入口是 `agent.py:create_agent()`，工具是 `tools.py:Tools`；`policy.md` 是模型的业务政策。

`tests/test_agent.py` 检查模型／工具协议及实际 SDK／零售后端；`materials/` 保留官方接口资料；`scripts/` 保留官方提交与终端客户端。设计和本次验证见 [docs/RESTART.md](docs/RESTART.md)。

不要重新添加自然语言意图解析器、客户命令语法、模型候选 JSON、工作流快照参数或与模拟输出绑定的大型验收器。描述理解、选择工具、追问和确认判断交给模型；工具代码只承担参数形状、REST 映射、执行与计算等明确职责。
