# Flash V5 独立工程准备审查判据

2026-09-27。本文件是正式 runner 交付前独立制定的有界判据，**不是 V5 准备通过结论**。目前仅只读旧源码及材料，没有运行旧入口、测试、Provider、HTTP 或数据库。新 runner 未在本轮检查；等待主控交付后按下列关键路径审查，不轮询实施目录。审阅者仅在本目录新建证据，不改实施、产品或冻结材料。

## 已核实的复用边界

- `backend/app/provider.py:309-410`：timeout=30 秒，max_retries=1，仅 transport timeout 触发一次内部重试；JSON 模式、thinking disabled、temperature=0、max_tokens=2000。Provider 对非法 JSON 不追加语义修复。实际使用参数还须与 V5 freeze 比对。
- `backend/app/engine.py:293-330`：ContinuityEngine 每 batch 最多首请求加一次 contract repair；修复答可有保守降级。`engine.py:677-692` 的 WritingAnalysisEngine 仅一次 evaluate。因此在比较集每例确为单 claim、单 batch 的前提下，24 比较例最多 96 个生成 HTTP、6 G02 最多 12 个生成 HTTP，总上限 **108 generation POST + 1 models GET**。这只是允许路径的上界，不是应耗调用数；无超时/修复时为 30 POST。批次/任务形态改变须停止并交主控处理，不能扩大矩阵。
- `evaluation/current_flash_v2/run.py:183-218` 的旧 observer 将 business snapshot 和 parsed output 只留在内存；`:145-171` 在 HTTP 返回/异常后的 finally 才追加事件，丢弃原始 content。不能原样复用为 V5 的持久证据保证。
- `evaluation/current_flash_v4/run.py` 先 verify freeze 再检查重复身份；V5 必须先保护新身份。V3 `run.py:reserve_run_dir/execute` 可参考 create-only 和首失败保留，但它是旧记录离线重评分入口，不能当真实 runner。
- `evaluation/v2_fixture_loader.py:249-262` 提供持久、隔离合成 runtime；G02 可复用 V2 `isolated_app/g02_one` 的当前 API 路径，但须使用新工作根且审查 observer。比较集应使用 V2 四份 corpus 和 V3 标签，由真实当前 API 构建请求后核对 V2 capture；只允许已声明的瞬时身份归一化，不能仅比较少数便利字段掩盖选中来源变化。
- V3 `score.py` 继续传递调用 V2 `score.py` 和当前 `ContinuityEngine.validate`。其 raw gate 默认禁止保守降级；机器 pass 仍为 `pending_manual_review`。V2 `score_one` 对非 completed 状态直接 terminal_failure，不能在适配中丢掉此门槛。

## 放行前检查

| ID | 必须成立的事实 | 有界独立检查/负控 |
|---|---|---|
| E01 身份先行 | 重复/非法 run 身份在读取 corpus/capture/已保存答案、读凭据或创建 DB 前拒绝；结果及 workspace 均唯一；路径留在 V5 指定根内 | 一次非法身份、一次结果目录已存在、一次 workspace 已存在；在材料读取处放置哨兵，确认不会触达。有效新身份后的配置失败仍留 first-failure，复用该身份不得改写它 |
| E02 冻结闭包 | 基线为 7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2；新 manifest 固定 30 个身份/顺序、去重政策、实际参数、runner/observer/fixture/scorer/当前产品依赖及上游 corpus/capture hashes | 静态追踪直接及关键传递 import/read 路径。特别纳入 V3+V2 scorer、fixture loader、所复用的 V2 runner、V4 G02 cases、V2 四 corpus/capture 与相关 app/schema/seed/settings 源码；无需泛扫第三方库。任一受保护 hash 不符必须阻断，不改旧清单 |
| E03 输入先落盘 | 每一次 evaluate（含 repair）及其 HTTP attempt 发起前，可恢复的脱敏 business request、稳定 case/阶段身份、源章节/span/Memory 绑定、选中原文及摘要 hash 已持久化；写盘失败不发送 | mock transport 的 post 入口直接读回文件并重算 canonical hash；一次注入持久化失败确认零网络发送。保存完整合成业务快照，不保存 key/Authorization/cookie/隐藏推理 |
| E04 派发账可辨认 | 逻辑输入、evaluate 调用、transport attempts、models GET 分账；HTTP 前 reservation 与返回/异常后 observation 配对 | 超时后成功应保留两次 attempt；guard 拒绝不能算派发。进程中断遗留 reservation 只能报告未完成/派发未知，不能伪称实际服务器已接收或计零 |
| E05 首答分层 | 原始可见 content、首个可解析业务 JSON、contract repair payload、最终产品各有独立身份；空白/非 JSON 首 content 不得用后答替换 | 一次非法 JSON、一次合法 JSON 但合同失败后 repair 的固定响应；核对 raw content 顺序/hash、parse 状态、repair 标志以及 first-parseable 是否来自 repair。只存可见 message.content 与安全元数据，不存完整 HTTP 响应/隐藏 reasoning |
| E06 用量诚实 | complete/missing/partial/unknown 可区分，非负整数并排除 bool；输入+输出与 total 一致才能完整。超时/非法响应的未知部分不能变零 | 参数化检查完整、缺 usage、缺一个字段、数值非法/负数/bool、total 不一致、timeout 后成功。部分已知数单列，总量不完整则 complete totals=null；成本无返回标 unavailable |
| E07 次数有界 | 30 个逻辑输入各一次；每例单 batch，比较例最多 2 evaluate×2 timeout attempts，G02 最多 1×2；全局 POST<=108，models GET<=1；没有质量失败后的外层补跑 | 静态枚举 loop 与上限，mock 覆盖最后一个允许派发和下一次拒绝；质量失败照常交付。不得为凑 30 completed 自动重开已运行例 |
| E08 服务停止 | models 不可用或 400/401/403/404 立即终止；连续两例 service failure 停止；业务 schema/证据错误与 service failure 分开；停止后其余例为 not_run | 各一条 auth、两条连续服务失败、服务失败-正常-服务失败的 mock 序列；不得停止后继续派发。保留触发事件及已知 usage，不把未运行例放入完成分母 |
| E09 原始评分不漂白 | raw first/repair 各用其对应 request 严格评分；final 用实际持久产品视图；failed/timed_out/running/cancelled 配空 issues 仍 terminal_failure | 一条 final failure+空 issues、一条严格 raw 失败但允许产品降级、一条合理 state_change。沿用已验收 V3，不重做 45 项旧评分控制；人工类别与引用语义留待逐答复核 |
| E10 隔离与保存 | 仅新合成 DB、新 V5 文件；默认 app 禁用，测试 settings 禁 SMTP/生产配置；异常也保留首失败和已产生事件；保护清单前后不变 | 静态核对所有输出路径和 settings；检查每个尝试文件 create-only。离线探针仅使用 mock transport 与本目录临时合成资料；不连接真实服务、不读取 .env/凭据/业务 DB |

## 收口规则

独立探针只覆盖以上首次执行风险与关键反例，不追求通用恶意 JSON 或全仓测试。实施方已有的有意义自测可复核；不为通过率扩充重复测试。对当前既有 scorer 暴露的任意格式异常，可在新 runner 保留 `unscorable` 与首失败，不能改产品/旧评分器来刷绿。

只有在主控提供完成版本、以上证据无阻断且源码/冻结 hash 一致后，才可向主控给出“工程准备限定通过”。该状态不等于真实执行、模型质量通过、用户接受或发布。真实运行后的独立验收另逐例核查保存内容、派发账与 usage，并人工审查结论/自身引用关系；本文件不授权审阅者调用 Provider。
