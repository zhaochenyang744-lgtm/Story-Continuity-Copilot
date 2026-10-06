# Story Continuity Copilot v1.6.1 — 3–5 minute demo guide

This path demonstrates the workflow using seeded data, locally or on the public site. It does not require a real provider call.

## 1. Enter the workspace

1. Open the frontend and choose **访客体验 24 小时** (visitor mode). A visitor space holds three seeded works; a new registered account instead starts with a guided tutorial copy of Grey Harbor Echoes.
2. Select **Grey Harbor Echoes** (灰港回声) from the projects view.
3. Open the project overview to confirm that its outline, chapters, Story Memory, and current draft belong to the selected project.

## 2. Review a completed continuity check

1. Open the writing workspace for the seeded Grey Harbor draft.
2. Select a completed continuity review.
3. Open the Evidence view and trace each cited item back to its chapter and SourceSpan.

The review is useful only when its Evidence resolves inside the selected project. A missing or unresolvable citation is rejected by the API rather than shown as a grounded finding.

## 2b. Look at a multi-chapter check

1. Open **章节管理** for Grey Harbor Echoes.
2. Read the chapter timeline: every written chapter and the current draft, in order, with its check status.
3. Open the labelled sample report of a chapter check (chapters 9–10): findings are grouped by chapter and each one cites an earlier chapter. Registered authors can tick up to eight chapters and run such a check themselves; the estimate is shown before anything is spent.

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
2. Open **更多** and choose **重置当前作品** (Reset); read the confirmation dialog.
3. Choose **确认重置** and return to the workspace.

Reset is explicit and idempotent. It restores the seeded project review path while keeping the operation constrained to the current project runtime.

## Suggested narration

“This is a continuity-review workspace for a long-form project. The author checks a draft against versioned Story Memory, reads the supporting Evidence, and decides which proposed changes belong in canon. The system helps review consistency; it does not write the novel for the author.”
