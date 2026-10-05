# G02 后 V4 第二轮主控独立验收

2026-09-26。**G02 上轮四项产品修复在限定离线范围通过；新比较集 V1 的金标准和语义评分未通过。本轮整体任务尚未交付。**

本结论由主控结合实际代码、原反例及正控制、保存结果、正式前端与新隔离后端的浏览器交互作出。没有增加真实 Provider 调用，没有 commit/push/merge/deploy。用户最终接受另一步。

## G02 通过范围

1. time-bound 原 V4 请求及真实首答直接过当前 validator：昨日未知和今日读信后获知两句都保留在 items、summary 及各自引用中。超过 12 项的背景省略有 overflow 记录。
2. 连续中文引语：新合成 API 实际生成两条完整带说话人和闭引号的 claims，没有孤立标点，也不再假 partial；持久化两次读取一致。
3. 容量反例：原 12 条不同模型分项经多来源展开后，三条正常草稿事实全部保留，3 条背景省略明确记录。
4. omitted 计数：一个、两个、已匹配分句分别为 1、2、0，不再循环与 fallback 双计。

代码、语义独立报告分别在 ../independent-round2-code/review.md 和 ../independent-round2-semantics/review.md。已人工核查知识否定及计划来源层级；这是产品受控重建行为，不是任意改写语义判定器。旧 V4 六个原始首摘要的自身引用缺口结论不变。

主控重新执行受影响产品回归及比较集离线测试：**46 tests + 12 subtests 通过**。新比较集冻结校验通过。134 份旧 Flash 材料和 10 份 V4 原始结果 hash 不变，44 份本轮快照未漂移（root-verification.json）。

## 主控浏览器

正式前端 build W52CgAUpNgqPizlf_vc_k，fresh 合成后端与 DB，端口 3238/8238，6 条 Playwright 交互通过：normal、cycle、dialogue、post-time、post-quotes、long-tail。来源展开、保存后刷新与内容保留均核查；主控目检 post-quotes-expanded、post-time-refreshed 图像，确认完整说话人引语、时间事实及引用展示。详见 ../independent-round2-browser/review.md。

测试使用注入固定响应，外部 HTTP Provider 为 0；不能作为新实模型成绩。主控 runner 已结束，只关闭自己的服务；端口再查无监听。

## 比较集 V1 仍须修正

已独立读取正式冻结材料、24 例 gold、完整 corpus、实际选中输入、scorer 和当前 Provider 契约。24/24 最小响应可通过产品契约，只证明形状可表达；不能证明 gold 与语义评分正确。

- 三个强冲突（world_rule、object_state、event_status）缺动态前提和草稿之间的共同时间/作用范围。固定规则不能证明帽一直松、船一直未签未离港，或不同日的 10 点相同。
- 后知、移动两条兼容控制允许有证据的 state_change，当前 scorer 却一律把非空 issues 当误报。
- 正确引用以外加入无关 contradicts/sufficient，或不足案例错误写成 contradicts，仍可经 validator 且 score pass。必需 ID 齐全不能替代逐条引用关系检查。
- 五个不足案例的第二来源只是背景，应区分最小充分证据集合和推荐背景。8/8 不足独有 establish 用语构成标签捷径，须在现有集合内改进近控与表述。

详见 ../independent-round2-comparison/review.md 和 results.json。正文/章节绑定、UTF-8、冻结 hash、当前最终 API classification 投影修复已通过。tampered chapter/excerpt 负控只说明 score 输入绑定不足，未证明当前 API 可返回伪造引文，不把它冒称产品漏洞。

返修限定为另起比较集修订版本、修材料和评分/人工复核门槛、离线预检。保留 current_contract_compare_v1 全部冻结文件及首失败结果；不改已通过的 G02 或 continuity 产品来迎合 gold；不跑整套 Provider。新版本再次交主控审阅。

## 保留限制与总账

- 同文倒序重复、长句摘要冗长、对象归到 character_state 三个 P3 保留。
- 引语处理覆盖本轮前置说话人中文弯/角引号及嵌套控制，不保证任意 ASCII 引号、后置说话者或完整小说句法。
- 当前 normal mapper 不产生的 Author Context 双正文观察保留为条件限制，不新增当前业务阻断。
- 真实模型后 V4 复测未做。没有把离线复放或 fixed response 当作新版模型分数。
- 累计仍为 **63 generation POST + 3 models 请求；185382 输入、20686 输出 tokens（共 206068）**。本次增量 0。旧 57 POST 与 V4 新增 6 POST 分账保留，complete usage，实际费用不可得。
- Agent、真实作者研究、整套比较集实模型运行、生产成功链路及应用完整恢复不在本次通过范围。

