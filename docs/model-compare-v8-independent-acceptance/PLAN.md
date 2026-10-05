# V8 模型与思考模式对照计划

用户已授权执行三组Provider测试，主控负责冻结与独立验收。测试在新evaluation/model_compare_v8目录实施，不修改产品或V5/V6/V7历史证据，不提交、推送、发布或切换生产模型。

## 比较对象和固定项

| 条件 | 模型 | 思考 | effort | temperature |
|---|---|---|---|---|
| Flash off | deepseek-flash | disabled | 不传 | 0 |
| Flash high | deepseek-flash | enabled | high | 不传，API在思考模式忽略此参数 |
| Pro high | deepseek-v4-pro | enabled | high | 不传 |

每组使用V7相同34个已经验收的prepared business request，包括相同claim ID、正文、selected证据、Memory、schema和prompt；不加gold、模型提示或候选答案。业务样本是24旧例+10已见开发控制，当前只做诊断，不代表盲测泛化。V7原2000-token Flash结果作为历史参考；本轮Flash off采用与另两组相同的新预算，是正式同期基线。

按case-major运行，每例三条件的先后顺序轮转，减少时间和缓存顺序偏差；相同输入每条件只运行一次，不因质量失败重抽答案。102个条件案例，每例最多两次合同evaluate、每evaluate最多一次transport重试，总生成POST硬上限408，models GET最多1次。HTTP400/401/402/403/404/422立即停止；transport未知usage优先停止后续派发，因此未确认用量的超时不会为了凑齐矩阵继续重试。原始失败与not-run都保留。

## 思考和实际用量

三组max_tokens统一32768，HTTPX timeout配置120秒。这是网络阶段/读取等待上限，不是整请求wall-clock截止；记录实际耗时。该输出额度由思考和可见输出共同使用，reasoning_tokens是completion_tokens的子项，不重复累加；未提供拆分时记unknown，不推算成0。

产品原每次返回预算为8000。为观察模型表现，测试包装仅在单进程串行execute的context内临时将内存MAX_RUN_TOKENS设置40000，入口检查原值、finally恢复8000；产品文件不变，输入估算6000的限制保留。ProviderResult和原始usage保持真实值，绝不填0绕过预算。最终结果标为“实验引擎交付”，另逐条报告是否超过产品原8000预算，不能视为生产端到端验收。

整矩阵已知实际token达到1,500,000后不再发起下一请求；出现无法确认总usage的派发后也停止。最后一请求可能使总量超过阈值，按实记账，6000输入估值不当作actual token硬界。若中止，列清每组实际覆盖、未跑及共同完成样本，不把未跑当模型答错。

仅保存可见content、实际请求参数/摘要、模型标识和安全usage metadata；reasoning正文不落盘，只记录返回有无、长度/hash及API提供的token计数。费用不可得时记unknown。finish_reason=length等截断/未完整返回单列，不混入语义错误，也不记完整通过。

## 验收方法

首答为主要比较，repair和实验最终输出为次级比较。固定gold和严格完整评分，同时分别报告事实/未知判断与联合推理、类别、引用角色/集合/绑定、schema与实际Issue交付。类别错不自动等于事实理解错；正确basis也不替代作者实际收到Issue。具体口径见SEMANTIC-CRITERIA.md/json，并在真实请求前冻结。

实验final scorer如适配非数据库Issue形状，只能去除持久化特有字段检查，不能放宽gold；先离线回放V7完整34原始响应链，对照原19个最终完整通过及失败原因。API持久化路径不在本实验新增验收范围。

语义验收尽可能使用隐藏模型名称、用量及耗时的匿名答案包，先锁首答结论，再审repair/final，最后揭示条件。保留首答和最终的分母，不将同模型单次运行的改善称为稳定能力上限。若有明确改善，再提出部署前独立新样本验证；本轮不自动更换生产模型。

## 官方参数依据

- [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)：模型ID、思考参数、输出上限、finish_reason和usage拆分。
- [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)：high档位及temperature在思考模式无效。
- [Error Codes](https://api-docs.deepseek.com/quick_start/error_codes/)：402余额不足与422参数错误。
- [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/)：阶段超时含义。
