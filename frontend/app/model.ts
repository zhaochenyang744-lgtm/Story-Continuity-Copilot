export type User = {
  id: string;
  account_name: string;
  display_name: string;
  avatar_preset: "continuity_violet" | "archive_blue" | "folio_rose" | "signal_amber";
  profile_revision: number;
  /** One line about the author, up to 60 characters; empty until they write it. */
  bio?: string;
  created_at?: string;
  /** When the password was last changed here or by a reset; null if it never was. */
  password_changed_at?: string | null;
  account_type?: "registered" | "visitor";
  visitor_expires_at?: string | null;
  recovery_email?: { configured: boolean; verified: boolean; masked: string | null };
  /** The assistant's roll-out for this account: whether it is offered at all, and whether it is still marked 测试版. */
  assistant?: { available: boolean; beta: boolean };
};
/** What the author's home page draws (GET /api/account/home). Days are Beijing-time days, already cut by the server. */
export type HomeEvent = {
  kind: "draft_saved" | "chapter_finished" | "checked" | "assistant_adopted" | "project_created";
  at: string;
  day: string;
  project_id: string;
  project_title: string;
  chapter_number: number | null;
  chapter_numbers: number[];
  chapter_title: string;
  /** draft_saved: the characters added (or cut) that day. */
  net_chars?: number;
  /** checked: how many findings the check made. */
  issue_count?: number;
  /** project_created: how the work came to be. */
  origin?: string;
};
export type AuthorHome = {
  today: string;
  day_utc_offset_hours: number;
  profile: { account_name: string; display_name: string; avatar_preset: User["avatar_preset"]; bio: string; created_at: string; account_type: "registered" | "visitor"; visitor_expires_at: string | null };
  totals: { works: number; chapters: number; chars: number; streak_days: number; streak_includes_today: boolean };
  calendar: { start: string; end: string; chars: number[]; levels: number[] };
  year: { chars: number; writing_days: number; best_day: { day: string; chars: number } | null; longest_streak: number; checked_chapters: number };
  current: { project_id: string; project_title: string; chapter_number: number; chapter_title: string; chars: number; saved_at: string; check_state: "unchecked" | "checked" | "edited" } | null;
  works: Pick<ProjectSummary, "id" | "title" | "genre" | "summary" | "status" | "data_origin" | "chapter_count" | "word_count" | "open_issue_count" | "continuity_status" | "updated_at">[];
  activity: HomeEvent[];
};
export type DailyUsage = {
  today: string;
  days: { day: string; check_chars: number; assistant_chars: number }[];
  /** The oldest charge still counting against the last 24 hours, and when it comes back. */
  oldest_charge: { recovers_at: string; chars: number } | null;
};
export type ProjectSummary = {
  id: string;
  title: string;
  genre: string;
  summary: string;
  status: "active" | "paused" | "completed" | "archived";
  metadata_revision?: number;
  data_origin: string;
  current_memory_version: number;
  author_context_version?: number;
  foreshadow_version?: number;
  source_revision?: number;
  chapter_count?: number;
  word_count?: number;
  /** Characters in the written chapters only (word_count also counts the draft). */
  chapter_word_count?: number;
  open_issue_count?: number;
  continuity_status?: "unchecked" | "checked_clear" | "pending";
  updated_at: string;
  current_draft?: { id: string; revision: number; chapter_number: number };
};
export type AuthorStoryPlan = {
  id: string;
  title: string;
  summary: string;
  goal: string;
  position: number;
  status: "planned" | "in_progress" | "paused" | "completed";
  target_chapter_number: number | null;
  archived_at: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
};
export type AuthorCharacterPlan = {
  id: string;
  name: string;
  role_type: "protagonist" | "ally" | "antagonist" | "supporting" | "other";
  goal: string;
  planned_state: string;
  notes: string;
  position: number;
  archived_at: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
};
export type AuthorWorldPlan = {
  id: string;
  name: string;
  category: "location" | "organization" | "rule" | "object" | "term" | "other";
  description: string;
  notes: string;
  position: number;
  archived_at: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
};
export type AuthorContext = {
  project_id: string;
  author_context_version: number;
  version: number;
  parent_version: number | null;
  snapshot_digest: string;
  story_plans: AuthorStoryPlan[];
  character_plans: AuthorCharacterPlan[];
  world_plans: AuthorWorldPlan[];
};
export type Project = ProjectSummary & {
  chapter_count: number;
  current_draft: { id: string; revision: number; chapter_number: number };
  latest_run: { run_id: string; status: string; created_at: string; result_origin: "provider" | "demo_preset" } | null;
  memory_initialization_status?: string;
  is_tutorial?: boolean;
};
export type TutorialEvent =
  | "memory_source_opened"
  | "continuity_issue_located"
  | "evidence_opened"
  | "author_decision_recorded"
  | "author_decision_reviewed";
