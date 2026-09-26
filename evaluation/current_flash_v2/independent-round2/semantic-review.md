# Flash V2 八例独立语义复核

日期：2026-09-26。审阅对象：`flash-v2-20260926-01` 的 8 个保存结果。结论基于逐例读取实际 `business_requests[0].business_request`、`model_outputs[0].business_json` 与 `product.analysis`，并非照抄实施者 `POSTRUN_REVIEW.md`。本轮只读取既有 JSON 和文档，用本地 Python 统计结构和定位文本；未发起 Provider / HTTP 请求、运行产品测试、读取数据库或凭据、修改产品或旧证据。

## 结论与数量

**G02 仍有明确的最终结果引用缺口，不能关闭全部语义问题。** 长句案例保留两个自身引用不支持完整文本的 item；其最终摘要仍包含未被摘要自身引用覆盖的句尾。其余三个 G02 案例的最终主要叙事事实有自身引用支持，其中 body-limit 仅在明确披露截断和未选范围的条件下可接受。

**G03 在这组新建的两章 fixture 上可作有限接受。** short、deep、other-chapter 各保留三个有对应来源的 item；absent 首答明确承认原文未定位，最终保守输出 insufficient。未发现本轮将草稿 ID 当作章节、目标章只引用另一章、或把缺失原文说成已写事实的情况。提案时间范围仍有歧义，不能据此声称一般连续性推理通过。

| 复核对象 | 本轮数量与发现 |
| --- | --- |
| 保存调用链 | 8 个业务输入、8 个首答、8 次已记录 HTTP dispatch；每例一个，无 repair 首答替换 |
| G02 首答 / 最终 items | 各 45 条（12 + 12 + 9 + 12）；所有 item 文本原样保留 |
| G02 明确的 item 自身引用缺口 | 首答 2 条，最终仍 2 条；都在 long-sentence 的 item 1、2 |
| G02 首答摘要自身引用缺口 | 4 / 4 个摘要各至少一处；按摘要计数，不把多分句拆成独立错误率 |
| G02 最终摘要自身引用缺口 | 1 / 4 个摘要：long-sentence |
| G03 首答 / 最终 items | 首答 12 条；最终 9 条，absent 的 3 条被产品移除 |
| G03 章节目标对应来源 | 首答 8 个 chapter item 均含对应章节自己的 SourceSpan；最终保留的 6 个也对应 |
| G03 明确的捏造章节事实 / 草稿冒充章节 | 本轮所见为 0；不等于总体模型错误为 0 |

以上是对固定、已暴露样本的人工审阅计数，不能合并为总体准确率。`supported` / `partial` 是产品状态，不自动证明每一分句都被该条引用支持。G03 的 absent 是产品保守拒答效果，不能折算为模型自己输出空 items。

## 定位方式与判据

以下用 item 1 表示数组 `[0]`，依此类推。`first` 指 `model_outputs[0].business_json`，`final` 指 `product.analysis`，`request` 指 `business_requests[0].business_request`。链接及行号均指原始 case JSON。

- G02：分别检查每个 item 的 `sources` 和 summary 的 `summary_sources`。事实在其他输入、其他条目或完整草稿中出现，不能自动补足该条自身引用。Memory 的 `source_span_id` 是来源绑定，不表示引用 Memory 时已引用其原文的所有额外事实。
- G03：当前实际输出契约只有 `summary` 和带 `evidence` 的 `items`，**没有 `summary_sources` 字段**。因此摘要核对实际请求和所列 item 的支持关系，不机械套用 G02 字段要求；item 独立核对自身 `evidence` 和 chapter ID 绑定。
- 章节标题、章号、revision、截断说明属于实际请求元数据，单独核对；不把这些元数据缺少叙事 SourceSpan 当作新增情节幻觉。条件性的提案比较与已经发生的故事事实分开判定。

## G02 逐例

### 01 — three-sentences：首摘要不通过，最终可接受

[原始 JSON](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v2/runs/flash-v2-20260926-01/cases/01-g02-three-sentences.json>)。

实际输入三句为“林默走进北门。银钥匙已经交给陈澈。她此时已经知道弟弟还活着。”，三条 draft_claim 各自完整，draft revision 2。请求正文和 claims 从第 689、696 行开始。

