# V6 同次输入绑定增量结果

2026-09-27；一次正式执行 `input-binding-02`，**5/5 控制通过**。使用既有 prep-v6-02 的 case 25 request、runtime-binding、case-start 与 cases-v2.json；先确认案例摘要及 business request 摘要对齐同次 capture，再调用当前 InputContract。

原输入通过。只改 draft.id 或 revision 均返回 `control_draft_id_or_revision_database_binding`；Memory 清空、保持原数量但将末项换成首项的重复变异，均返回 `control_selected_memory_set_drift`。未因不相干错误得到假负控。关闭 pending-review.md 中两项输入层风险，适用当前输入版本。

直接记录的 11 个关键源码/材料/探针摘要前后全部一致。inputs.py 为 `5b70bf132a4bc6fc4b07f7e7403fcb41ce7fdd9bfd885c9f7860c4610ac8ed48`，build_cases.py 为 `24ee48763ab0e1b3ec37ed6faa4682454a8a70284289d247bc450ff5d5ad71cf`；完整列表见 `input-probe-runs/input-binding-02/before.json` 与 `after.json`。这份局部摘要记录不是完整 V6 依赖冻结，最终交接仍须与完整 manifest 及继承的旧材料保护核对。

实际 API 重放 0、Provider 0、HTTP/socket/DNS 0、SQLite 连接 0；只读取 JSON 并作内存变异。首失败留存机制开启，本次无失败、无复跑。结果在 `input-probe-runs/input-binding-02/results.json`；未修改产品、eval 或旧 evidence。最终 manifest 中相关摘要若不变可承接此结果；若改变，只核验相关差异。
