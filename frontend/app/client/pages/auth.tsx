"use client";

import Link from "next/link";
import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { json, labelError, request, type ApiFailure } from "../../api";
import type { User } from "../../model";
import { Button } from "../ui";

/** The product's thread mark, drawn in ink so it follows the theme. */
function AuthMark() {
  return (
    <svg className="auth-mark" viewBox="0 0 48 48" aria-hidden="true">
      <path d="M9 11h26a6 6 0 0 1 0 12H13a6 6 0 0 0 0 12h26" stroke="currentColor" strokeWidth="5.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <circle cx="9" cy="11" r="4.2" fill="currentColor" />
      <path d="M36 30l6 5-6 5" stroke="currentColor" strokeWidth="5.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

function EyeIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {open ? (
        <><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>
      ) : (
        <><path d="M3 3l18 18" /><path d="M10.6 5.1A10.4 10.4 0 0 1 12 5c6.4 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.2M6.6 6.6C3.7 8.4 2 12 2 12s3.6 7 10 7a9.8 9.8 0 0 0 5.4-1.6" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" /></>
      )}
    </svg>
  );
}

/** A field with only an underline; the label sits inside it and rises once there is text (placeholder=" " drives that;
    a field with a real placeholder keeps its label raised). */
function LineField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="line-field">
      {children}
      <span className="line-label">{label}</span>
    </label>
  );
}

/** Sign-in pages: the product line set large on the left; on the right one narrow centred column with the mark,
    a large title and the form, and an optional line pinned to the foot. */
function AuthLayout({ title, lede, foot, children }: { title: string; lede?: string; foot?: ReactNode; children: ReactNode }) {
  return (
    <section className="auth">
      <div className="auth-side">
        <span className="wordmark auth-wordmark" aria-hidden="true">STORY<br />CONTINUITY</span>
        <p className="auth-claim">写长篇，<br />前后不打架。</p>
        <ol className="auth-points">
          <li><span className="num">01</span>写完一章就检查，和前文冲突的句子直接标在正文里。</li>
          <li><span className="num">02</span>每一处都附上前文出处，改不改由你决定。</li>
          <li><span className="num">03</span>资料只记已经写进正文的内容，还没写的放在计划里。</li>
        </ol>
      </div>
      <div className="auth-main">
        <div className="auth-body">
          <AuthMark />
          <h1>{title}</h1>
          {lede && <p className="auth-lede">{lede}</p>}
          {children}
        </div>
        {foot && <div className="auth-foot">{foot}</div>}
      </div>
    </section>
  );
}

export function AuthPage({ register, busy, error, submit, visitor, go }: {
  register: boolean;
  busy: string;
  error: unknown;
  submit: (form: FormData, kind: "login" | "register") => Promise<void>;
  visitor: () => Promise<void>;
  go: (href: string) => void;
}) {
  const account = useRef<HTMLInputElement>(null);
  const [showPassword, setShowPassword] = useState(false);
  const hasError = Boolean(error);
  const message = (error as ApiFailure | null)?.code === "authentication_required" ? "登录已过期，请重新登录。" : labelError(error);
  useEffect(() => {
    if (hasError || window.innerWidth > 760) account.current?.focus();
  }, [hasError, register]);
  const switchPage = (
    <p>
      {register ? "已有账号？" : "还没有账号？"}
      <button type="button" className="auth-switch" disabled={Boolean(busy)} onClick={() => go(register ? "/login" : "/register")}>{register ? "去登录" : "创建一个"}</button>
    </p>
  );
  return (
    <AuthLayout title={register ? "创建账号" : "欢迎回来"} lede={register ? "注册后作品长期保存，每 24 小时可以检查更多字数。" : "登录，继续写你的作品。"} foot={switchPage}>
      <form className="auth-form" onSubmit={(event) => { event.preventDefault(); void submit(new FormData(event.currentTarget), register ? "register" : "login"); }}>
        <LineField label="账号">
          <input ref={account} name="account_name" placeholder=" " autoComplete="username" required minLength={register ? 3 : undefined} aria-invalid={hasError || undefined} aria-describedby={hasError ? "auth-error" : undefined} />
        </LineField>
        {register && (
          <LineField label="显示名称">
            <input name="display_name" placeholder=" " required maxLength={60} />
          </LineField>
        )}
        {register && (
          <LineField label="恢复邮箱">
            <input name="recovery_email" type="email" autoComplete="email" required maxLength={254} placeholder="name@example.com" />
          </LineField>
        )}
        {/* Not a wrapping <label>: the eye button would become part of the field's name. */}
        <div className="line-field has-toggle">
          <input id="auth-password" name="password" placeholder=" " type={showPassword ? "text" : "password"} autoComplete={register ? "new-password" : "current-password"} required minLength={register ? 10 : undefined} aria-invalid={hasError || undefined} aria-describedby={hasError ? "auth-error" : undefined} />
          <label className="line-label" htmlFor="auth-password">密码</label>
          <button type="button" className="password-eye" aria-pressed={showPassword} aria-label={showPassword ? "隐藏密码" : "显示密码"} disabled={Boolean(busy)} onClick={() => setShowPassword((value) => !value)}><EyeIcon open={!showPassword} /></button>
        </div>
        {!register && (
          <div className="auth-row">
            <button type="button" className="auth-quiet" disabled={Boolean(busy)} onClick={() => go("/password-reset")}>忘记密码</button>
          </div>
        )}
        {register && <p className="field-hint">账号至少 3 个字符，密码至少 10 个字符。恢复邮箱用来找回密码，注册后会收到一封验证邮件。</p>}
        {register && <p className="field-hint">创建账号前，请看一下<Link className="link-inline" href="/privacy" onClick={(event) => { if (event.metaKey || event.ctrlKey || event.shiftKey) return; event.preventDefault(); go("/privacy"); }}>隐私说明</Link>。</p>}
        {hasError && <p id="auth-error" className="inline-error" role="alert">{message}</p>}
        <Button kind="primary" size="lg" type="submit" disabled={Boolean(busy)} busy={Boolean(busy)} className="auth-submit">{busy || (register ? "创建账号" : "登录")}</Button>
        {!register && (
          <div className="auth-visitor">
            <Button kind="outline" size="lg" className="auth-second" disabled={Boolean(busy)} onClick={() => void visitor()}>以访客身份进入</Button>
            <p><strong>先看看？</strong>访客空间保留 24 小时，带一部示例作品，可以检查几次短章节，也可以问助手。用到的片段会交给模型处理，详见<Link className="link-inline" href="/privacy" onClick={(event) => { if (event.metaKey || event.ctrlKey || event.shiftKey) return; event.preventDefault(); go("/privacy"); }}>隐私说明</Link>。</p>
          </div>
        )}
      </form>
    </AuthLayout>
  );
}

