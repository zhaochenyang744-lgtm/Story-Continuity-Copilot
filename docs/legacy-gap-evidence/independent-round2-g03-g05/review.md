# G03 / G05 第二轮独立复验

日期：2026-09-26。工作树 `story-continuity-legacy-gap-repair`，HEAD `39de855c005d77f7f02a132f5e807a0c1c476b7b`，评审对象为当前未提交修补。仅审查 G03/G05，未扩展至 Agent。

结论：G03 本轮有界离线条件通过；G05 首轮“超时后成功”问题已修复，但“首次响应成功，后续契约修复派发超时并最终失败”的完整 Run 用量仍有 P2 问题，因此 G05 尚不能完整关闭。本结论不等于真实模型效果、用户验收或发布 Gate。

## 仍存在的问题

### P2：修复请求最终失败时，首次已知用量仍被当成完整 Run

位置：`backend/app/engine.py:305`、`:308`。这两条异常路径只汇总既有 `results`；发生超时、或超时后的重试被额度拒绝时，没有把已派发但用量未知的请求纳入完整性判断。正常返回的 `ProviderResult` 虽已能标记未知，但最终抛异常时没有返回该结果。

最小流程：

1. 第一次 HTTP 返回有效 JSON、旧契约 Issue，触发既有连续性契约修复；响应的已知用量为 input 11、output 7、cost 0.2。
2. 修复调用的第一次 HTTP 抛 `httpx.ReadTimeout`，模拟请求发出但响应丢失。
3. 变体 A：修复重试也超时，3 次派发/3 次持久计数，Run 正确进入 `timed_out/provider_timeout`。
4. 变体 B：总额度为 2，修复重试在发出前被拒绝，2 次派发/2 次持久计数，Run 正确进入 `failed/provider_attempt_quota_exceeded`。
5. 两种变体的 SQLite Run 却都保存 11 / 7 / 0.2；`operations.usage` 三项均显示 `available`、`unknown_run_count=0`、`all_run_sum` 为首次响应数字。至少一次已发出请求的用量未知，完整 Run 应标记未知。

证据：`supplement-final-results.json` 的 `public_metrics_repair-timeouts` 和 `public_metrics_repair-retry-denied`。持久化入口为 `v2_database.py:3298`，运维完整性判断为 `operations.py:275-280`。请求计数与具体异常码在这两例中均正确。

修复边界：需要传播“该失败调用是否已有用量未知的实际派发”。不能将所有配额异常一律改成未知：若仅完成第一次已知响应，第二次 evaluate 在发出任何 HTTP 前就被额度拒绝，整个 Run 的已发生用量仍全部已知。本轮单独验证了该正控，现行为正确。

## 已验证修复与正控

| 范围 | 当前独立结果 |
|---|---|
| 低排名目标 Memory 与直接原文 | 目标排第一，维持原 8 条 Memory / 4 条来源预算；原文第 1100 字后的目标事实实际进入 500 字窗口，含省略号总长 502 |
| 来源覆盖状态 | 原文长度、实际摘录长度、截断状态准确；短原文完整保留且不标截断；目标事实无法逐字定位时为 `unlocated`，即使伪模型输出确定影响也过滤为 insufficient/空 items |
| 来源版本和身份 | 章节/SourceSpan 版本不一致、SourceSpan 新于项目版本均排除；现有回归覆盖跨项目直接来源；目标章 A 只引用 B，无论 A 原文是否已召回，均 insufficient；B 引用自身原文正常 supported |
| HTTP 额度 | 超时后成功实际 2 次派发/2 次计数；剩余 1 次额度时第二次派发前被拒；4 并发请求共享额度 1 时只有 1 次 post/1 次成功 |
| 首次超时、第二次成功 | 整个 ProviderResult / SQLite Run 的 tokens、费用均未知；operations 三项 unknown；后一次响应 11 / 7 / 0.2 保留于 `observed_response_*` |
| 正常成功 | 单次 HTTP 的完整 Run 用量仍为 11 / 7 / 0.2，operations available，未被过度置空 |
| 无效 JSON | 单次无效 JSON 为 failed/invalid_json，用量保留；超时后无效 JSON 为完整用量未知，后次响应 observation 保留；语法无效 JSON 现路径终止，不虚称已自动修复成功 |
| 契约修复 | 两次均有响应的成功修复为 22 / 14 / 0.4；修复先超时再成功，3 次派发且完整用量 unknown；修复无效 JSON 的已知总和正常，修复先超时再无效 JSON 的总量 unknown |
| 失败基本语义 | 首次单调用额度拒绝、两次超时、连接失败维持正确 Run 状态/错误码；没有写入 Issue，未知费用不计为零 |

