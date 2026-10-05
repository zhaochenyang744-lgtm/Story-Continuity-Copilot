# 当前契约比较集：交接前独立快照审查

2026-09-26。**状态：候选构建中，尚未交接；本文件是固定观察快照，不是最终版本验收，也不是模型成绩。** 按主控要求停止追随滚动修改，交接后再核对最终身份。仅新增本目录证据；没有改实施文件、旧冻结资产或业务代码，没有执行原 preflight，没有访问任何数据库、密钥或 Provider。

## 快照和执行身份

工作树 HEAD：`c3bd54ab019447354e8b1387e16b9aca3258b4c9`。探针捕获时间：`2026-09-26T11:21:59.501260+00:00`。完整 9 个候选文件和 4 个依赖文件 SHA-256 见 `material-probe-results.json`；探针前后这些文件均未变化。开始阅读与探针之间确有实施修改，因此以下发现绑定这个快照，不能直接归于后来交付文件。

| 文件 | 观察 SHA-256 |
|---|---|
| build.py | `99003507b3bffe146498bb8fa99f1eebe1f501c5aedf1ce03c8c9d80b0571adc` |
| cases.json | `33ca67a0766ef645df831e9affdfb599fd0cd6fbc5c0158c42e52be8c1dfc21a` |
| actual-inputs.json | `5d4b490833c0f75f245382337ad11f897a7560381dbbe44998ee316d6b2bf60d` |
| score.py | `c29b392dda16ca0d12104a414c328088917f5579b43e93b05f0c5c88c1741f34` |
| backend/app/engine.py | `4a10ead69c99f9c490c8f4f090157825e84385f4b4ee5df3610047fc431dd30a` |

执行：`.venv/Scripts/python.exe docs/g02-citation-repair-evidence/independent-round1-comparison/material-probe.py`。脚本输出采用 create-only，重复运行请另存到新审阅目录，不覆盖本结果。脚本只读取指定 JSON/源码，调用内存中的 engine.validate 和评分函数；socket connect、sqlite connect 均拦截，Provider/HTTP/数据库连接皆 0。第一次探针因把 socket 类替成函数导致 ssl 导入失败，未产生结果；仅修正本目录脚本的禁网方式后执行成功，没有修改被审查实现。

## 应在交接前解决的实质问题

### P1：若干不足标签惩罚了兼容的新情节，timeline 类别也不准确

`build.py:31–34` 的 `ccv1-harbor_signal-timeline-insufficient_evidence`：历史 09点门关闭，10点记录空白，草稿明确“10点门打开”。`build.py:58–62` 的 `ccv1-basalt_observatory-location_action-insufficient_evidence`：历史 18点人在西侧，19点去向未记，草稿明确“19点移向东侧”。两者都是草稿直接补入兼容的后来行动。`provider.py:100,104–107` 明确允许兼容的新信息，且草稿本身就是转变证据，不应要求另一来源再次证明。实际 gold 却强制 insufficient_evidence，理由只是记录没写；这会把符合产品契约的省略 Issue/state_change 算错。

剩余不足例同样需要人工解释真正缺失的必要连接，不能只写泛化的“相关记录空白”。目前 8 个不足例均只有一条 expected_evidence，且用同一理由生成，不满足前置建议中至少 4 个多证据不足边界。不是所有新增叙事事实都必须在历史记录预先出现。

同一 timeline-conflict 是 09点门开与门关闭，核心为同刻物体状态；`provider.py:116` 规定 timeline 是事件排序、object_state 是特定时刻物体状态。用这个样本声称覆盖 timeline，会使正确的 object_state 分类失分。建议重写真正排序情景并独立复核，不按模型结果临时改 gold。

### P1：4 个动态冲突仍不可由当前时间守卫表达

在捕获的实际请求上构造最小合法 confirmed_conflict，引用所有人工必要来源，分别给 claim/evidence 原文中的 `09点`、`11点` 或 `18点` 锚：timeline、character_knowledge、attribute、location_action 四例均被 `ContinuityEngine.validate` 拒绝为 `temporal_overlap_unproven`。另四个静态规则例被接受。

