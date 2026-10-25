"use client";

import { type CSSProperties, KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { request } from "../../api";
import type { AuthorHome, HomeEvent, User } from "../../model";
import { agoLabel, feedDayLabel, joinedLabel, localDay, monthDayLabel, shiftDay, weekdayOf } from "../day";
import { Avatar } from "../identity";
import { workStatusLabel } from "../labels";
import { Button, chapterHeading, Dialog, formatCount, Tag } from "../ui";
import { WorkCheckTag } from "./home";

/** 41.2 万 for the large figures; the exact count stays in the page for a screen reader. */
function figure(value: number): { text: string; unit?: string } {
  if (value >= 100_000) return { text: (Math.round(value / 1000) / 10).toLocaleString("en-US", { maximumFractionDigits: 1 }), unit: "万" };
  return { text: formatCount(value) };
}

const chapterList = (numbers: number[]) => {
  if (numbers.length < 2) return `第 ${numbers[0]} 章`;
  const run = numbers.every((value, index) => index === 0 || value === numbers[index - 1] + 1);
  return run ? `第 ${numbers[0]}–${numbers[numbers.length - 1]} 章` : `第 ${numbers.join("、")} 章`;
};

/** One line of 最近动态: what was done, never what was written. */
function eventLine(event: HomeEvent): { what: React.ReactNode; detail?: string; plus?: boolean } {
  const work = <b>《{event.project_title}》</b>;
  const chapter = event.chapter_numbers.length ? chapterList(event.chapter_numbers) : "";
  // The chapter's name, when it has one beyond its number.
  const detailName = event.chapter_numbers.length === 1 ? chapterHeading(event.chapter_numbers[0], event.chapter_title).split(" · ")[1] : undefined;
  switch (event.kind) {
    case "draft_saved": {
      const net = event.net_chars ?? 0;
      return { what: <>在{work}保存了{chapter}草稿</>, detail: net ? `${net > 0 ? "+" : "−"}${formatCount(Math.abs(net))} 字` : undefined, plus: net > 0 };
    }
    case "chapter_finished": return { what: <>在{work}写完了{chapter}</>, detail: detailName };
    case "checked": {
      const issues = event.issue_count ?? 0;
      return { what: <>检查了{work}{chapter}</>, detail: issues ? `发现 ${issues} 处` : "没有发现问题" };
    }
    case "assistant_adopted": return { what: <>采用了助手的改法{chapter ? ` · ${chapter}` : ""}</>, detail: [`《${event.project_title}》`, detailName].filter(Boolean).join(" · ") };
    default: return { what: <>{event.origin === "user_import" ? "导入了作品" : "新建了作品"}{work}</> };
  }
}

/** 写作日历: a year of days, one cell each, shaded by how much was written; hover or the arrow keys read a day. */
function WritingCalendar({ calendar }: { calendar: AuthorHome["calendar"] }) {
  const [active, setActive] = useState<number | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const summary = useId();
  const count = calendar.chars.length;
  const offset = weekdayOf(calendar.start);
  const columns = Math.ceil((count + offset) / 7);
  const labels = useMemo(() => calendar.chars.map((chars, index) => `${monthDayLabel(shiftDay(calendar.start, index))} · ${chars ? `${formatCount(chars)} 字` : "没有写"}`), [calendar]);
  const months = useMemo(() => {
    const marks: { column: number; label: string }[] = [];
    let last = -1;
    for (let column = 0; column < columns; column += 1) {
      const day = shiftDay(calendar.start, Math.max(0, column * 7 - offset));
      const [, month, date] = day.split("-").map(Number);
      if (month !== last && date <= 7) { marks.push({ column, label: `${month}月` }); last = month; }
    }
    return marks;
  }, [calendar.start, columns, offset]);
  const monthly = useMemo(() => {
    const totals = new Map<string, number>();
    calendar.chars.forEach((chars, index) => {
      const [year, month] = shiftDay(calendar.start, index).split("-");
      totals.set(`${year} 年 ${Number(month)} 月`, (totals.get(`${year} 年 ${Number(month)} 月`) ?? 0) + chars);
    });
    return [...totals];
  }, [calendar]);
  // Newest days are on the right: the row starts there when it is wider than the room, and stays there while the page settles
  // (the side gutters and the fonts change the room after the first paint) until the reader slides it themselves.
  const following = useRef(true);
  useEffect(() => {
    const row = scroller.current;
    if (!row) return;
    const toEnd = () => { if (following.current) row.scrollLeft = row.scrollWidth; };
    // The reader's own hand (wheel, touch, a press on the bar) ends the following; the row's own scrolls do not, since by the time
    // their scroll event arrives the room may already have changed again.
    const release = () => { following.current = false; };
    following.current = true;
    toEnd();
    const hands = ["wheel", "touchstart", "pointerdown"] as const;
    for (const name of hands) row.addEventListener(name, release, { passive: true });
    const observer = new ResizeObserver(toEnd);
    observer.observe(row);
    if (row.firstElementChild) observer.observe(row.firstElementChild);
    return () => { for (const name of hands) row.removeEventListener(name, release); observer.disconnect(); };
  }, [calendar]);
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    const steps: Record<string, number> = { ArrowRight: 7, ArrowLeft: -7, ArrowDown: 1, ArrowUp: -1 };
    let next: number | null = null;
    if (event.key in steps) next = Math.min(count - 1, Math.max(0, (active ?? count - 1) + steps[event.key]));
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = count - 1;
    if (next === null) return;
    event.preventDefault();
    setActive(next);
  };
  const place = (index: number) => ({ "--col": Math.floor((index + offset) / 7), "--row": (index + offset) % 7 }) as CSSProperties;
  return (
    <div className="heat">
      <div className="heat-scroll" ref={scroller}>
        <div
          className="heat-body"
          style={{ "--cols": columns } as CSSProperties}
          role="group"
          tabIndex={0}
          aria-label="写作日历，过去 12 个月，方向键可以逐日查看"
          aria-describedby={summary}
          onKeyDown={move}
          onFocus={() => setActive((value) => value ?? count - 1)}
          onBlur={() => setActive(null)}
        >
          <div className="heat-days" aria-hidden="true"><span /><span>一</span><span /><span>三</span><span /><span>五</span><span /></div>
          <div className="heat-months" aria-hidden="true">
            {months.map((mark) => <span key={mark.column} style={{ gridColumn: mark.column + 1 }}>{mark.label}</span>)}
          </div>
          <div className="heat-grid" onMouseLeave={() => setActive(null)}>
            {calendar.chars.map((_, index) => (
              <i key={index} data-l={calendar.levels[index]} data-active={active === index || undefined} style={index === 0 ? { gridRowStart: offset + 1 } : undefined} onMouseEnter={() => setActive(index)} />
            ))}
            {active !== null && <span className="tip" style={place(active)} aria-hidden="true">{labels[active]}</span>}
          </div>
        </div>
      </div>
      <p id={summary} className="sr-only">每月写作字数：{monthly.map(([month, total]) => `${month} ${formatCount(total)} 字`).join("，")}。</p>
      <span className="sr-only" role="status" aria-live="polite">{active !== null ? labels[active] : ""}</span>
      <div className="heat-foot">
        <span>每格一天，颜色越深写得越多。按章节正文和草稿的净增字数算，不含示例作品；一天从北京时间 0 点算起。</span>
        <span className="legend" aria-hidden="true">少 {[0, 1, 2, 3, 4].map((level) => <i key={level} data-l={level} />)} 多</span>
      </div>
    </div>
  );
}

