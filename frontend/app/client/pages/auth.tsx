"use client";

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { json, labelError, request, type ApiFailure } from "../../api";
import type { User } from "../../model";
import { Button } from "../ui";

/** Sign-in pages: the product line set large on the left, the form in one column on the right. */
function AuthLayout({ title, lede, children }: { title: string; lede?: string; children: ReactNode }) {
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
        <h1>{title}</h1>
        {lede && <p className="auth-lede">{lede}</p>}
        {children}
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
  return (
    <AuthLayout title={register ? "创建账号" : "登录"} lede={register ? "注册后作品长期保存，每 24 小时可以检查更多字数。" : "继续写你的作品。"}>
      <form className="auth-form" onSubmit={(event) => { event.preventDefault(); void submit(new FormData(event.currentTarget), register ? "register" : "login"); }}>
        <label className="field">
          <span className="field-label">账号</span>
          <input ref={account} name="account_name" autoComplete="username" required minLength={register ? 3 : undefined} aria-invalid={hasError || undefined} aria-describedby={hasError ? "auth-error" : undefined} />
        </label>
        {register && (
          <label className="field">
            <span className="field-label">显示名称</span>
            <input name="display_name" required maxLength={60} />
          </label>
        )}
        {register && (
          <label className="field">
            <span className="field-label">恢复邮箱</span>
            <input name="recovery_email" type="email" autoComplete="email" required maxLength={254} placeholder="name@example.com" />
          </label>
        )}
        <div className="field">
          <label className="field-label" htmlFor="auth-password">密码</label>
          <span className="password-field">
            <input id="auth-password" name="password" type={showPassword ? "text" : "password"} autoComplete={register ? "new-password" : "current-password"} required minLength={register ? 10 : undefined} aria-invalid={hasError || undefined} aria-describedby={hasError ? "auth-error" : undefined} />
            <button type="button" className="password-toggle" aria-pressed={showPassword} aria-label={showPassword ? "隐藏密码" : "显示密码"} disabled={Boolean(busy)} onClick={() => setShowPassword((value) => !value)}>{showPassword ? "隐藏" : "显示"}</button>
          </span>
        </div>
        {register && <p className="field-hint">账号至少 3 个字符，密码至少 10 个字符。恢复邮箱用来找回密码，注册后会收到一封验证邮件。</p>}
        {hasError && <p id="auth-error" className="inline-error" role="alert">{message}</p>}
        <Button kind="primary" size="lg" type="submit" disabled={Boolean(busy)} busy={Boolean(busy)} className="auth-submit">{busy || (register ? "创建账号" : "登录")}</Button>
        <div className="auth-links">
          <Button kind="text" disabled={Boolean(busy)} onClick={() => go(register ? "/login" : "/register")}>{register ? "已有账号？去登录" : "还没有账号？创建一个"}</Button>
          {!register && <Button kind="text" disabled={Boolean(busy)} onClick={() => go("/password-reset")}>忘记密码</Button>}
        </div>
        {!register && (
          <div className="auth-visitor">
            <p><strong>先看看？</strong>访客空间保留 24 小时，带一部示例作品，可以检查几次短章节。</p>
            <Button kind="outline" disabled={Boolean(busy)} onClick={() => void visitor()}>以访客身份进入</Button>
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
    <AuthLayout title="找回密码" lede="填写已经验证的恢复邮箱。无论账号是否存在，这里的回应都一样。">
      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        <label className="field"><span className="field-label">恢复邮箱</span><input name="recovery_email" type="email" autoComplete="email" required maxLength={254} /></label>
        {message && <p className={state === "failed" ? "inline-error" : "inline-ok"} role={state === "failed" ? "alert" : "status"}>{message}</p>}
        <Button kind="primary" size="lg" type="submit" className="auth-submit" disabled={state === "sending"} busy={state === "sending"}>{state === "sending" ? "正在发送" : "发送重置邮件"}</Button>
        <div className="auth-links"><Button kind="text" onClick={() => go("/login")}>返回登录</Button></div>
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
    <AuthLayout title="设置新密码" lede="链接只能用一次，15 分钟后过期。">
      {state === "success" ? (
        <div className="auth-form">
          <p className="inline-ok" role="status">{message}</p>
          <Button kind="primary" size="lg" className="auth-submit" onClick={() => go("/login")}>去登录</Button>
        </div>
      ) : (
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          <label className="field"><span className="field-label">新密码</span><input name="password" type="password" autoComplete="new-password" minLength={10} required /></label>
          <p className="field-hint">至少 10 个字符，不能全部相同。</p>
          {message && <p className="inline-error" role="alert">{message}</p>}
          <Button kind="primary" size="lg" type="submit" className="auth-submit" disabled={state === "sending"} busy={state === "sending"}>{state === "sending" ? "正在更新" : "更新密码"}</Button>
          <div className="auth-links"><Button kind="text" onClick={() => go("/password-reset")}>重新发起</Button></div>
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
