# V5 live-01：24例比较集独立逐答语义验收

**结论：真实记录可供审阅，当前固定比较集质量未通过。** 24个已见开发案例中，首答和最终产品各有10例同时满足冻结合同与本次人工审阅。这个数不能等同于“只理解了10例”：核心结论、类别/引用合同及产品是否交付必须分开。

核对前后 268 个所读文件SHA-256一致；27份可见响应（24首答+3修复）全部为HTTP200、finish_reason=stop、可解析，且解析后的JSON与各自保存的parsed_business_json相同。首个可见答复就是首个可解析业务答复，无前置未解析答复被忽略。未调用Provider/API、未打开数据库、未执行scorer或产品validator。

## 分层结果

|维度|首答|最终产品|
|---|---:|---:|
|与冻结三分类一致，仅核大类|17/24|11/24|
|同时通过固定类别/证据合同与人工审阅|10/24|10/24|
|冲突大类一致|8/8|2/8|
|无冲突大类一致|8/8|8/8|
|不足大类一致|1/8|1/8|
|不足全合同及人工审阅通过|0/8|0/8|

最终16例完成、8例终止；8个终止均没有issues字段，不能默认填空数组后计为无冲突。完成结果中另有5例应保留不足却返回空issues。三个修复都未满足冻结完整验收：03由错误confirmed变为漏报空结果，15维持归属冲突并改timeless，24重复原答。本次没有保守归一化记录。

11和23允许state_change，但模型均返回合法空issues，两个兼容性案例通过；本轮没有真实state_change对象，不能宣称实模型变化对象的引用/合同表现已经验证。

## 必须保留的判断差异

- 01/04/10/16的核心冲突结论、类别和最小证明正确；附加context或规则supports不符合当前confirmed证据一律contradicts的合同，导致产品终止。04/16使用explicit_overlap有实际同刻依据，虽不符冻结timeless枚举，不是把故事时间看错。01规则文本没有10点锚点，reasoning那一句有过度表述，其timeless规则适用的核心结论仍成立。
- 19正确以索引绑定R4，再由材料来源识别琥珀/透明冲突；object_state类别错误且supports关系违反合同。22的核心冲突及直接watch_log正确，但引用了不在allowed_evidence内的span6；Memory6确实提供19点移动内容，故是SourceSpan绑定越界，不是凭空编造该内容。
- 18准确识别Tala归责缺口，context/insufficient、missing_link及无动作正确；但event_status类别不对，附加launch_rule超出冻结允许集合。该来源本身真实且相关，不应称“无关编造”。最终产品保留了这些优缺点。
- 15/24的草稿明确说“record/register establishes”，模型判的是该文献归属断言与来源未记录/未命名的冲突。这种解释有文本依据，不能等同为模型断言相反故事事实；冻结gold采用故事事实仍未定的insufficient目标，存在解读范围歧义。本轮保留原始失败与24分母，不追改gold、不把二者加回通过率，也不把此处全部差异称幻觉。
- 15的attribute与24的character_knowledge仍不符已约定核心类别；24不是在判断人物知道什么，亦不落在location_action/relationship两候选内。本次可以裁定该回答类别不合格，不能因预声明候选存在便通过。15修复称无时间限定即timeless，附带亲属规则不能支持出生顺序为永恒规则。
- 13首答有来源支持的替换建议；最终仅清除建议与apply_suggestion，正确亲属冲突保留。engine的timeless_rule分支解释了此产品差异，不把它写成模型新增回答。

## 24例逐项记录

|序号|预期|首答人工判断|修复|最终产品|
|---|---|---|---|---|
|01|conflict|核心正确；可选名单context触发合同失败|未修复|终止：conflict_evidence_not_direct|
|02|no_conflict|无issue正确|未修复|通过|
|03|insufficient_evidence|把空白持有人升级为确定冲突|1次，未通过|完成但不合格|
|04|conflict|核心正确；规则supports/固定时间枚举不符|未修复|终止：conflict_evidence_not_direct|
|05|no_conflict|无issue正确|未修复|通过|
|06|insufficient_evidence|漏报Mira责任缺口|未修复|完成但不合格|
|07|conflict|顺序冲突、类别、自身证据均正确|未修复|通过|
|08|no_conflict|无issue正确|未修复|通过|
|09|insufficient_evidence|漏报Sera授权缺口|未修复|完成但不合格|
|10|conflict|核心正确；额外后时点context触发失败|未修复|终止：conflict_evidence_not_direct|
|11|no_conflict|合法知识变化，无issue正确|未修复|通过|
|12|insufficient_evidence|漏报Vela递送角色缺口|未修复|完成但不合格|
|13|conflict|亲属冲突、类别、联合证据正确|未修复|通过|
|14|no_conflict|正确识别叙述中故意谎话|未修复|通过|
|15|insufficient_evidence|文献归属解读争议；类别/合同不合格|1次，未通过|终止：conflict_evidence_not_direct|
|16|conflict|核心正确；规则supports/固定时间枚举不符|未修复|终止：conflict_evidence_not_direct|
|17|no_conflict|无issue正确|未修复|通过|
|18|insufficient_evidence|不足判断正确；类别/额外来源政策失败|未修复|完成但不合格|
|19|conflict|核心正确；属性类别错、supports不符|未修复|终止：conflict_evidence_not_direct|
|20|no_conflict|正确保留昨日主观回忆边界|未修复|通过|
|21|insufficient_evidence|漏报Vela磨制责任缺口|未修复|完成但不合格|
|22|conflict|核心正确；额外span6未被选中|未修复|终止：evidence_unresolvable|
|23|no_conflict|合法位置移动，无issue正确|未修复|通过|
|24|insufficient_evidence|文献归属解读争议；类别/合同不合格|1次，未通过|终止：conflict_evidence_not_direct|

每例完整人工说明、首可见/首解析/修复/最终产品的准确路径、自己的引用绑定诊断和机器结果对照，均在 [live-01-review.json](live-01-review.json) 的 `rows` 中。

## 问题定位与范围

最低充分材料在24份同次真实首请求中均已出现；请求与历史V2 capture仅claim.id不同，修复仅追加contract_repair、未替换故事材料。可见失败主要落在模型的不足识别、类别/引用关系/来源绑定、产品严格合同导致的交付损失，以及15/24 gold目标范围解释歧义；本轮不为分数改产品、提示词或gold。

后续改进应先审清“规则＋事实”“身份＋属性”的联合证据应如何表达，以及relation究竟相对草稿断言还是相对论证结论。不要把context/supports一律改写成contradicts以表面提分。是否调整混合关系、额外上下文、文献归属类目标，须形成新版本和独立正负控制；本报告只定位与保留失败，不启动修补。

本范围为已见24例，六例G02由另一分工验收。整体HTTP/usage账本、调用授权、最终冻结、提交/发布不在此语义分工的独立确认范围。用户接受和发布仍为后续独立状态。
