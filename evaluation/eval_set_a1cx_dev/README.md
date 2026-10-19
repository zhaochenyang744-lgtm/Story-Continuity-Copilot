# 开发题 eval_set_a1cx_dev

助手开发用的题目，**不是留用集**，由 Opus 在已经用过的长文本作品上编写（A1c SPEC 补充二第 6 条）。不作为任何门槛。

| 作品 | 来源 | 章数 | 题数 |
|---|---|---:|---:|
| `works/moriri.md` | `eval_set_lf1_import`（121 章，约 33.6 万字） | 121 | 13 |
| `works/folio.md` | `eval_set_lf2_formal` 的 folded_folio | 10 | 9 |
| `works/cistern.md` | `eval_set_lf2_formal` 的 resonant_cistern | 8 | 3 |

题型：有答案 9（含多章 2）、前后不一致 7、找不到 3、前情总结 2、修改建议 2、追问 2。前后不一致题用的是原题集里有意写错的地方；每道题的 `note` 写了依据。`quote_positions` 是依据句在章内的汉字位置，`deep` 由它算出。

## 授权

`works/moriri.md` 是 `eval_set_lf1_import/works/moriri_cleaner.md` 去掉段落之间空行后的文本（文字和章内汉字位置不变；原文件连空白共 356,620 字符，超过产品 35 万字符的导入上限）：改编自睡半夜怎麼三更《末日收尾人》（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)），出处与改动见 `evaluation/eval_set_lf1_import/README.md`。本目录中的该文本同样以 CC BY 4.0 提供，署名原作者"睡半夜怎麼三更"。其余两部为本仓库原创评测文本。

检查：`python -m evaluation.eval_set_a1cx_dev.check`
