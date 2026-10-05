# V7 修复技术验收

主控验收结论：通过固定34例真实Provider回归的技术门槛。用户在本会话已授权必要Provider调用，无需另行请求许可。真实模型质量待本轮输出及独立语义验收，不能由离线测试推定。

产品prompt为 `continuity-review-v17-repair-diagnostics`，schema provenance为 `continuity-issue-v7-repair-diagnostics`；兼容的两数组输出shape保留v6 marker。冻结manifest SHA256为 `361f4d7d778d6818b258e51caec65a8fd6e4a762b52c78181de35c5f7f8abe47`，direct-file guard已核验632文件（包括evaluation initializer）。正式run为 `flash-v7-20260927-01`，输入/gold/评分口径沿用V6的24旧例+10已见开发控制，不是盲测。

## 修复与证据

- HH:MM合法时钟识别、非法时钟词边界；同日同刻支持、不同分钟/小时/日期/无共享日期及引述回忆不被误升格。诊断和validate共用同一个直接contradicts时间判定。真实V6第26例原首答离线可一次交付且无normalization；第22例越界引用仍拒绝。
- 保留basis最多400 Unicode code points，统一常量驱动schema、prompt、validate；提供claim、invalid_field、observed_length、limit。未截断旧输出或放宽上限。
- repair携带完整原issues和claim_verdicts，收集同claim多项错误及逐claim不一致；明确不足判断需要实际交付带missing_link的Issue。完整反馈超过6000输入估值时在下一次evaluate前失败，保留原输出及既有usage，不进行截断。两次合同evaluate/一次transport重试边界不变。

根75项测试全部通过（旧42、新17、评测工具16），见offline-tests-01。最终词法增量后旧42+新17重新检查：58项首轮通过，1项因测试防护误拦Windows asyncio内部socketpair而失败；精确标准库自管道白名单单项复核通过，两个原始日志均保留。未修改旧测试以过关。

输入独立复核34/34通过，341所读文件前后稳定；完整prompt未注入gold或控制标签，见input-review-01。预检完整反馈离线估值最高5469/6000；这不保证任意多claim返回都能放入repair。最终prechecks-03确认G02类、非continuity提示、通用formatter/预算器AST及brief_citations与V6基线相同，故不追加G02真实调用。

## 边界

V6原run420文件及历史证据保留，基线源码另存baseline目录；本轮未提交、推送或发布，真实回归仅使用新隔离数据库。费用未知时保留unknown。8000预算检查仍是既有单次返回检查，并非整run累计token上限；真实HTTP调用受136 POST+1 GET总上限及原服务停止条件约束。
