# 比较集 V2：第三轮独立 gold 与材料复验

2026-09-26。**三类标签的故事语义已可接受，旧时间缺口、五条不足最小证据及两个转变允许结果已修正；整套严格评分 gold 仍有一处最小来源错误和不足类别沿用问题，暂不能宣布全部验收通过。** 本报告只验材料，不替其他审阅者验评分器、capture 或真实模型效果。

## 身份与范围

工作树：`story-continuity-legacy-gap-repair`。V2 manifest SHA-256：`35b8a9559b9d5138f21795cdeb74439d010490dd5a9ee07a37cd48dbd44ca337`，与主控指定一致。cases SHA-256：`a312282eef0ea34b91a55256b238a01e287705836c6c3387d5b68f34a6ba41c0`；build：`48d6072e26062431c91c2f9c703fa501a67cd16b2642cc395f3509f837cc4c9b`。

阅读 HANDOFF/RUBRIC、build、完整24 cases、四个 corpus 与 Memory、V1→V2 lineage，并与本人 round2 报告逐项比对。独立 `material-audit.py` 只使用标准库读取命名文件，检查来源正文 hash、Memory 与来源一致、标签结构及措辞计数；**没有调用产品 validator、API、Provider，也没有创建或读取数据库**。手工判断与脚本计数分开，脚本通过不是 gold 正确的理由。

结果在 `material-audit-results.json`：24例，8/8/8，8组三联、4作品；全部材料 hash 与 manifest 一致；每个声明来源 hash 和全部 Memory.value/source 对应无误；读取前后无变更。`lineage-audit.json` 验证24旧ID与24新ID一一对应，draft_changed 全部如实（13个草稿未变）。V1 manifest仍为 `d0da4eb5037c5ce8e724d0263255654d97fb25cc975e5e419786ea5a60c8d29c`。最终收尾 hashes 见 `final-receipt.json`。

## 必须处理的材料项

### 1. world_rule 的最小证据仍多要求一条，且理由与新草稿矛盾

定位：`cases.json:8–55`，`build.py:23`。案例 `ccv2-north_glass-world_rule-conflict`。

新草稿明确说 Mira **while wearing only her red badge** 开门；`badge_rule` 明确门只能由戴蓝徽章者打开，红徽章无法开门。因此 **draft + badge_rule 已形成完整矛盾**，不再需要 badge_roster 才能知道 Mira 的徽章颜色。

当前 `minimum_sufficient_evidence_sets` 只允许 `[badge_rule, badge_roster]`，`label_reason` 仍说没有单一来源能同时确定规则与徽章。这个理由忽略了草稿本身已提供徽章事实。只移除 roster 引文、保留草稿和 rule，矛盾仍然完整；这是具体、可手工复现的充分替代集合。

预期：将 `[badge_rule]` 设为最小充分集合、roster 作为可选佐证，或删除草稿自带的徽章信息并保留明确同日时间。无需同时改两种方案。标签 confirmed_conflict/world_rule 本身正确，但**当前来源 gold 会拒绝合理单条反证**，在严格评分前需要修订并保留冻结历史。其余四个两来源冲突的联合必要性仍成立。

### 2. 不足案例的 decision_category 不能从同组三联轴自动继承

V2 对每个案例都生成 `decision_category=category`（build 的 cases 构造段），但不足分支经常询问不同性质的缺口。两个确定例：

- `ccv2-harbor_signal-timeline-insufficient_evidence`，`cases.json:414–420`：草稿是 **Sera authorized a reopening**。缺少的是某个命名人物的授权依据，当前产品定义将命名人物的 authority/responsibility 归为 relationship；不是 opening/closing 先后的 timeline。
- `ccv2-orchard_restoration-relationship-insufficient_evidence`，`cases.json:714–720`：草稿断言 **Nera was born before Oren**。缺口是两次出生事件先后，属于 timeline；twins 的亲属关系只是背景。

此外 courier 身份不足并不是“人物知道什么”，不能仅因同组冲突测 knowledge，就预定 character_knowledge 为唯一正确类别。其余不足也应按实际决定核心人工指定允许类别，不能因轴名直接推导。

**三类标签 insufficient_evidence 不受此问题影响。** 本分工没有运行评分器；已向主控/评分审阅交叉提示：若 final/raw score 强制该字段，则这些正确类别会误失分，应修 gold；若暂不强制，应明示字段仅是分组轴而非类别答案。当前 RUBRIC 将类别列为评分条件，因此在全套 gold 验收前必须消除这个歧义。

## 已修正和可接受的范围

