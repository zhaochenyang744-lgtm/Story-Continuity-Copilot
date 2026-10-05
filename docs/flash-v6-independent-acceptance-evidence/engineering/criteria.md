# V6 独立工程验收判据

2026-09-27。当前仅完成旧 V5 runner/guard 与产品合同的只读风险核查；**不是 V6 实装通过或真实运行许可**。本分工不改产品、V5 冻结/实跑文件，不调用 Provider 或连接 DB；新审计证据仅写入本目录。

## 版本和历史保护

本轮允许修改产品源码。主控须先保存 V5 所绑定产品及关键传递依赖的逐字节快照，快照 hash 对齐原 V5 manifest 与 controller supplement；保存可恢复内容，不能只保留摘要。V5 runner、案例、清单、33 个真实响应及既有结论继续原样保留。

产品修复后，旧 guard 对工作区产品 hash 的拒绝是预期行为，不能改旧常量绕过，亦不直接运行旧 guard。V6 需独立身份、输出根、当前代码/未提交修改标识、完整依赖冻结及自己的派发入口。保护检查分为“旧资产自身不变”和“旧产品字节在快照中完整保留”。旧 V3 scorer 动态调用当前 engine；以新代码重评分必须标成 V6 离线结果，不能改写 V5 历史评分。

## 实装风险与少量正反控制

当前 `engine.validate` 对 confirmed_conflict 要求每条引用均 contradicts/sufficient。放宽联合证据时不能退化为“只要出现一条 contradicts 就整组通过”；修复要说明每条引用的角色、关联和联合充分性。以下使用已保存首失败及其最小变异，逐个消除无关类别/时间错误，避免假负控。

| 控制 | 验收要求 |
|---|---|
| 有关联合证据正控制 | 有直接矛盾来源，加确实支持必要前提的来源；时间、主体、范围一致。按新明确合同可通过，不能再仅因辅助来源不是 contradicts 拒绝 |
| 全 supports、无矛盾 | 不能保留 confirmed_conflict；不得仅凭非空 evidence 或自称 sufficient 通过 |
| 加入无关 context | 可判定无关反例须拒绝或进入有记录的有界修复，不能靠一条正确引用洗白其他来源。任意叙事相关性仍需人工审阅，不宣称通用语义证明 |
| unknown time / 不同时间 | 首答严格检查不能升级 confirmed；已有保守降级仍单列产品行为，不计首答正确 |
| 未选 SourceSpan / 错章或 Memory 绑定 | 即使正文看似合理也拒绝；新联合证据规则不能解除同次选中来源边界 |
| insufficient 与空结果 | 已有未决缺口不能在 repair 中无解释消失为 no_conflict；首答/修复的空数组、失败状态、最终降级分别留档。合理 no_conflict 的空数组正控制仍成立，禁止将 gold/expected_class 注入产品或把所有空结果强制改成不足 |

必要时保留一个合法 state_change 正控制，避免联合证据/时间修补误伤允许的状态变化。只测试实际修改路径；不重跑 V5 全部独立控制、UI 或无关产品测试。

## V6 工程收口标准

1. 核对主控 V5 字节快照及新 V6 manifest 的依赖闭包，包含产品、prompt/schema、scorer、fixture/输入适配、observer、guard 及实际调用的传递模块。已有输入逐字复用时保留 lineage；新 gold/评分解释另版本、事前声明。
2. V6 重复身份必须在材料/凭据/DB访问前拒绝。新合成隔离 DB，当前请求与同次 runtime snapshot 的草稿、source、chapter、Memory/revision 绑定；每次请求与 HTTP start 前持久化完整脱敏 business snapshot/hash。
3. 原始可见 content、首个可解析 JSON、repair、产品最终结果和归一化记录分层。保留首失败，评分异常不吞后续矩阵；failed/timed_out 配空 issues 不算 no_conflict，机器 pass 仍待人工语义复核。
4. 固定逻辑矩阵各例一次，沿用产品原有有界修复/transport retry；按 V6 实际矩阵推导硬上限，不把 V5 的 108 无条件照搬。auth/model rejection 立即停，连续两例任一 transport/service error 停；恢复超时也计本例服务失败。
5. usage complete/missing/partial/unknown、已知部分与完整总量、HTTP start/finish/响应及 models GET 分账；孤立 start 为派发可能发生/usage unknown，禁止自动补跑。隐藏推理、headers、凭据不落盘。

V5 已充分验证且字节未变的 journal/guard/usage 控制以 hash 与静态接线复核继承；只有改动或新接线路径追加小型独立探针。待实施交付稳定版本后，在网络与 SQLite 阻断下执行必要离线控制并保存首失败/后续结果。工程准备、实模型执行、逐答语义、用户接受和发布继续分别裁定。
