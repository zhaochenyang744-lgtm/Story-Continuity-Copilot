# DeepSeek Flash 真实评测：最终独立验收

> **历史记录**：本文记录的是 2026-09-26 时的设计或过程，文中的部分说法和功能已经变化，例如 Story Memory 现在叫事实库，作者资料和修订计划已经删除。现行说明见[当前产品](current-product.md)。

日期：2026-09-26。产品基线：`c3bd54ab019447354e8b1387e16b9aca3258b4c9`，分支 `codex/legacy-gap-repair`。被测 Provider：`deepseek-flash`，`https://api.deepseek.com`。实施任务使用的 `gpt-6-sol/high` 与被测模型分开记录。

**结论：本轮评测执行、结果保存、统计修复及限定材料修复可接受；产品／模型整体质量不能宣布通过。** 首轮及第二轮验收发现的问题、原始失败和原报告均保留，新证据补充说明适用范围，不倒写历史。用户接受本次评测结论仍待确认；本报告不授权下一轮产品修改、提交或发布。

## 实际调用与用量

| 运行 | 范围 | 生成 HTTP POST | models 预检 | 输入 tokens | 输出 tokens |
|---|---|---:|---:|---:|---:|
| `flash-v1-20260926-01` | V8 24 + 6 次重复、G01 10、G02 4、G03 4；48 次逻辑运行、42 个不同输入案例 | 49 | 1 | 144,300 | 8,508 |
| `flash-v2-20260926-01` | G02 4 与重建材料的 G03 4 | 8 | 1 | 20,844 | 5,734 |
| `offline-equivalence-20260926-01` | G03 四份完整材料一致性及业务请求等价验证 | 0 | 0 | 不适用 | 不适用 |
| **本轮累计** | 不跨版本合并唯一案例数或质量分母 | **57** | **2** | **165,144** | **14,242** |

57 次生成响应全部 HTTP 200、usage 完整；V1 含一次契约修复调用，没有 transport retry。HTTP 成功不等于产品成功：V1 两例 G03 的 `failed/evidence_unresolvable` 原样保留。实际账单费用不可得，不把 tokens 当作结算金额。总 tokens 为 179,386。主控及独立复核没有新增真实 Provider 调用；V3 fake 返回不计入上表用量或模型成绩。

用量证据：[V1 主控重算](../evaluation/current_flash_v1/independent-round1/root-verification.json)、[V2 主控重算](../evaluation/current_flash_v2/independent-round2/root-accounting.json)、[V2 独立计数审计](../evaluation/current_flash_v2/independent-round2/accounting-review.md)。

## 模型首答与产品最终结果

| 范围 | 独立结论 | 未关闭的限制 |
|---|---|---|
| G01 时间与知识变化 | 十个固定、短文本案例首答与最终均符合预期，包含六个兼容情形和四个真冲突控制；无修复调用 | 只支持本组已见案例，未证明长文、多来源或新作品泛化。不能用产品降级冒充模型首答正确 |
| G02 已保存草稿简报 | V2 四例首答／最终各 45 个 item；逐条核对自身引用。其他三例最终主要事实在相应范围披露下可接受 | 长句案例最终仍有两项引用不足：句尾交接／获知事实只引截断 claim；“看得懂潮表坐标”只引“不知道代号”的 Memory。四个首答摘要均有引用缺口，最终长句摘要仍有缺口。相关事实在完整输入其他位置存在，因此是自身引用不足，不是凭空编造；`partial` 也不能替代逐项支持 |
| G03 目标来源召回与章节绑定 | V2 short、deep、other 三例各三个最终 item 有对应来源；absent 首答承认缺少原文，最终 `insufficient`。深处目标原句确实进入摘录，章节自身引用对应。V3 修复完整材料后，四份实际业务请求与 V2 完全相等 | V1 教学材料字段污染限制归因；V2 原 DB 的父章节不一致已保留为历史缺陷。V3 只关闭生成器与断言问题，没有新的实模型重复。变更提案未明确生效时间，不能外推为一般时序推理通过 |
| V8 历史案例在当前链路的回放 | 按旧标签计算首答 9/24、最终 8/24；最终全部为 `no_conflict`。当前链路再次排序后，八个冲突案例均未获得完整预期证据 | 旧 `static_canon/fixture_anchor` 与当前 `timeless_rule` 所需的 `rule` 契约不兼容；旧标签亦不等于当前严格确认冲突指标。另有四个证据不足案例在完整证据下仍未输出 issue，故不能把全部问题归因于裁证据。此轮不能据此给 Flash 单独评分，更不能宣布旧 V8 Gate 通过 |

