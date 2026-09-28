# Flash V5：G02 六例独立审阅准备

状态：仅审阅准备，六例当前实际捕获和真实答复均待审；本文件不授予模型质量通过。创建时基线为 `7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2`。只读取现有源码、case、历史结果及报告；未执行产品、旧入口、Provider、业务数据库或新语料。

本表沿用已接受的 G02 定向回归目标，不修改 gold，不扩充六例。全部为已暴露开发材料。`preparation-audit.json` 保存每例完整正文、历史实际绑定/原文/claims/范围、来源哈希、当前静态预期及空白审阅字段。标为“当前预期”的字段来自源码阅读和已接受证据，**不是新 API 捕获**。新请求、模型或运行失败均须如实交付，不能改输入补跑刷绿。

## 捕获与身份准入

1. 新隔离合成 DB 经当前 API 保存正文并触发 `context_brief`；按每次实际 Provider 派发之前持久化的脱敏 business snapshot 审阅。核对项目、draft ID/revision、第11章绑定、source revision、memory version、作者材料版本/digest，以及 request hash、selected IDs 和原文。新 UUID 不等于历史 UUID，不从旧结果拷贝身份。
2. 与 V4 同正文不代表业务请求逐字相同。六例逐一比较正文 UTF-8 hash、claims/offsets、选中 SourceSpan 的章节与原文、Memory subject/predicate/value 和计划层级。差异列账；如果输入漂移使历史对照失效，限定比较范围，不能补造“完全相同”。
3. 旧 V4 每例8条 Memory、4段 SourceSpan（10段可用）和0条作者计划。复核新 capture 后再确认这些计数；仅在模型实际收到的来源白名单内审引用。未选章节、全库正文或 Memory 的 source_span_id 不能自动替代 item 自身引文。
4. 一份有效当前 capture 对应一个固定逻辑输入；按原有有界重试保留所有 transport attempt 和产品修复答。业务快照须先落盘，再派发。按实际 HTTP metadata 区分 complete/missing/partial/unknown usage。失败、超时或无可解析答复不能算通过。
5. 原首响应业务文本、首个可解析业务 JSON、每次修复业务 JSON、最终持久化产品分别保留和评分；凭据、header、cookie、隐藏推理不进入材料。模型最终调用并不一定是模型首答。没有修复答则明确“未发生”，不能拿最终产品填该栏。

## 逐 item、逐摘要判定口径

对每个阶段的每一条 item 按事实分句建行，字段至少为：`stage / response_ordinal / item_index / clause_text / own_source_refs / resolved_source_text / source_binding / proposition_support / layer_time_speaker / omission / verdict / evidence_pointer`。摘要另按自己的 `summary_sources` 建同样的分句行。实际条数随答复展开，不预设每例必有12项。

| 判定 | 必须核查 | 不能据此宣称通过 |
|---|---|---|
| 引用绑定 | source_type + ID 在当前请求白名单内，project/draft/source revision一致，展示 excerpt 与绑定原文对应 | 文本相似、相同人名、另一版本同文、全局 ID 并集 |
| 自身支持 | 一条 item 的每个事实分句均由自己的单条/多条来源支持；summary独立检查 | 另一 item 引过该源、全文其他地方有该事实、partial标签 |
| Memory | 同时保留 subject + predicate + value；否定、时间与对象类型不倒置 | 只看 value；把 does_not_know 当 knows；Memory 挂有 source_span_id就视为支持整段原文 |
| 两分句 | A+B 每一部分都有本条自身证据；坐标能力需要实际选中 SourceSpan，未知代号由 does_not_know 支持 | 只引未知代号 Memory 就声称“看得懂坐标且不知道代号”完整受支持 |
| 层级/时间/归属 | planned/confirmed/written 分清；保留昨日/今日、未/才、说话人和引语 | 词面相似度、substring、引用数齐全或产品摘录等于模型任意改写正确 |
| 有用性/范围 | 正常当前草稿仍有实质内容；8 selected claims与172未选范围分别核对；遗漏计数不双计 | 只返回背景/空壳就算安全通过，或把被省略背景当模型首答正确 |
| 容量 | 当前产品不超过12 items；摘要不超过400字/3来源，文本和来源同步取舍；selected草稿优先 | 摘要省略一个来源却保留其事实；8选中来源必须全放进摘要的错误要求 |

