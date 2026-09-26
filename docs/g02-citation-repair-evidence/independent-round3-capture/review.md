# V2 比较集：独立 capture 与 API 链复验

日期：2026-09-26。范围：`evaluation/current_contract_compare_v2` 的冻结材料、24 例实际请求、26 份保存 API 结果，以及 6 次全新合成数据库中的固定答复 API 复验。

结论：当前交付的输入与答复链完整性检查通过；6 次独立产品 API 控制通过。仍有一项历史证据限制：首轮 V2「24 次完成、仅 8 次结构通过」的逐例原始结果在本次有界检索范围内未找到，不能确认其保存完整。此报告不评判 gold 语义或 scorer 充分性，不是实模型效果报告，也不是发布或用户验收。

## 1. 本人实际执行与记录核对

实际执行了新脚本 `capture-probe.py`，退出码 0，约 8.7 秒，结果为：24 个 capture 身份、26 个保存 API 身份、6 个新合成 API run，检查错误 0，真实 Provider 调用 0。脚本未调用交付的 scorer，也未执行原 `preflight.py` / `api_score_probe.py` 入口。

对实施者保存的 24/26 结果进行了独立 JSON 与冻结正文比对；历史生成过程不能仅凭 JSON 追溯为本人的实际执行。历史记录的 Provider/模型标签分别是 `compare-v2-scripted-offline` / `compare-v2-no-model`，源码提供固定答复（`api_score_probe.py:54-71`），记录自报真实 Provider 调用 0。本次新执行则注入自己的 FixedProvider，设置 `SCC_DISABLE_DEFAULT_APP=1`，使用显式测试配置，并禁止 socket 外连；唯一允许的是 Windows 标准库 `_fallback_socketpair` 的内部回环连接。

## 2. 24 例输入及 26 份保存结果

以下逐例检查均未发现错误，详细机器诊断在 `saved-record-audit.json`：

- 24 个 case 与实际 capture 身份集合精确相等；26 份 API 结果恰好为 24 个 gold 身份加 2 个允许的 state_change 身份，无缺失或重复。
- 每份实际请求的完整 draft body、单个 claim text 与该 case 的 target_draft 相等；draft ID 和 revision=2 正确。
- 已选 SourceSpan 均能定位到本 corpus；chapter ID、标签正确，实际请求 body 与 prompt_excerpt 均等于完整冻结章节正文。声明的 expected / minimum-sufficient / recommended 来源哈希与 corpus 正文 UTF-8 SHA-256 相等；必需来源均在实际选择中。
- 已选 Memory 的 id、memory_type、subject、predicate、value、source_span_id 六个字段与冻结 corpus 一致。未见旧 does_not_know seed 仅改主语/值却遗留谓词的问题。
- 捕获的 business_selected 与实际请求来源相符，必需来源包含在记录的 retrieval_returned 中。此项是保存记录内部一致性；全部 24 例的原始 SQL 检索过程未重演。
- 26 份 API 请求与对应 preflight 请求整体一致，仅忽略每次运行生成的 claim.id；不是只核对短摘要或标签。
- 每份结果均独立保存 raw_first、显式为 null 的 raw_repair 与 final_product；product 别名与 final_product 相等。全部为 completed，raw/final Issue 数量、类别、性质、引用 span、Memory 关联及证据充分性一致，contract_normalization_count=0。
- raw/final 的 claim ID 均属于该次实际请求；final claim_text 相符。原始 temporal_basis 保存在 raw_first；本次未要求 final Issue 增设该字段。
- 最终 Evidence 的全文摘录/上下文、chapter ID/序号/标题与 corpus 对应；证据链引用能解析到该 Issue 的 Evidence。source_memory_version=1；Evidence.source_revision 与 run.source_revision=2 相等。

版本边界：请求中的已选来源不含单独的 source_revision 字段，因此这里只确认最终运行版本绑定，以及冻结来源正文与实际输入一致，不把它扩展为完整历史版本链已验收。26 份 raw_repair 都是 null，只说明本批未进入修复，不能作为修复分支保真性的覆盖。

## 3. 6 次新合成数据库 API 复验

