# 既有缺口 G01–G05 修补交接

状态更新（2026-09-26）：第三轮主控本地独立验收通过，用户已确认修补结果并明确授权在 `codex/legacy-gap-repair` 创建本地 Git 提交。下文“未提交”“待主控验收”为实施交接当时的历史状态；最新结论以 [独立验收报告](legacy-gap-repair-independent-acceptance.md) 为准。真实模型/线上/恢复验证仍待授权，未开始 Agent、合并、推送或部署。

日期：2026-09-26。隔离工作树 `story-continuity-legacy-gap-repair`，分支 `codex/legacy-gap-repair`，基线 `39de855c005d77f7f02a132f5e807a0c1c476b7b`。本次未提交、推送、部署，未调用真实 Provider 或 SMTP，未读取原仓库 `.env` 或改动原数据库。旧 Agent P1 原型工作树保持隔离，未合并；本次没有启动 Agent UI 或 Agent 循环。

## 修补结果

| 缺口 | 修改与验收边界 |
|---|---|
| G01 时间与知识 | 连续性提示词升至 `continuity-review-v15-knowledge-time`；确定冲突同时核对模型锚点与绑定的完整主张/引用片段。不同相对日或序数日、同句多时点、显式回忆或谎称均保守降级；同日同一时刻的直接知情矛盾正控制保留。未进行真实模型首答评估，因此不宣称模型准确率改善。 |
| G02 当前简报 | 模型遗漏已保存草稿引用时，校验器补入有 `draft_claim` 来源的分项；摘要仍由可引用分项重组。`draft_claim_scope` 记录选入主张在正文的起止、实际送入尾点和逐条截断；`draft_coverage` 明列未引用 ID 和未选入数量。只引用第一句、未选入主张、240 字单句截断或正文摘录截断都返回 `partial`，前端说明缺口。版本/归属守卫不变。 |
| G03 影响来源 | Memory 目标及直接 `SourceSpan` 在原有 8/4 配额内优先选择；围绕可逐字定位的目标事实截取 500 字原文，并记录原文/摘录长度及截断。直接来源缺失或不能定位目标事实时不生成确定结论；章节影响项必须引用该目标章自己的 `SourceSpan`。仍不扩大为全书检索。 |
| G04 富文本替换 | 在真实 Tiptap 文档内替换并保留统一 marks 和所在列表/引用结构；跨段、换行/CRLF、混合格式、重复定位保守拒绝。测试页只由 `frontend/scripts/stage-legacy-rich-e2e.mjs` 复制到系统临时 staging 后注入，正式 `frontend/app` 无测试路由；作者仍须显式保存正文。 |
| G05 请求计数和用量 | DeepSeek 每次实际 HTTP `post` 前进行持久额度预留。首发超时、第二次成功时，后一次响应的已知用量保留在 `ProviderResult.observed_response_*`，整个 Run 的 tokens/费用仍为 `None`；持久化与运维汇总显示未知，不把局部已知值误当总量。注入式非 HTTP Provider 沿用一次评估一次预留。 |

## 验证

- 后端新增及相关定向回归：`48 passed`；最后补充间接引述范围后相关 `23 passed, 6 subtests passed`；Stage 2/4 API 回归：`45 passed`。均使用本工作树 `.venv`，后者只在测试进程设置本地 `PUBLIC_*`、`TRUSTED_*` 环境变量。
- 前端 `npm run typecheck`、`npm run lint` 通过。最终生产构建在显式本地 `BACKEND_ORIGIN`、`PUBLIC_APP_MODE`、`PUBLIC_BASE_URL` 和独立 `NEXT_DIST_DIR=.next-gap-final-accept` 下通过，路由清单只有 `/_not-found`、`/[[...path]]` 和 `/icon.svg`，没有测试路由。`deployment/build-maintenance-source.py plan` 通过，93 个显式源码文件；未修改维护发布清单。构建/开发服务自动写入的 `next-env.d.ts`、`tsconfig.json` 和生成的 AGENTS/CLAUDE 文件已从交付 diff 清理。
- Playwright：隔离 staging 的 `legacy-rich-suggestion.spec.ts` 为 `1 passed`；更新后 `v130-writing-analysis.spec.ts` 为 `1 passed`，其中 390px 只读资料分栏可见，真实 Provider HTTP 调用为零。先前 `v140-frontend.spec.ts` 可信审查/建议应用场景为 `1 passed`；主控另以独立工作台测试复验 G04，证据见其独立验收记录。
- `git diff --check` 通过。更新后浏览器回归使用本机隔离 `3238/8238` 进程并在测试后停止；原 `3218/8218` 预览进程可能仍在运行，但后端未热重载，不可据其判断本轮最终修补。开发模式因现有 CSP 对 React 开发调试 `eval()` 的限制显示一个 Next 调试提示；生产构建通过，测试交互不受影响。

