# M7：t1 已核验，t2 进行中

本页以下接入与远程结果属于重构前提交快照。2026-10-08 用户另行要求全面重构自然语言入口和工具边界；实际代码变化见 [M7 重构记录](M7-REFACTOR.md)。旧 t1 成功和旧模型未启用声明不证明新代码已远程通过，重构后尚未发起付费复验。

2026-10-07 用户先选择“保持 t1，仅完成接入验收”，已完成下述核验；随后明确要求开始 t2。当前授权范围为 retail_plus／Python／全部 134 案例，仅使用现有平台额度、不追加、不自动重跑。M7 整体尚未完成；下述 t1 成功不等于正式业务、真实模型效果或费用已验收。

## 仓库、提交与运行范围

- 项目：`E:\Retail-Agent`；仓库：`1471436961/retail-agent`；分支：`main`。
- 当前提交：`254701659aefb07d53171fbc8a678f6f207e7063`。
- 2026-10-07 接入时绑定：`da37778d-769a-41ed-8c78-8eb4b91be977`；场景／语言／任务：`retail_plus`／Python／`t1`；`case_ids: null`。t1 的 null 不代表全量 134 个业务案例；2026-10-08 同一绑定的 t2 实际范围另见下文正式回执。
- 当前接入提交只含 `.github/workflows/hyper-lab.yml`、`hyper-lab.yml`、`GITHUB-SETUP.md`，已由用户明确授权提交推送。M6 Agent 实现保留。

本轮重新核验上述当前提交的实际成功回执，没有创建新提交或再次启动评测。报告记录的 commit 与 GitHub 运行的完整 SHA 相同；但平台回执 `commit_verified=False`，不能表述为平台已独立验证 Git 提交。这项核验不冒充一次新的远程执行。

## 本轮实际检查

| 检查 | 实际结果与范围 |
|---|---|
| 工作区与暂存区 | 开始时 `main...origin/main`，无工作区变更、无暂存文件；凭证和原始 ZIP 位于仓库外 |
| M6 已发布证据 | `scripts/evidence_docs.py` 返回 `CURRENT_EVIDENCE_PASSED`；成对来源／规范／run 与当前文档入口一致。未重新运行完整 1151 方法或改写 M6 报告 |
| 部署包 | 既有 `local_package_audit.audit_package()` 实际通过：57 文件，485,852 原始字节，最大文件 50,097 字节；Python 收集文本 481,554 字节 |
| 固定上传信封 | 既有审计的 Node／Python CI 固定 JSON 分别为 515,661／510,624 字节；不是本轮远程 HTTP 请求正文的抓包或签名 |
| SDK 包装专项 | `ProposalRecoveryTests.test_model_projection_and_application_adapter_use_real_sdk_offline` 实际 `Ran 1 test`、`OK`、零跳过、退出码 0；14.157 秒。包装检查真实 SDK 消息／工具注册和既有完成 marker，后台及网关为离线替身，实际路径网络尝试为 0 |
| 当前远程运行 | GitHub API 重新确认 `37605086821` 为 completed／success，提交 SHA 与本地当前提交一致；本地回执 task=t1、status=done、total=1、passed=1 |

SDK 首次调用误加 `-I`，使该脚本无法导入同目录的 `test_m3_proposals`，退出码 1；随后按已有测试包装入口复验通过。修正的是本轮调用方式，未修改生产代码、SDK 脚本或断言；首轮不计为通过，也不登记成业务缺陷。

## 真实 t1 回执

