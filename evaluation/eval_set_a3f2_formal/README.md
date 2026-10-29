# A3 第二套正式留用集

依据任务33、A3 SPEC全文及补充三编写。补充三取消tidy，本集每部9道长任务（trace3、thread_audit2、ask2、narrowed2）与10道route，共38题。两部中文作品各30章，另有第31章600–1000纯汉字共享草稿。封存后开发方只运行检查器，不打开正文、题目、金标或authoring内容。

正文逐章原创，中心设定先行，按连续章节分批交接；程序只保存写定文字或做数字、位置、重复、结构及哈希核对，不生成或扩写正文。题目与金标由主控统一编写。未参与对应作品写作的人员全文审读，判断用法仅input/context盲判，伏笔另仅按起始伏笔和全文独立判定。

根目录运行指定解释器：`..\story-continuity-copilot\.venv\Scripts\python.exe -X utf8 -B -m evaluation.eval_set_a3f2_formal.check`。也可从任意目录以同一解释器和check.py绝对路径运行。检查器以自身路径定位，仅标准库、离线、只读本集及本集保存的旧语料查重快照，输出一行只有编号、计数和固定错误码的JSON。

纯汉字范围U+3400–U+4DBF、U+4E00–U+9FFF，不计标题。考点首字位置一基；半数严格>1500，并按A1c引用要求另核至少三分之一>2500。按章号与原引句去重，初始事实支持另计，不混入考点深度分母。数组引用从1起；动作章节使用完整标题，quote为正文逐字唯一的10–60字符片段。

范围含端点。scope为原请求范围；narrowed的scope为null，执行范围为更小的plan_edit.chapters。narrowed两题分别为trace与thread_audit，类型登记在本集自查run_suites。thread_audit只为范围内正文明确回收/放弃而资料未标的全部目标出动作，near_misses保持未收。ask为trace，decision_point归属于请求点名的对象，author_replies仅选择叙述版本，改动为空。

照抄检查request、input及after_points与本作品全部正文的连续八汉字；names仅列实际专名，并作为比较断点。新颖性去空白及Unicode标点，SequenceMatcher比值达到0.8报错。同句组只豁免本集内部相同输入，不豁免对历史语料的检查。现有题材核读和名称/输入查重在遍历前排除eval_set_a1_reserve、eval_set_a1b_reserve、eval_set_v13_authoring、eval_set_a26_formal、eval_set_a2s6_formal；零重合仅覆盖获准可读语料。

set.sha256按相对路径排序覆盖tasks.json和works/materials全部文件。独立复核另绑定正文、资料、题目与自查/查重记录。UTF-8无BOM、LF，.gitattributes保留封存字节。负向测试只在临时副本进行。未调用模型接口、未运行产品或评测；结构PASS与独立语义复核分开记录，不代表真实模型或上线门槛通过。

独立首轮/最终记录均须完整覆盖；检查器直接读取并重算每条状态与回收章、范围动作集合以及route投票，不接受仅改汇总数字或缩减原始文件清单。首轮输入及原始记录保留绑定；发生正文修订时，通过复读记录保留旧源哈希并重新绑定最终源。至少三分之一考点>2500沿用引用A1c第2节，作为本轮从严创作约束，不改登记门槛。
