# V2 比较集评分器独立验收

结论：本轮 V1 评分器的主要问题已经修复；V2 仍需要按实际问项修正不足案例的类别 gold。原始答复评分目前只覆盖合同的一部分，不能把它的 `machine_result=pass` 解释为完整合同通过。本文未运行 Provider、API capture、数据库或输出覆盖入口；未修改产品或冻结文件。

## 独立证据

- 直接读取冻结的 26 组业务请求、首答和最终 API 结果，在内存分别调用 `score_raw_one` / `score_one`；全部 26 组仍为机器通过、语义待人工审核。首答与最终结果没有互相替代。
- 独立构造 46 项有界正负控制，35 项符合预期；11 项不符为 5 个原始合同遗漏，以及 3 个类别候选在 raw/final 两层的拒绝。这个数字是审计探针结果，不能当模型正确率。
- 32 个 manifest 受保护文件和 manifest 自身，共 33 个文件在执行前后逐一 SHA-256 校验，一致且无变化。
- manifest：`35b8a9559b9d5138f21795cdeb74439d010490dd5a9ee07a37cd48dbd44ca337`。
- scorer：`19b2fc2e14d0fdafd1ef54dccf7e885b16728c679e9da1045b24be586d27b94d`。
- 脚本与完整输入、变异结果、当前 validator 结论见本目录 `probe.py`、`results.json`。脚本封锁 socket connect 与 sqlite connect，结果以 create-only 模式写入。真实 Provider、网络及数据库连接均为 0。

## 已关闭的原问题

1. 两个知识变化与位置移动 `state_change` 的 raw/final 正控制通过；错用 `possible_conflict` 被拒。结果见 `results.json:574`、`:590`、`:622`、`:638`。
2. 额外无关来源即使补齐合法形状的 Evidence chain 也被拒；章节、摘录和 Memory 来源错配被拒。原先“最低 ID 齐了便忽略其他 Evidence”的问题关闭。见 `results.json:670` 起。
3. 八个不足案例只带当前声明的最小集合均通过，五个案例加上声明的 optional 来源也通过；位置移动带可选 prior 来源也通过。见 `results.json:905` 起。此结论只说明评分代码执行声明的集合策略正确，不背书 gold 所声明的集合一定最小；主控另已复现 badge_rule 单条充分的 gold 问题。
4. 最终不足结果的缺失 chain、错误 chain role、context 升成 contradicts、非空动作均被拒。失败、超时、运行中、取消且 `issues=[]` 不会算作无冲突。见 `results.json:755` 起、`:833` 至 `:904`。
5. `score_one` 的结构通过仍返回 `result=pending_manual_review`，没有把机器绑定验证冒充语义准确率。解释真实性、时序推理及改写是否等价仍需人工判断，这是正确的分层。

## 需修正的 gold 类别

`score.py:41` 和 `:116` 严格比较 `decision_category`，但三个不足目标已从原冲突轴转成别的问题。通过只改 category、保持请求、来源、关系和 missing_link 不变的正控制，复现当前产品 validator 接受，而 raw/final scorer 拒绝。

| 案例 | 当前强制类别 | 独立控制 | 结论 |
| --- | --- | --- | --- |
| orchard_restoration / relationship / insufficient | relationship | timeline | 草稿问 Nera 是否早于 Oren 出生，是事件先后；应按当前提示词修 gold。 |
| harbor_signal / timeline / insufficient | timeline | relationship | 草稿问 Sera 是否授权重新开放，是具名人的授权；应按当前提示词修 gold。 |
| harbor_signal / character_knowledge / insufficient | character_knowledge | attribute | 草稿问传令者身份；原知识轴不是当然正确。此候选证明现有 scorer 机械沿轴拒绝，确切 gold 应由语义复核决定，不能仅因 validator 接受就认定 attribute 是唯一正确类别。 |

当前提示词 `backend/app/provider.py:116` 明确规定授权属于 relationship、事件先后属于 timeline。因此前两项不是泛化成“任意合法类别都接受”的要求；修每例 gold 即可。具体 raw/final 输入与拒绝结果见 `results.json:2104`、`:2584`、`:3097` 起；validator 对三个 raw 控制均接受。

## 原始答复分数的明确限制

`score_raw_one` (`score.py:15-69`) 检查目标、outcome、来源 ID/章节、关系及 temporal_basis，但没有检查 Evidence chain、动作与 Memory 关联合同。以下五个纯机器可验证变异仍返回 `machine_result=pass`、`semantic_result=pending_manual_review`，当前真实产品 `ContinuityEngine.validate` 均拒绝：

| 首答变异 | scorer | 产品 validator | 证据 |
| --- | --- | --- | --- |
| 不足结果 `evidence_chain=[]` | pass | evidence_unresolvable | results.json:1129 |
| 不足 chain role 改为 prior_state | pass | evidence_unresolvable | results.json:1312 |
| 不足 `available_actions=[edit]` | pass | schema_invalid | results.json:1500 |
| 不足含 proposed_memory_change | pass | insufficient_evidence_memory_change | results.json:1690 |
| 引用不存在的 Memory ID | pass | evidence_unresolvable | results.json:1884 |

上述都可由真实模型首答产生，随后产品会修复或拒绝；如果未来把此 raw pass 计为完整首答合同成功，会遗漏需修复的首答。它们不是人工小说语义才能解决的问题。当前 RUBRIC 明确把 raw 检查列为较窄的四类，所以本审计将其作为**原始分数口径限制**，不据此否定本轮 26 条有效合成结果，也不另行扩展产品修改任务。后续真实评测需补齐这些原始合同判定，或明确命名为部分字段检查，并另外报告完整 validator 是否通过；不能用人工语义待审掩盖合同失败。

最终评分器对对应的 chain、动作、关联检查已通过本次控制。本文未扩展任意恶意 JSON、运行身份篡改或全工程防御性验证。

## 首答、修复答与最终结果留存

当前 26 条记录都拥有独立 `raw_first`、`raw_first_score`、`final_product`，`raw_repair=null`。`api_score_probe.py:107` 只有在 `provider.calls == 1` 且内容一致时才标记 capture 一致，26 条均为 true；因此当前材料未隐匿一次实际发生的修复。

但 probe 在 `api_score_probe.py:114` 直接写 `raw_repair=None`，计数在 `:122` 用行数。这是无修复的合成探针实现，不是通用的真实 Provider runner。后续真实 runner 须留存每次 request/首答/修复答、逐层评分及真实调用数，不能直接拿此入口代表已验证完整修复留存。此项是下一阶段复用限制；本次没有制造 Provider 调用去测试它。

## 复核范围

本次只核对现有修订、原失效控制、有限 raw 合同边界与主控指出的类别问题。gold 故事语义和 capture 由其他独立审阅负责。所有 26 条均为已见合成输出，不能支持真实模型效果或盲测结论。原始失败、V1/V2 文件和产品 hash 均保留。
