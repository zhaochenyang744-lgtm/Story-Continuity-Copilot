export type ApiFailure = Error & {
  code: string;
  retryable: boolean;
  details?: Record<string, unknown>;
};
type Envelope<T> = { data: T; request_id: string };

/** Same-origin client. Session cookies are browser-owned; tokens never enter React state or storage. */
export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const own = !init.signal;
  const controller = own ? new AbortController() : undefined;
  const timer = controller
    ? window.setTimeout(() => controller.abort(), 15_000)
    : undefined;
  const headers = new Headers(init.headers);
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  )
    headers.set("Content-Type", "application/json");
  try {
    const response = await fetch(`/api${path}`, {
      ...init,
      credentials: "same-origin",
      headers,
      signal: init.signal ?? controller?.signal,
    });
    if (response.status === 204) return undefined as T;
    const payload = (await response.json()) as Envelope<T> & {
      error?: {
        code?: string;
        message?: string;
        retryable?: boolean;
        details?: Record<string, unknown>;
      };
    };
    if (!response.ok) {
      const error = new Error(
        payload.error?.message ?? "请求无法完成",
      ) as ApiFailure;
      error.code = payload.error?.code ?? "unknown_error";
      error.retryable = Boolean(payload.error?.retryable);
      error.details = payload.error?.details;
      throw error;
    }
    return payload.data;
  } catch (cause) {
    // An AbortSignal supplied by the caller is deliberate lifecycle control
    // (for example, abandon project A while navigating to project B). Keep
    // its AbortError intact so that the caller can ignore it. Only this
    // client's 15 second controller is a request timeout.
    if (own && (cause as Error).name === "AbortError") {
      const error = new Error("请求超时") as ApiFailure;
      error.code = "request_timeout";
      error.retryable = true;
      throw error;
    }
    throw cause;
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}

export const json = <T>(
  path: string,
  method: "POST" | "PATCH",
  body: unknown,
  signal?: AbortSignal,
) =>
  request<T>(path, {
    method,
    signal,
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(body),
  });

export const labelError = (cause: unknown) => {
  const code = (cause as ApiFailure)?.code;
  const labels: Record<string, string> = {
    authentication_required: "会话已失效；已清除当前作品上下文，请重新登录。",
    invalid_credentials: "账号或密码不正确。",
    authentication_rate_limited: "登录尝试过于频繁，请稍后再试。",
    provider_unavailable:
      "本地 provider 不可用。本轮没有生成替代 Issue，可在恢复后重新检查。",
    invalid_json: "结果未通过结构校验，系统没有写入任何问题。",
    evidence_unresolvable:
      "证据来源不可解析，结果已安全关闭；请检查来源后重试。",
    revision_conflict:
      "草稿已被其他编辑更新。本地修改仍保留，请重新载入后处理冲突。",
    lineage_invalid_requires_recheck:
      "草稿谱系已失效，请基于当前 revision 重新检查。",
    insufficient_project_context:
      "Story Memory 尚待初始化；此作品暂不能运行连续性检查。",
    invalid_candidate_decision: "请为每个候选选择接受、拒绝或编辑后接受。",
    evidence_confirmation_required: "编辑后接受前，请明确确认上方 Evidence 仍支持该事实。",
    source_revision_not_current: "导入来源已不是当前 revision；系统没有写入候选或 Memory。",
    memory_initialization_conflict: "Memory V1 已不再为空，初始化已安全停止。",
    request_timeout: "请求超时，请稍后重试。",
    project_archived: "作品已归档，只读浏览。请先恢复作品再执行此操作。",
    metadata_revision_unavailable: "作品信息暂不可更新，请稍后重试。",
    source_revision_conflict: "来源版本已变化；没有追加章节，请重新预览。",
    source_hash_mismatch: "预览内容校验不一致；没有追加章节，请重新预览。",
    source_change_set_expired: "追加预览已过期；没有追加章节，请重新预览。",
    empty_source: "追加内容为空，无法创建章节。",
    unsupported_format: "文件仅支持 UTF-8 的 .md 或 .txt。",
  };
  return labels[code] ?? "请求未完成。请保留当前内容并重试。";
};
