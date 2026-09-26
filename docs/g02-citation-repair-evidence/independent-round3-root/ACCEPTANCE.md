# 比较集 V2：第三轮主控独立验收

2026-09-26。**G02 产品的第二轮限定通过结论保持；比较集 V2 的24例三分类叙事语义及实际输入链通过审阅，但最小引用和不足类别 gold 尚有两处规则问题，不能作为已全部通过的正式比较基准。**

本次没有新增真实 Provider 调用，没有修改产品、V1/V2 冻结或历史实测。由主控直接阅读材料/源码、执行校验和单来源反例，并结合三个独立审阅分工形成结论。

## 已通过

- 主控重跑 V1 与 V2 freeze verify，均成功；V2 5项离线测试通过。
- 134份旧Flash、10份V4原始结果、21份比较集V1文件保持原hash。本轮34份快照未变；V2全21文件另存保护清单 v2-preservation-final.json。
- V2 manifest：35b8a9559b9d5138f21795cdeb74439d010490dd5a9ee07a37cd48dbd44ca337。
- 24例三分类（8冲突/8兼容/8不足）的叙事语义可接受：三个规则＋动态前提已补同日时间，后两例还限定整分钟；两条真实后续变化允许 no_issue/state_change；五个不足例只把缺失字段来源列为最小，其背景改为可选。单一 establish 完全分隔标签的问题已经打断。
- 26份已保存合成答复的raw/final重评分与交接相符，均机器通过、语义待审，没有被当作真实准确率。现有26份均是单次脚本调用，没有实际发生而未保存的修复答。
- 独立6个新合成API场景（3个时间修订冲突、2个state_change、1个不足）全部completed，原始与最终nature及绑定一致。原24例输入、选中来源、章节正文和Memory已另行核查。
- final scorer的额外无关来源、错误引文/关系、错误Memory绑定、不足chain/动作、非完成空issues等原失效负控已关闭；机器通过后的语义仍明确 pending_manual_review。
- G02产品hash与第二轮相同，本轮没有重复浏览器测试。第二轮6条正式前端＋当时当前后端结果只在源码相同范围沿用。

## 仍须限定修订

### R3-1：徽章规则单条已足够，不能强制名单

V2草稿已明确Mira只戴红徽章开门，badge_rule已明确红徽章打不开。因此 draft + rule 足够，badge_roster是佐证。当前gold仍强制两条，label_reason还说单条不知道Mira徽章，和新草稿不符。

主控亲自在不改case的情况下移除roster、保持合法其余引用链：raw报raw_evidence_policy_mismatch，final报minimum_evidence_missing。见 single-source-control.json。修法限定为rule最小、roster可选并修理由，不需要改故事或重跑模型。

### R3-2：不足类别不能机械沿用三联轴

Provider当前定义按核心决定分类。Sera authorized reopening应按具名授权归relationship，Nera born before Oren应按先后归timeline；当前gold分别强制timeline/relationship，raw/final都会误罚合理回答。courier是谁也不能仅因背景谈知识就自动要求character_knowledge。

修订须逐8个不足问项审类别、依据及允许变体，区分分组轴和评分gold。对于确有语义分歧的类别，应明示需要人工裁定，不能因合法枚举或validator接受就称唯一正确，也不能无说明全部放宽为自动通过。八个冲突核心类别本轮接受。

### R3-3：原始答复结构分数只有部分合同检查

score_raw_one 对不足缺chain、错missing_link、允许edit、提出Memory修改、不存在的Memory关联五类输入仍machine pass，而当前产品validator会拒绝。final层相关控制已通过，未发现本轮对应漏检。

允许限定命名为部分字段检查并另报完整合同判断，或补齐这五项可机器检查条件；不能以后把该raw pass当完整首答合同通过。语义pending不是合同失败的替代。本轮26份有效脚本输出不因此被倒改成模型badcase。

### R3-4：首失败保留与新入口防覆盖

V2 PRECHECK_FAILURES记载最初24次中只有8结构通过，但当前固定输出入口使用open('w')。有限文件检索尚未找到该首失败的24逐例原始结果；现有记录只能确认失败概要，不能宣布完整失败链已保留。

后续新入口应在任何fixture/API执行前拒绝既有输出身份，逐次保留首次失败。不得根据当前输入重建后冒称旧原始结果；若无法找到，应明确记录历史审计缺口。当前26条最终冻结结果的真实性、保护hash及独立再现不因该缺口被抹除。

## 后续范围

另起小范围修订身份（可用只读V2材料＋新版元数据/评分的增量版本），保留V1/V2所有文件。首选不改变已接受的24个业务输入，只改上述最小/可选、类别说明和评分/留存规则；若复用V2真实捕获，明确是相同字节的离线重评分，不冒称新API运行。必要定向合成控制即可，不需要再跑整套26或重复G02/UI。

不改产品/提示词，不真实Provider，不Agent/作者研究/commit/push/merge/deploy。后续交接还须主控限定复验，用户接受另一步。

## 证据与总账

- verification.json、v1-freeze.txt、v2-freeze.txt、v2-offline-tests.txt：主控校验。
- ../independent-round3-gold/review.md：完整24例人工gold及lineage。
- ../independent-round3-score/review.md：46有界控制（35预期符合；6类别误拒与5raw合同遗漏），不作为模型分数。
- ../independent-round3-capture/：保存记录核查和6个新合成API输入/首答/最终结果。

真实总账不变：63 generation POST + 3 models；185382输入 / 20686输出tokens，共206068，complete usage，实际费用不可得。旧57 POST与V4新增6 POST仍分账。本轮真实调用0；上述合成调用不进入模型成绩与真实用量。

G02的重复倒序、摘要冗长、对象分类及引语语言范围限制继续保留。比较集是已暴露开发集，不能宣称盲测或模型泛化质量；未授权执行整套实模型比较，生产/真实作者/Agent不在本次结论内。

