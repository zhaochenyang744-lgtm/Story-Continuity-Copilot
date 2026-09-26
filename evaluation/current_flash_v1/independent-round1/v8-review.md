# V8 当前 Flash 运行独立复核

日期：2026-09-26。复核 HEAD：`c3bd54ab019447354e8b1387e16b9aca3258b4c9`。对象：`flash-v1-20260926-01` 的 24 个 V8 正式案例；原 V8、实施脚本和运行结果只读。仅在本目录新增本报告、两份诊断脚本及两份结果。

## 结论

**留存的首答标签命中 9/24、最终产品标签命中 8/24 可独立复算；不能把它们称为当前模型的严格语义准确率。** 首答多出的 1 例 timeline 缺失必要第二条直接证据，且明确时间关系被当前契约拒绝。24 例的实际 claim 文本与冻结 target_draft 全部逐字一致；未发现 `claim_text`、`summary` 或正文适配遗漏。证据缩减是当前产品代码真实执行的结果，不是 harness 自行裁剪。

同时，**旧 V8 的 Memory 表示与当前确定冲突契约存在独立的不兼容**。即使排除裁剪并给足证据，代表性的 relationship / world_rule 仍会因为旧 `fixture_anchor` 并非 `rule` 而拒绝 `confirmed_conflict`。因此不能将这次结果单独归因于 Flash，也不能把全部错误归因于证据裁剪；需要保留原结果，并另建契约兼容且人工复核过的新版本材料后才能进行相应模型质量比较。

## 1. 逐例输入与分母

| 冻结预期类 | 案例数 | DB top5 含全部预期证据 | 实际模型输入含全部预期证据 | 首答标签命中 | 最终标签命中 |
|---|---:|---:|---:|---:|---:|
| conflict | 8 | 8 | 0 | 1 | 0 |
| no_conflict | 8 | 8 | 4 | 8 | 8 |
| insufficient_evidence | 8 | 8 | 4 | 0 | 0 |
| 合计 | 24 | 24 | 8 | 9 | 8 |

独立诊断从四份冻结 corpus JSON 重建章节、SourceSpan 和 Memory，按当前 DB 排序公式恢复 top5，再实际调用纯函数 `ContinuityEngine._selected_evidence`。24 例的 top5 顺序、最终三条证据顺序、正文和 prompt_excerpt 全部与留存输入精确一致。所有预期 SourceSpan 的章节号与 source_label 对应关系也检查通过，不仅通过 ID 尾数推断。

这 24 个英文 target 各只有一个实际 claim，因此按绑定 claim_id 重算首答与最终标签，结果没有受到当前实现仅看首个 Issue 的缺陷影响；这一结论不能泛化到未来多主张案例。24 个最终运行均 completed 且无 Issue，故最终三分类全为 no_conflict；8/24 是冻结标签命中数，宏 F1 为 (0+0.5+0)/3 = 1/6。

四例即使实际输入包含完整预期证据，仍首答/最终均无 Issue：`v8-dusk-viaduct-insufficient-7`、`v8-flint-garden-insufficient-7`、`v8-opal-nursery-insufficient-7`、`v8-opal-nursery-insufficient-8`。这些错误无法仅用裁证据解释；本轮不进一步推断其模型/提示词因果贡献。

## 2. 裁证据的具体来源

- `evaluation/current_flash_v1/run.py:220-231`：仅加载旧 fixture、补空作者上下文快照、调用已有 run_case；没有替换 claim 或裁剪证据。
- `evaluation/run_eval.py:446-447`：通过草稿 API 保存冻结 `target_draft`。
- `backend/app/v2_database.py:3263-3265`：生产链由保存的正文生成 `claims[].text`；`3273-3279` 检索并记录 top5。
- `backend/app/engine.py:21,218-231`：模型输入再按 Memory 相关度的 10 倍权重和正文相关度排序，只留 3 条。
- `backend/app/provider.py:214-226`：当前字段为 `current_claims[].text` 和证据 excerpt，无 `claim_text` 或 chapter summary 的额外输入要求。

最小例 `v8-dusk-viaduct-conflict-relationship`：预期证据为第 1、2 章；DB 排序得到 `1,5,6,7,2`。engine 分值分别为 120、120、19、112、13，实际发送 `1,5,7`；第 2 章为没有 fixture Memory 绑定的观察证据，被其它共享人物名且有 fixture Memory 的片段压下。正文均短于摘录上限，所以不是字符串截断。旧 fixture 的第 1/3/5/7 章各绑定同名人物的 `fixture_anchor`，这个旧合成表示参与当前加权排序，是复现条件之一；不能推断真实作者材料有同样错误率。

