"use client";

// The wordmark and the author's badge.
import type { User } from "../model";

/** The first character of the name the author goes by (a Latin letter in capitals). */
export const initialOf = (user: Pick<User, "display_name" | "account_name">) => {
  const first = Array.from(user.display_name.trim() || user.account_name.trim())[0];
  return first ? first.toLocaleUpperCase() : "?";
};

export function Avatar({ user, className = "" }: { user: Pick<User, "display_name" | "account_name">; className?: string }) {
  return <span className={`avatar${className ? ` ${className}` : ""}`} aria-hidden="true">{initialOf(user)}</span>;
}

export function Wordmark() {
  return <span className="wordmark" aria-hidden="true">STORY<br />CONTINUITY</span>;
}
