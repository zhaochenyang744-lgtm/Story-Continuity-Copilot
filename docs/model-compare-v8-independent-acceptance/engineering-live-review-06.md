# V8 独立工程验收

**Technical pass，0 findings。** 六例负责的匿名语义首答、repair、final 全部锁定后，使用纯标准库完成一次只读审计，4,865 项核对。真实 Provider / DB 调用均为 0，未执行产品、runner 或 scorer，未修改原始证据。

- 102 个逻辑 trial 收尾：**98 completed、4 failed**。质量/合同失败已保留，不能称 102 个产品结果成功。
- **113 POST start = 113 finish，全部 HTTP 200 / finish_reason=stop；models GET 1 次成功。** 未完成派发 0、未运行 0、服务停止无触发，三条件各覆盖完整 34 例。
- 实际 usage 全部 complete：**386,082 input + 175,773 completion = 561,855 total**。未知 0；reasoning 子项 reported 70 / not_reported 43，不重复计入 total。费用仍 unknown。
- 11 次 repair：6 ledger/Issue mismatch、3 direct-evidence contract、1 temporal overlap、1 verdict validity；全部保留首答和完整 rejected_issues / rejected_claim_verdicts。diagnostics 与完整 repair 请求进入 wire，业务输入不变。归一化 1 次，score_error 0。
- 三条件实际 model / thinking / effort / temperature 有无及 max_tokens=32768 均吻合；首输入与冻结 V7 prep 完全相同，每例三组首消息一致。113 个 visible raw 均与保存 parsed JSON 一致；内容及 request/wire/attempt hash 对应。
- 请求/wire 时间先于 attempt-start，start 先于 response，派发串行；每次 admission 与累计 token/POST 数对应。7 个响应超过原 8000 预算，已如实保留；各 trial 恢复 8000，实验预算明确为 40000。总量未触 1,500,000，overshoot=0。
- V8 manifest **c99e007f026aa95c19fecdb15caf3f96ccd141673bc1c2b2b30d3b140975370a**：**443 source + 253 runtime** 全匹配。最初 V7 保存基线中的 **17 product、632 freeze、375 run 文件及清单** 全部保持。
- 新 run **979 文件**读前后 hash/清单稳定。结构化敏感字段及凭据模式扫描无命中；reasoning 只保留存在性/长度/hash，不保存隐藏正文。该扫描是指定日志标记核对，不声称任意敏感文本都已被识别。

这是实验引擎与证据账本的技术验收。原 8000 兼容性是响应层观察；未进行原预算 API/数据库端到端重测。120 秒仍是 HTTPX phase timeout。模型语义、用户和 release 验收由各自记录判定。

详细证据：[engineering-live-review-06.json](engineering-live-review-06.json)，SHA-256 `f4b86e90fb8be6104d4e54bd341a27510aa1b13698894ca05c1e4fdfa95a2bbf`。审计脚本和全部新 run 文件 hash 保存在独立记录中；旧失败与补充记录均未覆盖。
