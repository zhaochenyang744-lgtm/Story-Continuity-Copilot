# related_memory_ids 与联合证据的只读风险核查

2026-09-27。仅查源码与现有合同；未执行测试、Provider 或 DB 连接。此页补充工程判据，不裁定 V6 实装已通过。

**结论：现有产品合同没有明确要求每个 related Memory 的来源等于挂载它的 evidence.span_id。跨来源语义关联目前被允许进入结果，但不能据此认定它证明了该条引用或整组矛盾。** 不宜为满足负控制，直接把所有跨来源关联改成非法。

可核实依据：`backend/app/engine.py:161` 将该字段描述为 known memory id；`backend/app/provider.py:112` 要求 known related Memory ids，没有同源限定。`engine.py:236–247` 按来源加权及词义相关性挑选 Memory，可包含来源不同的相关事实；请求内多个 claim 还共用已选 Memory 集合。`engine.py:353` 仅检查 ID 属于本次请求的 Memory 集合（并非任意数据库 ID）；`v2_database.py:3426–3435` 回读时确认同项目、同 run 的 Memory 版本，仍不校验与当前 evidence 同源。旧 API 的关联事实展示也没有来源相等要求（`database.py:226–230`）。这些证明当前结构允许关联，不能证明任意跨来源 ID 都语义相关。

评测已有更严的政策：V3 raw scorer `evaluation/current_contract_compare_v3/score.py:72–74`、V2 final scorer `evaluation/current_contract_compare_v2/score.py:149–151` 都要求 Memory.source_span_id 等于当前 evidence.span_id。现有正例也多按同源构造。应明确这是评测采用的绑定口径，不能倒推出产品已明文禁止跨来源关系；若 V6 统一字段为“此引用的来源 Memory”，须事前更新合同说明与评分版本，保留旧分数。

**确定的风险位置是 timeless_rule 的资格判定。** `engine.py:281–282,380–382` 汇总任意 evidence 上的已知 related ID，只要其中一条是 static_canon/rule 就提供永恒规则资格，没有要求该规则自己的 SourceSpan 在本 issue 中实际被选中并引用。因此，把请求内另一条不相干规则的 ID 挂到一条引用上，结构上可能借来规则资格。此处是静态可达风险，尚未执行反例。联合证据若容纳 supports/context 作为辅助前提，将给这种错绑多一个进入通道；一条正确反证不应为其他任意引用背书。

建议实施采用以下精确边界：

1. 一般 related_memory_ids 保留“关联”含义：必须是本次请求中的字符串 ID 列表，不能从 ID 存在推出语义支持。未选 SourceSpan、错章、错项目/版本继续拒绝；不要无条件施加逐条同源约束而误伤合法关联。
2. 凡将 Memory 用作规则资格或其他证明前提，另外核对它的 source_span_id 是本 issue 实际引用的、该 claim 已选的 SourceSpan，且章/原文绑定有效。允许规则挂在另一条辅助 evidence 上；不要求每一个普通关联 ID 都来自其挂载 evidence。即使来源可解析，规则适用的主体、范围和与草稿的关系仍须明确，不能把 ID 校验称为语义证明。
3. 联合证据仍须实际矛盾依据与必要辅助前提共同成立；全 supports、无关 context、未知或错位时间均不得因为“有相关规则 ID”升级 confirmed。time 规则检查与 evidence 的关系/充分性检查分开保留。
4. 定向负控应为“未引用规则自己的来源，却挂入其已知 Memory ID，借此取得 timeless 资格”；正控保留“合法跨来源关联且无需该关联提供证明资格”，以及“规则来源另行作为已选辅助引用”的组合。两者区分后再验收，不用一概拒绝跨来源来取得测试通过。修复诊断与正式验证须使用一致的资格规则。

本页不要求拓展为通用自然语言相关性判别器。若继续保留 V3 同源评分政策，应在 V6 结果中明确它比通用产品关联字段更窄，避免将合法跨来源关联直接包装成产品错绑。