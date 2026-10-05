# V3 G03 fixture 独立验收

日期：2026-09-26。范围仅为 V3 四个 G03 fixture 的一致性、完整业务请求等价性和 V2 原证据保留。结论：**通过；本范围无剩余阻断。** 不需要为此次 fixture 生成器修复补充真实模型调用，也不产生新的模型质量分数。

## 独立结果

仅按 `runs/offline-equivalence-20260926-01/workspace-manifest.json` 的四条精确路径，以 SQLite `mode=ro&immutable=1` 读取新合成 DB。四例均满足：

- 两章正文与自身 SourceSpan 全文逐字相等，同时与原 case 期望文本相等；chapter summary、outline summary 等于对应正文前 180 字。
- project/source span/chapter 的 source_revision 均为 1，Memory version 为 1。
- 唯一 Memory 的完整字段为 `author_confirmed / dynamic_state / 星钥 / holder / 星钥始终由乔霁保管。`，绑定第 1 章 span；ID、来源、版本、类型和 review_status 均一致。
- short 目标正文 20 字；deep 与 other 为 1510 字、事实下标 1100；absent 正文 26 字且无目标事实。other 第二章实际为触碰/交还干扰正文，未保留旧“无保管事实”正文。

V3 现在同时写章节、SourceSpan 和摘要（`fixture.py:62-71`），数据库检查覆盖正文、来源 revision、摘要和完整 Memory（`fixture.py:19-44`）；请求检查补上了 `memory_type`（`fixture.py:47-51`）。本次未重复主控负责的三项 offline tests。

## 等价性不是仅比较两份报告

独立脚本首先重算四份保存的 V3 完整请求 SHA-256，并与对应 V2 真实业务请求逐字段比较；没有删除、归一化或忽略任何字段。然后从四份新数据库各自真实持久化的 `v2_analysis_inputs.input_json` 读取 API 输入，经当前 `WritingAnalysisEngine._request` 纯函数补入产品输出 schema，重建模型业务请求。**这些重建对象也与 V3 捕获及 V2 真实请求完全相同，4/4 通过。**

| 案例 | 完整请求等价 | 请求 SHA-256 |
|---|---|---|
| short | 通过 | `de140b22029c3ab345d7a1d7e8bca69b4b024d64a22ae873cb1af59dd3bdcbb2` |
| deep | 通过 | `fb4be4f58892a1c54aa244d1850400b72ca596d40bd91872b22c02012b63a52b` |
| absent | 通过 | `87e4258a5bb654c8c777e0ddfbcf78a3d629185400375291d475fb82c823ca15` |
| other | 通过 | `2128c1bad9d1087ff5f3ac47e95c7263a6f00962ea698fcd950c0f791c4620f3` |

新 DB 各有一次独立 change_impact Run、一份持久化 analysis input 和 result，Run ID 均不同于 V2 真实 Run；tokens 均为 fake 的 1/1。它们是独立产品运行的记录，不是 V2 结果表复制。

源码也支持这一链路：`offline_equivalence.py` 只替换 DeepSeekProvider.evaluate 为进程内 fake，仍通过 `fixture.create_case_runtime` 和 `v2.analysis` 调用真实产品 API，再取 `ObservedProvider.business_requests` 捕获；读取 V2 baseline 文件发生在 API 执行和捕获之后，只用于比较。未发现从 V2 请求直接复制来充当新输入的路径。此次独立核查没有执行该 capture 脚本或创建新运行。

## 冻结、保留与结论边界

- V3 start 清单及 V2 frozen-inputs 所列源码/输入 hash 全部与当前文件一致。四份新 case、baseline 记录及清单在独立核查前后 hash 不变。
- 四份 V3 DB 的大小与 hash 匹配其 manifest；八份旧 V2 DB 仅做文件 hash 检查，没有打开内容，全部仍匹配 V2 workspace manifest。共 12 份 DB 前后 hash 不变。
- 仅新增 `fixture-diagnose.py`、`fixture-results.json`、本报告。诊断脚本网络/SMTP 禁用，sqlite 连接白名单只接受四份 V3 DB 的精确只读 URI；没有构造 Provider。网络、SMTP、Provider 调用 0。
- 此项关闭的是生成器正文来源不一致和 Memory 类型漏检。V2 原 DB 的缺陷保留为历史证据；V3 的完整一致 fixture 和模型输入等价不倒写 V2 历史，也不是第二次真实模型复现。V2 SourceSpan 层真实观察仍按其原始输入评估；G02、V8、产品语义效果和发布结论不在本次范围。

可复跑：将 `fixture-diagnose.py` 复制到 `evaluation/current_flash_v3/` 下一个全新同层证据目录，再执行 `.venv/Scripts/python.exe -B <新目录>/fixture-diagnose.py`。结果独占创建，任何源文件或 DB hash 漂移会停止；不覆盖本轮结果。
