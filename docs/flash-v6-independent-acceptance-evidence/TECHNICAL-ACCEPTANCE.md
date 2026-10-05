# V6 独立离线验收与真实回归放行

结论：冻结候选通过本轮独立离线验收，可在既有用户授权内执行一次固定34例真实回归。此结论不是模型质量、用户或发布验收。

固定 identity：flash-v6-20260927-01。原 manifest SHA256：f0e2cb3d5c44a1a92000f703423a0d26ea1fab5aef750b7a3393102ea98ed696；root逐项确认876/876匹配。补充 evaluation/__init__.py 单独pin见PRELAUNCH-SUPPLEMENT.json，须在Python产品模块导入前以PowerShell校验。原manifest不改。

核心9组、非法verdict四类增量、输入绑定5控制通过；42核心和10评测测试由实施自测。G02六例回放保留6摘要72条目，后续core03变化仅continuity provenance，G02路径AST不变。34实际输入和完整提示通过；旧24保留业务内容，新10显式input-v2适配；全部10冲突评分角色与先验表一致。机器通过仍须逐答独立AI语义审查。

guard三个拒绝轨迹均证明在产品导入前拒绝；第三组探针自身Windows分隔符断言误报保留原失败，依据原traceback确认guard正确拒绝，不重跑。root首次enum探针缺allowed_evidence属fixture设置失败，第二次合法输入确认TypeError后已修复复验。prep-v6-01输入门槛及选择失败完整保留。1463历史资产及280旧字节快照未变。

真实执行限额136 generation POST + 1 models GET；单case一次固定流程、最多一次合同修复、每次最多一次transport重试。400/401/403/404立即停，连续两逻辑case出现服务/传输错误即停。不得质量失败原样补跑。仅用现有命名凭据，禁止打印落盘。所有原始答复、修复、产品终态和usage缺失均如实留存。旧24与新10分别验收，G02仅作离线保留检查。本轮未授权提交、推送或部署。
