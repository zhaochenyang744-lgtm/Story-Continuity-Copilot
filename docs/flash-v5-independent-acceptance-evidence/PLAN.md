# Flash V5 主控独立验收计划

2026-09-27。用户已在主控聊天明确启动下一轮，授权测试所需 Provider 调用自主执行，无须再次询问许可或费用上限。主控向既有「DeepSeek Flash 真实评测与回归」聊天派发实施工作，由本目录记录独立检查。实施聊天 ID：`01a0dd0a-6129-7be0-ac67-ccc349dfdff9`。

## 范围和基线

- 唯一工作树 `story-continuity-legacy-gap-repair`，分支 `codex/legacy-gap-repair`，代码基线 `7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2`。
- 固定 24 例当前契约 V3 比较集和 6 例 G02，共 30 个逻辑输入。全部是已见开发材料；不新增稳定性重复，不把历史 26 个合成记录计入本轮。
- 产品、提示词、旧 gold、旧冻结及结果不改。实施新增文件限定 `evaluation/current_flash_v5/`；合成运行数据库和缓存使用本地忽略路径。独立证据限定本目录。
- 模型 `deepseek-flash`，官方 base URL `https://api.deepseek.com`。沿用产品现有 temperature=0、thinking disabled、max_tokens=2000、timeout=30s、一次超时重试。单 batch 前提下比较例允许最多一次契约修复，G02 没有外层质量重试；总上界 108 generation POST，另 1 models GET。这不是应耗额度。
- 历史真实账保持 63 POST、3 models，185382 输入／20686 输出 tokens，费用不可得。V5 单独记账。

## 工作顺序

1. 实施者新建 runner、固定案例映射、调用前持久化、失败保留、分层记录、独立冻结与离线自测，先交主控技术检查。该停点是技术检查，不是再次征求用户许可。
2. 主控独立检查准备结果和 freeze 闭包。通过后向实施聊天发出固定矩阵执行指令。
3. 执行中保留首响应业务 content、首个可解析 JSON、修复答、最终持久产品；保存每次 attempt 的输入绑定和前置快照。超时或中断的未知派发和用量如实记录；不自动补跑或改写首次失败。
4. 完成后独立审查全部 30 例及原始账。质量失败也是正式交付；发现问题归因检索、模型、产品或评分，不通过修改产品／提示词／gold 干预本轮分数。

## 独立分工和判断标准

- `materials-v3/`：逐 24 例故事语义、类别、来源关系、最小充分证据。两个合理 state_change 和同伴 location_action/relationship 人工裁定独立处理。
- `materials-g02/`：逐 6 例实际输入、每项及摘要自身引用。对话旧三片段与当前两条完整引语的差异必须记录，不能称六例业务请求完全相同。
- `engineering-preflight/`：唯一身份、create-only、调用前落盘、首失败、raw/repair/final 分层、四类 usage、HTTP上限、隔离与依赖冻结。
- 主控：复核独立证据，重算分母和用量，核对受保护文件，形成最终限定结论。机器结构通过仍待人工语义复核；possible 不算 confirmed，产品保守降级不等于首答正确，失败/超时空 issues 不算 no_conflict。

`baseline-before.json` 记录初始 219 份受保护文件；`baseline-snapshot-supplement.json` 加入 V4 运行时 20 份源码和 manifest，共 240 个去重文件，全部匹配。`protect.py` 仅哈希读取与只创建新回执，不执行产品或评测。

当前本文件仅记录验收计划，**尚未放行真实运行、尚未宣布模型或产品质量通过**。用户接受、发布 Gate、commit/push/merge/deploy、Agent 新能力、G07/G08、未见集与真实作者研究不在此次实施范围内。
