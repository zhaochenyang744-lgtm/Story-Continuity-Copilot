"use client";

import { FormEvent, KeyboardEvent, ReactNode, useEffect, useId, useRef, useState } from "react";
import { json, labelError, request, type ApiFailure } from "../../api";
import type { DailyUsage, User } from "../../model";
import { momentDayLabel, monthDayLabel, shortDay, untilLabel } from "../day";
import { Avatar } from "../identity";
import { type FontSize, setFontSize, setThemeMode, type ThemeMode, usePrefs } from "../prefs";
import { Button, type CheckUsage, formatCount, Tag } from "../ui";

export const settingsItems = [
  ["general", "通用"],
  ["account", "账号"],
  ["usage", "用量"],
  ["data", "数据"],
] as const;
export type SettingsItem = (typeof settingsItems)[number][0];
export const isSettingsItem = (value: string): value is SettingsItem => settingsItems.some(([id]) => id === value);
/** The addresses of the five items before v1.8.1, and where each one is now. */
export const settingsAliases: Record<string, SettingsItem> = { profile: "general", preferences: "general", security: "account" };

const BIO_MAX = 60;
/** Characters as the author counts them (an emoji or a rare character is one). */
const length = (text: string) => Array.from(text).length;

/** A row of a settings group: what it is (and a line on it) on the left, the control on the right. */
function Row({ name, hint, children, wide = false, top = false, danger = false }: { name: string; hint?: ReactNode; children?: ReactNode; wide?: boolean; top?: boolean; danger?: boolean }) {
  return (
    <div className={`row${wide ? " wide" : ""}${top ? " top" : ""}${danger ? " danger" : ""}`}>
      <div className="row-text">
        <span className="k">{name}</span>
        {hint && <span className="d">{hint}</span>}
      </div>
      {children !== undefined && <div className="row-ctl">{children}</div>}
    </div>
  );
}

function Group({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  const id = useId();
  return (
    <section className="group" aria-labelledby={id}>
      <div className="group-h"><h3 id={id}>{title}</h3>{note && <span>{note}</span>}</div>
      {children}
    </section>
  );
}

function PaneHead({ title, lede }: { title: string; lede?: string }) {
  return <div className="pane-head"><h2>{title}</h2>{lede && <p className="lede">{lede}</p>}</div>;
}

type ProfileField = "display_name" | "bio";

/** 个人资料: the name and the one-line introduction. Each saves itself when the author leaves the box. */
function ProfileGroup({ user, updateUser, setDirty }: { user: User; updateUser: (user: User) => void; setDirty: (dirty: boolean) => void }) {
  const [name, setName] = useState(user.display_name);
  const [bio, setBio] = useState(user.bio ?? "");
  const [saving, setSaving] = useState<ProfileField | null>(null);
  const [saved, setSaved] = useState<ProfileField | null>(null);
  const [error, setError] = useState<{ field: ProfileField; text: string } | null>(null);
  // Saves run one after another, each on the revision the one before returned.
  const latest = useRef(user);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { latest.current = user; }, [user]);
  const changed = name.trim() !== user.display_name || bio.trim() !== (user.bio ?? "");
  // Only a change that could not be saved holds the author back when they leave.
  useEffect(() => { setDirty(changed && error !== null); }, [changed, error, setDirty]);
  useEffect(() => {
    if (!changed) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [changed]);
  const save = (field: ProfileField) => {
    const value = (field === "display_name" ? name : bio).trim();
    if (value === (field === "display_name" ? latest.current.display_name : latest.current.bio ?? "")) {
      if (error?.field === field) setError(null);
      return;
    }
    if (field === "display_name" && !value) { setError({ field, text: "名字不能是空的。" }); return; }
    if (field === "bio" && length(value) > BIO_MAX) { setError({ field, text: `简介最多 ${BIO_MAX} 个字。` }); return; }
    queue.current = queue.current.then(async () => {
      const base = latest.current;
      if (mounted.current) { setSaving(field); setSaved(null); setError(null); }
      try {
        const body = { base_profile_revision: base.profile_revision, display_name: base.display_name, avatar_preset: base.avatar_preset, bio: base.bio ?? "", [field]: value };
        const data = await json<{ user: User }>("/auth/profile", "PATCH", body);
        latest.current = data.user;
        updateUser(data.user);
        if (!mounted.current) return;
        if (field === "display_name") setName(data.user.display_name); else setBio(data.user.bio ?? "");
        setSaved(field);
      } catch (cause) {
        if ((cause as ApiFailure).code === "profile_revision_conflict") {
          try { const fresh = (await request<{ user: User }>("/auth/session")).user; latest.current = fresh; updateUser(fresh); } catch { /* keep the author's text */ }
        }
        if (mounted.current) setError({ field, text: labelError(cause) });
      } finally { if (mounted.current) setSaving(null); }
    });
  };
  const status = (field: ProfileField) => saving === field ? <span className="save-state" role="status">正在保存…</span>
    : error?.field === field ? <span className="save-state bad" role="alert">{error.text}</span>
      : saved === field ? <span className="save-state ok" role="status">已保存</span> : null;
  const commitOnEnter = (event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.blur(); }
  };
  return (
    <Group title="个人资料" note="显示在你的作者主页上，只有你自己看得到">
      <Row name="头像" hint="用显示名称的第一个字">
        <Avatar user={{ display_name: name.trim() || user.display_name, account_name: user.account_name }} className="avatar-md" />
      </Row>
      <Row name="显示名称" hint={status("display_name") ?? "显示在作者主页和右上角"} wide>
        <input aria-label="显示名称" value={name} onChange={(event) => { setName(event.target.value); setSaved(null); }} onBlur={() => save("display_name")} onKeyDown={commitOnEnter} maxLength={60} autoComplete="nickname" aria-invalid={error?.field === "display_name" || undefined} />
      </Row>
      <Row name="简介" hint={status("bio") ?? "一句话介绍自己"} wide top>
        <textarea aria-label="简介" className="bio-input" value={bio} onChange={(event) => { setBio(event.target.value.replace(/[\r\n]+/g, " ")); setSaved(null); }} onBlur={() => save("bio")} onKeyDown={commitOnEnter} rows={2} aria-describedby="bio-count" aria-invalid={error?.field === "bio" || undefined} />
        <span id="bio-count" className="char-count" aria-live="polite"><span className={length(bio) > BIO_MAX ? "over" : undefined}>{length(bio)}</span> / {BIO_MAX}</span>
      </Row>
    </Group>
  );
}

