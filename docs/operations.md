# 日常运维与本地恢复演练

本维护工具为独立 Python 标准库 CLI，不启动应用、不导入 Provider，不读取 `.env`，不修改产品数据结构。现有 `app.deployment` 的上线备份、迁移与停机恢复能力继续保留。2026-09-13（Australia/Sydney）已在生产安装并启用三个计时器，首跑和后续监测周期均有实际回执；用户已明确暂缓自动实例外复制与外部通知，作为可选后续项。见 [维护部署记录](maintenance-deployment.md)。本页为冻结源包之后的说明更新。

## 维护范围

| 操作 | 行为与证据 |
|---|---|
| `backup` | 只读连接源库，SQLite online backup API 获取一致快照；检查 SHA256、完整性、外键、迁移版本与表计数摘要；文件权限 0600。在线 WAL 数据被纳入快照。 |
| `drill` | 最新快照按哈希复制到独立临时目录；验证 schema/计数摘要；提交一次写入，重新打开读取再清理；原始数据库与快照均不被恢复覆盖。 |
| `monitor` | health/readiness 每 5 分钟探测；异常 JSON、HTTP 失败、备份过旧/损坏、缺少实例外副本、恢复演练过旧、失败/超时/预算暂停 Run、卡住 Run 产生本地结构化告警。 |
| `usage` | 读取当前保留数据的滚动 24 小时 Provider Run、attempt 与 reservation 汇总；不包含账号、正文、Prompt、原始响应或邮箱。 |
| `retention` | 默认保留至少 7 个新快照、30 天内快照；仅报告更旧候选，不删除任何文件。旧维护流程的备份完全不参与自动处理。 |

默认调度：每 6 小时备份，每周日恢复演练，每 5 分钟监测；时间按服务器本地时区。OS 文件锁防止同时执行维护；进程死亡后锁由操作系统释放。锁冲突会失败并保留可观察状态，下次定时执行重试。备份最长 5 分钟、网络请求最长 10 秒，SSH 传输有界超时；维护源 SQLite 始终以只读模式打开。

备份 manifest、`last-drill.json`、`monitor-latest.json`、`alerts/*.json`、`usage-latest.json`、`usage/*.json` 和 `retention-latest.json` 是检查入口。告警只在异常集合变化时增加记录，恢复也记录为空的异常集合；不会发送邮件、聊天通知或向第三方推送正文。控制台输出和 systemd journal 同时能看到退出状态。退出码 0 为操作成功，2 为已完成检查但存在待处理问题，1 为执行失败；未配置真异地目标时，备份文件成功生成仍返回 2。

## 本地复验

从仓库根目录使用项目虚拟环境：

```powershell
& .venv\Scripts\python.exe deployment\ops-local-acceptance.py
```

脚本只创建临时的全新数据库和本机 HTTP fixture，运行单元测试与五个维护 CLI 命令，执行完整 schema 的恢复写入演练。数据库和镜像副本随临时目录清理，汇总保留在 `artifacts/current-stage-completion/operations`。`local_test_mirror` 是同机不同目录的传输/哈希演练，明确标记 `is_off_instance=false`，不会清除“缺少实例外副本”告警，也不能用它宣布线上运维生效。

## 生产安装准备

依赖：Ubuntu systemd、Python 3.10+、OpenSSH 客户端；无需新增 pip 依赖。部署前先核实实际卷路径，不能假定示例路径有效：

```bash
sudo docker volume inspect story-continuity-runtime --format '{{.Mountpoint}}'
```

把返回路径下的 `data/demo.sqlite3` 填入独立的运维 JSON 配置。参考 `deployment/ops-config.example.json`，配置只含路径、阈值、健康检查 origin；不得复制应用环境文件或密钥内容进去。输出目录必须与源数据库目录互不重叠。使用当前已验收的源码包，在服务器运行：

```bash
sudo bash deployment/ops-install.sh /absolute/reviewed-ops-config.json --install-only
```

这只安装，不启动计时器。完成本地整体验收、配置检查以及线上启用授权后，执行：

```bash
sudo bash deployment/ops-install.sh /absolute/reviewed-ops-config.json --enable
sudo systemctl list-timers 'story-continuity-ops*' --no-pager
sudo systemctl status story-continuity-ops@backup.service story-continuity-ops@drill.service story-continuity-ops@monitor.service --no-pager
sudo journalctl -u 'story-continuity-ops@*' -n 30 --no-pager
```

