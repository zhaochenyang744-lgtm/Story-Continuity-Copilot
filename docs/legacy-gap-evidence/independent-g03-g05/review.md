# G03 / G05 独立只读复验

日期：2026-09-26。工作树基线：`39de855c005d77f7f02a132f5e807a0c1c476b7b`。本报告只覆盖 G03 / G05，不代表整个修补版本或发布验收。

结论：**仍有两个 P2，当前不能将 G03 与 G05 的约定范围记为独立验收关闭。** 已有测试 12/12 通过；独立探针 13 项，10 项通过、3 项断言暴露两个不同问题。三条失败断言中的两条是同一个 G05 用量问题在 Provider 与持久化层的复现，不计为两个问题。

## P2：优先选中来源 ID 后，真正发给模型的窗口仍可能没有目标事实

- 文件：`backend/app/v2_database.py:2975`，关联 `2955–2956` 与 `2983`。
- 目标 Memory 和直接 SourceSpan 已经优先选入原有 8 / 4 个槽位；作品、章节当前来源版本和项目来源版本过滤也成立。但是 `source_items` 仍使用从草稿/规划提取的通用 `terms` 做 500 字窗口截取，没有围绕目标 Memory 的主语/值/变更提案定位。
- 最小复现：当前 Memory 为“星钥始终由乔霁保管”，其当前 SourceSpan 的第约 1000 字才出现该事实，前面为与目标无关的景物；草稿保持原教学内容。请求对该 Memory 做“改为由沈砚保管星钥”的影响分析。`target_source.status` 为 `selected`，目标来源 ID 是第一个，但 fake Provider 收到的 501 字文本只有前段景物与省略号，没有“星钥”或事实句。
- 独立证据：`probe-results.json` 的 `pinned_source_contains_target_fact_passage`。原来源 1510 字，供应片段 501 字，目标事实不在供应片段中。
- 影响：G03 的目标原始依据仍可能没有实际送到模型，`selected` 仅证明来源身份选中，不能证明目标依据被覆盖。这会保留修补原本要解决的上下文缺失。建议为目标直接来源单独锚定有限窗口，并区分“来源选中”和“目标事实片段覆盖”；仍找不到时使用部分/不足状态，不扩大文本预算。

## P2：超时后成功重试，会将最后一次响应的用量当成完整 Run 的可用用量

- 文件：`backend/app/provider.py:372–378`，关联 `343–382`；后续 `engine.py:137–141`、`v2_database.py:3267` 与 `operations.py:275–280` 延续该信号。
- 最小复现：同一次 evaluate 的首次 HTTP 已派发后 ReadTimeout；第二次成功，假响应提供 `prompt_tokens=11`、`completion_tokens=7`、`cost_cny=0.2`。持久配额账本和 `request_attempts` 都正确为 2，但 `ProviderResult` 只返回第二次响应的 11 / 7 / 0.2，无首发未知用量标识。
- 完整 API → Engine → SQLite → operations.usage 探针进一步证实：Run completed，存入 11 / 7 / 0.2；三个 `run_observed_metrics` 均为 `available`、`unknown_run_count=0`、`all_run_sum` 为这些值。`billed_cost_status` 仍为 unknown，这点正确，但不补足 Run 用量完整性。
- 独立证据：`retry_success_preserves_unknown_first_attempt_usage` 与 `persisted_retry_usage_marks_unknown`。
- 影响：请求次数修复正确，但成功重试掩盖了已派发超时尝试的未知消耗。建议保留成功响应的 known partial 用量，同时令完整 Run 用量为 unknown，或附明确完整性字段贯穿存储和汇总。不得把首发超时的消耗当 0。本问题是 G05 修补后保留的既有用量语义缺口；并非本次新增的配额越界。

## 已验证成立的范围

- 原有 G03/G05 测试与 change-impact 回归：12 passed、0 failed、0 skipped。
- 有 20 条当前 Memory、16 个当前 SourceSpan 的合成作品中，弱词法匹配目标仍在第一槽；最终 Memory / SourceSpan 数仍为 8 / 4。
- 目标来源与章节当前版本不匹配时不会送给模型，结果为 insufficient、空影响项。
- 来源/章节均为 r2、项目仍为 r1 时，该来源不会进入当前项目输入。
- 剩余 1 次额度时：第一次 HTTP 超时后，第二次发送前被拒；保持 `provider_attempt_quota_exceeded`，账本、发送数、provider counter 都为 1。
- 允许重试时：2 次派发、2 条持久额度计数，无 evaluate 层双算。
- 4 个线程走完整 Guard → Provider → fake transport，配额为 1：只发送 1 次，其余 3 次均为明确 quota denial。
- 经公开 API 的 quota denial、连续双超时、连接错误分别得到 `failed/provider_attempt_quota_exceeded`、`timed_out/provider_timeout`、`failed/provider_error`；问题写入数均为 0，未知 token / cost 保持 null。
- `git diff --check` 通过。审阅时业务文件 SHA256 在 `regression-summary.json`；没有修改业务文件或已有测试。

## 执行与边界

- `probe.py` 是独立编写的断言与 fake transport，不复用实施测试的 helper。全部数据库在本目录 `synthetic-*` 新隔离目录生成，只含合成/教程数据；未读取运行数据库、`.env`、原始评估或私人证据。
- `run-regressions.py` 只运行 `tests.test_legacy_dispatch_quota`、`tests.test_v130_character_alias_change_impact`。原始日志保存在 `regression-log.txt`。
- 测试进程设置 `SCC_DISABLE_DEFAULT_APP=1`，不启动默认真实数据库；网络保护禁止外部 socket 和 SMTP，Provider 使用 fake Client。实际外部 Provider HTTP / SMTP 均为 0。
- 探针初次执行在 Windows asyncio 内部 loopback socketpair 被过严网络保护阻止时退出，发生在注册请求执行前，不是业务失败。之后仅允许该宿主所需 loopback 连接，外部网络仍拒绝，再执行得到本报告结果。
- 没有真实模型效果、生产兼容性或商业账单验证；没有提交、推送、部署、修改 Agent 功能。