export type TutorialProgress = {
  tutorial_version: "1.2.0";
  tutorial_project_id: string;
  current_step: 1 | 2 | 3 | 4 | 5;
  completed_events: TutorialEvent[];
  revision: number;
  updated_at: string;
};
export type Onboarding = {
  status: "active" | "completed" | "skipped";
  real_project_count: number;
  show_first_run: boolean;
  completed_at?: string | null;
  tutorial: { project_id: string; title: string; status?: ProjectSummary["status"]; data_origin: "tutorial_seed" } | null;
  progress: TutorialProgress | null;
};
export type DraftBodyFormat = "plain_text" | "markdown";
export type Draft = {
  id: string;
  project_id: string;
  title: string;
  body: string;
  body_format: DraftBodyFormat;
  chapter_number: number;
  revision: number;
  saved_at: string;
  status: string;
};
export type Chapter = {
  id: string;
  number: number;
  title: string;
  summary: string;
  source_spans?: { span_id: string; label: string; source_revision?: number; text_excerpt: string; is_current?: boolean }[];
};
export type Memory = {
  id: string;
  memory_type: string;
  subject: string;
  predicate: string;
  value: string;
  valid_from: number | null;
  valid_to: number | null;
  review_status: string;
  requires_source_review?: boolean;
  source_is_current?: boolean;
  source: { chapter_id: string; chapter_number: number; chapter_title: string; span_id: string; excerpt: string; source_path: string } | null;
};
export type MemoryInitialization = {
  id?: string;
  project_id: string;
  status: "required" | "draft" | "committed" | "rejected";
  source_revision: number;
  provider_label?: string;
  error_code?: string | null;
  coverage?: MemoryCoverage;
  candidates: {
    id: string;
    memory_type: string;
    subject: string;
    predicate: string;
    value: string;
    candidate_origin: "initialization" | "delta";
    review_priority: "core" | "supporting";
    decision_status: "pending" | "accepted" | "rejected" | "edited";
    decision?: { decision: string; after: Record<string, string> | null; evidence_span_id?: string | null } | null;
    review_history: {
      id: string;
      event: "decided" | "reopened";
      decision: "accepted" | "rejected" | "edited";
      snapshot: { decision: string; after: Record<string, string> | null; evidence_span_id?: string | null };
      source_revision: number;
      created_at: string;
    }[];
    source_revision: number;
    source: {
      chapter_id: string;
      chapter_number: number;
      chapter_title: string;
      span_id: string;
      label: string;
      excerpt: string;
      text: string;
      source_path: string;
    };
  }[];
};
export type MemoryCoverage = {
  project_id: string;
  status: "required" | "in_review" | "ready_partial" | "ready_current" | "update_pending";
  source_revision: number;
  memory_version: number;
  counts: { core_pending: number; supporting_pending: number; confirmed: number; confirmed_core: number; pending_canon_count: 0 };
  blocking_reason: "none" | "core_review_required" | "no_confirmed_core" | "delta_review_required";
};
export type Issue = {
  id: string;
  review_contract_version: "legacy_v3" | "trustworthy_review_v1";
  status: string;
  category: string;
  severity: "high" | "medium" | "low";
  evidence_status: string;
  explanation: string;
  nature?:
    | "confirmed_conflict"
    | "possible_conflict"
    | "state_change"
    | "insufficient_evidence"
    | string;
  reasoning?: string;
  evidence_chain?: { evidence_id: string; role: "prior_state" | "current_context" | "missing_link" }[];
  suggested_revision?: { before: string; after: string } | null;
  available_actions?: (
    | "edit"
    | "apply_suggestion"
    | "keep_intentional"
    | "false_positive"
    | "propose_fact"
  )[];
  claim_span_id: string;
  claim_text?: string;
  reused_decision?: { decision: string; status: string; source_issue_id: string; review_path: string; requires_new_decision: boolean } | null;
  /** v1.7.0 「待修改」: the author noted that the prose still needs a change for this finding. */
  to_revise?: boolean;
  decision?: { decision: string; resulting_revision: number | null; reused?: boolean } | null;
  /** The check proposed a change to the project facts for this finding (kept as an intentional change, it goes to fact review). */
  has_memory_proposal?: boolean;
  evidence?: {
    id: string;
    chapter_id: string;
    chapter_number: number;
    chapter_title: string;
    span_id: string;
    source_revision: number;
    excerpt: string;
    excerpt_context: string;
    source_path: string;
    relation: string;
    sufficiency: string;
    related_memory_ids: string[];
  }[];
};
export type Run = {
  run_id: string;
  project_id: string;
  /** The draft the check was run on; absent on older backends. */
  draft_id?: string | null;
  run_type: "continuity" | "memory_delta";
  status: "queued" | "running" | "completed" | "timed_out" | "failed" | "cancelled";
  stage: string;
  source_revision: number;
  source_memory_version?: number;
  source_change_set_id?: string | null;
  source_span_ids?: string[];
  incremental_batch_id?: string | null;
  current_revision: number;
  is_stale: boolean;
  superseded: boolean;
  lineage_status: string;
  result_origin: "provider" | "demo_preset";
  result_origin_label: string;
  error_code: string | null;
  retryable: boolean;
  created_at: string;
  started_at?: string | null;
  completed_at: string | null;
  cancel_requested_at?: string | null;
  duration_ms?: number | null;
  retry_of_run_id?: string | null;
  root_run_id?: string;
  attempt_number?: number;
  transitions?: { sequence: number; status: string; stage: string; error_code: string | null; created_at: string }[];
  provenance?: { provider_label: string; model_label: string; prompt_version: string; schema_version: string; retrieval_method_version: string; source_memory_version: number; source_change_set_id?: string; source_span_ids?: string[]; incremental_batch_id?: string };
  provider_metrics?: { latency_ms: number | null; input_tokens: number | null; output_tokens: number | null; cost_cny: number | null; cost_available: boolean };
  metrics?: { latency_ms: number | null; input_tokens: number | null; output_tokens: number | null; cost_cny: number | null; cost_available: boolean; provenance: Run["provenance"]; retrieval: { claim_ordinal: number | null; returned_span_ids: string[]; method_version: string }[];
    // Absent on older backends: treat a missing count as "nothing to report", never as "complete".
    undecided_claim_count?: number; undecided_claims?: { claim_span_id: string; error_code: string }[] };
  issues?: Issue[];
};
export type AnalysisSource = {
  source_type: "author_context" | "memory_record" | "source_span" | "draft_claim" | "character_record" | "character_alias" | "world_record" | "issue_evidence";
  source_id: string;
  label: string;
  excerpt: string;
  source_path?: string;
};
export type ForeshadowReference = {
  chapter_id: string;
  chapter_number: number;
  chapter_title: string;
  source_span_id: string | null;
  source_label: string | null;
  source_path: string;
};
export type ForeshadowRecord = {
  id: string;
  project_id: string;
  title: string;
  description: string;
  status: "planned" | "planted" | "developing" | "resolved" | "abandoned";
  version: number;
  planted: ForeshadowReference | null;
  resolved: ForeshadowReference | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};
