# G03 / G05 第三轮独立复验

日期：2026-09-26。工作树 `story-continuity-legacy-gap-repair`，HEAD `39de855c005d77f7f02a132f5e807a0c1c476b7b`。业务源码由实施者声明冻结后执行，评审对象为当前未提交修补；前两轮探针、首次失败、返修证据均保留。

## 结论

本轮 G03/G05 约定的公开 Web 链路有界离线复验通过。第二轮两条失败已关闭：契约修复发出请求后超时，及其重试被持久额度拒绝时，完整 Run tokens/费用均为未知，SQLite 和 operations.usage 口径一致。派发前直接拒绝的正控继续保留完整已知用量，没有过度置空。

独立断言 35 / 35 通过（含网络禁用断言）；既有定向回归 17 tests、0 failures、0 errors、0 skips。未发现本次复验范围内仍需返修的问题。该结论不代表真实模型效果、全部 Provider 工具组合、用户验收或发布 Gate。

## 关键结果

| 场景 | 第三轮结果 |
|---|---|
| 初次已知响应，契约修复两次超时 | 3 次 fake post = 3 次额度计数；Run 为 timed_out/provider_timeout；tokens/cost 全为 null；operations 三项 unknown、unknown_run_count=1 |
| 初次已知响应，修复首发超时，重试被额度拒绝 | 2 次 fake post = 2 次额度计数；Run 为 failed/provider_attempt_quota_exceeded；完整用量 null、operations unknown |
| 初次已知响应，修复请求在派发前直接被拒绝 | 1 次 post；Run 失败但已发生请求的完整用量仍为 11 / 7 / 0.2；operations available |
| 单次正常成功 | Run completed，用量 11 / 7 / 0.2，observed_response_* 保留同一响应值；operations available |
| 首次超时、第二次成功 | 2 次计数，无双算；完整用量 unknown，第二次响应的 11 / 7 / 0.2 留在 observed_response_*；SQLite/operations unknown |
| 已知无效 JSON | 单次失败为 invalid_json，用量仍已知；契约修复返回无效 JSON 时两次已知响应正确累加为 22 / 14 / 0.4 |
| 未知无效 JSON | 超时后返回无效 JSON，及契约修复先超时后返回无效 JSON，完整 Run 用量均 unknown；后一次响应 observation 仍保留 |
| 契约修复成功正控 | 两次有响应正常累加 22 / 14 / 0.4；第二次 evaluate 内先超时再成功则 3 次计数且完整用量 unknown |
| 额度、并发、失败 | 剩余 1 次额度时第二次派发被阻；4 并发共享额度 1 仅 1 次 post/1 次成功；基本超时/连接错误保持具体状态与错误码，零 Issue 写入 |
| 目标原文召回 | 低排名目标在 8 条 Memory / 4 条 SourceSpan 预算内优先；原文第 1100 字后的目标事实实际进入 500 字窗口（加省略号总长 502），长度/截断元数据准确 |
| 目标来源正负控 | 短原文完整保留、同章确定影响 supported；事实不能定位时为 unlocated，伪模型确定影响被过滤；章节/来源版本不一致和来源新于项目版本均排除；既有回归的跨项目来源测试通过 |
| 章节绑定 | 章 A 只引章 B，无论 A 原文是否已召回，均 insufficient；章 B 引自身原文仍 supported |

对应修补入口：`engine.py:177-182` 的 `_aggregate_attempt_failure` 与 `:322-325` 的连续性异常分支；`provider.py:27-37` 的异常默认完整性标记、`:405-411` 的派发状态传播。未修改业务代码或既有测试。

## 证据清单

