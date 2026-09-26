# G03 独立验收补充：章节影响的目标原文绑定

本文件追加在首轮 `review.md` / `probe-results.json` 之后，未改写首轮证据。范围只涉及 G03「没有引用目标原文章节时不得下确定影响结论」，没有扩大到语义蕴含判定。

## P2：目标章 A 可以只凭章 B 原文被标记为 supported

- 位置：`backend/app/engine.py:502`；最终 `supported` 返回见第 505 行。
- 当前检查只要求 `area=chapter` 的 evidence 含任意 `source_span`，没有检查所引用原文的 `chapter_id` 与该影响项的 `target_id` 一致。
- 最小复现：输入的 reference.chapters 包含章 A、章 B；修改目标 Memory 来自章 B，且其直接来源 B 已选中；伪模型声称「章 A 明确写了乔霁持有星钥，必须修订」，唯一 evidence 指向 span-B。校验返回 `supported` 并保留章 A 的确定影响。
- 两种输入均可复现：① 章 A 原文也已提供，但输出完全未引用它，且 A 的正文只谈天气；② 章 A 只有引用目录元数据，原文完全没有召回。二者都没有目标章 A 的原文依据。
- 正控：目标章 B 引用 span-B 正常得到 `supported`。负控：仅引用 Memory、没有任何 SourceSpan，正确返回 `insufficient`。因此问题在于章节身份未绑定，而非缺少通用来源类型校验。

建议：对确定的章节影响项，至少要求一个被引用 SourceSpan 的 `chapter_id == target_id`；允许同时引用其他章原文作为关联依据。若目标章原文未召回或没有被引用，应过滤/降级该项，不能因另一章有 SourceSpan 就输出确定结论。这条规则不试图证明同章引用一定支持模型措辞，也不禁止跨章关联分析。

## 验证边界

- 直接调用现有 `WritingAnalysisEngine.validate`，4 个合成案例，2 个反例未满足关闭条件，2 个控制案例通过。
- 未调用 API 层/Provider，未创建或读取数据库，未读取 `.env`；网络连接与 SMTP 均设为禁止，触发计数为 0。
- 使用工作树 `.venv`，只新增本目录中的独立探针、JSON 和本说明。
- 复现入口：`.venv/Scripts/python.exe -B docs/legacy-gap-evidence/independent-g03-g05/chapter-evidence-probe.py`。结果文件采用独占写入，以免复跑覆盖首次证据。
- 源码 SHA-256 和完整合成输入、伪模型输出、校验结果见 `chapter-evidence-results.json`；首次结果不支持将 G03 判定为完整关闭。