安装脚本不会切换应用 release 或恢复覆盖运行库；首次运行异常不会阻止后续监测计时器启动。必须核对三个计时器 active、最近备份 hash、`last-drill.json` passed、告警详情及实例外副本回执后，才可记录对应项已在线生效。停止调度可运行 `systemctl disable --now` 并列出这三个 timer 名称；不会删除既有备份。

## 真正实例外副本

本节是用户未来决定启用时的操作参考；当前已明确暂缓，不等待目标配置。生产可选用已授权、可达的另一台 Linux 机器作为目标。在目标提前创建仅备份账号可写的目录，部署受限 SSH 身份文件，并人工核对、保存目标主机密钥。配置增加：

```json
{
  "offsite_ssh": {
    "target": "backupuser@backup-host.example",
    "directory": "/srv/story-continuity-backups",
    "identity_file": "/etc/story-continuity-ops/backup_identity"
  }
}
```

传输使用 BatchMode 和 StrictHostKeyChecking，不自动信任未知主机；不建立目标账户或改安全组。SCP 上传临时文件后，由目标 Python 再算 SHA256 和字节数、0600 原子改名；两端 `/etc/machine-id` 哈希需不同，才记录 `is_off_instance=true`。源文件、目标快照文件名唯一，不覆盖既有副本。无目标、凭据不可用、传输/校验失败或无法证明机器独立时明确失败；不把第二个本地目录当作异地备份。外部目标、传输可达性和真实恢复速度需线上启用阶段验证。

备份含账户与作品数据，是私有恢复资料；0600 和加密 SSH 传输已经落实，静态磁盘加密由目标存储策略负责。不要放入 Git、公共网站或公开附件。本 CLI 不提供业务库恢复命令；真正故障时依然使用已有 `docs/stage14-deployment.md` 的停机恢复流程，先备份当前库，再选快照并检查 schema 兼容性。每周演练验证的是 SQLite 层的恢复可用性，不代替新应用版本迁移验收或灾难恢复演习。

## 费用与覆盖口径

缺失 token/费用为 `unknown` 和 JSON `null`，分别保留已知项小计、已知/未知 Run 数。预算 reservation 是配额预留，不是已消费金额。`billed_cost_cny` 始终保留 unknown，因为这些产品记录不能独立证明供应商账单。

窗口包含最近创建或完成的 Provider Run；卡住检查还覆盖更早的 active Run。预置演示 Run 被排除。失败增量批次可能给两个 Run 记录同一合计，所以 `run_observed_metrics` 不能当作可加总账单；初始化调用和已清理访客可能缺乏完整 Run 数据。attempt 数来自独立表，表不存在时为 unknown。每小时文件是一次滚动快照，多份不可相加，也不是不可变、完整的供应商交易账本。要获得准确全量费用，后续需接供应商用量账单或在调用边界建立持久计费事件；本次没有冒充已经具备这些证据。

## 当前验收状态

本地自测覆盖 WAL 快照、损坏拒绝、完整 schema 恢复、源数据不变、同机镜像真实标签、过旧/失败/卡住告警、unknown 费用、仅报告的保留策略、health/readiness 真 HTTP 响应和路径隔离。初轮 Windows 测试发现 SQLite context manager 不关闭句柄，导致临时文件重命名和清理失败；已改为显式 closing 后复验。本地结果保留于 `summary.json` 和 `self-test.txt`；当时同机测试的范围不因后来部署而改变。

生产安装按 install-only、串行首跑、单独启用调度的顺序完成。18 项首跑检查为 true，结果 `local_components_passed_with_warnings`、退出码2；schema146 快照、哈希/完整性/外键校验、独立目录恢复写入、原备份不变及 health/readiness HTTP200 均有回执。三个 timer enabled/active；监测在服务器 CST 22:55:57 首触发后，于 23:01:01 再次自然触发并排出 23:06:07，已观察一个重复周期。6小时备份和每周演练的后续自然周期尚未观察。

部署前后两份备份已手动下载至操作者工作站并独立核对 SHA256，部署后副本还完成隔离 SQLite 恢复写入及重开读取验证，原备份不变。这是一次性实例外留存；用户暂缓的自动 offsite 复制仍未配置，`offsite_copy_missing` 保留。外部通知也已暂缓且未实现；本地 JSON/journal 正常不代表故障已送达操作者。保留策略仍只报告、删除数0。首跑24小时窗口 Provider Run/attempt 为0，供应商账单仍 null/unknown，不能据此声称历史费用为0。维护验收没有调用 Provider 或 SMTP，也没有做完整应用灾难恢复。
