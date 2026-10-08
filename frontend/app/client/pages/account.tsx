"use client";

import { FormEvent, useEffect, useState } from "react";
import { json, labelError, request, type ApiFailure } from "../../api";
import type { ProjectSummary, User } from "../../model";
import { Avatar, avatarPresets } from "../identity";
import { workStatusLabel } from "../labels";
import { Button, formatCount, Num, PageHead, SectionHead, Tag } from "../ui";

const isSample = (project: Pick<ProjectSummary, "data_origin">) => project.data_origin === "demo_seed" || project.data_origin === "tutorial_seed";

/** 个人信息: the author's name and portrait, their figures, and their works. */
export function ProfilePage({ user, updateUser, go }: { user: User; updateUser: (user: User) => void; go: (href: string) => void }) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [name, setName] = useState(user.display_name);
  const [avatar, setAvatar] = useState<User["avatar_preset"]>(user.avatar_preset || "continuity_violet");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    Promise.all([request<{ projects: ProjectSummary[] }>("/projects?q=&sort=updated_desc"), request<{ projects: ProjectSummary[] }>("/projects?q=&status=archived&sort=updated_desc")])
      .then(([current, archived]) => { if (live) setProjects([...current.projects, ...archived.projects].filter((item) => !isSample(item)).sort((a, b) => b.updated_at.localeCompare(a.updated_at))); })
      .catch(() => { if (live) setProjects([]); });
    return () => { live = false; };
  }, []);
  const rows = projects ?? [];
  const chapters = rows.reduce((sum, item) => sum + (item.chapter_count ?? 0), 0);
  const words = rows.reduce((sum, item) => sum + (item.word_count ?? 0), 0);
  const changed = name.trim() !== user.display_name || avatar !== user.avatar_preset;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true); setMessage(""); setError("");
    try {
      const data = await json<{ user: User }>("/auth/profile", "PATCH", { base_profile_revision: user.profile_revision, display_name: name, avatar_preset: avatar });
      updateUser(data.user);
      setName(data.user.display_name);
      setAvatar(data.user.avatar_preset);
      setEditing(false);
      setMessage("已保存。");
    } catch (cause) {
      if ((cause as ApiFailure).code === "profile_revision_conflict") {
        try { updateUser((await request<{ user: User }>("/auth/session")).user); } catch { /* keep the author's choices */ }
      }
      setError(labelError(cause));
    } finally { setBusy(false); }
  };
  return (
    <section className="page profile">
      <header className="profile-head">
        <Avatar user={{ avatar_preset: editing ? avatar : user.avatar_preset }} className="avatar-xl" />
        <div className="profile-head-main">
          <p className="label">{user.account_type === "visitor" ? "访客空间" : `@${user.account_name}`}</p>
          <h1>{user.display_name}</h1>
        </div>
        <dl className="figures">
          <div><dt className="sr-only">作品</dt><dd><Num>{projects === null ? "—" : rows.length}</Num></dd><dd className="figure-label">部作品</dd></div>
          <div><dt className="sr-only">章节</dt><dd><Num>{projects === null ? "—" : formatCount(chapters)}</Num></dd><dd className="figure-label">章</dd></div>
          <div><dt className="sr-only">字数</dt><dd><Num>{projects === null ? "—" : formatCount(words)}</Num></dd><dd className="figure-label">字</dd></div>
        </dl>
      </header>
      <div className="profile-columns">
        <section aria-labelledby="profile-works">
          <SectionHead id="profile-works" title="我的作品" aside={<button type="button" className="link" onClick={() => go("/projects")}>作品管理</button>} />
          {projects === null ? <p className="loading">正在读取…</p> : rows.length ? (
            <ol className="work-list">
              {rows.slice(0, 6).map((item) => (
                <li key={item.id}>
                  <button type="button" onClick={() => go(`/projects/${item.id}/overview`)}>
                    <span className="work-list-main">
                      <span className="work-list-title">{item.title}</span>
                      <span className="label">{[item.genre, `${item.chapter_count ?? 0} 章`, `${formatCount(item.word_count ?? 0)} 字`].filter(Boolean).join(" · ")}</span>
                    </span>
                    {item.status !== "active" && <Tag>{workStatusLabel(item.status)}</Tag>}
                  </button>
                </li>
              ))}
            </ol>
          ) : <p className="empty">还没有作品。<button type="button" className="link" onClick={() => go("/projects/new")}>新建一部</button></p>}
          <p className="small-note">字数按章节正文和当前草稿去掉空白后统计，不含示例作品。</p>
        </section>
        <section aria-labelledby="profile-settings">
          <SectionHead id="profile-settings" title="个人信息" aside={!editing && user.account_type !== "visitor" && <Button kind="small" onClick={() => setEditing(true)}>编辑</Button>} />
          {editing ? (
            <form className="form profile-form" onSubmit={(event) => void submit(event)}>
              <label className="field"><span className="field-label">显示名称</span><input value={name} onChange={(event) => setName(event.target.value)} required maxLength={60} autoComplete="name" disabled={busy} /></label>
              <fieldset className="field">
                <legend className="field-label">头像</legend>
                <div className="avatar-picker">
                  {avatarPresets.map((preset) => (
                    <label key={preset.id} className="avatar-option">
                      <input className="sr-only" type="radio" name="avatar" value={preset.id} checked={avatar === preset.id} onChange={() => setAvatar(preset.id)} disabled={busy} />
                      <Avatar user={{ avatar_preset: preset.id }} className="avatar-lg" />
                      <span>{preset.label}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              {error && <p className="inline-error" role="alert">{error}</p>}
              <div className="form-actions">
                <Button kind="primary" type="submit" disabled={busy || !changed} busy={busy}>{busy ? "正在保存" : "保存"}</Button>
                <Button kind="text" disabled={busy} onClick={() => { setName(user.display_name); setAvatar(user.avatar_preset || "continuity_violet"); setEditing(false); setError(""); }}>取消</Button>
              </div>
            </form>
          ) : (
            <dl className="facts-list">
              <div><dt>显示名称</dt><dd>{user.display_name}</dd></div>
              {user.account_type !== "visitor" && <div><dt>登录账号</dt><dd>{user.account_name}</dd></div>}
              <div><dt>账号类型</dt><dd>{user.account_type === "visitor" ? "访客空间（注册后可以长期保存）" : "个人账号"}</dd></div>
            </dl>
          )}
          {message && <p className="inline-ok" role="status">{message}</p>}
          {user.account_type !== "visitor" && <button type="button" className="link profile-security" onClick={() => go("/account/security")}>账号安全 · 恢复邮箱</button>}
        </section>
      </div>
    </section>
  );
}

/** 账号安全: the recovery email used to reset a password. */
export function SecurityPage({ user, updateUser, go }: { user: User; updateUser: (user: User) => void; go: (href: string) => void }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const recovery = user.recovery_email ?? { configured: false, verified: false, masked: null };
  const send = async (resend: boolean) => {
    setBusy(true); setError(""); setMessage("");
    try {
      await json(resend ? "/auth/recovery-email/resend" : "/auth/recovery-email", "POST", { recovery_email: email });
      updateUser((await request<{ user: User }>("/auth/session")).user);
      setMessage(resend ? "验证邮件重新发送了。" : "恢复邮箱已绑定，验证邮件已发送。");
    } catch (cause) { setError(labelError(cause)); } finally { setBusy(false); }
  };
  return (
    <section className="page form-page">
      <PageHead title="账号安全" lede="恢复邮箱只用来找回密码和必要的安全通知。" />
      <div className="form">
        <div className="security-status">
          <p className="label">当前恢复邮箱</p>
          <p className="security-email">{recovery.configured ? recovery.masked : "还没绑定"}</p>
          <Tag tone={recovery.verified ? "solid" : "gap"}>{recovery.verified ? "已验证" : "未验证"}</Tag>
        </div>
        {user.account_type === "visitor" ? (
          <p className="note note-info" role="note">访客空间不能绑定恢复邮箱。注册个人账号后就可以绑定。</p>
        ) : (
          <form className="form-inner" onSubmit={(event) => { event.preventDefault(); void send(false); }}>
            <label className="field"><span className="field-label">{recovery.configured ? "换一个邮箱" : "恢复邮箱"}</span><input type="email" autoComplete="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} /></label>
            {message && <p className="inline-ok" role="status">{message}</p>}
            {error && <p className="inline-error" role="alert">{error}</p>}
            <div className="form-actions">
              <Button kind="primary" type="submit" disabled={busy}>{recovery.configured ? "更换并发送验证" : "绑定并发送验证"}</Button>
              {recovery.configured && !recovery.verified && <Button disabled={busy || !email} onClick={() => void send(true)}>重新发送验证</Button>}
              <Button kind="text" onClick={() => go("/account/profile")}>返回个人信息</Button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