export type ForeshadowSnapshot = { project_id:string; foreshadow_version:number; records:ForeshadowRecord[]; item?:ForeshadowRecord };
export type ForeshadowCandidate = {
  id: string;
  title: string;
  description: string;
  suggested_status: "planted" | "developing" | "resolved";
  planted_chapter_id: string | null;
  planted_source_span_id: string | null;
  resolved_chapter_id: string | null;
  resolved_source_span_id: string | null;
  evidence: (AnalysisSource & { relation:"planted"|"developing"|"resolved" })[];
  decision_status: "pending" | "accepted" | "edited" | "rejected";
  decision: { decision:string; created_record_id:string|null; after:ForeshadowRecord|null } | null;
  decided_at?: string | null;
};
export type WritingAnalysisRun = {
  run_id: string;
  project_id: string;
  run_type: "plan_alignment" | "change_impact" | "story_qa" | "foreshadow_scan";
  analysis_type: "plan_alignment" | "change_impact" | "story_qa" | "foreshadow_scan";
  status: "queued" | "running" | "completed" | "timed_out" | "failed" | "cancelled";
  stage: string;
  draft_revision: number;
  current_draft_revision?: number;
  source_revision: number;
  source_memory_version: number;
  author_context_version: number;
  author_context_snapshot_digest?: string | null;
  alias_version?: number | null;
  alias_snapshot_digest?: string | null;
  foreshadow_version?: number | null;
  foreshadow_snapshot_digest?: string | null;
  proposal?: { target_type: "chapter" | "character" | "world" | "memory" | "plan" | "general"; target_id?: string | null; proposed_change: string } | null;
  question?: string | null;
  scope?: ("confirmed"|"written"|"planned")[] | null;
  issue_ids?: string[] | null;
  source_run_id?: string | null;
  is_stale: boolean;
  lineage_status: string;
  error_code: string | null;
  retryable: boolean;
  attempt_number?: number;
  created_at: string;
  completed_at?: string | null;
  retrieval?: {
    method_version: string;
    selected_ids: Record<string, string[]>;
    counts: Record<string, { available: number; selected: number }>;
    truncated: Record<string, boolean>;
      target_source?: { memory_id: string; source_span_id: string | null; status: "selected" | "unlocated" | "missing"; source_revision: number | null; original_chars: number | null; excerpt_chars: number | null; excerpt_truncated: boolean };
      draft_claim_scope?: { body_chars: number; excerpt_chars: number; available: number; selected: { id: string; source_start: number; source_end: number; supplied_end: number; source_chars: number; supplied_chars: number; truncated: boolean }[] };
  };
  analysis?: {
    summary: string;
    evidence_status?: "supported" | "partial" | "insufficient";
    draft_coverage?: { status: "covered" | "partial" | "empty"; source_ids: string[]; cited_ranges?: { id: string; source_start: number; source_end: number; supplied_end: number; source_chars: number; supplied_chars: number; truncated: boolean }[]; uncovered_source_ids?: string[]; unselected_count?: number; discarded_item_indices?: number[]; reasons: string[] };
    summary_sources?: AnalysisSource[];
    proposal?: { target_type: "chapter" | "character" | "world" | "memory" | "plan" | "general"; target_id?: string | null; proposed_change: string };
    items: ({ section: "related_plan" | "confirmed_fact" | "character_state" | "world_rule" | "open_thread" | "recent_source"; text: string; sources: AnalysisSource[] } | { story_plan_id: string; story_plan_title: string; status: "planned_covered" | "planned_missing" | "planned_early" | "planned_changed" | "insufficient_evidence"; explanation: string; plan_source: AnalysisSource; evidence: AnalysisSource[] } | { area: "chapter" | "character" | "world" | "memory" | "plan"; target_id: string; label: string; impact: string; evidence: AnalysisSource[] })[];
    answer_status?: "answered"|"partial"|"insufficient"|"conflicting";
    answer?: string;
    question?: string;
    scope?: ("confirmed"|"written"|"planned")[];
    findings?: { layer:"confirmed"|"written"|"planned"; stance:"supports"|"contradicts"|"context"; text:string; evidence:AnalysisSource[] }[];
    candidates?: ForeshadowCandidate[];
  };
};
export type CharacterAliasSnapshot = {
  project_id: string;
  character_id: string;
  primary_name: string;
  version: number;
  updated_at: string | null;
  changed_alias_id?: string;
  aliases: { id: string; alias: string; status: "active" | "archived"; created_at: string; updated_at: string; archived_at: string | null }[];
};
export type MemoryDelta = {
  id?: string;
  project_id: string;
  source_revision?: number;
  base_memory_version?: number;
  status: string;
  error_code?: string | null;
  continuity_run_id?: string;
  memory_delta_run_id?: string;
  coverage?: MemoryCoverage;
  coverage_audit?: {
    id: string;
    project_id: string;
    source_revision: number;
    status: string;
    memory_version: number;
    delta_batch_id: string;
    actor_user_id: string | null;
    details: { candidate_ids?: string[]; decisions?: { candidate_id: string; change_kind: "new_fact" | "changed_fact" | "invalidated_fact"; affected_memory_id: string | null; decision: string; before: Memory | null; after: Record<string, string> | null; invalidation_reason: string | null; evidence_span_id: string | null }[] };
    created_at: string;
  } | null;
  retrieval?: {
    method_version?: string;
    selected_source_span_ids?: string[];
    selected_memory_ids?: string[];
    counts?: { source_spans?: { available: number; selected: number }; confirmed_memory?: { available: number; selected: number } };
    truncated?: { source_spans: boolean; confirmed_memory: boolean };
  };
  change_set?: {
    id: string;
    change_set_kind: "memory_delta";
    status: "committed" | "rejected";
    base_memory_version: number;
    target_memory_version: number;
    source_revision: number;
    run_id: string;
    batch_id: string;
    actor_user_id: string | null;
    created_at: string;
    committed_at: string | null;
    items: { id: string; operation: "add" | "replace" | "retire"; before: Memory | null; after: Record<string, unknown>; source_ids: string[]; decision_ids: string[]; review_status: string; committed_after: Record<string, unknown> | null }[];
  } | null;
  candidates: {
    id: string;
    change_kind: "new_fact" | "changed_fact" | "invalidated_fact";
    affected_memory_id: string | null;
    invalidation_reason: string | null;
    memory_type: string;
    subject: string;
    predicate: string;
    value: string;
    before: Memory | null;
    after: { memory_type: string; subject: string; predicate: string; value: string } | null;
    candidate_origin: "delta";
    review_priority: "core" | "supporting";
    decision_status: "pending" | "accepted" | "rejected" | "edited";
    decision?: { decision: string; change_kind: string; affected_memory_id: string | null; after: Record<string, string> | null; invalidation_reason: string | null; evidence_span_id: string | null } | null;
    source_revision: number;
    source: { chapter_id: string; chapter_number: number; chapter_title: string; span_id: string; label: string; excerpt: string; source_path: string };
  }[];
};
export type ChangeSet = {
  id: string;
  status: string;
  base_memory_version: number;
  target_memory_version: number;
  source_run_revision: number;
  resolved_revision: number;
  items: {
    id: string;
    operation: string;
    before: Record<string, unknown> | null;
    after: Record<string, unknown>;
    source_ids: string[];
    decision_ids: string[];
  }[];
};
export type SourceChangeSet = { id:string; project_id:string; base_source_revision:number; target_source_revision:number; mode:"append"; input_method:"draft_complete"|"paste"|"file"; content_sha256:string; status:"previewed"|"committed"|"failed"; chapter_count:number; source_span_count:number; chapters:{preview_id:string;title:string;order:number;character_count:number}[]; previewed_at:string; committed_at:string|null; failed_at:string|null; failure_code:string|null; expires_at:string; audit:{created_by_user_id:string;idempotency_key_fingerprint:string;request_fingerprint:string;file_basename:string|null} };

