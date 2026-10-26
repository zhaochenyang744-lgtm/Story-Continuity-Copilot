# 使用统计（stats-v1）

助手的使用情况有一个只读统计脚本：`backend/app/usage_stats.py`。它从数据库里读数字和编码，输出两种格式的汇总，用来

- 找最常见的毛病（差评、失败、卡片被拒绝或撤销、核对最常没过的规则），拿来写我们自己的开发评测题；
- 每个版本上线后，和上一版的同一批数字对比。

**这些数字不是上线门槛。** 作者的话说得少、用得少的时候，比例没有意义；看的是哪类问题反复出现。

## 一条铁律

只看数字和结构，**不存、不读、不输出作者的任何文字**：作者的问题、助手的回答、章节原文、引用的段落、事实和伏笔的内容、工具参数里的检索词、计划里的对象和范围说法，都不在内。脚本靠三层保证这一点：

1. **只读打开**：SQLite 的 `mode=ro`，加 `PRAGMA query_only=ON`。脚本不写库，库文件不会变，文件不存在时也不会新建。
2. **只查白名单里的列**：`usage_stats.py` 顶部的 `ALLOWED` 逐表列出可读的列（编号、种类、状态、失败码、规则编号、次数、token、费用、字数、时间、提示词版本、模型、账号类型、是否示例作品）。没有 `SELECT *`，没有连表；含正文的列（`input_json`、`answer_json`、`text`、`summary`、`args_json`、`before_json` / `after_json`、计划和步骤的 JSON 等）不在名单里。
3. **输出前再过滤**：读出来的每个字符串都要是短的英文编码（字母、数字、`_ . : / -`），否则输出 `unrecognized`；时间必须是标准时间格式。名单里仅有的几个 JSON 列（步骤的 `diagnostics_json`、反馈的 `reasons_json`）只含规则编号、次数和固定的原因码，读出后只留已知的形状。

测试里有哨兵检验（`backend/tests/test_v210_usage_stats.py`）：在所有含正文的列里写入一个特殊字符串，跑脚本，断言输出里一次也不出现。

## 在服务器上怎么跑

生产的后端在 `story-continuity-public` 这个 compose 项目的 `backend` 容器里，数据库是容器内的 `/app/runtime/data/demo.sqlite3`（卷 `story-continuity-runtime`，见[运维说明](operations.md)里核对卷路径的命令）。可以直接复制的命令：

```bash
sudo docker exec --user continuity "$(sudo docker ps -qf name=story-continuity-public-backend)" python -m app.usage_stats --db /app/runtime/data/demo.sqlite3 --format markdown > ~/usage-stats.md
```

要给以后的对比程序读，换成 JSON：

```bash
sudo docker exec --user continuity "$(sudo docker ps -qf name=story-continuity-public-backend)" python -m app.usage_stats --db /app/runtime/data/demo.sqlite3 --format json > ~/usage-stats.json
```

参数：

| 参数 | 含义 |
|---|---|
| `--db` | 数据库路径（必填） |
| `--since 2026-10-01` | 从这一天起（按任务创建的 UTC 日期，含当天） |
| `--until 2026-10-31` | 到这一天止（含当天） |
| `--format` | `json`（默认）或 `markdown` |
| `--out 文件` | 写到文件，不写则输出到标准输出 |
| `--trace-limit 500` | 单个任务列表最多列多少条（最近的），`0` 为全部 |

输出写在服务器自己的目录里（上面的命令写到 `~`）。**看完就删掉**（`rm ~/usage-stats.md`），不要传到别处，也不要放进仓库。里面没有作者的文字，但任务编号可以在库里对应到具体任务，按用户数据对待。

在开发机上用测试库试跑：

```bash
cd backend
PYTHONPATH=.. python -m app.usage_stats --db <某个 demo.sqlite3 的副本> --format markdown
```

## 怎么读

JSON 的顶层：`{"schema": "stats-v1", "meta": …, "segments": …, "traces": […]}`。

