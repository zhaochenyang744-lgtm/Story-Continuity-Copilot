# V13 短文本留用集

6 部全新作品，中英文各 3 部；每部 8 章，共 48 章、36 题。三种判断各 12 题，每部各 2 题。12 道冲突题覆盖全部 8 类，恰好 3 道指定回归题。题号从 `hv13-001` 连续至 `hv13-036`。

本集用于长文本项目第 4 阶段结束时的一次短文本回归评测。本次仅完成创作、静态检查和语义自查，没有运行模型评测。

## 文件与输入

- `cases.json`：完整 Markdown 原文、独立草稿和金标；顶层仅含 `version`、`author`、`corpora`、`cases`。
- `sources/`：6 份完整原文，与 JSON 中相应 `source` 的 UTF-8 字节一致。
- `check.py`：从 V12 检查器逐字节复制。
- `cases.sha256`：通过检查后计算的 `cases.json` 文件字节 SHA-256。
- `authoring/pair-*.json`：直接创作的题目、作品元信息和逐题审阅记录，用于打包完整原文。
- `authoring/content-review.json`：汇总后的逐题理由、逐条证据共享名词、改写与缺环核对。
- `authoring/novelty-review.md`、`authoring/names-check.json`：旧集名称检索与具体情节比对记录。
- `authoring/final-novelty-snapshot.json`：冻结前再次全量检索的最终旧文件快照及新增章节补读记录。
- `authoring/cross-review-a.md`、`authoring/assertion-audit.json`：协作逐题复核与原文一致性、复句和提示措辞核查。
- `authoring/scope-baseline.json`、`authoring/closeout.json`：工作范围基线、最终数量、哈希及冻结核对。
- `authoring/check-output.txt`：检查器完整输出。
- `authoring/delivery-report.md`：桌面交付报告的相同字节副本，仅包含输出、哈希、数量、自查和问题记录。

作品字段仅为 `key`、`title`、`language`、`source`。原文从一级标题开始，每章正文不超过 300 个 Unicode 字符，标题在作品内唯一。题目字段仅为 `id`、`corpus`、`draft`、`expected_class`、`category`、`evidence`、`designated_regression`、`note`；证据引用完整章节标题，不含 `# `。

同一作品每次整篇替换 draft；各题独立，均为一段 1–3 句，只考一个主要判断点。金标和 authoring 记录不作为模型输入。

## 创作与语义核对

六份原文均直接逐章创作。打包程序仅读取已完成的全文、加入作品元信息并序列化 JSON，不生成、拼接或替换章节正文。

全部证据章节逐条核对共享人物、物件或地点。草稿保留共享名词，改写事实表达；冲突草稿直接写自身事实。原文以正常叙述承载事实，证据不足的缺环由叙事自然留下；只有永久世界规则采用直白禁止句。无冲突题均有原文直接支持，证据不足题逐题说明实质缺环，不以缺共同时间替代缺环。

指定回归题为 `hv13-001`、`hv13-013`、`hv13-025`：分别依据永久禁止规则、同一完整时间锚点、同一完整时间锚点，要求明确矛盾及相应类别。静态及作者审阅确认这些文本约束，本次未测试产品时间抽取或模型判断。

## 检查及冻结

在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -B evaluation\eval_set_v13_authoring\check.py
```

检查器输出 `PASS` 且 `0 ERROR` 后再计算并写入 `cases.sha256`。哈希落盘即冻结；此后不再修改 `cases.json`，仅重读验证。该检查器不判断语义金标是否正确；逐题语义与新颖性审阅属于另行完成的内容自查。

本任务只新增 V13 文件和桌面交付报告，不修改旧评测集或产品代码，不调用模型接口、不访问 API key、不进行模型运行或评分，不提交、不推送、不切换分支。
