"use client";

import { FormEvent, MouseEvent as ReactMouseEvent, useCallback, useEffect, useRef, useState } from "react";
import { json, labelError, labelRunFailure, request, type ApiFailure } from "../../api";
import type { Chapter, CharacterAliasSnapshot, ForeshadowCandidate, ForeshadowRecord, ForeshadowSnapshot, Memory, MemoryDelta, MemoryInitialization, WritingAnalysisRun } from "../../model";
import { experienceSimulation } from "../env";
import {
  activeAnalysis,
  controlledPredicates,
  coverageLabel,
  foreshadowStatusLabel,
  memoryTypeLabel,
  memoryTypes,
  predicateLabel,
  qaLayerLabel,
  qaStanceLabel,
  qaStatusLabel,
  readableKeys,
  retryableAnalysis,
  roleTypeLabel,
  sourceKindLabel,
  stageLabel,
  timeLabel,
  worldTypeLabel,
} from "../labels";
import { bareChapterTitle, Button, Chips, clip, Num, PageHead, pad2, SectionHead, Tabs, Tag } from "../ui";
import type { PageProps } from "./frame";
import { BULK_REVIEW_THRESHOLD, type Character, type ProjectState, type WorldEntry } from "./use-project";

/** A choice of fact key, not free text. A legacy key already on the candidate stays selectable. */
export function PredicateSelect({ name, value, disabled }: { name: string; value: string; disabled: boolean }) {
  const options = controlledPredicates.includes(value) ? controlledPredicates : [value, ...controlledPredicates];
  return <select name={name} defaultValue={value} disabled={disabled}>{options.map((key) => <option key={key} value={key}>{predicateLabel(key)}</option>)}</select>;
}

type View = "facts" | "people" | "settings" | "threads" | "ask";
const views: View[] = ["facts", "people", "settings", "threads", "ask"];
const factTone: Record<string, "line" | "solid" | "state" | "gap" | "mid"> = { static_canon: "line", event_timeline: "solid", dynamic_state: "state", character_knowledge: "gap", open_thread: "mid" };
const current = (records: Memory[]) => records.filter((record) => record.valid_to == null && record.review_status === "author_confirmed");

/** 资料: only what is already written into the story, each item traceable to its chapter. */
export function MaterialsPage({ p, initialView, go, notices }: PageProps & { initialView: "people" | "settings" | null }) {
  const project = p.project!;
  const [view, setView] = useState<View>(() => {
    if (initialView) return initialView;
    if (typeof window === "undefined") return "facts";
    const requested = new URLSearchParams(window.location.search).get("view");
    const legacy: Record<string, View> = { places: "settings", foreshadow: "threads" };
    const value = (requested && (legacy[requested] ?? requested)) as View;
    return views.includes(value) ? value : "facts";
  });
  const [threadCount, setThreadCount] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    request<ForeshadowSnapshot>(`/projects/${project.id}/foreshadows`).then((r) => { if (live) setThreadCount(r.records.filter((item) => !item.archived_at && item.status !== "resolved" && item.status !== "abandoned").length); }).catch(() => undefined);
    return () => { live = false; };
  }, [project.id, view]);
  const choose = (next: View) => {
    setView(next);
    try { window.history.replaceState(window.history.state, "", `/projects/${project.id}/memory${next === "facts" ? "" : `?view=${next}`}`); } catch { /* the view still switches */ }
  };
  return (
    <section className="page materials">
      {notices}
      <PageHead title="资料" lede="只放已经写进正文的内容，每一条都能查到出自哪一章。还没写的打算放在「计划」。" rule={false} />
      <Tabs<View>
        label="资料分类"
        value={view}
        onChange={choose}
        items={[
          { id: "facts", label: "事实", count: current(p.memories).length },
          { id: "people", label: "人物", count: p.characters.length },
          { id: "settings", label: "设定", count: p.world.length },
          { id: "threads", label: "伏笔", count: threadCount ?? "" },
          { id: "ask", label: "问一问" },
        ]}
      />
      {view === "facts" && <FactsView p={p} go={go} />}
      {view === "people" && <PeopleView p={p} />}
      {view === "settings" && <SettingsView p={p} />}
      {view === "threads" && <ThreadsView p={p} go={go} />}
      {view === "ask" && <AskView p={p} go={go} />}
    </section>
  );
}

