# A3 第二套调试集

依据 `evaluation/assistant_a3/SPEC.md` 全文及2026-10-26补充一、预登记门槛和桌面任务22编写。版本 `a3-1`，集合 `a3-dev-2`，题号前缀 `a3e-`。这是公开可读的开发材料，最多运行三轮；本次工作只出题和进行离线检查。

《把台阶留给明天》写现代城市赫沄市一家家用无障碍辅具短租周转站的跨楼试办。正文三十章，每章2500–3500纯汉字；另有第31章600–1000汉字共享草稿。作品不采用校园、社团、广播、录音或老行当小镇题材。十一名人物中三名有别名，三件追踪对象各有跨十五章以上的实际状态变化和一处有意矛盾。

主控先写中央设定，正文作者逐章直接创作、每五章交接，再获派下一批。程序仅保存写定的字面量、原样装配章节及核对字数、重复、位置、结构和哈希，不生成或模板扩写正文。完整正文的唯一权威是 `works/w01.md`。题目及标准答案由主控在正文存在后统一编写。独立全文审读、整理资料题逐项完整性复核和只给input/context的路由盲判分别留证于authoring。

长任务8道：trace2、thread_audit1、tidy2、ask2、narrowed1。判断用法10道：long_task4、change2、ask2、check_passage1、recap1。两道tidy分别覆盖第1–10章和第16–22章，点名服务规矩、固定分工、固定时间地点、费用来源；这些类别的长期设定逐项列入起始资料或missing_facts及对应动作。一次事件、眼下处境、未定事项、即时持有人和人物能力自述不作为遗漏设定。

从仓库根运行：

```powershell
& '..\story-continuity-copilot\.venv\Scripts\python.exe' -X utf8 -B -m evaluation.eval_set_a3d2_dev.check
```

也可从任意当前目录用同一指定Python加本集check.py绝对路径运行。检查器标准库、离线、只读本集和本集保存的允许历史输入快照，不导入产品或评测代码。输出一行JSON，错误时非零退出。PASS证明结构与完整性，不能代替语义审阅或真实模型评测。

## 解释口径

- 纯汉字范围U+3400–U+4DBF和U+4E00–U+9FFF，不含章标题。考点位置为引句首汉字的一基位置，严格大于1500计深处；按引用次数和章号/原句去重分别统计，沿A1c另检查至少三分之一去重引句在2500字之后。
- 事实和伏笔按数组一基序号引用。材料及自查章号为整数；动作evidence_chapters使用不含井号的完整章标题。quote逐字在指定章唯一出现，长10–60字符；每动作依据最多两段，after_points只写原文明说的内容。
- 范围含两端，依据考点变化/回收/放弃/缺失设定首次明确所在章归属。narrowed从全书计划缩到plan_edit.chapters，卡片只取新范围内完整集合。task-intents.json冻结作者选择的任务类型，供检查器独立构造完整集合，避免删动作后仍靠题内自报数量通过。
- 追踪states只含实际交接等状态改变，不把仍在谁手中算一个节点。两处ask是叙述定稿选择，作者答复明确选a或b；起始资料没有相应槽位，expected_actions为空。
- selection为共享草稿完整句，含句末标点、至多80字符且只在writing页出现。本集没有fix_issue、支持FIX或注入题。
- 照抄比较request、input、after_points与本书全部正文，去非汉字后连续八字即报错。专名作为边界豁免，不能删除后拼接两侧，普通短语不能冒充专名。
- 新颖性直接对当前worktree可读旧tasks.json的input/question/request去空白及Unicode标点，SequenceMatcher达到0.8即失败。authoring/novelty-reference.json保存允许来源路径、SHA-256、归一化输入及names；检查器重算快照哈希，不重开历史题集。
- 七个禁读目录在枚举前明确排除：eval_set_a3_formal、eval_set_a3s_formal、eval_set_a25_formal、eval_set_a2s5_formal、eval_set_a1_reserve、eval_set_a1b_reserve、eval_set_v13_authoring。专名和新颖性结论只覆盖允许语料，不推断封存内容。
- set.sha256按路径排序，覆盖tasks.json和works/materials内全部文件。文本UTF-8无BOM、LF，.gitattributes保护字节。独立审阅另记录源文件绑定；任何语义修改后重核依据、审阅与哈希。

最终实际数字、完整检查输出、复核发现及负向测试见authoring/self-review.md和桌面22-交付报告.md。未调用模型接口，未运行产品或评测。
