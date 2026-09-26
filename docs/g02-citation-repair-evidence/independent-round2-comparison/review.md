# 冻结比较集 V1：第二轮独立材料与评分验收

2026-09-26。结论：**资产完整性与最小契约可表达性通过；金标准及严格语义评分尚未通过，暂不作为正式质量比较基准。** 本次没有真实模型效果结论，也没有修改冻结集合。以下结论绑定正式交接后的冻结身份，不沿用交接前快照缺陷。

## 身份与执行

工作树：`story-continuity-legacy-gap-repair`，基线 `c3bd54ab019447354e8b1387e16b9aca3258b4c9`。读取 `POST-V4-HANDOFF.md`、完整 build/cases/四个 corpus、capture、评分/探针/冻结源码及 lineage；复核当前 continuity 契约。独立结果时间 `2026-09-26T11:49:22.580057+00:00`。

| 冻结文件 | SHA-256 |
|---|---|
| frozen-inputs.json | `d0da4eb5037c5ce8e724d0263255654d97fb25cc975e5e419786ea5a60c8d29c` |
| cases.json | `a751a2a110e03001a1c213cf2a88e21ca5567e6d0a72b9da87430be90d10ebcd` |
| actual-inputs.json | `beaeb3c3ee5ccf5933c5b48d0bfcc9fa013fcc1f71da4040437cdf340f763d82` |
| score.py | `8966de95c75000d34e228aa76eca3d6b1965b97fcf4ec3b52f8bd1f3d13342eb` |
| engine.py | `4d3a07e955aadfaf1ecd31281ccca0d4fb3f36014756b801d906b193e15984c7` |

独立 `probe.py` 逐项重算 manifest 列出的全部文件，**零 hash mismatch、运行前后零变化，manifest 本身未变**。完整 hashes、24 行契约/输入检查、17 个评分控制在 `results.json`。没有运行原 build/preflight/contract_probe/API 入口；没有创建或读取数据库。仅内存构造响应、调用当前 validator，再按源码中的最终 API 字段投影调用评分。该投影不是新 API capture，实施者的 24 次 fresh API 证据仍属于实施证据。Provider/HTTP/数据库连接均为 **0**。

复跑命令：`.venv/Scripts/python.exe docs/g02-citation-repair-evidence/independent-round2-comparison/probe.py`。输出 create-only；再次验收应复制脚本到新的独立轮次目录，保留现有结果。语义判读是人工阅读，不能由这些脚本计数代替。

## 阻断正式质量评分的发现

### P1-1：静态规则不能替代其动态前提与草稿之间的同刻证明

`build.py:23,25–28,47–50` 的三个 conflict：world_rule、object_state、event_status。确实有真实 `static_canon/rule`，因此最小响应可通过 validator；但矛盾还依赖可变状态：Mira 当时只有红徽章、阀帽当时未锁、船当时未签单/出发。

- world_rule 来源是“10点 on the same day”，草稿只有“10点”。按当前产品要求，两个日子的同钟点不能自动合一；本例仍欠双端明确同日。
- object_state 检查记录帽未锁，草稿称已 ready，两者无同一日期/场景或“帽仍未锁”的绑定。先检查帽松、后来锁好再 ready 完全符合稳定规则。
- event_status 旧日志未签单/未离港，草稿称 launch completed，同样缺少同刻或仍未履约前提。后来签单离港即可同时满足日志与规则。

预期：补明真实共同时间/作用范围或草稿中仍成立的条件后再冻结 gold；否则不能把模型保守不足当作错误。实际：仅有 rule 就让 engine 的 timeless_rule 分支接受，评分也计为 confirmed 命中。这个 probe 结果只证明守卫形式可满足；`provider.py:101–107` 的同主体/范围/时间要求仍未由故事事实补足。不是声称文本必然发生了后续转变，而是存在兼容解释，故当前强制“确定冲突”不充分。

### P1-2：两个合法的 state_change 被严格评分误判为误报

