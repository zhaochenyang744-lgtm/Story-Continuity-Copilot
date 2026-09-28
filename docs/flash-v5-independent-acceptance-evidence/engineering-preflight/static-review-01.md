# V5 工程模块静态初审 01

2026-09-27。**状态：审阅未完成版本，存在待修项；不作技术放行。** 已读 `journal.py`、`inputs.py`、`run.py`、`score.py`、`build_cases.py`、`cases.json` 及必要产品/旧评分调用链。本次没有导入或执行这些模块，没有测试、HTTP、Provider 或数据库连接。实施者同期仍在修改，因此以下以函数/分支定位为准；不是最终 freeze 的版本验收。所有审阅新增文件仅在本目录。

## 必须在正式审查时关闭的发现

### S01 评分异常会终止剩余矩阵

`score.py:score_case` 将解析后的任意 JSON 直接送入旧 V3/V2 raw scorer。旧 V2 scorer 在读取 `raw.get("issues")` 前没有检查 raw 为 dict；合法 JSON 数组等可先被产品判 schema_invalid，却在评测评分阶段抛 AttributeError。`run.py:execute` 把该异常写为 first-failure 后上抛，导致剩余案例停止。

处理应限定在 V5 适配层：逐层记录 `unscorable`/评分错误及原始 payload，仍保存 final 和本例账目，仍检查服务停止条件，再继续后续允许案例。不得修改旧 scorer 或产品来使这些首答变正确。正式独立探针只需一个合法非 object JSON 和一个 scorer 抛错路径，确认原答/首失败不丢、后续允许案例不被评分异常吞掉。

### S02 G02 请求尚未绑定到同次数据库材料

`inputs.py:InputContract.g02` 检查请求内部 draft ID/revision、selected_ids、claim 范围以及专项样例条件，但没有对实际 DB 快照验证选中 source 的 chapter_id/body 或 Memory 的 value/source_span_id。`run.py:_binding_snapshot` 只写章节/span 的 hash，未校验请求；未包括 Memory 和 span 自身 revision。

因此把请求内某 source.chapter_id/body 改为伪值、或改 Memory.value/source_span_id，只要 ID 和计数仍自洽，现有 G02 输入校验仍可能接受。比较集有完整历史 capture 比较，G02 没有这个外部锚点。建议通过评测侧同次 runtime-binding 验证请求与合成 DB：project/draft/revisions、所选 source 及其实际父章节、Memory 语义字段及真实父 source 均应一致；不要求 Memory 关联的 source 必须入选，因为历史请求合法存在未选中来源。

### S03 G02 machine pass 的范围需要明确

`score_g02_raw/score_g02_final` 目前只检查每项和摘要具有 citation 且 source_type/source_id 在输入允许集合内。它不检查文本是否充分受自身来源支持，也不完整验证业务 schema。泛称 machine_result=pass 容易在汇总时被误读。

字段/说明应明确为 **citation-binding partial check**。人工审查继续负责逐项自身支持、摘要每个断言、时间与引语角色；不要求因此扩展重做产品 validator。该结果不能计作完整合同或语义通过。

### S04 JSON null 与无可解析响应应区分

`score_case` 通过 `parsed_business_json is None` 判断“没有解析结果”。Provider 可把可见 content `null` 解析为 Python None，evaluation 文件会记录 outcome=parsed；当前评分仍会把它归 unavailable，可能遗漏一个已收到但不合业务 object 合同的首答。

应依据 evaluation outcome/字段存在性区分无结果与“已解析但类型无效”。raw content、本次 evaluate ordinal 和 repair 标志已经保留，可以据此恢复首 content、首个解析值和首个业务 object，不能用修复后答案替换首答。正式探针把此例与 S01 的非 object 控制合并即可。

## 已有修正与剩余说明

- 最新读到的 `usage_info` 已把“所有提供字段均非法”记为 unknown；缺失/None/空 usage 为 missing，部分有效为 partial，完整且总数一致才 complete。尚未执行参数化验证。
- 首次读取时 ledger 用 starts 数称 actual_post_dispatches；后续直接读取已改成 post_attempt_start_records、http_responses_received 及 unfinished server receipt unknown。这个修正方向符合前置判据。`models_get_dispatches` 仍仅凭 models-start 存在计数，GET 应同样区分 start 与收到响应；不能用孤立 start 声称服务已收到。
- `run.py:_service_failure` 相比旧 V2 忽略“timeout 后重试成功”中的错误 attempt；旧协议把任一 transport error 计入该例 service failure。主控在收口前已明确本轮保持旧规则：恢复的超时仍计本例服务失败，并已转达实施者；最终 freeze 审查时验证，不在移动草稿上继续探测。
- 比较路径复用 `fixture_runtime_at`，进而调用无显式 settings 的 `create_app`，会读取宿主 Stage13Settings.from_env；PUBLIC_APP_MODE=0 使 mailer 为 UnavailableMailer，因此没有看到 SMTP 派发路径，但预算/配额等仍可能承接宿主环境。G02 已显式 for_test。比较路径可在 V5 侧控制 settings 避免宿主差异，不改旧 loader。

## 目前结构上成立的部分

1. `reserve` 对非法/重复结果或 workspace 身份先拒绝，位于 freeze、case 正文、凭据读取和 DB 创建前。模块导入阶段只枚举 corpus 路径，尚未读取正文；默认 app 已禁用。正式探针仍需验证哨兵与首失败保留。
2. 业务 snapshot 写入 request 文件并 fsync，随后 input-audit 写盘，再进入 Provider。每次 HTTP 的 start 文件也在底层 post 前 create-only+fsync；finish 只提取可见 message.content、安全元数据和 usage，没有保存 Authorization、响应其他字段或 hidden reasoning。
3. 比较请求与历史 V2 capture 是深比较，只去除 repair 附加字段并归一化瞬时 claim.id；不是只比正文摘要。每个 request 断言单 claim，正文等于完整 target，来源 body/chapter/prompt excerpt 对 corpus 核验。需用最终离线材料确认同次运行实际满足。
4. 108 POST 总上限与 comparison 4/G02 2 每例上限存在，Provider 原有 max_retries=1、Continuity 最多一次 repair 和 G02 一次 evaluate 保留。不能把每例 cap 当默许外层多次重跑；正式检查需断言最多两个/一个 evaluate 及 repair 阶段关系。
5. 每例保存 final-product 后评分；已解析业务 JSON 与原始 content 在不同文件保留。质量机器 fail 不直接触发重跑；两次服务失败或 auth/model rejection 有停止记录。S01 仍须隔离评分异常。
6. `build_cases` 固定 V3 24+V4 G02 6、ID 唯一，并验证前四个 G02 正文与 V2 相同，属于已见开发集。case 内容的全面语义/去重结论由材料审阅另作确认。

## 冻结后定向验证

等待实施正式交付 tests/freeze 后，按 criteria.md 执行少量无网络探针：重复身份提前拒绝；post 入口读回 snapshot；持久化失败禁止发送；timeout→success/repair 分层及用量；孤立 start；S01/S04 畸形首答；同次 source/Memory 篡改拒绝；服务停止；关键传递依赖完整性。不重复旧 45 项评分控制或整套产品/UI 验收。

当前 freeze 未完成，不审定依赖闭包、参数锁定或历史保护最终 hash，也不允许据此启动真实调用。本文件的发现已交主控，不直接向实施聊天发送消息。
