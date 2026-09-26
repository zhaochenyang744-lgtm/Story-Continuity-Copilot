# G01/G02 第三轮独立复验

日期：2026-09-26。工作树：`story-continuity-legacy-gap-repair`；基线：`39de855c005d77f7f02a132f5e807a0c1c476b7b`。按实施者明确冻结的未提交版本进行评审，7 个相关文件的前后 SHA-256 一致。

**结论：本次指定的 G01/G02 修补范围，独立离线复验通过。** 首轮与第二轮已报告的具体失败、相应正控制，以及本轮约定的直接复制组合边界均达到预期；没有在这次有界复验中发现新的阻断问题。此结论不是任意文本语义准确率、真实模型首答效果、用户验收或发布 Gate。

## 结果矩阵

| 检查 | 结果与证据 |
|---|---|
| 首轮 G01 六组：后知、完整相对日、截短时间锚、序数日、明确谎言、回忆 | 全部拒绝错误的确定冲突；两次 fake 输出后降为 `insufficient_evidence`。`probe-results.json` 的 `g01` |
| R2-1：同日十八点未知、十九点获知，对十九点已知 | 不再因共享十九点而接受确定冲突；现在保守降级。`controls-and-scope-results.json` → `compatible_same_day_two_clock_transition` |
| R2-2：目标句有真实矛盾，来源另一句是另一人物的无关回忆 | 目标句矛盾得到保留，首轮返回 `confirmed_conflict`。`positive_conflict_unrelated_recollection_in_source` |
| G01 同日、同完整日期、同序数日三个直接矛盾正控制 | 三组均首轮保留 `confirmed_conflict`，没有一律降级。`controls-and-scope-results.json` |
| G02 299 字单句裁成 240 字 | `partial / draft_claim_truncated`，源范围与实际送入末点准确。`probe-results.json` |
| G02 1980 字正文 | partial；分别说明未引用、未选入、正文摘录截断，未选入数量 172。`probe-results.json` |
| G02 三句全部入选且完全无截断，仅历史结果或仅首句引用 | 两种情况均 partial，明确列出第二、三条未引用 ID。`coverage-semantics-results.json` |
| R2-3：三条原句循环错配引用 | 三项均移除，披露 `discarded_item_indices=[0,1,2]` 及 `draft_item_citation_mismatch`；状态 partial。模型原错配未被静默改写成正确引用。`controls-and-scope-results.json` |
| 三条原句分别正确引用的正控制 | `covered / supported`，无丢弃项及遗漏理由。`controls-and-scope-results.json` |
| 合并复制两条不同原句、却仅引用第三条 | 错配原分项被移除，披露索引 `[0]`，状态 partial。`composition-results.json` |
| 合并复制两条原句，分别附对应引用 | 原分项保留、无错配标记；第三条未引用主张仍如实使整体 partial。`composition-results.json` |
| 相同原句绑定两个 ID，仅引用其中一个有效 ID | 原分项保留、不误记引用错配；另一个未引用 ID 仍列入未覆盖范围，整体 partial。`composition-results.json` |
| 一条正常改写控制 | “林默从北门进入。”得到保留，没有被直接复制守卫错误剔除；不据此宣称一般改写语义已获验证。`composition-results.json` |
| 三个 API 流程的来源/版本控制 | 外来草稿主张 ID 均拒绝；再次保存正文后旧简报均 `is_stale=true`。`probe-results.json` |

G01 共 11 个独立材料执行结果均符合各自预期。G02 在原探针、覆盖探针、引用控制和组合探针中共 11 个场景达到各自预期；组合脚本的 9 条具体断言全部通过。上述数量只是本轮材料数，不是模型正确率。

独立复跑两份相关测试：

```text
33 passed, 1 warning, 8 subtests passed in 15.35s
```

文件为 `backend/tests/test_v140_real_ai_contract_repairs.py` 与 `backend/tests/test_v130_writing_analysis.py`，完整日志在 `run_targeted_tests-console.txt`。唯一警告是既有 Starlette/AnyIO 弃用提示。

## 实现核对与通过边界

