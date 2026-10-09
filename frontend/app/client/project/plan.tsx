"use client";

import { FormEvent, useEffect, useState } from "react";
import { json, labelError, request, type ApiFailure } from "../../api";
import type { AuthorCharacterPlan, AuthorStoryPlan, AuthorWorldPlan } from "../../model";
import { roleTypeLabel, storyPlanStatusLabel, worldTypeLabel } from "../labels";
import { Button, Dialog, Num, PageHead, pad2, Tabs, Tag } from "../ui";
import type { PageProps } from "./frame";
import type { ProjectState } from "./use-project";

type Kind = "story" | "character" | "world";
type Plan =
  | { kind: "story"; item: AuthorStoryPlan }
  | { kind: "character"; item: AuthorCharacterPlan }
  | { kind: "world"; item: AuthorWorldPlan };
const kindLabel: Record<Kind, string> = { story: "情节", character: "人物", world: "设定" };
const endpoint: Record<Kind, string> = { story: "story-plans", character: "character-plans", world: "world-plans" };
const planTitle = (plan: Plan) => (plan.kind === "story" ? plan.item.title : plan.item.name);
const planSummary = (plan: Plan) =>
  plan.kind === "story" ? plan.item.summary || plan.item.goal
    : plan.kind === "character" ? [plan.item.goal, plan.item.planned_state].filter(Boolean).join("；") || plan.item.notes
      : plan.item.description;
const conflictMessage = (cause: unknown) => labelError(cause);

