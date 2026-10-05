import type { Draft, DraftBodyFormat } from "./model";

export const draftRecoverySchemaVersion = 1;

export type DraftRecoverySnapshot = {
  schema_version: typeof draftRecoverySchemaVersion;
  user_id: string;
  project_id: string;
  draft_id: string;
  base_revision: number;
  title: string;
  body: string;
  body_format?: DraftBodyFormat;
  updated_at: string;
};

type DraftRecoveryIdentity = {
  userId: string;
  projectId: string;
  draftId: string;
};

export function draftRecoveryKey({ userId, projectId, draftId }: DraftRecoveryIdentity) {
  return `story-continuity:draft:v${draftRecoverySchemaVersion}:${encodeURIComponent(userId)}:${encodeURIComponent(projectId)}:${encodeURIComponent(draftId)}`;
}

function isSnapshot(value: unknown): value is DraftRecoverySnapshot {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    item.schema_version === draftRecoverySchemaVersion &&
    typeof item.user_id === "string" &&
    typeof item.project_id === "string" &&
    typeof item.draft_id === "string" &&
    Number.isInteger(item.base_revision) &&
    typeof item.title === "string" &&
    typeof item.body === "string" &&
    (item.body_format === undefined || item.body_format === "plain_text" || item.body_format === "markdown") &&
    typeof item.updated_at === "string"
  );
}

export function readDraftRecovery(storage: Storage, identity: DraftRecoveryIdentity) {
  const raw = storage.getItem(draftRecoveryKey(identity));
  if (!raw) return null;
  const parsed: unknown = JSON.parse(raw);
  if (!isSnapshot(parsed)) return null;
  if (
    parsed.user_id !== identity.userId ||
    parsed.project_id !== identity.projectId ||
    parsed.draft_id !== identity.draftId
  ) return null;
  return parsed;
}

export function writeDraftRecovery(
  storage: Storage,
  identity: DraftRecoveryIdentity,
  draft: Draft,
  updatedAt = new Date().toISOString(),
) {
  const snapshot: DraftRecoverySnapshot = {
    schema_version: draftRecoverySchemaVersion,
    user_id: identity.userId,
    project_id: identity.projectId,
    draft_id: identity.draftId,
    base_revision: draft.revision,
    title: draft.title,
    body: draft.body,
    body_format: draft.body_format,
    updated_at: updatedAt,
  };
  storage.setItem(draftRecoveryKey(identity), JSON.stringify(snapshot));
  return snapshot;
}

export function removeDraftRecovery(storage: Storage, identity: DraftRecoveryIdentity) {
  storage.removeItem(draftRecoveryKey(identity));
}
