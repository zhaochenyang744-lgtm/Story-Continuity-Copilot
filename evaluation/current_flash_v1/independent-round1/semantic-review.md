# Flash v1：G01 / G02 / G03 独立逐例语义复核

复核日期：2026-09-26。对象为 `runs/flash-v1-20260926-01/cases/25-…42-….json` 的 18 个已保存结果，以及冻结 PLAN/cases、`run.py` 和必要产品/seed 源码。没有新模型调用、没有运行评测入口或测试、没有读取业务数据库、密钥或 `.env`，没有修改旧结果、标签或产品。仅新增本报告。

## 阻断结论

1. **G02 不能按 coverage 标签宣布语义通过。** long-sentence 的末尾两项事实在模型首答、最终分项及最终摘要中都保留，但该分项唯一引用只有前 240 字，不含末尾内容。identical-text 的“带月牙裂纹”也不受该分项自己的两条 Memory 引用支持。二者均是“事实在其他已供上下文存在，但自身引用不足”，不能直接叫事实编造。
2. **G03 两例真实端到端失败仍成立。** short-target、other-chapter 首答把 `draft-*` 当作 `area=chapter` 的 target，均终止于 `failed/evidence_unresolvable`；不是 HTTP 失败，也不是成功的无冲突判断。
3. **G03 测例准备存在污染，不能把四例合并成干净的模型准确率。** 任取教程 Memory 后仅更新 subject/value；deep 的产品证据明确显示“星钥 · does_not_know”。另外 other-chapter 准备的干扰原文没有实际进入模型输入，未实现计划中的特定测试条件。应以新评测身份重建一致 fixture，再重跑受影响范围，不能覆盖本轮。
4. **需要纠正交接中的语义定性。** absent 首答没有把缺失原文断言为已存在的章节事实；它明确说无法确认该章兼容性。deep / absent 的温岚项都写“无直接关联／无法判定”，不构成确定性影响幻觉。产品按更严格的 `unlocated` 规则清空 absent 是已验证事实，但不能反推模型在该章上作了确定性误报。

## 分母与层次

- 版本限定：这是交接中记录的 HEAD `c3bd54ab019447354e8b1387e16b9aca3258b4c9` 对应首轮保存输出；G02绑定 saved draft revision=2，G03绑定原教程 draft revision=1，来源revision=1、Memory version=4。每个案例是独立项目，不把不同案例的随机目标当作同一项目的版本迁移，也不把旧事实扩展为所有未来时间都不变。
- 反事实限定：G03讨论“提案若生效、原保管断言需相应修改”，不是已执行了改写或当前事实已经变化。若作者本意只是后来正常交接而非重写原有设定，“始终由乔霁保管”与未来沈砚接手还需明确时间范围；本轮不能据此推导所有保管人变化都是连续性冲突。对short/other的有效局部项分析，也不等于“删掉坏项后该run已成功”的反事实测试；实际终态仍为failed。
- 本报告覆盖 18 个不同案例：G01 10、G02 4、G03 4。记录中各有 1 次 HTTP 派发、1 个 parsed business JSON；总计 18 次，**0 次模型修复**。产品的过滤或摘要重组不是第二次模型回答。
- G01 十例：首答与最终产品类别均 10 / 10 对应冻结标签；6 个兼容场景、4 个冲突正控。没有 product normalization/downgrade。
- G02 四例都 completed；coverage 为 2 covered、2 partial。共 44 个原始分项和 44 个最终分项，四例分项文字均未被改写或删除。确认 2 个最终分项存在自身引用缺口，分布在 2 个案例；其余分项的主要叙事事实可由所列引用组合支持。标题、章号等上下文元数据不另算叙事事实。
- G02 四个原始摘要均有自身 `summary_sources` 不足；最终摘要重组后 3 个有来源支持，long-sentence 仍继承缺口。这是固定样本的逐项复核，不是模型总体准确率。
- G03：2 failed、1 completed/supported、1 completed/insufficient。不能把 failed 算成 no_conflict，不能把源证据 guard 正确视为模型首答正确。因 fixture 问题，不给四例总体语义通过率。

## G01 十例

十例保存的实际 `input_refs.claims[0].text` 和 `allowed_evidence[0].prompt_excerpt` 均与案例 claim/evidence 逐字相同；均为单条主张、单条来源。`run.py:240-251` 使用空 Memory。四个冲突首答均给出 character_knowledge / confirmed_conflict、正确来源 span-1、两侧字面时间锚点；建议修改也回到证据中的未知状态。

