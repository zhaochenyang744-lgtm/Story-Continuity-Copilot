# V5 之前的 V3 独立材料验收准备

准备日期：2026-09-27。基线：`7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2`。本记录由主控的材料审阅分工在查看 V5 真实结果前编写，只准备后续逐答验收。24 例材料可用于已见开发回归；这里没有模型答复或模型通过率，也不替代 V5 runner 的独立验收。

## 阅读与核对范围

完整阅读四份 V2 语料的 22 段故事正文及对应 Memory、24 个 V3 草稿和 gold 字段、V2 `actual-inputs.json` 中逐例实际选中来源/原文、V3 RUBRIC/scorer、依赖的 V2 scorer和当前 provider 类别定义。先形成独立逐例说明，再用本目录 `audit-inputs.py` 仅以标准库检查输入身份和绑定；不导入评测/产品代码，不运行 API/Provider，不连接数据库，不读取凭据或环境文件。

- `manual-expectations.json`：24 例手工编写的语义判断、独立列出的类别与最小/可选来源、引用检查和常见误判。
- `case-matrix.json`：将手工说明与冻结 gold、原始草稿、正文、历史 capture 的实际选择和 Memory 绑定组成可审核矩阵；不是重新生成评测案例。
- `inputs-audit.json`：当前输入 hash、24 例逐项核对、核对前后身份和脚本身份。它是只读材料核对结果，不是产品或模型评测结果。
- `audit-inputs.py`：默认只读复核并输出摘要；仅显式 `--write` 时以 create-only 建立本目录两个 JSON。既有输出或保留目录出现时拒绝重写，失败尝试另留首次异常。

核对文件范围包括 V3 27 个 manifest 绑定文件、V3 manifest 本身、四份 V2 corpus 及 V2 manifest、四份产品源码与本目录手工说明；不把旧冻结中的 `git_base=c3bd54a` 或 `gold_independently_accepted=false` 改写成当前状态。它们是历史冻结快照，后续独立接受以独立报告为准。

## 材料与输出判定政策

24 例分为四作品、八组三联；`conflict`、`no_conflict`、`insufficient_evidence` 各 8 例，其中 conflict 的预期 nature 为 `confirmed_conflict`。V3 逐字继承 V2 草稿及语料，只修订 gold/说明/评分；语料注明挑战形态派生自已见 V8。四作品标题虽不同，不能因此当作未见集或盲测集。本次重新阅读也增加了材料接触记录。

逐答必须独立审阅首个可解析业务 JSON、每个修复答、最终产品三个层次。首 HTTP 响应和解析状态仍需运行账本保留。机器结构通过只到 `pending_manual_review`；产品保守降级不能回记为模型首答正确。失败、超时、取消、仍运行不进入无冲突；possible 不算 confirmed。结构与人工语义分开记，发现等价证据争议时保留冻结结构结果并另记人工判断，不改 gold 迎合模型。

冲突项要联合检查目标断言、自身引用中的最小充分来源、同一实体和时间/规则范围。多来源证明可以由规则与事实、身份与属性共同成立，不要求每一条单独都能反驳完整断言。按冻结 V3 的结构字段执行 `contradicts/sufficient`，人工另外核查解释是否真的从这些来源得出结论。Memory 引用必须绑定被引用来源，不能用无关 Memory 填补缺失事实。

不足项要准确指出特定身份、角色、授权、原因或时间先后缺口；`context/insufficient`、每条 chain 的 `missing_link`、无编辑动作/建议/Memory变更仍是合同要求。未记载既不等于发生，也不等于未发生。具名人物责任/角色采用当前项目 `relationship` 定义，不机械继承邻例 category_axis。

无冲突允许 `issues=[]`，无需虚构 issue、类别或引用来满足材料表中的参考来源。材料表的 minimum 对无issue情形是核对输入和语义的依据，不是要求模型为不存在的问题发出 Evidence。类别为空不是无issue的类别错误。

## 需要逐答特别裁定的边界

| 案例 | 后续人工验收要点 |
|---|---|
| north_glass / world_rule / conflict | 草稿已经说仅戴红徽章，`badge_rule` 单条充分；名单可选。`case_time_scope.minimum_source_texts` 仍多列名单是既知展示残留，正式最小集合优先。 |
| harbor_signal / character_knowledge / no_conflict | 11点未知、13点学会是合法转变；允许无issue或充分支持的state_change。若输出变化项，两个时点来源都需覆盖，不能用非空issues判断冲突。 |
| basalt_observatory / location_action / no_conflict | 19点记录自身含起点/终点/移动，`later_watch`单条充分；18点记录可选。允许无issue或充分支持的state_change。 |
| basalt_observatory / location_action / insufficient_evidence | 同伴未命名；location_action和relationship仅为预声明人工候选。每层答复都需看解释能否正确识别身份缺口，裁定前标 `pending_manual_adjudication`。 |
| orchard_restoration / relationship / no_conflict | `lied` 明确人物在撒谎；引语不能冒充叙述者认可的设定。 |
| basalt_observatory / attribute / no_conflict | 昨日“看起来”琥珀的回忆与18点透明玻璃可以并存；不应补造客观材质变化，也不能抹掉时间/说话者范围。 |

冻结历史 V2 早期 24 完成/8结构通过首失败链仍缺失；本目录没有重建或补造。V3 19/26 的既有离线重评分是旧合成记录的新评分，不作为 V5 成绩。V5 将是30逻辑输入的建议矩阵，其中本分工只覆盖24个比较案例；六个G02由另一个分工验收。

## 使用本准备表检查 V5 结果

先核对新 runner 的案例映射和输入哈希，将每例 V5 同次 business snapshot 与本表语义材料对齐；允许瞬时身份变化，但身份必须在同一次请求/答复/产品之间一致。历史 V2 capture 只能用来核对内容，不能代替 V5 的实际派发快照。若实际选中证据不同，先记录检索/输入差异，再评价基于其真实可见材料的模型表现，不假设本表历史选择就是V5选择。

逐答记录 `case_id`、层次、真实结果文件/hash、模型结论、引用来源、最小集合覆盖、实体/时间/关系、类别、是否合理state_change、语义通过/失败/待裁定和一句可复查理由。无issue与终止失败单独记录；未解析首答保留解析失败，不用后续可解析答复覆盖它。完成后由主控合并机器结构、人工语义、HTTP/usage、G02引用和保留限制，再区分独立验收、用户接受、发布状态。

当前状态：材料阅读和验收准备完成；等待 V5 新冻结材料及真实结果，尚未进行任何 V5 模型或产品结果验收。
