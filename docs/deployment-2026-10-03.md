# 2026-10-03 生产部署记录（v1.5.0）

本次上线 Story Continuity Copilot v1.5.0，由 Git 标签 `v1.5.0`（提交 `b9f4b0f`）经 `deployment/build-maintenance-source.py` 打包：在服务器上从 GitHub 下载该提交的源码，`plan` 核对 inventory 后 `build`/`verify`，解压到新目录（0700），复制上一版的 `deploy.env` 与 `release-state`，再执行 `deployment/release.sh`。没有数据库结构变化；`release.sh` 切换前做了 `pre-release-v150-b9f4b0f-20261003` 备份。旧版本目录和镜像保留作回滚目标。

## 发布身份

| release id | Git 提交 | inventory SHA256 | 内容 |
|---|---|---|---|
| `v150-b9f4b0f-20261003`（当前） | `b9f4b0f9d6e8d0f7a5b4654943df68f12de5ee56`（标签 `v1.5.0`） | `e30d212177fb3e158000761ed025c58380ba895298bd358154ada3adc8d3f388`（99 个文件，8,216,794 字节） | 浏览器端到端测试迁移中发现的网站修复、后端连接保持时间、轻量微动效 |

- manifest SHA256：`dfc55ecafa20169724c83e074e8dc5ce379c641a83f28fc9c286d25064f712c5`。
- 归档 SHA256：`e20996b0945503c4ae88cc4e7af0ae4897e48d3089a8110b8549f19bd7dd16d2`（5,937,594 字节）。服务器生成的归档与本机从同一提交干净导出（`git archive b9f4b0f`）所建的归档逐字节相同。
- 与 `26ae621` 相比新增 `frontend-source/app/motion.css` 与 `docs/deployment-2026-10-02.md`；`v2_database.py` 未变，没有迁移。

当前回滚目标：`ui-26ae621-20261002`（`sudo bash /opt/story-continuity-v150-b9f4b0f-20261003/deployment/rollback.sh /opt/story-continuity-v150-b9f4b0f-20261003/deploy.env ui-26ae621-20261002`）。

## 本次内容

- 沉浸写作字号与菜单一致（17 / 19 / 21px）。
- 原文覆盖审计显示"已全部覆盖，事实库已更新 / 未变"，不再是"尚未提供"。
- 320px 宽的桌面窗口不再横向滚动（稳定的 10px 滚动条槽）。
- 证据不足的问题不再挡住"审阅事实变化"：按钮与待处理数采用与后端 `create_changeset` 相同的规则，只计允许作者决定的问题。
- 对比度达到 WCAG AA：白字紫底改用 `#8150e8`（悬停 `#7845df`）；已决定问题行不再整行变淡；作品问答与修订计划两个折叠面板保持原生 `details` 角色。
- 新检查开始后清除属于上一次检查的问题抽屉与受控修改；受控保存不再把新运行与旧问题拼在一起（原为不可重试的 422）。
- 教学中点击"查看完整证据"后，键盘焦点留在证据抽屉内。
- 后端 uvicorn 空闲连接保持 75 秒（`--timeout-keep-alive 75`），长于 Next.js 代理的 5 秒，避免页面并发请求时连接被重置。
- 轻量微动效（`motion.css`，沿用现有 120–220ms 时长与缓动，位移不超过 4px）：按钮按下下沉 1px；居中弹窗与提示淡入；保存与检查状态标签过渡，保存中、排队与检查中轻微呼吸；新的问题列表依次出现；记录决定后问题行与待处理数平滑过渡。系统开启"减少动态效果"时全部关闭。

## 验证

部署前在 Windows 本机：
- 浏览器端到端测试统一入口 `npm run test:e2e`（8 组），加入微动效后连续两次 124/124；此前第 4 批验收同样连续两次 124/124。
- 后端 462/462（同日首次运行与前端构建并行时有 1 个未能定位的失败，单独重跑通过），评测 51/51；lint、typecheck、build 通过；`test:build-origin` 44/45，唯一失败为已知的 "canonical HTTPS proxy exposes public health…"。

部署（服务器，逐步执行）：
- `plan` 的 inventory 与本机一致；`build` 与 `verify` 均为 `verified: true`、99 个文件；归档 SHA256 与本机一致。
- `release.sh` 退出码 0；backend、frontend 镜像 `v150-b9f4b0f-20261003` 构建完成，容器 healthy；`release-state` 当前 `v150-b9f4b0f-20261003`、上一版 `ui-26ae621-20261002`；`readiness` 200。

部署后（访客身份，公开站点）：
- 线上样式包含 `motion-dialog-in`、`motion-rise-in`、`motion-breathe`（位于 `prefers-reduced-motion: no-preference` 内）、主按钮色 `#8150e8` 与 `min-width: 310px`。
- 《灰港回声》写作与检查页：4 条问题中待处理提示为 3（证据不足的一条不计入）；主按钮背景 `rgb(129, 80, 232)`；问题列表使用 `motion-rise-in`。

## 已知限制

- 作品问答偶有 `evidence_unresolvable`（约 5%，按设计整条丢弃）。
- 真实模型下，长章节追加后的事实变化审阅有时未通过后端校验，长章节检查偶有"证据来源不可解析"，均属模型输出问题。
- `test:build-origin` 的已知失败：测试仍期待 compose 中的模型名为 `deepseek-v4-pro`，当前为 `deepseek-flash`。
- 自动实例外备份与外部告警仍按作者决定暂缓。
