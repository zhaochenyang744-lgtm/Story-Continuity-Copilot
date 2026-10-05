# Flash V5 实跑工程独立验收

2026-09-27。**实际工程账本、前置保护和所保留证据链独立通过。** 审查对象为 `evaluation/current_flash_v5/runs/flash-v5-20260927-01`，不是模型语义质量或发布验收。完整逐例检查与文件 hash 见同名 JSON；没有发现校验差异。

本次仅只读 JSON/源码和计算摘要。为复算实际 HTTP body 摘要，只从冻结 `provider.py` 提取两个纯提示词格式化函数及其字面常量，在隔离命名空间离线运行；没有导入 app、实例化 Provider、连接数据库、调用网络或重跑评分/测试。

## 调用与用量

| 项目 | 独立计数 |
|---|---:|
| 逻辑输入 | 30（比较集 24，G02 6） |
| 生成 POST start / finish / HTTP 200 | 33 / 33 / 33 |
| models GET start / finish / HTTP 200 | 1 / 1 / 1 |
| 首次业务请求 / 合同修复 | 30 / 3 |
| transport retry / 孤立 start / 未运行案例 | 0 / 0 / 0 |
| usage complete / missing / partial / unknown | 33 / 0 / 0 / 0 |
| 输入 / 输出 / 合计 tokens | 105167 / 13459 / 118626 |

每个 complete usage 都是非负整数，输入+输出=total；逐 attempt、evaluate reported/observed usage 与全局 summary 一致。费用在所保留 usage 中不可得。返回模型元数据均为 `deepseek-flash`，本审计不虚构其不可得固定后端版本。

三条合同修复分别为：徽章 11 点持有人不足、Nera/Oren 出生先后不足、Sora 同行者不足；均为原产品允许的第二次 evaluate，reason_code 为 `temporal_overlap_unproven`。修复 request 仅追加 contract_repair，原业务输入相同，rejected_issues 与前答逐字 JSON 一致。未发现追加逻辑补跑；各例 cap 与 108 POST 全局 cap 均满足。

## 证据链

- 30 个稳定案例身份、独立产品 run_id 各自唯一。请求先于 HTTP start 留档，response finish 先于 evaluate/case 完成；比较时按时区感知时间解析，未把不同 UTC offset 当时间倒置。
- 33 个业务快照 canonical SHA256 与 request、input-audit、attempt、evaluation 的引用相同；选中正文摘要可复算。当前请求与同次 runtime-binding 的草稿、章节/span、Memory 值和父来源一致。
- 33 个原始可见 message.content 的 SHA256 均正确，其可解析 JSON 与 evaluation payload 一致；33 个 HTTP body SHA256 均能由冻结纯 formatter、同次完整业务请求和固定参数重建。
- 首答、三次修复、最终产品分别保留，未用最终产品替代首答。修复阶段数量、parsed output 数量与分层评分记录一致。
- 最终产品状态为比较集 16 completed / 8 failed，G02 6 completed。八条失败为 `conflict_evidence_not_direct` 7 条、`evidence_unresolvable` 1 条；原答和失败 final 均存在，final score 都为 terminal_failure，未凭空 issues 当成 no_conflict。
- 本轮没有未处理 runner exception，因此没有 first-failure 文件；这不表示没有质量失败。八条产品质量失败已在各自 final-product/scores 中保存，后续矩阵继续。无 service-stop、not-run 或不完整派发记录，符合本轮全为 HTTP 200 且无 transport error 的实情。

## 冻结、保护与敏感信息检查

当前 HEAD 仍为 `7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2`。

- 原 V5 freeze SHA256 保持 `aabea4b8f99d2d4282ed627e98da98a57e46a1c526a7a45064af22acfd87682b`。
- controller 补充 freeze SHA256 保持 `bcc424e1a372b1e98b1d81d00f368e94075613ab559b1fceb68c7681c371747b`。
- 两者绑定的 280 文件，派发前 receipt 保护的 240 旧文件，以及本次 320 个实跑文件，独立检查前后 hash 均一致。
- 扫描实跑数据和已出现的 LIVE-HANDOFF/LIVE-INVENTORY，共 322 份保留文本：未发现 Authorization/API key/password/hidden reasoning 等禁止字段或高置信 bearer/key 模式。没有读取凭据以作逐值比对；这是限定字段/模式检查，不覆盖未提供的终端日志、外部日志或凭据存储。业务 JSON 的 `reasoning` 是用户可见任务输出，与 provider hidden reasoning 字段区分。

所保存 workspace-manifest 声明 30 个隔离 DB。本次没有打开 DB 或重新查询持久业务状态，数据库全量一致性不在本次独立检查范围；请求/来源绑定通过保留的同次 JSON 快照复核。

## 验收边界

沿用已通过的 preflight durability、guard、usage 和异常控制，不重复测试。实跑工程验收通过只表明这次 30 输入及 33 生成响应可追溯、账目完整、失败诚实保留。completed、HTTP 200、机器结构或 G02 citation-binding 通过均不等于语义正确。逐答结论、最小充分证据、每项自身引用、同伴类别、首答与修复/最终产品差异仍由语义分工和主控另行裁定；用户接受与发布 Gate 未评估。
