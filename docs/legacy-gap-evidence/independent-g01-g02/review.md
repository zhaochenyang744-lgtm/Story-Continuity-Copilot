# G01/G02 独立验收

日期：2026-09-26。工作树：`story-continuity-legacy-gap-repair`；交接基线：`39de855c005d77f7f02a132f5e807a0c1c476b7b`。

结论：**本次 G01/G02 尚不能验收通过。** 对应既有测试独立复跑 29 passed，但新离线反例复现两类 G01 确定冲突误判及一项 G02 截断未标记问题。这是产品校验与覆盖契约的未关闭缺口，不是对真实模型错误频率的判断。

## 发现

### R1 / P1：时间守卫只检查模型截取的锚，完整正文的跨天限制可被省略

位置：`backend/app/engine.py:93–98`、`:116–120`、`:336`；诊断入口 `:236` 同样只传入模型所选锚。

最小复现：当前主张“今日十八点，秦渡已经知道信使身份。”，引用“昨日十八点，秦渡还不知道信使身份。”；模型提供双方确实存在的子串“十八点”，并误报 `confirmed_conflict / explicit_overlap`。

预期：同钟点不能证明同一天；应拒绝确定冲突，修复后仍不明确则降为证据不足。

实际：`validate` 接受；`execute` 仅一次 fake Provider 调用就返回 `completed`，问题保持 `confirmed_conflict`、证据 `sufficient`，没有进入修复或保守降级。将正文换成“第二天十八点已知”与“第一天十八点未知”，即使给完整句子作为锚也同样通过，因为日序没有进入解析。

证据：`probe-results.json` → `g01.relative_day_short_anchors`、`g01.ordinal_day_full_anchors`。同一材料使用完整“今日/昨日”锚的控制组正确降级，说明新增守卫只处理了最窄的输入形式。应对完整主张及实际引用的时间限定作约束；无法证明同一故事时间时保守处理，不能只信任模型所选子串。

### R2 / P1：明确谎言及回忆的叙述范围仍能被提交为确定冲突

位置：`backend/app/provider.py:93`；`backend/app/engine.py:333–365`；新增测试 `backend/tests/test_v140_real_ai_contract_repairs.py:69–81`。

最小复现：当前主张“今日十八点，黎青故意撒谎说自己不知道信使身份。”，引用“今日十八点，黎青已经知道信使身份。”；fake Provider 把两处解释成确定的知情冲突，双方锚使用完整句子。

预期：原文明确是故意撒谎，台词不构成叙述者确认的“不知道”；应省略该假冲突或降为证据不足，不能保留确定冲突。

实际：`validate` 接受，`execute` 首轮直接返回 `confirmed_conflict`。另一个“今日十八点回忆昨日十八点尚不知道”对“今日十八点已知”的反例在双方锚取“今日十八点”时也被接受。新增测试对谎言仅检查提示词是否出现 `lie`，没有把谎言材料送入产品校验，因此测试通过不能证明此项修补成立。

证据：`probe-results.json` → `g01.explicit_lie_same_time`、`g01.explicit_recollection_short_anchors`。需要对已有明确叙述限定进行产品层核对或保守降级，并补上述反例的执行结果断言；不要求新增完整故事时间轴或 Agent。

### R3 / P2：单句 240 字截断未进入 partial，简报遗漏句尾仍标 covered

位置：`backend/app/v2_database.py:2971`、`:2981`；`backend/app/engine.py:462–472`、`:490`。

最小复现：保存一个 299 字单句：`“林默沿着长廊向前走，” * 28 + “最后把银钥匙交给陈澈并得知弟弟还活着。”`；fake Provider 的简报只引用历史来源，遗漏当前草稿。

预期：产品补草稿内容时须覆盖可定位的真实内容；若只使用被裁为 240 字的主张，截断和未覆盖句尾必须标记 `partial`，不能把“已经有一条引用”视为覆盖成立。

实际：数据库将唯一主张截为 240 字；`draft_body=false`（正文不足 1200 字）、`draft_claim=false`（主张数量没有减少）。校验器只补该主张前 240 字，末尾交钥匙和获知弟弟存活完全未进入分项或摘要；API 仍返回 `evidence_status=supported`、`draft_coverage.status=covered`、`reasons=[]`。

证据：`probe-results.json` → `g02.single_claim_truncated_below_body_limit`。较短三句材料遗漏模型草稿分项时，也只补第一句“林默走进北门。”而其余事实未呈现；这条作为覆盖边界观察，不单独增加问题编号。建议使主张内容截断可追踪，并区分“有引用”与“覆盖/部分覆盖”，保持现有长度预算。

## 已跑检查与正向结果

- 阅读交接、修补计划及 G01/G02 相关实现和测试 diff。
- 独立复跑 `test_v140_real_ai_contract_repairs.py` 与 `test_v130_writing_analysis.py`：**29 passed，1 条既有 Starlette/AnyIO 弃用警告**，详见 `targeted-tests.txt`。
- 独立 6 个 G01 执行探针：较早/较晚不同小时、完整今日/昨日锚两组错误输入均被拒绝并在第二次 fake 输出后降为 `insufficient_evidence`；其余四组错误输入仍成为确定冲突。
- 独立 3 个 G02 API 流程：正常短草稿、299 字长单句、1980 字超过正文上限。超过正文上限控制组正确返回 `partial / draft_truncated`。
- 三个 G02 流程均确认：外来/旧式不在绑定集合的草稿主张 ID 被拒绝；再次保存草稿后旧简报返回 `is_stale=true`。没有发现此次改动绕过项目来源集合或当前草稿版本绑定的证据。

## 运行边界与证据保全

探针只使用进程内 fake Provider、TestClient 和新建的临时应用数据库。独立探针显式阻止真实 HTTP transport、SMTP 和外部 socket；Windows asyncio 创建内部 socketpair 所需的本机回环连接获准。未读取 `.env`、原运行数据库或历史私有评估资料；未修改业务代码、原有测试或实施者证据；未提交、推送、部署或开展 Agent。

初次独立探针错误地阻止了 Windows asyncio 的内部 socketpair，未完成 API 探针。这是验收脚本防网络措施过严，不是产品故障；原始堆栈保存在 `probe-console.txt`。调整为允许内部回环且禁用真实 HTTP/SMTP 后，最终记录保存在 `probe-console-final.txt` 与 `probe-results.json`，没有覆盖首次失败。

本审查没有调用真实模型，不能评价提示词修改后的首答准确率，也没有重新做浏览器验收。结果仅覆盖 G01/G02 的离线产品行为、引用集合和版本失效控制；其他缺口由相应独立审查处理。