旧 `retrieval_hit_at_5` 只衡量 DB 候选列表（`evaluation/run_eval.py:403-417`），并非实际模型输入的证据覆盖。两者必须分开报告。

## 3. 旧 Memory 与当前确定冲突契约

四份旧 corpus 显式写了 `memory_type=static_canon`、`predicate=fixture_anchor`；不是 loader 未填默认值（例如 `evaluation/fixtures/eval-v8-dusk-viaduct.json:77-79`）。`evaluation/v2_fixture_loader.py:231-232` 原样写入，harness 没有把其改成新事实。

当前提示词 `backend/app/provider.py:101-103` 要求确定冲突有明确重叠时间，或已提供的静态规则。执行校验 `backend/app/engine.py:375-381` 对 timeless_rule 进一步要求引用相关 Memory 同时为 `static_canon` 和 `predicate=rule`。旧 fixture 的普通规则文本没有自动变成这种 Memory。

最小纯校验实验（无 Provider、无 DB，详见 `v8-contract-results.json`）：

| 输入/响应条件 | relationship | world_rule |
|---|---|---|
| 两条完整直接证据 + 原 fixture Memory + confirmed_conflict/timeless_rule | 拒绝 `timeless_rule_unproven` | 同左 |
| 仅在内存中将绑定 Memory 的 predicate 改为 rule，其余不动 | 通过 confirmed_conflict | 同左 |
| 原 Memory + possible_conflict/unknown，status 仍为 conflict | 通过 possible_conflict | 同左 |

第二行只是定位代码门槛的结构性反事实，不是正确制作的新评测集，也不证明单字段改名能完成语义适配；原 Memory value 仍是 fixture 标识，真实新材料应由来源事实及人工标签重新建立。未修改任何旧 fixture。

旧三分类只看 `classification`（`evaluation/metrics.py:10-16`），不会区分 possible_conflict 和 confirmed_conflict。因此旧 conflict 标签并不在技术上要求当前确定冲突性质；不能把两套口径混同。旧标签可继续保留为历史语义目标和已暴露回归参考，但无法未经适配就充当“当前模型在已获得完整有效输入时”的准确率金标准。

唯一首答 conflict 的 timeline 例还引用了单独的 dawn-tag 规则，未拿到证明该次 transfer 使用 afterglow 标签的第 4 章。它把 `before the dawn bell` 与 `after the ward's dawn bell has rung` 标作 explicit_overlap；当前 matcher 不将该 before/after 关系判为重叠。因此 9/24 仅是首答类标签命中上限，并非 9 个结构、时间、证据均正确的回答。

## 4. 验证与边界

- `v8-diagnose.py`：24 例输入、DB 排序、实际选择、引文正文、目标评分逐一重建，全部断言通过。
- `v8-contract-probe.py`：2 个代表案例各 3 种纯校验条件，全部断言通过。
- 两脚本均在调用前禁用 socket、SMTP、sqlite3.connect；未构造真实 Provider，禁止调用 evaluate。网络、SMTP、数据库访问尝试均 0。
- 冻结清单中的全部源码和输入 hash 与冻结值相符。第一个诊断另对 48 个留存 case、summary、postrun-audit 做前后 hash，相同。结果 JSON 保存具体 hash；未修改实施脚本、产品、旧结果或维护文档。
- 初次运行本人诊断脚本因 Windows 路径分隔符导致 frozen-hash 字典 KeyError，尚未写结果；仅修正本人脚本将路径统一为 POSIX key 后通过。该问题不是产品或评测实施缺陷。
- 普通 `git diff --stat` 对已有浏览器长路径发出 Filename too long 警告；本次只读指纹核验不依赖这条命令完整枚举。没有清理或改动那些文件。
- 未复跑真实模型，未访问原数据库/本轮 runtime DB、`.env`、受限 held-out，未运行旧 probe，未提交或部署。未作通用改写语义/未见故事准确率判断。

复跑需将本目录的两份脚本复制到 `evaluation/current_flash_v1/` 下一个全新同层目录，使用 `.venv/Scripts/python.exe -B <新目录>/v8-diagnose.py` 和 `.../v8-contract-probe.py`。输出以独占方式创建，不能覆盖本轮留存证据。
