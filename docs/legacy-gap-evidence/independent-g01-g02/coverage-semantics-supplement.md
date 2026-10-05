# G02 覆盖语义补充探针

日期：2026-09-26。仅追加两项窄范围离线探针，原 `probe-results.json` 与首次验收记录保持不变。

输入正文共 30 字、三句互不重复：“林默走进北门。银钥匙已经交给陈澈。她此时已经知道弟弟还活着。”三个完整主张全部在输入内，`available=selected=3`，所有截断标志均为 false；另有一条完整历史来源“渡口昨夜已经封锁。”。

| 模拟输出 | 实际产品结果 | 缺失内容 |
|---|---|---|
| 模型只返回带引用的历史事实，由产品自动补草稿首句 | `covered / supported / reasons=[]`，仅引用草稿 claim 1 | claim 2 的钥匙转移、claim 3 的知情变化均完全缺席 |
| 模型只引用草稿第一句 | `covered / supported / reasons=[]`，仅引用草稿 claim 1 | claim 2、claim 3 同样完全缺席 |

结论：**覆盖误标独立于 240 字或 1200 字截断存在。** 实现目前只检查是否至少引用一条草稿主张，而没有区分“草稿已引用”与“选入的草稿主张已覆盖”。只修复截断标志不足以关闭这一语义缺口。未覆盖信息至少应明确保留为部分状态和范围；摘要不必逐字复述全文，但不能用一个首句引用证明剩余重要状态已经覆盖。

实现定位：`backend/app/engine.py:461–472` 和 `:490`。运行时文件 SHA-256 已写入结果 JSON，便于与返修版本区分。

证据：`coverage-semantics-probe.py`、`coverage-semantics-results.json`、`coverage-semantics-console.txt`。调用的是 `WritingAnalysisEngine.validate`；Provider 的 evaluate 被设置为一旦调用即失败，此次未执行 Provider、HTTP、SMTP、数据库或浏览器操作。只追加本独立证据目录文件，没有修改业务实现或既有测试。补充后停止，等待返修复验。
