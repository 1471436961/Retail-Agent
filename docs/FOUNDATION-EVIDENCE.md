# 离线运行与 AT 组件证据的有效性

日期：2026-10-04。由 scripts/foundation_trace.py 生成 FOUNDATION-RUN.json / AT-TEST-TRACE.json；两者只是实际离线组件证据，不是完整业务 AT、远程评测或后台结算结果。业务范围始终 134 案例 / 522 AT。

## 发布与失效

每次 CLI 运行产生新的 run_id，先将当前追踪原子替换为 status=invalid、reason=run_in_progress。运行报告进入 running，实际 unittest 执行结束后记录逐方法结果。失败、错误、跳过、输入期间变化或引用方法未通过，都不能发布 valid 追踪；脚本返回 1，并留下失败报告及同运行的 invalid 标记。invalid 文件没有旧的通过 records/groups。

成功时先构造追踪，发布前再次标记 invalid，随后依次原子替换报告和追踪。报告 status=passed / exit_code=0，追踪 status=valid，两者具有相同 run_id。每个文件通过独占创建的同目录临时文件再 replace，临时文件最终清理；不假定两个文件之间有事务或跨进程锁。中断可能留下 invalid 或两者运行 ID 不匹配，不能视为当前成功。

读方必须同时加载两份文件、当前需求与 input_snapshot，再调用 validate_evidence_pair。只看旧追踪、valid 字段、相同 source_sha256 或绿色退出码都不足以判断当前证据。相同源码也可能下一次失败，run_id 防止将旧通过追踪与新报告混配。运行 ID 是本地关联标识，不是签名或外部真实性证明。

## 摘要覆盖范围

| 字段 | 范围 |
|---|---|
| source_sha256 | agent/**/*.py、tests/**/*.py、tests/fixtures/*.json、agent/agent.json 与生成脚本自身；包括相对路径和文件字节，不含缓存 |
| requirements_sha256 | CASE-REQUIREMENTS.md 的 UTF-8 读取文本，按文本换行规范化；保留原 AT 编号及来源 |
| specification_sha256 / specification_files | 以下显式允许列表每个文件的字节 SHA-256，以及路径/摘要映射的总体 SHA-256 |

关键规格允许列表：

- materials/CLASSROOM.md
- materials/client_api/openapi.yaml
- materials/framework/agent_contract.md
- materials/framework/client_api_contract.md
- materials/framework/scenario_contract.md
- materials/framework/deployment_manifest.json
- docs/POLICY-REGISTER.md
- docs/API-CONTRACT-MAP.md
- docs/PLATFORM-CONTRACT-NOTES.md
- docs/REFUND-IMPLEMENTATION-EVIDENCE.md

开始与结束比较全部输入快照，包括代码、需求及选定规格。规格改变后旧报告不能证明新规格下通过，须重新运行；即使只是文字修改也一样。该范围不覆盖任意其他文档、所有业务材料、仓库外 raw/ZIP、权限文件或凭证，不称全仓规格快照。报告不读取 Enterprise-AI.json、.env、Git 凭证。

## 运行与范围

使用项目解释器运行 `-B scripts/foundation_trace.py`。普通 unittest 命令仍可运行，但不会刷新这两份证据。缺真实 SDK 解释器按原包装测试失败，不静默跳过；SDK 子检查已经包含于主包装测试，不与主计数重复相加。测试使用 fake API/网关，成功路径不调用真实模型或网络。

追踪中 related_components_passed 表示相关方法实际执行通过；business_result=not_executed、business_test_ids=[]、remote_result=not_run 和 business_ats_executed=0 继续保留。改变发布协议不意味着完整业务已验收，也不启用业务写路由。
