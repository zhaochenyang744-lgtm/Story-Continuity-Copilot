# A2 正式留用集

依据 `evaluation/assistant_a2/SPEC.md`、`thresholds.py` 及桌面任务05编写，不修改登记规则。两部独立原创中文作品各20章，每章2500–3500汉字；每部28题，action 12、no_action 6、route 10。第21章共享草稿为600–1000汉字，独立于已完成正文。起始事实和伏笔按各自JSON数组的一基序号引用。

正文按主代理先行设定、四章一批逐章原创。程序只保存已经写成的字面量、核对结构、计数、查重、位置及哈希，不生成或扩写正文。主代理统一编写题目及答案；未参与该作品写作的代理进行全文连续性复核，另以不含金标的input/context进行route独立复判。完整记录在封存的authoring目录。

## 校验与封存

从仓库根目录运行 `..\story-continuity-copilot\.venv\Scripts\python.exe -X utf8 -B -m evaluation.eval_set_a2_formal.check`；也可从任意目录用该解释器运行本检查器的绝对路径。只使用标准库，不导入产品或评测运行器，不访问网络。所有读取限于本套目录；输出为一行JSON，只含数量、结构、编号和固定错误码。

`set.sha256` 按相对路径排序，覆盖tasks.json、works及materials内全部文件。authoring/independent-review.json另绑定同一组文件。文件使用UTF-8无BOM、LF；.gitattributes保护封存字节。结构PASS不代表助手质量或正式评测通过。交付后正式运行前，开发及评测准备会话只运行check.py，不读取正文、资料、题目、答案或authoring。

## 口径

- 汉字范围为U+3400–U+4DBF和U+4E00–U+9FFF，不含标题。位置是一基首汉字位置，严格大于1500才算深处；去重与出现次数两种分母都核对。沿A1c第2节另检查至少三分之一去重依据在2500字后。
- 任务evidence_chapters使用不带井号的完整章标题；材料chapter及自查chapter/changed_chapter用整数章号。每条引文须在对应章唯一出现。
- “主要动作”以expected_actions第一项计数，不增加运行字段。双动作题的全部动作均受金标及自查依据约束。
- 本套成卷每题选择1或2条动作，检查器据此锁定；登记规则本身并未规定所有未来题集的动作条数上限。引用片段也由作者选择与自查同一条原句，检查器额外绑定这个选择。authoring文件、语义标签及独立记录是本套作者增加的冻结证据，不冒称是登记运行字段。
- also_acceptable按明确任务单及A1c第33条使用列表，最多一个；本集不使用fix_issue或支持FIX题。
- 照抄检查去除非汉字，专名作为边界豁免，比较request、input和每个after_points与作品全文的连续八汉字，不以删名后拼接两端规避。
- 新颖性采用编写前获准旧题输入快照，在本套authoring/novelty-reference.json内重算SequenceMatcher相似度，不在封存检查时打开其他题集。来源路径和SHA-256同时保存。全库比较服从明确禁读要求，排除eval_set_a1_reserve、eval_set_a1b_reserve、eval_set_v13_authoring；零重合只覆盖获准语料。开发分支是否已有任务文件在交付前再次核查。
- 快照按来源分别保存归一化输入，检查器核对分组并集、来源哈希格式和清单计数；独立记录另绑定快照及两份自查文件的SHA-256。selection从句边界开始并在句末结束，允许冒号引出的完整独立指令句。
- aliases中的quote也计入自查引文的位置分母。人物、题材、事实内容是否被正文支持等语义条件由逐题自查及独立通读核验，不由计数代替。

冻结状态及最终数字以完整检查输出和交付报告为准。
