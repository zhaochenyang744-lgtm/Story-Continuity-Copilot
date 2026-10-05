# Post-V4 第二轮独立语义复验

2026-09-26。**time-bound 和 dialogue 两个上一轮 P2，在本次限定的离线产品行为范围内可以关闭。** 本轮没有新的真实模型调用，也不把改过的对话输入与旧答复当作新版模型成绩。重复、摘要凝练和对象分类三个 P3 仍保留。

本轮读了正式 `POST-V4-HANDOFF.md`、实施者的离线 replay 入口及必要源码 / API 测试，随后自行执行新的独立探针，没有运行或覆盖实施者 `results-v2.json`。只在当前独立目录创建脚本、结果、哈希清单和全新的临时合成 fixture；未读取真实业务库、凭据或 `.env`，未修改产品、V4 原始结果及旧报告。浏览器、完整回归和比较集由其他审阅负责，本报告不作相关结论。

## 执行范围与证据

- `semantic-probe.py`：独立执行入口。4 次直接调用当前 `WritingAnalysisEngine.validate`，输入 / 模型 JSON 均原样取自 V4 保存记录；另建隔离项目，使用 TestClient 走注册、添加计划、保存草稿、创建 context_brief、两次 GET 重读的产品 API。
- `semantic-probe-results.json`：保留四次 validator 最终结果及一份新 API 实际业务请求、固定脚本答复、持久化结果、检查明细。没有保存测试账号注册响应或 session / cookie。
- `hashes-before.json` / `hashes-after.json`：六份 V4 case JSON、三个当前产品文件、实施者 `results-v2.json` 共 10 份文件，前后 SHA-256 全部相同。
- 探针 172 项结构、范围、来源 ID / excerpt、持久化检查全部通过。这个数量随来源数增长，不是 172 个独立故事样本，也不是模型准确率。随后人工阅读了四个 replay 和新 API 的完整 summary、items、来源和覆盖信息。
- 真正的外部 Provider 调用为 0；fresh API 中的 scripted provider 在内存中执行 1 次。脚本禁用默认 app 初始化，显式指定新 fixture 路径和测试 settings，并阻止外部 socket 连接。

## 1. time-bound：旧真实首答原样离线重放，P2 关闭

重放的是 V4 `05-g02-time-bound.json` 的完整业务 request 与其唯一真实首答，**未改输入、ID、raw summary 或 raw items**。它原来“summary 正确、12 个 items 没有草稿”的状态原样进入当前 validator。

当前最终前两项分别为：

> 当前草稿句1原文：「昨日温岚尚未得知银钥匙的用途。」
>
> 当前草稿句2原文：「今日她读完陈澈的信，才知道银钥匙能打开潮汐档案柜。」

两条 item 各引用自己的 D1 / D2，excerpt 含完整对应原文。最终 summary 同时包含这两句，并自引 D1、D2；第三项是第 4 章所选原文，来源亦对应。昨天 / 今天、未得知 / 才知道、读信后的知识变化全部保留，没把两个时点合并成恒定未知或恒定已知。

`draft_coverage=covered`、无 uncovered ID、无 reasons；`fallback_draft_claim_ids` 记录 D1 和 D2。最终 12 项：两条草稿在前，剩余保留 10 条背景，`overflow_omitted_item_count=2`。省略的是原首答最后两个可选背景条目（第 9、8 章），没有再挤掉当前草稿的新知识事实。这一取舍比旧结果“保留大量背景、丢掉今日变化”更符合本例用途。

源码对应：`engine.py:520` 起补全部遗漏的 selected draft claims，`:531` 起在 12 项上限前为草稿预留位置，`:542` 记录 overflow。结论是**同一已保存输入和模型首答在后续产品 validator 的行为改善**，不是模型首答质量提高；旧 V4 首摘要的其他背景自身引用缺口仍作为历史结果保留。

## 2. dialogue：新隔离产品 API + 正确映射新 ID，P2 关闭

这次没有把旧三片段 request 直接送给 validator 来冒充新切分。独立创建了新的合成项目，保存 V4 同一个完整正文，使用最新 API 实际构建 context_brief 输入。新输入中的 draft claims 正好为：

1. `陈澈说：‘温岚已经把潮汐表交给林默。’`
2. `温岚摇头说：‘我没有交出潮汐表，它仍在我的背包里。’`

两段连接与原正文完全一致，字符范围为 `[0,19)`、`[19,45)`，各带说话人和自己的闭引号，没有标点 claim；两条均未截断。

固定脚本取旧 V4 对话前两个 item 的**说话人归属措辞**，将引用映射到此次真实新 request 的两个 claim ID。为检验分类还故意把这两条脚本 section 写为 confirmed_fact。它不是实际新模型返回；脚本的两个 Memory / plan 反例也明确是人为合成。

最终 API items 与两次持久化 GET 重读的 analysis 完全相同：

> 当前草稿句1原文：「陈澈说：‘温岚已经把潮汐表交给林默。’」
>
> 当前草稿句2原文：「温岚摇头说：‘我没有交出潮汐表，它仍在我的背包里。’」

两条最终 section 都是 recent_source；summary 同样保留完整两方引语，自己的 summary_sources 指向对应完整 claims。`covered`、无 uncovered ID / reasons，未再因孤立闭引号显示 partial。

人工语义判断：表述仍是“陈澈说”和“温岚摇头说”，保留对方否认“我没有交出”，没有判定谁说真话，没有把背包状态或交接变成叙述者确认的事实。因此不仅是“输出等于来源”，说话框架、否定、完整引号和最终类别也通过本例。

