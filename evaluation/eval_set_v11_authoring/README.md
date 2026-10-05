# 第三套留用案例：完整原文与章节标题格式

本目录交付 6 部全新作品、48 章、36 题。中文和英文各 3 部作品、18 题；conflict、no_conflict、insufficient_evidence 各 12 题，冲突覆盖全部 8 类。每章正文最多 262 个 Unicode 字符，未超过 300 字上限。

## 文件与输入格式

- `cases.json`：完整原文、独立草稿与作者金标。
- `cases.sha256`：上述文件的 SHA-256 校验值。
- `sources/`：每部作品一份完整 Markdown 原文，内容与 JSON 的 `source` 逐字一致。
- `check.py`：适配新格式的静态结构检查器，只使用 Python 标准库。
- `authoring/content-review.json`：逐题理由、共享名词检查、指定回归约束与作者文字校对记录。
- `authoring/closeout.json`：文件哈希、格式检查结果和交付边界。

顶层仍为 `version`、`author`、`corpora`、`cases`。每部作品字段为 `key`、`title`、`language`、`source`，不再使用旧版的 `chapters`、`label`、`is_rule` 字段。永久规则直接写在原文中。

`source` 是完整 Markdown 文档，用一级标题分章。中文形式为 `# 第一章 月纹账本`，英文形式为 `# Chapter 1 The Fiber Inspection`。章节标题在作品内唯一。`evidence` 保存不含 `# ` 前缀的完整章节标题，例如 `第一章 月纹账本`；不能按旧版 label 解析。

题目字段为 `id`、`corpus`、`draft`、`expected_class`、`category`、`evidence`、`designated_regression`、`note`。每个 draft 是独立的新章节正文，包含一个主要判断点；同一作品各题共享完整 source，每次整篇替换 draft，不把前一题的草稿追加进项目。

金标字段及 `authoring/` 记录供验收使用，不作为模型输入。旧版仅支持 chapters/label 的转换器不能直接用于本文件；本轮不实现或执行转换器。

## 第 4 节约束的落实

需要判断的事实在原文中直白陈述。36 题与其 41 条章节引用均核对了 draft 和目标章节正文共同出现的人名、物名或地名，具体词见内容复核记录。这一静态检查不等于已经验证 Memory 抽取或检索召回。

普通冲突题允许按新口径判为“明确矛盾”或“可能矛盾”；没有共享时间本身不能把它们改标为证据不足。hv11-004、hv11-025、hv11-028 的草稿未限定时间，专门保留这种普通冲突场景。

只有以下 3 题为指定回归题，验收要求 `nature = confirmed_conflict`（明确矛盾），且类别正确：

| 题号 | 类别 | 明确矛盾依据 |
|---|---|---|
| hv11-001 | world_rule | 原文明示永久规则，规则本身足以构成反证 |
| hv11-007 | relationship | 草稿与证据均为 2031 年 8 月 4 日 16 点 |
| hv11-022 | attribute | 草稿与证据均为 9 February 12:40 |

后两题的完整时间锚点已通过当前产品的纯时间范围校验函数；规则题已做文字校对。没有运行 Memory 抽取、检索、模型判断或正式 Gate。

证据不足题均缺少具体环节，例如身份、产地、对应关系、参数、上下文或结果。规则题针对必要条件被违反，不把“条件满足”误当成“结果必然发生”。

## 静态检查

在 `story-continuity-legacy-gap-repair` 目录运行：

```powershell
.\.venv\Scripts\python.exe -B evaluation\eval_set_v11_authoring\check.py
```

本检查验证结构、章节标题、正文长度、题数、类别覆盖与指定回归数量，不判断金标语义。文字校对由作者完成，未进行独立盲审；共享名词和产品时间兼容检查另记在 `authoring/content-review.json`。

前两套案例及其校验文件保持原样。本轮只编写案例、校对文字、检查格式并保存哈希，未调用 Provider、未进行模型评测、未修改评分器或产品代码。