| 范围 | 首答与最终逐项结论 |
| --- | --- |
| items 1–3 | 分别复述三句，各引对应 claim 1、2、3，均支持。第三句仍保留“她”，没有擅自把代词绑定为一个新人物 |
| items 4–5 | 温岚不知道代号含义、罗盘由温岚持有，各引相应 Memory，支持 |
| item 6 | 雾钟条件引 ring_condition Memory，支持 |
| items 7–8 | 白船未靠岸及来源未知、异常钟声原因未解，各引相应 open_thread Memory，支持 |
| items 9–11 | 航图地点、退潮时间、电台求救码，各引相应 Memory，支持 |
| item 12 | 第 10 章钟声、罗盘、汽笛原文，引该章完整 span，支持 |

首摘要第 450 行写“温岚尚不知‘廊桥钥匙’的含义，黄铜罗盘仍在她手中；白色渡船未靠岸且来源未明，异常雾钟……原因仍未解开”，但第 451 行起三个 `summary_sources` **只有草稿三句**。这些背景事实虽存在于请求的 Memory，仍不受该摘要自身引用支持。

最终摘要第 416 行仅由三个草稿条目组成，第 417 行起引用三个对应 claims，主要叙事事实均支持；最终 `completed/supported`、draft `covered` 在本例限定内可接受。首答 12 条和最终 12 条文本一致。

### 02 — long-sentence：首答与最终均有两个 item 引用缺口

[原始 JSON](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v2/runs/flash-v2-20260926-01/cases/02-g02-long-sentence.json>)。

本轮保存了完整实际业务输入，可直接确认 `request.layers.written.draft.excerpt` 是 299 字，包含句尾；`draft_claims[0].text` 只有前 240 字，全部是“林默沿着长廊向前走”的重复，缺失银钥匙交接与弟弟存活。对应正文和 claim 从第 651、658 行开始。无需再像 V1 那样事后重建完整 draft。

**缺口 A：item 1。** 首答第 430 行、最终第 232 行均写：

> 当前草稿（第十一章《未归的航标》，修订2）中，林默沿长廊向前走，最后把银钥匙交给陈澈并得知弟弟还活着；所选草稿证据在240字符处被截断。

唯一引用为 `draft-claim-draft-c864f5f6-8c3b-435b-ac75-bab9daee5f88-r2-1`，最终 `items[0].sources[0].excerpt` 也仅有前 240 字。承认截断不会让这条引用支持其尾部断言。句尾确实在完整实际输入中，故准确分类为 **自身引用缺口，不是凭空编造**。

**缺口 B：item 2。** 首答第 440 行、最终第 245 行均写：

> 已确认：温岚看得懂潮表上的坐标，但尚不知道“廊桥钥匙”这一代号指向什么。

唯一引用 `mem-b4780ea0-fd47-4749-9a7a-a652df579a71` 的完整语义是 `character_knowledge / 温岚 / does_not_know / 廊桥钥匙的含义`。它支持后半句，不支持“看得懂潮表上的坐标”。正确原文 `span-7b9805b0-9cef-4a29-aa98-d62686a2c74c` 确在实际请求的 `source_spans[2]`，且 item 12 自己正确引用了它；item 12 的引用不能借给 item 2。

| 其他条目 | 独立核对 |
| --- | --- |
| items 3–9 | 罗盘持有人、航图地点、退潮、电台、雾钟规则和两条未解线索，各自 Memory 支持 |
| item 10 | 第 8 章值守簿交接与约定，引第 8 章 span，支持 |
| item 11 | 第 6 章时间、三次求救码与信号方向，引完整第 6 章 span，支持 |
| item 12 | 第 4 章坐标能力与代号未知，引完整第 4 章 span，支持；是 item 2 的同事实引用正控 |

首摘要第 412 行自身引用只有 draft claim、代号未知 Memory、罗盘 holder Memory；因此句尾和“航图位于雾线水门外锚柱”未被自身引用支持。最终摘要第 378 行将 item 1 与第 8、6 章条目拼合；第 379 行起三个来源支持后两段，**仍不支持草稿句尾**。

