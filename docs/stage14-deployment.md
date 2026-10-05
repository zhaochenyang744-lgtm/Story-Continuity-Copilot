# Story Continuity Copilot v1.0 Public Release — 腾讯云 Lighthouse 部署 Runbook

本文是部署操作手册，不是产品 Gate 结果。62 号冻结文档中的 OCI 候选保留为历史决策；有效托管平台由腾讯云 Lighthouse 平台替换附录定义。最终 Gate 结果见 65 号独立验收与签署记录。

以下为部署前由用户确认的实例信息，保留为当时时点记录：

- 地域：新加坡
- 系统：Ubuntu 24.04 LTS
- 规格：2 vCPU、4 GB RAM、60 GB SSD、200 Mbps
- 公网 IPv4：`43.160.207.57`
- canonical hostname 候选：`43-160-207-57.sslip.io`
- 用户已确认 DNS A 解析；当前 TCP 22 可达，80/443 不可达

2026-08-31 后续部署和 PM3 独立验收已完成，冻结 Required Gates A–G 已签署通过，统一名称为 `Story Continuity Copilot v1.0 Public Release`。本 runbook 中“当前不得执行”“部署前”等措辞是历史操作边界，不作为新的执行授权。

## 1. 当前架构

- Caddy 是唯一公网入口，只发布 80/443；443/UDP 仅用于同端口 HTTP/3。
- Next.js 只在 Compose 私网监听 3000，不映射宿主端口。
- FastAPI 只在 Compose 私网监听 8000，不映射宿主端口，固定一个 service replica、一个 Uvicorn worker。
- SQLite runtime volume 挂载到 `/app/runtime`；应用备份 volume 挂载到 `/backups`。
- 两个 Docker named volume 都位于 Lighthouse 60 GB 系统盘，它们是逻辑隔离，不是独立故障域。
- Provider 与 SMTP 仅由 backend 读取；浏览器、Next.js、镜像层、Git、日志和证据不得包含 secret。

## 2. 腾讯云平台边界

Lighthouse 防火墙只控制入流量，并支持按单个 IP 或 CIDR 限制来源。部署前的允许规则应只有：

- TCP 80：`0.0.0.0/0`
- TCP 443：`0.0.0.0/0`
- UDP 443：`0.0.0.0/0`，仅在启用 Caddy HTTP/3 时保留
- TCP 22：优先删除公网全开放规则；确需 SSH 时只允许管理员固定 IP/CIDR。也可使用腾讯云控制台 OrcaTerm/自动化助手，并按腾讯云要求仅允许其代理网段。

不得开放 3000、8000、SQLite/数据库端口、Docker daemon 或任意全端口规则。操作系统 UFW 应重复执行同样的最小入口策略，形成双层边界。

腾讯云快照复制整块系统盘。快照过程中仍在内存中的数据可能未完整落盘，因此数据库快照前必须先完成应用级 SQLite online backup，并在需要强一致快照时停止 Caddy、frontend 与 backend。快照回滚不可逆，会清除快照时间点之后的整盘数据。

销毁 Lighthouse 实例会同时删除该实例快照；重装会清空系统盘。因此：

1. `/backups` 不能作为唯一备份；
2. 重装、回滚系统盘或销毁实例前，必须把经 SHA-256 校验的 SQLite backup 复制到实例外的用户控制存储；
3. 禁止把“存在云快照”写成“已具备独立灾备”；
4. 不自动删除历史 backup 或 snapshot，磁盘空间不足时先停机并由用户决定保留策略。

腾讯云官方依据：

- <https://cloud.tencent.com/document/product/1207/44577>
- <https://cloud.tencent.com/document/product/1207/48546/>
- <https://cloud.tencent.com/document/product/1207/44576>
- <https://cloud.tencent.com/document/product/1207/44608>
- <https://cloud.tencent.com/document/product/1207/54228>
- <https://cloud.tencent.com/document/product/1207/44642>

## 3. Secret 目录冻结

`SCC_SECRET_DIR` 固定为：

```text
/etc/story-continuity/secrets
```

宿主目录必须是 root-owned `0700`，以下五个文件必须是 root-owned `0600`、regular file、non-symlink、non-empty：

- `CONTINUITY_API_KEY`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `RECOVERY_HASH_SECRET`