function Segmented<T extends string>({ label, value, items, onChange }: { label: string; value: T; items: readonly (readonly [T, string])[]; onChange: (next: T) => void }) {
  return (
    <span className="seg" role="group" aria-label={label}>
      {items.map(([id, text]) => <button key={id} type="button" aria-pressed={value === id} onClick={() => onChange(id)}>{text}</button>)}
    </span>
  );
}

const themeItems: readonly (readonly [ThemeMode, string])[] = [["day", "浅色"], ["night", "深色"], ["system", "跟随系统"]];
const sizeItems: readonly (readonly [FontSize, string])[] = [["small", "小"], ["medium", "中"], ["large", "大"]];

/** 通用: the profile, and how the pages look on this device. */
function GeneralPane({ user, updateUser, setDirty }: { user: User; updateUser: (user: User) => void; setDirty: (dirty: boolean) => void }) {
  const { mode, fontSize } = usePrefs();
  return (
    <>
      <PaneHead title="通用" />
      {user.account_type === "visitor" ? (
        <Group title="个人资料">
          <p className="note note-info" role="note">访客空间不能修改个人资料。注册个人账号后，可以设置名字和一句简介。</p>
        </Group>
      ) : <ProfileGroup user={user} updateUser={updateUser} setDirty={setDirty} />}
      <Group title="外观" note="只影响这台设备，换一台设备要重新设">
        <Row name="主题" hint="跟随系统时，系统换成深色，这里也跟着换"><Segmented label="主题" value={mode} items={themeItems} onChange={setThemeMode} /></Row>
        <Row name="正文字号" hint="写作页和章节正文的阅读区"><Segmented label="正文字号" value={fontSize} items={sizeItems} onChange={setFontSize} /></Row>
        <Row name="减少动画" hint="在系统的辅助功能里打开后，页面的动画会停下"><span className="faint">跟随系统设置</span></Row>
      </Group>
    </>
  );
}

