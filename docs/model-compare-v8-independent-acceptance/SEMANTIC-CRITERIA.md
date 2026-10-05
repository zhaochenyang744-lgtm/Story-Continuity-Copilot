# V8 三组模型对照：预先固定语义验收标准

仅沿用 V7 **34 个已见开发输入**（无冲突13、确定冲突10、不足11）及冻结 gold。Flash-off、Flash-on high、Pro-on high 每例各一次，共102个逻辑条件案例；case-major轮转，配置和顺序由技术验收冻结。首答为主指标，repair/final为次指标。

本轮34例足以诊断，不加新样本。后续泛化检验另立 fresh holdout 版本。本文只新增验收标准，不修改产品、工具、历史证据或gold；编写阶段Provider/DB/测试均为0。

## 分层指标

|层|通过标准|分开记录的情况|
|---|---|---|
|F 事实/未知/联合推理|处理目标故事命题P；主体、动作、对话归属、时序及必要联合前提正确；no_issue有针对性相容理由|未知≠否定；来源不能担保P≠证明not-P；不能只给正确标签或泛称“关系不明”|
|C 类别|实际Issue符合原gold；manual_variant需说明理由|类别错不自动令F失败；不从旧case_id里的类别词猜gold|
|E_roles 证据角色|正确区分一般前提context与直接contradicts；不足为context/insufficient+missing_link|联合结论正确但角色倒置，可F通过、E_roles失败|
|E_set 证据集合|同一Issue满足一个冻结最低集合，额外证据限冻结optional集|真实且选中的额外来源仍可能集合违规，不能统称幻觉|
|E_binding 绑定/支持|claim、selected span、父chapter、Memory及正文支持正确；final适用来源字段对应输入|Memory知道某span不等于允许引用它；区分越界、错主体、正文不支持|
|S 结构合同|JSON/schema/claim/ledger一致，basis非空且≤400 Unicode code points；原chain/temporal/actions合同不变|可见理由正确但JSON/长度不合格，结构仍失败|
|D 实际交付|应有冲突/不足Issue时真实交付；无冲突合法空结果|正确不足basis+issues=[]：F可通过，D/完整失败；terminal不是no_issue|
|T 时间/操作|同体同刻和直接反证锚点符合原policy；变化不倒推；建议有支持|只有context带时钟不能担保动态反证；不足不得升级操作|
|Strict 完整|F及全部适用层通过；final另须实验引擎completed及适用输出合同；本轮不新增API持久化验收|repair/normalization/fallback不能回填首答分|

F取pass/fail/partial/unassessable；C/E另列not_delivered与N/A。正确no_issue的类别/显式引用可N/A，但F理由仍须通过；21个预期Issue的交付覆盖单列，不用已交付的小分母掩盖遗漏。basis与Issue实质矛盾时，不能挑正确部分让F通过。只评可见理由，不推测隐藏思维。

每条件首答报strict /34及分组 /13、/10、/11，同时列全部分层计数与适用分母。无法解析、预算或服务失败计严格未通过，归因单列；F无法观察时不伪造语义错误。尚未完成先pending，结束后封分母；可评子集比例必须同时给全34分母。

逐例报三组win/loss/tie及失败层。repair分报尝试、结构恢复、语义恢复、完整恢复与变差；final报完整通过、completed/terminal及归一化贡献。

## 冻结判定依据

34例身份取V7 cases；类别、最低/可选来源集合、允许outcome与temporal变体沿用V7 `score.py::policy` 引用的原冻结gold，不另手写或替换。正确no_issue不要求输出类别；原gold允许state_change时按原支持集合审阅。

重点边界保持不变：故事P未知不变成反向事实；规则/事实及身份/属性联合证明不可拆漏；具名行为/责任缺口保留动作主体；谎言台词不当叙述事实；回忆不当当前状态；合法新事件/后续获知不自动报警；未selected来源不得由Memory升级为可引用span。

## 对照流程与统一记录

技术人员冻结条件映射、顺序、模型/thinking实际参数和输入。模型不得收到gold、预期类别、case-family/outcome标签、旧成绩或审阅标准。三组业务内容、claim IDs、schema和模型提示词完全固定；共同预算/超时及差异按PLAN披露，不暗改repair或评分口径。

Root提供每例重新随机代号的匿名packet：保留完整业务内容与输出，隐藏model/condition/thinking、路径标签、机器评分、成本时延和历史成绩；原证据不改并保留映射。先独立评分后同例对照，锁定首答后才读repair，再读final；保留raw first与first parsed，不能挑更好的后续答案冒充首答。分歧按冻结policy裁定并保留初判；评分锁定后揭示条件。身份泄露或风格猜测需注明，不声称严格双盲。

每条统一记录：`case_alias / response_alias / stage / reviewer / condition_visibility / output_availability / policy_ref / F,C,E_roles,E_set,E_binding,S,D,T / strict / observed_decision / actual_issue_count / findings(短理由+原文短引+匿名证据定位) / attribution_tags / locked_before_reveal / adjudication`。配套JSON提供模板。技术归因尚无trace时注明待核，不能把模型错误自动归于产品。

## 预算、成本与结论边界

8000预算具体含义、有效API限制及thinking占用由技术验收另报；相同数字不保证相同可见输出空间。截断/限额/无答案单列配置兼容性，strict如实失败，不能据无答案断言已证实推理错误。

首答与含repair总账分别报token、费用/不可得、请求及端到端时延；usage完整/部分/未知分开，缺字段不是0。reasoning/cache仅按实际字段报告，避免与total重复相加；估价标来源/日期。延迟说明排队、重试，不能当纯推理时间。

Flash-off对Flash-on有限观察同模型thinking差异；Flash-on与Pro-on同叫high不代表计算相等。每例一次，仅能说明这组开发输入的观察，不是盲测泛化、统计稳定性或模型家族能力上限。来源hash与34例索引见配套JSON。
