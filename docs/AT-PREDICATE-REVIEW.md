# 逐 AT 谓词审阅索引

本页说明如何审阅 [AT-TEST-TRACE](AT-TEST-TRACE.json) 的 `local_business_acceptance`。当前运行及派生计数只维护在 [当前证据](CURRENT-EVIDENCE.md)，不在本页复制。原子语义和合成替代范围见 [需求](CASE-REQUIREMENTS.md)、[固定夹具](../tests/fixtures/m6_business_acceptance.json)与 [M6.7 交付](M6.7-DELIVERY.md)。

## 从要求定位到实际判定

1. 在 `plan` 找到 `at_id`，阅读完整 `requirement`、`substitution`、`scenario_ids` 和 `business_result`；`remote_result` 单列，不从本地通过推断课堂结果。
2. 查看该条的 `predicate_review.predicate_ids`；用 ID 查询 `predicate_review_index.predicates`。每个定义保存 `scenario`、完整 `path`、`op`、`expected`、`evidence_source`、`observation_result`、`at_ids` 和 `shared_at_count`。路径是有类型的 JSON 数组，不把包含句点的键误读成分段路径。
3. 在 [FOUNDATION-RUN](FOUNDATION-RUN.json) 的 `business_batch.results` 找到同场景，按该路径核对实际值。`equal` 是类型明确的 JSON 比较，`contains` 是字符串成员检查；原 [验收器](../scripts/business_acceptance.py)重新执行所有直接谓词及整个场景 oracle。
4. 联合审阅场景的逐轮精确读取／写入、完整复述、身份、journal 和完整最终后台补丁。单个直接谓词较少不自动等于覆盖不足；完整场景 oracle 也是证据，但须由人说明它如何承接原子要求。

稳定 ID 为 `predicate:` 加完整 SHA-256，输入是规范 JSON 的 `{scenario, path, op, expected}`。更换字段、操作符、期望值或场景会改变 ID；重排 AT／断言或增加共用该谓词的 AT 不会改变已有 ID。不同场景的同形检查保持不同 ID，避免把独立观察误合并。ID 是定位与内容标识，不是签名或语义充分性证明。

## 审阅队列的含义

`predicate_review_index.review_queue` 对全部已登记 AT 排序，依次优先：仅初始夹具、单个不同谓词、存在共用谓词，然后按 AT ID。每个 AT 的证据类型和标记同时保存在 `plan[].predicate_review`。

| 标记或来源 | 含义 | 人工复核重点 |
|---|---|---|
| `fixture_preconditions_only` | 直接谓词只检查 `initial_backend` | 起始条件不能单独证明 agent 正确定位／执行；检查场景轨迹及最终态是否承接行为要求 |
| `single_direct_predicate` | 只有一个不同的直接谓词 | 该谓词是否表达了全部原子语义，还是只检查了方式 ID／某个规格字段 |
| `shared_direct_predicate` | 同场景的完整谓词被多个 AT 共用 | 复用公共确认／权限门合理；不同要求是否还需要各自的区分性检查 |
| `native_history`／`native_turn` | 实际 history 派生证据／实际轮次观察 | 来源、目标、完整条件和后次确认是否相符 |
| `final_backend` | 实际合成后台最终状态 | 是否与固定起点加预期补丁一致，是否遗漏无关副作用 |

`assertion_occurrences` 数全部出现次数；`distinct_predicates` 数按场景区分的定义；`shared_predicates` 数有多个不同 AT 用户的定义。`single_predicate_atoms` 按不同谓词 ID 计数，不靠重复列同一检查增加覆盖。这些数不加到 unittest、对话或业务 AT 计数中。

这是可定位的人工工作清单，不是自动质量分数；没有标记的要求仍需语义复核，标记也不自动登记为缺陷。固定夹具尚未执行时，索引只描述计划，谓词为 `not_executed`；只有整批原生观察、所有场景 oracle 和直接谓词验证成功后才派生 `passed_local`。读方通过 `validate_evidence_pair` 重算索引并比较整个追踪；不能只改 ID、共用数、期望值或队列后沿用通过状态。

## 证据边界

索引与当前成对工件的 run／source／specification 绑定，不读取不可见的 Git 历史。机器证明已固定检查实际通过，人工负责判断这些检查是否充分表达原文；不把该索引称作人工复核已完成。真实模型、原始课堂 fixture、正式评分、后台事务和到账继续按 [M7 输入边界](M7-INPUT-BOUNDARIES.md)分别记录。
