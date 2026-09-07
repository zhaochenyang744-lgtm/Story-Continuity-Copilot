import { request, jsonWithIdempotency, type ApiFailure } from "../api";
import {
  EMPTY,
  type AuthorDocument,
  type Comparison,
  type Passage,
  type PreviewState,
  type Resolution,
} from "./author-context-model";

export const backendConnected =
  process.env.NEXT_PUBLIC_AUTHOR_CONTEXT_BACKEND === "1";
export type ContextSnapshot = {
  data: PreviewState;
  error: string;
  blocked: boolean;
};
export type ServerComparison = {
  id: string;
  document: AuthorDocument;
  passage: Passage;
  source_revision: number;
  decision_revision: number;
  is_stale: boolean;
  applicable?: boolean;
  latest_analysis_run_id?: string | null;
  decision_history: {
    id: string;
    decision: string;
    reason: string;
    created_at: string;
    before_material?: AuthorDocument;
    after_material?: AuthorDocument;
    is_effective: boolean;
  }[];
};
export type ContextAnalysis = {
  run_id: string;
  status:
    "queued" | "running" | "completed" | "failed" | "cancelled" | "timed_out";
  is_stale: boolean;
  error_code: string | null;
  retryable: boolean;
  analysis?: {
    assessment:
      | "aligned"
      | "possible_tension"
      | "plan_deviation"
      | "insufficient_evidence";
    explanation: string;
    evidence?: { source_type: string; source_id: string; excerpt?: string }[];
  };
};
const decisionNames: Record<Resolution, string> = {
  revise_text: "prepare_text_edit",
  revise_document: "adjust_material",
  intentional: "intentional",
  not_issue: "not_issue",
  later: "later",
};
export function contextError(cause: unknown) {
  const error = cause as ApiFailure;
  if (/conflict|stale|version/.test(error.code ?? ""))
    return "资料或正文有了新改动。你的输入还在，请先查看最新内容，再决定怎么保存。";
  if (error.code === "provider_unavailable")
    return "AI 暂时还不能提供分析。你仍然可以查看资料和原文，记下自己的判断。";
  if (/out_of_range/.test(error.code ?? ""))
    return "正文不在这条资料的适用章节范围内，请重新选择。";
  if (/insufficient/.test(error.code ?? ""))
    return "目前的正文记录还不够，暂时无法分析。请先到 Story Memory，按提示补充并确认记录。";
  if (error.code === "request_timeout")
    return "暂时没收到保存结果。可以重试，不会重复保存同一条内容。";
  return error.message || "服务暂时无法完成请求，请重试。";
}
export function materialFields(document: AuthorDocument) {
  return {
    kind: document.kind,
    title: document.title,
    content: document.content,
    nature: document.nature,
    disclosure: document.disclosure,
    knowledge: document.knowledge,
    from: document.from,
    to: document.to,
  };
}
// One key per logical mutation survives uncertain HTTP outcomes. It is released only after a definite success.
export function createContextApi(projectId: string) {
  const root = `/projects/${projectId}/author-context`;
  const keys = new Map<string, string>();
  const lifecycleRequests = new Map<string, string>();
  const lifecycleResults = new Map<string, string>();
  const write = async <T>(
    path: string,
    method: "POST" | "PATCH",
    payload: unknown,
  ): Promise<T> => {
    const signature = `${method}:${path}:${JSON.stringify(payload)}`;
    const key = keys.get(signature) ?? crypto.randomUUID();
    keys.set(signature, key);
    const result = await jsonWithIdempotency<T>(path, method, payload, key);
    keys.delete(signature);
    return result;
  };
  const lifecycle = async (runId: string, action: "cancel" | "retry") => {
    const signature = `${action}:${runId}`;
    const clientId = lifecycleRequests.get(signature) ?? crypto.randomUUID();
    lifecycleRequests.set(signature, clientId);
    let target = lifecycleResults.get(signature);
    if (!target) {
      const result = await write<{run?: ContextAnalysis}>(`/projects/${projectId}/analyses/${encodeURIComponent(runId)}/${action}`, "POST", {client_request_id:clientId});
      target = action === "retry" ? result.run?.run_id : runId;
      if (!target) throw Error("暂时没能获取分析进度，请稍后重试。");
      lifecycleResults.set(signature, target);
    }
    return request<ContextAnalysis>(`/projects/${projectId}/analyses/${encodeURIComponent(target)}`);
  };
  return {
    root,
    materials: () =>
      request<{ author_context_version: number; materials: AuthorDocument[] }>(
        `${root}/materials?include_archived=true`,
      ),
    comparisons: () =>
      request<{ comparisons: ServerComparison[] }>(
        `${root}/comparisons?include_stale=true`,
      ),
    comparison: (id: string) =>
      request<ServerComparison>(
        `${root}/comparisons/${encodeURIComponent(id)}`,
      ),
    create: (document: AuthorDocument, version: number) =>
      write<{ material: AuthorDocument; author_context_version: number }>(
        `${root}/materials`,
        "POST",
        {
          base_author_context_version: version,
          ...materialFields(document),
          origin: "author",
        },
      ),
    update: (document: AuthorDocument, version: number, revision: number) =>
      write<{ material: AuthorDocument; author_context_version: number }>(
        `${root}/materials/${encodeURIComponent(document.id)}`,
        "PATCH",
        {
          base_author_context_version: version,
          base_revision: revision,
          ...materialFields(document),
        },
      ),
    archive: (document: AuthorDocument, version: number, revision: number) =>
      write(
        `${root}/materials/${encodeURIComponent(document.id)}/archive`,
        "POST",
        {
          base_author_context_version: version,
          base_revision: revision,
          archived: document.archived,
          confirm: true,
        },
      ),
    compare: (
      document: AuthorDocument,
      passage: Passage,
      sourceRevision: number,
    ) =>
      write<ServerComparison>(`${root}/comparisons`, "POST", {
        material_id: document.id,
        material_revision: document.revision,
        source_span_id: passage.id,
        source_revision: sourceRevision,
      }),
    decide: (
      comparison: ServerComparison,
      resolution: Resolution,
      reason: string,
      version: number,
      adjusted?: AuthorDocument,
    ) =>
      write<{comparison:ServerComparison}>(
        `${root}/comparisons/${encodeURIComponent(comparison.id)}/decisions`,
        "POST",
        {
          base_decision_revision: comparison.decision_revision,
          decision: decisionNames[resolution],
          reason,
          ...(adjusted
            ? {
                base_author_context_version: version,
                base_material_revision: comparison.document.revision,
                material_patch: materialFields(adjusted),
              }
            : {}),
        },
      ).then(result => result.comparison),
    analyze: (comparison: ServerComparison) =>
      write<ContextAnalysis>(
        `${root}/comparisons/${encodeURIComponent(comparison.id)}/analysis`,
        "POST",
        { base_decision_revision: comparison.decision_revision },
      ),
    readAnalysis: (runId: string, signal?: AbortSignal) =>
      request<ContextAnalysis>(
        `/projects/${projectId}/analyses/${encodeURIComponent(runId)}`,
        { signal },
      ),
    cancelAnalysis: (runId: string) => lifecycle(runId, "cancel"),
    retryAnalysis: (runId: string) => lifecycle(runId, "retry"),
  };
}