Compose 将该目录只读挂载到 backend 的 `/run/secrets`。容器入口先以 root 读取文件并导出到当前进程环境，然后使用 `gosu` 降权到 UID/GID 10001 运行迁移与 FastAPI。secret 不作为 Docker build arg、不进入 image layer、不写入 `deploy.env`，也不得通过聊天发送。

`deployment/secret-dir-check.sh` 在 release、rollback、restore 前只检查存在性、owner、mode、文件类型与非空状态，不输出 secret 内容。威胁边界仍包括：宿主 root、Docker daemon/root 等价用户、运行中 backend 进程和具备宿主磁盘读取权的腾讯云控制面；其他本地用户、frontend、Caddy 和 Git 不应获得读取权限。

## 4. 本地生成脱敏 Bundle

PM3 必须使用独立 `stage14pm3` profile 与全新的 system-temp bundle root 重建，不复用实施 bundle。

```powershell
$bundle = Join-Path ([System.IO.Path]::GetTempPath()) ("story-stage14-bundle-" + [guid]::NewGuid().ToString("N"))
& .\frontend\scripts\stage14-bundle.ps1 `
  -Profile stage14impl `
  -RepositoryRoot (Get-Location).Path `
  -BundleRoot $bundle `
  -PublicBaseUrl 'https://43-160-207-57.sslip.io'
```

bundle builder 只复制冻结的最小 `frontend-source`（`app`、可选 `public` 与八个根构建文件）、production-only backend/deployment，并写入 `linux/amd64/musl` 平台元数据后执行整包脱敏扫描。它不在 Windows 生成或携带 `.next`、standalone、`node_modules` 或任何 native module；Next.js 的 `npm ci + build` 只能由 `Dockerfile.frontend` 在 Linux/amd64 Alpine build stages 内完成。

scanner 必须同时满足：`frontend-artifact` 不存在、source 根 allowlist 精确匹配、`node_modules/.next/tests/AGENTS/CLAUDE/.env` 不存在、PE/ELF/Mach-O/native files 为 0、平台元数据与 Dockerfile/Compose 契约一致。2026-08-31 首次腾讯云 bundle 因携带 Windows `sharp-win32-x64` standalone 被 PM3 判定失败，属于保留的失败证据，不得上传、复用或改写为通过。

## 5. 腾讯云控制台前置清单

以下动作必须由用户在控制台完成；本地线程不得代替：

1. 核对实例、地域、套餐、到期日和续费设置。
2. 删除 22 的 `0.0.0.0/0` 规则；选择固定来源 SSH、OrcaTerm 代理网段或自动化助手。
3. 新增 TCP 80/443；需要 HTTP/3 时新增 UDP 443。不要增加其他公网端口。
4. 开启账号操作保护；确认快照配额可用。
5. 准备已验证的 SMTP sender 和真实可收件验收邮箱，但不要把凭据发送给实施线程。
6. 用户单独授权远端操作后，才可开始下一节命令。

## 6. 远端执行命令草案（当前不得执行）

### 6.1 安装与主机防火墙

Ubuntu 仓库安装草案；若 `docker-compose-v2` 不存在或安装产生套餐外费用，立即停止：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

UFW 草案。`ADMIN_CIDR` 必须由用户现场确认；如果只用控制台通道，不添加公网 22 规则：

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw allow from ADMIN_CIDR to any port 22 proto tcp
sudo ufw enable
sudo ufw status numbered
```

### 6.2 上传与目录权限

本地上传草案中的 `<SSH_USER>` 必须在用户确认登录方式后替换：

```bash
scp -r LOCAL_SANITIZED_BUNDLE <SSH_USER>@43.160.207.57:/tmp/story-continuity-release
```

服务器端：

```bash
sudo install -d -o root -g root -m 0700 /opt/story-continuity
sudo cp -a /tmp/story-continuity-release/. /opt/story-continuity/
sudo chown -R root:root /opt/story-continuity
sudo install -d -o root -g root -m 0700 /etc/story-continuity/secrets
for name in CONTINUITY_API_KEY SMTP_USERNAME SMTP_PASSWORD SMTP_FROM RECOVERY_HASH_SECRET; do
  sudo install -o root -g root -m 0600 /dev/null "/etc/story-continuity/secrets/$name"
