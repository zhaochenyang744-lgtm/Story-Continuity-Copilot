# V5 真实运行准备：主控限定独立验收

2026-09-27。结论：**准备工作限定通过，可以按已授权固定矩阵执行真实测试。** 这不是模型质量、用户接受或发布结论。用户本轮已经授权 Provider 测试自主调用，不需要再次确认。

基线 `7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2`，分支 `codex/legacy-gap-repair`。V5 manifest SHA-256 `aabea4b8f99d2d4282ed627e98da98a57e46a1c526a7a45064af22acfd87682b`。实际执行必须同时使用本目录 `live_guard.py` 和补充冻结 `controller-dependency-freeze.json`，补充 SHA-256 `bcc424e1a372b1e98b1d81d00f368e94075613ab559b1fceb68c7681c371747b`。

## 验收依据

- 主控复跑冻结离线套件：7 tests，0 failures/errors；真实网络在测试进程中阻断。见 `controller-offline-tests.json`。
- 独立工程探针：12 个不同控制组均已有通过证据。formal-01 为 9/11，两个控制未进入目标逻辑即遇到审计目录 Windows 长路径失败；保留首版脚本和失败记录，formal-02 仅补这两组及新增 guard 组，3/3。不能把正式首轮写成 11/11。见 `engineering-preflight/probe-runs/formal-01/results.json` 和 `formal-02/results.json`。
- 已核对重复身份先拒绝、快照与attempt-start落盘后才进入mock transport、写盘失败零派发、超时重试与未知用量、四种usage、坏JSON与可解析非object/坏shape保留、评分异常不中断下一例、G02同次数据库快照错章/错Memory拒绝、108请求边界、连续服务失败停止及鉴权拒绝。
- 24 比较例和 6 G02 的独立输入审阅无阻断。主控另对最终 `prep-v5-03` 全部30例重算请求hash、与历史comparison capture完整比较（仅归一化claim ID）、核对SourceSpan/Memory与同次数据库快照，0失败。见 `controller-final-prep-audit.json`。这些是准备stub输入，不能算实模型成绩。
- 原V5 `freeze verify` 和主控 guard `--verify-only` 均通过；原清单加补充检查共280文件。240份历史/产品保护文件在派发前仍无漂移，见 `pre-dispatch-protected.json`。

## 本轮关闭与保留

静态初审发现的评分异常终止矩阵、G02只验请求内自洽、非法usage归错类、null解析混淆、孤立start计数、宿主settings干扰和停止规则差异，已在冻结版本及独立控制中核查。G02自动分数明确仅为citation-binding部分检查，引用语义继续逐答人工审阅。

原V5 freeze遗漏Memory词表、文本转换、workflow和export模块及包入口。未修改原freeze或任何产品文件；追加独立补充清单，5份产品依赖字节与基线commit blob一致，连同guard自身冻结。实际指令通过guard，先拒绝占用身份、验证原清单/补充清单/HEAD和依赖，再进入原runner。独立控制确认补充SHA错误、模拟依赖漂移及占用身份均被拒绝。

G02教学seed的父章节正文为空；本次仅核对合成SourceSpan、受控Memory与saved draft，父chapter身份/版本可核，不宣称完整章节或长篇稿件来源链。比较集及G02都是已见材料，历史缺失失败链、三个G02 P3、有限引语语法范围仍保留。

## 放行的具体执行

唯一新身份：`flash-v5-20260927-01`。24比较例加6 G02，每例一次；仅原有有界重试，最多108 generation POST与1 models GET。质量失败不补跑；鉴权/模型拒绝立即停，连续两个含服务错误的逻辑案例停止，未运行项明确留下。

执行后由主控独立核对全部首响应、首个可解析JSON、修复答、最终产品、实际输入、HTTP账和usage，并逐答人工判断语义/引用/最小充分证据。实施自测与本准备通过不能提前充当真实结果验收。
