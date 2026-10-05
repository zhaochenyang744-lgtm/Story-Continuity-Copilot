# 检查结束后的源码漂移说明

`results.json` 和 `cap-results.json` 中的探针针对 V4 冻结源码执行，执行窗口内 `brief_citations.py`、`engine.py`、`v2_database.py` 与冻结 hash 一致，测试前后未变。

写完 `review.md` 后再次读取源码 hash，发现实施侧已有新修改：

| 文件 | 探针所用 V4 hash | 后续只读检查所得 hash |
|---|---|---|
| `brief_citations.py` | `11a9b6f6c6f8d09ba85fe94c882cdbb7383e6ebb101bb5d1305212caf31dab69` | `a0a3a31251860265c29b09a95e85b27f05d92dc1a0e6bcc0a9d1736a57b28ccc` |
| `engine.py` | `370952e8a0452b4cfe2da8b1a2a662534d0d98fe3d14ba13859aff2a9e3189d1` | 相同 |
| `v2_database.py` | `540d74a4607639ecff2ea13e9d29ab99e0121a8f577930020a7707dd4bed8933` | `2485b997c32dda446325fe1535df0342330b09afdd53b9619137ad824a17e754` |

因此 `review.md` 是 **V4 冻结版本** 的独立结论，不是这次新改动后的验收。两项反例及首次结果均保持原样；在实施侧新冻结后应以新文件再次执行相关探针。此说明不推断新改动是否已解决任何问题，也未重新执行或覆盖结果。