`score.py:22–24` 对所有 no_conflict 只允许空 issues，而 `provider.py:104–107` 明确允许有充分依据的后续转变。对 `harbor_signal-character_knowledge-no_conflict` 和 `basalt_observatory-location_action-no_conflict` 构造解释为兼容后知/移动、充分 supports 证据、nature=state_change 的响应，**两者 engine.validate 均接受，评分均为 false_positive_issue**。

预期：这两个预声明转变控制允许“省略 Issue”或经人工/规则核实的兼容 state_change；二者不能被混为确定冲突。实际：正确遵守另一条产品指令的模型会失分。修评分时不能把所有 state_change 都自动当正确；仍要核对目标、真实转变和证据。

### P1-3：完整引用集合并未防止错误额外证据和错误不足关系得分

`score.py:33–36,46–49` 只核查 sufficiency 和必需 span 子集，未审查所有引用的语义关系。

1. 在 world_rule 正确两条证据之外，加入实际 allowed_evidence 中的 **pneumatic carrier 帽松检查**，将其标为门开矛盾的 contradicts/sufficient。该来源与门/徽章无关。当前 validator 接受，**score 仍 pass**。
2. world_rule 不足例保留正确来源和 insufficient，把 relation 从 context 改成 contradicts；当前 validator 接受，**score 仍 pass**。这与 `provider.py:111,117` 的不足证据契约不符。

预期：严格通过应要求每条引用关系正确；额外无关反证不能因必需 ID 齐而被掩盖。不足还应逐项 context/insufficient、missing_link、无行动/Memory 改写，并准确解释缺口。可以设置机器检查加人工逐项证据裁定，不要求通过任意文本相似度解决语义。

另两个仅离线篡改的负控制：保留 span_id 但改 chapter_id 或 excerpt，score 仍 pass。当前产品持久化路径有来源解析保护，**本次没有证明真实 API 会返回此种伪造正文**；这里只说明独立 score 输入需要绑定 capture/运行身份，不能仅凭 JSON 标签宣称引文真确。

### P2-1：多证据不足被机械加长，且不足类存在明显措辞捷径

5 条不足例宣称需要两条来源，但下列单条已经明确点出唯一缺口：spare_register 的 holder 空白、cap_actor 的实施者未记、later_recipient 的 courier 未记、delay_cause 的原因未记、grinder_blank 的 grinder 未记（该来源已直接写 lens R4）。另一条主要补背景，尚未说明为什么缺少它就不能判“不足”。当前 score 必须包含全部 declared ID，会惩罚合理的单条缺口说明。建议区分“推荐上下文”和“最小充分证据集合”，或重写确实需要联合推理的情景。

同时，8/8 不足草稿含 `establish`，其余 16/16 均无。一个措辞规则即可识别全部不足标签；`lineage-label-audit.json` 保存该计数。这不使每条 gold 自动无效，但弱化三联控制和未来模型比较的解释力。可在现有 24 例内加入同样记录背书措辞但成立的近控，打断提示词捷径，无需扩大案例数。

## 24 例逐组语义裁定

每格对应完整 case_id 的 corpus/axis/后缀，共 8×3=24 例。C=conflict，N=no_conflict，I=insufficient_evidence。表中“可用”只表示本次人工读取范围内语义可解释，不表示真实模型已通过。

