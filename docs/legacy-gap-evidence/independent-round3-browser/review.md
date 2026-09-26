# 第三轮 G02 实际校验器与页面独立验收

日期：2026-09-26（Australia/Sydney）。结论：本次两个新增 G02 贯通情形及一条受影响回归全部通过，共 **3 passed（21.5 秒），退出码 0**。三条逐字内容循环错配引用经过真实校验器被移除，页面说明错配数量并在刷新后保留；正确引用正控完整保留且未误标。此结论限定于下列合成案例，不宣称通用语义引用验证或真实模型准确率通过。

## 范围与实现方式

- 工作树：`story-continuity-legacy-gap-repair`。只新增 `frontend/e2e/legacy-gap-round3-brief.spec.ts` 及本证据目录的 wrapper/runner/报告，没有修改产品、原 `backend/tests/e2e_app.py`、既有回归测试或前两轮证据。
- `g02_brief_app.py` 仅在明确设置 `SCC_G02_ROUND3_BROWSER=1`、临时根位于系统临时目录且前缀为 `story-v130-rc-g02-r3-` 时加载。它导入原测试应用，仅 monkeypatch `BrowserTestProvider.evaluate`；只有 `context_brief` 且草稿包含 `E2E_G02_R3_CYCLE` 或 `E2E_G02_R3_VALID` 时返回合成模型分项，其余请求继续调用原测试桩。
- 每个合成请求必须实际产生恰好 3 个草稿 claim；错配情形引用顺序为第 1 句→第 2 句、第 2 句→第 3 句、第 3 句→第 1 句。正控逐项引用自身。独立测试接口保存该桩原始返回及实际 claim ID，以证明校验前确有错配。
- **没有替换 API 返回、validator、数据库或前端组件。** 实际浏览器注册新账号、创建新作品、保存三句正文，再点击“生成章节简报”；真实请求经过实际 `WritingAnalysisEngine.validate`、持久化与读取接口，到正式 Workbench 页面。刷新后再次验证同一个 Run 和完全相同的 analysis 内容。
- 测试使用 `gapg02r3` 账号前缀和 `example.test` 邮箱；没有请求真实 Provider 或邮件验证，不使用原项目数据库、`.env` 或真实账号。

## 产物与隔离

本轮收到代码冻结与执行授权后复用实施者已构建的最新产物，**没有重新构建**。

```text
source artifact: frontend/.next-gap-r2-repair
BUILD_ID: zh0KdT5LoRWDgI31kwXkx
frontend: http://127.0.0.1:3239
baked API rewrite: http://127.0.0.1:8239/api/:path*
temporary root: C:\Users\赵晨阳\AppData\Local\Temp\story-v130-rc-g02-r3-igAX4S
execution: 2026-09-26T06:16:16.079Z — 2026-09-26T06:16:43.597Z
evidence: attempt-1790403376077-22220
```

启动前两个端口均空闲；复制 standalone、public、static 到新临时根后启动，副本的 BUILD_ID 与源产物相同。正式 app-paths 清单只有 `/[[...path]]/page`、`/_global-error/page`、`/_not-found/page`、`/icon.svg/route`，没有测试页；`artifact-identity.json` 保留完整路由清单和源码身份。启动前已在正式静态/服务器 chunk 中定位到新增错配提示，未误用旧 W52 产物。

本地 runtime 环境显式设置 `PUBLIC_APP_MODE=0`、`PUBLIC_BASE_URL=http://127.0.0.1:3239`，并清除继承的 Provider/SMTP/密码/token/secret 环境变量。现有 `public-config.mjs` 的 public base 用于构建配置验证，未在该构建清单中单独序列化；本轮明确核验的是 baked API rewrite、实际 3239 页面及本地运行环境，不虚构独立的 baked public-base 证明。

## 实际结果

| 情形 | 接口与持久化断言 | 页面与刷新断言 |
|---|---|---|
| `cycle` 循环错配 | 原桩返回 3 个错配项。真实结果 `evidence_status=partial`、`draft_coverage.status=partial`、`discarded_item_indices=[0,1,2]`，理由包含 `draft_item_citation_mismatch` 和 `draft_claim_uncovered`。三个原始模型分项均移除；校验器只补入第一句正确定位的草稿引用。 | 显示“部分覆盖”“有 2 条选入主张未被引用”“有 3 条简报内容引用错配，已从结果移除”；模型分项标记不再出现，列表只剩 1 项。刷新后仍显示同样提示；同一 Run 的 analysis 完全相同。 |
| `valid` 正常引用 | `evidence_status=supported`、`draft_coverage.status=covered`、`discarded_item_indices=[]`、`reasons=[]`；3 项及对应 source ID 全部保留。 | 显示“全部选入主张已引用”，无“部分覆盖”或“引用错配”提示，列表为 3 项；刷新后仍保持，持久结果未变。 |
| 既有 `v130-writing-analysis.spec.ts` | 原测试覆盖简报、计划偏离、失败后重试和旧结果 stale；非特殊标记继续使用原本注入桩。 | 原测试完整通过，包括 390px 只读资料视图、无编辑/重试入口及无横向溢出断言。没有扩大修改原回归测试。 |

