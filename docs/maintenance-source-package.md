# 维护发布源包

本工具只在本地读取显式清单中的源文件，生成可逐文件核验的 Linux 构建输入。生成源包、源码测试通过、容器构建通过和部署上线是不同的状态。

2026-09-13（Australia/Sydney）发布 `maint-e2d141c23d0c-20260913` 已完成生产构建与切换，详见 [维护部署记录](maintenance-deployment.md)。冻结 inventory SHA256 为 `e2d141c23d0ccab25ccf1fd24b7f0ea0821493a6f892c7b784680f7f492b0402`，归档 SHA256 为 `acd9e4073fd217c423c69c80a932abd25bf0ce243f0d404e227e129d7656431b`。这些是源包身份，不是 Git commit。本页及当前说明在发布后更新，不能将当前工作区重新打包所得字节视为原部署归档；原归档、`SOURCE-PACKAGE.json` 和运行镜像继续保留冻结身份。

## 清单与命令

当前清单为 `docs/maintenance-release-manifest.json`。`include` 中每条记录都指定仓库源文件及包内目标文件；目录不是通配授权。`complete_trees` 只检查是否遗漏新源码，不会自动纳入文件。`verification_files` 记录本地测试与历史文档归属，不进入包。历史 `v1.3.0-release-allowlist.json` 保留当时版本、范围和动作记录，其 `current_manifest` 指向当前清单；历史动作列表不构成本次操作授权。

已部署冻结清单为 92 个 include、120 个 verification_files。发布后新增部署说明和发布脚本回归归属，当前工作区清单为 93 / 121，供以后重新冻结打包使用；其 `local_source_candidate` 描述工作区的下一份源包，不表示已部署维护版本仍未上线。没有重建或覆盖已部署归档。

在仓库根使用 Python 3.10 或更新版本（本轮实际测试使用仓库虚拟环境）：

```powershell
.\.venv\Scripts\python.exe deployment/build-maintenance-source.py plan
```

冻结所有待交付源码和说明后，重新运行 `plan`，保存其完整 JSON 及 `inventory_sha256`。随后用实际摘要生成新文件：

```powershell
.\.venv\Scripts\python.exe deployment/build-maintenance-source.py build --expected-inventory-sha256 <冻结清单摘要> --output <本地新路径>/maintenance-source.tar.gz
.\.venv\Scripts\python.exe deployment/build-maintenance-source.py verify --archive <本地新路径>/maintenance-source.tar.gz --expected-inventory-sha256 <冻结清单摘要>
```

`build` 拒绝覆盖已有包。工具会在构建前后重读并比对来源；冻结后任何选中文件或清单变化均拒绝继续。相同字节、清单和工具环境生成相同归档字节：文件排序固定，mtime/uid/gid 归零，权限固定，gzip 不记录当前时间和文件名。归档内 `SOURCE-PACKAGE.json` 记录逐文件来源、目标、字节数及 SHA256；外部验收记录保留整个归档 SHA256。内置摘要用于检测损坏与不一致，批准的摘要必须另行保存，摘要不是发布者数字签名。

## 包含范围与安全校验

包内包含全部当前 `backend/app`、前端 `app/public`、npm 锁文件和构建配置、后端 requirements、Docker/Compose/release/rollback/restore 与运维脚本、当前说明。前端映射为 `frontend-source/`，满足现有 Dockerfile；`deployment/.dockerignore` 映射到包根 `.dockerignore`，使 Docker context 使用显式构建白名单。

环境凭据、秘密目录、运行数据库、私人 evidence、冻结 evaluation、AGENTS/CLAUDE、本机依赖、编译产物、测试和浏览器 trace 不打包，也不为扫描打开这些排除文件。唯一环境模板是已审核的 `deployment/deploy.env.example`，其中没有 API key、密码或令牌。

离线校验拒绝路径穿越、绝对路径、大小写重名、链接、特殊文件、异常文件名、私钥/常见凭据格式、重置链接令牌、数据库及本机可执行文件签名、个人绝对路径，以及 Linux 脚本的 CRLF。此校验不读取真实凭据做精确匹配，也不声称能识别任意编码的秘密；显式选文件、代码审阅和凭据保持在目标机仍是必要条件。

## 部署前置条件

本地源包准备不执行以下部署动作。按本轮先本地验收再上线的顺序，取得目标机访问后执行：

1. 将批准的归档与独立保存的 SHA256 对照，再用 `verify` 校验归档；解包到新的版本目录，保留旧版本及回滚镜像。
2. 在目标 Linux amd64 主机检查 Docker/Compose、HTTPS 域名、磁盘空间和持久卷。沿用当前线上根目录与运行卷，先做在线 SQLite 一致备份，再验证独立副本和隔离恢复。
3. 在包外填写部署环境文件，校验根用户持有的 `0700` secret 目录及 `0600` secret 文件。Provider/SMTP/恢复密钥仍从目标机挂载；不放入源包。
4. 在目标机用既有 Dockerfile 构建 backend/frontend，执行 `verify-frontend-image.sh` 的 Linux amd64/musl/native-module 检查。npm 使用锁文件；Python 直接依赖固定版本，但传递依赖、系统 apt 仓库和基础镜像标签仍受外部仓库影响，本包不承诺容器位级重现。
5. 执行 `release.sh` 后，以真实 HTTP readiness、浏览器 JS/CSS/图片加载、登录/隔离及本轮新增作者流程核验线上版本。健康检查成功不能替代作者流程验收。
6. 运维安装和启用分别操作，检查 systemd 定时器及状态文件；自动实例外复制在用户决定启用后另行配置并验收。当前已完成手动工作站副本及 SQLite 恢复验证，自动复制与外部通知由用户暂缓，参见 `operations.md`。

源包本身不包含生产数据库、不执行迁移、不发 Provider/邮件请求，也不启动运维调度。当前包准备和测试结果记录在本地维护验收产物中；源码未冻结时的 plan 只作为候选清单。

本维护版本完成初始化后登记 schema 146。`rollback.sh` 在切换前探测目标镜像的 `rollback-capabilities`，再由当前后端只读执行 `rollback-preflight`。目标缺少命令、版本或历史修订契约时停止，不自动恢复旧库。相关本地验收使用 MSYS 与 Docker stub；部署时另已完成真实 Linux 镜像构建、迁移数据比较，以及旧镜像能力缺失和不兼容契约的拒绝检查。未实际回滚切换或恢复数据库，不能记录为完整回滚演练。
