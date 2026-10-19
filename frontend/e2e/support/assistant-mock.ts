import type { Page } from "@playwright/test";

// Assistant task views made by hand, for the tests that need a state a real run cannot hold still (a step that is in progress,
// a task that has just been cut short, an answer with every kind of source). The page reads them from the same two addresses it
// reads the real ones from; everything it sends (POST, PUT, DELETE) still goes to the real test server.

const ago = (seconds: number) => new Date(Date.now() - seconds * 1000).toISOString();

/** A finished question with an answer that cites two passages, as the server would show it. Anything can be overridden. */
export function askView(over: Record<string, unknown> = {}) {
  return {
    id: "atask-mock-ask", kind: "ask", status: "completed", question: "苏岑知道罗盘被调包了吗？",
    context: { page: "writing", chapter_number: 11 }, follow_up_of: null, regenerated_from: null, edited_from: null,
    steps: [
      { round: 1, kind: "say", tool: null, summary: "先查苏岑和罗盘的已确认事实。", result_count: null, group: null, refs: [], error_code: null, error_text: null },
      { round: 1, kind: "tool", tool: "lookup_facts", summary: "查事实：苏岑", result_count: 1, group: "g1-lookup_facts", refs: ["R1"], error_code: null, error_text: null },
      { round: 1, kind: "tool", tool: "lookup_facts", summary: "查事实：黄铜罗盘", result_count: 0, group: "g1-lookup_facts", refs: [], error_code: null, error_text: null },
      { round: 2, kind: "say", tool: null, summary: "再看罗盘在第 9、10 章经过了谁的手。", result_count: null, group: null, refs: [], error_code: null, error_text: null },
      { round: 2, kind: "tool", tool: "search_text", summary: "搜正文：「罗盘」· 第 1–10 章", result_count: 2, group: "g2-search_text", refs: ["R2", "R3"], error_code: null, error_text: null },
      { round: 2, kind: "tool", tool: "search_text", summary: "搜正文：「抽屉」· 第 9–10 章", result_count: 1, group: "g2-search_text", refs: ["R4"], error_code: null, error_text: null },
      { round: 2, kind: "tool", tool: "read_chapter", summary: "读第 10 章《五点四十分》", result_count: null, group: "g2-read_chapter", refs: [], error_code: null, error_text: null },
      { round: 3, kind: "say", tool: null, summary: "最后对一下草稿里写的。", result_count: null, group: null, refs: [], error_code: null, error_text: null },
      { round: 3, kind: "tool", tool: "read_draft", summary: "读本章草稿", result_count: null, group: "g3-read_draft", refs: [], error_code: null, error_text: null },
    ],
    answer: {
      status: "answered",
      sentences: [
        { text: "前文没有写苏岑知道罗盘被调包。", refs: ["R2"] },
        { text: "第 10 章里罗盘一直锁在温岚的抽屉中，苏岑没有再见过它。", refs: ["R3"] },
      ],
      note: null,
    },
    sources: {
      R1: { kind: "fact", chapter_number: 9, chapter_title: "第九章 仓道的高台", start: null, end: null, text: "苏岑：把罗盘交给温岚保管", cited: false },
      R2: { kind: "passage", chapter_number: 9, chapter_title: "第九章 仓道的高台", start: 10, end: 52, text: "苏岑把罗盘交给温岚，说“你先替我收着”。", cited: true },
      R3: { kind: "passage", chapter_number: 10, chapter_title: "第十章 五点四十分", start: 120, end: 150, text: "温岚把罗盘放进抽屉，锁上了。", cited: true },
      R4: { kind: "passage", chapter_number: 10, chapter_title: "第十章 五点四十分", start: 300, end: 330, text: "老周问起那枚罗盘，温岚没有回答。", cited: false },
    },
    out_of_scope_text: null,
    coverage: { checked: ["第 1–10 章正文", "已确认事实"], not_checked: ["计划"] },
    usage: { steps: 5, chars_charged: 500 },
    phase: null, phase_tool: null, phase_chapter: null, phase_started_at: null, feedback: null, error_code: null,
    created_at: ago(70), started_at: ago(68), completed_at: ago(54),
    ...over,
  };
}

/** A question that is still being worked on: one line said, one action done, and the step in progress. */
export function runningView(phase: "thinking" | "tool", over: Record<string, unknown> = {}) {
  const view = askView({
    id: "atask-mock-run", status: "running", answer: null, coverage: null, sources: {}, completed_at: null,
    usage: { steps: 1, chars_charged: 500 }, created_at: ago(9), started_at: ago(8),
    steps: [
      { round: 1, kind: "say", tool: null, summary: "先查苏岑和罗盘的已确认事实。", result_count: null, group: null, refs: [], error_code: null, error_text: null },
      { round: 1, kind: "tool", tool: "lookup_facts", summary: "查事实：苏岑", result_count: 2, group: "g1-lookup_facts", refs: [], error_code: null, error_text: null },
    ],
    phase, phase_tool: phase === "tool" ? "read_chapter" : null, phase_chapter: phase === "tool" ? 10 : null, phase_started_at: ago(5),
  });
  return { ...view, ...over };
}

/** Make the page read these tasks as the work's conversation (a function, so a test can change them between reads).
    Resolves with a function that takes the served tasks away again. */
export async function serveTasks(page: Page, tasks: () => unknown[]) {
  const matches = (url: URL) => /\/api\/projects\/[^/]+\/assistant\/tasks(\/[^/]+)?$/.test(url.pathname);
  const handler = async (route: import("@playwright/test").Route) => {
    const request = route.request();
    if (request.method() !== "GET") { await route.fallback(); return; }
    const url = new URL(request.url());
    const id = url.pathname.split("/assistant/tasks/")[1];
    const all = tasks() as { id: string }[];
    const body = id ? all.find((task) => task.id === id) : { tasks: all };
    if (!body) { await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "resource_not_found", message: "x", retryable: false } }) }); return; }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: body, request_id: "mock" }) });
  };
  await page.route(matches, handler);
  return () => page.unroute(matches, handler);
}

/** One way out of a finding, as the server shows it (an edit of one sentence unless overridden). */
export function proposalView(over: Record<string, unknown> = {}) {
  return {
    id: "aprop-mock-1", proposal: "P1", kind: "edit_this", chapter_number: null,
    before: "苏岑的外套内袋里装着父亲那枚带月牙裂纹的黄铜罗盘，而此刻同一枚罗盘仍握在温岚手中。",
    after: "苏岑的外套内袋里空着，父亲那枚带月牙裂纹的黄铜罗盘此刻仍握在温岚手中。",
    rationale: "只改罗盘在哪里，保留苏岑摸内袋的动作。", status: "proposed", after_edited: null, edited_by_author: false,
    draft_id: "draft-mock", draft_revision: 1, adopted_draft_revision: null, decided_at: null, recheck: null,
    ...over,
  };
}

/** A finished 帮我改这一处 with the given ways out. */
export function fixView(proposals: unknown[], over: Record<string, unknown> = {}) {
  return askView({
    id: "atask-mock-fix", kind: "fix_issue", question: null, context: { page: "writing", issue_id: "issue-mock" },
    steps: [], coverage: null,
    answer: { status: "answered", sentences: [{ text: "这句物品状态与已确认的事实可能冲突。", refs: ["R1"] }], note: null },
    sources: { R1: { kind: "issue", chapter_number: null, chapter_title: null, start: null, end: null, text: "这句物品状态与已确认的事实可能冲突。", cited: true } },
    proposals, ...over,
  });
}
