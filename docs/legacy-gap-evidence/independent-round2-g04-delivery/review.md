# G04 第二轮交付隔离独立复验

日期：2026-09-26（Australia/Sydney）。工作树：`story-continuity-legacy-gap-repair`。

结论：先前正式源码包含测试页而导致维护源包拒绝的缺口，在本轮源码及现有正式构建清单层面已关闭。独立只读 `plan` 通过，正式页面目录没有测试页面文件或测试组件引用，现有正式构建没有该测试路由。新的 staging 脚本没有向原目录写入或访问作品数据的操作。尚不能以此替代主控对最新正式产物的实际浏览器复验，也不表示发布或用户验收通过。

本轮只读取代码、Git 差异、既有证据和已有构建文件，执行只读源包计划、脚本语法检查及哈希检查；只新增本报告。没有运行 staging 脚本、生成包、构建、启动/重启服务、运行浏览器场景、读取 `.env` 或原数据库，也未调用 Provider/SMTP。首轮 `independent-g04/` 的所有记录保持原样。

## 1. 临时 staging 脚本与原文件边界

| 核对点 | 证据和判断 |
|---|---|
| 源路径 | `frontend/scripts/stage-legacy-rich-e2e.mjs:6` 用脚本自身位置解析 frontend 根目录，不依赖执行者当前目录。 |
| 目标路径 | 第 12 行使用系统 `tmpdir()` 和固定前缀 `story-rich-suggestion-e2e-` 调用 `mkdtemp`，创建新的唯一目录；第 14、17、20–27 行的所有复制和建目录目标都由该目录与固定子路径拼接，无用户输入路径或 `..`。当前 `tmpdir()` 实际解析为 `C:\Users\赵晨阳\AppData\Local\Temp`，位于工作树外。 |
| 原目录保护 | 第 7–9 行在原正式 `app/test-writing-tools/page.tsx` 存在时直接失败。脚本只有读取、复制、建目录和输出路径，没有删除、移动、回写源文件、执行依赖安装、构建或启动进程的操作。 |
| 复制范围 | 第 13–17 行只复制 `app/public` 和列明的 8 个前端构建配置文件；第 24–25 行复制两个测试支架文件；第 27 行复制现有 `node_modules`，没有复制 backend、作品数据库、`.env`、现有 `.next*` 或证据目录的分支。 |
| 链接边界 | 对当前 `frontend/app`、`frontend/public` 的递归检查未发现 reparse point；`node_modules` 自身和递归检查也均无 reparse point。第 27 行的 `dereference: true` 会读取依赖链接目标，因此本结论依赖本次实际依赖树；脚本本身不是面向任意不可信依赖树的隔离沙箱。 |
| 数据访问 | `frontend/e2e/support/RichSuggestionHarness.tsx:3–35` 使用本地 React 状态和真实 WritingTools/RichDraftEditor，场景数据均为内置短文本，没有作品 API、账号、数据库或 Provider 调用。staging 脚本没有网络操作。 |
| 语法 | `node --check frontend/scripts/stage-legacy-rich-e2e.mjs` 退出码 0；没有执行该脚本的复制行为。 |

正式 `frontend/app/test-writing-tools` 目前还保留空目录，独立枚举子项数量为 0；没有 `page.tsx`。空目录不是可访问的 Next 页面，源包按文件清单生成，也不会包含这个空目录。未为消除目录名残留而改动原目录。

新的模板 `frontend/e2e/support/RichSuggestionPage.tsx:1–5` 没有环境变量开关，复制进入临时 `app` 后就是可访问的测试页。这符合隔离测试用途，但临时 staging 本身不能当成生产交付目录。当前正式交付链路通过不引用、不复制这两个支架文件及 staging 脚本来排除该页面，并非依赖运行时开关隐藏页面。

## 2. 独立维护源包只读计划

在工作树根目录执行：

```powershell
& '.venv/Scripts/python.exe' -B 'deployment/build-maintenance-source.py' plan
```

结果：退出码 0；未执行 `build`，未提供 `--output`，未生成归档。第二次仅把同一只读输出解析为摘要，检查是否包含测试文件，结果一致。

```text
candidate: 2026-09-maintenance-local
deployed: false
file_count: 93
total_bytes: 8049456
inventory_sha256: 8a64f4a54dbdcbbf5d05e3e407b3c5618230e312f18953fa5713d8025b735793
manifest_sha256: ebbfe7183364e35c7dbdac0f200355eb2e8400de137366302e7fd36a5738839f
```

