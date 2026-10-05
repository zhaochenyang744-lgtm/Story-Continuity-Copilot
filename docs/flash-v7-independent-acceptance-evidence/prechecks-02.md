# 当前 V7 合同的离线容量与隔离检查

本记录针对 engine `1da59198cf29e775f81ce11be8a43118b0e279bdf5683b366016d112645a7e95`、provider `942d772662b5e44cca5de7b40d7a10c25210a8cadaef6faee11808ef07ba6f24`，读取前后未变。后续代码变化须另作增量，不覆盖本记录。

34份V6首答请求换成当前 `_continuity_schema`，用当前诊断和完整原 issues／claim_verdicts 构造34份假设修复请求。最大首请求4433单位（17），最大完整修复5469（24），超过6000为0；全部保留原输出，未截断。无诊断的输入也作容量估值，但不表示产品会实际修复。此为估值，既非新模型结果，也不证明多claim或任意近上限输入安全。

隔离核对通过：WritingAnalysisEngine、所有非continuity提示函数、request_prompt_and_budget、估算器AST均与V6基线一致；brief_citations字节一致。仅本轮continuity修复不需要额外G02真实调用；6summary／72items的既有限定范围不变。

时间主路径改善：14:00同值、10:00同值通过；14:00对14:01、今日对昨日拒绝。非法24:00、10:60、不完整分钟、三位分钟、HH:MM:SS、00:30pm均拒绝。预诊断与正式validate现共用 `_confirmed_temporal_failure`，同样要求足量直接contradicts证据；来源绑定和schema检查差别仍各有职责。

仍有一个小缺陷：`At x14:00 today` 被读作840分钟，`At 10:00pmx today` 被读作600分钟。裸HH:MM分支只检查数字／冒号边界，识别失败的字母后缀可退回裸时钟。建议在保留正常中英文时间邻接的前提下，限定标识符及错误am/pm后缀边界，不把任意字符串中钟点子串当完整时锚。

方法：仅标准库解析源码AST，隔离提取经检查的纯schema、诊断、formatter与时钟函数；未导入产品模块、运行engine.execute、调用Provider或打开DB。详细34行估值、AST摘要和只读探针见prechecks-02.json。