done
```

用户只在服务器本地使用 `sudoedit` 填入五个 secret。不要使用会进入 shell history 的 `echo secret > file`，也不要把值贴入聊天。

### 6.3 非 secret 配置与发布

```bash
cd /opt/story-continuity
sudo cp deployment/deploy.env.example deploy.env
sudo chmod 0600 deploy.env
sudoedit deploy.env
sudo bash deployment/secret-dir-check.sh /etc/story-continuity/secrets
sudo bash deployment/release.sh ./deploy.env s14-YYYYMMDD-HHMMSS
```

`deploy.env` 只填写 hostname、Provider base URL、已授权费率与 SMTP host/port；不得写五个 secret。首个发布前必须确认：

```text
PUBLIC_HOST=43-160-207-57.sslip.io
SCC_SECRET_DIR=/etc/story-continuity/secrets
```

`release.sh` 在 `up` 之前执行 Linux multi-stage build，再强制运行 `verify-frontend-image.sh`：image manifest 必须为 `linux/amd64`，Node runtime 必须为 `linux/x64`，libc 必须为 musl，所有 `.node` 必须是 ELF，必须存在并可加载 `sharp-linuxmusl-x64`，且不得出现 win32/windows 文件。任一检查失败均不会启动新 release。rollback 对目标 frontend image 执行同一验证。

### 6.4 只读发布核对

```bash
cd /opt/story-continuity
sudo docker compose --env-file ./deploy.env -f deployment/compose.yaml ps
sudo docker compose --env-file ./deploy.env -f deployment/compose.yaml config
curl --fail --show-error --silent https://43-160-207-57.sslip.io/health
curl --fail --show-error --silent https://43-160-207-57.sslip.io/readiness
```

证据只记录 image ID、replica/worker 数、status、HTTP 状态、必要安全头与 presence-only secret 检查，不保存环境变量展开值。

## 7. 应用备份、快照、回滚与恢复

应用级 backup：

```bash
cd /opt/story-continuity
export RELEASE_ID=CURRENT_RELEASE_ID
sudo docker compose --env-file ./deploy.env -f deployment/compose.yaml exec -T backend \
  python -m app.deployment backup --backup-dir /backups --label pre-snapshot
```

记录命令返回的 backup filename、SHA-256、bytes、migration version 与 integrity，不记录业务内容。需要强一致系统盘快照时，再停止服务并由用户在腾讯云控制台创建快照：

```bash
sudo docker compose --env-file ./deploy.env -f deployment/compose.yaml stop caddy frontend backend
```

快照完成后使用同一 release ID 恢复服务。重装、销毁或系统盘回滚前，先把选定 backup 复制到实例外并再次校验 SHA-256。

应用镜像回滚不隐式回滚数据库：

```bash
sudo bash deployment/rollback.sh ./deploy.env PREVIOUS_RELEASE_ID
```

只有独立审查确认 schema 需要回退时，才允许显式停机恢复：

```bash
sudo bash deployment/restore.sh ./deploy.env RELEASE_ID BACKUP_NAME BACKUP_SHA256
```

restore 会要求 `APPLICATION_STOPPED`、验证文件名 containment、SHA-256、SQLite integrity/foreign keys，创建 pre-restore recovery backup，只替换 `/app/runtime/data/demo.sqlite3`，再运行幂等迁移。

## 8. PM3 所需证据

- 腾讯云实例规格与防火墙规则截图，隐藏账号身份和其他实例。
- canonical HTTPS origin、TLS 证书与 `/health`、`/readiness`。
- `docker compose ps/config` 的脱敏结果，证明只发布 80/443、backend/frontend 无 host port、FastAPI worker=1。
- secret directory presence/owner/mode 结果，不含文件内容。
- SQLite pre-release backup、restart persistence、snapshot、rollback、必要时 restore 的哈希证据。
- 实例外 backup 副本存在性与 SHA-256。
- Provider HTTP/workflow/cost 和 SMTP send 计数。
- source-only bundle 的 file-list/content SHA-256、`linux/amd64/musl` 元数据，以及 native/PE/identity/secret/absolute-path hits=0。
- Linux frontend image verifier、public browser/runtime scan，Level 0、1、4、win32/native mismatch 均为 0。

真实平台和 PM3 独立检查已经完成；最终状态为 `stage14_product_gate_passed=true`。历史部署前 `blocked` 事实、失败 bundle、失败部署和首次 Provider 安全失败继续保留。
