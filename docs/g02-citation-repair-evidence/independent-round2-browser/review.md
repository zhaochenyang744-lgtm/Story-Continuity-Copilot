# 主控第二轮浏览器复验

2026-09-26，attempt-1790423341828。主控独立启动正式前端 build W52CgAUpNgqPizlf_vc_k 与当前源码 fresh 隔离后端（合成 DB），3238/8238；runner 结束后只停止自身子进程。再次检查端口均无监听。

6 条真实 Chromium/Playwright 交互通过（26.9 秒）：normal、cycle、dialogue、post-time、post-quotes、long-tail。包括保存草稿、生成简报、展开摘要和逐项引用、读取自身来源、刷新及持久化对照。注入脚本响应 6 次，真实 Provider HTTP 为 0。运行日志、结果 JSON、各场景 evidence.json 和 PNG 保存在该 attempt 目录，不覆盖首轮。

主控目检：
- post-quotes-expanded.png：摘要及两张近期正文卡各保留自己的完整引语和说话人，摘要显示两来源，各卡一来源；否认内容未变成已确认交接。
- post-time-refreshed.png：昨日未知、今日读信后获知均在摘要及前两张卡；刷新后仍显示覆盖，背景知识记录自身引用保留。

根测试代码：frontend/e2e/g02-controller-post-v4.spec.ts。旧 root 三条及实施者 long-tail 一条共同回归，使用本轮最新后端，未把首轮旧后端结果充当新验证。

范围：浏览器、引用展示与保存刷新通过，不能证明真实模型首答质量、任意引语句法或发布 Gate。