- GitHub 运行：[37605086821](https://github.com/1471436961/Retail-Agent/actions/runs/37605086821)。北京时间 2026-10-07 18:05:38 创建，18:06:28 更新为完成。
- 平台 Job：`9369977f-03fa-45b9-83da-de473d52a060`；[平台结果](https://agentist.org/lab/enterprise-ai?run=9369977f-03fa-45b9-83da-de473d52a060)。
- 案例：`public-customer-lookup`，passed；`identity_verified_before_details=True`。
- 结果：1 个接入案例，1 passed、0 未通过；GitHub 工作流 success。
- 平台报告的上传快照 SHA-256：`987959665c9b00ba46b383daa840bcf6945fb1a647e36e02bfb53dcbee4b9e70`；环境标识：`hyper-lab-v1-90c863ee6bf1ee8c9b72c6a58a6066d8730c713b6cbd7d0f785cf1e158bc6f4f`。这些报告元数据不证明整个课堂镜像与本地 SDK 一致。
- 本地回执：`.git/enterprise-evaluations/37605086821/report.json`；SHA-256 `a7ce06c0fbfcbce77f30a71ed4735f9d611f0d65ff727d4dba25bc64472537be`。此内容哈希不是签名；文件不提交到业务包。

t1 证明这个公开身份查询入口能调用课堂环境 API，不能证明完整订单业务、134 个正式案例通过、后台事务或到账。

## 模型、费用与后续范围

默认 `create_agent()` 保留确定性入口，未注入 `ModelAdapter`；本轮没有启用或调用真实模型。实际回执没有提供模型用量／计费证据，因此费用仍为未实测，不能写成零成本。

t1 接入子步骤已核验。用户随后明确选择手动提交 t2；当前 push 绑定仍为 t1。现有 GitHub 工作流只传 binding-id，没有声明 task 覆盖参数；手动入口 `scripts/evaluate.mjs --task t2` 则使用个人评测凭证，向 `/v1/evaluations` 上传 Agent，不携带 GitHub binding-id。两条入口不能混为一谈。不将 t1 的 1/1 计入 t2 的 134 案例结果。多对换货配错、封闭回执、完整复述预算和共享内存认领的边界继续见 [M7 输入清单](M7-INPUT-BOUNDARIES.md)。

## 手动 t2 提交观察（2026-10-07）

用户授权手动提交后，核对 Node v24.15.0、`agent.json` 的 Python／retail_plus，以及既有包体审计：57 文件、485,852 原始字节、最大单文件 50,097 字节；凭证／依赖及固定信封检查通过。由既有官方 `scripts/evaluate.mjs` 读取仓库外 `E:\Enterprise-AI.json`，未输出凭证；运行 `node --use-env-proxy scripts/evaluate.mjs --task t2`。仅对子进程设置既有代理，未改变系统配置。脚本只上传 `agent/`，未提供案例子集，未提交或推送文档，未修改 Agent／绑定。

实际打印 task=t2，提交幂等键为 `ae8e9230-e86d-48a9-82f7-f88f19a6bae6`，随后返回 `Evaluation HTTP 503`，进程退出码 1。该退出码是客户端错误退出，不能作为业务用例失败判定。未取得 Job ID、结果链接、案例通过／失败数、模型配置或计量回执；不能声称 0/134、无费用或后台绝未创建任务。该脚本不保留 HTTP 错误正文，本次可证事实限于 503 状态及上述客户端输出。

按既定失败处置已停止，没有第二次提交、自动重跑或改绑定。本次手动路径不携带旧／当前 GitHub 绑定 ID，不能仅以旧绑定残留解释失败；503 的具体服务端原因仍未知。M7.3–M7.6 的正式业务验收尚未完成。

## 用户重新授权的指定 Python 入口（2026-10-07）

用户指出其指定的是 `lab_eval.py`；上一次实际执行 Node 客户端是入口选择错误，不能将 Node 的返回值冒充 Python 运行结果。经用户“向我提权执行”的明确授权，一次性启动器读取仓库外权限文件，仅在内存及子进程环境中设置认证信息，没有打印、落盘或提交凭证。启动器明确清除 `HYPER_LAB_BINDING`，运行现有 `scripts/lab_eval.py submit --task t2 --domain retail_plus --source manual --project E:\Retail-Agent --wait`，没有修改脚本或 Agent。案例参数未提供，Python 请求的 `case_ids` 为 null。

此次实际终端输出为 `Evaluation client: Evaluation API returned HTTP 503`，外层命令退出码 1。Python 的 POST `/v1/evaluations` 未取得可读取的 Job ID，故未进入结果等待，也未生成该次评测报告。案例计数、费用和服务端具体原因仍未知。此次为用户纠正入口后重新明确授权的一次提交，不是自动重跑；返回 503 后停止，未再次提交。Node 与 Python 两次手动提交的事实分别保存，不将其计作业务案例失败，也不据此声称平台完全未产生效果。

## 平台绑定更新后的授权运行（2026-10-08，已结束／取消）

用户明确告知已在平台将绑定设为 t2，并要求现在试一次。本地及远程 main 均为 `254701659aefb07d53171fbc8a678f6f207e7063`，现有工作流使用绑定 `da37778d-769a-41ed-8c78-8eb4b91be977`；启动前未发现运行中的评测。按授权仅执行一次 `gh workflow run hyper-lab.yml --repo 1471436961/retail-agent --ref main`，没有创建 commit、push 或修改 Agent／绑定。

实际创建 [GitHub 运行 37719441669](https://github.com/1471436961/Retail-Agent/actions/runs/37719441669)，北京时间 2026-10-08 10:45:36，event=workflow_dispatch、head_sha 与上述版本一致；10:55:30 工作流 completed／failure，提交与等待步骤退出码 2，报告上传成功。身份校验及源码检出通过，此次未在提交阶段返回 503。

Parallight Lab 最初仅提供运行中的本人摘要，未给 GitHub run ID，故当时未以相近时间确证关联。随后通过官方 `lab_eval.py result --job-id ...` 仅读取同一任务的回执，确认 github.run_id=37719441669、commit_sha 与上述版本一致；此查询只有 GET，没有第二次提交。最终又下载该 GitHub 运行的正式 artifact，独立核对同一关联。

最终 [平台 Job d67137b4-14fb-494b-8c06-e04f92b686e1](https://agentist.org/lab/enterprise-ai?run=d67137b4-14fb-494b-8c06-e04f92b686e1) 的 task=t2、domain=retail_plus、language=python，case_ids 完整包含 0–133，共 134 案例。status/phase=error、report.verdict=cancelled、cancel_requested=true；平台完成时间为北京时间 10:55:24.187343。回执本身未说明取消发起者；随后用户明确确认“是我手动取消的”，故本轮终止原因记录为用户手动取消，依据为用户确认。助手没有发出取消请求，不将取消解释为额度耗尽或平台故障，也不因此抹去取消前已记录的案例错误。

| 正式回执分类 | 数量与范围 |
|---|---|
| 已执行／completed | 18／134 |
| passed | 0 |
| candidate_error | 17：0–14、16、17 |
| failed | 1：15 |
| not_run | 116；不能记为业务失败 |
| score_percent | null；没有正式完整评分 |
| infrastructure_errors | 报告字段为 0；该分类不构成候选错误根因已确定的证据 |

candidate_error 只给通用反馈 `Candidate execution failed; check the Agent interface and tool implementation.`；案例 15 只给 `Business assertions were not all satisfied. Inspect the conversation and tool results.`。当前正式 artifact 没有异常堆栈或完整对话／工具轨迹，尚不能定位具体实现或兼容性问题，不修改正确预期来适配失败。平台报告未包含模型／usage／cost 字段；费用未知，不登记为零或已验证额度符合。commit_verified=false，不能扩大为平台已独立验证 Git 提交。

正式 artifact 名称为 `enterprise-ai-254701659aefb07d53171fbc8a678f6f207e7063`，ID=11525079407；保存于 `.git/enterprise-evaluations/37719441669/github-artifact/report.json`，文件 SHA-256=`2894e8e425a025d7158395617ce3922412cfae442c20f4db79b688b6dd16ea2b`。上传快照 SHA-256=`987959665c9b00ba46b383daa840bcf6945fb1a647e36e02bfb53dcbee4b9e70`；environment_version=`hyper-lab-v1-90c863ee6bf1ee8c9b72c6a58a6066d8730c713b6cbd7d0f785cf1e158bc6f4f`。这些标识与 t1 回执一致，但不能证明 t1 与 t2 执行路径或全部课堂组件一致。

失败后已停止，无自动重跑、补充提交、源码修复或绑定修改。M7 整体未完成；后续首先需要具体候选异常及案例 15 的断言／对话证据，再决定修复范围与另获授权的复验。本轮只更新文档，原 M6 本地 1151 方法／522 原子验收的证据与这次真实 t2 结果分列。

本轮变更仅为本说明、实施计划的范围／状态及当前证据页的 M7 入口；Agent、固定业务场景、预期和 M6 成对工件不变。文档尚未提交推送。
