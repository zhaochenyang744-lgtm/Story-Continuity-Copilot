# V4 G02 六例真实输出：独立人工语义复核

日期：2026-09-26。运行身份：`flash-v4-g02-20260926-01`。只审该运行已保存的六份 case JSON、实际业务请求、全部模型答复及最终产品结果；另只读检查 `backend/app/brief_citations.py`。未发起 Provider / HTTP 调用，未运行产品测试、读取数据库或凭据，未修改产品、旧版本或本轮原始结果。尚未交付的比较集不在本报告结论中。

## 限定结论

**长句尾部和已知的自身引用缺口，在本轮最终显示中得到实证改善；但六例不能整体按语义与有用性全部通过。** time-bound 的最终输出丢失今日知识变化，是需要返修的明确遗漏。dialogue-attribution 没有把对话提升为叙述事实，但引语边界破碎，且孤立闭引号导致 partial，完整引用框架未通过。

全部六例各有一个实际业务请求、一个首答、一次已记录 dispatch；`contract_repair=false`，**没有模型修复答复可审**。每例首答 12 条 item；最终也各 12 条，但不意味着逐条都被保留：time-bound 的最终新增首句摘录后，原来最后一个第 8 章条目不再出现。

六例首答摘要均有自身引用未覆盖的背景事实；六例最终 `model_summary_used=false`，是产品依据来源重新生成的摘要。不能把最终引用充足归功于首答摘要正确，也不能把产品摘录等同于通用语义判断通过。

| 案例 | 首答限定判断 | 最终限定判断 | 有用性与限制 |
| --- | --- | --- | --- |
| three-sentences | 三条草稿和其余 item 的事实各有支持；首摘要的四项背景未被自己的来源覆盖 | 三句逐条引原文，否定 Memory 谓词保留；自身引用可接受 | 仍有完整当前草稿与相关记录，非空壳；对象地点被归到 character_state，类别不精确 |
| long-sentence | 实际 D1 已是完整 299 字，首答尾部有支持；首摘要未解线索缺自己的引用 | 尾部在 item 和摘要自己的完整 D1 中，坐标原文与“不知道”分别正确引述 | 安全但摘要变成 395 字，其中草稿原文重复“沿长廊”28 次；凝练性明显下降 |
| body-limit | 选中重复句与各背景条目有支持；首摘要漏航图、电台来源 | partial 披露 172 条未选、6 条已选未引；叙事引用可接受 | 同一句以句 2、句 1 倒序重复，占用摘要；该重复语料不能验证未选范围独有事实的召回 |
| identical-text | item 引用有支持，包括月牙裂纹；首摘要白船事实缺来源 | 两条草稿可寻址，月牙裂纹完整引第 9 章；引用可接受 | 两次同文倒序原样呈现，不是两个新信息；非空壳 |
| time-bound | 首摘要正确描述昨日未知→今日读信得知，且自身引 D1+D2；但全部 12 个 item 漏掉草稿，摘要另有背景引用缺口 | **P2：只补昨日 D1，今日 D2 在最终所有 items 和摘要中消失**；partial 如实披露，未修复内容遗漏 | 保留背景很多，但丢掉本例最重要的新状态；不能仅按引用安全接受 |
| dialogue-attribution | 首答两条都保留陈澈说、温岚否认与自称，没有叙述者确认交接；首摘要仍漏未解线索来源 | **P2：引语边界破碎，闭引号单独成为未覆盖 claim；完整框架不接受**；未发现说话人归属或否定被反转 | 两方说法仍可读，不应误记为“交接已发生”的幻觉；引用质量与覆盖提示存在缺陷 |

这里没有汇总“准确率”。计数只用于描述六份既有记录；`supported`、`partial` 以及输出与引文相同，均不是完整语义和有用性的替代判据。

## 审阅口径与证据位置

以下 item 按 1 开始编号；JSON 数组则从 `[0]` 开始。每例检查：实际输入全文及其各层、逐条首答的 `sources`、首答 `summary_sources`、最终文本及自己的 sources、否定 / 时间 / 说话人、事实类别、是否把计划当成已成事实、遗漏和重复。源中有一句话不意味着那句话是叙述者确认的事实；引用必须保留表述层级。