- 93 项中没有 `test-writing-tools`、`RichSuggestionHarness`、`RichSuggestionPage`、`stage-legacy-rich-e2e` 或任何 `e2e` 路径。
- `deployment/build-maintenance-source.py:118–178` 的 `make_plan` 读取显式清单及源码到内存；第 149–164 行继续检查完整源码树和链接，未放宽原约束。第 279–284 行将 `plan` 与生成归档分开。
- `docs/maintenance-release-manifest.json:379–383` 仍将 `frontend/app`、`frontend/public` 等列为完整源码树；该文件无 Git diff，没有为了容纳测试页扩大发布白名单。
- `frontend/package.json:5–24` 的正式 `build/start` 没有调用 staging 脚本。`deployment/Dockerfile.frontend:11,19–20` 从已列入源包的 `frontend-source` 构建，再于第 29–31 行复制 standalone/static/public；测试模板及脚本不在该输入中。
- 本报告及既有独立测试文件在 `docs/legacy-gap-evidence`、`frontend/e2e`，不在生产完整源码树或显式生产 include 中；本次没有修改 `verification_files` 或生产 manifest。

## 3. 已有正式构建路由检查

按返修交接指定，独立读取 `frontend/.next-gap-final-accept`；未构建或占用其目录。

```text
BUILD_ID: W52CgAUpNgqPizlf_vc_k
BUILD_ID LastWriteTimeUtc: 2026-09-26T05:51:54.9255701Z
```

`server/app-paths-manifest.json` 的完整键集合：

```text
/[[...path]]/page
/_global-error/page
/_not-found/page
/icon.svg/route
```

`routes-manifest.json` 只有通用动态页面 `/[[...path]]` 和框架静态页 `/_global-error`、`/_not-found`、`/icon.svg`；没有 `/test-writing-tools` 路由。API rewrite 指向本地 `http://127.0.0.1:8238/api/:path*`。

对该构建的 `server` 和 `static` 文件内容检查：没有 `RichSuggestionHarness`、测试标题“富文本建议替换浏览器测试”或 `rich-test-body`。`test-writing-tools` 字符串在服务器 SSR loader 的 `.js` 和对应 `.js.map` 各有一处，内容是目录元数据 `["components","test-writing-tools"]`，对应上述空目录；不是页面模块、测试组件或页面路由。不将该字符串残留误报为测试页面仍公开。

构建清单证明该产物没有专用测试页路由，但应用存在 catch-all；实际请求 `/test-writing-tools` 未必返回 HTTP 404。主控浏览器复验应核对实际呈现和测试组件缺席，不能只凭 HTTP 状态下结论。

## 4. G04 源码身份及建议应用复核

| 文件 | 本轮 SHA256 | 与上一轮比较 |
|---|---|---|
| `frontend/app/components/WritingTools.tsx` | `9903E8D8578E9970B4B9A9F44DB204A83CB676BFCC355707DFBE20EFFD0B87E1` | 与 `independent-g04/review.md` 的通过轮次完全相同。 |
| `frontend/app/components/Workbench.tsx` | `04644CCAB961F53E26306906A862E70D785621980530B96CF8F9E87E1388E58A` | 与上轮 `AE3AC6B2378889AD07466A2CB263DDA290021D30A31E5BB43A47DEE19185D4F1` 不同，不能声称整文件未变。 |
| `frontend/e2e/legacy-gap-independent.spec.ts` | `33A04286612F903CC932C17B18EB96562108654D12BC9A39B5FA127065CF2C1D` | 与上轮补视口断言后的测试完全相同。 |

`Workbench` 当前相对 Git 基线的差异涉及 G02 草稿覆盖文案（第 4147 行）、G03 目标来源提示（第 6221 行）及 G04 已验过的人工处理提示（第 6600 行）。该 Git diff 不是相对上一轮临时源码的差分；本轮没有旧 Workbench 完整副本，因此只作当前逻辑和旧独立记录的人工比对，不虚构逐字节未变证明。

本轮复核的 G04 路径与上轮行为记录一致：

- 第 2759 行仍以 `dirty || run.is_stale` 使建议过期。
- 第 2790–2805 行仍先检查开放操作、充分证据和建议；Markdown 调用同哈希的真实 `replaceVisibleDraftText`，失败立即返回；成功只进入受控未保存状态并提示作者保存，不在此自动调用保存或事实写入。
- 第 6599–6600 行仍在真实抽屉用 `role="alert"` 展示人工处理提示，应用按钮受到 `busy/outdated/decisionReady` 守卫。
- 第 6605 行的预览按钮仍受旧建议、缺证据及已决定状态守卫。

没有发现需要因本轮 G04 业务变化重新解释上一轮 6 个场景的代码差异。本次未重跑它们；主控正在最新正式产物上单独复验，其结果应另行登记，不能把本轮静态检查计作新的浏览器通过数。

## 5. 交付身份补充

