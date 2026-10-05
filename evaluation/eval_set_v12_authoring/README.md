# 第四套留用案例：与第三套相同的出题要求

6 部全新作品、48 章、36 题。中英文各 3 部作品、18 题；conflict、no_conflict、insufficient_evidence 各 12 题。冲突覆盖全部 8 类，恰好 3 道指定回归题。每章正文不超过 300 个 Unicode 字符，本套最大值为 262。

## 文件

- `cases.json`：完整原文、各自独立的草稿和作者金标。
- `cases.sha256`：题集的 SHA-256 校验值。
- `sources/`：6 份完整 Markdown 原文，与 JSON 的 `source` 逐字一致。
- `check.py`：逐字节复用第三套的静态结构检查器。
- `authoring/content-review.json`：共享名词、指定回归约束、逐题判断理由和作者文字校对记录。
- `authoring/closeout.json`：最终文件哈希、数量、检查结果与工作范围。

| 作品 | 完整原文文件 |
|---|---|
| 蒲瓴城的折光节 | `sources/puling_refraction_festival.md` |
| 笙岫谱馆的失页 | `sources/shengxiu_score_library.md` |
| 迢槿坡的雨水工地 | `sources/tiaojin_rainworks.md` |
| Brambletide's Aquarium Census | `sources/brambletide_aquarium_census.md` |
| Calverin's Rag-Paper Mill | `sources/calverin_rag_paper_mill.md` |
| A Lift at Elmrake Hotel | `sources/elmrake_hotel_repairs.md` |

## 与第三套一致的输入约定

顶层字段为 `version`、`author`、`corpora`、`cases`。每部作品使用 `key`、`title`、`language`、`source`。完整 `source` 用 Markdown 一级标题分章，章节标题在作品内唯一；没有旧格式的 `chapters`、`label`、`is_rule` 字段。

题目字段为 `id`、`corpus`、`draft`、`expected_class`、`category`、`evidence`、`designated_regression`、`note`。`evidence` 是完整章节标题列表，不包含开头的 `# `，例如 `第一章 映砂的永久法则` 或 `Chapter 1 The Face Inspection`。

每题 draft 为独立的一段正文，1—3 句，只包含一个主要判断点。同一作品各题共享 source，但每次整篇替换 draft，不追加前题内容。金标与 `authoring/` 记录仅供验收，不作为模型输入。本轮未执行转换器。

## 判断与指定回归约束

需要判断的事实在原文中直白陈述。已核对全部 39 条章节引用：每条引用的章节正文和对应 draft 都共享明确的人名、物名或地名。证据不足题缺少因果区分、答复、实际见闻、身份、审批、测量结果、后续状态或检查结果等环节；未把单纯缺共同时间当作证据不足。

普通冲突允许按第三套口径判为明确矛盾或可能矛盾，不要求共同时间。hv12-010、hv12-022、hv12-034 保留未限定时间的草稿。无冲突题均有原文直接支持。

只有以下三题要求 `nature = confirmed_conflict`（明确矛盾）且类别正确：

| 题号 | 类别 | 约束依据 |
|---|---|---|
| hv12-001 | world_rule | 永久规则在任何情况下都禁止映砂自身发光产生热量；规则本身构成反证 |
| hv12-007 | relationship | 草稿和证据共享 `2032年5月8日14点` |
| hv12-025 | attribute | 草稿和证据共享 `12:05 on 21 June`，面积值由原文直接陈述 |

两道带时间的指定回归题已用当前产品的纯时间范围函数检查完整锚点。规则题已核对禁止条件，不把必要条件误写成充分条件。此项检查不涉及 Provider、Memory 抽取或模型判断。

## 静态检查与范围

在 `story-continuity-legacy-gap-repair` 目录运行：

```powershell
.\.venv\Scripts\python.exe -B evaluation\eval_set_v12_authoring\check.py
```

检查器只验证结构、题数、章节标题、正文长度、类别覆盖与指定回归数量；金标语义由作者校对。本套未进行独立盲审，尚未实测 Memory 抽取、检索召回或模型表现。

本轮只编写案例、校对和做静态检查。前三套及其校验文件保持原样，未修改产品代码、评分器或评分阈值，未读取以往模型结果，未调用 Provider、未进行模型评测或正式 Gate。
