# 3–5 minute demo guide

This path demonstrates the local workflow using seeded data. It does not require a real provider call.

## 1. Enter the workspace

1. Open the local frontend and register or sign in.
2. Select **Grey Harbor Echoes** from the projects view.
3. Open the project overview to confirm that its outline, chapters, Story Memory, and current draft belong to the selected project.

## 2. Review a completed continuity check

1. Open the writing workspace for the seeded Grey Harbor draft.
2. Select a completed continuity review.
3. Open the Evidence view and trace each cited item back to its chapter and SourceSpan.

The review is useful only when its Evidence resolves inside the selected project. A missing or unresolvable citation is rejected by the API rather than shown as a grounded finding.

## 3. Make the author decision

1. Open the Memory update review.
2. Accept, reject, or edit proposed changes individually.
3. Confirm the ChangeSet.

The system records the decision. Only the accepted subset can update the versioned Story Memory, so the application does not turn a model response into canon by itself.

## 4. Show project isolation

1. Return to the projects view.
2. Open **Paper Moon Archive** or **Midnight Garden**.
3. Compare its title, story context, and workspace state with Grey Harbor.

Each account/project scope owns its own data. The demo uses three independent preloaded works rather than presenting a shared decorative dashboard.

## 5. Restore the seeded path

1. Return to Grey Harbor.
2. Choose Reset and read the confirmation state.
3. Confirm the reset and return to the workspace.

Reset is explicit and idempotent. It restores the seeded project review path while keeping the operation constrained to the current project runtime.

## Suggested narration

“This is a continuity-review workspace for a long-form project. The author checks a draft against versioned Story Memory, reads the supporting Evidence, and decides which proposed changes belong in canon. The system helps review consistency; it does not write the novel for the author.”