六例的 `planned.character_plans/story_plans/world_plans` 都为空，且没有实际作者计划条目。因此这六例**未实测**“作者未来计划不能变成既成事实”；不能依据源码的“作者计划记录”前缀将此能力列为通过。六例知识 Memory 都是 `does_not_know`；肯定 `knows` Memory 的展示也不在这六例实测覆盖中。

### 01 — three-sentences

[原始 case](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/01-g02-three-sentences.json>)。

实际正文：“林默走进北门。银钥匙已经交给陈澈。她此时已经知道弟弟还活着。”三条完整 claims 在第 709、714、719 行；代词“她”没有足够上下文确认身份，本次首答和最终均保留原代词，未新增身份断言。

- 首答 items 1–3，第 477、487、497 行：分别写当前草稿中的三句，各引自己的 D1、D2、D3，内容有支持。但 section 为 `character_state`，与草稿来源层级不够清晰；最终改为 `recent_source`。
- items 4–11：罗盘 holder、航图 location、电台 received、退潮 time、钟声条件、两条 open_thread、温岚 does_not_know，都分别引正确 Memory。item 12 引完整第 10 章 span，保留“北潮闸并未关闭”与“却响一次”的否定 / 反差，没有倒置。
- 首摘要第 459 行仅引 D1–D3，却还写罗盘持有人、航图地点、电台时间和退潮时间。四项背景在其他输入中存在，但不受摘要自己的三条来源支持。
- 最终 item 1–3 第 279、292、305 行完整引述三句；摘要第 425 行也只引这三句。item 11 第 409 行明确“温岚不知道”，未把 value“廊桥钥匙的含义”误显示为肯定知识。

最终引文与所说层级可接受，三个当前草稿事实均在，没有只剩背景。最终航图位置条目第 331 行归 `character_state`；这是分类不精确，不是地点事实造假。

### 02 — long-sentence

[原始 case](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/02-g02-long-sentence.json>)。

实际 `request.layers.written.draft_claims[0].text` 第 669 行包含完整 299 字，尾部“最后把银钥匙交给陈澈并得知弟弟还活着。”已进入模型可引用的 D1；scope 也记录 source_chars=supplied_chars=299、truncated=false。这与旧轮 240 字 claim 的缺口不同，不能仍按旧截断判断。

- 首答 item 1 第 437 行概括长廊前行及句尾，自引完整 D1，尾部有直接支持。
- items 2–9 的 Memory 各正确；item 3 不知道代号，item 11 坐标能力加“不知道”直接引第 4 章完整 source span，未复现用 does_not_know Memory 支持坐标能力的旧错误。items 10、12 分别引第 6、8 章完整原文。
- 首摘要第 419 行引 D1、罗盘 holder、does_not_know，却又称异常雾钟与白色渡船均为未解线索。这两个背景判断缺少摘要自身来源。
- 最终 item 1 第 239 行和 summary 第 385 行，均实际包含句尾，并在其自己的来源中绑定完整 D1。最终 item 3 第 265 行保留“不知道”；item 11 第 369 行以“第4章所选原文”引完整坐标 / 未知句，语义有支持。

**有用性损失（P3）**：首摘要 83 字，最终摘要 395 字，核心动作前的“林默沿着长廊向前走，”重复 28 次全部进入摘要，再追加第 6、4 章原文。重要句尾没有丢，但摘要凝练性明显下降；不能把字面保真写成摘要体验同样良好。重复原先就存在于草稿，此处问题是摘要全量搬入，并非系统捏造重复事件。

### 03 — body-limit

[原始 case](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/03-g02-body-limit.json>)。

实际全文为同句“林默在雾港核对潮汐表。”180 次、1980 字，draft excerpt 600 字，选中完整 D1–D8。首答 item 1 第 535 行引用 D1、D2；items 2–9 各正确引用 Memory；items 10–12 分别是第 7、6、10 章原文，各有自己的 span，未发现把章节内容无来源搬到另一条目的情况。

首摘要第 517 行只引 D1、退潮时间和罗盘 holder，却也写航图地点、电台求救码，仍有自身来源缺口。

最终 item 1 第 337 行和摘要第 483 行，均按“句2原文……句1原文……”复述完全相同的短句。各自己的引文真实，但顺序倒置、信息重复。最终仍有时间线、地点、知识边界、未解线索和章节细节；不是空壳。