最终 `completed/partial` 且原因 `draft_claim_truncated` 正确披露范围，但 12 条文本均保留。该例最终语义不接受：2 个 item 缺口和 1 个摘要缺口仍在；摘要句尾与 item 1 是同一底层事实缺口的两处呈现，不算两个独立成因。

### 03 — body-limit：首摘要不通过，最终在范围披露下可接受

[原始 JSON](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v2/runs/flash-v2-20260926-01/cases/03-g02-body-limit.json>)。

原正文是“林默在雾港核对潮汐表。”重复 180 次，共 1980 字；实际 draft excerpt 600 字，选中 8 条完整、同文的 claims，最终引用其中 1、8 两条。未选 172 条、已选未引 6 条，产品报告 `draft_claim_uncovered`、`draft_claim_unselected`、`draft_body_truncated`。

| 范围 | 首答与最终逐项结论 |
| --- | --- |
| item 1 | 引 claims 1、8，支持核对潮汐表；文字限定“所选草稿片段”“未提供更多情节”，与输入截断信息相符 |
| item 2 | 航图地点和右下角缺失，同时引 Memory 与完整第 7 章 span，支持 |
| item 3 | 罗盘交接与月牙裂纹，同时引 holder Memory 与第 9 章 span，支持 |
| items 4–5 | 代号未知和雾钟条件，各引对应 Memory，支持 |
| item 6 | 求救码时间及信号方向，同时引 Memory 与第 6 章 span，支持 |
| item 7 | 退潮时间引对应 Memory，支持 |
| item 8 | 异常钟声原因未解、握罗盘与汽笛，同时引 Memory 与第 10 章 span，支持 |
| item 9 | 白船未靠岸、来源未明，引相应 Memory，支持 |

首摘要第 497 行提及罗盘保管人、求救码、退潮时间、两条未解线索，但第 498 行起自身来源只有 claim 1、航图地点 Memory、雾钟条件 Memory。上述额外背景事实未被摘要自己的来源覆盖。

最终摘要第 463 行仅保留选中草稿内容与退潮时间，第 464 行起引用 claims 1、8 及退潮 Memory，主要叙事事实受支持。9 条 item 文本均保留，未发现明确自身引用缺口。

限定： “所选草稿片段在此处截断”略笼统，claim 1、8 本身并未截短，截断的是 draft excerpt 和选取范围；结合产品范围说明，不另计为情节错误。本例全篇反复同一句，不能证明系统发现了截断后独有的新事实，也不能把仅引用 2 条解读成实际漏掉 178 种不同情节。

### 04 — identical-text：首摘要不通过，最终可接受；月牙裂纹这次有支持

[原始 JSON](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v2/runs/flash-v2-20260926-01/cases/04-g02-identical-text.json>)。

正文正好两句“林默走进北门。”，两条 claims 分别完整。item 1 引两条，支持“正文仅有两句重复”的概述，未强行把同字文本当成两个不同事实。

| 范围 | 首答与最终逐项结论 |
| --- | --- |
| item 1 | 两句草稿及重复情况，引两条 claims，支持 |
| items 2–9 | 电台、退潮、雾钟规则、两条未解线索、罗盘持有人、代号未知、航图地点，各自对应 Memory 支持 |
| item 10 | 第 10 章未关闸响钟、温岚握盘、白船汽笛，引完整第 10 章 span，支持 |
| item 11 | 第 9 章交接及月牙裂纹，引完整第 9 章 span，支持 |
| item 12 | 第 8 章交接值守簿与约定，引完整第 8 章 span，支持 |

item 11 首答第 559 行、最终第 387 行写“苏岑把带月牙裂纹的黄铜罗盘交到温岚手里保管”，自身来源是 `span-2abb6703-609c-4249-a127-836e5b956cc6`；最终 source excerpt 与实际请求 `source_spans[2].body` 都确有“带月牙裂纹”。**本轮这条支持充分，不能把 V1 的缺口沿用到这次结果。** 同样，单次不同回答不构成产品修复证据。

