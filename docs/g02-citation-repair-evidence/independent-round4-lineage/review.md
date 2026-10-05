# V3 历史与离线重评分链：独立复核

日期：2026-09-26。结论：本次限定的 lineage 检查通过，未发现 V2 输入/旧答复被改写或旧类别失败被隐藏。V2 首轮 24/8 原始逐例链依旧无法核实，V3 已如实保留该限制；本报告不把它视为已补回。

## 实际执行与边界

本人阅读 HANDOFF、HISTORY_GAP、run.py、controls.py、评分入口及冻结/保存 JSON，并执行新的 `lineage-check.py`。此脚本只使用 Python 标准库进行 JSON/哈希比对，未导入或运行 scorer、产品、API 或数据库。没有新 Provider 或 API 调用，没有读取 `.env`、密钥或业务数据库。gold 语义与 scorer 反例充分性由其他审阅负责；本轮没有重跑 V3 原入口或控制。

机器结果：24 capture、26 个保存结果身份，raw-first 19 pass / 7 fail，final 19 pass / 7 fail，错误 0。详见 `lineage-results.json`。

## 1. V2 exact capture 和旧答复保持原样

- 与前轮 capture 独立验收留下的 34 文件哈希逐项一致。V3 manifest 的 27 个绑定文件符合冻结值；本轮合并保护清单 55 个文件，前后哈希全同。
- V3 24 个 successor 均正确映射 V2 case；target_draft、corpus_key、target_claim_ordinal、expected_class 未变。V3 的 gold/category/minimum 调整不被当成实际正文变化。
- 26 份已保存 API request 与其冻结 capture 深比较一致，只归一化瞬时 claim.id。26 个 V3 评分身份与 26 个 V2 保存身份精确对应，无缺失/重复。
- V2 capture SHA-256：`b55eba3b0aa4e8881c22d2ef0646de5303522cc2215a5d6e1a33c1c2ab26913c`。
- V2 26 份保存结果 SHA-256：`b261629423eed61caccc9eb65b56bda2a69f68f927ea8c02e753fada070a8d0e`。
- V3 manifest SHA-256：`0afd9630d22aecc44d1fbc8a955787d12d1286b31ec85a3e0985dff132da8baf`。

## 2. 19/7 不是修改旧输出后的全通过

7 个失败的旧 raw 与 final category 保持相同，均不在对应 V3 category candidates 中；所有失败仅呈现 raw 的 `raw_target_or_category_mismatch` 和 final 的 `category_mismatch`。它们都是 insufficient_evidence case：

| corpus / 原 axis | 保留的旧类别 | V3 声明类别 |
|---|---|---|
| north_glass / world_rule | world_rule | object_state |
| north_glass / object_state | object_state | relationship |
| harbor_signal / timeline | timeline | relationship |
| harbor_signal / character_knowledge | character_knowledge | relationship |
| orchard_restoration / relationship | relationship | timeline |
| orchard_restoration / event_status | event_status | relationship |
| basalt_observatory / attribute | attribute | relationship |

此表只确认历史类别与新评分结果的映射，不替其他审阅判定新类别语义正确。summary 的 19/19、7 行 category_delta、repair=0 都能从逐例 rows 独立计数得到。

`run.py:84-89` 分别读取旧 raw_first、存在时的 raw_repair、final_product 评分。V3 rows 中这三个字段是分层**评分结果**；完整首答/最终产品仍在冻结 V2 源文件中，并非 V3 又生成了一批答复。26 个旧 raw_repair 均为 null，V3 也均为 null，没有制造修复答复。initial-offline-rescore 和 final-offline-rescore 两份产物均实际存在且受 manifest 绑定，未以最终文件冒充初始记录。

## 3. targeted-01 的干扰与 targeted-02 的纠正分别保留

两轮各保留 20 个控制身份。逐项核对五个 raw 负控：缺 evidence_chain、错误 missing_link role、insufficient 携带 edit action、携带 Memory change、未知 Memory ID。

- targeted-01 每例都保留预期错误及额外 `raw_target_or_category_mismatch`，与 HISTORY_GAP 所说 category confound 一致。首轮的 20/20 汇总不能单独充当这五项已隔离验证的证据。
- targeted-02 对同五身份均保留相应预期错误，移除类别不匹配错误，并记录 `raw_full_validator=rejected`。`controls.py:79-103` 明确先在内存副本中设置 V3 类别，再作单项变异。
- `HISTORY_GAP.md:5` 明确第一轮被第二轮取代的是「隔离负控证据」用途，而不是删除首轮。两轮文件哈希不同，均仍存在并被 manifest 绑定。

这些是已保存的控制评分输出和源码逻辑核对，不是本人重新运行负控，也不是保存了全部变异 raw payload 的实模型响应链；没有把它们计为新模型成绩。

## 4. 零新调用与首失败缺口的表述准确

`run.py:68-98` 读取冻结 V2 JSON 并离线评分；`controls.py` 对已保存答复做内存副本变异；raw gate 调用本地 `ContinuityEngine.validate`，没有生成调用入口。产物的 new_api_runs=0 / real_provider_calls=0 与本次所查入口和用途一致。本次独立检查本身也为零调用。HANDOFF 中跨历史的累计真实调用/token 台账不属于本轮审计，未据此作独立确认。

`HISTORY_GAP.md:3` 准确写明 V2 24-completed/8-pass 只有失败摘要，缺完整逐例首答链，V3 不重建或换名冒充。`run.py:112` 的新失败说明也区分「本次 V3 failure」与「历史 V2 failure」。本轮没有扩大旧文件搜索或重建缺失证据。历史缺口仍在，披露与后续保护机制改进可以验收，原始缺失不能宣称修复。

## 复跑与产物

实际执行：

```powershell
.\.venv\Scripts\python.exe docs/g02-citation-repair-evidence/independent-round4-lineage/lineage-check.py
```

输出 `lineage-results.json`、`hashes-before.json`、`hashes-after.json`；均 create-only。复跑需把脚本复制到同层新证据目录，避免覆盖本轮原记录。防覆盖入口的运行验证由主控负责，本人只核对上述文件和静态调用链。

限定结果：lineage 部分通过，历史 V2 首失败逐例链未验证的状态继续保留。无新 API/DB 实跑、无真实模型质量结论、无发布或用户验收结论。
