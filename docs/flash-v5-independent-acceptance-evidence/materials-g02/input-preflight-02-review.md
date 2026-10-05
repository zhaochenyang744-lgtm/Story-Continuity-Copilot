# Flash V5 / prep-v5-02：G02输入独立核对

结论：未发现本轮限定G02输入阻断。核对对象为准备运行25–30的离线stub实际业务请求，不是实模型质量、首答改善或真实30例验收。真实输出仍待逐条审阅。

仅标准库读取JSON、重算hash并交叉比对已有准备表；未打开DB、执行runner/产品或调用Provider。只创建本次review JSON/Markdown，原准备材料与读入记录不改。

| 序号 | 案例 | 正文字符 | 可用/选中/未选claims | excerpt字符 | 选中章节 | 输入结果 |
|---|---|---:|---|---:|---|---|
| 25 | g02-three-sentences | 30 | 3/3/0 | 30 | 4,8,6,10 | 限定通过 |
| 26 | g02-long-sentence | 299 | 1/1/0 | 299 | 8,6,4,3 | 限定通过 |
| 27 | g02-body-limit | 1980 | 180/8/172 | 600 | 7,6,10,9 | 限定通过 |
| 28 | g02-identical-text | 14 | 2/2/0 | 14 | 6,10,9,8 | 限定通过 |
| 29 | g02-time-bound | 40 | 2/2/0 | 40 | 4,10,9,8 | 限定通过 |
| 30 | g02-dialogue-attribution | 45 | 2/2/0 | 45 | 8,10,9,6 | 限定通过 |

六例正文UTF-8 hash、请求规范JSON hash、case-start对V5 case行hash均独立重算一致；所选4段SourceSpan的章节/标题/label/revision/原文/顺序与V4一致，8条Memory的type/subject/predicate/value集合一致，实际Memory→SourceSpan关系在各自runtime绑定中可解析。Memory指向未选SourceSpan允许存在（每例4–5条），不能据此把该未选原文当作模型已见证据。

新project/draft/claim/source/Memory及chapter身份集合在六例间互不混用。wrapper绑定、business_request、runtime和input-audit的身份/版本相符，draft为第11章revision2、source revision1、Memory version4；没有作者计划。selected-source的文本hash采用JSON字符串规范编码，saved draft与runtime span/chapter hash采用原UTF-8字节，已分别核对，不混用算法。

长句完整299字且未截断；长正文实际180句中选D1–D8，各有独立ID和offset，172句未选，excerpt600字。同文两句分别绑定[0,7)、[7,14)。对话当前两条完整引语分别为[0,19)、[19,45)，连接等于完整正文，未出现旧V4孤立闭引号第三claim。首答/修复/final的自身引用是否正确须在真实结果出现后另审。

## 父章节绑定与范围限制

六例runtime各有10条父chapter记录，chapter_body全部为空，但独立SourceSpan正文非空。已独立核对所选span的父chapter ID、标题、章节号与revision和runtime记录一致，span原文逐字一致；不能把这写成从完整章节正文中提取的证据链已核验。

主控已报告亲读_seed_grey_harbor：教学seed本来将chapter body留空而另存SourceSpan；当前context_brief供给written.draft/draft_claims/source_spans。本次据主控限定裁定作为非阻断披露，不补造章节全文、不改六例背景。不据本轮声称完整章节来源链、长篇稿件覆盖或完整源阅读验收。该seed实现解释来自主控；本审阅者独立核验的是已保存JSON。

## 审阅与执行状态

run start为prepare/offline-stub，summary报告30逻辑记录完成、HTTP/模型预检派发均为0，semantic_status仍pending_manual_review。本次未读取或评分stub final-product，不把准备记录当真实模型成绩。真实执行会产生新身份、新请求与结果，应再次绑定核对并分别审原首响应、首个可解析JSON、修复答及最终产品。

准备表中的三个P3（重复/倒序、摘要冗长、对象分类）和有限引语语法边界继续保留。历史正文/来源对应通过不使旧首摘要缺口消失；对话输入切分变化须继续限定历史对照。

读取文件SHA256、逐例检查及绑定见同目录 `input-preflight-02-review.json`。此次读取28份JSON，读前/读后hash一致；未改此前审阅记录。