判定采用 `supported / unsupported / partially_supported / not_assessable`，另列信息遗漏、层级/时间/归属错误和有用性限制；不能把“没有无据陈述”混同于“应有信息完整”。机器结构符合仍保持 `pending_manual_review`。产品补引、来源重建或降级另记为产品行为，不回填模型首答正确。

## 历史对照限制

- V4 六例均只有一个业务请求、一个首答、一次生成派发，没有产品修复答；首摘要均有自身引用缺口。旧最终结果为来源重建（model_summary_used=false），这不证明首摘要正确。
- 前四个 V4 正文逐字复用 V2；时间和对话是后加合成例。旧 long-sentence 的 V4 请求已供给完整299字，不可继续用更旧240字问题描述它。
- 对话正文相同，但 V4 claims 是三片段：`陈澈说：‘温岚已经把潮汐表交给林默。`、`’温岚摇头说：‘我没有交出潮汐表，它仍在我的背包里。`、`’`。当前预期为两条完整引语。不得把旧三片段request/改映射旧答当V5真实输入或成绩；只能比较同正文在不同输入构建及产品代码版本下的限定行为。
- 后续离线 replay 的 long/time 使用旧首答与旧request证明产品守卫行为；对话使用新合成 API + scripted 输出验证新切分。这些均不是新版真实模型成绩。
- 对当前其余五例也先核对新实际来源与绑定，才能作有限同正文对照；一次样本差异不能归因为模型、提示词或产品单一因素，不汇总成通用准确率或盲测泛化。

## 保留问题与覆盖边界

三个 P3 单独保留：同文重复/倒序；长句摘要冗长；对象地点被归入 character_state。它们可以与引用安全同时存在，不能因本轮安全项通过而自动关闭。

现有引语防护只在既有中文前置说话人、弯/角引号与对应嵌套控制范围有证据，不保证 ASCII 引号、后置说话者、不闭合或任意小说句法。本次两方连续引语不是广泛语法验证。六例没有作者计划，不能从本次推出计划不得升级的真实模型能力；肯定 knows Memory、未选范围独有情节召回及真实作者效果亦未覆盖。新材料不扩展这些语料。

## 六例审阅表

所有阶段结论目前均为待审。以下当前 claims 是静态预期，须与 V5 派发前 capture逐字核验。


### 01 — g02-three-sentences

- 完整正文与 SHA256：见 `preparation-audit.json` 本例 `saved_draft`；30字，`28ef08a3a19dedc412b26bdcb3db58db626110d8cc45a41f5de2fa752c29783f`。
- V4实际请求：`evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/01-g02-three-sentences.json`；request hash `f42b6d4dd045efa3bed69cf0c2d305d11ef22eda3f7433f22818bf605ace9c31`。
- 当前静态预期：可用3 claims，选择3，未选0；预计excerpt 30字；selected claims均未截断；正文缩减 `false`。
- V4首摘要缺口：摘要仅引 D1–D3，但额外陈述罗盘持有者、航图地点、电台时间、退潮时间。

| 当前预期 claim | 原文 | 字符范围 |
|---|---|---|
| D1 | 林默走进北门。 | [0,7) |
| D2 | 银钥匙已经交给陈澈。 | [7,17) |
| D3 | 她此时已经知道弟弟还活着。 | [17,30) |

V4选中 SourceSpan 历史原文如下；V5是否同样选中须核对新capture，不强制复制旧ID或旧顺序。

| 章节/标签 | 历史实际选中原文 |
|---|---|
| 第4章 / 知识边界 | 温岚看得懂潮表上的坐标，却还不知道‘廊桥钥匙’这个代号指向什么。 |
| 第8章 / 关系变化 | 温岚把北堤值守簿交给苏岑，两人约定不再各自隐瞒新线索。 |
| 第6章 / 事件记录 | 电台在二十一点零五分收到三次短促求救码，信号来自雾线水门以外。 |
| 第10章 / 未解问题 | 北潮闸并未关闭，雾钟却响了一次；温岚仍握着罗盘，港外传来白色渡船的汽笛。 |