/** 作者主页: who the author is, what they have written, and what they are writing now. */
export function AuthorHomePage({ user, go, fail, leaveToRegister }: { user: User; go: (href: string) => void; fail: (cause: unknown) => void; leaveToRegister: () => Promise<void> }) {
  const [data, setData] = useState<AuthorHome | null>(null);
  const [confirmRegister, setConfirmRegister] = useState(false);
  const [leaving, setLeaving] = useState(false);
  // "2 小时前" is read against the moment the page was opened.
  const [now] = useState(() => Date.now());
  useEffect(() => {
    let live = true;
    request<AuthorHome>("/account/home").then((next) => { if (live) setData(next); }).catch((cause) => { if (live) fail(cause); });
    return () => { live = false; };
    // The name and portrait come with the page, so a saved profile is read again on the next visit.
  }, [fail, user.profile_revision]);
  const visitor = user.account_type === "visitor";
  if (!data) return <section className="page author"><p className="loading">正在读取…</p></section>;
  const { profile, totals, year, current, works, activity } = data;
  const words = figure(totals.chars);
  const streak = totals.streak_days;
  const hours = Math.max(0, Math.ceil((Date.parse(profile.visitor_expires_at ?? "") - now) / 3_600_000));
  const left = hours >= 24 ? `${Math.ceil(hours / 24)} 天` : `${hours} 小时`;
  const best = year.best_day;
  const checkLabel = { checked: "本章已检查", edited: "检查之后又改过", unchecked: "本章还没检查" };
  return (
    <section className="page author">
      {visitor && (
        <div className="visit" role="note">
          <p>这是访客空间，还剩 <b className="mono">{left}</b>。到期后作品、写作日历和动态都会清除；注册个人账号，可以长期保存之后写的内容。</p>
          <Button kind="plain" className="visit-go" onClick={() => setConfirmRegister(true)}>注册个人账号</Button>
        </div>
      )}
      <header className="author-hero">
        <Avatar user={profile} className="avatar-xl" />
        <div className="author-who">
          <p className="author-handle">{visitor ? `访客 · ${monthDayLabel(localDay(profile.created_at))}开始` : `@${profile.account_name} · ${joinedLabel(profile.created_at)}`}</p>
          <h1 className="author-name">{profile.display_name}</h1>
          {visitor ? <p className="author-bio faint">注册后可以写一句介绍自己。</p>
            : profile.bio ? <p className="author-bio">{profile.bio}</p>
              : <button type="button" className="link author-bio-empty" onClick={() => go("/settings/general")}>写一句介绍自己</button>}
          <div className="author-actions">
            {!visitor && <Button kind="small" onClick={() => go("/settings/general")}>编辑资料</Button>}
            <Button kind="small" onClick={() => go("/settings")}>设置</Button>
          </div>
        </div>
        <dl className="author-figs">
          <div><dt className="sr-only">作品</dt><dd className="v">{formatCount(totals.works)}</dd><dd className="k">部作品</dd></div>
          <div><dt className="sr-only">章节</dt><dd className="v">{formatCount(totals.chapters)}</dd><dd className="k">章</dd></div>
          <div><dt className="sr-only">字数 {formatCount(totals.chars)}</dt><dd className="v">{words.text}{words.unit && <small>{words.unit}</small>}</dd><dd className="k">字</dd></div>
          {!visitor && (
            <div>
              <dt className="sr-only">{totals.streak_includes_today || !streak ? "连续在写" : `昨天以前连续 ${streak} 天`}</dt>
              <dd className="v blue">{streak}</dd>
              <dd className="k">{!totals.streak_includes_today && streak ? "天 · 昨天以前连续" : "天连续在写"}</dd>
            </div>
          )}
        </dl>
      </header>

      <div className="author-activity">
        <section aria-labelledby="author-calendar">
          <div className="sec-h"><h2 id="author-calendar">写作日历</h2><span className="label">过去 12 个月</span></div>
          <WritingCalendar calendar={data.calendar} />
        </section>
        <section aria-labelledby="author-year">
          <div className="sec-h"><h2 id="author-year">这一年</h2></div>
          <dl className="author-stats">
            <div><dt>写了</dt><dd>{(() => { const total = figure(year.chars); return total.unit ? `${total.text} ${total.unit}字` : `${total.text} 字`; })()}</dd></div>
            <div><dt>写作的天数</dt><dd>{year.writing_days} 天</dd></div>
            <div><dt>最多的一天</dt><dd>{best ? `${formatCount(best.chars)} 字` : "—"}</dd></div>
            <div><dt>最长连续</dt><dd>{year.longest_streak} 天</dd></div>
            <div><dt>检查过的章节</dt><dd>{year.checked_chapters} 章</dd></div>
          </dl>
        </section>
      </div>

      <div className="author-body">
        <div>
          {current && (
            <section aria-labelledby="author-current" className="author-current-wrap">
              <div className="sec-h"><h2 id="author-current">正在写</h2></div>
              <div className="current">
                <span className="chap" aria-hidden="true">{current.chapter_number}</span>
                <div className="meta">
                  <span className="label">《{current.project_title}》 · 第 {current.chapter_number} 章</span>
                  <h3>{chapterHeading(current.chapter_number, current.chapter_title).split(" · ")[1] ?? `第 ${current.chapter_number} 章`}</h3>
                  <p className="draft">草稿 <b>{formatCount(current.chars)}</b> 字 · {agoLabel(current.saved_at, now)}保存 · {checkLabel[current.check_state]}</p>
                </div>
                <Button kind="primary" onClick={() => go(`/projects/${current.project_id}/workspace`)}>继续写 →</Button>
              </div>
            </section>
          )}
          <section aria-labelledby="author-works">
            <div className="sec-h">
              <h2 id="author-works">全部作品 <span className="mono count">{works.length}</span></h2>
              <button type="button" className="link" onClick={() => go("/projects")}>作品管理 →</button>
            </div>
            <ul className="works">
              {works.map((work) => (
                <li key={work.id}>
                  <button type="button" className="work" onClick={() => go(`/projects/${work.id}/overview`)}>
                    <span className="top">
                      <span className="label">{work.genre || "未分类"}</span>
                      <span className="tags">
                        {work.status !== "active" && <Tag tone={work.status === "archived" ? "gap" : "line"}>{workStatusLabel(work.status)}</Tag>}
                        <WorkCheckTag project={work} />
                      </span>
                    </span>
                    <span className="t">{work.title}</span>
                    <span className="sum">{work.summary || "没有简介"}</span>
                    <span className="foot"><span>{work.chapter_count ?? 0} 章</span><span>{formatCount(work.word_count ?? 0)} 字</span><span>{agoLabel(work.updated_at, now)}更新</span></span>
                  </button>
                </li>
              ))}
              <li>
                <div className="work work-new">
                  <button type="button" className="t blue" onClick={() => go("/projects/new")}>＋ 新建一部作品</button>
                  <span className="sum">也可以<button type="button" className="link" onClick={() => go("/projects/import")}>导入已有的稿子</button>。</span>
                </div>
              </li>
            </ul>
          </section>
        </div>
        <aside aria-labelledby="author-feed">
          <div className="sec-h"><h2 id="author-feed">最近动态</h2><span className="label">只有你看得到</span></div>
          {activity.length ? (
            <ol className="feed">
              {activity.map((event, index) => {
                const line = eventLine(event);
                return (
                  <li key={`${event.kind}-${event.at}-${index}`}>
                    <span className="d">{feedDayLabel(event.day, data.today)}</span>
                    <span className="w">{line.what}{line.detail && <span className={`x${line.plus ? " plus" : ""}`}>{line.detail}</span>}</span>
                  </li>
                );
              })}
            </ol>
          ) : <p className="empty">还没有动态。写一章草稿、检查一章，这里就会有记录。</p>}
        </aside>
      </div>

      {confirmRegister && (
        <Dialog title="先退出访客空间" close={() => { if (!leaving) setConfirmRegister(false); }} closeDisabled={leaving}>
          <p>注册要先退出访客空间。这里的作品和记录不会带到新账号里，到期后会清除。</p>
          <div className="dialog-actions">
            <Button kind="primary" disabled={leaving} busy={leaving} onClick={() => { setLeaving(true); void leaveToRegister().finally(() => setLeaving(false)); }}>退出并去注册</Button>
            <Button kind="text" disabled={leaving} onClick={() => setConfirmRegister(false)}>留在这里</Button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