最终 partial 原因 `draft_claim_uncovered`、`draft_claim_unselected`、`draft_body_truncated`；保留 172 条未选、D3–D8 未引的范围事实，可接受为有范围限制的引用展示。不能由这组全篇重复文本证明对未选部分新情节的发现能力，也不能把 178 个未引用位置称为 178 种漏掉的情节。

### 04 — identical-text

[原始 case](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/04-g02-identical-text.json>)。

实际正文只有两句相同的“林默走进北门。”，D1、D2 可分别寻址。首答 item 1 第 464 行引两条；items 2–9 各 Memory 内容受支持；item 10–12 分别引第 10、9、8 章。item 11“带月牙裂纹”的原文在自己的第 9 章 span，首答第 568 行、最终第 396 行均有支持。

首摘要第 446 行只引 D1、钟声规则及异常钟声 Memory，“白色渡船未靠岸、来源未明”缺自己的引用。其“第10章”关联来自请求中的章节来源元数据，而非该 Memory 值本身；不将这类元数据再额外计为独立故事幻觉。

最终第 266 行、摘要第 412 行都显示“句2原文……句1原文……”，重复且倒序。内容安全、两条都可引用，但不应称为去重或精炼通过。背景 item 保留较完整，非空壳；最终 summary 与各 item 的事实有自身来源。

### 05 — time-bound：P2 内容遗漏

[原始 case](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/05-g02-time-bound.json>)。

实际两个完整、未截断 claim：

- D1，第 683 行：“昨日温岚尚未得知银钥匙的用途。”
- D2，第 688 行：“今日她读完陈澈的信，才知道银钥匙能打开潮汐档案柜。”

**首答哪些是正确的：** 第 433 行 summary 正确写“昨日尚不知……今日读完陈澈的信才知……”，且 `summary_sources` 包含 D1、D2。未把昨天未知与今天已知混成无时间状态，也没把“银钥匙”与背景“廊桥钥匙”强行当作同一物品。不过摘要随后提到罗盘、白船和异常钟声，其自身来源只有 D1、D2、廊桥钥匙 does_not_know，因此这些额外背景仍缺自己的引用。12 个首答 items 全是旧 Memory / 原文，**没有草稿条目**，存在重要信息只出现在摘要中的结构缺口。

**最终为何不接受：** 产品不用首摘要，只补了 D1：item 1 第 253 行、summary 第 399 行均显示“当前草稿句1原文：昨日……尚未得知……”。D2 在全部最终 items 和 summary 中消失，诊断记录 D2 的 final_item_uses=0、final_summary_uses=0。最终虽然 `partial`、`draft_claim_uncovered` 明确指出 D2 未覆盖，但没有满足本例“保留昨日未知与今日知道两个状态”的目标。

这不是产品说了一个假的“今日仍不知道”；它保留“昨日”限定，属于**关键状态遗漏 / 有用性失败**，不误计成否定反转。背景的“温岚不知道廊桥钥匙”谈的是另一把钥匙，也不是与今日银钥匙知识直接冲突。

同时最终还有很多旧背景，仍为 12 条：补 D1 后，首答 item 12 的第 8 章交接约定不再出现。这是当前结果的可见取舍，不推测其他未跑的上限情况。应优先保留本次完整草稿的两条时间状态，再考虑背景，而不能只凭有一个 draft quote 就当作当前草稿已被有用地保留。

**最小复现位置，无需新调用：** 读取此 case 的 `business_requests[0].business_request.layers.written.draft_claims[1]`、`model_outputs[0].business_json.summary` 及其 sources，再搜索最终 analysis；可看到输入与首摘要均有“今日……潮汐档案柜”，最终没有。根审阅者可直接使用该已保存 badcase。

### 06 — dialogue-attribution：P2 引语边界与覆盖提示

[原始 case](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/06-g02-dialogue-attribution.json>)。

完整实际草稿为：“陈澈说：‘温岚已经把潮汐表交给林默。’温岚摇头说：‘我没有交出潮汐表，它仍在我的背包里。’”。两个说话人给出不同说法，不足以认定哪一方是真实叙述事实。

**首答归属正确：** items 1、2 第 471、481 行分别是“陈澈说……”“温岚摇头否认……并称……”，自身引 D1、D2，没有抹掉说话人，也没有断言“交接确已发生”或“背包状态已被叙述者确认”。summary 第 453 行也保留“陈澈称 / 温岚否认并称”。但是摘要关于白船与异常雾钟是未解线索的分句，没有自己的引用（只引 D1、D2、罗盘 holder）。其余十条首答背景 item 自身来源支持所述事实。

