# V6 runner 输入层待核问题

2026-09-27。仅只读审查正在落盘、尚未冻结的草稿；没有运行 runner、Provider、DB 或测试。本页不是最终验收结论，旧 core-stable-01 与原探针均未修改。

1. **新 10 例缺少同次草稿身份/版本核对。** `evaluation/current_flash_v6/inputs.py:new_control` 校验 body 与 claim 文本，但未比较 request.draft.id/revision 和 runtime-binding 中保存的 draft_id/draft_revision；继承的 V5 runtime_binding 对 comparison 分支也只核 body。旧 24 例另有完整历史 capture 比较，新 10 例没有该补偿。建议在 V6 输入层对所有请求明确比较同次保存的 id/revision；同文本配错误身份或版本须在派发前拒绝。
2. **新控制只逐行检查 Memory，不能证明选中集合完整。** new_control 的循环可被 memory=[] 跳过，也不排重复；同次 DB 核对同样只覆盖传入行。lens fixture 明示三条 Memory，其他 fixture 可合法为空。建议按事前确定的检索/捕获结果固定每例预期选中 ID 集合、数量和完整字段，保留可能来自未引用来源的合法关联；不能一概要求所有 fixture Memory 都必须入选。派发前验证缺失/重复/额外项与既有字段绑定。

审查所见 inputs.py SHA256：`cf3c9a055b769c0504412e9e56ca915964bd87026120a686682bb867d773a659`。

尚未完工项暂不下最终缺陷结论：score.py 仍沿用旧 GOLD 查找与旧 raw validator 接线，当前新 case ID 会在 safe scorer 之外查找失败，V6 ledger 也不应交给无 V6 标识的旧 validator；freeze/guard/preflight 尚未落盘。待正式交接一次核查新评分政策、完整依赖、重复身份早拒绝、单批/派发上限与首失败留存，无需反复审计复制中的草稿。
