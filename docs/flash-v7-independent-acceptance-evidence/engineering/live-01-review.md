# V7 独立工程验收

结论：技术通过。此结论只覆盖工程账本与证据链，不替代语义、用户或 release 验收。

- 34 个逻辑案例均收尾；产品结果为 33 completed + 1 failed（22：evidence_unresolvable）。该失败保留原答及实际引用越界，后续案例继续执行；不是服务停止。
- 40 POST start/finish/HTTP200 一一对应，0 unfinished；1 models GET200；6 次 repair（03/12/18/21/24/28）。完整首答 issues/claim_verdicts 和逐 claim/字段诊断均进入第二次请求，首失败链保留。
- 40/40 raw 内容哈希和 parsed JSON 完全一致；HTTP body 独立重建哈希全部吻合，确认单 user 消息、完整 repair、thinking disabled。所有 basis 均在400字符内，最大388。
- usage complete40，missing/partial/unknown均0；136159 input +11938 output =148097 tokens。费用未知，保留null。0 not-run、0 uncaught failure、0 normalization、service-stop=false。
- 632/632 冻结文件与manifest一致；V6原run420/420不变；本run 375 个文件读前后稳定。34份同次runtime-binding与V6对应快照一致，所选Source/Memory与实际request逐项匹配。
- API顶层source_revision表示draft revision，真实Source/Memory版本依据runtime-binding核对；未将API字段误作独立章节revision证据。敏感字段/令牌模式扫描0标记。

本次只读JSON、源码AST字面量和文件哈希；未执行Provider、SQLite、runner、scorer或测试。数据库核对限于保存快照，服务停止条件继承先前离线验收，本轮全200未触发。完整逐例记录及读前后哈希见live-01-review.json。