首摘要第 437 行的“白色渡船未靠岸、来源未明”没有自己的来源；第 438 行起只引 claim 1、电台 Memory、异常雾钟 Memory。重复动作的表述可由实际两句输入验证，但摘要只引一条的标注也较简略；计数仍以明确白船缺口为一例，不额外扩成一个故事幻觉。

最终摘要第 403 行只复述两句草稿与第 10 章片段，第 404 行起引两条 claims 及第 10 章 span。12 条 item 文本均保留，最终主要叙事事实和 `covered` 状态可接受。

## G03 逐例

四例实际请求均为新的最小结构：一个 `dynamic_state / 星钥 / holder / 星钥始终由乔霁保管。` Memory，固定绑定 chapter 1 span 1；两个明确章节及各自 span；draft revision 1、空正文、无 claims；角色、计划、世界条目均为空。memory version、source revision 都为 1。这里不再借用 V1 的旧温岚 / does_not_know 教学记录。

各例是隔离运行，重复的 fixture ID 是相同逻辑标识，不表示一个项目按时间连续改写；不把这四例合成来源版本演化测试。absent 刻意保留确认 Memory 与来源文本不一致，是预设负例。

### 05 — short-target：有限可接受

[原始 JSON](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v2/runs/flash-v2-20260926-01/cases/05-g03-short-target.json>)。

`request.layers.written.source_spans[0]` 第 375 行起是 20 字完整目标原文：“星钥始终由乔霁保管。平静的溪水流过石桥。”第二章明确没有星钥保管事实；`target_source.status=selected`。

- item 1：目标 Memory 与提案的保管人不同，仅讨论这条记录替换 / 修订，自引 Memory，支持。首答第 269 行，最终第 213 行。
- item 2：第一章确有乔霁保管句，自引第一章 span；并写“若提案生效”及“不代表已核查全部受影响章节”。首答第 280 行，最终第 228 行。
- item 3：第二章没有相关事实，仅称“本次所选证据中未发现……依据”，自引第二章 span，支持。首答第 291 行，最终第 243 行。

首 / 最终 summary 分别第 264、253 行，文本一致，正确描述目标 Memory、来源第一章、第二章不相关，以及空草稿无法判断。最终 supported、三个原样保留 item，可有限接受。

限定：item 2 的“若提案生效，该处既有书面表述与新的保管设定不一致”默认提案覆盖原有设定。若用户只是要求在未来发生正常交接，则历史第一章可能仍然成立。这是提案缺少生效时间与改写范围的歧义，本轮不计为已经证实的章节事实幻觉。

### 06 — deep-target：有限可接受

[原始 JSON](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v2/runs/flash-v2-20260926-01/cases/06-g03-deep-target.json>)。

请求第 375 行起第一章 span 为含省略号的 502 字摘录，`target_source` 记录原文 1510 字、excerpt_truncated true、selected。摘录中确实保留完整“星钥始终由乔霁保管。”，因此不是仅找到了 source ID 而没把关键句给模型。

- item 1：自引目标 Memory，比较提案改变目标值。首答第 269 行、最终第 213 行，支持。
- item 2：自引第一章 span，明确说片段有原保管人且文本被截断，仅比较人名不同。首答第 280 行、最终第 228 行，支持。
- item 3：自引第二章 span，限定在选定证据中未见相关保管内容。首答第 291 行、最终第 243 行，支持。

首 / 最终 summary 第 264、253 行一致，正确限定“当前选定证据”，没有把局部摘录提升为整稿确认。最终三个原样 item supported，在来源召回和章节绑定这一窄范围内可接受。

### 07 — fact-absent：首答有条件地比较 Memory，最终 insufficient 可接受

[原始 JSON](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v2/runs/flash-v2-20260926-01/cases/07-g03-fact-absent.json>)。

实际第一章 span 第 333 行起写“山坡上没有关于星钥保管者的记载。平静的溪水流过石桥。”，第二章也无保管事实；`target_source.status=unlocated`。确认 Memory 却仍写乔霁始终保管，是 case 定义主动制造的来源不支持状态。

首摘要第 218 行明确写“未在本次选定证据中定位到支持该确认事实的原文”，没有声称第一章记载乔霁保管。

