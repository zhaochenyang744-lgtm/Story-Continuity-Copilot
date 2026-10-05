# V10 类别判定修复：冻结计划

日期：2026-09-28。依据：V7 NEXT-ROUND-HANDOFF 第 1 项、V8 下一轮建议第 2 项、V9 结果（剩余失败以类别为主）。遵循[评测集长期维护规则](../evaluation-maintenance.md)：不把案例 ID、金标或固定故事答案写进 prompt，不放宽冻结类别口径。

## 缺陷定位

汇总 V8 三组与 V9 两组首答中的全部类别错误（V8/V9 run 只读）：

| 金标 → 模型 | 次数 | 涉及已见案例 |
|---|---:|---|
| relationship → event_status / location_action / attribute / object_state | 19 | 06、12、18、21、28 |
| attribute → object_state | 5 | 19、25 |
| timeline → event_status / object_state | 3 | 07、15、31 |
| world_rule → event_status / object_state | 2 | 01 |
| location_action/relationship 可变体 → event_status / character_knowledge | 3 | 24、32 |

金标一致：V6 评分口径规定出生先后用 timeline、具名责任/授权用 relationship。主因是 v18 规则没有说明“记录了行为或结果、但未记录谁做的/谁导致的”属于归属（relationship），也没有说明时间锚点不改变固有属性；模型于是按动词或时间锚点分类。

## 产品修改（prompt v19）

仅替换 `CONTINUITY_REVIEW_RULES` 中的类别规则，其他规则、schema、validator 不变；prompt 版本 `continuity-review-v19-decisive-fact-category`。新规则的通用原则：

- 按决定性事实分类：直接反驳主张的那条事实；证据不足时则是缺失环节。不按动词、时间锚点或背景分类。
- 行为/结果有记录而执行者、原因或负责人未记录时，缺失环节是归属，用 relationship。
- 材质、成分、颜色、尺寸等固有属性即使带时间锚点也是 attribute；可变的运行状态、持有人、放置位置是 object_state。
- 只定义“什么算就绪/完成/允许”的规则是前提，按它所作用的记录状态或结果分类；仅当规则本身是唯一直接反驳、没有记录实际状态或结果时才用 world_rule。

## 新对照集 category-controls-v1

`evaluation/category_controls_v1/cases.json`，20 例，中英混合，均为新故事，文本不与 34 个已见输入重合。金标在任何 v19 调用前由实施者按 V6 口径写定并冻结；**未经独立标注，不是独立未见集**。设计为成对正反控制：

| 探测点 | 案例 | 期望 |
|---|---|---|
| 执行者/原因/送件人/下令人未记录 | cc1–cc5 | relationship |
| 执行者已知、结果未知（反向控制） | cc6、cc7 | event_status |
| 持有人未知（反向控制） | cc8 | object_state |
| 规则只是完成定义 | cc9 | event_status |
| 规则本身是唯一直接反驳 | cc10 | world_rule |
| 人物位置 | cc11 | location_action |
| 带时间锚点的材质 | cc12、cc13 | attribute |
| 运行状态（反向控制） | cc14、cc15 | object_state |
| 先后顺序 | cc16、cc17 | timeline |
| 亲属关系 | cc18 | relationship |
| 是否知道（反向控制） | cc19 | character_knowledge |
| 无问题（防误报） | cc20 | no_issue |

离线已证明：每例按金标构造的答案同时通过产品 validator 与评分器，换错类别则必判 `category_mismatch`；请求中不含金标字段。

## 评测设计

| 项目 | 固定值 |
|---|---|
| 输入 | 34 个 V7 已见输入（同 V9）＋20 个新对照；共 54 |
| 条件 | Flash high、Pro high（同 V9） |
| 次数 | 每条件每例 1 次；108 个条件案例 |
| 上限 | 432 次生成 POST、1 次 models GET、1,500,000 已知 token 停止阈值 |
| 评分 | 1–34 沿用 V7/V6 金标与评分器；35–54 用同一评分逻辑与冻结期望 |

对比方式：1–34 与 V9 同条件逐例比较；35–54 单列。类别之外的变化也要列出，防止规则改动引起其他退化。

## 不在本轮范围

独立标注的未见集、重复运行稳定性、原预算端到端、检索/数据库/API 链路、上线。单次运行的类别翻转已知存在，本轮结果不能作为稳定性证明。