- **三个规则＋动态前提**：Mira 的动作及徽章、carrier ready 及未锁帽、boat completed 及 unsigned/未离港都已写明同日10点；后两者来源明确 throughout that minute。静态规则确实存在且稳定，不是给动态状态换 predicate。原先“后来锁帽/后来离港也可能兼容”的时间缺口已消除。
- **两个合理转变**：knowledge 控制明确 11点不知、13点后来学会；location 控制明确19点西→东移动。两例 `allowed_outcomes` 都允许 no_issue/state_change，后者有实际转变证据，不因底层 status 名为 conflict 就认为确定矛盾。移动例 minimum=later_watch、watch_log 可选背景合理。
- **五条不足**：spare_register、cap_actor、later_recipient、delay_cause、grinder_blank 各自是唯一最小缺口来源；原第二条降为 recommended_context。另三条不足本来就是单条最小。不会再因缺少冗余背景而否定充分的“不足”解释。
- **措辞捷径**：V1 的 establish=8不足/0其他，现为4不足/1无冲突/0冲突，timeline正控制也使用“records establish”。原来的单词完全分隔已打断。仍以“记录据称证明某事但字段未知”为主要不足模板，属于小型已暴露开发集的覆盖限制，不据此声称泛化或盲测能力，也不因模板集中继续扩张本轮要求。
- **来源诚实性**：V2 明确从V1逐例修订，保留V8 pattern adaptation和seen-development说明；13条未改正文也在 lineage 中明确记录。没有将V2包装成独立未见集或与V1同输入比较。

## 逐24例人工裁定

以下每行覆盖一个 axis 的 C/N/I 三个 case_id 后缀，总计24例。C=conflict，N=no_conflict，I=insufficient_evidence。表中的“成立”是本文限定的故事语义判断，不是对模型回答的评价。

| corpus / axis | C：确定冲突 | N：兼容控制 | I：记录背书不足 |
|---|---|---|---|
| north_glass / world_rule | 同日10点红徽章开蓝徽章门，成立；但 rule 单条已足够，最小来源需修 | 红徽章不能开门，与机制相符 | 11点持有人空白，不能由名单背书 Mira；最小 spare_register，roster 可选；不足成立 |
| north_glass / object_state | 同一分钟帽未锁却 ready，规则条件直接相冲，成立 | 四bar但帽未锁，所以未ready，成立 | 操作人未记，不能将松帽归给 Mira；cap_actor 单条足够，不足成立 |
| harbor_signal / timeline | 首开先于首关，草稿反转，且双端明确同日09点，成立 | 记录背书09点开/10点关，正好与来源一致，成立 | 11点重新开启/操作人未记，亦无 Sera 授权依据，不足成立；decision_category需修为授权核心 |
| harbor_signal / character_knowledge | 双端同日11点不知/知，直接矛盾，成立 | 13点学习可与11点不知共存，成立；两允许结果合理 | courier 未指名，记录无法背书 Vela；最小 later_recipient，旧不知记录可选；不足成立，类别需独立判 |
| orchard_restoration / relationship | 永久kinship规则加twins身份，不能互为母子/母女，成立 | 明确 lied 的话语不当作叙述者事实，兼容成立 | 出生先后未记，不足成立；其决定核心为timeline，不是亲属关系 |
| orchard_restoration / event_status | 同一分钟未签单且未离港却已完成，违反明确完成条件，成立 | 同一条件下尚未完成，兼容成立 | 原因未记，不能归责Tala；最小delay_cause，launch状态可选，不足成立 |
| basalt_observatory / attribute | 双端同日18点，经R4=west lens桥接，amber/clear矛盾成立 | 当前clear与回忆yesterday looked amber不冲突，兼容成立 | grinder身份空白，维护表直接写R4，最小grinder_blank、index可选，不足成立 |
| basalt_observatory / location_action | 同日18点直接west/not east与east相冲，成立 | 19点明确移动，与此前西侧兼容；no_issue/state_change均合理 | 同伴未命名，不能据watch断言Sora，不足成立 |

不足接受范围仍是“记录没有证明所说身份、原因或关系”，不是断言事情没有发生或人物一定没参与。语义说明必须保留这个边界；把 according to the records 当作普通无来源的新情节，会改变这组测试在测什么。

## 非阻断说明与交付边界

`time_scope` 当前按 axis 复用于三条案例，如11点持有人不足却写“claimed opening at10点”；metadata更像轴的上下文，不是每条草稿时间。建议标为axis context或写成case-specific，以免人工复核借错时间；本文判断以实际 draft/source 为准，因此不把该文字错误再算一条标签失败。

没有运行任何原生成/覆写入口，没有改业务代码、V1/V2冻结或他人证据。材料 hash/Memory 一致性不等于实际请求完整或评分正确；这些由其他独立审阅合并。当前可接受的是24例三分类叙事语义、8个冲突核心类别及上述修复范围；**最小来源 gold 和不足 issue 类别修订前，不建议宣布24例严格 gold 全部通过**。无需真实模型调用来处理这两个材料项。
