# A2 新动作调试集 `a2t-dev`

可读的开发材料，36题：两部作品各动作9、不该改3、路由4，另含注入4。主动作按每部 add_thread/edit_thread/abandon_thread 各3；各有一题混合新旧动作。题目版本 a2-2。本交付只出题和离线检查，未运行产品或评测。

w01原样复用 `eval_set_a23_formal/works/w01.md`，w02原样复用 `eval_set_a24_formal/works/w01.md`；对应事实文件逐字节复制。作品title/names/shared_draft也保持来源内容。伏笔资料及请求重新设计。事实不能改，四道资料注入均放在 foreshadow.description；其余合法动作与载荷目标分离。

正文中的历史线索即使后来已有回应，也可作为“资料漏记”的add_thread对象；请求只要求新增时，不擅自再加回收动作。未收、已收未标、已标回收三类分别核查。w01移出来源伏笔1/2后，仅保留来源resolved_unmarked3/4的章号和原句并重映射序号；w02原四条全部保留。详细差异、逐题依据、章内位置、独立盲判与复核边界见 `authoring/self-review.md`。

从仓库根运行：

```powershell
..\story-continuity-copilot\.venv\Scripts\python.exe -X utf8 -B -m evaluation.eval_set_a2t_dev.check
```

也可在任意目录用指定Python加本目录check.py绝对路径运行。检查器只校验本集；新颖性部分程序读取本checkout已有tasks.json的input/question/request，在内存中比对、仅输出计数，不保存或展示封存原文。本文的作品复用不做跨作品专名零重合要求，新的请求仍须通过copy8与0.8相似度检查。

`set.sha256`按路径排序覆盖全部7个数据文件。`independent-review.json`额外绑定数据、自查及原始盲判记录。authoring内package和组装脚本是过程记录，最终权威为tasks.json、works/、materials/和对应manifest；修改数据后须重新复核与绑定。

PASS表示字节一致性、结构、分布、引用、深处位置、照抄/新颖性、哈希和审读记录绑定通过，不代表真实模型质量或正式评测过线。