/** 修改密码: the old password, the new one twice. The reset by mail stays the way out for a forgotten one. */
function PasswordForm({ onDone, onCancel, leaveTo }: { onDone: () => void; onCancel: () => void; leaveTo: (href: string) => Promise<void> }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    if (next.length < 10 || new Set(next).size < 2) { setError(labelError({ code: "password_policy_failed" })); return; }
    if (next !== again) { setError("两次输入的新密码不一致。"); return; }
    setBusy(true);
    try {
      await json("/auth/password", "POST", { current_password: current, new_password: next });
      onDone();
    } catch (cause) { setError(labelError(cause)); } finally { setBusy(false); }
  };
  return (
    <form className="settings-subform" onSubmit={(event) => void submit(event)}>
      <label className="field"><span className="field-label">旧密码</span><input type="password" autoComplete="current-password" required value={current} onChange={(event) => setCurrent(event.target.value)} disabled={busy} /></label>
      <div className="field">
        <label className="field-label" htmlFor="password-new">新密码</label>
        <input id="password-new" type="password" autoComplete="new-password" required minLength={10} value={next} onChange={(event) => setNext(event.target.value)} disabled={busy} aria-describedby="password-new-hint" />
        <span id="password-new-hint" className="field-hint">至少 10 位，不能全是同一个字符。</span>
      </div>
      <label className="field"><span className="field-label">再输一次新密码</span><input type="password" autoComplete="new-password" required value={again} onChange={(event) => setAgain(event.target.value)} disabled={busy} /></label>
      {error && <p className="inline-error" role="alert">{error}</p>}
      <p className="small-note">改好后，其他设备上的登录会退出，没用过的找回密码链接也会作废。忘了旧密码？找回要先退出登录，再用恢复邮箱收一封重置邮件。<button type="button" className="link" onClick={() => void leaveTo("/password-reset")}>退出登录并找回密码</button></p>
      <div className="form-actions">
        <Button kind="primary" type="submit" disabled={busy} busy={busy}>{busy ? "正在修改" : "修改密码"}</Button>
        <Button kind="text" disabled={busy} onClick={onCancel}>取消</Button>
      </div>
    </form>
  );
}

/** 恢复邮箱: bind, change or send the verification again. */
function RecoveryEmailForm({ user, updateUser }: { user: User; updateUser: (user: User) => void }) {
  const recovery = user.recovery_email ?? { configured: false, verified: false, masked: null };
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const send = async (resend: boolean) => {
    setBusy(true); setError(""); setMessage("");
    try {
      await json(resend ? "/auth/recovery-email/resend" : "/auth/recovery-email", "POST", { recovery_email: email });
      updateUser((await request<{ user: User }>("/auth/session")).user);
      setMessage(resend ? "验证邮件重新发送了。" : "恢复邮箱已绑定，验证邮件已发送。");
    } catch (cause) { setError(labelError(cause)); } finally { setBusy(false); }
  };
  return (
    <form className="settings-subform" onSubmit={(event) => { event.preventDefault(); void send(false); }}>
      <label className="field"><span className="field-label">{recovery.configured ? "换一个邮箱" : "恢复邮箱"}</span><input type="email" autoComplete="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      {message && <p className="inline-ok" role="status">{message}</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}
      <div className="form-actions">
        <Button kind="primary" type="submit" disabled={busy}>{recovery.configured ? "更换并发送验证" : "绑定并发送验证"}</Button>
        {recovery.configured && !recovery.verified && <Button disabled={busy || !email} onClick={() => void send(true)}>重新发送验证</Button>}
      </div>
    </form>
  );
}

/** 账号: the account, the password, the recovery email, and how signing in works. */
function AccountPane({ user, updateUser, leaveTo }: { user: User; updateUser: (user: User) => void; leaveTo: (href: string) => Promise<void> }) {
  const visitor = user.account_type === "visitor";
  const recovery = user.recovery_email ?? { configured: false, verified: false, masked: null };
  const [changing, setChanging] = useState(false);
  const [editingEmail, setEditingEmail] = useState(false);
  const [notice, setNotice] = useState("");
  const signedIn = <Row name="登录状态" hint="在别的设备登录后，这里会自动退出"><span className="faint">只在一处保持登录</span></Row>;
  return (
    <>
      <PaneHead title="账号" />
      {visitor ? (
        <Group title="登录与安全">
          <p className="note note-info" role="note">访客空间不能绑定恢复邮箱，也没有密码。注册个人账号后就可以绑定。</p>
          {signedIn}
        </Group>
      ) : (
        <Group title="登录与安全">
          <Row name="登录账号" hint="注册时起的，不能修改"><span className="mono">{user.account_name}</span></Row>
          <Row name="密码" hint={<>
            {user.password_changed_at ? `上次修改：${momentDayLabel(user.password_changed_at)}` : "注册时设置"}
            {notice && <span className="save-state ok d-line" role="status">{notice}</span>}
          </>}>
            {!changing && <Button kind="small" onClick={() => { setChanging(true); setNotice(""); }}>修改密码</Button>}
          </Row>
          {changing && <div className="row-sub"><PasswordForm leaveTo={leaveTo} onCancel={() => setChanging(false)} onDone={() => {
            setChanging(false);
            setNotice("密码已修改");
            void request<{ user: User }>("/auth/session").then((data) => updateUser(data.user)).catch(() => undefined);
          }} /></div>}
          <Row name="恢复邮箱" hint={<>
            <span className="security-email">{recovery.configured ? recovery.masked : "还没绑定"}</span>{" "}
            <Tag tone={recovery.verified ? "solid" : "gap"}>{recovery.verified ? "已验证" : "未验证"}</Tag>
            <span className="d-line">只用来找回密码和必要的安全通知</span>
          </>}>
            <Button kind="small" expanded={editingEmail} onClick={() => setEditingEmail((open) => !open)}>{recovery.configured ? "更换" : "绑定"}</Button>
          </Row>
          {editingEmail && <div className="row-sub"><RecoveryEmailForm user={user} updateUser={updateUser} /></div>}
          {signedIn}
        </Group>
      )}
    </>
  );
}

