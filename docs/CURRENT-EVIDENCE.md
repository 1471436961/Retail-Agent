# 当前离线证据

唯一当前计数来源为成对校验后的 FOUNDATION-RUN 与 AT-TEST-TRACE；其余文档入口链接到本页，里程碑交付记录属于历史版本。

<!-- CURRENT-EVIDENCE:START -->
实际完整回归 **961/961**，零跳过/失败/错误、退出码 0。原生 SDK＋合成后台对话 **23** 组，75 个 user 轮次、204 次 HTTP 调用、21 次业务发送。

计划保留 134 案例／522 AT；关联 31 个不同 AT、33 条关联关系，491 条尚未关联首批对话。完整业务 AT 执行 **0**；全部本地业务验收由 M6.7 收口，课堂正式评分由 M7 单列。

run_id `37a6eb3c75f647f49450172e3350a5f1`；source_sha256 `871a53472b1f736a382a757fe6c25deac36262a88aa58892127acad7c08b87be`；specification_sha256 `b69229eb3c9487395f6b256729e5d2c37a700a95c968321ca502648a1de4032a`。
<!-- CURRENT-EVIDENCE:END -->

使用 `python -B scripts/evidence_docs.py --update` 从与当前输入匹配的通过报告更新，随后 `python -B scripts/evidence_docs.py` 验证。同 run/source/spec 校验、当前块和六份入口引用均须通过；普通 unittest 不负责刷新文档。此元数据不是签名，不保证整体人工伪造的报告可被识别。

M6.1 有限交付见 [交付记录](M6.1-DELIVERY.md)，该批已按用户授权分三次提交推送。M6.2 有限组合及只读汇总已完成，见 [交付记录](M6.2-DELIVERY.md)，尚未提交推送，等待 review；生产代码、schema 和工具库存不由证据脚本改变。完整本地业务验收归 M6.7，正式平台评分归 M7。
