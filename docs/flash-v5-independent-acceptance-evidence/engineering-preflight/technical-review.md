# V5 独立工程准备审查结论

2026-09-27。**限定技术准备通过，建议主控仅通过已核验的 controller `live_guard.py` 启动一次授权矩阵。** 本结论针对原 V5 freeze 与新增依赖补充的组合；不把漏依赖的原 freeze 单独视为完整冻结，也不追改原清单。没有执行真实 Provider、网络、数据库或产品 API。

## 已绑定身份

- HEAD：`7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2`。
- 原 V5 manifest：`aabea4b8f99d2d4282ed627e98da98a57e46a1c526a7a45064af22acfd87682b`，274 文件；冻结准备运行 `prep-v5-03`。
- controller 补充 manifest：`bcc424e1a372b1e98b1d81d00f368e94075613ab559b1fceb68c7681c371747b`，追加 5 个 app 模块和 guard 本身，合计 280 文件。
- guard：`fe1e753c5b6e0840ba9a30bf1b9dd75bbcf4c10a5c4a76200b3677da5f28980a`。

补充的 `memory_contract`、`text_content`、`long_term_workflow`、`project_export`、`app/__init__` 是必要的直接或传递运行依赖。前两者参与受控术语/可见正文；workflow 参与初始化、run 绑定和结果；export 在 create_app 中必经注册。其本地依赖已回到原冻结清单内，本次没有扩展三方库冻结或无关模块。

## 初审发现关闭

- S01/S04：合法 JSON null/数组与 malformed issue 保留在 evaluation；评分分别记 unscorable/score_error，不冒充无响应。模拟三个连续案例中，一个产品侧 AttributeError、一个 null、一个 scorer 错误均留证据，后续案例继续；首个产品异常保留 first-failure 与 final-product-unavailable。
- S02：G02 请求已绑定本次 runtime snapshot 的 project/draft/revision、选中 source 的真实章节/文本，以及 Memory 值与真实 source。用冻结 prep JSON 作正控制，再分别改错章、Memory 值、Memory 来源，全部拒绝；无需读取或连接 DB。
- S03：G02 raw/final 分数明确 `citation_binding_only`，语义支持待人工复核。它不构成完整合同或逐项自身引用语义通过。
- 用量与派发：非法 usage 为 unknown；缺失、部分、完整分别保留。POST 与 models GET 的 start/finish 分开，孤立 start 仍为派发/服务接收未知，不计成已收到响应。timeout 后成功保留两次尝试、已知部分 token 与不完整总量；按原规则仍计本例服务失败。
- 比较 runtime 已显式使用 `Stage13Settings.for_test`，没有继续承接宿主 Stage13 配置。输入完整 capture 深比较、单 claim 前提、逐次 request/input-audit/start 的 create-only+fsync 路径保留。

## 独立执行证据与首次失败

脚本：`probe_v5.py`；首版完整保留为 `probe_v5_initial.py`。

1. `probe-runs/formal-01/results.json`：9/11 组通过；两组 runner-loop 控制因审计目录过深触发 Windows 长路径异常，未进入目标断言。原失败记录和文件不覆盖，首版脚本 SHA256 为 `f7548850b8b491d651cdece23ad42e5169910ee6a80726151a3c19f5d5f1b304`。
2. 仅给独立 probe 增加 Windows 扩展路径及定向执行选择，以新身份 `formal-02` 补跑两组未进入检查，并加入 controller guard 一组；3/3 通过。没有重复已通过的九组，第二版脚本 SHA256 为 `5c28d59cdb4167e9c06754d816a5bb898325d156011707c81ae3a482731adb5c`。
3. 合并 12 个有界控制组均有通过证据：身份先于材料/环境读取拒绝；transport 入口读回已落盘完整业务快照/hash；request/attempt 写盘失败零发送；timeout+success 与四类 usage；原始可见 content 保留且隐藏推理/Authorization/占位 key 不落盘；POST/GET 孤立 start；坏 shape/null；G02 同次绑定；两次 evaluate×两次 transport 与全局 108 边界；质量异常继续；两个恢复超时仍停止第三例；auth 与质量失败分类；补充 guard。

全局上限控制通过在内存将计数设为 107，验证第 108 次允许、下一次拒绝；它不是执行了 108 次请求。所有 transport 均为固定 mock。runner-loop 控制用预存 request/evaluation 模拟 API 返回或异常，替换 fixture/API 和 models preflight；不声称验证真实 DB/API 全链路。

两轮均使用 socket/sqlite/HTTP 阻断与写路径审计；实际网络、真实 Provider、数据库连接为 0，阻断计数亦为 0，说明未触达被禁止路径。所有写入留在本审计目录。每轮 `frozen-hashes-before.json` 与 `frozen-hashes-after.json` 一致，fixture JSON hash 不变。

## controller guard 验证

`formal-02/checks/controller_dependency_guard.json` 记录当前 verify 成功，核验 HEAD 及 280 个文件；没有调用 launch，也没有创建真实运行身份。补充 manifest SHA 错误与模拟 `text_content.py` hash 漂移分别被拒绝；占用身份在任何 sha/material 读取前拒绝。源文件和补充文件的前后 hash 一致，负控没有真实修改旧依赖。

正式派发必须走这份已绑定 guard 的 CLI 校验路径，不单独调用其 `launch()` 或绕过 wrapper 直接执行原 V5 live 命令。runner 仍负责唯一身份、原 freeze 检查和有界矩阵；controller guard 补足依赖闭包。

## 结论范围

本审阅通过的是限定工程准备与证据链关键控制，主控另负责材料血缘、完整自测及实际执行启动。没有真实模型成绩、逐答叙事语义准确率、浏览器新验收、生产恢复、发布或用户接受结论。实测后仍须独立核对 30 例或明确停止后的实际分母、首 content/首个可解析 JSON/repair/final、HTTP 尝试与 usage，并对结论及自身引用关系逐答人工复核。
