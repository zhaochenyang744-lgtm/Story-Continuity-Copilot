# 既有缺口修补的版本化证据

本目录同时承载可复现的验收证据和本地运行产物。2026-09-26 用户确认本轮修改结果并授权本地 Git 提交；提交内容使用显式白名单，见 [retained-manifest.json](retained-manifest.json)。业务修补的最终范围及限制见 [独立验收报告](../legacy-gap-repair-independent-acceptance.md)。

版本化内容包括三轮报告、复现/复跑脚本、小型离线结果、源码指纹、最终浏览器身份与结果，以及四张代表性截图。第一、二轮的产品失败结果与第三轮通过结果同时保留，不能将错误输出经过产品降级后的安全结果当作真实模型准确率。

代表性浏览器证据：

- [富文本混合格式安全拒绝](independent-round2-browser/attempt-1790402376904/results/legacy-gap-independent-rou-fbbc7-out-changing-body-or-saving/mixed-marks.png)
- [嵌套列表和引用保存刷新后保格式](independent-round2-browser/attempt-1790402376904/results/legacy-gap-independent-rou-4dcc5-h-explicit-save-and-refresh/nested-list-quote-saved-reloaded.png)
- [错配引用移除并说明原因，刷新后保持](independent-round3-browser/attempt-1790403376077-22220/results/legacy-gap-round3-brief-G0-b6569-esh-with-correct-disclosure/cycle-after-refresh.png)
- [正常三条引用完整保留](independent-round3-browser/attempt-1790403376077-22220/results/legacy-gap-round3-brief-G0-36405-esh-with-correct-disclosure/valid-after-refresh.png)

本地保留而不提交：合成数据库及 runtime 目录、浏览器会话/注册请求和响应、trace/network 资源、压缩 trace、运行日志、控制台原始输出及其他截图。没有删除、覆盖或清理这些历史材料。各轮原报告仍保留当时完整证据路径；不在清单中的链接仅在原验收工作树可用，干净检出请按报告复跑以生成新证据。

本目录的 `.gitignore` 默认忽略新产物，仅放行清单中的文件；`.gitattributes` 禁用证据的自动换行转换，以保留原始字节和 SHA-256。后续需要版本化新证据时，应先检查其用途与内容，再显式扩充白名单。复跑应使用新的证据目录或唯一 attempt，避免覆盖已保留的首次失败。

没有纳入真实密钥或真实数据库。小型结果中的项目/主张标识来自合成离线材料；它们与真实账号无关。真实 Provider、SMTP、线上成功链路和完整恢复仍未通过本轮验证。
