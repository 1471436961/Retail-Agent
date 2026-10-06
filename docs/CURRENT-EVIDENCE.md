# 当前离线证据

唯一当前计数来源为成对校验后的 FOUNDATION-RUN 与 AT-TEST-TRACE；其余文档入口链接到本页，里程碑交付记录属于历史版本。

<!-- CURRENT-EVIDENCE:START -->
实际完整回归 **924/924**，零跳过/失败/错误、退出码 0。原生 SDK＋合成后台对话 **16** 组，43 个 user 轮次、94 次 HTTP 调用、9 次业务发送。

计划保留 134 案例／522 AT；关联 20 个不同 AT、22 条关联关系，502 条尚未关联首批对话。完整业务 AT 执行 **0**；全部本地业务验收由 M6.7 收口，课堂正式评分由 M7 单列。

run_id `abcc496e70834a60880f737573819a16`；source_sha256 `3c8b78944b5b5f1fc71f9a00b5def6a1d93014795fcc22b50f7be5ba1233d84c`；specification_sha256 `b69229eb3c9487395f6b256729e5d2c37a700a95c968321ca502648a1de4032a`。
<!-- CURRENT-EVIDENCE:END -->

使用 `python -B scripts/evidence_docs.py --update` 从与当前输入匹配的通过报告更新，随后 `python -B scripts/evidence_docs.py` 验证。同 run/source/spec 校验、当前块和六份入口引用均须通过；普通 unittest 不负责刷新文档。此元数据不是签名，不保证整体人工伪造的报告可被识别。

M6.1 有限交付见 [交付记录](M6.1-DELIVERY.md)。生产代码、schema 和工具库存不由证据脚本改变。完整本地业务验收归 M6.7，正式平台评分归 M7；当前停留 M6.1，不提交推送或开始 M6.2。
