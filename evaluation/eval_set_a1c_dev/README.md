# A1c 调试集

本集遵循 `evaluation/assistant_a1c/SPEC.md` 和其引用的 A1、A1b 规范。作品《回声之外的赛道》是近未来都市混合现实竞技群像：一支候补队从报名时的路线失误开始，通过训练、资格复核、伤病与分工调整，完成公开赛。作品正文由作者逐章原创，程序不生成、扩写、重排模板或替换句型。

## 文件与规模

`works/race.md` 为唯一完整作品，30 章，每章 2,500–3,500 汉字。`tasks.json` 包括 800–1,200 汉字共享草稿、两章计划、线索记录和 15 题：QA 9（single 2、multi 3、not_in_text 2、conflicting 2）、RECAP 2（k=15/30）、FIX 2、follow_up 2。具名人物、别名、易手物件、状态变化和故意矛盾的证据登记在 `authoring/self-review.json`。

`authoring/story-bible.md` 是写作前登记的统一设定和分批协调记录。独立复核结果另存于 `authoring/independent-review.json`；逐题自查将引用其结论，不把结构检查通过当作语义正确。

## 离线检查

在本 worktree 可运行：

```powershell
& '..\story-continuity-copilot\.venv\Scripts\python.exe' -B evaluation\eval_set_a1c_dev\check.py --staged-dev
```

也可从任意当前目录用绝对路径运行脚本。检查器仅以 `__file__` 所在题集为范围，不导入产品代码，不读取其他题集，不发起模型调用。正式集使用逐字节相同的 `check.py`，由 `set_id` 决定对应规模。输出只含标识、结构和数字。

## 约定与歧义处理

- A1c 未明确改写 version 和题号前缀，沿 A1b 命名方式使用 `a1c-1`、`a1c-dev` 和 `a1cd-`；不修改登记的 SPEC。
- 汉字计数口径为 Unicode U+3400–U+4DBF、U+4E00–U+9FFF，标题不计。引句位置指正文中引句首个汉字的一基序号；严格 `>1500` 才是深处。引句在章中须唯一，避免按错误命中标注。
- `evidence_quotes` 是与 `evidence_chapters` 同序一一对应的原样字符串数组。QA 有答案题（包括 conflicting）和 follow_up 都标注 `deep`；依 2026-10-16 补充，正式集为两部各30章、各15题，“合计至少12道、每部至少5道”只计 answerable_single、answerable_multi 和 follow_up，conflicting 不凑数。
- “至少三分之一”按较严格口径解释为全部去重考点句的三分之一，而非深处句中的三分之一。计入逐题自查中 QA、追问、第一问、FIX、RECAP 的正文依据，按章标题和原样引句去重。计划没有已发表正文依据，不列入分母。
- 照抄检查移除标点后取连续八汉字，专名以 `names` 中明确登记的名称为边界豁免；题目、选段、FIX 草稿、回顾开头和共享草稿均与所依赖章节比对。只豁免名称本身，不豁免普通叙述句。
- multi 问初始和最终两个端点，答案需分别取自相隔至少十章的章节；最终章不得汇总复述两端。找不到题保留正文中的相关人物活动，但不写出所问年龄或私人职业动机。
- 没有读取已有题集的作品、题目、自查记录或专名表，因此不声称完成对全部历史作品的专名查重；本集专名独立设计，两套新集之间另作精确交集检查。唯一允许参考的旧题集文件是 `eval_set_a1b_dev/check.py`。

## 封存与状态

`set.sha256` 按路径排序覆盖 `tasks.json` 与 `works/` 下全部文件。文本用 UTF-8 无 BOM、LF；题集通过 `.gitattributes` 保留封存字节。自查与独立复核的最终状态以各自记录和交付报告为准；本说明不声称运行过真实模型或产品评测。
