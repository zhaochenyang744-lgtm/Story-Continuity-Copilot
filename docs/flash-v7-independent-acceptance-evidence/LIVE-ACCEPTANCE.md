# V7 检查、修复与独立验收

本轮三项trace修复已通过工程验收；整体模型质量仍不通过。主控亲自修改产品代码，由独立审阅分别复核产品差异、输入、调用账本及逐例语义。本轮完成一次固定34例真实回归，未重复运行以改善分数，未提交、推送或发布。

## 修复结果

1. **时间误拦截修复。**支持有效24小时HH:MM，排除非法时钟和伪词法边界；诊断与validate共用直接contradicts证据的时间范围判定。同日同刻正控及不同小时/分钟/日期、无共享日期、引述回忆、只有context带时钟等负控通过。第26例真实首答直接完整通过；第25例也不再发生错误时间repair，但其类别仍有模型错误。
2. **basis合同对齐。**400 Unicode code points上限由同一常量驱动schema、prompt和校验，并给出对应claim、字段、实际长度及上限。原始输出未被截断、上限未放宽。本轮40份真实输出basis最长388，超限0；第17、27例均首答直接通过。
3. **repair反馈补全。**完整原issues和claim_verdicts进入下一次请求，同claim多个错误及逐claim不一致一起反馈。6例首答“不足判断但Issue为空”均经一次repair实际交付Issue；第03例完整通过，其余仍因类别等质量标准失败。完整反馈若超过输入预算，会在再次evaluate前明确失败，保留原输出与已知usage。

## 同一固定矩阵的结果

| 指标 | V6 | V7 |
|---|---:|---:|
| 首答完整通过 | 12/34 | 18/34 |
| 最终交付完整通过 | 14/34 | 19/34 |
| 产品流程completed | 20/34 | 33/34 |
| 终止失败 | 14/34 | 1/34 |
| contract repair次数 | 15 | 6 |

完整通过同时要求语义、类别、证据角色/集合及产品合同满足冻结口径。completed仅表示产品完成流程，不能替代质量通过。输入是24个旧对比案例和10个已见开发控制，未扩写分母、改gold或调整评分口径；这些不是盲测准确率。

| 分组 | V6首答→最终 | V7首答→最终 |
|---|---:|---:|
| 旧24例 | 8→10 | 12→13 |
| 新10开发控制 | 4→4 | 6→6 |
| 预期无冲突（13例） | 9→11 | 13→13 |
| 预期确定冲突（10例） | 3→3 | 5→5 |
| 预期证据不足（11例） | 0→0 | 0→1 |

V7最终完整通过：01、02、03、04、05、07、08、11、14、16、17、20、23、26、27、29、30、33、34。没有通过保守时间normalization增加分数；本轮normalization为0。

## 仍未通过的原因

- 11例类别不符：09/12/15/18/19/21/24/25/28/31/32；其中15同时有多余引用。
- 06仍将来源不能担保断言的缺口当作no_issue。
- 13将一般前提和直接反证的角色倒置；10有冻结口径之外的多余证据。
- 22引用了未selected的span，产品严格拒绝，是本轮唯一终止失败；不能放宽引用绑定让它过关。

后续范围见[NEXT-ROUND-HANDOFF.md](NEXT-ROUND-HANDOFF.md)。类别、证据角色和漏检需要下一版通用合同及新冻结回归；本轮不宣称已消除这些模型错误。

## 调用与保全

正式run：`evaluation/current_flash_v7/runs/flash-v7-20260927-01`，prompt `continuity-review-v17-repair-diagnostics`，schema `continuity-issue-v7-repair-diagnostics`，兼容输出shape仍使用v6 marker。manifest SHA256：`361f4d7d778d6818b258e51caec65a8fd6e4a762b52c78181de35c5f7f8abe47`。

40次生成POST全部HTTP200、finish_reason=stop，另1次models GET成功；无transport重试、unfinished或服务中止。usage全部完整：136159输入token＋11938输出token＝148097；费用不可得。6次repair均因claim_verdicts_issue_mismatch，未再出现V6的basis超长失败或错误HH:MM时间repair。

632冻结文件未漂移，V6 manifest所列文件仅本轮明确修改的engine/provider不同，其余历史文件保持原字节；旧V6真实run420文件保留。G02类、非continuity提示、通用formatter/预算器AST及brief_citations与基线相同，本轮没有新增G02质量主张或追加调用。测试/真实回归使用隔离数据库，不操作业务数据库。

离线75项通过；最后词法增量的59项复测中，1次Windows内部socketpair被测试防护误拦，修正仅该防护后单项通过，原失败与复核日志均保留。见[技术验收](TECHNICAL-ACCEPTANCE.md)、[输入复核](input-review-01.md)、[最终边界复核](prechecks-03.md)。逐例语义和工程明细分别保存在semantics、new-controls及engineering目录；原始机器结果保留在run，不被人工验收覆盖。

最终独立报告：[旧24例语义](semantics/live-01-review.md)、[新10例语义](new-controls/live-01-review.md)、[工程账本](engineering/live-01-review.md)。主控汇总数据与证据摘要见[LIVE-ACCEPTANCE.json](LIVE-ACCEPTANCE.json)，本run375文件在收尾时再次逐项校验，均未改变。