本例必审：
- 三个当前草稿事实均保留；每个 item 的相应事实与该 item 自身 D1/D2/D3 引用对应。
- 摘要陈述的每个事实由自己的 summary_sources 支持；三句均可容纳，需核查没有为背景挤掉当前草稿。
- 原文代词“她”未建立新身份链接；不得擅自绑定到林默、温岚或其他人物。

| 阶段 | 逐item自身引用 | summary自身引用 | 完整性/时间/归属 | 结论 |
|---|---|---|---|---|
| 原首响应/首个可解析JSON | 待真实结果逐条展开 | 待逐分句核对 | 待审 | pending_manual_review |
| 每次产品修复答 | 待实际发生；逐答单列 | 待审或未发生 | 待审或未发生 | pending_manual_review |
| 最终持久化产品 | 待逐条展开并核对重建 | 待独立核对 | selected覆盖、范围与计数另列 | pending_manual_review |

当前实际 snapshot hash、来源选择差异、每条证据指针、保留P3及人工结论：填写于新真实审阅文件；本准备版不预先写“通过”。


### 02 — g02-long-sentence

- 完整正文与 SHA256：见 `preparation-audit.json` 本例 `saved_draft`；299字，`c37ec0f518fbf7e7c499cb4dc0e23db72f8edeb458dc8939618e7ce8bbecadee`。
- V4实际请求：`evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/02-g02-long-sentence.json`；request hash `54ef9a5ca41bd8751d86adc4a356a9ed303e9c8038f6ca47e621134dbb0e8fd4`。
- 当前静态预期：可用1 claims，选择1，未选0；预计excerpt 299字；selected claims均未截断；正文缩减 `false`。
- V4首摘要缺口：摘要引完整 D1、罗盘 holder、does_not_know，却额外陈述异常雾钟与白船未解线索。

| 当前预期 claim | 原文 | 字符范围 |
|---|---|---|
| D1 | “林默沿着长廊向前走，”×28 + “最后把银钥匙交给陈澈并得知弟弟还活着。”（完整299字在JSON内） | [0,299) |

V4选中 SourceSpan 历史原文如下；V5是否同样选中须核对新capture，不强制复制旧ID或旧顺序。

| 章节/标签 | 历史实际选中原文 |
|---|---|
| 第8章 / 关系变化 | 温岚把北堤值守簿交给苏岑，两人约定不再各自隐瞒新线索。 |
| 第6章 / 事件记录 | 电台在二十一点零五分收到三次短促求救码，信号来自雾线水门以外。 |
| 第4章 / 知识边界 | 温岚看得懂潮表上的坐标，却还不知道‘廊桥钥匙’这个代号指向什么。 |
| 第3章 / 时间线 | 十九点二十，西航道先退潮，最后一班渡船在十九点四十才离开风栈码头。 |

本例必审：
- 299 字完整 claim 含尾部“最后把银钥匙交给陈澈并得知弟弟还活着。”；item 与 summary 若说句尾，自己的引用必须包含句尾。
- “看得懂潮表上的坐标”必须自行引用实际选中的第4章 SourceSpan；does_not_know Memory 只能支持不知道代号，不能单独撑完整 A+B 两分句。
- 保留原文“并得知”的主体语法，不依据孤立词面补造身份；长句摘要凝练性另判，安全不等于精炼。

| 阶段 | 逐item自身引用 | summary自身引用 | 完整性/时间/归属 | 结论 |
|---|---|---|---|---|
| 原首响应/首个可解析JSON | 待真实结果逐条展开 | 待逐分句核对 | 待审 | pending_manual_review |
| 每次产品修复答 | 待实际发生；逐答单列 | 待审或未发生 | 待审或未发生 | pending_manual_review |
| 最终持久化产品 | 待逐条展开并核对重建 | 待独立核对 | selected覆盖、范围与计数另列 | pending_manual_review |

当前实际 snapshot hash、来源选择差异、每条证据指针、保留P3及人工结论：填写于新真实审阅文件；本准备版不预先写“通过”。


### 03 — g02-body-limit

