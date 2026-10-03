# 退款计算的源码证据与适用边界

核查日期：2026-10-03。针对 M3.1 的退款合计问题，补充公开实现核查，不局限于寻找文档公式。源码可以支持实现推断，但须记录固定版本、调用链及适用环境；上游行为与当前课堂 REST 后端一致性分别核实。本记录不授权业务写入，也不把未取得的代码视为不存在。

## 来源与核查方法

读取已安装 SDK 的公开 src 子树，没有读取上游业务数据、教师答案、隐藏案例或凭证，没有运行退货/取消工具。来源为 Sierra 官方 hyper-tau-bench 固定提交 `6e9f34c685d40fa7a9f5935d8970af6fd9d5f118`，tau2 1.0.1；安装来源与导出 ZIP 哈希见 [M0-SDK-CHECK](M0-SDK-CHECK.md)。

本地源码位于 `E:\Retail-Agent\.venv\tau2-source-6e9f34c685d4\src`，保持被忽略、未修改、未提交。下表链接指向上游固定提交；SHA-256 为本地所读文件的字节哈希，用于复核此次取证对象，不能单独证明课堂镜像一致性。

| 文件 | 本地文件 SHA-256 | 核查位置 |
|---|---|---|
| [src/tau2/domains/retail_plus/tools.py](https://github.com/sierra-research/hyper-tau-bench/blob/6e9f34c685d40fa7a9f5935d8970af6fd9d5f118/src/tau2/domains/retail_plus/tools.py) | `2c2488299802bee1cc22b7185fd9b601dcbf7c0d236b4eee7cab95e45e4d88c0` | 第 24 行继承 RetailTools；第 28–42 行取消委托父类；此类未覆盖退货方法 |
| [src/tau2/domains/retail/tools.py](https://github.com/sierra-research/hyper-tau-bench/blob/6e9f34c685d40fa7a9f5935d8970af6fd9d5f118/src/tau2/domains/retail/tools.py) | `9c7bee3e877cfaf9335fe95aefe1846747b6b99a1d3f1e7a202068b6435bd204` | 取消第 160–204 行；退货第 673–717 行 |
| [src/tau2/domains/retail/data_model.py](https://github.com/sierra-research/hyper-tau-bench/blob/6e9f34c685d40fa7a9f5935d8970af6fd9d5f118/src/tau2/domains/retail/data_model.py) | `98d1154081a76b09a463c46d47ae0e177164bdb671cc20c54e83b59fd20f166c` | 第 100–119 行：OrderItem.price 与 OrderPayment.amount 声明为 float |

读取了 retail_plus/environment.py 的工具选择：get_environment 使用 RetailPlusTools。没有加载其政策、任务或数据库文件。这证明固定上游版本的工具连接关系，不证明课堂 Client API REST 路由使用相同代码。

## 直接可观察事实与推断

| 问题 | 所读代码中的直接事实 | 可支持的推断及限制 |
|---|---|---|
| 退货申请 | return_delivered_order_items 校验 delivered、已存方式及商品重复次数；写入 return requested、sorted(item_ids) 和 return_payment_method_id；返回订单 | 该函数不计算退款合计，不新增退款交易或更新余额，没有可复现的退款合计累加/舍入公式。列表排序不能用作金额累加顺序的证据 |
| 取消退款 | cancel_pending_order 遍历 payment_history，逐条以原 amount/方式构造 refund；礼品卡逐笔增加余额后 round(balance, 2)，最后扩展退款记录 | 该函数不计算统一退款合计；余额舍入与合计舍入是不同操作，不能推出 round(sum, 2)。数据模型 float 类型也不能独立决定合计运算与舍入时点 |
| 取消历史类型 | 上述循环未按 transaction_type 筛选，历史 refund 条目同样进入循环 | 与当前 RF-01 的逐 charge 依据有差异，不能将其复制为本项目取消规则，也不能直接宣称当前课堂后端具有该行为。本项目继续只将 payment 条目作为 charge 依据，既有 refund 单独保留 |
| 退货退款去向 | retail/tools.py 第 702–704 行仅要求方式存在于用户 payment_methods，未限定原支付方式或开启时已保存的礼品卡 | 上游接口接受其他已保存卡/PayPal 的能力，宽于本项目 RT-02/S02 RD5 的业务许可。继续遵守原支付方式或开启时礼品卡；后端可接受不等于业务允许。M5 前核实课堂实现与现行规则的对应关系，不根据上游能力放宽政策 |

这些结论来自对固定公开实现的静态阅读，不是运行真实退款的结果，也不是平台新增裁决。没有执行上游写方法来验证或改变业务记录。

### 合成取消差异探针

[test_m3_rules.py](../tests/test_m3_rules.py) 的 `test_static_upstream_history_loop_differs_from_rf01_charge_basis` 使用同一方式的两笔 payment（10、3）及一笔历史 refund（1），静态建模上游循环的行选择，得到三行；本项目 cancellation_refund_basis 只保留前两笔 charge，并独立保留 refund。比较逐行依据，不计算退款合计，也不执行 SDK 或 REST 写方法。此探针展示已知源码语义差异，不能证明课堂后端行为；M4 取消流程接入前必须核实实际交易类型过滤及重复退款风险。

## 插件查询能提供的证据

用户要求再次查询后，通过 Parallight Lab 的 lab_assistant 分别检索退款精度、退货/取消端点及公开实现来源；没有传 context_files 或项目文件。返回的相关资料仍为：

- `integrations/enterprise-ai-starters/common/INTERFACE-CLARIFICATIONS.md`，version `d58e1786ae008e15f7bafe3ba51f215cfe18415a3c55b532839a113724b8a6ae`。U6b 定义修改/换货差价与余额舍入，没有明确退货/取消合计公式。
- `materials/client_api/openapi.yaml#/v1/orders/{order_id}/returns`、`#/v1/orders/{order_id}/cancellations` 及订单读取片段，version `f2268b325c442206b1234c4a16dbd5a7f4ff81a925be56d9fb0be59cf8a56594`。退货回执无合计金额，取消返回 payments，没有定义汇总算法。

本次插件没有返回课堂退款实现源码；这不等于确认该源码不存在或平台不能提供。公开查询返回保留在会话中，不声称取得完整平台文档导出；平台 raw 和原始材料没有写入仓库。

## 对当前实施的影响

已有两类明确依据：退货选中商品的原成交价和重复次数；取消实际 charge 的原金额和原方式。仍未取得适用于当前课堂后端的退款合计计算依据，不能将上游函数中的“没有计算”解释为总额为零，也不能从差价或余额函数补造退款公式。

因此 [catalog.py](../agent/support_agent/domain/catalog.py) 继续保留选择依据，return_refund_basis 返回 needs_information、aggregate_amount=null；[policies.py](../agent/support_agent/domain/policies.py) 保留逐 charge 与独立退款记录，不产生合计或到账结论。既有 code/aggregation_contract_verified 字段名保持兼容；取得适用实现代码也可以作为核实依据，不要求只能由契约文档提供。

下一步取证应指向可公开披露的课堂 REST 退款实现或可验证的对应版本关系，明确操作前预计额的累加、舍入及其与后台交易的关系。若取得源码，记录其固定版本、完整计算路径及适用范围后再实现回归；无需反复等待同一份澄清文档，但也不能用不对应当前环境的代码代替证据。未知课堂后端行为继续保留，M3.1 不整体勾选，M3.2–M3.5 未提前实施。
