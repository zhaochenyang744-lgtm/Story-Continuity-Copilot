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
    recovery_email_required: "请提供用于密码找回的恢复邮箱。",
    recovery_email_invalid: "恢复邮箱格式无效。",
    recovery_email_unavailable: "该恢复邮箱已绑定其他账号。",
    recovery_email_mismatch: "输入的邮箱与当前绑定邮箱不一致。",
    recovery_delivery_failed: "安全邮件暂时无法发送；未留下可用 token，请稍后重试。",
    recovery_rate_limited: "安全请求过于频繁，请稍后再试。",
    recovery_token_invalid: "安全链接无效、已过期或已使用，请重新发起。",
    password_policy_failed: "密码至少 10 个字符，且不能全部相同。",
    visitor_expired: "访客空间已过期，请创建新的访客空间或注册账号。",
    workflow_quota_exceeded: "过去 24 小时的 AI workflow 次数已用完；本轮未调用 Provider。",
    provider_attempt_quota_exceeded: "过去 24 小时的 Provider attempt 次数已用完；本轮未继续调用 Provider。",
    server_budget_exceeded: "服务器预算上限已到；本轮未调用 Provider。",
    budget_rates_unavailable: "服务器预算费率未配置，AI 功能已安全关闭。",
    import_too_large: "文件超过当前身份的服务器导入上限，未写入任何内容。",
    draft_too_large: "单次草稿最多 30,000 个 Unicode 字符。",
    provider_unavailable:
      "本地 provider 不可用。本轮没有生成替代 Issue，可在恢复后重新检查。",
    provider_timeout: "Provider 响应超时；本轮未写入部分结果，可以安全重试。",
    schema_invalid: "Provider 结果未通过结构校验；本轮未写入部分结果。",
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
    author_cancelled: "本轮已由作者取消，任何迟到结果都会被丢弃，未写入部分结果。",
    budget_guard_exceeded: "本轮被预算守卫安全停止，未写入部分结果。",
    internal_run_error: "运行遇到内部安全失败；未写入部分结果，可以重试。",
    run_retry_lineage_stale: "原 Run 的草稿、来源或 Memory 谱系已过期，请基于当前版本重新运行检查。",
    run_retry_not_allowed: "当前 Run 状态不允许重试。",
    run_cancel_terminal: "Run 已进入不可变终态，不能再次取消。",
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