- 完整正文与 SHA256：见 `preparation-audit.json` 本例 `saved_draft`；1980字，`2005fb472e4d473c2fd327b19ab6d3b5df281af7fb806ce2216b2498f2a23269`。
- V4实际请求：`evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/03-g02-body-limit.json`；request hash `5fad8535f2ba3993c9bd5ad4206e36a19d5f38da236153a886d9eb051c24196a`。
- 当前静态预期：可用180 claims，选择8，未选172；预计excerpt 600字；selected claims均未截断；正文缩减 `true`。
- V4首摘要缺口：摘要引 D1、退潮、罗盘，却额外陈述航图地点与电台求救码。

| 当前预期 claim | 原文 | 字符范围 |
|---|---|---|
| D1 | 林默在雾港核对潮汐表。 | [0,11) |
| D2 | 林默在雾港核对潮汐表。 | [11,22) |
| D3 | 林默在雾港核对潮汐表。 | [22,33) |
| D4 | 林默在雾港核对潮汐表。 | [33,44) |
| D5 | 林默在雾港核对潮汐表。 | [44,55) |
| D6 | 林默在雾港核对潮汐表。 | [55,66) |
| D7 | 林默在雾港核对潮汐表。 | [66,77) |
| D8 | 林默在雾港核对潮汐表。 | [77,88) |

V4选中 SourceSpan 历史原文如下；V5是否同样选中须核对新capture，不强制复制旧ID或旧顺序。

| 章节/标签 | 历史实际选中原文 |
|---|---|
| 第7章 / 地点状态 | 航图被固定在雾线水门外的锚柱上，右下角缺失了一块。 |
| 第6章 / 事件记录 | 电台在二十一点零五分收到三次短促求救码，信号来自雾线水门以外。 |
| 第10章 / 未解问题 | 北潮闸并未关闭，雾钟却响了一次；温岚仍握着罗盘，港外传来白色渡船的汽笛。 |
| 第9章 / 动态状态 | 进入仓道前，苏岑把带月牙裂纹的黄铜罗盘交到温岚手里保管。 |

本例必审：
- 180 个同文位置中当前选择预计为 D1–D8，其 ordinal 与 offsets 分别保留；不得按文本去重后冒称180句全部被审。
- 当前产品应为全部8个 selected claims 保留可寻址最终引用；172条未选、正文 excerpt 缩减分别披露。
- summary 受3来源/400字上限，不要求包含8个来源；只要出现某事实就须有自身引用，摘要范围不能声称全180位置完成。

| 阶段 | 逐item自身引用 | summary自身引用 | 完整性/时间/归属 | 结论 |
|---|---|---|---|---|
| 原首响应/首个可解析JSON | 待真实结果逐条展开 | 待逐分句核对 | 待审 | pending_manual_review |
| 每次产品修复答 | 待实际发生；逐答单列 | 待审或未发生 | 待审或未发生 | pending_manual_review |
| 最终持久化产品 | 待逐条展开并核对重建 | 待独立核对 | selected覆盖、范围与计数另列 | pending_manual_review |

当前实际 snapshot hash、来源选择差异、每条证据指针、保留P3及人工结论：填写于新真实审阅文件；本准备版不预先写“通过”。


### 04 — g02-identical-text

- 完整正文与 SHA256：见 `preparation-audit.json` 本例 `saved_draft`；14字，`3e296b4f2262e0655b7a88d79bc09fdb99b25b1720d6c3533ebf1df0a3125223`。
- V4实际请求：`evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/04-g02-identical-text.json`；request hash `29f3e2cfa9675c2fe2c56419c8c84196414a1f36bed8f281be02b4a12f5492a0`。
- 当前静态预期：可用2 claims，选择2，未选0；预计excerpt 14字；selected claims均未截断；正文缩减 `false`。
- V4首摘要缺口：摘要引 D1、钟声规则、异常钟声，却额外陈述白船未靠岸与来源不明。

| 当前预期 claim | 原文 | 字符范围 |
|---|---|---|
| D1 | 林默走进北门。 | [0,7) |
| D2 | 林默走进北门。 | [7,14) |

V4选中 SourceSpan 历史原文如下；V5是否同样选中须核对新capture，不强制复制旧ID或旧顺序。