- `probe-results.json`：原首轮 13 / 13。
- `chapter-evidence-results.json`：章节绑定 4 / 4。
- `supplement-final-results.json`：第二轮补充路径 14 / 14，其中 `public_metrics_repair-timeouts`、`public_metrics_repair-retry-denied` 为本轮关键反例复验。
- `failure-boundary-control-results.json`：派发前拒绝、已知/未知无效 JSON 控制与网络断言，4 / 4。
- `regression-log.txt`、`regression-summary.json`：原样运行 `tests.test_legacy_dispatch_quota` 与 `tests.test_v130_character_alias_change_impact`，17 / 17。
- 各脚本 stdout/stderr 独立保存于同目录的 `*-console.txt`；本轮使用第二轮已纠正的探针，没有覆盖前两轮结果。
- `git diff --check` 通过。运行前后 5 个业务文件、2 个既有测试文件、2 个交接/计划文件的 SHA-256 全部相同，见 `sha256-before.json`、`sha256-after.json`、`sha256-comparison.json`。

主要源码 SHA-256：

```text
engine.py      df9b2a19b07744b318743802679c22f67a49af13a67275cf81f74c0d06891ea4
provider.py    e415c36cc08114492e7ac5305ef67db89eb58f1a06aa01a0a19c9c89b91b7380
stage13.py     957c219bb3f8036e421c63ba7c204ed1767d2d334a39a08aa958f5119cfd9500
v2_database.py 9f0b8c2b512f2d69f03cbc7193d83d9681fe42fe3ade51a7fcc4ad494fdba965
operations.py  ea9d4628417a4056f187da25635c2deedb9e501faad648202d5be7570dcd405c
```

## request_cap 配置范围：只做静态检查

`provider.py:324` 的默认 `request_cap=None`，公开应用入口 `main.py:298` 直接构造默认 Provider，公开持久额度使用 `ProviderDispatchDenied`，属于上面的实际复验范围。

源码中设置 request_cap 的三个真实验证工具都同时禁用内部重试：

- `tools/run_stage11l_real_100k.py:173-174`：max_retries=0，再设 request_cap。
- `tools/run_stage11m_real_300k.py:304-305`：max_retries=0，再设 request_cap。
- `tools/run_stage11m_capacity_repair_v2.py:35-36`：max_retries=0，再设 request_cap。

因此“先超时，然后在同一次 evaluate 重试时命中 request_cap”的组合并非当前公开入口或这些工具的现有配置路径。源码另有一个未实测的组合边界：如果后续把 cap 与 retries>0 一起配置，`provider.py:360-361` 直接抛出的 ProviderFailure 默认 usage_unknown=False，没有带上前一次超时状态。该静态边界不作为当前公开链路阻断项，也不宣称已验证正确；没有为此运行真实工具或新增穷举探针。后续启用该组合前应另行修补和离线验证。

## 隔离与限制

真实 Provider HTTP、外部请求、SMTP 均为 0；只使用 fake transport、合成内容、全新独立 SQLite 根目录和 `Stage13Settings.for_test()`。DeepSeekProvider 用 object.__new__ 和固定假值配置，未读取真实密钥或 `.env`。仅本证据目录新增文件及合成测试数据；业务源码、既有测试、前两轮证据未修改。没有启动外部服务、读取原数据库、执行真实 Stage11 工具、提交、推送或部署。

observed_response_* 仍只保留于内存结果/异常对象，没有新增逐次响应持久化。完整 Run 为未知时不把局部已知响应当作完整总量；这是本轮交接已有的明确限制。

## 复跑

为保留证据，先将以下脚本复制到 `docs/legacy-gap-evidence/` 下全新同层目录，再在工作树根目录使用 `.venv/Scripts/python.exe -B <新目录>/<脚本>` 执行：

```text
probe.py
chapter-evidence-probe.py
supplement-final-probe.py
failure-boundary-controls.py
run-regressions.py
```

脚本按自身目录创建合成数据库与结果；部分结果采用独占写入，复跑不得覆盖已保留证据。PowerShell 可先设置 `PYTHONIOENCODING=utf-8` 以便读取中文输出。