export function PasswordResetRequestPage({ go }: { go: (href: string) => void }) {
  const [state, setState] = useState<"request" | "sending" | "sent" | "failed">("request");
  const [message, setMessage] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setState("sending");
    setMessage("");
    try {
      await json("/auth/password-reset/request", "POST", { recovery_email: String(form.get("recovery_email")) });
      setState("sent");
      setMessage("如果这个邮箱已经验证，我们发了一封重置邮件，15 分钟内有效。");
    } catch (cause) {
      setState("failed");
      setMessage(labelError(cause));
    }
  };
  return (
    <AuthLayout title="找回密码" lede="填写已经验证的恢复邮箱。无论账号是否存在，这里的回应都一样。" foot={<p><button type="button" className="auth-switch" onClick={() => go("/login")}>返回登录</button></p>}>
      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        <LineField label="恢复邮箱"><input name="recovery_email" type="email" placeholder=" " autoComplete="email" required maxLength={254} /></LineField>
        {message && <p className={state === "failed" ? "inline-error" : "inline-ok"} role={state === "failed" ? "alert" : "status"}>{message}</p>}
        <Button kind="primary" size="lg" type="submit" className="auth-submit" disabled={state === "sending"} busy={state === "sending"}>{state === "sending" ? "正在发送" : "发送重置邮件"}</Button>
      </form>
    </AuthLayout>
  );
}

function consumeToken(): string {
  const token = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token") ?? "";
  history.replaceState(history.state, "", `${window.location.pathname}${window.location.search}`);
  return token;
}

export function PasswordResetConfirmPage({ go }: { go: (href: string) => void }) {
  const [state, setState] = useState<"confirm" | "sending" | "success" | "invalid">("confirm");
  const [message, setMessage] = useState("");
  const token = useRef("");
  useEffect(() => { token.current = consumeToken(); }, []);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (!token.current) { setState("invalid"); setMessage("链接无效或已过期，请重新发起。"); return; }
    setState("sending");
    try {
      await json("/auth/password-reset/confirm", "POST", { token: token.current, password: String(form.get("password")) });
      setState("success");
      setMessage("密码已更新，其他设备上的登录都已退出。请用新密码登录。");
    } catch (cause) {
      setState("invalid");
      setMessage(labelError(cause));
    }
  };
  return (
    <AuthLayout title="设置新密码" lede="链接只能用一次，15 分钟后过期。" foot={state === "success" ? undefined : <p><button type="button" className="auth-switch" onClick={() => go("/password-reset")}>重新发起</button></p>}>
      {state === "success" ? (
        <div className="auth-form">
          <p className="inline-ok" role="status">{message}</p>
          <Button kind="primary" size="lg" className="auth-submit" onClick={() => go("/login")}>去登录</Button>
        </div>
      ) : (
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          <LineField label="新密码"><input name="password" type="password" placeholder=" " autoComplete="new-password" minLength={10} required /></LineField>
          <p className="field-hint">至少 10 个字符，不能全部相同。</p>
          {message && <p className="inline-error" role="alert">{message}</p>}
          <Button kind="primary" size="lg" type="submit" className="auth-submit" disabled={state === "sending"} busy={state === "sending"}>{state === "sending" ? "正在更新" : "更新密码"}</Button>
        </form>
      )}
    </AuthLayout>
  );
}

export function VerifyEmailPage({ go, refreshUser }: { go: (href: string) => void; refreshUser: (user: User | null) => void }) {
  const [message, setMessage] = useState("正在验证恢复邮箱…");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const token = consumeToken();
    if (!token) {
      queueMicrotask(() => { setFailed(true); setMessage("链接无效或已过期，请重新发送验证邮件。"); });
      return;
    }
    json("/auth/recovery-email/verify", "POST", { token })
      .then(async () => {
        const session = await request<{ user: User | null }>("/auth/session?optional=true");
        refreshUser(session.user);
        setMessage("恢复邮箱验证好了，可以用来找回密码。");
      })
      .catch((cause) => { setFailed(true); setMessage(labelError(cause)); });
  }, [refreshUser]);
  return (
    <AuthLayout title="验证恢复邮箱">
      <div className="auth-form">
        <p className={failed ? "inline-error" : "inline-ok"} role={failed ? "alert" : "status"} aria-live="polite">{message}</p>
        <Button kind="primary" size="lg" className="auth-submit" onClick={() => go("/")}>回到首页</Button>
      </div>
    </AuthLayout>
  );
}
