# V8 独立工程预检结论

2026-09-27：**通过，可冻结。无剩余真实派发的实质工程阻断。** 派发前由 root 固定最终 manifest SHA-256，原 direct-file live_guard 以该 pin 完成 verify-only，再使用同一清单启动新身份。本文不代表已完成真实运行、语义、用户或 release 验收。

## 审查发现已关闭

- 评分异常已由 safe_score 隔离，保存 score_error，不会因非法可解析 shape 中断矩阵或把当前 trial 错列 not-run。
- parsed / unparsed 的非 stop 响应及终态都有 generation 分类。最后的交叉负控（非法 evidence shape 同时 finish_reason=length）亦通过：保留 score_error、scoring TypeError、generation:length，complete_answer=false。
- known-usage retry 的 ProviderResult / ProviderInvalidJson 现在累计本 evaluation 的全部已知 attempts；observed_response 字段仍是末次响应，时延累计。HTTP 失败或未知用量导致引擎终止时，以每 attempt 账本为完整会计依据。
- reasoning 分项的非法类型、负数、超过 completion 明确 invalid；总量不会重复相加，缺失分项不会伪造零或破坏已知完整总量。

## 验证依据

独立 `engineering-targeted-probe-03.json` 首次为 4/5：四个 guard 负控全部通过，保留第 5 项分类遗漏的原失败；`engineering-generation-fix-probe-04.json` 仅复核该失败，1/1 通过。两次源 hash 前后稳定，网络/socket/HTTP/SQLite 阻断下实际尝试数均为 0。guard 负控确认已占身份先于读取材料、manifest 漂移、产品源码漂移和缺失闭包均在产品导入/环境访问前拒绝。没有改写历史证据或重复全回放。

实施者及 root 各运行的 14 项离线测试通过，承接其预算恢复、用量、停止、快照、评分和完整 34 条 V7 回放验证。本审查直接读取 `offline-replay-01.json`，确认 34/34 等价、原/适配 final 均 19，通过/失败及读取 hash 稳定；这是适配器验证，不是新的模型成绩。实施者另报交叉路径定向 1/1，通过情况由本次独立 04 再确认。

## 关键接线和边界

- 单进程串行、非重入预算 context，入口要求 8000，execute 内暂设 40000，finally 恢复。原完整请求 estimator 6000、固定 prompt、原 validator、最多一次 repair 均保持。结果明确 experiment-only engine 层，不冒称 API/数据库持久化或原 8000 端到端结果。
- 同一冻结 V7 请求在三条件中保持完整一致；full request/wire/start 均先于 HTTP。unknown/partial/missing 总 usage、已知 token 阈值及每次 retry admission 禁止后续派发。保留 408 POST + 1 GET 硬上限、终止 HTTP 和连续服务失败控制。
- 原始 total_tokens 是累计依据；reasoning 是 completion 子项。1,500,000 是停止阈值，最后一次可能超额，真实结算须记录 overshoot；8000 兼容性单列。120 秒为 HTTPX phase timeout，不是总墙钟保证。
- freeze 闭包覆盖新 harness、产品 Python、package initializers、V7 scorer/build_cases、实际请求、gold/角色依据、prep、原回放证据及运行依赖。guard 在 lazy import 前逐项核固定 manifest、源码、initializer 覆盖和安装运行时，再调用 freeze.verify 作完整清单/配置/输入检查；凭据只在验证后的 launch 读取。
- 评分沿用原 policy；final 删除的仅 API/DB 持久化检查。首答、repair 和实验 final 分离，人工语义仍独立判定；不因修复成功回填首答。匿名 packet 白名单未主动泄露模型条件/用量/评分。
- 部分矩阵须同时给全 34 分母、实际已完成/未运行和三组公共完成子集；技术停止或不可观察不能虚构语义错误。全部 usage 的未知部分不能猜零。

632 冻结与 375 V7 run 的保存基线承接 `baseline-v7-preservation-01.json`。按 root 指示，此次不再次全量扫描，真实运行完成后作最终保全核验。

## 固定证据与所审源码

|文件|SHA-256|
|---|---|
|engineering-targeted-probe-03.json|e16375b38399deebcee516e3d97ceea82bafc27a46cd0cbe0901b027e1ace295|
|engineering-generation-fix-probe-04.json|0b6032960e96b5f05dd04cabba62218271c14ea9d854ba9f351643780aa2243a|
|harness.py|9d9fb2d3641378631e45faddd7bc52f114684dfa6f464c86e02b8f9e990cb658|
|provider.py|0c503fea4249f2a1ec1e9bfc6f7d09f6aa01a5238a00f8b3748773aed286d924|
|score.py|d3308031a9ed850706bbd802058fb6c72e3eb136a3ede5bbaa40b618bc0ad01d|
|journal.py|56ff06a77d60d463abab7702ea076bd420c2b2aacd28018ac82893c68796127e|
|freeze.py|8665a717d4d2fbc508fd1fe51e742bf67e5be31f32a47ad60eda6596346f85b5|
|live_guard.py|336b36408ddc947d402aed3b2b97e89bcda988221be9848267ccfebaae39dfe7|
|test_offline.py|95382c06c1f505b1c61408e432b647c25189d115cd20984ad9ef219685a229d3|
|offline-replay-01.json|0173d36349eac37037fef7f588efa0b461e24bd1e446192d864a8a676a0e5f09|

本审查仅新增专属 engineering 文件；真实 Provider 调用 0，DB 连接 0，未触凭据或改产品/V7/实施文件。
