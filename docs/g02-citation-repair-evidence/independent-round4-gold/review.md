# V3 限定末轮 gold 复验

2026-09-26。**本分工接受 V3 作为后续评测的已暴露开发材料准备版本；R3-1/R3-2 的 gold 阻断已关闭，未发现新的明确误罚材料。** 此结论只覆盖最小来源、类别与未变语义的继承，不替代其他分工对评分、运行器或 capture 的独立验收，也不授权真实 Provider 调用。

## 身份与继承范围

V3 manifest：`0afd9630d22aecc44d1fbc8a955787d12d1286b31ec85a3e0985dff132da8baf`。cases：`99cf17ca8391be0438164eabecebf181f6e88b5f6a11cd20fb15f913854716f0`。完整读入文件哈希和独立比对结果见 `incremental-results.json`，收尾前后身份见 `final-receipt.json`。

仅用标准库读取 V3 HANDOFF/RUBRIC/HISTORY_GAP/build/cases 和其引用的 V2冻结资产，辅以当前 provider 的类别定义。没有运行原生成/评分/测试入口，没有调用 validator、API 或 Provider，没有打开数据库。

增量比对确认：

- 24 个 V2→V3 案例一一对应；24 个 target_draft、目标序号、corpus_key、expected_class/category/nature、allowed_outcomes、temporal_policy 均未改变。
- 8 个 conflict 的 decision_category 不变；V2 四个 corpus 文件全部仍匹配其冻结哈希，因此沿用上轮24例三分类和8个冲突核心类别的人工接受，不重做整套语义审判。
- V3引用的24条业务请求就是原 V2 capture 文件，SHA-256仍为 `b55eba3b0aa4e8881c22d2ef0646de5303522cc2215a5d6e1a33c1c2ab26913c`。这证明本轮复用同一冻结输入身份，不宣称新执行了24次 API。
- 本次读取的 manifest 绑定文件全部匹配；读取期间无变化。Provider/HTTP/数据库连接均为0，所有新增文件只在本目录。

## R3-1：规则单条最小、名单可选——通过

`ccv3-north_glass-world_rule-conflict` 的正式字段一致：

- `minimum_sufficient_evidence_sets=[[badge_rule]]`
- `expected_evidence=[badge_rule]`
- `recommended_context=[badge_roster]`
- `requires_all_expected_evidence=false`

label_reason 现在明确草稿自身提供“只戴红徽章”，所以蓝徽章规则一条即可反驳；名单仅为同刻佐证。这与实际故事逻辑一致，关闭前轮“强制两来源”的材料问题。

## R3-2：八条不足的实际核心类别——有界接受

类别裁定依据当前产品定义及实际缺口，不依据 validator 能否接受一个枚举。全部仍是 insufficient_evidence；未知的角色/原因/先后不能被说明文字提升为已发生或绝未发生。

| 不足断言 | V3类别 | 独立判断 |
|---|---|---|
| 11点徽章持有人是Mira | object_state | 接受。核心是命名物件在指定时间的持有状态，非开门规则 |
| Mira松开阀帽 | relationship | 在当前“命名人物责任/角色”定义下接受。待证的是实施者归属，非帽松状态 |
| Sera授权再次开门 | relationship | 接受。明确为命名人物授权关系，不是开关先后 |
| Vela担任送信者 | relationship | 接受为递送角色/责任归属。材料没有在问Sera知道什么，也没有具体递送地点问题；不能继续沿用knowledge轴类别 |
| Nera出生早于Oren | timeline | 接受。核心是出生事件先后，亲属关系只是背景 |
| Tala导致延误 | relationship | 按产品对命名人物责任归属的定义接受，完成状态不是缺口 |
| Vela磨制R4 | relationship | 按工作实施者/责任归属接受，非玻璃固有属性 |
| Sora陪Vela到东侧 | location_action；relationship为人工候选 | 两种读法均有依据：具体移动中的同行行动，或同行角色关系。接受预声明候选范围，不自动裁定任一模型回答正确 |

cap actor/courier/grinder 等属于这套产品分类法下的责任或角色判读，不声称这些类别是脱离项目定义后的唯一通用分类。当前没有与项目核心定义明确相反的强制类别，因此不再以可能存在别的分类体系要求扩张本轮。

companion 明确使用 `manual_variant`、候选 location_action/relationship；RUBRIC 与 score 的状态说明保留 `pending_manual_adjudication`。结构允许并不等于类别准确，未来逐答需看模型是否正确说明“记录未指明同伴”，再人工裁定。这个边界诚实，可以进入评测准备，不必先伪造一个唯一确定类别。

## 时间说明与历史审计边界

原轴级 time_scope 已更名为 axis_time_context；每例新增 case_time_scope，包含自身草稿与来源文本，不足例的 note 已分别指明11点持有人、13点递送者、出生先后等实际缺口。前轮“用10点开门说明11点持有人不足”的混淆已从正式 case-specific note 中移除。

有一处**非阻断元数据残留**：world_rule conflict 的 `case_time_scope.minimum_source_texts` 仍包含 rule 和可选 roster 两段，因为 build 在改最小集合之前生成此展示字段。正式最小来源、expected_evidence、可选字段及理由均已正确；本轮未发现评分引用该说明字段来强制 roster。以后整理该字段时应只列rule，或明确其包含可选上下文。本备注不撤销R3-1接受，不要求为此新增评测或改写当前冻结。

HISTORY_GAP 明确区分：V2早期24完成/8通过仅有书面摘要，缺少完整首次逐例失败链；V3不重建或冒充原记录。targeted-controls-01的类别混杂也被保留并说明由-02提供隔离负控。本分工接受此披露的诚实范围，不由文档披露反推历史链已经完整。

V3继续是seen-development，故事模板和V8/V1/V2派生关系没有被包装成未见评测。24例语义继承与本轮类别接受不代表模型成绩、盲测泛化、产品发布或用户验收。

## 结论

可接受准备范围：继承的24例三分类语义、8个冲突类别、五条不足最小/可选来源、两个合理state_change允许结果，加上V3单规则最小证据和上述八条不足类别政策。**本分工无剩余阻断项。** companion逐答人工裁定、小样本/已暴露性质、历史首次失败链缺失及说明字段残留作为明确非阻断限制保留。实际评分/运行审计结论由主控合并其他分工后决定。
