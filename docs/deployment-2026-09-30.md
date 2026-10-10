# 2026-09-30 生产部署记录

> **历史部署记录**：记录的是当时的发布过程，不随产品更新。现行说明见[当前产品](current-product.md)。

本日三次上线均由 Git 提交经 `deployment/build-maintenance-source.py` 打包，在服务器上 `plan` 校验 inventory 后 `build`/`verify`，解压到新目录，复制上一版的 `deploy.env` 与 `release-state`，再执行 `deployment/release.sh`。三次都没有数据库结构变化，旧版本目录和镜像保留作回滚目标。

## 发布身份

| release id | Git 提交 | inventory SHA256 | 内容 |
|---|---|---|---|
| `longform-bd090fe-20260930` | `bd090fe` | 见当时 plan 输出 | 长章节并行检查、证据去重、超预算对半拆分 |
| `longform-aac1517-20260930` | `aac1517` | `a129f2ccfe1d4d0926b009eaaba171f58251cedacdad0b281051d2a3bc0ccc24` | 额度预检与中途用完保留结果；修复 `split_draft_claims` 重名导致简报多拆对话句 |
| `ui-cbfa536-20260930` | `cbfa5368dc0eb06d2241b423001ba2ddf6838108` | `d3551e4a4ec75e174f358011c4ae37769b0b66b49f4df45ff35bc6f9b269bc14`（94 个文件） | "点数不足"文案与 `max_claims`；界面打磨第 1–6 批；手机输入框 16px |

2026-10-02 起线上为 `ui-26ae621-20261002`（见 [2026-10-02 部署记录](deployment-2026-10-02.md)），本版本成为其回滚目标。当时的回滚目标：`longform-aac1517-20260930`（`bash deployment/rollback.sh deploy.env longform-aac1517-20260930`，在新版本目录执行）。

## 模型配置

连续性检查使用 `deepseek-flash`，`CONTINUITY_REVIEW_THINKING=high`，`CONTINUITY_REVIEW_CONCURRENCY=4`（见 `deployment/compose.yaml`）。其他 AI 功能保持思考关闭。Provider 密钥只在服务器 secret 目录，容器启动时读取；更换密钥后需重启后端容器。

## 验证

**`longform-bd090fe`**：线上 37 句长章节由此前 240 秒失败变为 72.5 秒完成（3 批并行，各批合计 231.6 秒），记录见 `evaluation/results/prod-longform-after-bd090fe-20260930.json`。

**`longform-aac1517`**：部署前后端 456 个测试中 455 个通过（唯一失败为云端缺少本机保留的 `artifacts/` 文件），评测测试失败集合与 `bd090fe` 完全相同（Windows 路径）。部署后以新访客在线提交 130 句草稿，检查开始前即返回额度不足提示，未消耗调用。

**`ui-cbfa536`**：部署前在 Windows 本机：
- 后端 456/456，评测 51/51，lint、typecheck、build 通过；`test:build-origin` 44/45，唯一失败为已知的 "canonical HTTPS proxy exposes public health…"。
- `test:v130` 在 `aac1517` 与新版本上失败同样的 12 个测试；stage5/8/11j、auth-entry、v110 的失败同为旧界面测试未更新。为跟上当前界面修正了 4 个测试（`2944e76`、`4513763`、`170c51f`、`a153153`）。
- 使用真实模型打开章节简报、计划偏离、检查进行中与失败、点数不足与中途用完、导入后事实库初始化审核、事实库变更审核、作品问答、伏笔扫描、修订建议、修改影响分析等结果，分别在 1440px 与 390px 截图；新的点数文案在真实运行中出现。
- 部署后作者在公开站点人工核对新 Logo 与图标、作品管理、写作与检查、沉浸写作问题列表、"找不到"页面与手机输入框。

## 已知限制

- 浏览器端到端测试落后于当前界面，尚未恢复全绿；这是 v1.4 界面改版后遗留，不是本日改动引入。
- 真实模型下，长章节追加后的事实库变更审核有时未通过后端校验（`candidate_count_invalid`、`memory_type_invalid`），长章节检查偶有"证据来源不可解析"失败。二者属于模型输出问题。
- 事实库初始化与变更审核流程、检查结果技术详情中仍有技术措辞与原始编号，留待后续界面批次处理。
- 自动实例外备份与外部告警仍按作者决定暂缓，沿用 [维护部署记录](maintenance-deployment.md) 与 [运维说明](operations.md) 的范围。
