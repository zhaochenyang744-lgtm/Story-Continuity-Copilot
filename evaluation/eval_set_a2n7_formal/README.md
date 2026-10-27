# A2 supplementary holdout: a2n7-formal

依据 evaluation/assistant_a2/SPEC.md 全文、补充十二、任务单34和任务单32的适用正式集规则创作。交付后封存；开发会话在正式评测前仅可运行本目录检查器，不打开内容。此目录的静态 PASS 不代表语义验收、模型表现或正式补测通过。

## 结构

- 1 部中文作品，12 章，每章 2500–3500 汉字。
- 第13章共享草稿 600–1000 汉字。
- 起始事实 25 条、伏笔 10 条。
- 20 道改资料任务：no_action 12，action 8；route 0，injection 0。
- no_action 类型数量：already_recorded 4，no_evidence 4，prose_edit 2，unsupported_kind 2。
- action 主要动作数量：change_fact 2，resolve_thread 2，add_fact 2，edit_thread 1，abandon_thread 1。每题只要求一处改动。

## 写法解释

1. 任务单34明确替换任务单32的章数、题数、分布以及多动作要求。全部题目按 change 任务运行。
2. 口语与模糊比例按第六套动作题折算，使用向上取整：paraphrased 最少 4/8；vague 最少 1/8，且至少一道为新动作。实际数量由检查器输出。
3. 任务单34把 edit_thread 和 abandon_thread 各指定为一道，因此不再执行第六套要求两种 edit_thread 模式各一道的数量。唯一 edit_thread 采用按正文纠正说明，author_words 为 false。
4. 外号对应在正文和事实中均明确，四名人物各有一个外号。alias_use 是 authoring 验证元数据，不供运行中的助手判断。
5. premise_contradicted 和 premise_evidence 标记正文明确反驳前提的题；why 含反驳原句，只用于检查与复核。
6. 全部20题盲判采用随机乱序的不透明编号，blind-key.json 仅供主控与检查器映射。盲判包不包含 suite、why、expected_actions、request_targets、类型、布尔考点标记或答案。
7. 汉字位置同时继承 A1c 第2节至少三分之一唯一依据在2500字后的要求。正文不靠程序生成。

## 文件

works/w01.md 是唯一装配正文；materials/ 为起始数组，索引从1开始；tasks.json 为题目及金标。authoring/ 包括创作设定、交接、自查、独立全文审读、盲判原始记录及分歧处理、可读语料快照、封存语料计数回执和离线验证脚本。

set.sha256 按路径排序，覆盖 tasks.json、works/ 和 materials/ 的全部数据文件。独立复核记录另外绑定数据和相关 authoring 文件的 SHA-256。

独立全文审读后的三处时间词与一处vague标记修订记录在authoring/revision-log.json。首轮盲判包、编号映射和原判以.initial.json保留；正文修订后复读相关章节并再确认全部判定。创作交接文件记录的是各段交稿快照，最终字数和引用位置以canonical正文、自查和最终检查器输出为准。

## 离线检查

在仓库根目录运行：

```powershell
..\story-continuity-copilot\.venv\Scripts\python.exe -X utf8 -B -m evaluation.eval_set_a2n7_formal.check
```

亦可用指定虚拟环境 Python 以本 check.py 的绝对路径从任意目录运行。检查器只读取本套目录，输出数字、编号和结构；它不会调用模型、启动产品或运行评测。跨题集比对只在 authoring/corpus-audit.py 中执行，封存语料只留下计数和哈希。