原因可定位 `engine.py:127–156,377–383`：仅时钟相同不足以证明同日，时钟锚场景还要求两端都有日期或明确 same day。当前草稿没有同日限定，attribute 来源和草稿也都只有时钟。只能在故事本身真实定义同日/日期后绑定正确锚；不能为评分拼接缺乏语义依据的短语。静态 validator 接受只证明格式可表达，不证明任意混合动态事实具有同一时间范围。

初次阅读发现的 relationship 没 rule、attribute 完全没时钟已经在此快照前被改写，不把旧观察当成此版本仍存在的同一缺陷。

### P1：评分器把首答/engine 字段当作最终 API 字段，正确结果会失分

`score.py:26,35` 检查 Issue.status 是否为 insufficient_evidence/conflict，CLI 声称输入 full product response。然而 `v2_database.py:3495` 的真实 API Issue.status 是 open/decided，语义标签在 classification。最低复现不需要 Provider：将成功通过 engine.validate 的四个静态规则 Issue 按真实 API 约定投影为 `status=open, classification=conflict`，四例均被打为 `confirmed_conflict_class_mismatch`。

此外 `score.py:46–50` 从最终 Issue 读取 temporal_basis；engine.py:407–409 和 v2_database.py:3457 返回的 review 不含该字段。四个已被 validator 接受的静态规则 Issue，直接送入评分器仍全部报 `timeless_rule_contract_missing`。这不是模型失败，而是评测入口不兼容。

应分开首答原文评分、engine/产品语义评分与关联响应中的时间依据审查，明确目标 claim 绑定和来源，不能给最终 API 补一个臆测字段以让评分通过。本次只验证字段适配，没有运行真实 API，也没有将投影声称为新 API capture。

已有正面负控：possible_conflict 不能冒充 confirmed_conflict，8/8 均被拒；`status=failed, issues=[]` 被判 terminal_failure，没有当 no_conflict。尚不能据此称完整评分负控、首答/最终分离或全部语义评分已完成。

### P2：actual-inputs.json 不是 UTF-8

按 UTF-8/UTF-8-SIG 读取在偏移 676 失败：`invalid start byte 0xb5`。PowerShell 宽松显示会出现替代字符。独立探针仅为诊断用 GBK 解码后核对，不改文件；这不等于正式资产可按 UTF-8 复跑。请由构建流程显式写 UTF-8，再记录新 hash；不能用有损解码掩盖正文或时间锚变化。

## 材料来源与覆盖风险

- `build.py:24–28` 的圆筒密封规则、“uncut and blue”及“uncut but gray, not blue”，与旧 `evaluation/fixtures/eval-v8-dusk-viaduct.json:42,48` 几乎逐句同构，只替换作品/物件称呼。当前 corpus 却标 `deterministic_original / source_inputs=[]`。不能称这部分为全新证据结构；应真正重写，或明确披露旧题派生并限定比较用途。没有据此断言整套集均为复制。
- 此快照已增加 Sera 明确后知控制；仍未覆盖前置设计所列的跨日、回忆/谎言、规则条件不成立等关键相近控制。不能用大部分直接复述型 no_conflict 代表这些有区别的边界，也不要求在本次审阅外扩展整套实测。

## 已核对事实与保留边界

结构为 24 例，8/8/8，8 组三联，4 个作品，6 个冲突要求至少 2 个来源。按 GBK 诊断解码现有 capture 后，24/24 的目标草稿及首 claim 与 cases 一致；所有预声明必要来源的 body/excerpt 与 corpus 全文逐字一致，必要 body hash 匹配，捕获 Memory 的 type/subject/predicate/value 与 corpus 对应项一致。因此在本快照中，没有发现“必要 ID 在而正文关键句截断/错配”的情况。这个结论只覆盖宣告的必要证据，不替代 gold 的语义正确性。

fixture loader 静态代码将同一 corpus.body 写入章节和 SourceSpan，摘要取前 180 字，并绑定 Memory 来源、version=1、author_confirmed。未读取或运行任何 fixture 数据库，因此本审阅不声称验证了持久化端到端状态。

preflight 的 fake Provider 固定返回空 issues，只能证明输入路径和捕获，不证明金标准可表达或模型效果。manifest、完整评分机制及最终交接未在本审阅范围内定稿，统一标 **待 handoff**，不以尚未写完报告缺陷。收到最终交接后，仅按最终 hash 复核上述确定问题及被修订材料。