/** The last seven days, checks and assistant side by side in one column per day. */
function WeekChart({ daily }: { daily: DailyUsage }) {
  const [active, setActive] = useState<number | null>(null);
  const top = Math.max(1, ...daily.days.map((day) => day.check_chars + day.assistant_chars));
  const read = (index: number) => {
    const day = daily.days[index];
    return `${monthDayLabel(day.day)} · 检查 ${formatCount(day.check_chars)} 字 · 助手 ${formatCount(day.assistant_chars)} 字`;
  };
  return (
    <div className="week-wrap">
      <ol className="week" aria-label="近 7 天每天用掉的字数" onMouseLeave={() => setActive(null)}>
        {daily.days.map((day, index) => (
          <li key={day.day} tabIndex={0} aria-label={read(index)} onMouseEnter={() => setActive(index)} onFocus={() => setActive(index)} onBlur={() => setActive(null)}>
            <i className="a" style={{ height: `${(day.assistant_chars / top) * 100}%` }} />
            <i className="c" style={{ height: `${(day.check_chars / top) * 100}%` }} />
          </li>
        ))}
      </ol>
      <ol className="week-labels" aria-hidden="true">{daily.days.map((day) => <li key={day.day}>{shortDay(day.day, daily.today)}</li>)}</ol>
      {active !== null && <span className="tip" style={{ left: `${((active + 0.5) / daily.days.length) * 100}%` }} aria-hidden="true">{read(active)}</span>}
    </div>
  );
}