V2 identical-text 的月牙裂纹这次有对应章节来源，不能沿用 V1 错误认定本次仍错；同样，单次输出改善不是产品修复证据。V2 G03 更换了材料，不能把它与 V1 的分数差称作同条件进步。G04/G05 离线与浏览器回归也不充入实模型成绩。

语义证据：[G01/G02/G03 首轮复核](../evaluation/current_flash_v1/independent-round1/semantic-review.md)、[V2 八例逐项原文与引用核查](../evaluation/current_flash_v2/independent-round2/semantic-review.md)、[V8 契约与召回诊断](../evaluation/current_flash_v1/independent-round1/v8-review.md)。

## 评测工程修复及独立验证

1. **统计与故障分类。** V2 修复 missing／partial／invalid usage 被误计为零未知、业务失败被当作服务故障提前停等问题。独立审计的 38 项检查与七组汇总反例通过。本轮实际 57 次完整 usage 未受这些缺陷影响。
2. **输入可核查性。** V2 保存完整脱敏业务请求、来源和版本绑定、schema、哈希、首答及产品结果；补齐 seed 等源码依赖冻结。快照在调用前内存捕获、随后落盘，不代表已经具备进程崩溃耐久日志。V1 快照和已清理 DB 的可复现性限制继续保留。
3. **完整材料一致性。** V3 四份新合成 DB 的章节、SourceSpan、摘要、revision 与 Memory 一致；故意不一致正文、错误 Memory 类型会被离线断言拒绝。从每份新 DB 的实际持久化 API 输入经当前引擎重新构造模型业务请求，与 V3 捕获及 V2 真实请求逐字段、逐哈希完全一致，4/4。读取 V2 baseline 只用于捕获后的比较，没有用旧请求伪造新捕获。因此无需重复真实调用。
4. **保留与隔离。** 主控重跑 V1 三项、V2 四项、V3 三项针对性离线测试及相应冻结校验通过；最终再次核对 V1/V2 的 65 份原结果和 V3 原结果无漂移。独立材料审阅核对八份旧 V2 DB 哈希不变。产品逻辑、提示词、历史冻结资产与原仓库没有修改，没有提交、推送或部署。

阶段结论：[第一轮退回](../evaluation/current_flash_v1/independent-round1/ACCEPTANCE.md)、[第二轮限定退回](../evaluation/current_flash_v2/independent-round2/ACCEPTANCE.md)、[V3 独立材料验收](../evaluation/current_flash_v3/independent-round3/fixture-review.md)、[主控最终复核记录](../evaluation/current_flash_v3/independent-round3/root-verification.json)、[65 份原结果最终完整性核对](../evaluation/current_flash_v3/independent-round3/root-integrity-final.json)。原失败证据继续有效；本文件是最终结论入口。

## 后续建议与边界

建议下一步先修复 G02 每项及摘要的自身引用支持，并把本次明确 bad cases 纳入长期开发回归。另建符合当前契约的比较集与版本化检索检查，复核标签、必要证据和相近正控制后，再评估模型或提示词变化；不要机械改旧 predicate 或旧标准答案刷绿。暂不据这组结果下“Flash 最适合”或替代模型优劣的结论。

新未见集尚未建立；12 案例旧原始包仍未找回，不能重建后冒称原集。G07 线上成功链路、G08 完整应用恢复未在本轮验证。真实作者研究、Agent 开发和发布均未开展。后续工作遵循[长期维护规则](evaluation-maintenance.md)，本轮停止于评测交付与用户确认。