- G01 `engine.py:128–150` 先限定包含模型时间锚的唯一绑定句，再处理显式叙述限定和句内多钟点。无唯一句、无法证明时间重叠时采取保守处理。原无关回忆句回归已经用相反预期的正控制核实。
- G02 `engine.py:503–509` 按被直接复制的原句文本分组检查引用；同文本多个 ID 允许任一相符 ID，因此没有为了拦截错配而拒绝重复原句的合法引用。`engine.py:525–548` 保留丢弃序号、原因及部分状态。
- `covered` 的准确口径是当前选入主张的引用集合完整，且没有已检测到的截断、遗漏或直接复制错配。它**不证明任意改写、推理或每一种非逐字分项已经通过语义蕴含判断**。本次只验证可确定的直接复制错配、两句组合、重复文本引用和一个正常改写保留控制。
- G01 仍是有界格式/范围守卫，不是完整故事时间理解引擎。正控制证明这次没有一律降级，但不能由这 11 个材料推断所有叙述方式都已覆盖。
- 所有安全降级及错误项丢弃均为产品处理；探针 JSON 仍保留原 fake Provider 错误输出，不能报告为原模型“零错误”。

前端 `Workbench.tsx:4147` 的错配移除数量和 `model.ts` 的字段已只读核对；本子审查未重新执行浏览器渲染，浏览器验收由主控另行完成。

## 评审版本指纹

`source-hashes-before.json` 与 `source-hashes-after.json` 全部一致：

| 文件 | SHA-256 |
|---|---|
| `backend/app/engine.py` | `DF9B2A19B07744B318743802679C22F67A49AF13A67275CF81F74C0D06891EA4` |
| `backend/app/provider.py` | `E415C36CC08114492E7AC5305EF67DB89EB58F1A06AA01A0A19C9C89B91B7380` |
| `backend/app/v2_database.py` | `9F0B8C2B512F2D69F03CBC7193D83D9681FE42FE3ADE51A7FCC4AD494FDBA965` |
| `backend/tests/test_v140_real_ai_contract_repairs.py` | `3BC5481CD33EC589620061F885FE5B516529C2DD2EC8E42C5CCB88CB0E740398` |
| `backend/tests/test_v130_writing_analysis.py` | `2770182D22A3BB37B0EBF1BFD38C85B704A19F9012CD07F93F2273781D9F78D6` |
| `frontend/app/components/Workbench.tsx` | `BF76619E7AE5D3652A99D70FA5B440CAA8A38EA1235814180014DA1116823680` |
| `frontend/app/model.ts` | `D1999849318EAF94DC50F1321F37675BBF4CC2AD6AEB9C8E6C15AC7DF0DD9E1B` |

## 可复跑方式

在当前修补工作树根目录执行。再次复验时应先将五份脚本复制到新的同级证据目录，再替换下面目录名，避免覆盖第三轮结果。

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'backend'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
& '.\.venv\Scripts\python.exe' 'docs\legacy-gap-evidence\independent-round3-g01-g02\probe.py'
& '.\.venv\Scripts\python.exe' 'docs\legacy-gap-evidence\independent-round3-g01-g02\coverage-semantics-probe.py'
& '.\.venv\Scripts\python.exe' 'docs\legacy-gap-evidence\independent-round3-g01-g02\controls-and-scope-probe.py'
& '.\.venv\Scripts\python.exe' 'docs\legacy-gap-evidence\independent-round3-g01-g02\composition-probe.py'
& '.\.venv\Scripts\python.exe' 'docs\legacy-gap-evidence\independent-round3-g01-g02\run_targeted_tests.py'
```

所有前两轮证据保持原样；本轮只写 `independent-round3-g01-g02/`。完整执行探针使用 fake Provider、TestClient 和新临时数据库，阻止真实 HTTP transport、SMTP 和外部 socket，Windows asyncio 内部回环 socketpair 被允许。纯校验探针的 Provider 若被调用即失败。未读 `.env`、原运行库，未改业务实现或既有测试，未提交、推送、部署或开展 Agent。

真实 Provider 首答效果、泛化召回和误报、真实作者研究及生产恢复均未在本子审查中验证，继续保留原有待验边界。
