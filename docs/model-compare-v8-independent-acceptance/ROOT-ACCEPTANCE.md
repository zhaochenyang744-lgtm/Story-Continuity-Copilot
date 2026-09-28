# V8 模型对照测试：独立验收结论

验收日期：2026-09-27 UTC（悉尼时间 2026-09-27）；run：`model-compare-v8-20260927-01`。

**本轮实验及工程验收通过，产品质量尚未通过上线验收。** 三组各 34 例全部完成测试与人工审阅。开启思考显著改善了本组样本的完整输出；现有证据不足以认定整个 Flash 模型系列不适合任务。建议下一轮以 Flash high 为主要候选，保留 Pro high 作质量对照，先修正已定位的产品合同缺陷，再用未见样本复验。本轮没有切换生产模型。

**主要结果**

“完整通过”同时要求事实判断、类别、证据选择与角色、引用绑定、原输出合同、Issue 交付、适用的时序和动作均通过。“最终”指实验引擎执行原校验、修复及必要归一化后的交付，不是数据库落库或 Web API 端到端验收。

| 配置 | 首答完整通过 | 最终完整通过 | 首答 HTTP 耗时中位数 | 首答 HTTP P95 | 修复调用 |
|---|---:|---:|---:|---:|---:|
| Flash，关闭思考 | 16/34（47.1%） | 17/34（50.0%） | 1.47 秒 | 2.97 秒 | 9 |
| Flash，high 思考 | 24/34（70.6%） | 25/34（73.5%） | 7.20 秒 | 19.46 秒 | 1 |
| Pro，high 思考 | 27/34（79.4%） | 28/34（82.4%） | 31.20 秒 | 46.06 秒 | 1 |

Flash high 最终比关闭思考多通过 8 例。Pro high 比 Flash high 净多通过 3 例，但首答耗时中位数约为其 4.33 倍；逐例比较为 Pro 独自通过 5 例、Flash high 独自通过 2 例。因此 Pro 并非逐例占优。

| 样本类型 | 数量 | Flash 关闭思考：首答→最终 | Flash high：首答→最终 | Pro high：首答→最终 |
|---|---:|---:|---:|---:|
| 无冲突 | 13 | 13→13 | 12→13 | 13→13 |
| 确认冲突 | 10 | 2→3 | 6→6 | 9→9 |
| 证据不足 | 11 | 1→1 | 6→6 | 5→6 |

单独评估首答事实理解，Flash 关闭思考为 32 例通过、1 例部分通过、1 例失败；另两组均为 34 例通过。这只反映这 34 例可见回答中的事实推理，不能写成一般任务准确率 100%。完整通过的主要差距还包括分类、证据角色和输出交付。21 个应产生 Issue 的案例，首答实际产生 Issue 分别为 14、21、21 例；最终实际交付分别为 16、20、21 例。产生 Issue 本身不等于内容正确。

**Trace 定位与责任划分**

1. **产品合同存在未告知的长度限制。** Flash high 的第 04 例事实判断正确，但 `reasoning` 为 881 字符，被引擎的 800 字符限制拒绝，返回泛化的 `schema_invalid`，没有进入修复。该限制没有写入提供给模型的 prompt/schema。位置：[engine.py:499](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/backend/app/engine.py:499>)。这不能归因于模型不会推理，也不能删除该失败来抬高通过率。人工初评漏判了此结构约束，已通过独立追加裁决更正并保留初评。
2. **模型有真实理解错误。** Flash 关闭思考第 21 例把 `ground`（grind 的过去式）当成残句而漏报；第 06 例遗漏来源依据缺口，事实层仅部分通过。
3. **引用与证据角色错误可以发生在事实理解正确时。** Flash 关闭思考第 22 例引用了 Memory 中存在、但本次未选入允许证据的 span 4；引擎正确拒绝 `evidence_unresolvable`。第 26 例把准备状态规则当作 supports 而非 context，修复仍重复，最终 `conflict_evidence_not_direct`。
4. **修复并不保证改善语义。** Flash 关闭思考第 25 例首答身份推理正确但类别/合同错误；修复否认了显式身份依据并改成 no_issue，同时 basis 达 417 字符，超过已声明的 400 限制，最终失败。第 01 例经保守归一化完成交付，但把已确认冲突降成证据不足，事实层仍不通过。
5. **有成功的局部修复。** Flash 关闭思考第 16 例修正证据角色；Flash high 第 20 例把超出已声明上限的 402 字符 basis 缩短；Pro high 第 18 例修正 ledger 与 Issue 状态不一致。11 次修复中，3 例恢复完整通过，不能把其他交付恢复算成语义通过。

Pro high 最终剩余失败为第 06、12、13、21、28、32 例，主因是 5 例类别错误及 1 例证据角色错误。英文目标下出现中文输出作为独立观察记录，没有临时增设硬性评分标准。

**用量与原预算兼容性**

| 配置 | 生成 POST | 输入 token | 输出 token | 总 token | 其中首答总 token | 其中修复总 token |
|---|---:|---:|---:|---:|---:|---:|
| Flash 关闭思考 | 43 | 148,721 | 13,606 | 162,327 | 122,398 | 39,929 |
| Flash high | 35 | 117,649 | 63,184 | 180,833 | 176,376 | 4,457 |
| Pro high | 35 | 119,712 | 98,983 | 218,695 | 209,848 | 8,847 |
| 合计 | 113 | 386,082 | 175,773 | 561,855 | 508,622 | 53,233 |

