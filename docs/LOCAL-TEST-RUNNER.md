# Windows 本地离线测试入口

2026-10-03：新增 [test-local.ps1](../scripts/test-local.ps1)，负责将测试临时文件放在仓库内并清理。它不改变 TemporaryDirectory 的建目录 mode，不能单独解决下文的 Windows 0o700 问题。后续通过测试专用 helper 调整四处建目录调用；业务代码、测试断言、系统环境变量、执行策略和现有 ACL 不变。脚本要求 PowerShell 7+ 和项目 `.venv\Scripts\python.exe`；解释器缺失直接失败，不回退到其他 Python，也不跳过 SDK 检查。

在仓库根目录运行完整套件：

```powershell
pwsh -NoProfile -File .\scripts\test-local.ps1
$LASTEXITCODE
```

指定一个测试文件时：

```powershell
pwsh -NoProfile -File .\scripts\test-local.ps1 -Pattern 'test_case_trace.py'
$LASTEXITCODE
```

脚本从自身路径确定仓库位置，使用项目解释器运行 `-B -m unittest discover -s tests -p <pattern> -v`。stdout/stderr 原样显示，unittest 进度写入 stderr 是正常行为；以原生退出码判断结果，不根据 PowerShell 的流类型判断失败。默认 pattern 为 test*.py，不缩小完整测试范围，不发起远程评测或真实模型调用。

每次运行在仓库 `.test-tmp/run-<随机标识>` 创建独立目录，只为子进程设置 TEMP/TMP/TMPDIR。Python tempfile、测试 helper 和 SDK 包装启动的子进程继承这些值；调用方环境保持不变。`.test-tmp/` 已加入 Git 忽略，不属于 agent 部署包。

正常结束或可捕获异常时，finally 检查绝对目标仍在预期的普通临时目录内，再清理本次运行目录；拒绝临时根目录或运行目录为重解析点。保留空的 `.test-tmp` 根目录，不删除其他运行目录。子进程非零退出码原样返回；启动异常返回 1；清理失败使原本成功的运行返回 1。强制结束整个启动器或主机中断可能留下本次目录，脚本不自动删除其他运行的遗留数据。

## Windows 临时目录 mode 修订

用户转交的评审报告给出同一评审环境内的对照：TEMP 已指向仓库时，mkdtemp/0o700 建目录成功但写入失败，普通 mkdir/0o755/0o777 则可写；实验性全局 mode 注入后受限套件通过。这否证了“只重定向 TEMP 就能解决该环境写入问题”。这些实验属于评审报告证据，不作为本会话独立复现结果。

机制依据：[CPython 3.12.13 tempfile 源码](https://github.com/python/cpython/blob/v3.12.13/Lib/tempfile.py) 的 mkdtemp 使用 os.mkdir(path, 0o700)；[Python Windows mkdir 文档](https://docs.python.org/3.12/library/os.html#os.mkdir) 明确 0o700 专门设置访问控制，其他 mode 值忽略。此处 0o777 用于普通目录创建、保留父目录 ACL 继承，不按 Unix 的权限位解释，也不修改现有目录 ACL。

正式修订使用共享 [temp_dirs.py](../tests/temp_dirs.py)：Windows 在 tempfile.gettempdir() 下，以 UUID 名和 os.mkdir(path, 0o777) 原子创建目录，正常及异常退出时校验确为已知父目录下本次创建的普通目录，再清理；重解析点或路径变化拒绝递归删除。其他系统保留标准 TemporaryDirectory。仅替换 [test_case_trace.py](../tests/test_case_trace.py) 三处和 [test_m1_adapter.py](../tests/test_m1_adapter.py) 一处调用，不改断言或包装 SDK，不新增测试计数，不安装 sitecustomize、不全局改写 mkdir。

直接运行原测试命令也会使用 helper，不依赖 TEMP 重定向：

```powershell
& '.\.venv\Scripts\python.exe' -B -m unittest discover -s tests -v
$LASTEXITCODE
```

## 本会话验证与评审环境证据

- helper 修订后，直接命令在非受限模式实跑 **266/266、零跳过、退出码 0**，当次 22.731 秒，仅为观测；未重定向 TEMP/TMP/TMPDIR。涉及临时文件的四项及真实 SDK 包装均包含在完整运行中，SDK 子检查不相加。
- 用户随后授权提交推送：测试环境 53ee070、M3.4 源码 2413049 已逐批推送。源码提交后核对 agent/tests 与 HEAD 一致，直接命令在非受限模式实跑 266/266、零跳过、退出码 0，当次 22.559 秒；仍有待提交文档，不称为另一完全干净检出。来源与推送回执详见文末交付记录链接。
- Windows helper 的两个独立烟测通过：实际 mkdir 审计事件均为 0o777，文件写入/读回成功，正常与主动抛异常后目录均清理，异常正常传播，os.mkdir 对象未被全局改写。烟测不加入 266 的计数。
- helper 修订前，启动脚本在非受限模式实跑 266/266、23.276 秒；调用方环境未变、运行目录清理通过。此项是当时版本的历史记录。
- 本会话 2026-10-03 的受限观测：PowerShell 7.6.5 可以启动脚本，但项目 uv trampoline 在启动 Python 子进程时被拒绝，未进入测试；脚本返回 1、环境未变且清理完成。直接启动配置中基础 Python 的该次尝试同样被拒绝。最新默认受限解释器探针仍报相同启动错误，不能据此判断目录 mode 修订的受限执行效果。
- 早前评审会话报告的 shell 为 Windows PowerShell 5.1，Python 可启动后发生写入拒绝。5.1 直接调用本脚本不满足版本要求；若已安装 PowerShell 7，可从 5.1 使用上述 pwsh 命令，否则可直接运行项目 Python 命令。没有为了兼容修改全局执行策略或安装 PowerShell。
- 用户随后转交的新一轮评审报告：正式 helper 在评审会话受限模式下，通过原命令直接实跑 **266/266、零跳过、零 FAILED、退出码 0**，无提权、无 TEMP 重定向、无补丁或注入。报告另核对 PYTHONPATH 为空、仓库无 sitecustomize.py、.test-tmp 为空且不在 sys.path 中；真实 SDK 包装包含在主套件，不额外计数。此项登记为评审环境的正式 helper 通过证据，不是本会话独立执行，也不是早前 sitecustomize 实验的结果。

正式 helper 的受限完整通过证据现已由评审会话提供，测试目录 mode 修订可按该范围收口。解释器启动失败和目录创建后的写入失败仍是两种观测，不合并为受限模式的通用根因；本会话此前的启动失败及非受限通过保留对应执行来源，没有修改解释器、虚拟环境或运行时 ACL，也不将实验注入通过当作正式 helper 的通过。启动脚本仍是可选便利入口。M3.4 的业务交付范围仍见 [交付记录](M3.4-DELIVERY.md)，M3.5 未开始。