已知限制按交接文件保留：`observed_response_*` 只存在于内存 ProviderResult/异常对象，未新增逐响应持久化；完整 Run 为未知时，不将这些局部已知数字冒充持久总量。没有验证语义蕴含、真实 Provider 或全书检索效果。

## 结果与证据

- 原首轮独立探针复制复跑：`probe-results.json`，13 / 13。
- 原章节绑定补探复制复跑：`chapter-evidence-results.json`，4 / 4。
- 新增正控和异常路径：`supplement-final-results.json`，12 / 14；2 个失败对应上述同一 P2。
- 失败边界额外控制：`failure-boundary-control-results.json`，4 / 4。
- 独立断言合计 35 项，33 通过、2 失败，包含网络禁用断言；不是模型质量样本数。
- 现有定向回归：`regression-log.txt` / `regression-summary.json`，16 tests、0 failures、0 errors、0 skips。
- `git diff --check` 通过。完整 SHA-256 清单见 `reviewed-sha256.json`，其中 engine=`f79d2494a7bfe632da29c5ef9c2a7113c12b210e90b459df3e1ee773daccf863`；provider=`5138bc1563d4670c450d08d219cc9231be1cfe34ed165cadba39de24b37416d1`；v2_database=`9f0b8c2b512f2d69f03cbc7193d83d9681fe42fe3ade51a7fcc4ad494fdba965`。与本轮回归哈希一致。

探针自身的失败也已保留：最初 `supplement-probe.py` 错把实际只有一个 user message 的 prompt 当成 `messages[1]`，并误以为原文条目键为 span_id；中间 `supplement-verified-probe.py` 只纠正 id 键，仍受 message 索引影响。这两次导致 fake transport 内部 IndexError，Run 的 internal_run_error 不是产品发现。随后依据当前源码纠正为 `messages[0]` 和 `source['id']`，单独生成 `supplement-final-probe.py` 与最终证据，没有覆盖前两次文件或首轮证据。

## 隔离与复跑

所有业务代码只读。写入仅在本目录，包括新注册的合成测试账号、新建合成 SQLite 数据库、脚本和结果。应用创建显式使用 `Stage13Settings.for_test()`；DeepSeekProvider 通过 `object.__new__` 和固定假配置创建，绕过读取环境配置的构造函数；HTTP transport 完全替换。未读取 `.env`、真实数据库或密钥。真实 Provider、外部网络、SMTP 调用均为 0。网络守卫仅允许 Windows asyncio 内部 socketpair 所需 loopback；禁止外部 socket 与 SMTP。未提交、推送、部署或启动浏览器/服务。

在工作树根目录，使用 `.venv/Scripts/python.exe -B` 依次运行以下脚本：

```text
docs/legacy-gap-evidence/independent-round2-g03-g05/probe.py
docs/legacy-gap-evidence/independent-round2-g03-g05/chapter-evidence-probe.py
docs/legacy-gap-evidence/independent-round2-g03-g05/supplement-final-probe.py
docs/legacy-gap-evidence/independent-round2-g03-g05/failure-boundary-controls.py
docs/legacy-gap-evidence/independent-round2-g03-g05/run-regressions.py
```

为保留本轮证据，应先把这些脚本复制到 `docs/legacy-gap-evidence/` 下另一个全新同层目录，再从新目录执行；脚本按自身目录写入，部分结果采用独占写入会拒绝覆盖。真实外部调用仍须保持禁用。
