# A3正式留用集

依据已登记A3 SPEC全文及任务06；不修改规则。正文逐章原创，多场景推进；主控统一题目和答案，独立全文通读与仅input/context盲判另记authoring。

从仓库根目录用指定虚拟环境python -X utf8 -B -m evaluation.eval_set_a3_formal.check；也可任意目录以绝对路径运行check.py。检查器标准库离线，只读本套，输出一行仅编号、计数及固定错误码的JSON，有错非零。

set.sha256按相对路径排序覆盖tasks.json、works和materials全部文件。独立审读绑定数据及自查与查重快照。UTF-8无BOM、LF；封存后开发会话只运行结构检查器，不打开内容。

汉字计U+3400—U+4DBF、U+4E00—U+9FFF，章标题不计；首字位置一基。共享草稿600—1000汉字。考点半数>1500且至少三分之一>2500；专名作为照抄边界豁免。新颖性去空白/Unicode标点，SequenceMatcher比值达到0.8即报错。

查重在遍历前排除eval_set_a1_reserve、eval_set_a1b_reserve、eval_set_v13_authoring；零重合仅覆盖获准语料。未调用模型、未运行产品或评测；结构PASS与语义审读分开记录。
