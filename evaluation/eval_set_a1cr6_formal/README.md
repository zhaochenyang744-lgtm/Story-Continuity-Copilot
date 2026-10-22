# 用法判断重测封存题集

依据 `evaluation/assistant_a1c/SPEC.md` 补充十三第 33 条（1）和补充十六第 44 条编写。两部沿用作品逐字节复制自第五套，共 30 道新写的用法判断题；4 道 `support: true` 的 FIX 题仅用于准备上下文，不运行、不计分。每部 ask 共 5 道，包含常规 4 道和拿不准时默认 ask 的 1 道；`also_acceptable` 使用列表。

在仓库根目录运行：`..\story-continuity-copilot\.venv\Scripts\python.exe -X utf8 -m evaluation.eval_set_a1cr6_formal.check`。也可从任意目录用该解释器运行本检查器的绝对路径。输出仅含数量和错误标识；结构检查不调用模型或评测程序。

`set.sha256` 按相对路径排序覆盖 `tasks.json` 和 `works/` 下全部文件；新颖性比较仅使用既有题集的输入字段。封存后开发会话只运行检查器，不读取题目内容。建议题由 `note` 标记，拿不准的题在 `why` 中说明歧义；这些人工判断不等同于模型评测通过。
