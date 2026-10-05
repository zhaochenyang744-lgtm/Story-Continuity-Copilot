# G02 source-rendered 修补：第一轮独立代码验收

日期：2026-09-26。只验收当前冻结的 `brief_citations.py`、`engine.py` context brief 路径及有界输入；真实模型逐例语义与浏览器由其他审阅者负责。

**结论：核心来源重建方向在本轮反例中有效，但整体不建议立即验收通过。** 独立纯函数测试发现一个可达的有用性回归和一个计数错误，建议在新修复证据中关闭。未发现本轮否定、时间、引语和主客体反例被提升为原模型的错误断言。

## 当前源码身份与方法

测试前后 SHA-256 一致，均匹配 V4 `frozen-inputs.json`：

- `backend/app/brief_citations.py`: `11a9b6f6c6f8d09ba85fe94c882cdbb7383e6ebb101bb5d1305212caf31dab69`
- `backend/app/engine.py`: `370952e8a0452b4cfe2da8b1a2a662534d0d98fe3d14ba13859aff2a9e3189d1`
- `backend/app/v2_database.py`: `540d74a4607639ecff2ea13e9d29ab99e0121a8f577930020a7707dd4bed8933`

测试只调用 `WritingAnalysisEngine(None).validate(...)`，使用内存合成字典。未实例化 Provider，没有网络、数据库、凭据访问。Python bytecode 写入关闭。所有新文件在本目录，未改产品和原评测证据。

`probe.py` 首次有一个独立测试脚本列表括号笔误；原文件保留，`probe-rerun.py` 仅在内存修正该括号后运行，输出 `results.json`。11 项中 8 通过、3 未满足预期；第三项是下述受限接口条件，不作为当前业务链路阻断。`cap-probe.py` 再用 12 条互不重复的合法模型分项收窄并确认容量回归，输出 `cap-results.json`。

## [P2] 来源展开挤占 12 条容量，丢掉模型已正确给出的正常草稿事实

位置：`engine.py:509–525`，尤其按来源拆项后的 `if len(items)>=12: break` 与只补首条 claim 的 fallback。

独立强反例 `cap-results.json` 完全符合现有输入限制：

- 四段已选来源，每段不足 500 字，各记录一座塔的灯色。
- 八条已选 Memory，各记录不同物件由顾遥保管。
- 三条完整、短小、不同的草稿事实，均已进入输入且没有截断。
- 模型恰好给出 12 条**不同且各有正确自身引用**的 items：第一条合述四座塔并引四个来源；之后八条 Memory；最后三条草稿。没有重复模型分项，也没有模型错误需要删除。

第一条重建为四条长原文后，前九条模型分项已经占满最终 12 条，后面的三条草稿分项被逐个跳过。fallback 仅补 claim 1 并再挤掉最后一个已渲染项目。结果：

```json
{
  "draft_facts_preserved": {"c1": true, "c2": false, "c3": false},
  "output_item_count": 12,
  "draft_coverage": {
    "status": "partial",
    "uncovered_source_ids": ["c2", "c3"],
    "discarded_item_indices": [],
    "reasons": ["draft_claim_uncovered"]
  },
  "citation_transform": {
    "model_item_count": 12,
    "source_rendered_item_count": 12,
    "omitted_unmatched_clause_count": 0,
    "discarded_model_item_indices": []
  }
}
```

partial 披露避免了虚称全覆盖，但没有解决新引入的有用性损失：本来已被模型正确提供的正常三句，产品只留下第一句。转换元数据也没有说明哪些有效模型项因展开容量被略去。

修复验收条件：在有界输出内显式分配草稿与背景的容量、去重或采用合适的分项/引用呈现，保留这三条短草稿事实。至少保证一条多来源分项展开不会无条件挤掉后续重要短分项；真实发生的容量删减必须有可复核原因和原始项关联。不能通过提高 schema 声称无限输出或把所有结果清空规避。首轮原反例与新的正控都应保留。

## [P2] 单个未匹配分句被记为两个

位置：`brief_citations.py:81–94`。

输入只有一个模型分句“外星访客夺走紫色皇冠。”，唯一可引用 Memory 是“星钥 / holder / 乔霁”。没有匹配候选时，循环在 `82` 行将 omitted 加一；fallback 在 `94` 行再次加一，最终 `omitted_unmatched_clause_count=2`。

最终重建的是有依据的乔霁保管记录，安全处理本身有效。错误在可审计计数：字段名表示未匹配分句数，却把 fallback 事件也加进同一数值。该计数不能拿来汇报删除了两条模型分句或评估改写程度。

修复验收条件：一个实际未匹配分句只计一次；fallback 可有单独标识。同时核对容量丢项与未匹配分句是不同事件，不混用或漏记。一个未匹配分句和两个未匹配分句必须有相应正控制。

## 已通过的有限范围

独立名称和内容不同于实施测试：

1. 正常三句分别有对应引用时，三个事实保留且覆盖为 covered。
2. 以改写措辞循环错引三条 claim，最终重建出正确绑定的三个原文事实。
3. “知道 / 不知道”相反断言：最终保留源段完整否定，不保留模型肯定断言。
4. 18 点未知、19 点才知道：最终保留来源的时序限定。
5. 明确谎言引语：最终完整保留说话归属、旁白纠正与未知状态；没有将引语当叙述者事实。
6. 主客体反转：最终显示实际交付关系的来源原文。
7. 坐标能力加知识未知、原模型只引 Memory：最终补上真实选中 SourceSpan，并保留有自身来源的事实。
8. 小于 540 字的长句尾部：尾部进入实际引用 excerpt，并在最终分项保留。

这些结果支持“相似度用于寻找候选，最终重新渲染实际来源”的实现方向。它们不证明原模型任意改写得到语义验证，也不证明所有长文本都能安全压缩。最终摘要没有采用测试中注入的自由模型摘要。

## 受限接口观察，不计本轮当前路径阻断

`brief_citations.py:45–46、124–125` 把 Author Context 的 title/name/content/summary/goal/planned_state/description 拼接成一个引用文本，而 `engine.py:462、478` 的清理引用只选第一个非空正文域。

纯 validator 输入若同时含 `summary="计划清晨关闭城门。"` 和 `goal="计划傍晚重新开门。"`，渲染文本包含两者，但自身 source excerpt 只有 summary，重现了字段组合与显示引用不一致。见 `results.json` 的 `author_field_own_excerpt_coverage`。

目前 `v2_database.py:2951、2958、2960` 构造 context brief Author Context 时将 goal 等并行域置空，每类只保留一个实际正文域，所以本次没有证明这一双正文输入能从当前正常 HTTP 路径到达。将其记录为 renderer/cleaner 输入契约的防御性缺口，不能夸大成当前真实用户可达失败。后续如扩展 Author Context 输入，需让渲染和引用使用同一投影。

## 范围限制

本报告没有检查真实 V4 每条模型输出、浏览器排版、实际调用计费或全工程回归。没有发现源码在检查过程中变化。本轮若修复上述两项，应保留 V4 冻结和本目录结果，以新结果文件与新冻结身份复验，不能覆盖这些首次失败证据。