// The built-in assistant (v1.8.0): what GET/POST /projects/{id}/assistant/tasks answer with.
export type AssistantPage = "writing" | "chapters" | "materials" | "plan" | "overview";
/** The uses the input box can tell apart (`POST /assistant/route`), and what it answers. */
export type AssistantRoute = "ask" | "fix_issue" | "recap" | "check_passage" | "change" | "out_of_scope";
export type AssistantRouting = { route: AssistantRoute; source: "rule" | "model"; unsure: boolean };
export type AssistantContextInput = { page: AssistantPage; chapter_number?: number; selection?: string; character_id?: string; issue_id?: string; intent?: "check_selection" };
/** `say` is the model's one line before it works; `tool` an action (grouped with the others of its round in `group`); `repair` a re-written
    answer; `protocol_error` a reminder nobody needs to read. `refs` are the passages a step turned up, cited or not; a failed step has `error_*`. */
export type AssistantStep = {
  round: number;
  kind: "say" | "tool" | "repair" | "protocol_error" | string;
  tool: string | null;
  summary: string;
  result_count: number | null;
  group: string | null;
  refs: string[];
  error_code: string | null;
  error_text: string | null;
};
/** Every passage the task registered; `cited` says the answer rests on it. */
export type AssistantSource = {
  kind: string;
  chapter_number: number | null;
  chapter_title: string | null;
  start: number | null;
  end: number | null;
  text: string;
  cited: boolean;
  /** Facts only: the passage the fact was taken from (its first 120 characters) and that passage's chapter; null when it has none. */
  anchor?: { text: string; chapter_number: number } | null;
};
export type AssistantAnswer = { status: "answered" | "not_found" | "inconsistent" | "out_of_scope"; sentences: { text: string; refs: string[] }[]; note?: string | null };
export type AssistantFeedbackReason = "wrong" | "verbose" | "not_found" | "bad_source";
/** The signed-in author's own verdict on a task. */
export type AssistantFeedback = { verdict: "up" | "down"; reasons: AssistantFeedbackReason[] } | null;
/** 写前回顾: four columns, each item one sentence and the numbers of the passages it rests on. */
export type RecapSection = "previous_ending" | "character_state" | "open_threads" | "plan";
export type RecapAnswer = { kind: "recap"; chapter_number: number; sections: Record<RecapSection, { summary: string; refs: string[] }[]> };
/** 帮我改这一处: one way to deal with a finding. before/after are empty for `intentional`; add_setup names an earlier chapter. */
export type AssistantProposalKind = "edit_this" | "add_setup" | "intentional";
export type RecheckIssue = {
  sentence: string;
  category: string;
  nature: string;
  severity: "high" | "medium" | "low";
  explanation: string;
  evidence: { ref: string; chapter: number | null; chapter_title: string | null; text: string }[];
};
export type ProposalRecheck =
  | { status: "running"; started_at?: string }
  | { status: "clean"; issues: RecheckIssue[] }
  | { status: "issues"; issues: RecheckIssue[] }
  | { status: "failed"; error_code: string };