| 章节/标签 | 历史实际选中原文 |
|---|---|
| 第6章 / 事件记录 | 电台在二十一点零五分收到三次短促求救码，信号来自雾线水门以外。 |
| 第10章 / 未解问题 | 北潮闸并未关闭，雾钟却响了一次；温岚仍握着罗盘，港外传来白色渡船的汽笛。 |
| 第9章 / 动态状态 | 进入仓道前，苏岑把带月牙裂纹的黄铜罗盘交到温岚手里保管。 |
| 第8章 / 关系变化 | 温岚把北堤值守簿交给苏岑，两人约定不再各自隐瞒新线索。 |

本例必审：
- 两个同文 claim 为两个来源位置，D1 [0,7)、D2 [7,14)，不可凭同文换用错误 revision/project 来源。
- 内容等价不等于两次独立新事件；分别记录覆盖、重复与倒序，不以全局来源并集证明单 item 支持。
- 若输出月牙裂纹等背景，核对该条自己的已选第9章 SourceSpan，不能借另一条引文。

| 阶段 | 逐item自身引用 | summary自身引用 | 完整性/时间/归属 | 结论 |
|---|---|---|---|---|
| 原首响应/首个可解析JSON | 待真实结果逐条展开 | 待逐分句核对 | 待审 | pending_manual_review |
| 每次产品修复答 | 待实际发生；逐答单列 | 待审或未发生 | 待审或未发生 | pending_manual_review |
| 最终持久化产品 | 待逐条展开并核对重建 | 待独立核对 | selected覆盖、范围与计数另列 | pending_manual_review |

当前实际 snapshot hash、来源选择差异、每条证据指针、保留P3及人工结论：填写于新真实审阅文件；本准备版不预先写“通过”。


### 05 — g02-time-bound

- 完整正文与 SHA256：见 `preparation-audit.json` 本例 `saved_draft`；40字，`c4127523dcbbd745a7742fc3448bfb655c5a28854a362b097c244ebb683b50d3`。
- V4实际请求：`evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/05-g02-time-bound.json`；request hash `5ea3e8bfebd9ce47f883fddc3b42825a3ccf7aa4eb1fcafca692ba3aafa1da78`。
- 当前静态预期：可用2 claims，选择2，未选0；预计excerpt 40字；selected claims均未截断；正文缩减 `false`。
- V4首摘要缺口：摘要对昨日/今日正确并引 D1+D2，但罗盘、白船、异常钟声缺自身来源。

| 当前预期 claim | 原文 | 字符范围 |
|---|---|---|
| D1 | 昨日温岚尚未得知银钥匙的用途。 | [0,15) |
| D2 | 今日她读完陈澈的信，才知道银钥匙能打开潮汐档案柜。 | [15,40) |

V4选中 SourceSpan 历史原文如下；V5是否同样选中须核对新capture，不强制复制旧ID或旧顺序。

| 章节/标签 | 历史实际选中原文 |
|---|---|
| 第4章 / 知识边界 | 温岚看得懂潮表上的坐标，却还不知道‘廊桥钥匙’这个代号指向什么。 |
| 第10章 / 未解问题 | 北潮闸并未关闭，雾钟却响了一次；温岚仍握着罗盘，港外传来白色渡船的汽笛。 |
| 第9章 / 动态状态 | 进入仓道前，苏岑把带月牙裂纹的黄铜罗盘交到温岚手里保管。 |
| 第8章 / 关系变化 | 温岚把北堤值守簿交给苏岑，两人约定不再各自隐瞒新线索。 |

本例必审：
- D1 昨日未知与 D2 今日读信才知共同保留，当前最终 items 与 summary 各自引用完整两条。
- 不可把昨日未知和今日获知归并为无时间的恒定未知/已知；读信的获得知识条件与钥匙用途保持。
- 银钥匙与背景廊桥钥匙没有同一物品证明；不得以背景 does_not_know 否定今日银钥匙的新知识。