截图：`legacy-gap-evidence/writing-analysis/writing-analysis-01-desktop.png`、`writing-analysis-02-mobile-390.png`；`legacy-gap-evidence/rich-suggestion/legacy-rich-suggestion-1440.png`、`legacy-rich-suggestion-390.png`；`legacy-gap-evidence/v140-01-trustworthy-review-1440.png`、`v140-02-mobile-review-390.png`。截图与本地测试账号数据只在新工作树及隔离临时 E2E 根目录。

## 独立验收首轮失败与返修

首轮本地自测通过后，主控独立验收复现了五类遗漏：锚点只截“十八点”绕过完整日期/叙述范围、三句草稿只引第一句及单句 240 字截断仍显示完整覆盖、目标 `SourceSpan` 只送入开头 500 字、章节 A 的确定影响错引章节 B、超时后成功响应把第二次用量当作完整 Run。首次失败的独立探针与结果保留在 `legacy-gap-evidence/independent-g01-g02/`、`independent-g03-g05/`；本次只读参考，没有修改或覆盖。上述回归分别加入产品测试。

测试入口本身也曾触发维护源包完整性拒绝：`frontend/app/test-writing-tools/page.tsx` 不在显式生产清单。现正式目录不含该文件；测试页模板在 `frontend/e2e/support/RichSuggestionPage.tsx`，staging 脚本只复制 `app/public`、构建配置和本地依赖到系统临时目录，再注入页面。第一次 staging 使用跨目录 `node_modules` 链接触发 Turbopack 拒绝；改为复制依赖后，使用 `localhost` 作为测试浏览器入口通过 9 个富文本场景。正式源包扫描和生产构建均未纳入测试页。临时 staging 路径为 `%TEMP%/story-rich-suggestion-e2e-8k2byv`，只用于本机复验。

用量口径限制：成功重试的后一次响应 tokens/费用目前只保留在内存中的 `ProviderResult.observed_response_*`，现有 Run 表只记录完整总量，因此持久值和运维总量均为未知；没有新增逐次响应持久化或推算首发费用。

## 第二轮独立反例后的限定返修

主控第二轮证据在 `legacy-gap-evidence/independent-round2-g01-g02/` 与 `independent-round2-g03-g05/`，本工作树只读参考，没有修改独立探针和结果。

- G01：时间范围判断只检查包含模型锚点的绑定句。句内出现“十八点未知、十九点才获知”时，即使模型两侧都截取“十九点”，仍不能定为确定冲突；另一无关句的“回忆”也不再使十八点的直接矛盾误降级。无唯一锚点句时保守拒绝。
- G02：分项直接复制草稿主张时，逐段核对不同原句是否各有对应 `draft_claim` 引用。确定错配的分项从摘要及列表中移除，`draft_coverage` 写入 `draft_item_citation_mismatch` 和原始分项序号，状态为 `partial`；相同文本绑定多个 ID 时任一相符引用可保留，无法作逐字判断的正常释义也保留。前端显示移除数量。没有把模型原来的错引静默改成正确引用。
- G05：初次响应已知用量，但契约修复 HTTP 请求超时后，整轮用量标未知；如超时后重试被持久额度拒绝，仍保持未知。只在修复请求派发前直接被额度拒绝、没有未知 POST 时，已知初次用量继续保留。

返修后，相关后端 `39 tests` 通过（含 G01 两个新句级反例、G02 循环错配/双句拼接/重复文本/正确引用/释义、G05 三个契约修复失败边界）；Stage 2/4 API `45 tests` 通过。前端 typecheck、lint、最新生产构建通过，独立构建目录为 `frontend/.next-gap-r2-repair`，已包含新的错配说明，路由仍只有 `/_not-found`、`/[[...path]]`、`/icon.svg`。构建对 `next-env.d.ts` 与 `tsconfig.json` 的自动写入已清理。返修后的浏览器复验由主控独立执行；这里不宣称该项已通过。

## 待后续验收

G01 真实 Provider 首答效果、真实 Provider/SMTP 链路、G07 线上成功链路和 G08 完整应用恢复没有在本次运行。当前结果是实现及本地自测，可供主控独立复验；不等于用户验收或发布 Gate。交付代码保持未提交，供主控检查后决定后续操作。