export type AssistantProposal = {
  id: string;
  proposal: string;
  kind: AssistantProposalKind;
  chapter_number: number | null;
  before: string;
  after: string;
  rationale: string;
  status: "proposed" | "adopted" | "dismissed";
  /** The author's own wording when they changed `after` before adopting (the effective sentence is `after_edited ?? after`). */
  after_edited?: string | null;
  edited_by_author?: boolean;
  draft_id: string;
  draft_revision: number;
  adopted_draft_revision: number | null;
  decided_at: string | null;
  /** When the adoption was last undone (null while it stands, and after it was adopted again). */
  undone_at?: string | null;
  recheck: ProposalRecheck | null;
};
/** 改资料 (v2.0): one item of a change card, and of the ledger of what the assistant changed. `before` and `after` are already words. */
export type AssistantChangeKind = "resolve_thread" | "change_fact" | "add_fact" | "add_thread" | "edit_thread" | "abandon_thread";
export type AssistantChange = {
  /** Only in the ledger, where changes and adoptions are listed together. */
  entry?: "change";
  id: string;
  label: string;
  task_id: string;
  kind: AssistantChangeKind;
  /** A thread by its id; a fact by its lasting id and the record it is now (null when it is not in the current version). */
  target: { kind: "foreshadow"; id: string } | { kind: "fact"; id: string; record_id: string | null };
  title: string;
  before: string;
  after: string;
  editable: boolean;
  /** Only an item the author may reword (a fact, a thread's note): the wording they may change before confirming. */
  value: string | null;
  /** How risky the kind of change is; a batch confirm will set the high ones apart. Not shown yet. */
  risk: "low" | "high";
  /** False when the change may stand on the author's words alone, so `evidence` can be empty. */
  evidence_required: boolean;
  evidence: { chapter_number: number; chapter_title: string | null; start: number | null; end: number | null; text: string }[];
  /** A few words of the author's own sentence that name the record the change is about (null on an item made before they were asked for). */
  request_words: string | null;
  status: "proposed" | "applied" | "rejected" | "undone";
  edited_by_author: boolean;
  /** The materials no longer hold what this item expects, so a confirm or a plain undo would be refused (null for a rejected item). */
  changed_since: boolean | null;
  created_at: string;
  decided_at: string | null;
  applied_at: string | null;
  undone_at: string | null;
};
/** 改动记录 (v2.1): a proposal of a fix_issue task that the author adopted (or adopted and then undid), listed beside the changes. Undoing an adoption
    only records it; the draft is not touched. `after` is the sentence adopted, the author's own wording when they reworded it. */