function FactsView({ p, go }: { p: ProjectState; go: (href: string) => void }) {
  const project = p.project!;
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const blocked = p.readOnly || Boolean(p.busy);
  const records = p.memories;
  const visible = records
    .filter((record) => (filter === "all" || record.memory_type === filter) && `${record.subject} ${predicateLabel(record.predicate)} ${record.value}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
    .sort((a, b) => (a.source?.chapter_number ?? 9_999) - (b.source?.chapter_number ?? 9_999));
  const deltaOpen = p.memoryDelta && p.memoryDelta.status !== "not_started" && p.memoryDelta.status !== "covered";
  const initOpen = project.data_origin === "user_import" && p.initialization && (!records.length || p.coverage?.status === "ready_partial");
  return (
    <div className="materials-view">
      {p.memoryDelta?.coverage_audit && <p className="small-note">新增章节的事实：{coverageLabel(p.memoryDelta.coverage_audit.status)}{p.memoryDelta.change_set ? ` · 更新了 ${p.memoryDelta.change_set.items.length} 条` : ""}</p>}
      {deltaOpen ? <DeltaReview delta={p.memoryDelta!} blocked={blocked} submit={p.submitMemoryDelta} openSource={p.openMemorySource} />
        : initOpen ? <InitReview p={p} go={go} />
          : null}
      {records.length > 0 && (
        <>
          <div className="filter-row">
            <Chips label="事实类型" value={filter} onChange={setFilter} items={[{ id: "all", label: "全部", count: records.length }, ...memoryTypes.map((type) => ({ id: type, label: memoryTypeLabel(type), count: records.filter((record) => record.memory_type === type).length })).filter((item) => item.count)]} />
            <label className="search small"><span className="sr-only">搜索事实</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索" /></label>
          </div>
          {visible.length ? (
            <ol className="fact-list" aria-label="事实列表">
              {visible.map((record) => (
                <li key={record.id} id={`memory-${record.id}`} className={record.valid_to != null ? "retired" : undefined}>
                  <button type="button" className="memory-source fact-chapter" disabled={!record.source} aria-label={record.source ? `看 ${record.subject} 出自哪一章` : `${record.subject} 没有出处`} onClick={(event) => void p.openMemorySource(record, event.currentTarget)}>
                    <Num>{record.source ? pad2(record.source.chapter_number) : "—"}</Num>
                  </button>
                  <span className="fact-copy">
                    <strong>{record.subject}</strong>
                    <span className="fact-value">{predicateLabel(record.predicate) !== "其他" && <span className="fact-key">{predicateLabel(record.predicate)} · </span>}{record.value}</span>
                    {(record.valid_to != null || record.requires_source_review) && <span className="label">{record.valid_to != null ? "已被后来的内容取代" : "出处改过，待复核"}</span>}
                  </span>
                  <Tag tone={factTone[record.memory_type] ?? "line"}>{memoryTypeLabel(record.memory_type)}</Tag>
                </li>
              ))}
            </ol>
          ) : <p className="empty">没有符合条件的事实。</p>}
        </>
      )}
      {!records.length && !initOpen && !deltaOpen && (
        <p className="empty">{project.memory_initialization_status === "required" ? "这部导入作品还没整理事实。不整理也能检查，系统会直接对照前文；整理并确认后检查更准。" : "还没有确认过的事实。检查完一章、审阅事实变化后，事实会出现在这里。"}</p>
      )}
    </div>
  );
}

function DeltaReview({ delta, blocked, submit, openSource }: { delta: MemoryDelta; blocked: boolean; submit: (event: FormEvent<HTMLFormElement>) => Promise<void>; openSource: (memory: Memory, element: HTMLElement) => Promise<void> | void }) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  if (["processing", "cancelling"].includes(delta.status)) return <div className="note note-info" role="status">正在检查新增的章节、整理事实变化；两项都完成后显示在这里。</div>;
  if (["failed", "timed_out", "cancelled"].includes(delta.status)) return <div className="note note-error" role="alert">事实变化没有整理完。{labelRunFailure(delta.error_code, "事实整理")} 可以放心重试。</div>;
  const kind = { new_fact: "新事实", changed_fact: "改变", invalidated_fact: "不再成立" } as const;
  const asMemory = (candidate: MemoryDelta["candidates"][number]): Memory => ({
    id: candidate.id, memory_type: candidate.memory_type, subject: candidate.subject, predicate: candidate.predicate, value: candidate.value, valid_from: null, valid_to: null, review_status: "pending",
    source: { chapter_id: candidate.source.chapter_id, chapter_number: candidate.source.chapter_number, chapter_title: candidate.source.chapter_title, span_id: candidate.source.span_id, excerpt: candidate.source.excerpt, source_path: candidate.source.source_path },
  });
  return (
    <form className="confirm-block" aria-label="确认事实变化" onSubmit={(event) => void submit(event)}>
      <SectionHead title="新增章节的事实变化" aside={<span className="label">{coverageLabel(delta.coverage?.status)}</span>} strong />
      <p className="lede">每一条都附有出处。重要的变化需要逐条决定；次要的只有你接受了才会写入。</p>
      {!delta.candidates.length && <p className="empty">这些章节没有带来新的事实变化。确认后资料保持不变。</p>}
      {delta.candidates.map((candidate) => {
        const chosen = choices[candidate.id] ?? "";
        return (
          <article key={candidate.id} className="candidate">
            <header><Tag tone={candidate.change_kind === "invalidated_fact" ? "gap" : candidate.change_kind === "changed_fact" ? "state" : "solid"}>{kind[candidate.change_kind]}</Tag><span className="label">{candidate.review_priority === "core" ? "重要 · 必须决定" : "次要 · 可以稍后"}</span></header>
            <div className="change-flow">
              <div><p className="label">现在的资料</p><p className="change-text">{candidate.before ? `${candidate.before.subject} · ${predicateLabel(candidate.before.predicate)}：${candidate.before.value}` : "（还没有）"}</p>{candidate.before?.source && <button type="button" className="link" onClick={(event) => void openSource(candidate.before as Memory, event.currentTarget)}>原来的出处</button>}</div>
              <span className="change-arrow" aria-hidden="true">→</span>
              <div><p className="label">建议改为</p><p className="change-text">{candidate.change_kind === "invalidated_fact" ? `不再沿用这条。理由：${candidate.invalidation_reason}` : `${candidate.subject} · ${predicateLabel(candidate.predicate)}：${candidate.value}`}</p></div>
            </div>
            <blockquote className="candidate-quote"><span className="label">第 {candidate.source.chapter_number} 章 · {bareChapterTitle(candidate.source.chapter_title)}</span>{candidate.source.excerpt}<button type="button" className="link" onClick={(event) => void openSource(asMemory(candidate), event.currentTarget)}>看出处</button></blockquote>
            {candidate.decision_status === "pending" ? (
              <>
                <fieldset className="radio-row">
                  <legend className="sr-only">这一条怎么处理</legend>
                  {(["accepted", "rejected", ...(candidate.change_kind !== "invalidated_fact" ? ["edited"] : [])] as string[]).map((value) => (
                    <label key={value}><input type="radio" name={`memory-delta:${candidate.id}`} value={value} checked={chosen === value} onChange={() => setChoices((all) => ({ ...all, [candidate.id]: value }))} disabled={blocked} />{value === "accepted" ? "接受" : value === "rejected" ? "不接受" : "改一下再接受"}</label>
                  ))}
                </fieldset>
                {chosen === "edited" && (
                  <div className="edit-fields">
                    <label className="field"><span className="field-label">类型</span><select name={`memory-delta:${candidate.id}:memory_type`} defaultValue={candidate.memory_type} disabled={blocked}>{memoryTypes.map((type) => <option key={type} value={type}>{memoryTypeLabel(type)}</option>)}</select></label>
                    <label className="field"><span className="field-label">对象</span><input name={`memory-delta:${candidate.id}:subject`} defaultValue={candidate.subject} maxLength={80} disabled={blocked} /></label>
                    <label className="field"><span className="field-label">关系</span><PredicateSelect name={`memory-delta:${candidate.id}:predicate`} value={candidate.predicate} disabled={blocked} /></label>
                    <label className="field wide"><span className="field-label">内容</span><textarea name={`memory-delta:${candidate.id}:value`} defaultValue={candidate.value} maxLength={240} rows={2} disabled={blocked} /></label>
                  </div>
                )}
              </>
            ) : <p className="small-note">已{candidate.decision_status === "rejected" ? "不接受" : candidate.decision_status === "edited" ? "改后接受" : "接受"}；{candidate.decision_status === "rejected" ? "不会改资料。" : "提交后写入。"}</p>}
          </article>
        );
      })}
      <Button kind="primary" size="lg" type="submit" disabled={blocked}>{delta.candidates.length ? "确认并更新资料" : "确认，资料不变"}</Button>
    </form>
  );
}

/** First facts for an imported work: candidates from the text, each accepted, rejected or edited. */
function InitReview({ p, go }: { p: ProjectState; go: (href: string) => void }) {
  const init = p.initialization!;
  // Which candidates are set to 「改一下再接受」, so their edit fields show. The radios stay uncontrolled:
  // submit reads them from the form.
  const [editing, setEditing] = useState<Set<string>>(() => new Set());
  const choose = (id: string, value: string) => setEditing((current) => { const next = new Set(current); if (value === "edited") next.add(id); else next.delete(id); return next; });
  const blocked = p.readOnly || Boolean(p.busy);
  if (init.status === "required")
    return (
      <div className="confirm-block">
        <SectionHead title="从正文整理事实" strong />
        {p.initializationError && <p className="note note-error" role="alert">{p.initializationError}</p>}
        <p className="lede">系统从导入的章节里找出人物、地点、规则和事件，整理成候选。候选要你逐条确认，不会自动写进资料。</p>
        {experienceSimulation && <p className="note note-info">隔离模拟环境：候选来自固定示例数据，不会调用真实模型。请先导入体验包里的 v140-simulation-sample.md。</p>}
        <Button kind="primary" size="lg" disabled={blocked} onClick={() => void p.startMemoryInitialization()}>开始整理</Button>
      </div>
    );
  if (init.status === "rejected") return <p className="note note-info">候选全部没接受，资料是空的。检查仍会直接对照前文；想重新整理可以重置作品。</p>;
  const grouped = init.candidates.length > BULK_REVIEW_THRESHOLD;
  const groups: { from: number; to: number; items: MemoryInitialization["candidates"] }[] = [];
  if (grouped)
    for (const candidate of [...init.candidates].sort((a, b) => a.source.chapter_number - b.source.chapter_number)) {
      const from = Math.floor((candidate.source.chapter_number - 1) / 10) * 10 + 1;
      let group = groups.at(-1);
      if (group?.from !== from) { group = { from, to: from + 9, items: [] }; groups.push(group); }
      group.items.push(candidate);
    }
  const selectGroup = (event: ReactMouseEvent<HTMLButtonElement>, value: "accepted" | "rejected" | "clear") => {
    event.currentTarget.closest("details")?.querySelectorAll<HTMLInputElement>('input[type="radio"][data-memory-candidate-id]').forEach((input) => {
      if (value === "clear") input.checked = false; else if (input.value === value) input.checked = true;
    });
    const ids = Array.from(event.currentTarget.closest("details")?.querySelectorAll<HTMLInputElement>('input[type="radio"][data-memory-candidate-id]') ?? []).map((input) => input.dataset.memoryCandidateId!);
    setEditing((current) => { const next = new Set(current); ids.forEach((id) => next.delete(id)); return next; });
  };
  const card = (candidate: MemoryInitialization["candidates"][number]) => (
    <article key={candidate.id} className="candidate">
      <header><Tag tone={factTone[candidate.memory_type] ?? "line"}>{memoryTypeLabel(candidate.memory_type)}</Tag><span className="label">{candidate.review_priority === "core" ? "重要 · 必须决定" : "次要 · 可以稍后"}</span></header>
      <p className="candidate-fact"><strong>{candidate.subject}</strong> · {predicateLabel(candidate.predicate)}：{candidate.value}</p>
      <blockquote className="candidate-quote"><span className="label">第 {candidate.source.chapter_number} 章 · {bareChapterTitle(candidate.source.chapter_title)} · {candidate.source.label}</span>{candidate.source.text}</blockquote>
      {candidate.decision_status === "pending" ? (
        <>
          <fieldset className="radio-row">
            <legend className="sr-only">这一条怎么处理</legend>
            {(["accepted", "rejected", "edited"] as const).map((value) => (
              <label key={value}><input type="radio" name={`memory-init:${candidate.id}`} value={value} data-memory-candidate-id={candidate.id} disabled={blocked} onChange={() => choose(candidate.id, value)} />{value === "accepted" ? "接受" : value === "rejected" ? "不接受" : "改一下再接受"}</label>
            ))}
          </fieldset>
          {editing.has(candidate.id) && (
            <div className="edit-fields">
              <label className="field"><span className="field-label">类型</span><select name={`memory-init:${candidate.id}:memory_type`} defaultValue={candidate.memory_type} disabled={blocked}>{memoryTypes.map((type) => <option key={type} value={type}>{memoryTypeLabel(type)}</option>)}</select></label>
              <label className="field"><span className="field-label">对象</span><input name={`memory-init:${candidate.id}:subject`} defaultValue={candidate.subject} disabled={blocked} /></label>
              <label className="field"><span className="field-label">关系</span><PredicateSelect name={`memory-init:${candidate.id}:predicate`} value={candidate.predicate} disabled={blocked} /></label>
              <label className="field wide"><span className="field-label">内容</span><textarea name={`memory-init:${candidate.id}:value`} defaultValue={candidate.value} rows={2} disabled={blocked} /></label>
              <label className="check wide"><input type="checkbox" name={`memory-init:${candidate.id}:evidence-confirmed`} value="confirmed" disabled={blocked} />改过的内容仍然有上面这段原文做依据</label>
            </div>
          )}
        </>
      ) : (
        <div className="small-note">
          已{candidate.decision_status === "rejected" ? "不接受" : candidate.decision_status === "edited" ? "改后接受" : "接受"}。
          {candidate.decision_status === "edited" && candidate.decision?.after && <> 最终写入：{candidate.decision.after.subject} · {predicateLabel(candidate.decision.after.predicate)}：{candidate.decision.after.value}</>}
          {init.status === "draft" && <button type="button" className="link" disabled={blocked} onClick={() => void p.reopenMemoryCandidate(candidate.id, candidate.decision_status as "accepted" | "rejected" | "edited")}>重新评估</button>}
        </div>
      )}
    </article>
  );
  return (
    <form className="confirm-block" aria-label="确认整理出的事实" onSubmit={(event) => void p.submitMemoryInitialization(event)}>
      <SectionHead title="确认整理出的事实" aside={<span className="label">{p.coverage ? `重要待定 ${p.coverage.counts.core_pending} · 次要待定 ${p.coverage.counts.supporting_pending}` : `第 ${init.source_revision} 版正文`}</span>} strong />
      <p className="lede">重要的候选要全部决定；次要的可以先不管，它们不会写进资料，也不会用于检查。{grouped && " 候选较多，按每 10 章分组；可以先把一组全部选为接受或不接受，再单独改个别的。"}</p>
      {experienceSimulation && <p className="note note-info">隔离模拟环境：候选来自固定示例数据，不会调用真实模型。</p>}
      {grouped ? groups.map((group, index) => {
        const pending = group.items.filter((candidate) => candidate.decision_status === "pending");
        return (
          <details key={group.from} className="candidate-group" open={index === 0}>
            <summary><Num>{pad2(group.from)}–{pad2(group.to)}</Num><span>{group.items.length} 条{pending.length ? ` · 待定 ${pending.length}` : " · 都决定了"}</span></summary>
            {pending.length > 0 && init.status === "draft" && (
              <div className="actions group-actions">
                <Button kind="small" disabled={blocked} onClick={(event) => selectGroup(event, "accepted")}>本组都接受</Button>
                <Button kind="small" disabled={blocked} onClick={(event) => selectGroup(event, "rejected")}>本组都不接受</Button>
                <Button kind="text" disabled={blocked} onClick={(event) => selectGroup(event, "clear")}>清除选择</Button>
              </div>
            )}
            {group.items.map(card)}
          </details>
        );
      }) : init.candidates.map(card)}
      {init.status === "draft" && <Button kind="primary" size="lg" type="submit" disabled={blocked}>确认，建立第 1 版资料</Button>}
      {p.coverage?.status === "ready_partial" && <div className="note note-ok"><span>核心事实已确认；还有 {p.coverage.counts.supporting_pending} 条次要候选没决定，它们不在资料里。</span><Button kind="primary" onClick={() => go(`/projects/${p.project!.id}/workspace`)}>开始检查</Button></div>}
      {p.coverage?.status === "in_review" && p.coverage.counts.core_pending === 0 && p.coverage.counts.confirmed_core === 0 && <p className="note note-error">没有确认任何重要事实，资料还是空的；检查仍会直接对照原文。可以在某条重要候选上点「重新评估」后重新决定。</p>}
    </form>
  );
}

/** Confirmed facts whose subject names this person or setting (or one of its aliases). */
function relatedFacts(names: string[], memories: Memory[]) {
  const wanted = names.map((name) => name.trim()).filter(Boolean);
  return current(memories).filter((record) => wanted.some((name) => record.subject.includes(name) || name.includes(record.subject)));
}
function RelatedFacts({ facts, p }: { facts: Memory[]; p: ProjectState }) {
  return facts.length ? (
    <ol className="fact-list compact">
      {facts.map((record) => (
        <li key={record.id}>
          <button type="button" className="memory-source fact-chapter" disabled={!record.source} onClick={(event) => void p.openMemorySource(record, event.currentTarget)}><Num>{record.source ? pad2(record.source.chapter_number) : "—"}</Num></button>
          <span className="fact-copy"><span className="fact-value">{record.subject} · {predicateLabel(record.predicate)}：{record.value}</span></span>
        </li>
      ))}
    </ol>
  ) : <p className="small-note">资料里还没有关于它的已确认事实。</p>;
}

function PeopleView({ p }: { p: ProjectState }) {
  const [openId, setOpenId] = useState<string | null>(() => (typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("character")));
  const lastChapter = p.chapters.at(-1)?.number;
  if (!p.characters.length) return <p className="empty materials-view">还没有人物。检查正文、确认事实后，出现过的人物会记在这里。</p>;
  return (
    <div className="people materials-view">
      {p.characters.map((character) => <PersonCard key={character.id} character={character} p={p} lastChapter={lastChapter} open={openId === character.id} toggle={() => setOpenId(openId === character.id ? null : character.id)} />)}
    </div>
  );
}

function PersonCard({ character, p, lastChapter, open, toggle }: { character: Character; p: ProjectState; lastChapter?: number; open: boolean; toggle: () => void }) {
  const [aliases, setAliases] = useState<CharacterAliasSnapshot | null>(null);
  const [aliasInput, setAliasInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const projectId = p.project!.id;
  useEffect(() => {
    let live = true;
    request<CharacterAliasSnapshot>(`/projects/${projectId}/characters/${character.id}/aliases?include_archived=true`).then((next) => { if (live) setAliases(next); }).catch(() => undefined);
    return () => { live = false; };
  }, [projectId, character.id]);
  const active = aliases?.aliases.filter((item) => item.status === "active") ?? [];
  const facts = relatedFacts([character.name, ...active.map((item) => item.alias)], p.memories);
  const change = async (path: string, method: "POST" | "PATCH", body: Record<string, unknown>, done: string) => {
    if (!aliases) return;
    setBusy(true); setNotice("");
    try { setAliases(await json<CharacterAliasSnapshot>(`/projects/${projectId}/characters/${character.id}/aliases${path}`, method, { base_version: aliases.version, ...body })); setNotice(done); }
    catch (cause) { setNotice(labelError(cause)); } finally { setBusy(false); }
  };
  return (
    <article id={`character-${character.id}`} className={`person${open ? " open" : ""}`}>
      <div className="person-head">
        <h2>{character.name}</h2>
        <span className="person-identity">{character.identity || roleTypeLabel(character.role_type)}</span>
        <span className="alias-chip">{active.length ? `别名 · ${active.map((item) => item.alias).join("、")}` : "无别名"}</span>
      </div>
      <dl className="person-facts">
        <dt>{lastChapter ? `第 ${lastChapter} 章末` : "现在"}</dt><dd>{character.current_state || "正文里还没写到。"}</dd>
        <dt>还不知道</dt><dd>{character.knowledge_boundary || "正文里还没写到。"}</dd>
        {character.goal && <><dt>想要</dt><dd>{character.goal}</dd></>}
      </dl>
      <button type="button" className="link person-toggle" aria-expanded={open} onClick={toggle}>{open ? "收起" : `相关事实 ${facts.length} 条 · 别名 · 改动影响`}</button>
      {open && (
        <div className="person-detail">
          <p className="label">相关事实</p>
          <RelatedFacts facts={facts} p={p} />
          <p className="label">别名</p>
          <p className="small-note">主名：{character.name}。这里只记你确认过的称呼，系统不会把猜测写成别名。</p>
          <ul className="alias-list">
            {aliases?.aliases.map((item) => <AliasRow key={item.id} item={item} readOnly={p.readOnly} busy={busy} save={(value) => void change(`/${item.id}`, "PATCH", { alias: value }, "别名改好了。")} archive={() => void change(`/${item.id}/archive`, "POST", {}, "别名已归档，记录仍保留。")} />)}
          </ul>
          {!p.readOnly && (
            <form className="inline-form" onSubmit={(event) => { event.preventDefault(); void change("", "POST", { alias: aliasInput }, "别名记下了。").then(() => setAliasInput("")); }}>
              <input value={aliasInput} maxLength={80} onChange={(event) => setAliasInput(event.target.value)} placeholder="加一个别名" aria-label="新别名" />
              <Button kind="small" type="submit" disabled={busy || !aliasInput.trim() || active.length >= 20}>添加</Button>
            </form>
          )}
          {notice && <p className="small-note" role="status">{notice}</p>}
          <ImpactPanel character={character} p={p} />
        </div>
      )}
    </article>
  );
}

function AliasRow({ item, readOnly, busy, save, archive }: { item: CharacterAliasSnapshot["aliases"][number]; readOnly: boolean; busy: boolean; save: (value: string) => void; archive: () => void }) {
  const [value, setValue] = useState(item.alias);
  return (
    <li id={`alias-${item.id}`} className={item.status === "archived" ? "archived" : undefined}>
      <input aria-label={`别名 ${item.alias}`} value={value} disabled={readOnly || busy || item.status === "archived"} onChange={(event) => setValue(event.target.value)} />
      <span className="label">{item.status === "active" ? "使用中" : "已归档"}</span>
      {!readOnly && item.status === "active" && <><Button kind="text" disabled={busy || !value.trim() || value === item.alias} onClick={() => save(value)}>保存</Button><Button kind="text" disabled={busy} onClick={archive}>归档</Button></>}
    </li>
  );
}

/** 改动影响: what else in the story a planned change to this person would touch. Analysis only. */
function ImpactPanel({ character, p }: { character: Character; p: ProjectState }) {
  const projectId = p.project!.id;
  const [runs, setRuns] = useState<WritingAnalysisRun[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const refresh = useCallback(async () => setRuns((await request<{ runs: WritingAnalysisRun[] }>(`/projects/${projectId}/analyses?analysis_type=change_impact`)).runs ?? []), [projectId]);
  useEffect(() => { void Promise.resolve().then(refresh).catch(() => undefined); }, [refresh]);
  const activeRun = runs.find((run) => activeAnalysis(run));
  useEffect(() => {
    if (!activeRun) return;
    const timer = window.setInterval(() => void refresh().catch(() => undefined), 700);
    return () => window.clearInterval(timer);
  }, [activeRun, refresh]);
  const proposal = (run: WritingAnalysisRun) => run.proposal ?? run.analysis?.proposal ?? null;
  const mine = runs.find((run) => proposal(run)?.target_type === "character" && proposal(run)?.target_id === character.id);
  const start = async () => {
    if (!p.draft || !input.trim()) return;
    setBusy(true); setNotice("");
    try {
      await json(`/projects/${projectId}/analyses`, "POST", { analysis_type: "change_impact", draft_id: p.draft.id, draft_revision: p.draft.revision, proposal: { target_type: "character", target_id: character.id, proposed_change: input }, client_request_id: crypto.randomUUID() });
      setInput("");
      await refresh();
    } catch (cause) { setNotice(labelError(cause)); } finally { setBusy(false); }
  };
  const act = async (action: "cancel" | "retry") => {
    if (!mine) return;
    setBusy(true);
    try { await json(`/projects/${projectId}/analyses/${mine.run_id}/${action}`, "POST", { client_request_id: crypto.randomUUID() }); await refresh(); }
    catch (cause) { setNotice(labelError(cause)); } finally { setBusy(false); }
  };
  return (
    <div className="impact">
      <p className="label">改动影响 · 只分析，不修改</p>
      {!p.readOnly && (
        <div className="inline-form">
          <textarea value={input} maxLength={4000} rows={2} onChange={(event) => setInput(event.target.value)} placeholder={`例如：把${character.name}的身份改成港务调查员`} aria-label="打算怎么改" />
          <Button kind="small" disabled={busy || Boolean(activeRun) || !p.draft || !input.trim()} onClick={() => void start()}>看会影响什么</Button>
        </div>
      )}
      {activeRun && activeRun.run_id !== mine?.run_id && <p className="small-note">另一项影响分析正在进行，完成后才能开始新的。</p>}
      {mine && (
        <div className="impact-result">
          <p className="small-note">打算：{proposal(mine)?.proposed_change} · {mine.is_stale ? "依据已变" : stageLabel(mine.status)}</p>
          {mine.analysis && (
            <>
              <strong>{mine.analysis.summary}</strong>
              {mine.analysis.evidence_status === "insufficient" && <p className="small-note">没有找到有依据的影响。</p>}
              {mine.analysis.items.map((item, index) => "impact" in item ? (
                <div key={index} className="impact-item"><strong>{readableKeys(item.label)}</strong><p>{item.impact}</p><p className="small-note">{item.evidence.map((source) => `${readableKeys(source.label)}（${sourceKindLabel(source.source_type)}）`).join("、")}</p></div>
              ) : null)}
            </>
          )}
          {!p.readOnly && <span className="actions">{activeAnalysis(mine) && <Button kind="small" disabled={busy} onClick={() => void act("cancel")}>取消</Button>}{retryableAnalysis(mine) && !mine.is_stale && <Button kind="small" disabled={busy} onClick={() => void act("retry")}>重试</Button>}</span>}
        </div>
      )}
      {notice && <p className="small-note" role="status">{notice}</p>}
    </div>
  );
}

type Category = { id: string | null; key: string; name: string; builtin: boolean; count: number };
type CategoryView = { categories: Category[]; membership: Record<string, string> };
const builtinKeys = ["location", "rule", "organization", "object", "term"];

function SettingsView({ p }: { p: ProjectState }) {
  const projectId = p.project!.id;
  const [view, setView] = useState<CategoryView | null>(null);
  const [managing, setManaging] = useState(false);
  const [names, setNames] = useState<Record<string, string>>({});
  const [newName, setNewName] = useState("");
  const [openId, setOpenId] = useState<string | null>(() => (typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("world")));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    request<CategoryView>(`/projects/${projectId}/setting-categories`).then((next) => { if (live) setView(next); }).catch(() => undefined);
    return () => { live = false; };
  }, [projectId]);
  const categories = view?.categories ?? builtinKeys.map((key) => ({ id: null, key, name: worldTypeLabel(key), builtin: true, count: p.world.filter((entry) => entry.entry_type === key).length }));
  const membership = view?.membership ?? Object.fromEntries(p.world.map((entry) => [entry.id, entry.entry_type]));
  const change = async (payload: Record<string, unknown>) => {
    setBusy(true); setError("");
    try { const next = await json<CategoryView>(`/projects/${projectId}/setting-categories`, "POST", payload); setView(next); return next; }
    catch (cause) { setError(labelError(cause)); return null; } finally { setBusy(false); }
  };
  const editable = !p.readOnly;
  const shown = categories.filter((category) => p.world.some((entry) => membership[entry.id] === category.key));
  if (!p.world.length) return <p className="empty materials-view">还没有设定。检查正文、确认事实后，地点、规则和物品会记在这里。</p>;
  return (
    <div className="materials-view">
      {editable && <div className="view-tools"><Button kind="small" expanded={managing} onClick={() => setManaging((value) => !value)}>{managing ? "完成" : "管理分类"}</Button></div>}
      {error && <p className="inline-error" role="alert">{error}</p>}
      {managing && editable && (
        <section className="category-editor" aria-label="管理分类">
          <p className="small-note">分类由你决定：可以改名、删除，也可以新建。删除分类不会删除里面的设定，它们会回到原来的类别。</p>
          <ul>
            {categories.filter((item) => item.key !== "other").map((item) => (
              <li key={item.key}>
                <input aria-label={`${item.name} 的名称`} value={names[item.key] ?? item.name} maxLength={20} disabled={busy} onChange={(event) => setNames((all) => ({ ...all, [item.key]: event.target.value }))} />
                <span className="label">{item.count} 条</span>
                <Button kind="text" disabled={busy || !(names[item.key] ?? item.name).trim() || (names[item.key] ?? item.name) === item.name} onClick={() => void change({ action: "rename", category: item.key, name: names[item.key] })}>改名</Button>
                <Button kind="text" disabled={busy} onClick={() => void change({ action: "delete", category: item.key })}>删除</Button>
              </li>
            ))}
          </ul>
          <form className="inline-form" onSubmit={(event) => { event.preventDefault(); void change({ action: "create", name: newName }).then((next) => { if (next) setNewName(""); }); }}>
            <input aria-label="新分类名称" value={newName} maxLength={20} placeholder="新分类，例如：功法、门派" disabled={busy} onChange={(event) => setNewName(event.target.value)} />
            <Button kind="small" type="submit" disabled={busy || !newName.trim()}>新建</Button>
          </form>
        </section>
      )}
      <div className="setting-grid">
        {shown.map((category) => {
          const entries = p.world.filter((entry) => membership[entry.id] === category.key);
          return (
            <section key={category.key} className="setting-group">
              <div className="setting-group-head"><h2>{category.name}</h2><Num>{entries.length}</Num></div>
              {entries.length ? entries.map((entry) => <SettingEntry key={entry.id} entry={entry} p={p} categories={categories} membership={membership} editable={editable} busy={busy} open={openId === entry.id} toggle={() => setOpenId(openId === entry.id ? null : entry.id)} assign={(next) => void change({ action: "assign", entry_id: entry.id, category: next === entry.entry_type && builtinKeys.includes(next) ? null : next })} />) : <p className="small-note setting-empty">还没有。</p>}
            </section>
          );
        })}
      </div>
    </div>
  );
}

function SettingEntry({ entry, p, categories, membership, editable, busy, open, toggle, assign }: { entry: WorldEntry; p: ProjectState; categories: Category[]; membership: Record<string, string>; editable: boolean; busy: boolean; open: boolean; toggle: () => void; assign: (category: string) => void }) {
  const facts = open ? relatedFacts([entry.name], p.memories) : [];
  return (
    <div id={`world-${entry.id}`} className={`setting${open ? " open" : ""}`}>
      <button type="button" className="setting-name" aria-expanded={open} onClick={toggle}><strong>{entry.name}</strong><span>{entry.summary || "还没有摘要。"}</span></button>
      {open && (
        <div className="setting-detail">
          {editable && (
            <label className="field"><span className="field-label">放在</span>
              <select value={membership[entry.id] ?? entry.entry_type} disabled={busy} onChange={(event) => assign(event.target.value)}>
                {categories.filter((item) => item.key !== "other").map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}
              </select>
            </label>
          )}
          <p className="label">相关事实</p>
          <RelatedFacts facts={facts} p={p} />
        </div>
      )}
    </div>
  );
}

type ThreadEditor = { title: string; description: string; status: ForeshadowRecord["status"]; planted: string; resolved: string };
const emptyEditor: ThreadEditor = { title: "", description: "", status: "planted", planted: "", resolved: "" };
const splitRef = (value: string) => { const [chapter_id, source_span_id] = value.split("|"); return { chapter_id: chapter_id || null, source_span_id: source_span_id || null }; };
const recordEditor = (record: ForeshadowRecord): ThreadEditor => ({ title: record.title, description: record.description, status: record.status, planted: record.planted ? `${record.planted.chapter_id}|${record.planted.source_span_id ?? ""}` : "", resolved: record.resolved ? `${record.resolved.chapter_id}|${record.resolved.source_span_id ?? ""}` : "" });
const candidateEditor = (candidate: ForeshadowCandidate): ThreadEditor => ({ title: candidate.title, description: candidate.description, status: candidate.suggested_status, planted: candidate.planted_chapter_id ? `${candidate.planted_chapter_id}|${candidate.planted_source_span_id ?? ""}` : "", resolved: candidate.resolved_chapter_id ? `${candidate.resolved_chapter_id}|${candidate.resolved_source_span_id ?? ""}` : "" });
const payload = (value: ThreadEditor) => { const planted = splitRef(value.planted), resolved = splitRef(value.resolved); return { title: value.title, description: value.description, status: value.status, planted_chapter_id: planted.chapter_id, planted_source_span_id: planted.source_span_id, resolved_chapter_id: resolved.chapter_id, resolved_source_span_id: resolved.source_span_id }; };

function ChapterRefSelect({ label, value, setValue, chapters, disabled }: { label: string; value: string; setValue: (value: string) => void; chapters: Chapter[]; disabled: boolean }) {
  return (
    <label className="field"><span className="field-label">{label}</span>
      <select value={value} disabled={disabled} onChange={(event) => setValue(event.target.value)}>
        <option value="">不关联</option>
        {chapters.map((chapter) => {
          const spans = chapter.source_spans ?? [];
          const name = `第 ${chapter.number} 章 · ${bareChapterTitle(chapter.title)}`;
          if (spans.length <= 1) return <option key={chapter.id} value={spans[0] && value === `${chapter.id}|${spans[0].span_id}` ? value : `${chapter.id}|`}>{name}</option>;
          return <optgroup key={chapter.id} label={name}><option value={`${chapter.id}|`}>整章</option>{spans.map((span) => <option key={span.span_id} value={`${chapter.id}|${span.span_id}`}>{span.label === "chapter_revision" ? "修订后的正文" : span.label}{span.is_current === false ? "（修订前）" : ""}</option>)}</optgroup>;
        })}
      </select>
    </label>
  );
}

/** 伏笔: threads planted in the text, how long they have run, and when they are resolved. */
function ThreadsView({ p, go }: { p: ProjectState; go: (href: string) => void }) {
  const projectId = p.project!.id;
  const [snapshot, setSnapshot] = useState<ForeshadowSnapshot | null>(null);
  const [scans, setScans] = useState<WritingAnalysisRun[]>([]);
  const [editor, setEditor] = useState<ThreadEditor | null>(null);
  const [editing, setEditing] = useState<{ id: string; version: number } | null>(null);
  const [edits, setEdits] = useState<Record<string, ThreadEditor>>({});
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const refresh = useCallback(async () => {
    const [records, scan] = await Promise.all([
      request<ForeshadowSnapshot>(`/projects/${projectId}/foreshadows?include_archived=true`),
      request<{ runs: WritingAnalysisRun[] }>(`/projects/${projectId}/analyses?analysis_type=foreshadow_scan&limit=20`),
    ]);
    setSnapshot(records); setScans(scan.runs ?? []);
  }, [projectId]);
  useEffect(() => { void Promise.resolve().then(refresh).catch((cause) => setNotice(labelError(cause))); }, [refresh, p.draft?.revision]);
  const scanning = scans.find(activeAnalysis);
  useEffect(() => {
    if (!scanning) return;
    const timer = window.setInterval(() => void refresh().catch(() => undefined), 700);
    return () => window.clearInterval(timer);
  }, [scanning, refresh]);
  const current = p.draft?.chapter_number ?? p.project!.current_draft.chapter_number;
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!snapshot || !editor) return;
    setBusy("record"); setNotice(""); setConflict(false);
    try {
      const next = editing
        ? await json<ForeshadowSnapshot>(`/projects/${projectId}/foreshadows/${editing.id}`, "PATCH", { base_version: editing.version, ...payload(editor) })
        : await json<ForeshadowSnapshot>(`/projects/${projectId}/foreshadows`, "POST", { base_foreshadow_version: snapshot.foreshadow_version, ...payload(editor) });
      setSnapshot(next); setEditor(null); setEditing(null);
      setNotice(editing ? "伏笔改好了。" : "伏笔记下了。");
      await refresh();
    } catch (cause) { setConflict((cause as ApiFailure).code === "foreshadow_version_conflict"); setNotice(labelError(cause)); } finally { setBusy(""); }
  };
  const loadLatest = async () => {
    setBusy("reload");
    try {
      const latest = await request<ForeshadowSnapshot>(`/projects/${projectId}/foreshadows?include_archived=true`);
      setSnapshot(latest);
      if (editing) { const record = latest.records.find((item) => item.id === editing.id); if (record) setEditing({ id: record.id, version: record.version }); }
      setConflict(false);
      setNotice("载入了最新版本；你填的内容还在，核对后再保存。");
    } catch (cause) { setNotice(labelError(cause)); } finally { setBusy(""); }
  };
  const archive = async (record: ForeshadowRecord) => {
    setBusy(record.id); setNotice("");
    try { setSnapshot(await json<ForeshadowSnapshot>(`/projects/${projectId}/foreshadows/${record.id}/archive`, "POST", { base_version: record.version })); setNotice("已归档，记录仍可追溯。"); }
    catch (cause) { setNotice(labelError(cause)); } finally { setBusy(""); }
  };
  const resolveRecord = (record: ForeshadowRecord) => {
    setEditing({ id: record.id, version: record.version });
    setEditor({ ...recordEditor(record), status: "resolved" });
    window.setTimeout(() => formRef.current?.scrollIntoView({ block: "center", behavior: "smooth" }), 0);
  };
  const scan = async () => {
    if (!p.draft) return;
    if (p.dirty) { setNotice("先保存草稿；扫描只看已保存的版本。"); return; }
    setBusy("scan"); setNotice("");
    try { await json(`/projects/${projectId}/analyses`, "POST", { analysis_type: "foreshadow_scan", draft_id: p.draft.id, draft_revision: p.draft.revision }); setNotice("开始扫描了；找到的候选不会自动记下。"); await refresh(); }
    catch (cause) { setNotice(labelError(cause)); } finally { setBusy(""); }
  };
  const decide = async (run: WritingAnalysisRun, candidate: ForeshadowCandidate, decision: "accepted" | "edited" | "rejected") => {
    if (!snapshot) return;
    setBusy(candidate.id); setNotice("");
    try {
      await json(`/projects/${projectId}/analyses/${run.run_id}/foreshadow-candidates/${candidate.id}/decision`, "POST", { base_foreshadow_version: snapshot.foreshadow_version, decision, ...(decision === "edited" ? { edited: payload(edits[candidate.id] ?? candidateEditor(candidate)) } : {}) });
      setNotice(decision === "rejected" ? "没记这一条。" : "记下了。");
      await refresh();
    } catch (cause) { setNotice(labelError(cause)); } finally { setBusy(""); }
  };
  const records = snapshot?.records ?? [];
  const open = records.filter((record) => !record.archived_at && record.status !== "resolved" && record.status !== "abandoned").sort((a, b) => (a.planted?.chapter_number ?? 999) - (b.planted?.chapter_number ?? 999));
  const closed = records.filter((record) => !open.includes(record));
  const pendingCandidates = scans.flatMap((run) => ((run.analysis?.candidates ?? []) as ForeshadowCandidate[]).filter((candidate) => candidate.decision_status === "pending" && !run.is_stale).map((candidate) => ({ run, candidate })));
  const link = (path: string | undefined) => (event: ReactMouseEvent<HTMLAnchorElement>) => { if (!path || event.metaKey || event.ctrlKey) return; event.preventDefault(); go(path); };

  const row = (record: ForeshadowRecord) => (
    <li key={record.id} id={`foreshadow-${record.id}`} className={record.archived_at ? "archived" : undefined}>
      <span className="thread-planted"><span className="label">埋于</span><Num>{record.planted ? pad2(record.planted.chapter_number) : "—"}</Num></span>
      <span className="thread-copy">
        <strong>{record.title}</strong>
        <span>{record.description}</span>
        <span className="thread-links">
          {record.planted && <a href={record.planted.source_path} onClick={link(record.planted.source_path)}>埋下：第 {record.planted.chapter_number} 章{record.planted.source_label ? ` · ${record.planted.source_label}` : ""}</a>}
          {record.resolved && <a href={record.resolved.source_path} onClick={link(record.resolved.source_path)}>回收：第 {record.resolved.chapter_number} 章</a>}
        </span>
      </span>
      <span className="thread-side">
        <span className="thread-age">{record.archived_at ? "已归档" : record.status === "resolved" ? "已回收" : record.status === "abandoned" ? "放弃了" : record.planted ? `${foreshadowStatusLabel[record.status]} · 已过 ${Math.max(0, current - record.planted.chapter_number)} 章` : foreshadowStatusLabel[record.status]}</span>
        {!p.readOnly && !record.archived_at && (
          <span className="actions">
            {record.status !== "resolved" && <Button kind="text" disabled={Boolean(busy)} onClick={() => resolveRecord(record)}>标为已回收</Button>}
            <Button kind="text" disabled={Boolean(busy)} onClick={() => { setEditing({ id: record.id, version: record.version }); setEditor(recordEditor(record)); window.setTimeout(() => formRef.current?.scrollIntoView({ block: "center", behavior: "smooth" }), 0); }}>编辑</Button>
            <Button kind="text" disabled={Boolean(busy)} onClick={() => void archive(record)}>归档</Button>
          </span>
        )}
      </span>
    </li>
  );

  return (
    <div className="materials-view threads">
      {!p.readOnly && (
        <div className="view-tools">
          <Button kind="small" disabled={Boolean(busy) || Boolean(scanning) || !p.draft || p.dirty} onClick={() => void scan()}>{scanning ? "正在扫描…" : "从正文里找伏笔"}</Button>
          <Button kind="small" disabled={Boolean(busy)} onClick={() => { setEditing(null); setEditor({ ...emptyEditor }); window.setTimeout(() => formRef.current?.scrollIntoView({ block: "center", behavior: "smooth" }), 0); }}>记一条伏笔</Button>
        </div>
      )}
      {notice && <p className="small-note" role="status">{notice}</p>}
      {conflict && <div className="note note-warn" role="alert"><span>伏笔在别处更新过；你填的内容还在。载入最新版本，核对后再保存。</span><Button kind="text" disabled={Boolean(busy)} onClick={() => void loadLatest()}>载入最新版本</Button></div>}
      {editor && !p.readOnly && (
        <form ref={formRef} className="thread-form" onSubmit={(event) => void save(event)}>
          <SectionHead level={3} title={editing ? "编辑伏笔" : "记一条伏笔"} />
          <label className="field"><span className="field-label">标题</span><input value={editor.title} maxLength={120} onChange={(event) => setEditor({ ...editor, title: event.target.value })} placeholder="简短的标题" /></label>
          <label className="field"><span className="field-label">说明</span><textarea rows={3} value={editor.description} maxLength={1200} onChange={(event) => setEditor({ ...editor, description: event.target.value })} placeholder="这条线索是什么，打算怎么展开" /></label>
          <div className="field-row">
            <label className="field"><span className="field-label">状态</span><select value={editor.status} onChange={(event) => setEditor({ ...editor, status: event.target.value as ForeshadowRecord["status"] })}>{Object.entries(foreshadowStatusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <ChapterRefSelect label="埋在" value={editor.planted} setValue={(value) => setEditor({ ...editor, planted: value })} chapters={p.chapters} disabled={Boolean(busy)} />
            <ChapterRefSelect label="回收于" value={editor.resolved} setValue={(value) => setEditor({ ...editor, resolved: value })} chapters={p.chapters} disabled={Boolean(busy)} />
          </div>
          <div className="form-actions">
            <Button kind="primary" type="submit" disabled={Boolean(busy) || !editor.title.trim() || !editor.description.trim()}>{editing ? "保存" : "记下"}</Button>
            <Button kind="text" onClick={() => { setEditor(null); setEditing(null); }}>取消</Button>
          </div>
        </form>
      )}
      {pendingCandidates.length > 0 && (
        <section className="candidates" aria-label="扫描找到的伏笔">
          <SectionHead level={3} title="扫描找到的伏笔" aside={<span className="label">{pendingCandidates.length} 条待定 · 不会自动记下</span>} />
          {pendingCandidates.map(({ run, candidate }) => {
            const value = edits[candidate.id] ?? candidateEditor(candidate);
            return (
              <article key={candidate.id} id={`foreshadow-candidate-${candidate.id}`} className="candidate">
                <p className="candidate-fact"><strong>{candidate.title}</strong> · {foreshadowStatusLabel[candidate.suggested_status]}</p>
                <p>{candidate.description}</p>
                <p className="small-note">{candidate.evidence.map((source) => readableKeys(source.label)).join("、")}</p>
                {!p.readOnly && (
                  <>
                    <details className="edit-toggle"><summary>改一下再记</summary>
                      <div className="edit-fields">
                        <label className="field wide"><span className="field-label">标题</span><input value={value.title} maxLength={120} onChange={(event) => setEdits((all) => ({ ...all, [candidate.id]: { ...value, title: event.target.value } }))} /></label>
                        <label className="field wide"><span className="field-label">说明</span><textarea rows={2} value={value.description} maxLength={1200} onChange={(event) => setEdits((all) => ({ ...all, [candidate.id]: { ...value, description: event.target.value } }))} /></label>
                        <Button kind="small" disabled={Boolean(busy) || !value.title.trim() || !value.description.trim()} onClick={() => void decide(run, candidate, "edited")}>改好了，记下</Button>
                      </div>
                    </details>
                    <div className="actions"><Button kind="primary" disabled={Boolean(busy)} onClick={() => void decide(run, candidate, "accepted")}>记下</Button><Button kind="text" disabled={Boolean(busy)} onClick={() => void decide(run, candidate, "rejected")}>不记</Button></div>
                  </>
                )}
              </article>
            );
          })}
        </section>
      )}
      {scans.filter((run) => ["failed", "timed_out", "cancelled"].includes(run.status)).slice(0, 1).map((run) => <p key={run.run_id} className="small-note">上次扫描没有完成。{labelRunFailure(run.error_code, "扫描")}</p>)}
      {snapshot === null ? <p className="loading">正在读取…</p> : open.length ? <ol className="thread-list">{open.map(row)}</ol> : <p className="empty">没有未回收的伏笔。</p>}
      {closed.length > 0 && (
        <>
          <button type="button" className="link" aria-expanded={showClosed} onClick={() => setShowClosed((value) => !value)}>{showClosed ? "收起" : `已回收、放弃或归档的 ${closed.length} 条`}</button>
          {showClosed && <ol className="thread-list closed">{closed.map(row)}</ol>}
        </>
      )}
    </div>
  );
}

/** 问一问: questions about the written story, answered with where the answer comes from. */
function AskView({ p, go }: { p: ProjectState; go: (href: string) => void }) {
  const projectId = p.project!.id;
  const [runs, setRuns] = useState<WritingAnalysisRun[]>([]);
  const [question, setQuestion] = useState("");
  const [scope, setScope] = useState<("confirmed" | "written" | "planned")[]>(["confirmed", "written", "planned"]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const refresh = useCallback(async () => setRuns((await request<{ runs: WritingAnalysisRun[] }>(`/projects/${projectId}/analyses?analysis_type=story_qa&limit=20`)).runs ?? []), [projectId]);
  useEffect(() => { void Promise.resolve().then(refresh).catch((cause) => setNotice(labelError(cause))); }, [refresh]);
  const asking = runs.find(activeAnalysis);
  useEffect(() => {
    if (!asking) return;
    const timer = window.setInterval(() => void refresh().catch(() => undefined), 700);
    return () => window.clearInterval(timer);
  }, [asking, refresh]);
  const ask = async (text: string) => {
    if (!p.draft || !text.trim()) return;
    if (p.dirty) { setNotice("先保存草稿；问一问只看已保存的版本。"); return; }
    setBusy(true); setNotice("");
    try { await json(`/projects/${projectId}/analyses`, "POST", { analysis_type: "story_qa", draft_id: p.draft.id, draft_revision: p.draft.revision, question: text, scope }); setQuestion(""); await refresh(); }
    catch (cause) { setNotice(labelError(cause)); } finally { setBusy(false); }
  };
  const runAction = async (run: WritingAnalysisRun, action: "cancel" | "retry") => {
    setBusy(true); setNotice("");
    try { await json(`/projects/${projectId}/analyses/${run.run_id}/${action}`, "POST", { client_request_id: crypto.randomUUID() }); await refresh(); }
    catch (cause) { setNotice(labelError(cause)); } finally { setBusy(false); }
  };
  const toggle = (value: "confirmed" | "written" | "planned") => setScope((all) => (all.includes(value) ? (all.length === 1 ? all : all.filter((item) => item !== value)) : [...all, value]));
  const names = p.characters.slice(0, 2).map((character) => character.name);
  const suggestions = [names[0] ? `${names[0]}现在在哪里？` : "", names[1] ? `${names[1]}知道哪些事？` : "", p.world[0] ? `${p.world[0].name}有什么规则？` : ""].filter(Boolean);
  const link = (path: string | undefined) => (event: ReactMouseEvent<HTMLAnchorElement>) => { if (!path || event.metaKey || event.ctrlKey) return; event.preventDefault(); go(path); };
  return (
    <div className="materials-view ask">
      {!p.readOnly && (
        <>
          <form className="ask-form" onSubmit={(event) => { event.preventDefault(); void ask(question); }}>
            <label htmlFor="ask-input" className="sr-only">问一个关于正文的问题</label>
            <input id="ask-input" value={question} maxLength={1000} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：罗盘现在在谁手里？" />
            <button type="submit" disabled={busy || Boolean(asking) || !question.trim() || !p.draft || p.dirty}>{asking ? "…" : "问"}</button>
          </form>
          <div className="ask-options">
            {suggestions.map((text) => <button key={text} type="button" className="chip small" disabled={busy || Boolean(asking)} onClick={() => void ask(text)}>{text}</button>)}
            <span className="ask-scope">
              <span className="label">依据</span>
              {(["confirmed", "written", "planned"] as const).map((value) => <label key={value} className="check"><input type="checkbox" checked={scope.includes(value)} onChange={() => toggle(value)} />{qaLayerLabel[value]}</label>)}
            </span>
          </div>
        </>
      )}
      {notice && <p className="small-note" role="status">{notice}</p>}
      {runs.length ? runs.map((run) => (
        <article key={run.run_id} className={`answer${run.is_stale ? " stale" : ""}`}>
          <p className="answer-q">{run.question || "问题"}<span className="label"> · {run.is_stale ? "正文改过，回答可能过时" : qaStatusLabel[run.analysis?.answer_status ?? ""] ?? stageLabel(run.status)} · {timeLabel(run.created_at)}</span></p>
          {activeAnalysis(run) && <p className="small-note">{stageLabel(run.stage)}…</p>}
          {["failed", "timed_out", "cancelled"].includes(run.status) && <p className="inline-error">{labelRunFailure(run.error_code, "分析")}</p>}
          {run.analysis && (
            <>
              <p className="answer-text">{run.analysis.answer}</p>
              {run.analysis.findings?.map((finding, index) => (
                <div key={index} className={`answer-finding stance-${finding.stance}`}>
                  <span className="label">{qaLayerLabel[finding.layer]} · {qaStanceLabel[finding.stance]}</span>
                  <p>{finding.text}</p>
                  {finding.evidence.map((source) => (
                    <a key={`${source.source_type}:${source.source_id}`} className="answer-source" href={(source as { source_path?: string }).source_path} onClick={link((source as { source_path?: string }).source_path)}>
                      <strong>{readableKeys(source.label)}</strong><span>{source.excerpt}</span>
                    </a>
                  ))}
                </div>
              ))}
              <p className="small-note">只根据已保存的内容回答{run.scope?.includes("planned") ? "，包括计划" : "，不包括计划和没保存的草稿"}。</p>
            </>
          )}
          {!p.readOnly && (activeAnalysis(run) || retryableAnalysis(run)) && (
            <span className="actions">
              {activeAnalysis(run) && <Button kind="small" disabled={busy} onClick={() => void runAction(run, "cancel")}>取消</Button>}
              {retryableAnalysis(run) && !run.is_stale && <Button kind="small" disabled={busy} onClick={() => void runAction(run, "retry")}>重试</Button>}
            </span>
          )}
        </article>
      )) : <p className="empty">问一个关于已写内容的问题，比如谁在哪里、谁知道什么、某条规则是什么。回答会附上出处。</p>}
    </div>
  );
}
