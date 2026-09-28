# V6 核心增量独立工程验收

2026-09-27；唯一正式执行 identity：`core-stable-01`。结论：**本轮核心结构合同增量控制通过，9/9 组，无新增工程阻断。** 不等同真实模型质量、用户或发布验收，也不替代后续 V6 runner/输入/完整冻结的工程核查。

执行前后，CORE-REVIEW-FREEZE-01.json 摘要均为 `d340e009af4687fce098159f45ba6e99cb1542705107824faa4000f1080238e1`，其中 16 文件逐字摘要均吻合。独立探针 SHA256 为 `65d68db3c97dd2a83d5935d1e39b24cb1b8d116e3089a8590043986d5f548062`；脚本及其直接审阅的来源/合同文件执行前后未变。交接文档的 Provider 摘要排字问题使用主控实测冻结值核对，没有修写旧文档。

通过的增量路径：

- 三 claim 精确覆盖；缺失、重复、foreign、null/数字/list/dict ID、空 basis、缺失 ledger 均按合同错误拒绝。矛盾 issue/verdict、重复 issue 与错误 issue ID 也拒绝。
- reviewed_issue 保留合法 state_change；证据不足 issue 保留；合法新情节的有解释 no_issue 可以返回空 issues。ledger 未混入 Issue 行。
- repair 删除 issue 后仍须完整覆盖并解释；静默删除失败，有解释的兼容性重新判断通过。均只允许两次 stub evaluate，并保留首答与 repair 请求。
- 实际 _batches/execute 在内存降低预算后形成三批；每批精确覆盖通过，上批 verdict ID 不能覆盖当前 claim，第二次仍错即失败，后批未继续。
- selected-but-uncited 规则 Memory 不能提供 timeless_rule 资格；首答严格拒绝，execute 的有界二次结果保留一次明确归一化为 insufficient_evidence。规则自身来源另行引用的联合集合通过；该来源不在 claim 选中集合则拒绝。普通跨来源 Memory 关联仍可保留，不借此提供证明资格。

全部夹具为合成。只用实际 engine.validate/execute 与严格本地 stub；共 13 次 stub evaluate，真实 Provider 构造/调用、HTTP、socket/DNS、SQLite 连接/触达均为 0，拦截已启用。没有执行实施者 40/41 自测或旧 V5 durability/usage 测试；未改产品、V5 或既有证据。自然语言相关性、完整联合证明与 no_issue 理由是否真实仍须独立语义判断。

证据：`probe-runs/core-stable-01/results.json`、同目录六份 trace 与逐组结果；`core-before-formal-01.json` 为执行前收据（命名在最终 run identity 指定前创建），`core-after-core-stable-01.json` 显式绑定实际 identity 并保存结果摘要。只执行一次，所有证据 create-only；本次没有测试失败需要重跑。