- **`segments`**：`registered`（注册作者）、`visitor`（访客）、`sample`（示例作品）三类**分开统计、不相加**。示例作品的任务不进另外两类，只要任务所在的作品是示例作品（`demo_seed`、`tutorial_seed`）就归 `sample`。每类里有 `overall`（全时段合计）和 `groups`（按 种类 × 提示词版本 × 周，周是 ISO 周，如 `2026-W41`）。
- 每一份汇总（`overall` 或一个 group）里，字段顺序固定，**`cards` 在最前面**，这是最重要的信号：
  - `cards.by_kind[动作种类]` 和 `cards.all`：`proposed` 提出、`confirmed` 确认、`rejected` 拒绝、`undone` 撤销、`edited` 作者改过值的条数，以及 `confirm_rate`、`reject_rate`、`undo_rate`（撤销占确认）。确认过又撤销的卡片，既算确认也算撤销。
  - `tasks`、`status`（完成 / 失败 / 停下 / 没结束的条数）、`status_rate`、`error_codes`（任务的失败码分布）。
  - `feedback`：`up`、`down`、`down_rate`（差评占有评价的）、`down_reasons`（`wrong`、`verbose`、`not_found`、`bad_source`）。
  - `steps`、`elapsed_seconds`、`cost_cny`、`chars_charged`、`input_tokens`、`output_tokens`：各自的中位数 `median` 和 P90 `p90`（P90 取最近秩）。没有数据时为 `null`。
  - `rules`：`failed_codes`（核对没过的规则编号及次数，最常出问题的排在前面）、`failed_code_tasks`（出现过它的任务数）、`repairs`（修的次数）、`repaired_tasks`、`dropped`（修完后仍被程序丢掉的条目）、`dropped_codes`、`apply_dropped_codes`（交上去以后又被程序丢掉的条目，按失败码）。
  - `long`：长任务的计划类型分布 `plan_types`（`none` 是输入框判断成长任务、但计划模型认为做不了的）、来源 `origin`（`route` 输入框判断出来的、`mode` 作者选了长任务模式、`unknown` 没带）、改范围和改上限的比例、中途提问的比例 `asked_rate`、结束原因 `stopped_by`（`author_stop`、`cost_cap`、`questions_exhausted`、`program_error`，`none` 是正常做完）、`cost_cap_stop_rate`、每步 `steps`（共几步、修过几步、丢过条目几步）、每步耗时 `step_seconds`、计划读的章数 `chapters_planned`。
- **`traces`**：每个点了差评（`thumbs_down`）、失败（`failed`）、有卡片被撤销（`card_undone`）的任务一条：任务编号、种类、提示词版本、模型、状态、失败码、每一步（工具名、返回条数、失败码、规则编号、耗时毫秒）、费用、耗时、点了什么原因。长任务另有计划类型、来源、结束原因和每步的状态、耗时、规则编号、修和丢的次数。**没有任何正文。**
- **`meta.missing_columns`**：库是较早的版本、缺少某些列时，列在这里，对应数字按空值处理。

字段只增不改名；以后版本要按 `schema` 对比，字段改了含义就换成 `stats-v2`。

## 规则编号表

规则编号（`backend/app/problem_codes.py` 的 `CODES`）是稳定的英文短码，给模型看的中文句子可以随时改，编号不改。编号一旦发出就不改名、不改作他用，要换就新加一个。

- 普通任务：记在 `assistant_steps.diagnostics_json`（修的那一步和修完之后的回答那一步），形如 `{"problem_codes": ["ref_unknown"], "repairs": 1, "dropped": 0, "dropped_codes": {}}`。
- 长任务：每一步的 `assistant_long_steps.diagnostics_json`，多一项 `apply_dropped_codes`。

完整的编号和含义见代码里的 `CODES`；常见的几条：

| 编号 | 含义 |
|---|---|
| `ref_unknown` | 回答引用了工具没返回过的出处编号 |
| `sentence_no_ref` | 回答里有一句没有出处 |
| `refusal_cited` / `absence_cited` / `attribution_cited` | 带出处的句子其实是拒绝、改写建议、"原文没写什么"或作者自己的说法 |
| `people_unsupported` | 只引了事实的句子写到了事实里没有的人 |
| `note_untrue` | note 说查过的地方，步骤记录里没有 |
| `proposal_kinds_missing` | 帮我改这一处没有给出至少两种不同的改法 |
| `ref_outside_step` | 长任务的一条发现引用了这一步之外的段落 |
| `refs_over_two` | 一条发现引了两个以上的段落（一张卡片最多带两个） |
| `thread_unknown` / `verdict_invalid` | 伏笔编号不在清单里 / 判断不是 resolved、abandoned、open |
| `fact_unknown` | 过时的事实不是清单里的事实 |
| `conflict_malformed` / `conflict_fields_missing` / `conflict_subject_missing` | 对不上的地方格式不对、缺一边、缺主语 |
| `report_call_missing` | 这一步没有调用交报告的工具 |
| `change_evidence_invalid` / `change_fact_already_recorded` | 交上去以后，因为依据不成立 / 事实已经记过而没有做成卡片（`apply_dropped_codes`） |

## 记录从哪来

- 普通任务的步骤：`assistant_steps.elapsed_ms`（这一步花了多久）和 `diagnostics_json`（见上）。
- 长任务：`assistant_long_plans` 上的 `origin`（前端发起时带的可选字段）、`range_edited`、`cap_edited`（作者在计划卡上改没改章节范围、改没改费用上限）、`stopped_by`（没做完就结束的原因）、`plan_type` 和 `chapters_planned`（计划的类型和读几章，单独存，不去读含作者说法的计划 JSON）；每步的开始和结束时间本来就有。
- 这些列都在启动时用 `ALTER TABLE ... ADD COLUMN` 加上，老数据不动，老行这几列是空。删作品时随任务一起删（`assistant_store.purge`）。

隐私页的说法另行起草和批准，不在这一页。
