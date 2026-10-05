# V3 评分修订限定复验

结论：本次指定的评分修复范围通过独立复验，45/45 有界控制符合预期，没有发现新增评分阻断。R3 的五项原始合同遗漏已关闭；单条 badge_rule 来源和修正后的类别能够通过；产品安全降级没有被当成首答正确。Gold 的人工语义接受、历史缺失失败链、真实模型效果和用户接受仍是另外的结论。

## 执行和证据保护

独立脚本直接读取 V2 的只读 26 份合成记录以及上一轮独立失败 payload，在内存调用 V3 评分器；没有调用实施 `run.py`、`controls.py` 的执行入口，没有新 API、Provider、网络或数据库连接。socket 和 sqlite 连接在脚本中被禁止。输出只以 create-only 写入本目录。

- [probe.py](probe.py)：本轮独立探针，可复查控制构造。
- [results.json](results.json)：31 个已检查文件的前后 hash、历史重评分、每项变异及评分结果。
- V3 manifest：`0afd9630d22aecc44d1fbc8a955787d12d1286b31ec85a3e0985dff132da8baf`。
- V3 scorer：`89afed19eb6ba9dbad63b4e95c24f4d687c97e076f38d44767633b6db727243d`。
- 31 个文件包括 V3 manifest 声明的文件、manifest 本身和上一轮独立脚本/失败结果/报告；执行前后 hash 一致。产品与所有旧证据未修改。

## R3 五个失败逐项关闭

没有重写一个“相似的新反例”代替旧失败：直接取 `independent-round3-score/results.json` 的五份原 payload 和当时业务请求，只把 category 改成当前 V3 gold，避免无关类别误拒造成假绿。修改前先为八项新类别建立 raw/final 正控制，均通过。

| 旧首答错误 | V3 指定错误 | 完整 validator | 结果位置 |
| --- | --- | --- | --- |
| 缺失 Evidence chain | raw_evidence_chain_mismatch | rejected | results.json:2906 |
| 不足 chain role 为 prior_state | raw_missing_link_role_invalid | rejected | results.json:2958 |
| 不足含 edit 动作 | raw_insufficient_actions_invalid | rejected | results.json:3015 |
| 不足含 Memory change | raw_insufficient_memory_change_invalid | rejected | results.json:3074 |
| 引用未知 Memory ID | raw_memory_link_mismatch | rejected | results.json:3137 |

五项均为 `machine_result=fail`、`semantic_result=not_reviewed`，并且不含 category mismatch。修复位于 `evaluation/current_contract_compare_v3/score.py:43-80`。

## 单条来源、类别和历史保留

badge conflict 的单条 `badge_rule` 引用在 raw/final 两层均通过；保留 rule + optional roster 也通过。两条 Evidence 不再是这一案例的强制最小集合。见 `results.json:3194`、`:3315` 起。

八项不足类别逐一按 V3 `decision_category` 设置后，raw/final 共 16 项通过。出生先后改为 timeline、具名人授权改为 relationship 等修订在评分执行上已生效。同行者的 location_action 与声明的 relationship 候选都保留 `category_status=pending_manual_adjudication`，且 `semantic_result=pending_manual_review`；结构接受没有变成语义确定。见 `results.json:730` 至 `:2905`。本报告确认代码执行新 gold 的规则，完整类别理由由专门的 gold 审阅作最终判断。

独立重评分冻结 V2 的原始 26 组记录，原样得到 **19/26 raw 通过、19/26 final 通过**；其余七条均保留旧不足类别的失败。26 份原始答复仍被产品完整 validator 接受，但这不让七个不符合新 gold 的旧答案通过。没有静默改写历史答案；八项新类别正控制明确属于人工变异，不能充作新模型或 API 结果。

历史 `raw_repair` 均为空，本轮没有制造修复答。评分首答与最终结果使用不同字段/函数；机器通过结果仍为语义待审。

## 首答不会借安全归一化变绿

`score.py:76` 调用 `ContinuityEngine(object()).validate(raw, request)`，没有启用 `allow_conservative_temporal_normalization`；该参数在 `backend/app/engine.py:332` 默认 False。

独立控制将同时间冲突首答的 temporal relation 改为 unknown：V3 raw 得到 `full_validator_result=rejected` 和机器失败；另在内存明确传 `allow_conservative_temporal_normalization=True` 时，同一原始 payload 才降为 insufficient_evidence。见 `results.json:6229`。这直接区分了严格原始合同失败和产品可选的安全降级，不把后者算成 raw 成功。完整 validator 的接受仍只证明当前合同接受，不证明故事判断正确。

## 保留的原正负控制

两项支持充分的 state_change 在 raw/final 通过，改成 possible_conflict 均拒绝。附加无关最终 Evidence、错误章节、错误摘录、不足引用关系升级仍拒绝。failed、timed_out、running、cancelled 四种状态配 `issues=[]` 均返回 terminal_failure。负控都先修正类别，再施加目标变异，避免 category confound。

本轮不扩展任意恶意 JSON、通用 run 身份或新产品能力检查；运行身份防覆盖、实施 tests 和更广冻结保护由主控独立检查。本轮 45 项是合成控制，不是模型准确率。`case_time_scope.minimum_source_texts` 的 badge 项仍列出 optional roster，是说明字段残留；评分实际依据的 minimum 已正确，不影响上述通过结论，已告知主控。