| 阶段 | 逐item自身引用 | summary自身引用 | 完整性/时间/归属 | 结论 |
|---|---|---|---|---|
| 原首响应/首个可解析JSON | 待真实结果逐条展开 | 待逐分句核对 | 待审 | pending_manual_review |
| 每次产品修复答 | 待实际发生；逐答单列 | 待审或未发生 | 待审或未发生 | pending_manual_review |
| 最终持久化产品 | 待逐条展开并核对重建 | 待独立核对 | selected覆盖、范围与计数另列 | pending_manual_review |

当前实际 snapshot hash、来源选择差异、每条证据指针、保留P3及人工结论：填写于新真实审阅文件；本准备版不预先写“通过”。


### 06 — g02-dialogue-attribution

- 完整正文与 SHA256：见 `preparation-audit.json` 本例 `saved_draft`；45字，`efbd2767a8328cd339f26b4983e8ac5bfa56e02842dd14b5e1e1c18db629ed17`。
- V4实际请求：`evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/06-g02-dialogue-attribution.json`；request hash `611a65de1f5d3b7f1740a49d6e500af1a9911adb1f67f46717fa299697a6e9ee`。
- 当前静态预期：可用2 claims，选择2，未选0；预计excerpt 45字；selected claims均未截断；正文缩减 `false`。
- V4首摘要缺口：摘要对两方说法保留归属并引旧 D1+D2、罗盘，但白船和异常雾钟缺自身来源。

| 当前预期 claim | 原文 | 字符范围 |
|---|---|---|
| D1 | 陈澈说：‘温岚已经把潮汐表交给林默。’ | [0,19) |
| D2 | 温岚摇头说：‘我没有交出潮汐表，它仍在我的背包里。’ | [19,45) |

V4选中 SourceSpan 历史原文如下；V5是否同样选中须核对新capture，不强制复制旧ID或旧顺序。

| 章节/标签 | 历史实际选中原文 |
|---|---|
| 第8章 / 关系变化 | 温岚把北堤值守簿交给苏岑，两人约定不再各自隐瞒新线索。 |
| 第10章 / 未解问题 | 北潮闸并未关闭，雾钟却响了一次；温岚仍握着罗盘，港外传来白色渡船的汽笛。 |
| 第9章 / 动态状态 | 进入仓道前，苏岑把带月牙裂纹的黄铜罗盘交到温岚手里保管。 |
| 第6章 / 事件记录 | 电台在二十一点零五分收到三次短促求救码，信号来自雾线水门以外。 |

本例必审：
- 必须捕获2条完整、含说话人及闭引号的 claims，范围 [0,19)、[19,45)，不应存在只含闭引号的第三条。
- 陈澈称已交给林默；温岚否认并自称仍在背包。两方陈述均为引语，不裁定谁说真话、不升级为叙述者确认交接或真实持有状态。
- 否认“没有交出”、说话人和引语框架不得丢失；两条完整当前草稿应保留在最终 items 和其自身引文、summary 及其自身引文。

| 阶段 | 逐item自身引用 | summary自身引用 | 完整性/时间/归属 | 结论 |
|---|---|---|---|---|
| 原首响应/首个可解析JSON | 待真实结果逐条展开 | 待逐分句核对 | 待审 | pending_manual_review |
| 每次产品修复答 | 待实际发生；逐答单列 | 待审或未发生 | 待审或未发生 | pending_manual_review |
| 最终持久化产品 | 待逐条展开并核对重建 | 待独立核对 | selected覆盖、范围与计数另列 | pending_manual_review |

当前实际 snapshot hash、来源选择差异、每条证据指针、保留P3及人工结论：填写于新真实审阅文件；本准备版不预先写“通过”。


## 当前审阅材料索引

- `preparation-audit.json`：创建时源码与历史材料SHA256、六份历史输入与当前静态预期、空白人工审阅字段。
- 原始真实证据：`evaluation/current_flash_v4/runs/flash-v4-g02-20260926-01/cases/`。
- 历史语义审阅：`docs/g02-citation-repair-evidence/independent-round1-semantics/semantic-review.md`。
- 后续离线边界：`docs/g02-citation-repair-evidence/independent-round2-semantics/review.md` 和 `evaluation/g02_post_v4_offline/results-v2.json`。
- 已接受边界：`docs/g02-citation-repair-independent-acceptance.md`。其中提交前状态为历史说明，不替代当前7d811cc基线。
