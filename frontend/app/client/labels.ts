// Author-facing wording for server values. Raw keys and ids never reach the page.
import type { Issue, Run, WritingAnalysisRun } from "../model";

export const stageLabel = (value: string): string =>
  ({
    queued: "排队中",
    preparing_draft: "准备草稿",
    retrieving_confirmed_facts: "读取已确认的事实",
    comparing_evidence: "对照前文",
    assembling_reviewable_results: "整理结果",
    binding_context: "读取写作资料",
    analyzing_layers: "对照计划、事实与正文",
    assembling_results: "整理结果",
    running_continuity: "检查新章节",
    running_memory_delta: "核对事实变化",
    running: "进行中",
    pending: "待处理",
    processing: "处理中",
    succeeded: "已完成",
    cancelling: "正在取消",
    completed: "已完成",
    timed_out: "超时",
    failed: "没有完成",
    cancelled: "已取消",
  } as Record<string, string>)[value] ?? "进行中";

export const activeRun = (run: Pick<Run, "status"> | null | undefined) => Boolean(run && ["queued", "running"].includes(run.status));
export const retryableRun = (run: Pick<Run, "status" | "retryable"> | null | undefined) =>
  Boolean(run && ["failed", "timed_out", "cancelled"].includes(run.status) && (run.status !== "failed" || run.retryable));
export const activeAnalysis = (run: Pick<WritingAnalysisRun, "status"> | null | undefined) => Boolean(run && ["queued", "running"].includes(run.status));
export const retryableAnalysis = (run: Pick<WritingAnalysisRun, "status" | "retryable"> | null | undefined) =>
  Boolean(run && ["failed", "timed_out", "cancelled"].includes(run.status) && (run.status !== "failed" || run.retryable));

export const timeLabel = (value?: string | null) => (value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—");
export const clockLabel = (value?: string | null) => (value ? new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }) : "");
export const dayLabel = (value?: string | null) =>
  value ? new Date(value).toLocaleString("zh-CN", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) : "";
