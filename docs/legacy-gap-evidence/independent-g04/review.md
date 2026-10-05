# G04 真实工作台独立浏览器补验

日期：2026-09-26（Australia/Sydney）。

结论：G04 的本次限定行为通过独立浏览器补验：4 类拒绝场景保持正文及格式不变并在真实 Evidence 抽屉提供人工处理提示；统一加粗和嵌套列表/引用/加粗斜体成功进入未保存草稿，明确保存并刷新后保留格式。此结论不关闭测试路由的交付边界问题，也不表示用户验收、生产发布或真实模型效果验收通过。

## 范围和隔离

- 工作树：`C:\Users\赵晨阳\Documents\ChatGPT\Agent 搭建\Story-Continuity-Copilot\产出\交付物\story-continuity-legacy-gap-repair`。
- 复用已运行的 `http://127.0.0.1:3218` 前端及 `http://127.0.0.1:8218` 隔离后端，没有启动或重启服务。
- 只新增 `frontend/e2e/legacy-gap-independent.spec.ts` 和本目录证据；没有修改产品代码或既有测试。
- 账号前缀为 `gapg04`，使用本轮创建的隔离教学作品。没有读取或写入原项目数据库、`.env`、真实 Provider、SMTP 或外部账号。
- 在每个测试开始和结束读取隔离后端统计：`provider_mode=injected_stub`、`external_provider_http_enabled=false`、`provider_http_calls=0`。页面外部 HTTP(S) 请求一律阻止并记录，实际记录为空。
- 真实 API 完成注册、Markdown 草稿保存、检查 Run、最终显式保存及作者决定。GET 检查响应夹具仅为一个已有充分证据 Issue 提供测试建议、问题性质和场景标记；保留实际 Run/Issue/来源及版本，不替换 WritingTools、Tiptap、Evidence 或保存接口。
- 场景标记和建议是作者定义的验收夹具，不能作为原始模型能力或语义准确率证据。

## 执行记录

| 轮次 | 结果 | 边界 |
|---|---|---|
| attempt-001 | 独立脚本定位失败后主动中止，退出码 1 | 夹具只改 explanation，而真实问题行优先显示 claim_text；定位器等待场景标记。未完成产品断言，不计为产品失败。原命令日志和未完成 trace 保留。 |
| attempt-002 | 2 passed，22.2 秒，退出码 0 | 修正夹具显示字段后，两个测试、6 个场景完整通过。 |
| attempt-003 | 1 passed，12.2 秒，退出码 0 | 只重跑4个拒绝场景：新增滚动提示进入视口及 `toBeInViewport` 断言，补充能完整看到提示的截图。不是新增4个独立场景，不和 attempt-002 相加计数。 |

attempt-001 的首个失败来自验收脚本，不曾修改产品来使测试通过。attempt-002 原图中抽屉内的失败提示在截图视口下方；attempt-003 显式滚动抽屉后完整记录提示。该证据证明提示存在、可读、能进入视口，不声称应用失败后页面会自动滚动到提示。

新增独立测试文件的定向 ESLint 检查通过：在 `frontend` 目录执行 `.\node_modules\.bin\eslint.cmd e2e/legacy-gap-independent.spec.ts`，退出码0；没有扩大为全项目测试或修改自动生成配置。

## 已验证结果

| 场景 | 独立断言 |
|---|---|
| mixed-marks | 建议跨加粗与普通文字；真实 Evidence 抽屉拒绝，提示“正文未改变；请返回正文手动修改并检查格式”；编辑器 innerHTML 与服务器正文/版本保持原样。 |
| after-newline | 替换后的文字含换行；同样拒绝，正文/格式/服务器版本均不变。 |
| cross-paragraph | 定位文字跨两个真实段落；同样拒绝，正文/格式/服务器版本均不变。 |
| repeated-paragraph | 两段有相同目标文字；同样拒绝，没有猜测一个位置替换。 |
| uniform-bold | 替换后仍为 strong；点击应用不会产生 draft PATCH 或 Issue decision 请求，服务器仍为原稿；界面显示未保存，旧建议按钮禁用。点击“保存受控修订”后产生真实保存及作者决定，版本从2变3；刷新后 Markdown及strong保留。 |
| nested-list-quote | 真实列表内引用中的统一 bold+italic 替换成功；DOM `li blockquote strong em` / `li blockquote em strong` 保留；只先进入未保存稿，显式保存后版本从2变3，刷新后列表、引用、加粗、斜体及 Markdown格式仍保留。 |

两个通过轮次的 `browserErrors`（pageerror）均为空；页面外部请求记录为空。此处没有把所有 console 输出都判定为零：开发预览仍显示既有 Next “1 Issue”提示，并请求本地 `__nextjs_original-stack-frames`。没有隐藏或修饰该调试提示；这些图片是开发预览证据，不是生产构建的无调试界面验收。

## 证据

