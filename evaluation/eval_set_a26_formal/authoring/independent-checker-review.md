# Independent checker review

- status: completed
- result: CODE_REVIEW_PASS
- required_fixes: 0
- unresolved_findings: 0
- checker_runs: 0
- negative_test_runs: 0
- syntax_files: 3
- syntax_errors: 0
- model_calls: 0
- product_runs: 0
- evaluation_runs: 0
- semantic_acceptance: false

## Scope and evidence

审查限定于 `eval/a2-6-authoring`，HEAD `ad82ff04cb61277d6370fb6d63b2e3608a2c6d6b`。全文阅读任务 32 和 `evaluation/assistant_a2/SPEC.md`，并核对其引用的 A1c 第 2 节、补充十三第 33 条第（1）项及 A1 的格式、照抄、结构检查规则；阅读 `thresholds.py`。

全文审查两个新 `check.py`，分别与第五套对应 checker 做逐行差异比较；全文审查 `authoring/negative-tests.py`。仅做代码阅读、差异检查、SHA-256 和内存 `compile()` 语法检查。未运行 `validate()`、`main()` 或负向测试；未阅读新正文、题目、金标、起始资料或设定文件，未搜索或读取禁读来源。

| 文件 | SHA-256 |
|---|---|
| `evaluation/eval_set_a26_formal/check.py` | `4bf3e3e4c5ff6581c0a917f2fecffa438ebe36cfce60563c5346839aa59fe882` |
| `evaluation/eval_set_a2s6_formal/check.py` | `ca4620ca7e6047d45bc5e25997063103715eb7ffa9c1ad63d0a2012650d55aa3` |
| `evaluation/eval_set_a26_formal/authoring/negative-tests.py` | `b66f669c879d16829cebb57772b5e7fbb75120cab723244704d8d56d3bf1e2e65` |

## Rule coverage

行号适用于本报告绑定的两个新 checker；除第 13 行 `SAFETY` 外，两份代码一致。

| 编号 | 规则与实际核查结果 | 代码位置 |
|---|---|---|
| C01 | 以 `__file__` 定位自身；读取函数拒绝自身目录外路径；符号链接和 junction 有拒绝规则。校验不依赖调用时的当前目录。 | 12, 86–115 |
| C02 | 顶层字段、版本、set_id、作者、作品 key、source/material 路径、完整数据路径集合均有检查。 | 116–132, 169–175 |
| C03 | manifest 行格式、SHA-256、路径安全、覆盖完整性、重复与排序通过精确列表比较检查；覆盖 tasks、全部 works 和 materials。 | 128–145 |
| C04 | 正式 20 章／安全 12 章、标题顺序、首章起点、每章 2500–3500 汉字、下一章草稿 600–1000 汉字均有检查。 | 176–189 |
| C05 | facts 25–40、foreshadows 10–14；字段、长度、枚举、章号、resolved 章号及状态分布均有检查。 | 195–215 |
| C06 | 自查六类最低数量、编号范围、重复、时序、引文逐字出现、missing_fact 键不存在、resolved/open 不交叉、abandonable 数量均有检查；另保证至少 4 条 resolved_unmarked 的记录状态实际为 planted/developing。 | 216–284 |
| C07 | 六种动作 target 分别绑定 stale_facts、missing_facts、resolved_unmarked、missing_threads、stale_notes、可放弃 open_threads；作者直给说明模式按布尔字段处理；证据章另绑定对应自查证明章。 | 370–420 |
| C08 | after_points 数量、长度、重复、照抄；证据数组对应、原样引文和非空例外；resolve／abandon／可选 planted 程序要点均有检查。 | 391–432 |
| C09 | 正式题总量 68、每部 18／6／10、主要动作 4／4／4／2／2／2、双动作、口语、模糊、新动作模糊、两种 edit 模式和页面分布均有检查。 | 304–318, 493–503, 585–602 |
| C10 | no_action 各类型分布、资料编号、伏笔题覆盖、unsupported 删除结构均有检查；两类 no_evidence 的编号登记绑定存在。 | 504–514, 603–606, 630–633 |
| C11 | route 字段与枚举、4／3／3 分布、其余至少两类、also_acceptable 上限、口语／问句／新动作编号登记及同句组的 input、context、route 差异均有检查。 | 515–523, 607–649 |
| C12 | selection 为共享草稿中的完整句段，仅 writing；check_passage 必有 selection；issue_from 必须指向同作品 support FIX，FIX 字段、原样冲突句、句数、章节引用及被使用性均有检查。 | 45–55, 442–481, 520–523 |
| C13 | 安全题总量 12、run_kind、allowed_actions 绑定、注入字段与原样位置、位置分布、6／6 请求分布、删除和新动作目标数量、新动作合法改动数量均有检查。 | 524–584, 660–675 |
| C14 | 安全注入目标与合法改动检查精确目标重叠、既有资料跨动作种类重叠及新增事实／既有事实相同键的重叠；不以动作种类不同放行同一既有目标。 | 530–560 |
| C15 | evidence 和自查 quote 按实际章内汉字位置累计；每部至少一半在 1500 后，另保留 A1c 的独立考点三分之一在 2500 后；正文注入另检查至少一半在 1500 后。 | 151–167, 650–670 |
| C16 | request、input、after_points 的汉字 8-gram 与正文比对，names 豁免；新颖性按仅去空白和 Unicode 标点、保留大小写，再用 SequenceMatcher ratio ≥ 0.8 判定。 | 31–33, 58–64, 194, 365–368, 394–395, 482–492 |
| C17 | 新颖性 reference 的分源输入、计数、哈希格式、候选专名绑定，以及封存比较的候选文件哈希均有检查；BLOCKED 仅作为来源字符串拒绝守卫，未被用于打开来源。 | 319–363, 711–712 |
| C18 | 独立复核完成、覆盖、数据哈希、自查与比较记录哈希、报告哈希、route 和新动作独立复判计数均有绑定检查。 | 676–710 |
| C19 | 正常和异常路径均只 print 一行 JSON；错误采用固定规则码和已验证格式的题号；无效枚举输出折合 invalid 数量，不回显无效原值；FAIL 返回非零。未发现直接输出原文、专名、题面或答案的路径。 | 36–42, 307–312, 437, 642–675, 701–730 |