/** 用量: the rolling 24-hour allowance, and the last seven days. */
function UsagePane({ user, usage }: { user: User; usage: CheckUsage | null }) {
  const visitor = user.account_type === "visitor";
  const [daily, setDaily] = useState<DailyUsage | null>(null);
  const [failed, setFailed] = useState(false);
  const [now] = useState(() => Date.now());
  useEffect(() => {
    if (visitor) return;
    let live = true;
    request<DailyUsage>("/account/usage/daily?days=7").then((next) => { if (live) setDaily(next); }).catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [visitor, user.id]);
  return (
    <>
      <PaneHead title="用量" lede="检查和助手用同一个额度，按字数计：检查算它读的字数，助手每问一次算 500 字。额度是滚动的 24 小时，用掉的字数过 24 小时就回来，不是每天 0 点恢复。" />
      <Group title="近 24 小时">
        {usage?.account_type === "visitor" ? (
          <div className="meter-block">
            <span className="label">访客 · 24 小时内还可检查</span>
            <span className="big">{usage.checks_remaining}<small>/ {usage.checks_limit} 次</small></span>
            <span className="bar"><i style={{ width: `${usage.checks_limit ? (usage.checks_remaining / usage.checks_limit) * 100 : 0}%` }} /></span>
            <span className="sub"><span>每次最多 {formatCount(usage.check_chars_per_check)} 字</span>{usage.assistant_tasks_limit !== undefined && <span>助手还可以问 {usage.assistant_tasks_remaining} / {usage.assistant_tasks_limit} 次</span>}</span>
            <p className="small-note">注册个人账号后，可以检查更长的章节，也能看到每天的用量。</p>
          </div>
        ) : usage?.account_type === "registered" ? (
          <div className="meter-block">
            <span className="label">还能检查</span>
            <span className="big" data-testid="usage-remaining">{formatCount(usage.check_chars_remaining)}<small>/ {formatCount(usage.check_chars_limit)} 字</small></span>
            <span className="bar"><i style={{ width: `${usage.check_chars_limit ? (usage.check_chars_remaining / usage.check_chars_limit) * 100 : 0}%` }} /></span>
            <span className="sub">
              <span>已用 {formatCount(usage.check_chars_used)} 字</span>
              {daily?.oldest_charge && <span>最早的一笔在 {untilLabel(daily.oldest_charge.recovers_at, now)}后恢复</span>}
            </span>
          </div>
        ) : <p className="loading">正在读取…</p>}
      </Group>
      {!visitor && (
        <section className="group" aria-labelledby="usage-week">
          <div className="group-h">
            <h3 id="usage-week">近 7 天</h3>
            <span className="key" aria-hidden="true"><span><i className="c" />检查</span><span><i className="a" />助手</span></span>
          </div>
          <div className="group-body">
            {daily ? <WeekChart daily={daily} /> : failed ? <p className="empty">暂时读不到每天的用量，请稍后再看。</p> : <p className="loading">正在读取…</p>}
            <p className="small-note">一天从北京时间 0 点算起。</p>
          </div>
        </section>
      )}
    </>
  );
}

/** 数据: everything the author has written, in one download. */
function DataPane({ user }: { user: User }) {
  const visitor = user.account_type === "visitor";
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const download = async () => {
    if (busy) return;
    setBusy(true); setMessage(""); setFailed(false);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 120_000);
    try {
      const response = await fetch("/api/account/export", { credentials: "same-origin", cache: "no-store", signal: controller.signal });
      if (!response.ok) {
        let code = "";
        try { code = ((await response.json()) as { error?: { code?: string } }).error?.code ?? ""; } catch { /* no body */ }
        if (response.status === 401) throw new Error("登录已过期，请重新登录后导出。");
        throw new Error(code ? labelError({ code }) : "暂时没能导出，请稍后重试。");
      }
      const blob = await response.blob();
      const encoded = /filename\*=UTF-8''([^;]+)/i.exec(response.headers.get("Content-Disposition") ?? "")?.[1];
      let filename = "story-continuity-all.zip";
      if (encoded) { try { filename = decodeURIComponent(encoded); } catch { /* keep the fallback */ } }
      filename = filename.replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, "-");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
      if (mounted.current) setMessage("文件已生成，看一下浏览器的下载列表。");
    } catch (cause) {
      if (!mounted.current) return;
      setFailed(true);
      setMessage((cause as Error).name === "AbortError" ? "等太久了，可以再试一次。" : (cause as Error).message);
    } finally {
      window.clearTimeout(timeout);
      if (mounted.current) setBusy(false);
    }
  };
  return (
    <>
      <PaneHead title="数据" lede="你的作品是你的。" />
      <Group title="导出">
        <Row name="导出全部作品" hint={<>全部作品的正文、草稿、事实和计划，打成一个压缩包，不含示例作品。<span className="d-line">{visitor ? "访客空间不能导出全部作品；注册个人账号后可以使用。" : "单部作品仍可在作品的“更多”里导出。"}</span></>}>
          <Button kind="small" disabled={visitor || busy} busy={busy} onClick={() => void download()}>{busy ? "正在生成…" : "导出"}</Button>
        </Row>
      </Group>
      <p className={failed ? "inline-error" : "inline-ok"} role={failed ? "alert" : "status"} aria-live="polite" hidden={!message}>{message}</p>
      <Group title="删除">
        <Row name="删除账号" hint="删除账号和全部作品，不能恢复。这一版先不提供。" danger><span className="faint">暂不提供</span></Row>
      </Group>
    </>
  );
}

/** 设置: one pane at a time, each at its own address. */
export function SettingsPage({ user, updateUser, usage, item, go, setDirty, leaveTo }: {
  user: User;
  updateUser: (user: User) => void;
  usage: CheckUsage | null;
  item: SettingsItem;
  go: (href: string) => void;
  setDirty: (dirty: boolean) => void;
  /** Signs out and goes to an address that only signed-out visitors may open. */
  leaveTo: (href: string) => Promise<void>;
}) {
  useEffect(() => () => setDirty(false), [setDirty, item]);
  return (
    <section className="page settings">
      <nav className="settings-nav" aria-label="设置">
        <h1>设置</h1>
        <div className="settings-links">
          {settingsItems.map(([id, label]) => (
            <button key={id} type="button" aria-current={id === item ? "page" : undefined} onClick={() => go(`/settings/${id}`)}>{label}</button>
          ))}
        </div>
        <button type="button" className="link back" onClick={() => go("/account")}>← 回到作者主页</button>
      </nav>
      <div className="settings-pane">
        {item === "general" && <GeneralPane user={user} updateUser={updateUser} setDirty={setDirty} />}
        {item === "account" && <AccountPane user={user} updateUser={updateUser} leaveTo={leaveTo} />}
        {item === "usage" && <UsagePane user={user} usage={usage} />}
        {item === "data" && <DataPane user={user} />}
      </div>
    </section>
  );
}
