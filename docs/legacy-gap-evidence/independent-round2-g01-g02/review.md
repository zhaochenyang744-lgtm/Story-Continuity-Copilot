# G01/G02 第二轮独立复验

日期：2026-09-26。工作树：`story-continuity-legacy-gap-repair`；基线：`39de855c005d77f7f02a132f5e807a0c1c476b7b`。本轮审查的是未提交返修版本，文件 SHA-256 见下表及 JSON。

**结论：首轮所有具体反例已修复，但 G01/G02 完整验收仍未通过。** 新增的少量一般化与正控制探针发现：同日多时点仍可形成无根据确定冲突；无关叙述词会误降级真实冲突；逐项引用错配仍被整体标成 supported。下面明确区分首轮修复与本轮剩余问题。

## 已通过的复验

| 范围 | 实际结果 |
|---|---|
| 首轮 G01 六个反例/控制组 | 全部拒绝原错误确定冲突；重复 fake 输出后均降为 `insufficient_evidence`，不再首轮保留误判 |
| G01 正控制：同相对日、同完整日期、同序数日的直接知情矛盾 | 三组均首轮保留 `confirmed_conflict`，证明实现并非一律降级 |
| G02 首轮 299 字单句/240 字裁剪 | 正确为 `partial / draft_claim_truncated`；返回源起止、实际送入尾点和截断标志 |
| G02 1980 字正文控制组 | 正确为 partial，分别标未引用、未选入和正文截断；未选入数量为 172 |
| G02 30 字三句全部入选、无任何截断 | 模型仅给历史事实或仅引首句时，均为 partial，明确第二、三条未引用 ID |
| G02 正控制：每条分项逐字引用其自己的草稿来源 | 正确为 `covered / supported`，无遗漏理由 |
| G02 三个 API 流程的身份/版本控制 | 不在绑定集合内的外来草稿 ID 均被拒绝；保存新正文后旧简报均 `is_stale=true` |
| 相关既有/新增测试独立复跑 | `32 passed, 1 warning, 6 subtests passed in 23.97s`；警告为既有 Starlette/AnyIO 弃用提示 |

首轮探针和补充探针均以副本在本目录运行，原 `independent-g01-g02/` 的脚本、结果、首次失败与报告未修改。

## 仍需处理的问题

### R2-1 / P1：同一天有多个钟点时，仍把明确后知事件当作确定冲突

位置：`backend/app/engine.py:137–145`、`:116–120`、`:360`。

最小复现：

- 当前主张：`今日十九点，秦渡已经知道信使身份。`
- 引用原文：`今日十八点，秦渡还不知道信使身份，直到十九点才从密信获知身份。`
- 模型双方锚：`十九点`；错误地要求 `confirmed_conflict / explicit_overlap`。

预期：引用明确说明十八点不知、十九点获知，与当前主张相容。至少应拒绝确定冲突并降为证据不足，不能只因共享十九点就认定证据支持矛盾。

实际：`validate` 接受；`execute` 仅调用一次 fake Provider，就返回 `completed`、`confirmed_conflict`、`sufficient`。当前 `days()` 只检查一天/多天，完整时间重叠函数又接受时间集合有交集，未把同日多个钟点对应的状态区分开。交接中“同句多时点均保守降级”的表述因此仍超出实现证据。

证据：`controls-and-scope-results.json` → `g01.compatible_same_day_two_clock_transition`。这延续既定 G01 后知范围，不要求新增叙事时间轴。

### R2-2 / P2：整段来源出现无关“回忆”等字样，会降级另一句已有充分证据的真实冲突

位置：`backend/app/engine.py:130–131`。

最小复现：

- 当前主张：`今日十八点，秦渡已经知道信使身份。`
- 来源片段：`今日十八点，秦渡还不知道信使身份。另一间屋内，陈澈回忆童年的航海经历。`
- 模型双方锚：`十八点`。

预期：第一句对同一人物、同一天、同一时刻直接陈述不知情，应保留其与当前主张的确定冲突；另一人物的独立回忆句不改变第一句的叙述范围。

实际：`validate` 拒绝；`execute` 二次 fake 调用后降为证据不足。新守卫对整个 `evidence_text` 搜索框架词，一处命中就否决整个片段，而现有检索片段本来可以含多句。这是本轮修补引入的保守性回归；应将叙述限定绑定到实际支撑冲突的句子/范围，或明确给出该情形的不可判断原因，不将无关词视为目标句限定。