export const durationLabel = (value?: number | null) => (value == null ? "—" : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} 秒`);

export const workStatusLabel = (value?: string) =>
  ({ active: "进行中", paused: "已暂停", complete: "已完成", completed: "已完成", archived: "已归档" } as Record<string, string>)[value ?? ""] ?? "进行中";

export const memoryTypeLabel = (value: string) =>
  ({
    static_canon: "规则",
    dynamic_state: "状态",
    event_timeline: "事件",
    character_knowledge: "谁知道什么",
    open_thread: "未解",
  } as Record<string, string>)[value] ?? "其他";
export const memoryTypes = ["static_canon", "event_timeline", "dynamic_state", "character_knowledge", "open_thread"] as const;

export const reviewStatusLabel = (value: string) =>
  ({ author_confirmed: "已确认", pending: "待确认", rejected: "已拒绝" } as Record<string, string>)[value] ?? "待确认";

export const categoryLabel = (value: string) =>
  ({
    attribute: "属性",
    location_action: "位置与动作",
    timeline: "时间线",
    character_knowledge: "谁知道什么",
    object_state: "物品状态",
    relationship: "人物关系",
    world_rule: "世界规则",
    event_status: "事件进展",
  } as Record<string, string>)[value] ?? "其他";

export const severityShort: Record<Issue["severity"], string> = { high: "高", medium: "中", low: "低" };

/** Which mark a finding gets: red = confirmed, yellow = possible, dashed = not enough evidence,
    blue outline = a state update. */
export type FindingTone = "high" | "mid" | "gap" | "state";
export const findingTone = (issue: Pick<Issue, "nature" | "severity">): FindingTone =>
  issue.nature === "confirmed_conflict" ? "high"
    : issue.nature === "possible_conflict" ? "mid"
      : issue.nature === "insufficient_evidence" ? "gap"
        : issue.nature === "state_change" ? "state"
          : issue.severity === "high" ? "high" : "mid";
export const toneLabel: Record<FindingTone, string> = { high: "确定矛盾", mid: "可能矛盾", gap: "证据不足", state: "状态更新" };

export const decisionLabel = (value?: string) =>
  ({ keep_intentional: "保留原意", false_positive: "不是问题", accept_and_edit: "已改正文" } as Record<string, string>)[value ?? ""] ?? "已处理";

/** The backend accepts only these fact keys (memory_contract.CONTROLLED_PREDICATES). */
export const controlledPredicates = ["identity", "relationship", "affiliation", "location", "status", "rule", "possession", "event_occurred", "knowledge"];
export const predicateLabel = (value: unknown) =>
  ({
    holder: "持有 / 存放",
    status: "状态",
    next_action: "下一步",
    ring_condition: "触发条件",
    rule: "规则",
    does_not_know: "还不知道",
    location: "所在位置",
    relationship: "关系",
    goal: "目标",
    occurred_at: "发生时间",
    time: "时间",
    received: "接收",
    identity: "身份",
    affiliation: "所属",
    possession: "持有",
    event_occurred: "发生的事",
    knowledge: "知道的事",
  } as Record<string, string>)[String(value)] ?? "其他";
/** Server labels such as "温岚 · does_not_know" end in a raw key; show the author wording instead. */
export const readableKeys = (text: string) => text.replace(/ · ([a-z][a-z_]*)(?=）|\)|$)/g, (_, key: string) => ` · ${predicateLabel(key)}`);

export const roleTypeLabel = (value: string) =>
  ({ protagonist: "主角", antagonist: "对立角色", ally: "同伴", supporting: "配角", other: "其他" } as Record<string, string>)[value] ?? "其他";
export const worldTypeLabel = (value: string) =>
  ({ location: "地点", rule: "规则", organization: "组织", object: "物品", term: "术语", other: "其他" } as Record<string, string>)[value] ?? "其他";

export const coverageLabel = (value?: string) =>
  ({
    required: "事实库还没建立",
    in_review: "有事实等你确认",
    ready_partial: "可以检查（部分事实待确认）",
    ready_current: "可以检查",
    update_pending: "有事实更新等你确认",
    covered_with_memory_change: "已全部确认，事实库已更新",
    covered_without_memory_change: "已全部确认，事实库没有变化",
  } as Record<string, string>)[value ?? ""] ?? "—";
export const deltaStatusLabel = (value?: string) =>
  ({ queued: "排队中", running: "检查中", in_review: "待确认", covered: "已完成", cancelled: "已取消", failed: "没有完成", timed_out: "超时" } as Record<string, string>)[value ?? ""] ?? "处理中";

export const sourceKindLabel = (type?: string) =>
  ({
    draft_claim: "草稿",
    author_context: "计划",
    author_material: "作者资料",
    source_span: "正文",
    memory_record: "事实",
    character_record: "人物",
    character_alias: "别名",
    world_record: "设定",
    issue_evidence: "检查依据",
  } as Record<string, string>)[type ?? ""] ?? "资料";
export const briefSectionLabel: Record<string, string> = { related_plan: "相关计划", confirmed_fact: "已确认的事实", character_state: "人物状态", world_rule: "世界规则", open_thread: "未解的线索", recent_source: "最近的正文" };
export const alignmentStatusLabel: Record<string, string> = { planned_covered: "已写到", planned_missing: "还没写", planned_early: "提前写了", planned_changed: "写法不同", insufficient_evidence: "依据不足" };

export const foreshadowStatusLabel: Record<string, string> = { planned: "打算埋", planted: "已埋下", developing: "展开中", resolved: "已回收", abandoned: "放弃" };
export const qaStatusLabel: Record<string, string> = { answered: "有答案", partial: "部分回答", insufficient: "依据不足", conflicting: "依据冲突" };
export const qaLayerLabel: Record<string, string> = { confirmed: "已确认的事实", written: "已写的正文", planned: "计划" };
export const qaStanceLabel: Record<string, string> = { supports: "支持", contradicts: "冲突", context: "背景" };

export const storyPlanStatusLabel: Record<string, string> = { planned: "待写", in_progress: "在写", paused: "暂停", completed: "写完了" };

export const importStrategyLabel = (strategy: string) =>
  ({
    chapter_heading: "按章节标记分章",
    markdown_heading: "按 Markdown 标题分章",
    numeric_heading: "按连续数字标题分章",
    single_chapter_fallback: "没找到可靠的分章标记，整篇保留为一章",
    markdown_or_chinese_heading: "按章节标题分章",
  } as Record<string, string>)[strategy] ?? "按章节结构分章";
export const importWarningLabel = (warning: string) =>
  ({
    directory_index_removed: "目录行已跳过，不会写进正文",
    numeric_headings_preserved_as_subsections: "重复的数字标题当作章内小节保留",
    leading_chapter_inferred: "第一章是根据后面的“第二章”推定的，开头正文已保留",
    leading_content_preserved: "章名前的开篇内容单独保留",
    chapter_heading_not_found: "没找到可信的章节分界",
    ambiguous_numeric_headings_preserved_as_single_chapter: "数字标题有歧义，原文整体保留，没有强行分章",
  } as Record<string, string>)[warning] ?? warning;

export const timelineStatusLabel: Record<string, string> = { checked: "已检查", basis_changed: "前文改过", edited_unchecked: "改后未查", unchecked: "未检查", empty: "还没写" };
export const timelineStatusHint: Record<string, string> = {
  checked: "检查覆盖了这一章现在的正文。",
  basis_changed: "检查之后，前面的章节改过，建议重新检查。",
  edited_unchecked: "这一章检查之后又改过，新的正文还没检查。",
  unchecked: "这一章还没有检查过。",
  empty: "还没写。",
};

/** Shown when a finished check leaves nothing to record into the project facts. */
export const NO_FACT_CHANGES = "这次没有要记进资料的变化。";
