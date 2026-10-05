# V9 模型对照复测：冻结计划

日期：2026-09-28。依据：V8 独立验收下一轮建议第 1、3 项，以及[评测集长期维护规则](../evaluation-maintenance.md)。

## 产品修改

V8 Flash high 第 04 例事实判断正确，但 `reasoning` 为 881 字符，被引擎未告知的 800 字符上限以泛化的 `schema_invalid` 拒绝，且没有进入修复。本轮修改：

- `MAX_ISSUE_REASONING_CODEPOINTS = 800` 由同一常量驱动 prompt 规则、output schema、validator 和修复指令；上限、按去除首尾空白后的 Unicode code point 计数的口径均未放宽。
- 超长改为可修复的 `reasoning_too_long`，诊断给出 claim、字段、实际长度与上限；首答阶段即与其他合同问题一起收集。仍只允许一次修复，重复超长以 `reasoning_too_long` 失败。原始输出不截断。
- 空白、非字符串的 `reasoning` 仍为不可修复的 `schema_invalid`。
- prompt 版本升为 `continuity-review-v18-reasoning-length`。

离线证据：`backend/tests/test_v9_reasoning_length_contract.py` 6 项，读取 V8 04/flash-high 原始首答作为 fixture。用新 validator 重验 V8 全部 102 份首答：只有该例超过 800，且由终止失败变为可修复；其余首答判定不变。后端全量 397 项中 9 项失败，与 HEAD 原版逐项相同，均为既有失败。

## 评测设计

| 项目 | 固定值 |
|---|---|
| 输入 | V7 `prep-v7-01` 的 34 个已见开发输入；仅 `output_schema` 替换为 v18（逐例断言其余字段逐字相同） |
| 条件 | Flash high（主候选）、Pro high（质量对照）；与 V8 同参数，`max_tokens=32768` |
| 次数 | 每条件每例 1 次；共 68 个条件案例 |
| 上限 | 272 次生成 POST、1 次 models GET、1,000,000 已知 token 停止阈值 |
| 预算 | 实验引擎单次 40,000（仅限 `engine.execute` 内），逐响应记录原 8,000 兼容性 |
| 评分 | V7/V6 金标与评分口径、V8 语义标准不变；机器评分之后需人工语义复核 |

对比方式：先与 V8 同条件逐例比较首答、修复和最终完整通过，再单列变化案例的原因。prompt 新增一条规则，影响不限于第 04 例，因此不能把全部分数变化归因于长度修复。

## 不在本轮范围

未见样本集、跨语言新样本、重复运行稳定性、原预算端到端、检索/数据库/API 完整链路、生产模型切换与发布。本计划不授予上线或模型替换结论。
