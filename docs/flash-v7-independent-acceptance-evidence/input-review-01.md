# V7 准备输入独立验收

结论：**34/34 通过，无输入层阻断**。本报告是 `prep-v7-01` 离线 stub 输入检查，不是模型成绩。

- 24旧例＋10去重开发控制的故事、draft/claim正文、selected顺序及全文、Memory精确集合与V6一致；34份runtime绑定快照相等，ID/revision及摘要匹配。
- 业务请求仅允许运行生成的claim ID变化，以及schema中basis说明明确“at most 400 Unicode code points”；34份均可见。
- 用标准库AST隔离当前精确continuity_prompt与四个数据常量，生成完整34份prompt；逐一核对draft/current_claims/allowed_evidence/Memory/schema，并确认规则也明确400。未导入产品模块、构造Provider、调用网络或打开DB。
- 34份请求和完整prompt均未出现case_id/control_ids、gold、expected分类/类别、semantic_role、候选答案等案例专属标注。通用schema枚举及通用判定例子仍按合同存在。
- lens控制仍选择L1/L2/L4，L3仅Memory已知；来源和Memory ID保留，材料仍是seen development。
- 准备记录为34 completed，POST 0、models GET 0；这不代表任何真实模型通过率。

所有逐例请求路径、business/prompt SHA-256及读取文件摘要在同名JSON。共341份所读文件前后SHA-256一致；未修改准备记录或工具。修复轮prompt和真实回答的语义验收仍由后续阶段完成。
