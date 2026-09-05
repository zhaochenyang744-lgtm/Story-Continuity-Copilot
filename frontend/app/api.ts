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
    candidate_fields_invalid: "Provider 返回的事实候选字段不完整或包含未知字段；本轮未写入部分结果。",
    change_kind_invalid: "Provider 返回了不支持的事实变化类型；本轮未写入部分结果。",
    affected_memory_invalid: "事实变化未正确绑定原 Story Memory；本轮未写入部分结果。",
    affected_memory_unresolvable: "绑定的原 Story Memory 已无法解析；请基于当前版本重新运行。",
    invalidation_reason_invalid: "失效候选缺少可审计的失效理由；本轮未写入部分结果。",
    duplicate_candidate: "同一条原 Story Memory 被重复提出变化；本轮未写入部分结果。",
    candidate_conflict: "候选与当前事实相同或会产生重复事实；请修改决定后重试。",
    memory_delta_stale: "来源或 Story Memory 基线已变化；当前选择仍保留，请基于最新版本重新运行。",
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
    analysis_draft_empty: "当前草稿没有正文；保存正文后再检查计划偏离。",
    analysis_plan_unavailable: "尚无可对照的创作计划；请先在大纲中记录计划。",
    analysis_evidence_unavailable: "当前绑定版本没有可引用的上下文，未生成简报。",
    analysis_input_invalid: "分析输入无法验证；本轮未写入部分结果。",
    analysis_result_unresolvable: "分析结果来源无法解析，请基于当前版本重新生成。",
    character_alias_version_conflict: "角色别名已在其他窗口更新；当前输入仍保留，请载入最新别名版本后重试。",
    character_alias_duplicate: "该称呼与角色主名或现有使用中别名重复，请换一个称呼。",
    character_alias_limit_reached: "该角色已达到 20 个使用中别名的上限；请先归档不再使用的别名。",
    character_alias_archived: "该别名已经归档，不能继续修改或重复归档。",
    character_alias_invalid: "别名不能为空且最多 80 个字符，请修改后重试。",
    change_impact_proposal_invalid: "修改影响分析缺少完整提案；请明确填写拟修改内容后重试。",
    change_impact_target_invalid: "分析对象已不存在或不属于当前绑定资料，请重新选择对象。",
    run_already_active: "同一草稿已有一项分析正在运行；请等待完成或先取消当前运行。",
    story_qa_input_invalid: "问题或限定范围不完整；请至少选择一种依据并重新提问。",
    foreshadow_invalid: "伏笔标题、说明或状态不完整；请修改后重试。",
    foreshadow_reference_invalid: "关联的章节或正文来源已不存在；请重新选择来源。",
    foreshadow_duplicate: "已有同名的使用中伏笔记录；请更新原记录或更换标题。",
    foreshadow_version_conflict: "伏笔记录已在其他窗口更新；当前输入仍保留，请载入最新版本后重试。",
    foreshadow_version_limit: "伏笔记录版本已达到安全上限，未写入本次修改。",
    foreshadow_limit_reached: "当前作品已达到 200 条使用中伏笔记录的上限；请先归档不再使用的记录。",
    foreshadow_archived: "该伏笔记录已经归档，不能继续修改或重复归档。",
    foreshadow_candidate_unavailable: "伏笔扫描尚未完成，当前候选不能处理。",
    foreshadow_candidate_decided: "该 AI 候选已经完成作者决策，不能重复处理。",
    foreshadow_candidate_stale: "扫描依据或作者伏笔记录已变化；请基于当前版本重新扫描。",
    foreshadow_candidate_decision_invalid: "请选择接受、编辑后接受或拒绝；编辑后接受需要完整记录。",
    foreshadow_candidate_duplicate: "AI 返回了重复伏笔候选；本轮未写入任何候选。",
    revision_plan_issue_invalid: "请选择同一次当前连续性检查中的有效问题。",
    revision_plan_issue_stale: "所选问题已处理或草稿版本已变化；请基于当前保存稿重新检查。",
    revision_plan_evidence_unavailable: "所选问题没有可解析的充分依据，未生成修订建议。",
    revision_plan_candidate_count_invalid: "修订建议未逐项覆盖所选问题；本轮未写入任何候选。",
    revision_plan_candidate_invalid: "修订建议字段、优先级或问题绑定无效；本轮未写入任何候选。",
    revision_plan_candidate_duplicate: "AI 返回了重复修订建议；本轮未写入任何候选。",
    revision_candidate_unavailable: "修订建议尚未完成，当前不能处理。",
    revision_candidate_decided: "该修订建议已经完成作者决策，不能重复处理。",
    revision_candidate_stale: "修订建议的草稿、来源或问题依据已变化；请重新检查后生成。",
    revision_candidate_decision_invalid: "请选择接受、编辑后接受或拒绝；编辑后接受需要完整任务内容。",
    revision_task_invalid: "修订任务标题、行动说明或优先级不完整。",
    revision_task_duplicate: "已有同名的活动修订任务；请先完成原任务或修改建议标题。",
    revision_task_limit_reached: "当前作品已达到 200 条活动修订任务上限；请先完成现有任务。",
    revision_task_version_conflict: "修订任务已在其他窗口更新；请刷新后重试。",
    revision_task_version_limit: "修订任务版本已达到安全上限，本次没有写入。",
    revision_task_status_invalid: "请选择不同的有效任务进度。",
    project_archived: "作品已归档，只读浏览。请先恢复作品再执行此操作。",
    metadata_revision_unavailable: "作品信息暂不可更新，请稍后重试。",
    source_revision_conflict: "来源版本已变化；没有追加章节，请重新预览。",
    source_hash_mismatch: "预览内容校验不一致；没有追加章节，请重新预览。",
    source_change_set_expired: "追加预览已过期；没有追加章节，请重新预览。",
    empty_source: "追加内容为空，无法创建章节。",
    unsupported_format: "文件仅支持 UTF-8 的 .md 或 .txt。",
    tutorial_progress_unavailable: "教学进度暂时不可用，已保留当前界面并重新同步。",
    tutorial_progress_conflict: "教学进度已在其他窗口更新，已重新同步服务器记录。",
    tutorial_progress_target_invalid: "当前作品不是该账号的教学样例，未记录进度。",
    tutorial_unavailable: "当前账号没有可用的教学进度。",
    onboarding_progress_failed: "教学进度未能保存，已重新同步服务器记录。",
    profile_revision_conflict: "个人信息已在其他窗口更新，已载入最新版本；请确认后重试。",
    profile_update_not_allowed: "当前身份不支持修改个人信息。",
  };
  return labels[code] ?? "请求未完成。请保留当前内容并重试。";
};
