# 第三套 A2 正式留用集

版本`a2-1`，集合`a23-formal`，题号前缀`a23f-`。依据当前A2 SPEC全文及补充一至五、thresholds.py、引用的A1/A1c写法与桌面任务16。两部原创中文作品，每部20章，每章2500–3500汉字；各有600–1000汉字的第21章共享草稿，草稿独立于已完成正文。每部action12、no_action6、route10。起始事实25–40条、伏笔8–12条，序号从1起。

主控先登记统一设定和资料变化，正文作者逐四章手写原创并交接，主控审查后再派后续章节。程序只保存写定文字、装配手写元数据并做计数、位置、重复、结构与哈希核验，不生成或扩写正文。主控统一出题与核对金标；未参与作品写作的审读者全文复核；判断用法另以乱序id/input/context独立盲判。实际记录保存在封存authoring中。

## 检查与口径

在worktree根目录使用`..\story-continuity-copilot\.venv\Scripts\python.exe -X utf8 -B -m evaluation.eval_set_a23_formal.check`，也可从任意目录用同一解释器运行check.py绝对路径。检查器仅用标准库，只读本套，无网络、模型、产品或评测运行。输出一行JSON，仅含编号、固定错误码和数字；错误时非零退出。

- 汉字计U+3400–U+4DBF及U+4E00–U+9FFF，不计标题。依据位置以首汉字一基计，严格大于1500算后段；同时报告重复引用和按章/引文去重的口径，附2500后数量。
- 资料、自查的章号为整数；动作evidence_chapters为完整章标题，不含`# `。正文发生的明确变化与起始资料旧值不同，属于预设测试条件，不是应消除的正文矛盾。
- 主要动作取expected_actions第一项；次要动作同样完整受约束。resolve_thread要点原样使用`已回收`、`收在第N章`（N为阿拉伯数字）；若另有回收方式要点，须直接由本条引文支持。
- selection取共享草稿完整原句，只在writing页，含句末标点，至多80字符。本集不使用fix_issue，不附support FIX。
- 照抄覆盖request/input/after_points与本部全文，去非汉字、专名作为断点，连续8字即失败。专名仅实际人名、别名、地名、具名物件，不用普通短语规避检查。
- 新颖性在创作阶段对获准旧tasks.json的input/question/request去空白及Unicode标点，按SequenceMatcher相似度≥0.8判重，保留大小写。本套保存来源哈希与归一化旧题快照，封存checker不读其他套件。两部及两新套间另作比对。
- 遍历前排除eval_set_a1_reserve、eval_set_a1b_reserve、eval_set_v13_authoring；名称零重合及新颖性结论不覆盖这些禁读目录。旧快照所含原有文字同样不得向开发报告外泄。
- self-review中的语义标签和独立审读记录是作者冻结证据，不是新增产品输入字段，结构PASS不代表语义自动验收或模型质量。

set.sha256按相对路径排序覆盖tasks.json和works/materials全部文件。UTF-8无BOM、LF；.gitattributes保护字节。独立记录另绑定源文件及自查、快照。任何语义修改均重新审阅、绑定、生成manifest并校验。交付后封存，正式运行前开发与准备会话只运行checker，不打开正文、资料、题目、答案或authoring。交付报告只含数字和结构。