两条新增 G02 测试记录的 `pageErrors=[]`、`externalRequests=[]`。对本地以外的浏览器 HTTP(S) 请求设拦截并记录，实际为零。此新增网络/pageerror 记录针对两个新情形；既有回归沿用其原有断言，没有虚称它新增了同样的全量网络记录或控制台错误检查。

全轮后端统计：`provider_mode=injected_stub`、`external_provider_http_enabled=false`、真实 `provider_http_calls=0→0`；注入式 `provider_calls=0→6`。后者是本地桩评估次数，不是外部 HTTP。统计中的 `test_root` 与本轮新建目录严格一致。

两个新增情形均先滚动状态提示进入视口并断言可见，再截图；已人工查看两张刷新后完整截图，错配提示和正控状态均清晰显示。未把“covered”延伸解释为任意语义内容都正确。

## 证据路径

均相对于本目录：

- `attempt-1790403376077-22220/playwright.log`：3 个测试及通过耗时。
- `attempt-1790403376077-22220/result.json`：产物、前后源码身份、真实 Provider HTTP 统计、桩原始返回及进程清理。
- `attempt-1790403376077-22220/artifact-identity.json`：正式 app-paths/routes 与前置源码身份。
- `attempt-1790403376077-22220/results/legacy-gap-round3-brief-G0-b6569-esh-with-correct-disclosure/brief-validator-evidence.json`：循环错配原始返回、实际 Run 和刷新后结果。
- 同一子目录 `cycle-before-refresh.png`、`cycle-after-refresh.png`。
- `attempt-1790403376077-22220/results/legacy-gap-round3-brief-G0-36405-esh-with-correct-disclosure/brief-validator-evidence.json`：正常引用对应证据。
- 同一子目录 `valid-before-refresh.png`、`valid-after-refresh.png`。
- `attempt-1790403376077-22220/writing-analysis-01-desktop.png`、`writing-analysis-02-mobile-390.png`：既有回归截图。

## 源码身份与执行命令

运行前后 `sourceIdentity` 完全一致（`source_unchanged=true`），包括前端源码 Build ID、下列业务文件、原测试应用、新增独立测试/wrapper、`next-env.d.ts` 和 `tsconfig.json`。没有构建自动改写原配置。

| 文件 | SHA256 |
|---|---|
| `backend/app/engine.py` | `df9b2a19b07744b318743802679c22f67a49af13a67275cf81f74c0d06891ea4` |
| `backend/app/v2_database.py` | `9f0b8c2b512f2d69f03cbc7193d83d9681fe42fe3ade51a7fcc4ad494fdba965` |
| `backend/app/provider.py` | `e415c36cc08114492e7ac5305ef67db89eb58f1a06aa01a0a19c9c89b91b7380` |
| `frontend/app/components/Workbench.tsx` | `bf76619e7ae5d3652a99d70fa5b440caa8a38ea1235814180014da1116823680` |
| `frontend/app/model.ts` | `d1999849318eaf94dc50f1321f37675bbf4cc2ad6aeb9c8e6c15ac7df0dd9e1b` |
| 新增 `legacy-gap-round3-brief.spec.ts` | `3340bf88ed75efd1d711ec2dd88b07b125091a3aa13128108b33fac3e65fc90f` |
| 新增 `g02_brief_app.py` | `6f1cdb6f344b9d16bb345733d99fb6d34acb2827b6337d5a131d7a487074c8d3` |

前端源码身份：`s13v4-dce0bc906338b546f4d4fb4eedea9c77`。这描述当前源文件；被实际运行的正式产物另以 `zh0KdT5LoRWDgI31kwXkx` 标识，没有混用两种 ID。

在工作树根目录执行：

```powershell
node docs/legacy-gap-evidence/independent-round3-browser/run.mjs
```

runner 只运行新增 spec 与既有 `v130-writing-analysis.spec.ts`，使用唯一 attempt 目录，结束后停止自身进程；没有 G04 六场景重跑。准备阶段 `node --check` 和 Python AST 解析通过，新增 spec 的定向 ESLint 通过。第一次从仓库根目录执行 ESLint 因找不到前端配置失败；改在 `frontend` 目录执行后退出 0，这是检查命令工作目录问题，不计为产品失败，也未改配置。

清理记录：Playwright PID `21288` 自然退出 0；前端 PID `18084`、后端 PID `24916` 均收到 SIGTERM 后退出。随后绑定检查及独立监听器复查均确认 3239/8239 空闲。保留本次临时根和所有证据，没有覆盖旧失败链或删除数据。

此轮没有真实模型、SMTP、线上发布、全书检索能力或通用语义引用匹配验收；也没有提交、推送、部署或进入 Agent 新功能实现。