**实际输入切分与最终引用有缺陷：**

| claim | 实际输入原文 | 结果 |
| --- | --- | --- |
| D1，第 703 行 | `陈澈说：‘温岚已经把潮汐表交给林默。` | 缺自己的闭引号，最终 item 1 第 273 行照样包入「」 |
| D2，第 708 行 | `’温岚摇头说：‘我没有交出潮汐表，它仍在我的背包里。` | 带上了前句闭引号，却缺本句闭引号；最终 item 2 第 286 行照样包入「」 |
| D3，第 713 行 | `’` | 仅一个闭引号，被当作独立 claim，最终未引用 |

最终 summary 第 419 行出现：`当前草稿句1原文：「陈澈说：‘……。」 当前草稿句2原文：「’温岚摇头说：‘……。」`。增加外层「」没有修复内部引语结构。首答的两方言说关系仍能读懂，但不能宣称完整引用框架已经保留。

最终 `partial` 的唯一未覆盖 claim 是 D3 那个闭引号；不是遗漏了一条新情节。此处未覆盖计数在字面索引上可解释，但作为作者看到的内容覆盖提示会误导。**应把这一点列为切分 / 引语呈现及覆盖质量问题，不写成模型编造对话事实。** 最小复核只需此 case 的三条 draft_claims、final items 1–2 和 draft_coverage，不需要新 Provider 调用。

## 只读源码与结果的对应关系

[brief_citations.py](<C:/Users/赵晨阳/Documents/ChatGPT/Agent 搭建/Story-Continuity-Copilot/产出/交付物/story-continuity-legacy-gap-repair/backend/app/brief_citations.py>)：

- 第 22 行起的 `_candidate_score`、第 64 行起 `locate_sources` 是词面选源；源码说明不作语义接受。不能用词面阈值或命中来源数量代替本报告的说话人、时间和谓词核对。
- 第 78 行按评分等字段逆序排序，能解释两个同文已引 claim 在结果中显示为句 2、句 1 的顺序；它不是叙事顺序排序。倒序是这两例实际结果，不扩展断言所有来源都会逆序。
- 第 109–112 行对 draft/source 直接加“原文”前缀；第 137 行只加外层「」，不处理内部引语完整性。因此上游已经切断的 D1/D2 引语框架仍以碎片显示。
- 第 116–123 行确实区别 `does_not_know`、holder、location 与其他谓词；六个真实结果中“不知道”都没有丢。其他谓词保留 `received`、`time`、`ring_condition` 等内部标签，事实关系仍可辨，但对作者读起来不够自然，是展示质量限制。
- 第 140–148 行将所有 `dynamic_state` 统一归 `character_state`。于是六例的“航图位于雾线水门外锚柱”均进入角色状态（例如 01 最终第 331 行、05 第 318 行）。**P3：对象地点分类不准确**，但不等于引用或地点事实错误。未观察到把实际计划归为事实，因为这些输入根本没有计划。
- 本轮六例 `added_source_count=0`，不能拿这次真实结果证明“漏引正确来源后自动补源”分支已获真实案例验证。time-bound 的补首句行为可从最终结果观察，但其调用入口和截取上限实现没有在本次授权源码范围内追查；报告不臆断精确修补位置。

## 证据保存与后续处理建议

本目录新建了 `semantic-diagnostics.json`，只含六例的原文件名、请求 / 首答 / 修复数量、文本行号、claim 在最终 item / summary 的引用次数、覆盖和重建元数据；不是模型评分器。原文件前后 SHA-256 与字节数分别存于 `original-case-hashes-before.json`、`original-case-hashes-after.json`，六份全部一致，无原结果改写。

优先返修 time-bound 的关键状态遗漏及 dialogue 的完整引用边界 / 孤立标点 coverage。重复句顺序和去重、长句摘要凝练、非角色对象的分类、内部谓词标签可作为明确的有用性改进项；这些不应掩盖本轮已经验证的长句尾部引用完整和否定谓词保留。

本报告不授权修代码或再次真实调用，不评尚未交付比较集，不从当前六例推导盲测准确率、整体模型能力、计划处理通过、用户验收或上线 Gate。