| 文件 / 案例 | 独立标签判断 | 首答 → 产品 |
|---|---|---|
| 25 / later-hour | 今日20点未知、22点认出；允许后来得知，不冲突 | 空 issues → 空 issues |
| 26 / relative-day | 昨日18点未知、今日18点已知；不同日期，不冲突 | 空 → 空 |
| 27 / ordinal-day | 第一天未知、第二天已知；不同日期，不冲突 | 空 → 空 |
| 28 / explicit-lie | 故意谎称不知，与实际已知相容 | 空 → 空 |
| 29 / recollection | 今日回忆昨日未知，与今日已知相容 | 空 → 空 |
| 30 / within-day-change | 来源已写19点获知，与19点已知一致 | 空 → 空 |
| 31 / positive-relative | 今日18点同一人、同一身份知识已知/未知矛盾 | confirmed_conflict → confirmed_conflict |
| 32 / positive-calendar | 9月25日18点同一知识状态相反 | conflict → conflict |
| 33 / positive-ordinal | 第十一天18点同一知识状态相反 | conflict → conflict |
| 34 / positive-unrelated-memory | 秦渡同一时刻矛盾；陈澈另句回忆不应改变秦渡判断 | conflict → conflict |

上述标签没有发现需重标的语义歧义。结论仅限这些暴露、短句、单来源样本，不能外推长篇时间解析或未见作者资料。

## G02 逐例

### 35 — three-sentences

- 草稿三句分别写林默进北门、银钥匙交给陈澈、她已知弟弟活着。首答前三项各引自己那一句，正文含义正确；没有把“她”强行消歧成另一个角色。
- 原始摘要引用只有三条 draft_claim，却又陈述温岚持有罗盘、低室电台求救码、异常雾钟/白船等 Memory 内容。这些事实在其他输入/分项有依据，但**不在该摘要自己的引用集合内**，首答摘要引用不足。
- 最终 12 项都保留，主要事实各有自身引用；coverage=covered 的三个草稿 ID 对齐。最终摘要被重组为第8章和温岚知识边界，引用可支持。
- 产品摘要本身已不包含当前三句草稿，尽管分项完整。这是摘要优先级/体验限制，应与“草稿完全没进入结果”区分；本例不把它另计成引用错误。

### 36 — long-sentence

- 保存正文 299 字，完整草稿 excerpt 也为299字；唯一 draft_claim 实际 supplied_chars=240、truncated=true。原文末尾是“最后把银钥匙交给陈澈并得知弟弟还活着”。
- 首答第1项陈述上述末尾，唯一引用是被截断的 draft_claim，其 excerpt 只有长廊重复文字。最终第1项及最终摘要仍原样保留末尾。`partial/draft_claim_truncated` 只披露范围，未修复该项引用。
- 证据见 `36-g02-long-sentence.json` 的 `input.saved_draft`、`product.retrieval.draft_claim_scope`、`product.analysis.items[0]`、`product.analysis.summary` 及首答对应项。
- 判定：**首答引用契约不足，产品保留同一不足；不是无上下文编造。** “模型拿到完整299字草稿 excerpt”可由保存正文、excerpt_chars 与当前组装源码事后核对，但完整 `layers.written.draft` 未原样保存，必须标为源码辅助重建。

### 37 — body-limit

- 180 条相同句子，选入8条、分项引用前2条；正文摘录被截断，172条未选入。模型只说“已保存的草稿片段显示”，没有声称全书/完整正文都检查了。
- 原始摘要另写退潮时间，但 summary_sources 仅为草稿、航图位置和电台求救码，未引退潮 Memory。
- 最终9项主要事实均有自己的引用组合；最终摘要的草稿片段与退潮时间也各有引用。coverage=partial，列 draft_claim_uncovered、draft_claim_unselected、draft_body_truncated，符合实际截取范围。
- 判定：分项/产品范围披露通过；首答摘要引用不足。由于180句内容完全相同，本例不能证明模型能处理截掉区域内的新事实；结构覆盖不足与新增语义遗漏不是同一个指标。

### 38 — identical-text

- 草稿同一句出现两次，首答第1项同时引用两个不同 claim ID，正确描述重复文本；最终 covered 对应这两条，不能把重复正文自动当错误。
- 原始摘要包含白船未靠岸/来源未明，但 summary_sources 只有草稿、雾钟规则、异常雾钟。其“第10章”也不在这些 Memory 引用正文中；相关来源虽然供给过，但未被该摘要引用。
- **第5项主要补充属性引用不足**：“温岚目前持有带月牙裂纹的黄铜罗盘；她尚不知道廊桥钥匙的含义。”该项只引 `黄铜罗盘 · holder → 温岚` 与 `温岚 · does_not_know → 廊桥钥匙的含义`，没有月牙裂纹属性。该属性在本次实际提供的第9章 SourceSpan中，因此是自身引用遗漏，不是属性凭空产生。最终项未移除或补引用，产品仍显示 supported。
- 最终摘要只选重复草稿和第6章电台来源，所选两部分有支持；摘要重组未解决第5项的缺口。