/** 计划: what is not written yet, grouped by the chapter it is meant for. Used as reference by checks, never as fact. */
export function PlanPage({ p, go, notices }: PageProps) {
  const project = p.project!;
  const context = p.authorContext;
  const [filter, setFilter] = useState<"all" | Kind>(() => {
    if (typeof window === "undefined") return "all";
    const requested = new URLSearchParams(window.location.search).get("kind");
    return requested === "story" || requested === "character" || requested === "world" ? requested : "all";
  });
  const [considering, setConsidering] = useState<Set<string>>(() => new Set());
  const [openId, setOpenId] = useState<string | null>(() => (typeof window !== "undefined" && window.location.hash.startsWith("#plan-") ? window.location.hash.slice(6) : null));
  const [dialog, setDialog] = useState<{ kind: Kind; item: Plan["item"] | null } | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<Plan | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  useEffect(() => {
    let live = true;
    request<{ considering: { kind: Kind; plan_id: string }[] }>(`/projects/${project.id}/plan-states`).then((result) => { if (live) setConsidering(new Set(result.considering.map((item) => `${item.kind}:${item.plan_id}`))); }).catch(() => undefined);
    return () => { live = false; };
  }, [project.id]);
  const all: Plan[] = context ? [
    ...context.story_plans.map((item) => ({ kind: "story" as const, item })),
    ...context.character_plans.map((item) => ({ kind: "character" as const, item })),
    ...context.world_plans.map((item) => ({ kind: "world" as const, item })),
  ] : [];
  const active = all.filter((plan) => !plan.item.archived);
  const archived = all.filter((plan) => plan.item.archived);
  const shown = active.filter((plan) => filter === "all" || plan.kind === filter);
  const isWeighing = (plan: Plan) => considering.has(`${plan.kind}:${plan.item.id}`);
  const decidedCount = active.filter((plan) => !isWeighing(plan)).length;
  const draftNumber = p.draft?.chapter_number ?? project.current_draft.chapter_number;
  const chapters = [...new Set(shown.filter((plan) => plan.kind === "story" && plan.item.target_chapter_number != null).map((plan) => (plan.item as AuthorStoryPlan).target_chapter_number!))].sort((a, b) => a - b);
  const groups = [
    ...chapters.map((chapter) => ({ key: String(chapter), chapter, items: shown.filter((plan) => plan.kind === "story" && plan.item.target_chapter_number === chapter) })),
    { key: "any", chapter: null as number | null, items: shown.filter((plan) => plan.kind !== "story" || plan.item.target_chapter_number == null) },
  ].filter((group) => group.items.length);
  const blocked = p.readOnly || Boolean(p.authorBusy) || !context;

  const toggleConsidering = async (plan: Plan) => {
    setError("");
    try {
      const result = await json<{ considering: boolean }>(`/projects/${project.id}/plan-states`, "POST", { kind: plan.kind, plan_id: plan.item.id, considering: !isWeighing(plan) });
      setConsidering((current) => { const copy = new Set(current); const key = `${plan.kind}:${plan.item.id}`; if (result.considering) copy.add(key); else copy.delete(key); return copy; });
    } catch (cause) { setError(labelError(cause)); }
  };
  const move = async (plan: Plan, offset: -1 | 1) => {
    if (!context) return;
    const list = active.filter((item) => item.kind === plan.kind);
    const index = list.findIndex((item) => item.item.id === plan.item.id), next = index + offset;
    if (index < 0 || next < 0 || next >= list.length) return;
    const ids = list.map((item) => item.item.id);
    [ids[index], ids[next]] = [ids[next], ids[index]];
    setError(""); setFeedback("");
    try { await p.mutateAuthorContext(`${endpoint[plan.kind]}/reorder`, "POST", { base_author_context_version: context.author_context_version, ordered_ids: ids }, "正在调整顺序"); setFeedback("顺序调整好了。"); }
    catch (cause) { setError(conflictMessage(cause)); }
  };
  const archive = async () => {
    if (!context || !archiveTarget) return;
    setError(""); setFeedback("");
    try {
      await p.mutateAuthorContext(`${endpoint[archiveTarget.kind]}/${archiveTarget.item.id}/archive`, "POST", { base_author_context_version: context.author_context_version, confirm: true }, "正在归档");
      setFeedback("已归档。");
      setArchiveTarget(null);
    } catch (cause) { setError(conflictMessage(cause)); }
  };
  const compare = () => { void p.startAnalysis("plan_alignment").then(() => go(`/projects/${project.id}/workspace`)); };

  return (
    <section className="page plan">
      {notices}
      <PageHead
        title="计划"
        lede="还没写进正文的打算。检查时只作参考，不当成事实。"
        rule={false}
        aside={!p.readOnly && (
          <div className="head-actions-stack">
            <div className="actions">
              <Button size="lg" disabled={blocked} onClick={() => setDialog({ kind: filter === "all" ? "story" : filter, item: null })}>新建计划</Button>
              <Button kind="primary" size="lg" disabled={p.analysisBusy === "plan_alignment" || !decidedCount || !p.draft || p.dirty} title={decidedCount ? undefined : "还没有已定的计划；「考虑中」的不参与对照"} onClick={compare}>{p.analysisBusy === "plan_alignment" ? "正在对照" : "对照正文"}</Button>
            </div>
            <span className="small-note">只对照「已定」的计划，结果显示在写作页</span>
          </div>
        )}
      />
      <Tabs<"all" | Kind>
        label="计划分类"
        size="md"
        value={filter}
        onChange={(next) => { setFilter(next); try { window.history.replaceState(window.history.state, "", `/projects/${project.id}/plan${next === "all" ? "" : `?kind=${next}`}`); } catch { /* still switches */ } }}
        items={[{ id: "all", label: "全部", count: active.length }, ...(["story", "character", "world"] as Kind[]).map((kind) => ({ id: kind, label: kindLabel[kind], count: active.filter((plan) => plan.kind === kind).length }))]}
        trailing={<span className="plan-legend"><span><i className="key decided" />已定</span><span><i className="key weighing" />考虑中</span></span>}
      />
      {error && <p className="note note-error" role="alert">{error}</p>}
      {feedback && <p className="small-note" role="status">{feedback}</p>}
      {!context ? <p className="loading">正在读取…</p> : groups.length ? groups.map((group) => (
        <section key={group.key} className="plan-group">
          <div className="plan-group-label">
            <Num className={group.chapter === draftNumber ? "blue" : undefined}>{group.chapter == null ? "—" : pad2(group.chapter)}</Num>
            <span>{group.chapter == null ? "不限章节" : group.chapter === draftNumber ? "正在写" : group.chapter === draftNumber + 1 ? "下一章" : group.chapter < draftNumber ? "已经写过" : ""}</span>
          </div>
          <div className="plan-items">
            {group.items.map((plan) => {
              const weighing = isWeighing(plan);
              const open = openId === plan.item.id;
              const sameKind = active.filter((item) => item.kind === plan.kind);
              const index = sameKind.findIndex((item) => item.item.id === plan.item.id);
              return (
                <article key={plan.item.id} id={`plan-${plan.item.id}`} className={`plan-card${weighing ? " weighing" : ""}${open ? " open" : ""}`}>
                  <button type="button" className="plan-card-main" aria-expanded={open} onClick={() => setOpenId(open ? null : plan.item.id)}>
                    <span className="plan-card-tags">
                      <span className="kind-tag">{kindLabel[plan.kind]}{plan.kind === "character" ? ` · ${roleTypeLabel(plan.item.role_type)}` : plan.kind === "world" ? ` · ${worldTypeLabel(plan.item.category)}` : ""}</span>
                      {weighing ? <Tag tone="considering">考虑中</Tag> : <Tag tone="solid">已定</Tag>}
                      {plan.kind === "story" && plan.item.status !== "planned" && <span className="label">{storyPlanStatusLabel[plan.item.status]}</span>}
                    </span>
                    <span className="plan-card-title">{planTitle(plan)}</span>
                    {planSummary(plan) && <span className="plan-card-summary">{planSummary(plan)}</span>}
                  </button>
                  {open && (
                    <div className="plan-card-more">
                      {plan.kind === "story" && plan.item.goal && plan.item.summary && <p><span className="label">想达到 · </span>{plan.item.goal}</p>}
                      {plan.kind !== "story" && plan.item.notes && <p><span className="label">备注 · </span>{plan.item.notes}</p>}
                      {!p.readOnly && (
                        <div className="actions">
                          <Button kind="primary" disabled={blocked} onClick={() => setDialog({ kind: plan.kind, item: plan.item })}>编辑</Button>
                          <Button kind="text" disabled={blocked} onClick={() => void toggleConsidering(plan)}>{weighing ? "定下来" : "放到考虑中"}</Button>
                          <Button kind="text" disabled={blocked || index <= 0} onClick={() => void move(plan, -1)}>上移</Button>
                          <Button kind="text" disabled={blocked || index < 0 || index >= sameKind.length - 1} onClick={() => void move(plan, 1)}>下移</Button>
                          <Button kind="text" disabled={blocked} onClick={() => setArchiveTarget(plan)}>归档</Button>
                        </div>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      )) : (
        <div className="plan-empty">
          <p>{filter === "all" ? "还没有计划。记下接下来要写的情节、人物的变化、要用到的设定；它们会出现在概览航线的「接下来」一段。" : `还没有${kindLabel[filter]}计划。`}</p>
          {!p.readOnly && <Button kind="primary" disabled={blocked} onClick={() => setDialog({ kind: filter === "all" ? "story" : filter, item: null })}>写下第一条计划</Button>}
        </div>
      )}
      {archived.length > 0 && (
        <div className="plan-archived">
          <button type="button" className="link" aria-expanded={showArchived} onClick={() => setShowArchived((value) => !value)}>{showArchived ? "收起" : `已归档 ${archived.length} 条`}</button>
          {showArchived && <ul>{archived.map((plan) => <li key={plan.item.id}><span className="kind-tag">{kindLabel[plan.kind]}</span>{planTitle(plan)}</li>)}</ul>}
        </div>
      )}
      {dialog && <PlanDialog p={p} state={dialog} close={() => setDialog(null)} done={(message) => { setFeedback(message); setDialog(null); }} />}
      {archiveTarget && (
        <Dialog title={`归档「${planTitle(archiveTarget)}」？`} close={() => setArchiveTarget(null)} closeDisabled={Boolean(p.authorBusy)}>
          <p>归档后默认不显示，也不再用于检查。正文和资料不受影响。</p>
          {error && <p className="inline-error" role="alert">{error}</p>}
          <div className="dialog-actions"><Button kind="danger" disabled={Boolean(p.authorBusy)} onClick={() => void archive()}>{p.authorBusy || "归档"}</Button><Button kind="text" onClick={() => setArchiveTarget(null)}>取消</Button></div>
        </Dialog>
      )}
    </section>
  );
}

function PlanDialog({ p, state, close, done }: { p: ProjectState; state: { kind: Kind; item: Plan["item"] | null }; close: () => void; done: (message: string) => void }) {
  const [kind, setKind] = useState<Kind>(state.kind);
  const story = state.kind === "story" ? (state.item as AuthorStoryPlan | null) : null;
  const character = state.kind === "character" ? (state.item as AuthorCharacterPlan | null) : null;
  const world = state.kind === "world" ? (state.item as AuthorWorldPlan | null) : null;
  const [error, setError] = useState("");
  const busy = Boolean(p.authorBusy);
  const editing = Boolean(state.item);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!p.authorContext) return;
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "");
    const fields: Record<string, unknown> = kind === "story"
      ? { title: text("title"), summary: text("summary"), goal: text("goal"), status: text("status") || "planned", target_chapter_number: text("target") ? Number(text("target")) : null }
      : kind === "character"
        ? { name: text("name"), role_type: text("role_type"), goal: text("goal"), planned_state: text("planned_state"), notes: text("notes") }
        : { name: text("name"), category: text("category"), description: text("description"), notes: text("notes") };
    setError("");
    try {
      await p.mutateAuthorContext(state.item ? `${endpoint[kind]}/${state.item.id}` : endpoint[kind], state.item ? "PATCH" : "POST", { base_author_context_version: p.authorContext.author_context_version, ...fields }, state.item ? "正在保存" : "正在新建");
      done(state.item ? "计划改好了。" : "计划记下了。");
    } catch (cause) { setError(conflictMessage(cause)); }
  };
  return (
    <Dialog title={editing ? "编辑计划" : "新建计划"} kicker="只用来安排后面的写作，不会当成事实" close={close} closeDisabled={busy}>
      {!editing && (
        <div className="segmented" role="radiogroup" aria-label="计划类型">
          {(["story", "character", "world"] as Kind[]).map((value) => <button key={value} type="button" role="radio" aria-checked={kind === value} onClick={() => setKind(value)}>{kindLabel[value]}</button>)}
        </div>
      )}
      <form key={kind} className="form-inner" onSubmit={(event) => void submit(event)}>
        {kind === "story" ? (
          <>
            <label className="field"><span className="field-label">标题</span><input name="title" defaultValue={story?.title} maxLength={120} required disabled={busy} data-autofocus /></label>
            <label className="field"><span className="field-label">写什么</span><textarea name="summary" defaultValue={story?.summary} maxLength={2000} rows={3} disabled={busy} placeholder="主要事件和走向" /></label>
            <label className="field"><span className="field-label">想达到什么</span><textarea name="goal" defaultValue={story?.goal} maxLength={2000} rows={2} disabled={busy} placeholder="这一段要推进什么，或让读者感受到什么" /></label>
            <div className="field-row">
              <label className="field"><span className="field-label">写在第几章</span><input name="target" type="number" min={1} defaultValue={story?.target_chapter_number ?? ""} disabled={busy} placeholder="不限" /></label>
              <label className="field"><span className="field-label">进度</span><select name="status" defaultValue={story?.status ?? "planned"} disabled={busy}>{Object.entries(storyPlanStatusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            </div>
          </>
        ) : kind === "character" ? (
          <>
            <div className="field-row">
              <label className="field"><span className="field-label">人物</span><input name="name" defaultValue={character?.name} maxLength={120} required disabled={busy} data-autofocus /></label>
              <label className="field"><span className="field-label">角色</span><select name="role_type" defaultValue={character?.role_type ?? "supporting"} disabled={busy}>{["protagonist", "ally", "antagonist", "supporting", "other"].map((value) => <option key={value} value={value}>{roleTypeLabel(value)}</option>)}</select></label>
            </div>
            <label className="field"><span className="field-label">想要什么</span><textarea name="goal" defaultValue={character?.goal} maxLength={2000} rows={2} disabled={busy} /></label>
            <label className="field"><span className="field-label">接下来会怎样变化</span><textarea name="planned_state" defaultValue={character?.planned_state} maxLength={2000} rows={2} disabled={busy} placeholder="处境、关系或知道的事" /></label>
            <label className="field"><span className="field-label">备注</span><textarea name="notes" defaultValue={character?.notes} maxLength={4000} rows={2} disabled={busy} /></label>
          </>
        ) : (
          <>
            <div className="field-row">
              <label className="field"><span className="field-label">名称</span><input name="name" defaultValue={world?.name} maxLength={120} required disabled={busy} data-autofocus /></label>
              <label className="field"><span className="field-label">类别</span><select name="category" defaultValue={world?.category ?? "location"} disabled={busy}>{["location", "organization", "rule", "object", "term", "other"].map((value) => <option key={value} value={value}>{worldTypeLabel(value)}</option>)}</select></label>
            </div>
            <label className="field"><span className="field-label">内容</span><textarea name="description" defaultValue={world?.description} maxLength={4000} rows={3} required disabled={busy} placeholder="内容、适用范围和限制" /></label>
            <label className="field"><span className="field-label">备注</span><textarea name="notes" defaultValue={world?.notes} maxLength={4000} rows={2} disabled={busy} /></label>
          </>
        )}
        {error && <p className="inline-error" role="alert">{error}</p>}
        <div className="dialog-actions"><Button kind="primary" type="submit" disabled={busy} busy={busy}>{p.authorBusy || "保存"}</Button><Button kind="text" disabled={busy} onClick={close}>取消</Button></div>
      </form>
    </Dialog>
  );
}
