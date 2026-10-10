"use client";

import type { Issue } from "../../model";
import { findingTone, severityShort, toneLabel } from "../labels";
import { Tag } from "../ui";

/** One line for a finding: the first sentence of its explanation, kept short. */
export const findingHeadline = (issue: Pick<Issue, "explanation" | "claim_text">) => {
  const text = (issue.explanation || issue.claim_text || "").trim();
  const first = text.split(/(?<=[。！？])/)[0] ?? text;
  return first.length > 34 ? `${first.slice(0, 33)}…` : first;
};

/** 「确定矛盾 · 高」; with long, 「确定矛盾 · 高影响」 as on 写作. */
export function FindingTag({ issue, level = true, long = false }: { issue: Pick<Issue, "nature" | "severity">; level?: boolean; long?: boolean }) {
  const tone = findingTone(issue);
  return <Tag tone={tone}>{toneLabel[tone]}{level && tone !== "state" ? ` · ${severityShort[issue.severity]}${long ? "影响" : ""}` : ""}</Tag>;
}

export const openIssues = (issues: Issue[] | undefined, resolved: string[]) =>
  (issues ?? []).filter((issue) => !issue.decision && !issue.reused_decision && !resolved.includes(issue.id));
