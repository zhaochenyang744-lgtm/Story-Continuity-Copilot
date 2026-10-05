# V8 接线增量审查 02

2026-09-27。仅静态审查当前草稿，不构成最终 freeze 或 live 放行。未运行 harness、评分器、测试或 Provider；网络与数据库调用均为 0。仅新增本文件。适用祖先及目标目录未发现 AGENTS.md。本次未重复 632/375 历史哈希检查，沿用 baseline-v7-preservation-01.json，最终冻结时再验。

## 待关闭项

1. **P1：评分异常可终止矩阵并错误标记 not-run。** `harness.py:125–130` 的 raw/final 评分在执行器异常保护之外；所调用的 V7 `score_raw` 只捕获产品 validator 错误，随后 `issue_errors` 仍可抛出 shape 异常。例如可解析输出含 `evidence[0].span_id=[]` 时，V7 `score.py:96` 的 `set(cited)` 会抛 TypeError（本轮为静态推导，未执行该负控）。当前 trial 已有 engine-final，却未到 `trial-finish` / `finished.append`；外层 finally 以完成数量切 schedule，将它列入 not-run，stop_reason 还可能为空。应在评分边界输出明确 score_error 并保留其余试次，或明确停止并区分 started/finished/not-run，不能因一个非法模型 shape 吞掉后续矩阵。修正仅需新 harness，不改冻结 V7 scorer。

2. **P2：非 stop 标签未覆盖无法解析的响应及终态。** `harness.py:127` 的非 parsed 分支仅返回 unavailable/解析错误，未附 generation 层；`provider.py:95` 产生 `finish_reason:length` 等 error_code，而 `score.py:9–17` 仅将 `generation:` 前缀归到 generation，当前终态因此被分到 structure。截断、过滤等应在解析成功与失败两条路径都独立标记，避免被统计成合同或事实能力失败。raw 响应及 finish_reason 本身仍完整留存。

3. **P2：重试用量的两个统计口径需要对齐或显式区分。** 新版 provider 对完整 usage 的 429/5xx 允许一次 retry。matrix 按每个 receipt 累加，信息未丢；但 `ProviderResult` / `ProviderInvalidJson` 只使用最后一次 receipt，engine-final 的 input/output 因而不是全部派发用量。例如两次已知各 100 token，matrix 是 200，engine-final 只有末次 100。建议 ProviderResult 累计本 evaluation 的全部已知 attempt，observed_response 字段保留最后响应；若采用另一设计，必须明确 engine-final 的用量范围，报告和预算兼容性统一引用完整账本，不能把末次响应当全部费用。不要为预算通过替换真实 usage。

## 本次静态确认

- `experimental_budget` 使用非阻塞进程内锁，拒绝嵌套/并发，入口要求原值 8000，finally 恢复原值并释放锁。当前 execute 循环串行，实验结果显式标为 experiment_only / engine_not_api_or_database；未修改产品字节。
- `FrozenInputEngine._batches` 返回原请求的深拷贝，原 execute 仍检查完整初始及 repair 输入的 6000 estimator 上限，沿用一次合同修复与 validator。provider 去掉 contract_repair 后严格比较完整业务请求与 base_request，实际消息仍调用原 continuity_prompt。
- 完整 request/wire 在 attempt-start 之前落盘，HTTP 发生在 begin_post 之后；每次实际重试都重新 admission。未知总 usage 立即设置矩阵停止，禁止下一 transport/evaluation；完整用量达到 1,500,000 后不再派发。最后一次越界允许，最终报告应明确实际 overshoot。
- known retry 的 429/5xx receipt 全部保留；未知超时不自动补跑。终止性 HTTP 状态、全局 408 上限、每 trial 4 上限及两次连续服务失败控制均有接线。质量失败自身不触发 service stop。
- `journal.py` 已修复前次 reasoning 分项问题：非法类型/负数/超 completion 标 invalid，缺失为 not_reported；completion/total 不再重复加 reasoning。只有总 usage 完整时计算 8000/40000 兼容性；分项缺失不伪造总量未知。
- raw 评分沿用冻结 V7 policy 和产品 validator。final 评分针对 engine 输出使用原证据/决策/类别/链/时间策略，并从实际 accepted 响应补读 engine 丢弃的 temporal_basis；API 持久化、数据库映射/修订等排除项显式列出。产品 execute 已承担 ledger 与结构合同校验，不能将此结果冒称 API/DB 端到端验收。人工语义判断仍 pending。
- 正常控制停止路径记录 not-run、每条件 coverage 及 common_finished_cases，可支持部分矩阵分母；第 1 项异常路径须修复后才能依赖这些数值。

## 匿名 packet 快速核查

`docs/model-compare-v8-independent-acceptance/build_blind_packets.py` 的 first 白名单不包含 model/condition/thinking、usage、评分或 arm 路径；随机条件映射单独保留于 root-only-mapping。followup 的 final 白名单也未包含模型或用量。首轮锁分后才生成 followup 是 root 的操作边界，当前代码只要求 first mapping 已存在。若输出正文主动透露模型身份，应保留原文并标记泄露，不能声称绝对双盲。

## 所读草稿版本

本轮读取期间 provider/journal 正在接受定向修正；下列为本报告完成读取所对应的 SHA-256，非冻结清单：

|文件|SHA-256|
|---|---|
|harness.py|e597d5d8262edd5d3119162fa870d4ce7259c4fe056edc56e65ee5644ad8792e|
|provider.py|d60071142fd3d7761e7c4a0546857933c57fa473133f92195881ccc8357d0196|
|score.py|8f81fa7a2cdb993430a4aab185da980ef92a7aeb1eea6cb81a079954a9b3ac3e|
|journal.py|56ff06a77d60d463abab7702ea076bd420c2b2aacd28018ac82893c68796127e|
|config.py|7b70b2cf1072a6dc57f540189ffdbef2a731d94488b9b68953b1112837f166a4|

静态结论：第 1 项为真实执行前阻断，第 2–3 项需在冻结前关闭或准确限定指标范围。freeze/guard/tests 尚未完整交接，本轮不扩大到旧控制重测；待稳定包一次完成定向离线验证和总门槛。
