# V6 版本字段审计告警关闭补充

原 live-01-engineering-review.json/md 保留不改。本补充关闭其中34项 final_runtime_versions 审计器误判；最终结论见 live-01-engineering-review-final.json/md。

冻结源码 `backend/app/v2_database.py:2850–2868` 的常规 continuity create_run 将 `draft["revision"]` 写入 `v2_runs.source_revision`，未写 `draft_revision` 列；`:3488` 原样返回这两个列。因此 final-product.source_revision 应对应 runtime-binding.draft_revision，不能拿它与 runtime-binding.source_revision（章节版本）相比。

|案例序号|运行 source_revision|绑定草稿 revision|运行 draft_revision|快照章节 source_revision|Memory version|
|---:|---:|---:|---|---:|---:|
|1|2|2|null|1|1|
|2|2|2|null|1|1|
|3|2|2|null|1|1|
|4|2|2|null|1|1|
|5|2|2|null|1|1|
|6|2|2|null|1|1|
|7|2|2|null|1|1|
|8|2|2|null|1|1|
|9|2|2|null|1|1|
|10|2|2|null|1|1|
|11|2|2|null|1|1|
|12|2|2|null|1|1|
|13|2|2|null|1|1|
|14|2|2|null|1|1|
|15|2|2|null|1|1|
|16|2|2|null|1|1|
|17|2|2|null|1|1|
|18|2|2|null|1|1|
|19|2|2|null|1|1|
|20|2|2|null|1|1|
|21|2|2|null|1|1|
|22|2|2|null|1|1|
|23|2|2|null|1|1|
|24|2|2|null|1|1|
|25|2|2|null|1|1|
|26|2|2|null|1|1|
|27|2|2|null|1|1|
|28|2|2|null|1|1|
|29|2|2|null|1|1|
|30|2|2|null|1|1|
|31|2|2|null|1|1|
|32|2|2|null|1|1|
|33|2|2|null|1|1|
|34|2|2|null|1|1|

34项均符合真实字段合同。**没有用 final-product 顶层版本字段独立证明章节版本，也未重新打开DB。** 原审阅的章节/来源一致性只来自留存的 runtime-binding JSON 与同次请求 JSON 对照；这是账本一致性检查。以上数字列示章节版本仅用于区分字段语义。

本补充未改产品、原始结果或首审报告；Provider/API/DB重放均为0。