export type AssistantAdoption = {
  entry: "adoption";
  id: string;
  label: string;
  task_id: string;
  kind: "edit_this" | "add_setup";
  chapter_number: number | null;
  before: string;
  after: string;
  edited_by_author: boolean;
  status: "adopted" | "undone";
  adopted_at: string | null;
  undone_at: string | null;
};
export type LedgerEntry = AssistantChange | AssistantAdoption;
export type AssistantTask = {
  id: string;
  kind: "ask" | "recap" | "fix_issue" | "change";
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  /** Null for a 写前回顾, and for a 帮我改这一处 asked without a request. */
  question: string | null;
  context: Partial<AssistantContextInput>;
  follow_up_of: string | null;
  /** How many follow-ups lie behind this task: 0 for a question of its own, 2 for the last one a chain allows. */
  follow_up_depth?: number;
  /** Set when the input box chose the use itself ("自动"): by what, and the author's sentence it was chosen for. */
  routed?: boolean;
  route_source?: "rule" | "model" | "manual" | null;
  routed_input?: string | null;
  /** The task this one answers again, and the question this one is an edit of. */
  regenerated_from?: string | null;
  edited_from?: string | null;
  steps: AssistantStep[];
  answer: AssistantAnswer | RecapAnswer | null;
  sources: Record<string, AssistantSource>;
  /** The fixed reply of an `out_of_scope` answer. */
  out_of_scope_text?: string | null;
  coverage: { checked: string[]; not_checked: string[] } | null;
  usage: { steps: number; chars_charged: number };
  /** While running: `thinking` (waiting for the model) or `tool` (running `phase_tool`, on `phase_chapter` for a chapter), since `phase_started_at`. */
  phase?: "thinking" | "tool" | null;
  phase_tool?: string | null;
  phase_chapter?: number | null;
  phase_started_at?: string | null;
  feedback?: AssistantFeedback;
  error_code: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at: string | null;
  /** Only on a fix_issue task. */
  proposals?: AssistantProposal[];
  /** Only on a change task: the card, in order. */
  changes?: AssistantChange[];
};
