export type User = { id: string; account_name: string; display_name: string };
export type ProjectSummary = {
  id: string;
  title: string;
  genre: string;
  summary: string;
  status: "active" | "paused" | "completed" | "archived";
  metadata_revision?: number;
  data_origin: string;
  current_memory_version: number;
  open_issue_count?: number;
  updated_at: string;
  current_draft?: { id: string; revision: number; chapter_number: number };
};
export type Project = ProjectSummary & {
  chapter_count: number;
  current_draft: { id: string; revision: number; chapter_number: number };
  latest_run: { run_id: string; status: string; created_at: string } | null;
  memory_initialization_status?: string;
};
export type Draft = {
  id: string;
  project_id: string;
  title: string;
  body: string;
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
  source_spans?: { span_id: string; label: string; text_excerpt: string }[];
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
  source: { chapter_id: string; span_id: string; excerpt: string } | null;
};
export type Issue = {
  id: string;
  status: string;
  category: string;
  severity: "high" | "medium" | "low";
  evidence_status: string;
  explanation: string;
  claim_span_id: string;
  claim_text?: string;
  decision?: { decision: string; resulting_revision: number | null } | null;
  evidence?: {
    id: string;
    chapter_id: string;
    span_id: string;
    excerpt: string;
    relation: string;
    sufficiency: string;
    related_memory_ids: string[];
  }[];
};
export type Run = {
  run_id: string;
  project_id: string;
  status: string;
  stage: string;
  source_revision: number;
  current_revision: number;
  is_stale: boolean;
  superseded: boolean;
  lineage_status: string;
  error_code: string | null;
  created_at: string;
  completed_at: string | null;
  issues?: Issue[];
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
