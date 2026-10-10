"use client";

// The wordmark and the author portraits.
import Image from "next/image";
import type { User } from "../model";

export const avatarPresets: { id: User["avatar_preset"]; label: string; src: string }[] = [
  { id: "continuity_violet", label: "连续线", src: "/assets/avatars/continuity-violet.webp" },
  { id: "archive_blue", label: "档案蓝", src: "/assets/avatars/archive-blue.webp" },
  { id: "folio_rose", label: "书页玫", src: "/assets/avatars/folio-rose.webp" },
  { id: "signal_amber", label: "信号琥珀", src: "/assets/avatars/signal-amber.webp" },
];
export function Avatar({ user, className = "" }: { user: Pick<User, "avatar_preset">; className?: string }) {
  const src = avatarPresets.find((item) => item.id === user.avatar_preset)?.src ?? avatarPresets[0].src;
  return <span className={`avatar${className ? ` ${className}` : ""}`} aria-hidden="true"><Image src={src} alt="" width={512} height={512} sizes="96px" /></span>;
}

export function Wordmark() {
  return <span className="wordmark" aria-hidden="true">STORY<br />CONTINUITY</span>;
}
