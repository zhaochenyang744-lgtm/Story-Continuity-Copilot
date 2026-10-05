export const pendingDecisionSchemaVersion = 1;

export type PendingControlledDecision = {
  schema_version: typeof pendingDecisionSchemaVersion;
  userId: string;
  projectId: string;
  draftId: string;
  runId: string;
  issueId: string;
  sourceRevision: number;
  resultingRevision: number;
  decision: "accept_and_edit";
  idempotencyKey: string;
  createdAt: string;
};

export type StoppedPendingDecision = PendingControlledDecision & {
  stoppedAt: string;
  stopReason: "server_state_conflict";
  conflict: string;
};

type PendingDecisionIdentity = {
  userId: string;
  projectId: string;
  draftId: string;
};

export function pendingDecisionKey({ userId, projectId, draftId }: PendingDecisionIdentity) {
  return `story-continuity:pending-decision:v${pendingDecisionSchemaVersion}:${encodeURIComponent(userId)}:${encodeURIComponent(projectId)}:${encodeURIComponent(draftId)}`;
}

export function pendingDecisionConflictHistoryKey({ userId, projectId, draftId }: PendingDecisionIdentity) {
  return `story-continuity:pending-decision-conflicts:v${pendingDecisionSchemaVersion}:${encodeURIComponent(userId)}:${encodeURIComponent(projectId)}:${encodeURIComponent(draftId)}`;
}

function isPendingDecision(value: unknown): value is PendingControlledDecision {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    item.schema_version === pendingDecisionSchemaVersion &&
    typeof item.userId === "string" &&
    typeof item.projectId === "string" &&
    typeof item.draftId === "string" &&
    typeof item.runId === "string" &&
    typeof item.issueId === "string" &&
    Number.isInteger(item.sourceRevision) &&
    Number.isInteger(item.resultingRevision) &&
    item.decision === "accept_and_edit" &&
    typeof item.idempotencyKey === "string" &&
    item.idempotencyKey.length >= 16 &&
    typeof item.createdAt === "string"
  );
}

export function readPendingDecision(storage: Storage, identity: PendingDecisionIdentity) {
  const raw = storage.getItem(pendingDecisionKey(identity));
  if (!raw) return null;
  const parsed: unknown = JSON.parse(raw);
  if (!isPendingDecision(parsed)) return null;
  if (parsed.userId !== identity.userId || parsed.projectId !== identity.projectId || parsed.draftId !== identity.draftId) return null;
  return parsed;
}

export function writePendingDecision(storage: Storage, pending: PendingControlledDecision) {
  storage.setItem(pendingDecisionKey(pending), JSON.stringify(pending));
}

export function removePendingDecision(storage: Storage, identity: PendingDecisionIdentity) {
  storage.removeItem(pendingDecisionKey(identity));
}

export function stopPendingDecision(
  storage: Storage,
  pending: PendingControlledDecision,
  conflict: string,
) {
  const historyKey = pendingDecisionConflictHistoryKey(pending);
  const raw = storage.getItem(historyKey);
  const parsed: unknown = raw ? JSON.parse(raw) : [];
  if (!Array.isArray(parsed)) throw new Error("pending_decision_conflict_history_invalid");
  const stopped: StoppedPendingDecision = {
    ...pending,
    stoppedAt: new Date().toISOString(),
    stopReason: "server_state_conflict",
    conflict,
  };
  const history = parsed
    .filter((item): item is StoppedPendingDecision => Boolean(item && typeof item === "object"))
    .filter((item) => item.idempotencyKey !== pending.idempotencyKey);
  storage.setItem(historyKey, JSON.stringify([...history, stopped].slice(-20)));
  storage.removeItem(pendingDecisionKey(pending));
}