## G03 逐例与错误归因

### 39 — short-target

- 目标20字来源确实含星钥事实，target_source=selected；首答 Memory 项和真实章节项引用了该直接来源，主干提案差异有依据。
- 第3项却是 `area=chapter`、`target_id=draft-76896…`，证据全是 draft_claim。它表达的是“当前草稿无法认定直接冲突”，不是虚构某章确定冲突，但其目标类型不合法。
- 产品在 `engine.py:558` 的目标归属检查终止整个结果，`failed/evidence_unresolvable`；没有第二次修复。这是首答契约错误和真实分析失败，拒绝错误目标的防护仍发挥了作用。
- 首答摘要另称“当前草稿与所选证据中未出现星钥或沈砚”，与自身已引用星钥来源及下一章节项矛盾。这是该首答的范围措辞错误，不由 target ID 错误造成。

### 40 — deep-target

- 1510字原文中的目标句进入502字符带省略号摘录，直接 Memory 与章4项都引用正确的同章来源，产品保留 supported。就深处来源召回和章节绑定这两个局部条件而言通过。
- 温岚项明说“与星钥保管无直接关联”“影响无法从本次选取证据判定”，引用温岚角色记录也支持其罗盘/知识背景。**不能把这一冗余、不确定项判作确定性幻觉。** 全局 supported 容纳一个不确定项可讨论呈现粒度，但不能倒改模型语义。
- 摘要“未发现沈砚或乔霁的出场记录”口径较松：片段确实出现乔霁保管事实，但没有动作出场场景或其角色记录；不将该歧义直接新增为确定误报。
- 产品给出的目标 Memory 标签是“星钥 · does_not_know”（JSON第250、264行），属于下述 fixture 污染。不能据此宣布干净的物品保管语义验收通过。

### 41 — fact-absent

- 实际来源26字明确没有星钥保管者记载，target_source=unlocated。模型摘要也明确识别该来源没有保管者；章节项原文是“无法确认该章正文与提案的兼容性”，角色项是“无法据此判断提案对温岚的影响”。
- 唯一确定差异是 Memory 项：输入给了被确认的“星钥始终由乔霁保管”，提案拟改为沈砚，模型说明这是对该记录的改写，并明确提案不等于已经变更。**不能将这种对已给 Memory 的差异描述算作未引用原文章节却下确定结论。** 它与“来源不存在、Memory仍被标已确认”的评测矛盾设置有关。
- 产品执行更严格的 unlocated 规则，整组输出清空为 insufficient、items=[]，保护路径通过。若冻结验收策略要求模型自身一见 unlocated 就返回空 items，可以记策略不一致；不可把它同义改写为模型虚构了章中事实。HANDOFF 的“one first-model overclaim”需要这一区分。

### 42 — other-chapter

- 目标事实在502字摘录中，首答真实章节项引用其自身章3来源，没有看到“章A引用章B”的确定影响项。
- 与 short 同样新增 `area=chapter` 的 draft ID，产品 failed/evidence_unresolvable，属于契约目标错误；不能把它当跨原文章节错引失败。
- `run.py:316-320` 将另一个章节片段改成“另一章只记载沈砚经过石桥，没有星钥归属事实”。但已保存实际 `input_refs.source_spans` 只有目标章3及教程章2/10/9，**没有这段干扰文本**。因此 intended other-chapter 场景未有效送入模型；本例不能覆盖该专门条件。

## fixture 污染与证据完整性

### 直接可见的准备问题

`run.py:306-315` 在教程当前 Memory 中 `LIMIT 1`，未固定语义目标，也未 ORDER BY；随后只改 subject/value 和所连 SourceSpan 的 body/label。四次实际目标分别落在章9、4、7、3，并非同一基础 fixture 只改变来源长度。

