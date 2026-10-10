# G02 引用修补与比较集准备：最终独立验收

> **历史记录**：本文记录的是 2026-09-26 的 G02 修补 时的设计或过程，文中的部分说法和功能已经变化，例如 Story Memory 现在叫事实库，作者资料和修订计划已经删除。现行说明见[当前产品](current-product.md)。

日期：2026-09-26。状态：**本轮限定范围独立验收通过，等待用户接受。** 通过的是 G02 产品修补和已见比较集的准备工作，不是模型整体质量、发布 Gate 或 Agent 阶段通过。

工作树：story-continuity-legacy-gap-repair；分支 codex/legacy-gap-repair；基线 c3bd54ab019447354e8b1387e16b9aca3258b4c9。修补仍为未提交改动；没有 commit、push、merge 或部署。原仓库、撤销的 Agent 工作树与历史冻结文件保留。

## 1. G02 产品修补通过范围

简报现在从完整绑定来源或受控 Memory/作者计划记录重建正文和摘要，并让每一项与摘要分别拥有自身引用。词面匹配只用于寻找候选来源，不能证明任意改写正确。以下已独立核查：

- 长句尾部事实、Memory 只支持半句和原摘要漏引，不再靠“引用ID全集齐全”冒称逐项支持。
- 昨日未知、今日读信后获知两条草稿事实都进入最终条目、摘要与自己的引用。
- 本轮中文连续/嵌套引语保留说话人和闭引号，没有孤立标点造成假 partial。
- 多来源展开遇到12项上限时优先保留选中草稿事实，背景省略明确计数；未匹配分句不再双计。
- 知识否定和未来计划层级保留，没有把“不知道”变成“知道”，也没有把计划升级为已发生。

第二轮主控46 tests＋12 subtests、6条正式前端配新隔离后端的真实浏览器交互通过，包括引用展开与保存后刷新。当前产品hash仍与当轮一致，比较集后续修订没有改产品，不重复计作新UI测试。证据见[产品独立验收](g02-citation-repair-evidence/independent-round2-root/ACCEPTANCE.md)、[浏览器复验](g02-citation-repair-evidence/independent-round2-browser/review.md)。

当前产品SHA-256：

| 文件 | SHA-256 |
|---|---|
| backend/app/brief_citations.py | a0a3a31251860265c29b09a95e85b27f05d92dc1a0e6bcc0a9d1736a57b28ccc |
| backend/app/engine.py | 4d3a07e955aadfaf1ecd31281ccca0d4fb3f36014756b801d906b193e15984c7 |
| backend/app/v2_database.py | 2485b997c32dda446325fe1535df0342330b09afdd53b9619137ad824a17e754 |

## 2. 比较集准备通过范围

采用 [current_contract_compare_v3](../evaluation/current_contract_compare_v3/HANDOFF.md) 作为本轮接受的准备版本：4个合成作品、8组三联、24例（确定冲突/兼容/证据不足各8）。它只修订V2的gold元数据和评分，逐字复用V2故事与捕获输入，明确为已暴露开发材料，并非未见集。

V3 manifest SHA-256：`0afd9630d22aecc44d1fbc8a955787d12d1286b31ec85a3e0985dff132da8baf`。

- 三个“固定规则＋可变前提”的冲突补齐共同时间，避免把后来合法变化误判确定冲突。
- 红徽章开门案例接受规则单条最小引用，名单仅为可选佐证。
- 不足问项按实际核心判断类别，授权与出生先后不再机械继承相邻冲突的类别。
- 合理后知/移动允许充分支持的 state_change；每条引用的来源绑定、关系和最小集合均参与检查。
- 原始首答、修复答（如存在）、最终产品分层。五类原始合同漏洞已关闭；严格首答失败不会因产品安全降级而变成首答正确。
- 机器结构通过仍为 pending_manual_review。同伴案例的 location_action/relationship 两个预声明候选保留 pending_manual_adjudication，逐答人工复核后才能报告类别正确。
- 两个新运行入口都在读取材料前拒绝既有运行身份；文件只创建、不覆盖，首失败单独保留。

