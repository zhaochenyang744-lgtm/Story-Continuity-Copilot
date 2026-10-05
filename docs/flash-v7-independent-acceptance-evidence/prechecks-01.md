# V7 前置检查与 V6 基线保全

核心快照在主控获准编辑前保存：engine `527f986d…7fd39`、provider `ed33b197…32643`、V6 测试 `7f1a9325…57f`。其余 V6 manifest 所列产品依赖也已保存，14 产品文件＋1 测试全部符合冻结 SHA；另存 manifest、evaluation 初始化文件及其 pin，共18份。见 baseline/core-receipt.json、dependency-snapshot-receipt.json。

HEAD 为 `7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2`。完整 dirty 状态2582行已记录。普通 git status 曾有 Windows 长路径警告及输出截断，随后仅对此命令设置 core.longpaths=true，完整 stdout/stderr 落盘，无全局配置修改。dirty 采集发生在核心快照确认后，可能包含随后获准的编辑；不能误称整个工作树是同一原子时刻的快照。

旧真实 run 精确420文件已逐项计算哈希，捕获前后稳定；baseline/v6-run-hashes.json 留作最终不变性复查，不改原 run。

1. **400 的用途。**基线 `_v6_issues` 将其作为内部 ledger 的 basis 长度上限，然后只返回 issues；未发现前端或持久层消费 claim_verdicts，HEAD 和该路径提交历史也没有这个 V6 ledger。没有证据表明400由作者UI截断要求决定；context_brief 的400摘要是另一合同。最小修复是单一上限常量、schema/prompt显式字数单位、超限字段/实际长度/上限诊断。不要静默截断，也不要只靠扩大上限掩盖问题。

2. **修复预算。**首请求分批不预留修复中追加 diagnostics/rejected_issues 的空间；Provider仍限制输入6000、输出2000。按冻结 formatter 的字面常量和估算公式复算34首请求＋15修复：首请求最高4403，修复最高5402，均未超限；所以此轮不是已发生的预算失败，但接近上限请求需要检查明确拒绝或预算预留。engine 的 MAX_RUN_TOKENS 判断逐次 result，并非全run累计，这一既有限制应披露。

3. **多claim边界。**上述49份请求全部只有1个claim，不能证明多claim覆盖与2000输出预算足够。最小离线检查应含混合 no_issue／不足／冲突、逐claim诊断、每个当前ID恰好一次及接近预算边界；无需扩大真实样本。

4. **G02隔离。**WritingAnalysisEngine 不调用 temporal helper 或 `_v6_issues`。基线已记录其类AST、context_brief_prompt、request_prompt_and_budget及brief_citations指纹。若仅改continuity语义路径，稳定后对照这些AST/哈希即可；若共同transport、预算或G02引用逻辑被改，再决定针对性离线回放。G02原有6summary／72items的有限范围不扩大。

详细路径、复算行和AST摘要见 prechecks-01.json。本阶段未导入产品模块、未执行测试，Provider和DB均0。
