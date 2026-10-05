# G03 V2 fixture 与业务请求独立验收

日期：2026-09-26。对象：`evaluation/current_flash_v2`、运行 `flash-v2-20260926-01`。范围：全部 8 例的冻结/请求 hash，G03 四例的合成语料、实际请求、Memory、章节引用及合成数据库一致性。开放文本的逐项语义由主控另行审阅，本报告的引用绑定通过不代表语义正确。

## 结论

**请求层 fixture 与证据契约可验证，完整双章节正文一致性未通过。** 四例实际发送的 Memory、SourceSpan、目标、空草稿及干扰章节均符合新 case 定义，8 例业务请求与输出关联 hash 正确。现有结果可以保留为这些具体 SourceSpan 输入下的模型/产品观察，但不能无条件称为“完整两章节正文与来源一致的 fixture”或端到端来源闭环验收。

发现 1 项来源一致性问题和 1 项前置检查遗漏。未发现本轮真实 Memory 字段错误、干扰章未进入请求或最终章节 ID 错配；未调用 Provider，也未修改任何实施文件、留存结果或数据库。

## F1：章节正文没有跟随 SourceSpan 更新

位置：`evaluation/current_flash_v2/run.py:320-323`。初始化 loader 为章节正文和 SourceSpan 写入相同初始文本（`evaluation/v2_fixture_loader.py:208-215`），随后 G03 每例只更新 `v2_source_spans.body`，没有同步 `v2_chapters.body`。两份内容都仍为 `source_revision=1`。

依据 `workspace-manifest.json` 中精确路径，以 SQLite `mode=ro&immutable=1` 打开四份 G03 合成 DB，确认：

| 案例 | 实际 SourceSpan / 模型输入 | 留存 v2_chapters.body | 结论 |
|---|---|---|---|
| short | 第 1 章为 20 字短正文，第 2 章无保管事实 | 相同 | 一致 |
| deep | 第 1 章 1510 字，目标事实位于下标 1100 | 第 1 章仍为原 20 字短正文 | 深处事实不在实际章节正文深处 |
| absent | 第 1 章 26 字，明确无保管者记载 | 第 1 章仍含“星钥始终由乔霁保管。” | 章节正文与缺失来源条件不一致 |
| other_chapter | 第 1 章深处目标；第 2 章 31 字触碰/交还事实 | 第 1 章仍为短文；第 2 章仍说“没有星钥保管事实” | 两章均不一致 |

最小只读复核 SQL：

```sql
SELECT c.id, c.body AS chapter_body, s.body AS span_body,
       c.source_revision AS chapter_revision, s.source_revision AS span_revision
FROM v2_chapters c JOIN v2_source_spans s ON s.chapter_id=c.id;
```

这不是模型漏看材料：业务快照忠实记录了更新后的 SourceSpan，预期目标片段和干扰文本确实进入请求。问题在合成 runtime 的完整章节层没有同步，所以“absent / deep / other”只能按实际 SourceSpan 输入解释。此项阻止完整章节一致性验收，不否定已留存调用和响应的真实性。后续若制作完整一致 fixture，应在新身份/新目录同时建立对应章节与 SourceSpan 并检查来源关系；不得原地修写本次证据。这里没有为该建议发起新真实调用。

## F2：前置条件没有检查 memory_type

位置：`evaluation/current_flash_v2/run.py:240-241`。检查了 Memory 的 subject、predicate、value、source_span_id，但遗漏 `memory_type`。独立纯离线反例只把已保存请求的 `memory_type` 改为 `not_a_memory_type`，四例均仍通过 `assert_business_input`。

本轮真实快照及四份 DB 中类型都为正确的 `dynamic_state`，因此不是本次数据失败；这是后续复用前置校验时的防回归遗漏。当前实现不能宣称 preflight 已完整检查全部 Memory 字段。独立验收另行核对了完整字段，详见结果 JSON。

## 已通过的具体核查

- 四例请求均含且仅含确定的 2 个章节和 2 个 SourceSpan；Memory 仅 1 条：`dynamic_state / 星钥 / holder / 星钥始终由乔霁保管。`，绑定第 1 章来源。数据库和实际业务快照逐字段一致。
- proposal 始终以该 Memory 为目标，改为由沈砚保管；草稿为空，draft_claims 为空，避免当前草稿 ID 冒充章节目标。
- short：20 字完整输入，无截断，`selected`；deep 和 other：原文 1510 字，目标事实在下标 1100，包含目标事实的 502 字摘录（500 正文字符加首尾省略号）实际入请求，截断/原长/摘录长元数据吻合。
- absent：实际发送的第 1 章 SourceSpan 为 26 字，确实不含目标事实；`unlocated`，最终 `insufficient` 且 items 为空。其完整章正文不一致问题见 F1。
- other：第 2 章 31 字干扰文本与 case 定义逐字相同，实际在 request 中；不是只列章节 ID。
- 四例首答和最终保留的每个 `area=chapter` 项，均至少有一个 SourceSpan 引用与自身 `target_id` 对应章节一致。没有无效 draft-as-chapter target。这里只证明 ID/章节归属，不证明每个 impact 自然语言结论充分受支持。
- 4 例实际快照都通过现有 `assert_business_input`。独立诊断仅从 AST 抽取两份纯函数，没有导入 runner 环境设置或构造 Provider。
- 8 例 input_sha256、完整 business_request_sha256、output_schema_sha256 与 model_outputs 关联 hash 全部重算一致。
- frozen-inputs 的 15 份文件 hash 全部与当前文件一致，包含此前 V1 未单列的 `backend/app/seed_data.py`；start.json 引用的冻结清单 hash 也一致。新 corpus/cases/runner 共同足以重建本轮发送的合成 SourceSpan 输入。不能由 hash 本身推导章节层已正确构造，F1 即是可重复的构造遗漏。
- workspace-manifest 中 8 份合成 DB 的路径、文件大小、SHA-256 全部匹配；仅打开 4 份 G03 DB，没有打开 G02 DB 内容或其它数据库。全部源码/输入/结果和 8 份 DB 的前后 hash 相同。

## 证据与运行范围

- `fixture-diagnose.py`：独立脚本，网络和 SMTP 禁用，数据库连接必须属于 manifest 中四份 G03 精确只读 URI 白名单。
- `fixture-results.json`：逐案例结果、章节/SourceSpan 差异、完整前后文件 hash 和数据库 hash。8 例记录校验、四例请求条件和全部章节引用绑定断言通过；来源差异及 memory_type 漏检作为发现保留，没有被改成通过。
- 初次运行本人脚本的 sqlite 包装器参数名 `uri` 与 `uri=True` 冲突，尚未打开数据库、未写结果；仅修正本人脚本参数名后完成。本项不属于产品缺陷。
- 网络/SMTP/Provider 调用 0；精确白名单内只读数据库连接 4；没有读取 `.env`、真实业务 DB 或受限 held-out，没有改业务逻辑、重跑 V8、运行旧 probe、提交或部署。

复跑时将 `fixture-diagnose.py` 复制到 `evaluation/current_flash_v2/` 下新的同层证据目录，再执行 `.venv/Scripts/python.exe -B <新目录>/fixture-diagnose.py`。脚本以独占方式写结果，不能覆盖本次输出；原 DB 若已变更会在读取前因 hash 不符停止。
