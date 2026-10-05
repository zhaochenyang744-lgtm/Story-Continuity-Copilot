# 2026-09 维护更新：生产部署记录

2026-09-13（Australia/Sydney）已将 v1.4.0 维护更新部署至 [公开站点](https://43-160-207-57.sslip.io)，release 为 `maint-e2d141c23d0c-20260913`，生产 schema146。本页是在源包冻结之后追加的说明；历史 [9月8日部署记录](v1.4.0-deployment.md)、本地测试和模型原始结果均保留。

## 发布身份

| 项目 | 已确认值 |
|---|---|
| 冻结源清单 SHA256 | `e2d141c23d0ccab25ccf1fd24b7f0ea0821493a6f892c7b784680f7f492b0402` |
| 归档 SHA256 | `acd9e4073fd217c423c69c80a932abd25bf0ce243f0d404e227e129d7656431b` |
| Backend image | `sha256:2fd00ee037343a4d9e00be379f937c48073146a754b5e40ed037823fc8b0f32c` |
| Frontend image | `sha256:d5def1bee0899b9c7bfd7ffea4929abdaf00e3b3d04ee89ba19c1b49982a64f3` |
| 切换完成 UTC | 2026-09-12 14:54:06.510061 |
| 上一 release | `v140-4bd8d93-20260908` |

源清单摘要不是 Git commit。上述归档和运行镜像保持原字节身份；发布后工作区说明变动单独记录，不宣称已进入运行镜像。

## 迁移、服务和浏览器

先完成真实 Linux 镜像构建与隔离迁移，再切换生产。schema145→146 的隔离比较和开放前端前的生产比较均保留 67 张既有业务表、661 行数据，新增6张 workflow 表；既有迁移行保留、changed_table_count=0、integrity=ok、FK violations=0。比较发生在验收新数据创建前。前后端 healthy，公开 readiness HTTP200。

2026-09-12 14:59:41–14:59:58 UTC，在全新访客的三章作品上完成7项浏览器检查：HTTPS、当前界面与图像、实际 TXT/Markdown/ZIP 下载及校验、维护页当前正文与 HTTP409 修订守卫零变化、移动只读无溢出、新 JS/CSS 加载。实际下载3个文件，加载10个 JS/CSS，page error/5xx/被阻断请求均为0；桌面和移动截图经主验收任务查看，导出文件另经独立校验。

这轮线上没有重跑成功修订提交、跨 Run 作者判断复用、事实确认或外部 Provider。相关成功流程仍以 [本地维护验收](maintenance-acceptance.md)和[当前模型验证](current-model-acceptance.md)为证，不能把当前7项线上检查扩大为全部作者流程、模型零误判或真实用户研究。

## 备份、调度与保留项

部署前 schema145 和部署后 schema146 的一致备份均已实际下载至操作者工作站，分别流式核对大小1,318,912字节及 SHA256；这是一轮手动实例外留存。部署前静默窗口的新备份与已下载基线 hash 一致。部署后副本在工作站另做隔离SQLite恢复、完整性/外键检查及提交写入、重新读取验证，原备份不变；这不等于完整应用灾难恢复。备份文件保存在私有恢复资料中，不进入 Git 或公开附件。

生产运维按安装、串行首跑、单独启用调度执行。18项首跑检查为 true，返回 `local_components_passed_with_warnings`（退出码2）：一致备份、hash/完整性/外键、隔离 SQLite 恢复写入及原备份不变、health/readiness 均通过。三个 timer enabled/active，监测从服务器 CST 22:55:57 到23:01:01实际重复，采样时下一次排在23:06:07；6小时备份与每周演练已设置，验收采样时尚未观察后续自然周期。

用户已明确暂缓自动实例外备份与外部通知，保留为可选后续项，不再等待目标或渠道。自动复制尚未配置，`offsite_copy_missing` 告警保留；当前只有本地 JSON 与 journal。手动工作站副本不代替持续复制，机器分离也不独立证明跨地域容灾。工作站 SQLite 恢复演练不代替完整应用恢复。保留策略只报告，删除数0；供应商账单为 null/unknown，空的24小时运行窗口不能证明历史费用为0。命令和限制见 [运维说明](operations.md)。

## 回滚边界与证据归属

真实 Linux 上旧镜像缺少 `rollback-capabilities`，代码探测退出2；当前后端只读 preflight 拒绝无历史修订契约的目标，退出1、`rollback_workflow_contract_unsupported`。这验证了兼容性拒绝，没有实际切回旧 release 或恢复旧库。旧镜像保留不代表可以直接承接 schema146 数据。

完整包外回执保存在 `current-stage-completion/deployment`：`production-verification.json`、两个独立工作站备份回执、`ops-first-run-console.txt`、`ops-timers-enabled-console.txt`、`ops-monitor-recurring-console.txt` 和 `online-acceptance-01/acceptance.json`。早期首跑记录的“调度未启用”是其采样时的真实状态，后续记录补充启用结果而不覆盖它。真实作者研究、完整账单、商业 SLA 和完整灾难恢复仍无完成证据。

## 发布后的工具修复

2026-09-12 15:05:47 UTC 已单独同步 `deployment/release.sh`：显式版本参数在读取环境文件后设置，防止环境中的值覆盖调用者指定版本。真实Bash定向回归1 passed、2 subtests passed。脚本SHA256从 `7106b882184691ad9abbe015a517d44e938fc26da0be1e53210175fd39a05ac2` 改为 `1819a587e9e610284209219d557299b7a3120448afd41c9bac85bc862f2f8374`。当前服务器环境原无RELEASE_ID字段，已新增实际maintenance版本号，默认Compose镜像配置核对一致。修复没有重启服务或操作数据库，原归档与运行镜像未修改；服务器发布脚本的这次字节变化单独记录。
