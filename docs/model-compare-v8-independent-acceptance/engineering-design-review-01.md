# V8 三条件比较：独立工程设计判据

设计可继续；此记录不是工具实现或真实运行放行。检查时间为2026-09-27，Provider调用0，数据库连接0。V7基线见baseline-v7-preservation-01.json：冻结632项、原run375项均与正式V7验收一致，读取前后稳定；V7产品及旧证据必须保持原字节。

条件与官方API

三条件固定为 deepseek-flash + thinking disabled、deepseek-flash + thinking enabled/high、deepseek-v4-pro + thinking enabled/high。显式配置，不能依赖默认。官方说明temperature在thinking模式不生效；统一传0不等于三条件有相同确定性。无tools时，修复无需回传reasoning_content，修复只继承完整可见issues/claim_verdicts和诊断。[DeepSeek思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)

max_tokens32768是completion生成预算；reasoning_tokens在completion_tokens_details内，属于completion子项，不能再次加到total_tokens。结合该定义，本实验按思考与可见输出共同消耗max_tokens处理；不能把32768宣称为纯最终答案预算。记录prompt/completion/total、reasoning细分及cache hit/miss的原始计数与可用性；字段缺失不填0，明细需非负且reasoning≤completion。finish_reason=length、content_filter、aborted、资源中断、无content分别分类，不伪装语义错误。若推导visible_tokens=completion-reasoning，须明确是派生值且明细齐全。[Chat Completions定义](https://api-docs.deepseek.com/api/create-chat-completion/)

120秒为HTTPX超时参数时，read限制的是等待下一chunk，非整请求wall-clock。DeepSeek非流式响应也可持续空行保活；必须分别记录timeout配置和真实elapsed。若需要120秒硬截止，另需有界取消和unknown usage行为，不得仅靠超时参数宣称已实现。[HTTPX超时](https://www.python-httpx.org/advanced/timeouts/)、[DeepSeek保活](https://api-docs.deepseek.com/quick_start/rate_limit/)

预算与指标隔离

1. 原engine.py:18/377的8000检查针对每次ProviderResult的input+output，发生在校验输出之前；它不是整run累计上限。将thinking真实completion直接送入旧限额会产生budget_paused，不能拿此判模型语义能力差。
2. 接受主控决定：只在实验进程串行engine.execute上下文中临时MAX_RUN_TOKENS从8000变40000，进入断言原值且拒绝嵌套/并发；finally恢复，覆盖成功、校验失败、超时、提前停止与其它异常。不得改backend字节，不得把真实ProviderResult usage写0或伪装missing。每个case结果显式experiment_only及effective_engine_budget。
3. 首答raw内容及其合同/语义评分为主指标；一次repair为次指标；另报原8000每次真实usage的pass/exceeded/unknown兼容性。实验40000交付不能宣传成原生产8000端到端成功。真实usage缺失时兼容性unknown；原引擎or0的实现行为不是可确认的预算兼容。
4. 32768输出加6000输入估值并非严格actual上界，40000也不能保证任意响应必定不触发；若触发仍留raw、真实usage与预算标记。
5. 主控指定102个logical entries（34×3）、case-major三条件轮换、每条件每case一次，首答/repair/evaluate/transport dispatch分别记账。以原prompt和相同业务输入hash约束三条件；V7旧输出不能代替本轮Flash-off。固定34为已见控制，不能称盲测或宣称显著性。
6. 总已知actual_tokens达到1500000即停；任意派发usage未知、部分或缺失后不得再派发（包括隐藏transport retry），保留该attempt与未知状态。最多408POST+1GET；对每次POST发送前持久化并查cap。允许最后一响应超出累计token cap，按actual记录overshoot；38768只能作估算而非严格最大值。提前停止保留所有not-run、条件实际分母与同案可配对集合，不猜剩余结果。

后续工具审查的有界验收

- 复核baseline全部hash、case/condition新identity、请求/配置/输入在发送前留存，以及first content/first parseable/repair/final无串线。
- 离线检查budget context在所有出口恢复8000、无其它条件并发；真实usage未被修改，reasoning计数不重复、不将缺失当0；408+1及1500000/unknown拦截在每次实际transport前生效。
- 完整repair的400字符合同与输入估值6000均保留；不能截断raw或反馈来制造通过。截断或无最终content不能进入正常能力分母后静默消失。
- 仅保存可见content及reasoning的存在/长度或计数/摘要hash等允许元数据，不保存或展示原始reasoning_content、headers或凭据。响应model/fingerprint与耗时保留。
- 一次有限离线正反控制证明上项后才能建议freeze；当前没有调用Provider或启动live。