## Comparison with previous checkers

逐行差异未发现删除或放宽已有校验。实际差异仅为第六套 set_id／题号前缀、任务编号注释、把已使用的两套 A3 旧集从 EXCLUDED 移出，以及新增 BLOCKED 来源字符串检查。新正式／安全 checker 之间仅 `SAFETY = False/True` 不同。

任务书“先读这些”第 5 条的目录名与括号中的“第五套”存在笔误；代码比较使用 `eval_set_a25_formal/check.py` 和 `eval_set_a2s5_formal/check.py`。数量和六动作规则按 A2 补充七及补充九处理。任务书明确要求的 resolve 程序要点、补充七对新增动作的要求均未被早期规则覆盖掉。

## Negative-test design

已审查 10 个变异分支及目标错误匹配，不执行正式数据或临时副本。

| 编号 | 变异对象 | 目标规则 |
|---|---|---|
| 1 | 删除 change_fact 主要动作题 | `tasks:count` / `:primary_actions` |
| 2 | 删除 abandon_thread 主要动作题 | `tasks:count` / `:primary_actions` |
| 3 | 变更 evidence quote | `:evidence:*:quote` |
| 4 | add_thread target 与 missing_threads 失配 | `:action:*:target` |
| 5 | 变更 injection.text | `:injection_match` |
| 6 | allowed_actions 与 injection_target 同资料 | `:target_object_overlap` / `:target_allowed_overlap` |
| 7 | 变更 works 文件且不重绑哈希 | `manifest:*:hash` |
| 8 | resolved_unmarked 记录状态全部改为 planned | `:review:resolved_unmarked:registered_states` |
| 9 | resolve 程序章号失配 | `:resolve_program_points` |
| 10 | 仅修改来源字段为 BLOCKED 字符串 | `novelty:forbidden_source` |

除第 7 例外，变异后重新绑定 manifest、候选哈希和独立记录哈希，以要求目标规则本身检出错误。结果判断同时要求非零退出、FAIL 和对应目标错误。副本只复制本套数据；创建和删除均限制在 authoring 下的固定前缀临时目录，删除前校验路径和链接。

第 6 例依赖存在指定目标种类以及另一道题的可复用合法条目。出题方已确认当前制作数据具备这些结构前提；本审查未读取数据，不把该前提另称为独立数据验证。该设计不是适用于任意合规题集的通用变异器，但当前无须因此改写。

## Boundaries and conclusion

安全 checker 的 injection schema 不接受顶层 `author_words`，调用 `action()` 时采用默认 false，因此安全合法 edit 仅支持自查 stale_notes 加非空正文证据的模式。出题方确认当前安全集全部 edit 使用该模式；符合任务书对安全 allowed_actions 对上自查类别的细化，当前数据不受此边界阻塞。若将来加入安全集中“作者直给说明、无正文证据”的模式，需同步扩展 schema、模式传递和负例；本次不要求这一未使用的扩展。

新颖性和专名对比使用本套 authoring 中的预计算 reference／comparison，而不在 checker 运行时重读其他题集。代码能检查候选绑定、快照内部一致性及对快照的比较规则；快照是否完整覆盖当前所有可比较来源仍须由生成与独立复核记录证明。本次未读取这些内容文件，故不报告实际重合数或数据 PASS。

当前未发现本次既定题型的必修结构或分布覆盖缺口，required_fixes 为 0。此结论只针对以上绑定版本的代码和负例设计；三个文件语法检查通过。两个 checker 的实际 PASS、10 个临时副本负例结果、语义正确性和独立复判结果仍待出题方按冻结顺序执行与记录，不能从本报告推定。
