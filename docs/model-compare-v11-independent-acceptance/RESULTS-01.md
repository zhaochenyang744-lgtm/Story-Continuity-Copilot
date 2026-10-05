# V11 类别修复复测：机器评分结果（待人工语义复核）

run：`model-compare-v11-20260928-01`，prompt `continuity-review-v20-decisive-fact-category`，冻结清单 SHA256 `3d4c14a82ceb40fd34b6b25645ad0e1492b164e711d7325ae0b5c2dde503e688`。计划见 [PLAN.md](PLAN.md)，逐例数据见 [machine-comparison-01.json](machine-comparison-01.json)。

**状态：执行完整，机器评分已出；人工语义复核、独立工程验收和独立标注的未见集均未进行，本文件不是 gate 通过结论。**

## 执行与用量

108/108 条件案例完成，无停止、无未知用量。111 次生成 POST＋1 次 models GET，已知总 token 642,157；费用未知。中止的 V10（v19）另有 20 次 POST，未评分。

## 已见 34 例（与 V9 同条件、同金标）

| 配置 | V9 最终通过 | V11 最终通过 | V9 最终类别错误 | V11 最终类别错误 | V11 原预算内最终通过 |
|---|---:|---:|---:|---:|---:|
| Flash high | 27 | **30** | 7 | **1** | 30 |
| Pro high | 27 | **31** | 6 | **1** | 26 |

转为通过：Flash 06、12、18、19、21、25、28；Pro 06、12、18、21、24、28。它们正是 V8/V9 反复出现的归属（relationship）与带时间锚点属性（attribute）混淆。

仍失败：

- 01（金标 world_rule，门禁规则）：Flash 标 object_state，修复后 reasoning 807 字符超限终止；Pro 标 relationship。两组都未识别“规则本身是唯一直接反驳”。
- 07（金标 timeline）：Flash 标 object_state。
- 10、13（Flash）、13、33（Pro）：证据角色/多余证据/结论错误，与类别无关；13 在 V8 也曾失败。这些是 V9 通过、V11 未通过的非类别变化，单次运行下无法区分规则副作用与随机波动，需要重复运行确认。

## 新对照 20 例（v19 调用前冻结，实施者编写，非独立未见集）

| 配置 | 首答通过 | 最终通过 | 类别错误 |
|---|---:|---:|---:|
| Flash high | 19/20 | 19/20 | 0 |
| Pro high | 17/20 | 18/20 | 0 |

两组在 19 个应产生 issue 的对照上首答类别全部正确（38/38），包括所有反向控制：执行者已知只缺结果 → event_status，持有人未知 → object_state，只下定义的规则 → event_status，规则单独构成反驳 → world_rule，人物是否知道 → character_knowledge；无问题控制未误报。非类别失败：cc3（Flash 建议修订无法定位；Pro 结论错误）、cc18（Pro 证据角色）。

注意：对照中 world_rule 单例（cc10）两组都判对，而已见 01 两组都判错，说明该类仍不稳。

## 冻结清单与提交代码的差异

运行结束后，`backend/app/provider.py` 与 `backend/app/stage13.py` 为产品侧 Flash 配置再次修改：新增默认关闭的 `CONTINUITY_REVIEW_THINKING` 开关（仅连续性检查可选 high 思考、输出上限 6,000、超时 60 秒），公开模式允许 `deepseek-flash`。prompt 规则与版本（v20）、engine、评分和全部运行记录未变；评测经自身 harness 调用 Provider，不经过该开关。因此在包含这些改动的提交上执行 V9/V10/V11 `freeze verify` 会报 `dependency_closure_or_hash_drift`，漂移文件仅上述两个；这是已知的后续修改，不代表运行证据被改动。线上部署配置仍为 `deepseek-v4-pro`，等 gate 通过后再切换。

## 结论与下一步

1. 类别判定是剩余失败的主因，这一项已大幅改善：已见集最终类别错误 7→1（Flash）、6→1（Pro），新对照 0 错误；prompt 与 v17 等长，后端全量与修改前失败集合相同。
2. 仍不能宣布 gate 通过。需要：独立标注的未见集（与本实施者和开发材料隔离）、每例重复运行测稳定性、人工语义盲审、原预算下的完整链路验收。
3. 待跟进：world_rule（01）；修复阶段 reasoning 仍可能超长（01 Flash 修复输出 807）；10/13/33 的证据角色变化需在重复运行中确认。
