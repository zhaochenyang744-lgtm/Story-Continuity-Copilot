# prep-v5-02 比较集输入独立复核

结论：限定输入检查通过，无输入阻断。仅覆盖 `01–24` 的 stub 准备输入；不形成模型分数，也不替代最终冻结、运行器或真实结果验收。

本次仅用 Python 标准库读 JSON 和计算 hash，没有运行评测入口、调用 Provider/API 或打开数据库。读取每例 `case-start.json`、`requests/01.json`、`input-audit/01.json`、`runtime-binding.json`，对照先前独立人工矩阵、V3 gold、V2 exact capture及四份语料。

已检查 108 个文件，前后 hash 一致；24 例中 24 例全部检查通过。每例的 case 定义 canonical hash、业务请求 hash、case ID/ordinal、草稿/项目 ID、正文、所有章节/SourceSpan/Memory 绑定、选中来源和最小集合均逐项核对。

24 份请求仅归一化 claim.id 后与 V2 历史业务请求完整深比较相同；本轮 24 个 claim.id 唯一。每例 draft revision=2、source revision=1、memory version=1，三条实际选中来源均与语料和人工矩阵一致，最小集合全部入选。Memory 中未进入当前三条 Evidence 选择的来源，均在完整 runtime 章节快照中存在且自身绑定正确。

注意两种正文 hash 编码：请求包装的 selected_source_bindings.sha256 是 JSON 字符串编码的 hash（包括引号），runtime 的 chapter/span/draft body hash 是原始 UTF-8 正文 hash。两者不能直接互比；本次分别按实际编码重新计算并通过。

case-start 的 case_input_sha256 绑定 V5 的案例包装（ordinal/family/case_id/corpus/saved_draft/gold_ref），不是直接把 V3 完整 gold JSON 当对象求 hash；本次独立核对两者映射及V5包装的hash。

## 逐例结果

|序号|案例|输入检查|最小来源|
|---|---|---|---|
|01|ccv3-north_glass-world_rule-conflict|pass|badge_rule|
|02|ccv3-north_glass-world_rule-no_conflict|pass|badge_rule + badge_roster|
|03|ccv3-north_glass-world_rule-insufficient_evidence|pass|spare_register|
|04|ccv3-north_glass-object_state-conflict|pass|carrier_ready_rule + carrier_inspection|
|05|ccv3-north_glass-object_state-no_conflict|pass|carrier_ready_rule + carrier_inspection|
|06|ccv3-north_glass-object_state-insufficient_evidence|pass|cap_actor|
|07|ccv3-harbor_signal-timeline-conflict|pass|gate_log|
|08|ccv3-harbor_signal-timeline-no_conflict|pass|gate_log|
|09|ccv3-harbor_signal-timeline-insufficient_evidence|pass|reopen_log|
|10|ccv3-harbor_signal-character_knowledge-conflict|pass|telegram_seal|
|11|ccv3-harbor_signal-character_knowledge-no_conflict|pass|telegram_seal + later_recipient|
|12|ccv3-harbor_signal-character_knowledge-insufficient_evidence|pass|later_recipient|
|13|ccv3-orchard_restoration-relationship-conflict|pass|kinship_rule + twin_register|
|14|ccv3-orchard_restoration-relationship-no_conflict|pass|kinship_rule + twin_register|
|15|ccv3-orchard_restoration-relationship-insufficient_evidence|pass|birth_order|
|16|ccv3-orchard_restoration-event_status-conflict|pass|launch_rule + launch_log|
|17|ccv3-orchard_restoration-event_status-no_conflict|pass|launch_rule + launch_log|
|18|ccv3-orchard_restoration-event_status-insufficient_evidence|pass|delay_cause|
|19|ccv3-basalt_observatory-attribute-conflict|pass|lens_index + west_lens|
|20|ccv3-basalt_observatory-attribute-no_conflict|pass|lens_index + west_lens|
|21|ccv3-basalt_observatory-attribute-insufficient_evidence|pass|grinder_blank|
|22|ccv3-basalt_observatory-location_action-conflict|pass|watch_log|
|23|ccv3-basalt_observatory-location_action-no_conflict|pass|later_watch|
|24|ccv3-basalt_observatory-location_action-insufficient_evidence|pass|later_watch|

## 保留边界

准备记录声明 offline-stub/prepare；summary 的生成POST开始/完成、HTTP响应和models GET开始/完成均为0。这里核对的是记录内容，不通过stub输出推算模型质量。start 中 frozen_manifest_sha256 仍为 null，符合冻结前准备阶段；真实执行前需要主控另行验收最终冻结。

runtime-binding 属于实施保存的数据库快照，本分工仅核对该快照与请求/语料/版本的自洽性，没有独立打开数据库证实持久化。input-audit 中 matched_persisted_isolated_database 是原运行器的声明，本报告不扩大为本分工的数据库实查。

11与23允许state_change，24同伴类别需逐答人工裁定；这些规则未变。01徽章规则单条充分，名单可选。实际真实请求与结果到来后仍需逐层检查首答、修复、最终产品与自身引用，不能用本stub输入通过替代。六个G02及真实HTTP/usage/质量不在本次范围。

全部读取文件的路径、前后SHA-256及24例细项见同名JSON。旧准备记录与旧人工矩阵未改写。