- item 1 第 223 行：“该确认记忆记录星钥始终由乔霁保管，提案改为由沈砚保管，因此该记忆的保管者事实将被推翻或需改写。”后半段又明确来源未定位、片段没有支持原文。它同时引 Memory 与该 source span，比较的是**给定记录与假设提案**；“将”处于提案语境，不是报告已发生的交接。
- item 2 第 238 行：第一章所选片段未呈现可判断变更影响的保管事实，自引第一章，支持这种不能确定的结论。
- item 3 第 249 行：第二章未显示直接关联，自引第二章，并限定“本次选定证据”，支持。

因此不能把这三条误计为“捏造章节中有乔霁保管事实”。最终第 207 行摘要为“当前证据不足以支持影响结论。”，`insufficient`、`items=[]`，符合预设产品保守行为。但这意味着产品移除了三个首答条目，不是模型原始回答自己采用空 items；若后续要求未定位时模型必须为空，须把该更严格格式规则与语义事实错误分别计分。

### 08 — other-chapter：绑定与事实可接受，保留时间范围歧义

[原始 JSON](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v2/runs/flash-v2-20260926-01/cases/08-g03-other-chapter.json>)。

第一章同 deep，502 字摘录确有目标句。实际 `source_spans[1]` 也包含干扰章正文：“第二章写明沈砚曾短暂触碰星钥，随后交还乔霁；星钥仍由乔霁保管。”故这次有真正执行其他章节干扰条件，不能沿用 V1 干扰原文未进入请求的问题。

- item 1：正确描述 Memory 的 dynamic_state、holder 和值；引用该 Memory，表示提案需改变记录。首答第 269 行、最终第 213 行。
- item 2：准确复述第一章乔霁保管，强调选定片段截断；自身只引第一章的正确 span。首答第 280 行、最终第 228 行。
- item 3：准确复述第二章短暂触碰后归还、自身只引第二章 span。首答第 291 行、最终第 243 行。

首 / 最终 summary 第 264、253 行一致，区分原保管状态、第二章短暂触碰与归还，正确承认草稿为空。三个 item 原样保留，均没有把第一章结论只挂在第二章原文上。

item 3 的末句“与提案的长期保管者变更不一致”含一个额外解释：提案原文只有“改为由沈砚保管星钥。”，未写“长期”或起效时间。若指回改既有设定，指出需同步复核第二章合理；若是第二章之后的未来交接，第二章仍可成立。因此将该项列为**时间 / 改写范围歧义，不计新增已证实幻觉，也不将本例升格为时间一致性判定通过**。

## 与 V1、实施者结论及后续决策的边界

1. 实施者 POSTRUN_REVIEW 中本轮两个 long-sentence item 缺口、四个首摘要缺口、一个最终摘要缺口、identical 月牙裂纹这次有自身支持、G03 三 supported 加一 insufficient，与本次逐例独立检查一致。
2. 本轮 8 例全部 source_case_ref 指向 V2 cases.json。G02 draft 文本与 V1 相同，但项目 ID、选中原文及回答内容不同，不能把月牙裂纹单次引用正确写成已修产品。G03 是新最小 fixture，空草稿和确定的 holder Memory 改变了任务难度及上下文；不能以 V1 两个失败到 V2 supported 声称模型 / 产品同输入提升。
3. 版本身份采用本轮交接所记录的 checkout HEAD `c3bd54ab019447354e8b1387e16b9aca3258b4c9`。本报告不承担根审阅者的代码冻结、HTTP 用量与哈希完整性验收，也没有重新验证当前源码；这里只通过保存输入和输出审阅语义。
4. 建议保留 G02 长句与坐标两个引用缺口作为后续可复现实例。若授权产品修补，应同时测：尾部真实进入引用、同条多事实需相应来源、摘要重建不得继续继承不支持的 item；不能以 partial 文案代替这些条件。
5. G03 后续若验证连续性推理，应分别明示“回改原章节设定”和“未来章节合法交接”，不能用一个无时间范围的提案混合打分。本轮只接受实际触发的直接来源与目标绑定范围。
6. 本报告不重评 V1 V8 / G01、不证明盲测能力、不涉及真实作者研究、Agent、用户验收或上线 Gate。原始失败链保持不变。