每例创建全新 fixture；直接在本人的新数据库中核对章节/SourceSpan 全文存储，再经产品 PATCH draft → POST checks → 两次 GET（issues/evidence/metrics）验证。第二次读取的 Issues 与第一次完全一致。每例仅调用固定 Provider 一次，未修复、未规范化；当前实际请求与被冻结的 capture 除 claim ID 外一致。

| 新结果 | case / variant | 最终性质 | 结果 |
|---|---|---|---|
| `fresh-01.json` | north_glass / world_rule / conflict / gold | confirmed_conflict | 通过 |
| `fresh-02.json` | north_glass / object_state / conflict / gold | confirmed_conflict | 通过 |
| `fresh-03.json` | orchard_restoration / event_status / conflict / gold | confirmed_conflict | 通过 |
| `fresh-04.json` | harbor_signal / character_knowledge / no_conflict / state_change | state_change | 通过 |
| `fresh-05.json` | basalt_observatory / location_action / no_conflict / state_change | state_change | 通过 |
| `fresh-06.json` | north_glass / world_rule / insufficient_evidence / gold | insufficient_evidence | 通过 |

这覆盖了本轮 3 个修订后的同一时间冲突、2 个允许的状态变化和 1 个证据不足控制。固定答复取自已保存的 scripted raw_first，仅将 claim ID 映射到新运行；这是当前产品接收/绑定/持久化的独立复验，不是独立生成 gold、模型推理或新版真实模型成绩。各例完整实际请求、固定首答及产品结果保存在 fresh 文件中，汇总见 `fresh-api-summary.json`。

## 4. P2：首失败逐例原始结果无法核实；原入口存在确定的覆写风险

`PRECHECK_FAILURES.md:4-5` 叙述首轮 V2 有 24/24 次完成、8/24 次结构通过，以及后续修正为 26 份结构通过。当前 V2 只交付 `api-score-probe-results-v2.json`，其内容是后续 26 个 V2 身份，不能充当那批 24 个首失败原始结果。

本次按文件名在 V2、对应 `docs/g02-citation-repair-evidence`、`artifacts` 有界检索，并在 `evaluation` 中核对同名 API 结果身份（包含隐藏/忽略路径的文件清单）。另两份 24 例结果属于 V1，schema/case ID 为 ccv1，不是 V2 的 24/8 首失败链。未发现能直接复核该首失败的独立逐例原始结果。

确定的代码事实是 `api_score_probe.py:133-134` 将固定目的文件用 `open("w")` 写入，重复运行会替换同一路径内容。这证明存在覆写风险，不能仅据此断言历史文件已经被覆写，也不代表在所有未检索目录中都不存在备份。

影响：当前 26 份交付的内部一致性与本次 6 例新复验可以成立；但「V2 首轮原始失败链完整保留」无法验收。建议后续入口采用独立 run 目录和 create-only 写入；缺失历史应如实标为叙述记录，不能重新构造成原始结果。本次未恢复、改写或要求无限追索旧证据。

## 5. 冻结保护与复跑

收到的 manifest SHA-256 与本次读取相符：

`35b8a9559b9d5138f21795cdeb74439d010490dd5a9ee07a37cd48dbd44ca337`

manifest 绑定的 32 份文件均符合其冻结哈希。前后保护清单共 34 个文件（上述 32 份、manifest、HANDOFF），全部未变；逐文件记录见 `hashes-before.json` / `hashes-after.json`。HANDOFF SHA-256 为 `6e611e8752e9a1696611d380c55a39a0e8c1b202b965a198d77f16c08444cd71`。本次全部新增文件及合成数据库仅在本目录，未改产品、原结果、业务数据库、凭据或配置。

实际执行命令（工作目录为本 worktree 根）：

```powershell
.\.venv\Scripts\python.exe docs/g02-citation-repair-evidence/independent-round3-capture/capture-probe.py
```

脚本自身结果使用 create-only 写入，且保留异常为新的 first-failure 文件；本轮无异常。不要在已有证据目录原地重跑。需要复跑时将脚本复制到同层新的独立证据目录，保留原 6 份输出及 synthetic 目录；不得重跑会覆盖原交付 JSON 的 `api_score_probe.py` 入口。

最终限定：本人的 capture / API 链任务完成。gold 的逐例叙事正确性、scorer 对反例的拒绝能力及任何真实模型调用，分别由对应验收任务或后续独立授权决定。