证据：`controls-and-scope-results.json` → `g01.positive_conflict_unrelated_recollection_in_source`。

### R2-3 / P2：逐项引用错配未被核对，“所有 ID 已引用”仍被当成整体 supported

位置：`backend/app/engine.py:479–485`、`:495–520`。

最小复现：输入仍是无截断的三句短草稿；模型分项内容全部来自输入，但将引用循环错配：

| 分项文字 | 该分项唯一引用实际写了什么 |
|---|---|
| 林默走进北门。 | 银钥匙已经交给陈澈。 |
| 银钥匙已经交给陈澈。 | 她此时已经知道弟弟还活着。 |
| 她此时已经知道弟弟还活着。 | 林默走进北门。 |

预期：每条分项必须受自身所列引用支持；至少不能把这种错配结果标作 supported。草稿引用 ID 完整与内容/引用正确性需要分开记录。

实际：三个 source ID 的集合完整，因此返回 `covered / supported / reasons=[]`，所有错配分项原样保留。新 UI 使用“全部选入主张已引用”描述 ID 集合，较原表述准确；但该状态仍不证明正文分项被其引用支持。摘要由分项重组也只继承了分项的错误配对。此项是既有引用校验边界的剩余问题，不声称由本轮新引入。

证据：`controls-and-scope-results.json` → `g02.all_ids_cited_but_each_item_uses_wrong_source`。同材料引用正确的正控制为 supported，方便区分“完整引用集合”和“逐项支持”。精确字符串匹配只用作本探针证据，并不建议用“只允许原文相等”代替一般的合理改写支持判断。

## 文件指纹

本轮开始和结束哈希一致，详见 `source-hashes-before.json`、`source-hashes-after.json`。

| 文件 | SHA-256 |
|---|---|
| `backend/app/engine.py` | `F79D2494A7BFE632DA29C5EF9C2A7113C12B210E90B459DF3E1EE773DACCF863` |
| `backend/app/provider.py` | `5138BC1563D4670C450D08D219CC9231BE1CFE34ED165CADBA39DE24B37416D1` |
| `backend/app/v2_database.py` | `9F0B8C2B512F2D69F03CBC7193D83D9681FE42FE3ADE51A7FCC4AD494FDBA965` |
| `backend/tests/test_v140_real_ai_contract_repairs.py` | `31FC09A04FFABAEDB112C4EDBDE45955D599BDC93635FED598553486F77201CB` |
| `backend/tests/test_v130_writing_analysis.py` | `2770182D22A3BB37B0EBF1BFD38C85B704A19F9012CD07F93F2273781D9F78D6` |
| `frontend/app/components/Workbench.tsx` | `04644CCAB961F53E26306906A862E70D785621980530B96CF8F9E87E1388E58A` |
| `frontend/app/model.ts` | `8559FE54FC3A6D5E909C4CDE2455D8A24723BBF07EAD313F9E3600886E088A53` |

## 可复跑命令与边界

以下记录本轮实际运行方式，工作目录为当前修补工作树。再次复跑应先把四份脚本复制到新的同级证据目录，并相应替换目录名，以保留本轮结果。

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'backend'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
& '.\.venv\Scripts\python.exe' 'docs\legacy-gap-evidence\independent-round2-g01-g02\probe.py'
& '.\.venv\Scripts\python.exe' 'docs\legacy-gap-evidence\independent-round2-g01-g02\coverage-semantics-probe.py'
& '.\.venv\Scripts\python.exe' 'docs\legacy-gap-evidence\independent-round2-g01-g02\controls-and-scope-probe.py'
& '.\.venv\Scripts\python.exe' 'docs\legacy-gap-evidence\independent-round2-g01-g02\run_targeted_tests.py'
```

执行完整探针使用进程内 fake Provider、TestClient 与新的临时数据库，阻止真实 HTTP transport、SMTP 及外部 socket；Windows asyncio 内部 socketpair 所需回环连接被允许。纯校验探针的 Provider 一旦被调用就失败。没有读取 `.env`、原运行库，未改业务代码、既有测试或首轮原始证据；没有提交、推送、部署或 Agent 开发。

本轮未调用真实模型，无法说明提示词修改后的首答准确率；也未重新做浏览器视觉验收。这里的“通过/失败”只针对明确列出的离线产品行为与源版本/引用控制，不代替用户验收、真实 AI 验证或上线 Gate。