| corpus / axis | C | N | I |
|---|---|---|---|
| north_glass / world_rule | 规则与红徽章联合可反驳，但同日绑定待补，见 P1-1 | 只有红徽章所以不能开门，与规则兼容 | 两份记录不能确认11点蓝徽章持有人；作为记录背书不足可用，10点名单是背景 |
| north_glass / object_state | ready 的动态条件无同刻，见 P1-1 | 四 bar 不足以满足锁帽条件，负条件控制兼容 | 帽松事实不能推出 Mira 是操作人；actor 空白一条已说明缺口 |
| harbor_signal / timeline | 同日09点首次开、10点首次关，草稿把首次关闭置于首次打开之前；确定排序矛盾可用 | 首开后首关与明确时间顺序相符 | 11点 reopening/operator 未记，不能由记录推出 Sera 授权；可用，但授权比实际操作更强，解释须明确此缺口 |
| harbor_signal / character_knowledge | 双端11点 same day、不知与知直接冲突，可用 | 13点后来获知与11点不知兼容，允许 state_change；评分待修 | 知情变更不等于 courier 身份；作为记录背书不足可用，11点不知是背景 |
| orchard_restoration / relationship | 明确稳定 kinship rule 加 twins 身份，母女主张矛盾可用；不是把 relationship 谓词冒充 rule | 明确 lied，不能把人物谎话当叙述者事实；可用 | 登记明说出生次序未记；不能由列名顺序推出先后，作为不足可用 |
| orchard_restoration / event_status | 完成与未签未离港无同刻，见 P1-1 | 当前条件未达成所以尚未完成，兼容 | 延误日志原因空白，不能背书 Tala 责任；launch 状态主要为背景 |
| basalt_observatory / attribute | 双端18点 same day，经身份桥接 R4=west lens，clear/amber 材质矛盾可用 | 18点 clear 与回忆 yesterday looked amber 不必相冲；回忆/跨日近控可用 | 维护表直接指R4且 grinder 未记；index 来源对这个缺口不是必需 |
| basalt_observatory / location_action | 双端18点 same day，来源直接 west/not east；east矛盾可用 | 19点明确移动，有真实 later-transition 支持，允许 state_change；评分待修 | 同伴未指名，无法由 watch record 背书 Sora 身份；可用 |

不足例已将旧“普通新情节未曾记载”改为“既有记录建立某事实”，因此前轮 later-event 误标签问题不再按原形存在。这里接受的是**记录不能证明具体身份/原因/次序的保守审阅**：不得把它提升为事件未发生、人物必然未参与，也不能在解释里继续声称记录已经证明了该事实。字面错误归因与真实事件未知应分别说清。

Memory 与时间策略均与完整文本做了核对：规则真实在 SourceSpan 中；动态属性/知情/位置使用真实类型而非 rule；actor/原因缺口未被同作品其他 Memory 偷偷补齐。除 P1-1 中时态范围不足，未发现额外标签与来源事实直接相反的案例。

## 已通过与剩余限制

- 24 例、8/8/8、8 组三联、4 作品。UTF-8 可无损读取。24/24 草稿及首 claim 完整一致；核对**全部选中来源**的章节绑定/body/excerpt，而非仅 declared IDs；必要来源 hash 与完整 corpus 一致；所有请求 Memory 字段和值及来源一致。没有发现本轮检索丢失必要文本。
- 24/24 最小响应通过 validator，24/24 正确最终 API 字段投影通过评分。前轮 status/classification 和 temporal_basis 持久化误读已经修好。raw 首答直接送 final 入口会失败，未冒充最终成绩；未来仍需要保存并独立审阅首答/修复/归一化，当前没有完整 raw 语义评分证据。
- 17 个独立控制中，11 个行为符合预期：wrong nature×3、缺证据、额外 Issue、错误 claim、raw/final 混用、非完成空数组×4 均不通过。其余 6 个问题如上（其中2个是假数据篡改能力边界，4个是当前 validator 可接受输出的评分误差）。
- V8 lineage 已明确承认 pattern adaptation/seen development，全部旧24个ID有排除记录，独立比较新旧 target_draft 没有逐字相同项。pneumatic carrier 仍沿用“两必要条件且一项不满足”的旧挑战形式，但披露后不再称盲测或同输入比较；不是全新独立难度分布的证明。旧 V8 失败不被本集覆盖。
- 未实跑 Provider、未重建 fixture DB、未核对原作者库。静态 fixture loader 的章节/SourceSpan/Memory 写入来自同一 corpus；持久化 API 再现是交接中的实施证据。本次结论不会将 24 脚本通过改写为 24 gold 正确或模型24/24。

建议仅修复/重写上述有界问题后另起候选版本或保留本次冻结并生成明确修订身份，再复核被影响案例与评分控制。无需追加真实模型调用来判断这些材料和评分缺陷。