另有 1 次模型列表 GET。所有 113 次生成请求均 HTTP 200、finish_reason=stop，usage 完整；未知用量、未运行案例、传输重试和评分异常均为 0。供应商未提供本轮金额，**费用未知**。high 两组分别报告 50,427 / 85,537 reasoning tokens，已包含在输出 token 中，不能再次相加；关闭思考组未报告该明细，不能把未报告写成 0。未保存隐藏推理正文，只保存是否存在、长度、hash 与 token 元数据。

为了分离模型能力与原 token 门限，三组统一 `max_tokens=32768`，实验引擎单次评估预算临时为 40,000；每例结束后恢复原 8,000。7 个响应超过原 8,000 门限：Flash high 第 01 例；Pro 第 04、09、16、24、25 例首答和第 18 例修复。无响应超过实验门限。

按真实回执做原预算兼容性核算，三组“完整通过且未超原单次门限”的案例数分别为 **17、25、22 /34**。这是账面兼容性分析，没有在原预算下重新执行生产链路；不能将 22/34 当作 Pro 原预算端到端实测成绩。原门限按单次评估计算，不能把两次各自未超限的首答与修复总量相加后判超限。

**验收执行与证据完整性**

本轮将 harness 实现、人工语义审阅、独立工程检查分工执行，由主验收汇总裁决。102 个条件案例最终状态为 98 completed、4 failed；所有失败链完整保留。failed 是被测结果，不代表测试未执行；completed 也不代表语义通过。

人工共锁定 **215 条记录：102 首答、11 修复、102 最终交付**。各案例别名独立随机，隐藏模型、耗时、用量与机器分数；先锁定首答，再审阅修复/最终结果，全部评分锁定后才解开映射汇总。明确裁决后，人工完整评分与原机器合同评分分歧为 0。主验收另抽查了第 04、09、22 例。

这不是严格双盲：工程审阅人此前接触过第 01/02 例条件，随后承担另外六例语义审阅；主验收在审阅自身匿名样本前见过三组机器汇总分，但未见样本映射。这些限制保留在解释中。

独立工程审计 **4,865 项检查通过，0 遗留 findings**：请求正文与参数、跨组业务输入、记录 hash、raw→parsed 链、修复拒绝字段和诊断、真实 usage、预算恢复、隐私处理均通过。冻结的 443 个 source 与 253 个 runtime 文件匹配；既有 17 个产品模块、632 个 V7 冻结文件、375 个 V7 run 文件保持；本轮 979 个 run 文件读取前后 hash 与清单稳定。

离线验证包括 14 项测试通过、冻结前针对评分异常与截断行为的修复探针通过，以及 34 条历史 V7 链精确回放。历史最终 19/34 和各例失败集保持。运行期间没有修改产品源码、金标或评分口径；本轮新增实验与验收文件。未提交、推送或部署。

**适用范围与下一轮建议**

本轮使用 34 个已见开发输入（24 个既有案例和 10 个此前控制案例），各组每例只运行一次，不能证明未见样本泛化或重复运行稳定性。三组输入、claim ID、prompt、schema、gold 固定相同；按案例轮转条件顺序。仅通过固定输入绕过检索/批处理，保留原执行、校验与修复；数据库和 API 持久化链路未覆盖。供应商模型列表返回 `deepseek-flash` / `DeepSeek-V4.1-Flash` 和 `deepseek-v4-pro` / `DeepSeek-V4-Pro`，不据此声称服务端版本不可变。旧 V7 关闭思考结果的 max_tokens 为 2,000，属于历史背景，不是同预算同步基线。

建议下一轮按以下顺序推进；本报告不把建议写成已完成修复：

1. 在 prompt、schema、validator 中统一 reasoning 长度约束，提供可定位的错误诊断与适当修复入口，覆盖 800 边界及失败保留。
2. 用跨类型、跨语言的新样本检查类别边界、证据角色和修复退化，保留未见测试集，增加重复运行；不得针对本轮失败逐例放宽金标。
3. 以 Flash high 作为质量/延迟折中的主候选，Pro high 继续作为对照。对 Pro 必须先解决原预算兼容性，再考虑生产用途；不能直接沿用实验放宽的预算。
4. 之后再验收检索、原预算、数据库与 API 的完整链路。本轮不授予上线或模型替换通过结论。

**可复核文件**

- [人工评分与逐例证据、裁决及映射汇总](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/docs/model-compare-v8-independent-acceptance/ROOT-SEMANTIC-MEASUREMENTS.json>)
- [调用、时延和逐例结果](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/docs/model-compare-v8-independent-acceptance/ROOT-LIVE-MEASUREMENTS.json>)；[阶段用量及原预算核算](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/docs/model-compare-v8-independent-acceptance/ROOT-STAGE-USAGE.json>)
- [独立工程验收](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/docs/model-compare-v8-independent-acceptance/engineering-live-review-06.md>)；[完整检查与文件 hash](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/docs/model-compare-v8-independent-acceptance/engineering-live-review-06.json>)
- [冻结计划](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/docs/model-compare-v8-independent-acceptance/PLAN.md>)；[预先固定的语义标准](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/docs/model-compare-v8-independent-acceptance/SEMANTIC-CRITERIA.md>)；[冻结输入清单](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/model_compare_v8/frozen-inputs.json>)

原始 run 汇总在生成结束时保存的 `semantic_review=pending` 保持不改；最终人工完成状态以本报告及 `ROOT-SEMANTIC-MEASUREMENTS.json` 的 `complete=true`、215 条记录为准。