主控重新运行V1/V2/V3冻结校验、V3四项测试；独立45项有界评分控制全部符合预期。另独立验证两个入口的重复身份拒绝、首次失败留存及原文件不可覆写。前轮24条capture、26份保存答复链及6个新合成API控制通过；V3没有新增API，未把复评分伪称新运行。

依据：[gold审阅](g02-citation-repair-evidence/independent-round4-gold/review.md)、[评分复验](g02-citation-repair-evidence/independent-round4-score/review.md)、[主控校验与防覆盖](g02-citation-repair-evidence/independent-round4-root/verification.json)、[重评分血缘](g02-citation-repair-evidence/independent-round4-lineage/review.md)。

V3冻结文件中的独立接受字段记录的是冻结当时的未审状态，保持原样；本文件与[接受记录](g02-citation-repair-evidence/independent-round4-root/acceptance.json)提供后续独立接受结论，不追改冻结历史。

## 3. 模型首答、产品结果与用量分别报告

G02 V4曾真实运行6个输入：新增6次生成POST、1次models预检，20238输入/6444输出tokens。六条真实首摘要均存在自身引用缺口，不能说模型首答已经修好。后续产品修补通过原首答离线复放及新合成输入/浏览器验证；没有再次调用真实模型来证明新版首答质量。

比较集V3对V2的26份旧合成结果只做离线重评分：raw/final均19份结构通过、7份因旧不足类别与修订gold不符而保留失败。这个19/26不是模型分数，也不是新API结果。单独的人为正负控制不能合并到真实案例分母。

| 实测范围 | 生成POST | models请求 | 输入tokens | 输出tokens |
|---|---:|---:|---:|---:|
| 先前Flash V1/V2 | 57 | 2 | 165144 | 14242 |
| G02 Flash V4 | 6 | 1 | 20238 | 6444 |
| 比较集及后续独立修订 | 0 | 0 | 0 | 0 |
| 累计真实调用 | 63 | 3 | 185382 | 20686 |

总tokens 206068；现有真实记录usage完整，实际费用不可得，未估算。合成stub的占位usage不进入此总账。此前G01等真实结论及旧V8质量失败继续以[上一轮实测验收](flash-real-provider-independent-acceptance.md)为准，不被本轮评分准备覆盖。

## 4. 明确保留的限制

1. G02仍有同文重复/倒序、长句摘要冗长、对象误归角色状态三个P3；保守来源呈现不等于精炼摘要。
2. 引语处理仅覆盖本轮中文前置说话人、弯/角引号及对应嵌套控制，不保证ASCII引号、后置说话者或任意小说句法。
3. 比较集小而已见，不能支持盲测泛化结论。同伴类别需逐答人工裁定；未解决类别争议不能计入正式类别准确率。
4. V3徽章案例的展示字段 case_time_scope.minimum_source_texts 仍附可选名单原文；正式minimum/expected_evidence/optional及评分均正确。作为非阻断说明残留保留，不改当前冻结。
5. V2早期“24完成、8结构通过”的逐例原始失败链未在有界检索中找到，目前仅能核实失败概要。没有补造历史；新入口防覆盖已经验证。见[历史缺口说明](../evaluation/current_contract_compare_v3/HISTORY_GAP.md)。V3自身首个混杂负控与隔离修正后的第二结果均保留。
6. 旧12案例原始包仍未定位。G07生产成功链路、G08完整应用恢复、新版产品真实效果和独立未见材料仍未完成。

主控保护检查确认134份旧Flash材料、10份V4原始结果、比较集V1/V2各21文件未变；V4运行时20份产品源码快照继续保留。所有旧分数、首失败和迭代报告保持历史身份。

## 5. 交付后边界

本轮交付为：G02引用防护、可复核的已见比较集准备版本、评分与失败留存机制、更新的[长期维护入口](evaluation-maintenance.md)。本次不自动运行整套真实比较集，不开展Agent或真实作者研究，不发布或提交Git。

先由用户接受本轮结果；未来执行真实比较时仍须冻结具体矩阵、运行身份、参数和有界重试，保留每次首答/修复/最终与真实HTTP账。此前无费用上限授权不撤销，也不据此无限重试。后续维护按新缺陷、能力变更和里程碑触发，保护不可变结果，不因失败而改写旧标签或输出。