- `attempt-002/command.log`：两个测试通过的命令输出。
- `attempt-003/command.log`：拒绝提示视口补验输出。
- `attempt-002/results/legacy-gap-independent-G04-ce495-h-explicit-save-and-refresh/g04-save-evidence.json`：真实账号/项目/Issue、服务器保存版本、Markdown正文、DOM选择器、页面写请求、HTTP计数。
- `attempt-003/results/legacy-gap-independent-G04-755d1-out-changing-body-or-saving/g04-rejection-evidence.json`：拒绝场景、服务器版本未变及页面写请求/HTTP计数。

拒绝提示截图（attempt-003；均为真实工作台 Evidence 抽屉）：

- `attempt-003/results/legacy-gap-independent-G04-755d1-out-changing-body-or-saving/mixed-marks.png`
- `attempt-003/results/legacy-gap-independent-G04-755d1-out-changing-body-or-saving/after-newline.png`
- `attempt-003/results/legacy-gap-independent-G04-755d1-out-changing-body-or-saving/cross-paragraph.png`
- `attempt-003/results/legacy-gap-independent-G04-755d1-out-changing-body-or-saving/repeated-paragraph.png`

成功替换及刷新截图（attempt-002）：

- `attempt-002/results/legacy-gap-independent-G04-ce495-h-explicit-save-and-refresh/uniform-bold-unsaved.png`
- `attempt-002/results/legacy-gap-independent-G04-ce495-h-explicit-save-and-refresh/uniform-bold-saved-reloaded.png`
- `attempt-002/results/legacy-gap-independent-G04-ce495-h-explicit-save-and-refresh/nested-list-quote-unsaved.png`
- `attempt-002/results/legacy-gap-independent-G04-ce495-h-explicit-save-and-refresh/nested-list-quote-saved-reloaded.png`

已人工查看 `mixed-marks.png`（attempt-003）及 `nested-list-quote-saved-reloaded.png`（attempt-002）：前者显示完整人工处理提示，后者显示列表/引用及加粗斜体正文和已保存状态。截图没有删除开发调试标识。原 attempt-001 日志/trace 和 attempt-002 原截图保持不变。

## 运行命令

在工作树的 `frontend` 目录执行（下列为 attempt-002；证据目录已独立存在）：

```powershell
$env:E2E_BASE_URL='http://127.0.0.1:3218'
$env:E2E_BACKEND_ORIGIN='http://127.0.0.1:8218'
$env:E2E_ACCOUNT_PREFIX='gapg04'
$evidencePath=Join-Path (Resolve-Path '..').Path 'docs\legacy-gap-evidence\independent-g04\attempt-002'
New-Item -ItemType Directory -Path $evidencePath -Force | Out-Null
& '.\node_modules\.bin\playwright.cmd' test e2e/legacy-gap-independent.spec.ts --config=playwright.config.ts --output="$evidencePath\results" --reporter=line 2>&1 | Tee-Object -FilePath "$evidencePath\command.log"
exit $LASTEXITCODE
```

attempt-003 使用新的 `attempt-003` 目录，并在命令中加入 `--grep='rejects unsafe'`。后续重跑必须换新目录，不能复用旧 output 目录覆盖失败链或已核验截图。

## 当次源码身份

以下哈希在 attempt-002 后读取，attempt-003 后再次核对产品文件相同：

| 文件 | SHA256 |
|---|---|
| frontend/app/components/WritingTools.tsx | 9903E8D8578E9970B4B9A9F44DB204A83CB676BFCC355707DFBE20EFFD0B87E1 |
| frontend/app/components/Workbench.tsx | AE3AC6B2378889AD07466A2CB263DDA290021D30A31E5BB43A47DEE19185D4F1 |
| frontend/e2e/legacy-gap-independent.spec.ts（attempt-002） | CACF0820F1BFFCC3F83ABD0DAD5662267C36381574400B7C16F2D5872B164E91 |
| frontend/e2e/legacy-gap-independent.spec.ts（补视口断言后） | 33A04286612F903CC932C17B18EB96562108654D12BC9A39B5FA127065CF2C1D |

本轮是共享开发预览的行为验证；哈希描述测试后读取的本地文件，不取代未来冻结生产构建的身份检查。

## 未扩大结论

- 本轮没有重跑 CRLF 或纯斜体单独场景；已有支架结果和静态审查可另引用，不能混称本次真实工作台覆盖。嵌套成功场景实际包含 bold+italic。
- 本轮未验收390移动只读、生产构建、跨账号隔离矩阵、真实模型首答、SMTP、线上成功链路或恢复演练。
- G04 仍是唯一定位、单文本块且 marks 一致的保守替换，不是通用富文本改写或 Agent 新功能。
- 先前测试入口位于 `app/test-writing-tools` 的生产源码/包清单问题已交原实施任务返修；本报告不预先宣布该问题关闭。
- 新增独立测试在 `frontend/e2e`，证据在 `docs/legacy-gap-evidence`，均不在当前 `complete_trees`。如需登记 `verification_files` 由主控统一维护，不通过扩大生产发布白名单纳入调试页或本地证据。