| 案例 | 实际目标章 | 原教程记录类型/谓词 | 证据层次 |
|---|---:|---|---|
| short | 9 | dynamic_state / holder | 来源章号为原始记录；类型/谓词来自 seed_data:41 及不修改这些字段的 runner，属事后重建 |
| deep | 4 | character_knowledge / does_not_know | does_not_know 标签在产品结果直接保存；类型来自 seed_data:43 重建 |
| absent | 7 | dynamic_state / location | 来源章号保存；原谓词来自 seed_data:45 与 runner 重建 |
| other | 3 | event_timeline / time | 来源章号保存；原谓词来自 seed_data:42 与 runner 重建 |

把“星钥 / 星钥始终由乔霁保管。”塞进 does_not_know、location、time 等三元组，使输入层次自相矛盾。另保留了原教程人物、角色状态、代号和关系：温岚/苏岑/黎舟、罗盘、雾钟、廊桥钥匙；G03当前草稿仍是原教程的罗盘同时两处、随后转移、黎舟告诉苏岑代号含义这四句。目标原文则被替换，原章节标题/摘要和其他 Memory/角色的来源关系未同步重建。

这些背景不是模型凭空添加的人物。它们是否应作为干扰条件，需要在计划中明示；否则会把评测准备不一致误算为模型变化。G02同样只替换正文，保留第11章《未归的航标》和教程 Memory/来源；其“她”代词在输入本身未明确消歧，模型重复“她”不算错。

G03四例 `source_case_ref` 还默认指向 V8 case set，而实际来自本次 cases.json；这是来源元数据错误，不是模型错误。

### 哪些可以判定，哪些不能完全重建

`run.py:174-182` 的 input_refs 只保存 claims、draft_claims、source_spans、retrieval、proposal；**没有原样保存 confirmed.memory_records、written.draft、identity.characters/aliases、reference 或 planned 层。**

- 不阻断本报告的长句引用缺口、ID类型失败、深处句子是否被供给、unlocated文本、另一章干扰是否入选和G01标签核查；它们都有现存输入/输出的直接证据。
- 产品的 cleaned citation 保存 label/excerpt，可独立核对作者实际看见的引用是否支持该项；因此第38例“月牙裂纹”缺自身支持仍可确认。
- 已保存正文、长度与当前组装源码可重建299字 draft excerpt 的内容；这属于事后源码重建，不能称为原始实际请求快照。
- 教程 Memory谓词/类型和角色字段可借 seed_data、runner和输出反向核对部分内容，但原始完整 UUID映射、所有未引用条目以及完整层次不在保存input_refs中；本报告没有重新创建DB/执行harness来冒充原始输入。
- 因此完整重放一致性和G03全部层语义归因受阻；尤其不应把 deep 的 polluted Memory 当作标准保管案例，也不应称 other-chapter 的计划条件已验证。

## 下一轮评测入口建议（未执行，非产品修改）

1. 为G03建立最小一致 synthetic project，固定逻辑ID和章序。Memory完整设置 project/version/review_status、memory_type=dynamic_state、subject=星钥、predicate=holder、value=乔霁、source_span_id以及有效期；SourceSpan、章节正文/摘要/标题、source_revision和项目source_revision保持一致。不要复用任意教程行只改两列。
2. short/deep/absent/other共用同一基础上下文，仅改变计划字段。absent 要明确是“故意造出Memory和原文矛盾以测保守策略”的负控；分别评估模型对Memory差异、原文章节影响、产品unlocated guard，不能混成一条笼统“不得任何确定语句”。
3. other-chapter 固定干扰章ID，并在调用前断言该干扰文本实际进入 source_spans/reference，确保能检查目标章与引用章的绑定。失败就标 fixture_precondition_failed，不发模型请求或计入该语义条件分母。
4. 当前草稿使用与星钥主题一致或明确标注“无关”的最小文本；如保留教程旧角色作为干扰，冻结其完整数据并预先说明“不确定/无影响说明”允许还是应省略。角色不存在也要作为明确条件，而不是随机副作用。
5. G02需要同时保留草稿主张范围负控、背景事实引用和摘要来源评估；body-limit 除重复文本外应有截取外新事实，避免把结构partial冒充真实遗漏能力测试。已有四例不改标签或覆写结果。
6. 在每次Provider调用前保存经允许的完整业务输入对象及哈希：bindings、全部layers、proposal、retrieval与output_schema；包括修复调用。此对象可去除凭据、HTTP头和私有推理，不等于保存秘密或原始HTTP包。记录稳定case来源，不用V8默认来源指向G03。
7. 原始首答、修复（若有）、产品过滤、终止失败分层计数。新一轮使用新ID；本次失败、污染条件和手工审阅都保留。

本报告仅为独立语义复核；是否修改产品、如何改提示词、是否追加真实调用和通过产品Gate由主控另行决定。