| 文件 | SHA256 |
|---|---|
| `frontend/scripts/stage-legacy-rich-e2e.mjs` | `4A3A4742C58A081F85F720523642F123DAE672C136D70BCA27010DD00CC27182` |
| `frontend/e2e/support/RichSuggestionPage.tsx` | `413A784A6327253965E8C9AE4DB323B677BEC0D537F535498DE85FDA75414347` |
| `frontend/e2e/support/RichSuggestionHarness.tsx` | `B97AC58B24C72036F57A21AB5D7A2DF10EBEC09509607B09BEE69C55C21AAB18` |
| `frontend/.next-gap-final-accept/server/app-paths-manifest.json` | `5FA3A3282772099245EFDD51BBF29C15B8A6B4B79496A0BDC037440F60078777` |
| `frontend/.next-gap-final-accept/routes-manifest.json` | `981BEB30ED76647A5962F5EF4D83FB232E2BDB38F7C441817BD4C861A5A016BD` |

剩余验证由主控负责：最新正式产物真实工作台的 G04 场景、实际请求测试路径时不出现支架页面、正式页面不出现开发调试浮层。若后续更换源码或构建，应重新记录身份。本报告没有执行归档构建、容器构建、部署、线上或真实 Provider 验收。

## 6. 后续授权的两页面实际浏览器补验

以上为初次只读交付复验记录。主控随后明确授权启动现有正式产物的临时副本，只核对测试路径和注册页。以下补充关闭这两个页面的实际呈现待验项；不覆盖或改写前面的历史执行边界，也没有重跑主控已通过的四条工作台流程。

执行命令（工作树根目录）：

```powershell
node docs/legacy-gap-evidence/independent-round2-g04-delivery/verify-pages.mjs
```

结果：退出码 0，`status=passed`。执行时间 `2026-09-26T06:03:42.368Z` 至 `2026-09-26T06:03:50.481Z`；唯一证据目录为 `pages-attempt-1790402622367-12348`。没有重新构建。

- 启动前分别绑定检查 `3238/8238` 可用；临时根为 `C:\Users\赵晨阳\AppData\Local\Temp\story-v130-rc-g04-delivery-pages-gSH3gv`，复制既有 standalone/static/public 后运行。后端使用该新根、注入式 stub 和清除敏感环境变量的进程环境。
- 源产物 build ID 仍为 `W52CgAUpNgqPizlf_vc_k`；源目录与副本 `app-paths-manifest.json` 哈希均为 `5fa3a3282772099245efdd51bbf29c15b8a6b4b79496a0bdc037440f60078777`。
- 本轮仅在无登录会话、1440×900 视口导航两个页面，没有创建账号或作品、提交表单、访问原数据或修改正文。

| 页面 | 实际浏览器结果 | 截图 |
|---|---|---|
| `/test-writing-tools` | 初始 HTTP 200；客户端会话检查后转到 `/login`，显示实际“登录”标题和登录表单。测试支架标题、编辑器、场景选择及序列化正文元素均不存在。 | `pages-attempt-1790402622367-12348/test-writing-tools-catchall-to-login-1440.png` |
| `/register` | HTTP 200，停留在 `/register`，显示实际“创建账号”标题及账号、显示名称、恢复邮箱、密码表单。 | `pages-attempt-1790402622367-12348/register-production-1440.png` |

两页的 `pageErrors`、`consoleErrors`、失败请求、HTTP 400 及以上响应、浏览器写请求全部为空；`nextjs-portal`、开发错误浮层/提示/工具按钮元素计数均为 0。页面外部请求全部拦截并记录，实际列表为空。两张截图均已人工查看，页面中没有开发调试浮层或测试界面。此结果针对这两个匿名页面，不扩张为全应用所有状态均无错误。

前后读取隔离统计均为 `provider_mode=injected_stub`、`external_provider_http_enabled=false`、`provider_calls=0`、`provider_http_calls=0`，统计返回的临时根与本轮创建的根相同。

清理记录：仅终止本次启动的前端 PID `8292` 和后端 PID `28628`，两者均收到 `SIGTERM` 并退出；随后重新绑定检查两个端口均空闲。独立 PowerShell 监听器复查也没有发现 `3238/8238` 监听者。没有删除临时根或旧证据。

证据文件：该目录的 `result.json` 保存完整页面结果、产物身份、前后 Provider 统计及进程清理记录；`frontend.log`、`backend.log` 保存本次进程输出；`two-pages-trace.zip` 保存两次真实导航的浏览器 trace。新增 runner 只位于证据目录，不修改生产文件或发布清单。

本轮实际页面补验完成。真实工作台的 G04 场景继续引用主控单独执行的正式产物流程报告；本报告不将两个页面计作额外业务场景或发布 Gate。