export function comparisonView(item: ServerComparison): Comparison[] {
  return item.decision_history
    .map((decision) => ({
      id: decision.id,
      serverId: item.id,
      serverStale: item.is_stale,
      superseded: !item.is_stale && !decision.is_effective,
      document: decision.after_material ?? item.document,
      previousDocument: decision.before_material,
      passage: item.passage,
      sourceRevision: item.source_revision,
      resolution: (Object.entries(decisionNames).find(
        ([, value]) => value === decision.decision,
      )?.[0] ?? "later") as Resolution,
      reason: decision.reason,
      at: decision.created_at,
    }))
    .reverse();
}

export function createBackendStore(projectId: string) {
  const api = createContextApi(projectId);
  let snapshot: ContextSnapshot = { data: EMPTY, error: "", blocked: true },
    version = 0;
  let inFlight = false,
    readSequence = 0;
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((fn) => fn());
  const comparisonCache = new Map<string, ServerComparison>();
  const refresh = async () => {
    const sequence = ++readSequence;
    try {
      const [materials, comparisons] = await Promise.all([
        api.materials(),
        api.comparisons(),
      ]);
      if (sequence !== readSequence) return;
      version = materials.author_context_version;
      comparisonCache.clear();
      for (const item of [...comparisons.comparisons].reverse()) {
        const key = JSON.stringify([
          item.document.id,
          item.document.revision,
          item.passage.id,
          item.source_revision,
        ]);
        if (!item.is_stale && !comparisonCache.has(key))
          comparisonCache.set(key, item);
      }
      snapshot = {
        data: {
          ...EMPTY,
          serial: version,
          documents: materials.materials,
          comparisons: comparisons.comparisons.flatMap(comparisonView).sort((a,b) => b.at.localeCompare(a.at)),
        },
        error: "",
        blocked: inFlight,
      };
    } catch (cause) {
      if (sequence === readSequence)
        snapshot = { ...snapshot, error: contextError(cause), blocked: true };
    }
    notify();
  };
  const comparisonFor = async (
    document: AuthorDocument,
    passage: Passage,
    sourceRevision: number,
  ) => {
    const signature = JSON.stringify([
      document.id,
      document.revision,
      passage.id,
      sourceRevision,
    ]);
    let comparison = comparisonCache.get(signature);
    if (!comparison) {
      comparison = await api.compare(document, passage, sourceRevision);
      comparisonCache.set(signature, comparison);
    }
    return comparison;
  };
  return {
    api,
    comparisonFor,
    findComparison: (
      document: AuthorDocument,
      passage: Passage,
      sourceRevision: number,
    ) =>
      comparisonCache.get(
        JSON.stringify([
          document.id,
          document.revision,
          passage.id,
          sourceRevision,
        ]),
      ),
    get: () => snapshot,
    subscribe: (fn: () => void) => {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    refresh,
    update: async (fn: (state: PreviewState) => PreviewState) => {
      if (snapshot.blocked || inFlight) return false;
      const before = snapshot.data,
        after = fn(before);
      const changed = after.documents.filter(
        (d) =>
          JSON.stringify(d) !==
          JSON.stringify(before.documents.find((old) => old.id === d.id)),
      );
      const added = after.comparisons.find(
        (c) => !before.comparisons.some((old) => old.id === c.id),
      );
      inFlight = true;
      snapshot = { ...snapshot, blocked: true, error: "" };
      notify();
      try {
        if (added) {
          const document =
            added.previousDocument ??
            before.documents.find((d) => d.id === added.document.id);
          if (!document) throw Error("先保存这条资料，就可以和正文对照了。");
          const comparison = await comparisonFor(
            document,
            added.passage,
            added.sourceRevision,
          );
          const result = await api.decide(
            comparison,
            added.resolution,
            added.reason,
            version,
            added.resolution === "revise_document" ? added.document : undefined,
          );
          comparisonCache.set(
            JSON.stringify([
              document.id,
              document.revision,
              added.passage.id,
              added.sourceRevision,
            ]),
            result,
          );
        } else if (changed.length === 1) {
          const document = changed[0],
            original = before.documents.find((d) => d.id === document.id);
          if (!original) await api.create(document, version);
          else if (original.archived !== document.archived)
            await api.archive(document, version, original.revision);
          else await api.update(document, version, original.revision);
        } else if (changed.length > 1) throw Error("请一次保存一条资料。");
        inFlight = false;
        await refresh();
        return true;
      } catch (cause) {
        inFlight = false;
        if (/conflict|stale|version/.test((cause as ApiFailure).code ?? ""))
          await refresh();
        snapshot = { ...snapshot, blocked: false, error: contextError(cause) };
        notify();
        return false;
      }
    },
  };
}