源码对应：`brief_citations.py:18` 的新 splitter 及 `v2_database.py:2973` 的 context_brief 调用入口。仅验证此种两段中文单引号和实际正文；未证明任意嵌套引语、英文直引号或不闭合原文都能处理。

## 3. 新 API 中的知识否定与计划层级正控

同一个 fresh API 固定脚本另给出两个故意不正确的自由转述，所引记录是真实新 request 中选中的记录：

| 合成脚本输入 | 真实所引资料 | 持久化最终行为 |
| --- | --- | --- |
| “温岚已经知道廊桥钥匙的含义。” | character_knowledge / does_not_know / 廊桥钥匙的含义 | `character_state`：“已确认记录：温岚不知道「廊桥钥匙的含义」” |
| “林默已经把星钥交给沈砚。”，故意标 confirmed_fact | `planned` 的 story plan，内容明确是未来安排、尚未写入正文 | `related_plan`：“作者计划记录……”且完整保留“计划在下一章”“尚未写入正文” |

两项自己的来源均解析到实际请求记录；计划还进入最终 summary，自身 summary_sources 包含该作者计划记录。未把未来计划升级为既成事实，也没有通过删除所有信息来回避风险。

该正控只证明**当前产品对这份固定脚本和已选资料的保守呈现**，不证明模型能正确判断知识真假，也不验证计划本身的排期一致性。肯定 `knows` Memory 和更复杂计划合并仍不在此范围。

## 4. 三个受影响常见正控

这三例同样使用旧 V4 真实首答与完整原 request，只有 validator 是后续版本。

| 正控 | 人工核对结果 |
| --- | --- |
| long-sentence | 299 字 D1 完整保留，尾部交钥匙与弟弟存活在 item 和 summary 中均有自己的完整 D1 引用；“看得懂坐标”引用第 4 章原文，不依靠 does_not_know Memory；否定知识记录仍是“不知道” |
| three-sentences | 三个草稿事实各自完整引用并在摘要保留；“她”沿用原文，未新增身份绑定；非空壳，其他 Memory / 来源条目仍有内容 |
| identical-text | 两个同文 claim 均可寻址且 covered；第 9 章月牙裂纹有自身完整 source span，未丢其他核心来源事实 |

四次 replay 的所有最终 item / summary 的引用 ID 与 excerpt 均逐一对应实际 request，最终 item 数不超过 12，summary 不超过 400 字。这里的检查不替代上面人工核对的谓词、时间、说话人与类别。

## 尚未关闭的限制

- **P3，重复与顺序**：identical 最终仍为“句2原文……句1原文……”双重同文，`duplicate_omitted_item_count=0`；当前去重没有将不同 source ID 的同文内容合并。这不是虚构两个事件，但摘要效率和顺序仍欠佳。
- **P3，长句摘要凝练**：long-sentence 最终仍把长廊句重复 28 次搬入 summary，重要句尾保留但摘要冗长。安全引用不等于精炼总结。
- **P3，对象类别**：航图地点依旧落在 character_state；`brief_citations.py:180` 仍把 dynamic_state 统一映射为角色状态。地点事实正确，分类不精确。
- body-limit 未在本轮再次执行；更长截断草稿、上限压力的广泛回归与浏览器由主控另行验收。不要将此次两个 badcase 的关闭扩大成全部草稿范围、任意引语或整套 UI 通过。
- 产品重建依然没有把旧 raw answer 变成正确首答；所有旧真实结果和上一轮评价保持有效。当前没有后续真实 Flash 结果，因此不能报告新版模型成绩、真实作者效果或发布 Gate。

## 探针首次失败的保留说明

首次执行在 TestClient 进入 Windows asyncio 事件循环时失败，尚未执行该 API 请求。原因是独立探针对 `socket.socket.connect` 的全禁把标准库 `_fallback_socketpair` 构建本地 self-pipe 也拦截了，异常为 `AssertionError: External socket connection prohibited in this probe`。这是探针防外连实现过宽，不是产品缺陷或 Provider 失败。

只修改了本目录的独立脚本：仅在调用栈是标准库 `_fallback_socketpair` 且目标为本机 loopback 时放行；其他 socket connect 仍禁止。第二次执行通过并生成 create-only 结果。首个失败创建的临时 synthetic fixture 仍保留，没有删除或冒充成功结果；未覆盖已有产品或评测证据。

## 版本与复跑

本次实际源码 SHA-256，执行前后均一致：

| 文件 | SHA-256 |
| --- | --- |
| backend/app/engine.py | `4d3a07e955aadfaf1ecd31281ccca0d4fb3f36014756b801d906b193e15984c7` |
| backend/app/brief_citations.py | `a0a3a31251860265c29b09a95e85b27f05d92dc1a0e6bcc0a9d1736a57b28ccc` |
| backend/app/v2_database.py | `2485b997c32dda446325fe1535df0342330b09afdd53b9619137ad824a17e754` |

原始执行命令（工作目录为本 worktree）：

```powershell
.\.venv\Scripts\python.exe docs/g02-citation-repair-evidence/independent-round2-semantics/semantic-probe.py
```

结果文件使用独占创建，不能直接复跑覆盖。复验时将脚本复制到同级的新独立证据目录再执行，保持同级目录深度即可；脚本会为该次运行新建独立合成 fixture。无需真实 Provider、外部服务或历史数据库。
