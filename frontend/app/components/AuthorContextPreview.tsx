"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";
import type { AuthorContext, Chapter, Memory, Project } from "../model";
import { DesignAsset } from "./VisualPrimitives";
import { backendConnected, createBackendStore } from "./author-context-api";
import { AuthorContextAnalysis } from "./AuthorContextAnalysis";
import {
  EMPTY,
  categories,
  comparisonStale,
  disclosures,
  documentError,
  formalConflict,
  formalDocuments,
  mergeDocuments,
  natures,
  outOfRange,
  parseState,
  passagesFrom,
  resolutions,
  type AuthorDocument,
  type Comparison,
  type Kind,
  type Nature,
  type Passage,
  type PreviewState,
  type Resolution,
} from "./author-context-model";

const enabled =
  backendConnected || process.env.NEXT_PUBLIC_AUTHOR_CONTEXT_PREVIEW === "1";
const live = (preview: string, connected: string) =>
  backendConnected ? connected : preview;
type Snapshot = { data: PreviewState; error: string; blocked: boolean };
const initial: Snapshot = { data: EMPTY, error: "", blocked: false };
function makeStore(key: string) {
  let snapshot = initial,
    loaded = false,
    lastRaw: string | null = null;
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((fn) => fn());
  const read = () => {
    try {
      lastRaw = localStorage.getItem(key);
      snapshot = { data: parseState(lastRaw), error: "", blocked: false };
    } catch {
      snapshot = {
        ...snapshot,
        error:
          "本地预览无法读取，已暂停保存。原有记录未被覆盖，请检查浏览器存储后重新读取。",
        blocked: true,
      };
    }
    loaded = true;
  };
  return {
    get: () => {
      if (!loaded && typeof window !== "undefined") read();
      return snapshot;
    },
    subscribe: (fn: () => void) => {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    refresh: () => {
      read();
      notify();
    },
    update: (fn: (state: PreviewState) => PreviewState) => {
      if (!loaded) read();
      if (snapshot.blocked) return false;
      try {
        if (localStorage.getItem(key) !== lastRaw) {
          read();
          snapshot = {
            ...snapshot,
            error:
              snapshot.error ||
              "另一个窗口已更新预览，已读取最新进度。请核对内容后重试。",
          };
          notify();
          return false;
        }
        const data = { ...fn(snapshot.data), serial: snapshot.data.serial + 1 };
        const raw = JSON.stringify(data);
        localStorage.setItem(key, raw);
        lastRaw = raw;
        snapshot = { data, error: "", blocked: false };
        notify();
        return true;
      } catch {
        snapshot = {
          ...snapshot,
          error:
            "保存失败：本地存储不可用或空间不足。当前输入仍保留，请重试；尚未记录为已保存。",
        };
        notify();
        return false;
      }
    },
  };
}
type View = "guide" | "basis" | "edit" | "compare" | "history";
type ContextValue = {
  documents: AuthorDocument[];
  local: AuthorDocument[];
  comparisons: Comparison[];
  formal: AuthorDocument[];
  passages: Passage[];
  project: Project;
  memories: Memory[];
  blocked: boolean;
  remote: ReturnType<typeof createBackendStore> | null;
  pendingDrafts: AuthorDocument[];
  consumeDraft: (id: string) => boolean;
  open: (
    view: View,
    trigger: HTMLElement,
    kind?: Kind,
    document?: AuthorDocument,
  ) => void;
  go: (route: string) => void;
};
const Context = createContext<ContextValue | null>(null);
export function useCanonicalMaterialIds() {
  const context = useContext(Context);
  return new Set(
    backendConnected
      ? context?.documents
          .filter((d) => d.origin !== "legacy_author_intent")
          .map((d) => d.id)
      : [],
  );
}
export function AuthorContextPreviewProvider({
  project,
  userId,
  chapters,
  memories,
  authorContext,
  go,
  children,
}: {
  project: Project;
  userId: string;
  chapters: Chapter[];
  memories: Memory[];
  authorContext: AuthorContext | null;
  go: (route: string) => void;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const key = `story-continuity:author-context-preview:v1:${userId}:${project.id}`;
  const localStore = useMemo(() => makeStore(key), [key]);
  const remote = useMemo(
    () => (backendConnected ? createBackendStore(project.id) : null),
    [project.id],
  );
  const store = remote ?? localStore;
  const localSnapshot = useSyncExternalStore(
    localStore.subscribe,
    localStore.get,
    () => initial,
  );
  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.get,
    () => initial,
  );
  const formal = useMemo(
    () => (backendConnected ? [] : formalDocuments(authorContext)),
    [authorContext],
  );
  const documents = mergeDocuments(formal, snapshot.data.documents);
  const passages = passagesFrom(chapters, project.source_revision ?? 0);
  const [modal, setModal] = useState<{
    view: View;
    kind: Kind;
    document?: AuthorDocument;
    sequence: number;
  } | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const locatedSource = useRef("");
  useEffect(() => {
    if (!backendConnected) return;
    const locate = () => {
      const hash = window.location.hash;
      if (!hash.startsWith("#plan-") || locatedSource.current === hash) return;
      let id: string;
      try { id = decodeURIComponent(hash.slice(6)); } catch { return; }
      const document = snapshot.data.documents.find((item) =>
        item.origin !== "legacy_author_intent" && (item.id === id || item.id === `${item.kind}:${id}`),
      );
      if (!document) return;
      locatedSource.current = hash;
      queueMicrotask(() => setModal({ view: "basis", kind: document.kind, document, sequence: Date.now() }));
    };
    locate();
    window.addEventListener("hashchange", locate);
    return () => window.removeEventListener("hashchange", locate);
  }, [snapshot.data.documents, pathname]);
  const blocked = snapshot.blocked || project.status === "archived";
  useEffect(() => {
    if (!remote) return;
    void remote.refresh();
    const focus = () => {
      void remote.refresh();
    };
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, [remote]);
  useEffect(() => {
    const changed = (event: StorageEvent) => {
      if (event.key === key || event.key === null) store.refresh();
    };
    window.addEventListener("storage", changed);
    return () => window.removeEventListener("storage", changed);
  }, [key, store]);
  const close = () => {
    setModal(null);
    requestAnimationFrame(
      () => trigger.current?.isConnected && trigger.current.focus(),
    );
  };
  const context: ContextValue = {
    documents,
    formal,
    passages,
    project,
    memories,
    local: snapshot.data.documents,
    comparisons: snapshot.data.comparisons,
    blocked,
    remote,
    pendingDrafts: backendConnected ? localSnapshot.data.documents : [],
    consumeDraft: (id) =>
      localStore.update((state) => ({
        ...state,
        documents: state.documents.filter((d) => d.id !== id),
      })),
    go,
    open: (view, button, kind = "world", document) => {
      trigger.current = button;
      setModal({ view, kind, document, sequence: Date.now() });
    },
  };
  if (!enabled) return <>{children}</>;
  return (
    <Context.Provider value={context}>
      {children}
      {modal && (
        <ContextDialog
          key={modal.sequence}
          initialView={modal.view}
          initialKind={modal.kind}
          initialDocument={modal.document}
          snapshot={snapshot}
          update={store.update}
          refresh={store.refresh}
          close={close}
        />
      )}
    </Context.Provider>
  );
}

export function ContextButton({
  view = "basis",
  kind,
  children = "设定与检查依据",
  className = "quiet",
}: {
  view?: View;
  kind?: Kind;
  children?: ReactNode;
  className?: string;
}) {
  const context = useContext(Context);
  if (!context) return null;
  return (
    <button
      type="button"
      className={className}
      onClick={(event) => context.open(view, event.currentTarget, kind)}
    >
      {children}
    </button>
  );
}
export function ContextOverview() {
  const context = useContext(Context);
  if (!context) return null;
  return (
    <section className="project-section ac-overview" aria-label="准备检查依据">
      <div className="ac-heading">
        <DesignAsset name="paper" />
        <div>
          <h2>把你的构思带进检查</h2>
          <p>补充已有的大纲与设定，对照正文，看看有没有需要调整的地方。</p>
        </div>
        <ContextButton view="guide" className="primary">
          准备检查依据
        </ContextButton>
      </div>
      <div className="ac-metrics">
        <span>
          <b>{context.project.chapter_count}</b> 个已导入章节
        </span>
        <span>
          <b>{context.documents.filter((d) => !d.archived).length}</b>{" "}
          {live("条作者资料（含预览）", "条作者资料")}
        </span>
        <span>
          <b>{context.memories.length}</b> 条现有 Memory 记录
        </span>
      </div>
      <p className="ac-note">
        {live(
          "前端验收 · 新增资料与决定仅存本浏览器，尚未用于真实检查。可以跳过补充，继续阅读与写作。",
          "可以先补充一两条，也可以继续写作，等有需要时再回来。",
        )}
      </p>
    </section>
  );
}
export function ContextInline({ memory = false }: { memory?: boolean }) {
  const context = useContext(Context);
  if (!context) return null;
  return (
    <div className="ac-inline">
      <div>
        <strong>
          {memory ? "看看故事里已经写了什么" : "带上你的设定，一起核对正文"}
        </strong>
        <p>
          {memory
            ? "在这里核对正文记录；还没写进故事的设定和安排，可以到作者资料中补充。"
            : live(
                "明确设定、故事安排与待定想法分开处理；预览资料尚未用于真实检查。",
                "已经确定的设定、接下来的安排、还在犹豫的想法，都可以分别记下来。待定想法暂不参与检查。",
              )}
        </p>
      </div>
      <ContextButton view={memory ? "basis" : "compare"}>
        {memory ? "查看检查依据" : live("预览对照流程", "查看与对照")}
      </ContextButton>
    </div>
  );
}
export function ContextDraftShelf({ kind }: { kind: Kind }) {
  const context = useContext(Context);
  if (!context) return null;
  const drafts = context.local.filter(
    (d) =>
      d.kind === kind &&
      !d.archived &&
      (!backendConnected || d.origin !== "legacy_author_intent"),
  );
  if (!drafts.length) return null;
  return (
    <section className="ac-draft-shelf" aria-label={live("本次预览资料", "检查参考资料")}>
      <div className="ac-section-heading">
        <div>
          <strong>{live("本次预览资料", "检查参考资料")}</strong>
          <p>
            {live(
              "尚未保存到正式作品。以下入口引用同一份预览内容。",
              "这里和检查中使用的是同一份资料，保存修改后会同步更新。",
            )}
          </p>
        </div>
        <ContextButton kind={kind}>
          {live("管理预览资料 ·", "管理作者资料 ·")}
          {drafts.length}
        </ContextButton>
      </div>
      {drafts.slice(0, 3).map((d) => (
        <div className="ac-draft-row" key={d.id}>
          <div>
            <strong>{d.title}</strong>
            <span>
              {natures[d.nature]} ·{" "}
              {d.baseSignature ? live("本地修订", "作者修订") : "作者补充"}
            </span>
          </div>
          <button
            type="button"
            className="quiet"
            disabled={context.blocked}
            onClick={(e) => context.open("edit", e.currentTarget, kind, d)}
          >
            {live("编辑预览", "编辑资料")}
          </button>
        </div>
      ))}
      {drafts.length > 3 && (
        <small>另有 {drafts.length - 3} 条，可在{live("管理预览资料", "管理作者资料")}中查看。</small>
      )}
    </section>
  );
}

const blankDocument = (kind: Kind): AuthorDocument => ({
  id: "",
  kind,
  title: "",
  content: "",
  nature: "idea",
  disclosure: "unspecified",
  knowledge: "",
  from: null,
  to: null,
  revision: 0,
  archived: false,
  origin: "作者手动补充",
});
function Scope({ document }: { document: AuthorDocument }) {
  return (
    <div className="ac-tags">
      <span>{natures[document.nature]}</span>
      <span>{disclosures[document.disclosure]}</span>
      <span>
        {document.from === null && document.to === null
          ? "适用章节未限定"
          : `第 ${document.from ?? 1} 章起${document.to === null ? "，未限定结束" : `至第 ${document.to} 章`}`}
      </span>
    </div>
  );
}
function Pager({
  page,
  total,
  change,
}: {
  page: number;
  total: number;
  change: (page: number) => void;
}) {
  const count = Math.max(1, Math.ceil(total / 5));
  if (count === 1) return null;
  return (
    <nav className="ac-pagination" aria-label="资料分页">
      <button
        type="button"
        className="quiet"
        disabled={page <= 0}
        onClick={() => change(page - 1)}
      >
        上一页
      </button>
      <span>
        {page + 1} / {count} · 共 {total} 条
      </span>
      <button
        type="button"
        className="quiet"
        disabled={page + 1 >= count}
        onClick={() => change(page + 1)}
      >
        下一页
      </button>
    </nav>
  );
}

function ContextDialog({
  initialView,
  initialKind,
  initialDocument,
  snapshot,
  update,
  refresh,
  close,
}: {
  initialView: View;
  initialKind: Kind;
  initialDocument?: AuthorDocument;
  snapshot: Snapshot;
  update: (
    fn: (state: PreviewState) => PreviewState,
  ) => boolean | Promise<boolean>;
  refresh: () => void | Promise<void>;
  close: () => void;
}) {
  const context = useContext(Context)!;
  const {
    project,
    documents,
    formal,
    passages,
    memories,
    comparisons,
    blocked,
  } = context;
  const [view, setView] = useState<View>(initialView);
  const [migrationId, setMigrationId] = useState<string | null>(null);
  const [draft, setDraft] = useState<AuthorDocument>(
    initialDocument ?? blankDocument(initialKind),
  );
  const [editBase, setEditBase] = useState<AuthorDocument>(
    initialDocument ?? blankDocument(initialKind),
  );
  const [editExpected, setEditExpected] = useState(() =>
    JSON.stringify(documents.find((d) => d.id === initialDocument?.id)),
  );
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [discard, setDiscard] = useState(false);
  const nextView = useRef<View | null>(null);
  const [section, setSection] = useState<"author" | "memory">("author");
  const [filter, setFilter] = useState<Kind | "all">(
    initialView === "basis" ? initialKind : "all",
  );
  const [query, setQuery] = useState(initialView === "basis" ? initialDocument?.title ?? "" : "");
  const [showArchived, setShowArchived] = useState(initialView === "basis" && Boolean(initialDocument?.archived));
  const [page, setPage] = useState(0);
  const [documentId, setDocumentId] = useState(initialDocument?.id ?? "");
  const [passageId, setPassageId] = useState("");
  const [selectionStamp, setSelectionStamp] = useState("");
  const [resolution, setResolution] = useState<Resolution | "">("");
  const [reason, setReason] = useState("");
  const [adjusting, setAdjusting] = useState(false);
  const [adjustReason, setAdjustReason] = useState("");
  const [openHistory, setOpenHistory] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const fileEpoch = useRef(0);
  const initialFocus = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (!element?.open) element?.showModal();
    initialFocus.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
      fileEpoch.current += 1;
    };
  }, []);
  const dirty =
    view === "edit" && JSON.stringify(draft) !== JSON.stringify(editBase);
  const comparisonDirty =
    view === "compare" && (Boolean(reason.trim()) || Boolean(resolution));
  const navigate = (next: View | null) => {
    if (dirty || comparisonDirty) {
      nextView.current = next;
      setDiscard(true);
      return;
    }
    setError("");
    setFeedback("");
    setPage(0);
    fileEpoch.current += 1;
    if (next === null) close();
    else {
      setView(next);
      setAdjusting(false);
    }
  };
  const acceptDiscard = () => {
    setDiscard(false);
    setError("");
    setReason("");
    setResolution("");
    setAdjusting(false);
    fileEpoch.current += 1;
    if (nextView.current === null) close();
    else setView(nextView.current);
  };
  const edit = (document?: AuthorDocument, kind: Kind = initialKind) => {
    setMigrationId(null);
    const next = document ? { ...document } : blankDocument(kind);
    setEditBase(next);
    setEditExpected(JSON.stringify(documents.find((d) => d.id === next.id)));
    setDraft(next);
    setError("");
    setFeedback("");
    setView("edit");
    setAdjusting(false);
    fileEpoch.current += 1;
  };
  const go = (route: string) => {
    close();
    context.go(`/projects/${project.id}/${route}`);
  };
  const source = (passage: Passage) =>
    go(`sources#span-${encodeURIComponent(passage.id)}`);
  const saveDraft = async () => {
    if (blocked) return;
    const invalid = documentError(draft);
    if (invalid) {
      setError(invalid);
      return;
    }
    const current = documents.find((d) => d.id === draft.id);
    if (JSON.stringify(current) !== editExpected) {
      setError(
        "此资料已在其他窗口更新，请返回列表并重新打开，避免覆盖新内容。",
      );
      return;
    }
    if (!backendConnected && formalConflict(draft, formal)) {
      setError("正式资料已更新，请返回列表，以最新正式资料重新编辑。");
      return;
    }
    if (adjusting && !adjustReason.trim()) {
      setError("请填写调整资料的理由。");
      return;
    }
    const saved = {
      ...draft,
      id: draft.id || crypto.randomUUID(),
      title: draft.title.trim(),
      content: draft.content.trim(),
      revision: Math.max(current?.revision ?? 0, draft.revision) + 1,
    };
    const passage = passages.find((p) => p.id === passageId);
    if (
      adjusting &&
      (!passage ||
        selectionStamp !==
          JSON.stringify([editBase, passage, project.source_revision ?? 0]))
    ) {
      setError("对照的正文或资料已变化，请返回重新选择依据。");
      return;
    }
    const decision: Comparison | null =
      adjusting && passage
        ? {
            id: crypto.randomUUID(),
            document: saved,
            previousDocument: editBase,
            passage,
            sourceRevision: project.source_revision ?? 0,
            resolution: "revise_document",
            reason: adjustReason.trim(),
            at: new Date().toISOString(),
          }
        : null;
    if (
      await update((state) => ({
        ...state,
        documents: [...state.documents.filter((d) => d.id !== saved.id), saved],
        comparisons: decision
          ? [decision, ...state.comparisons]
          : state.comparisons,
      }))
    ) {
      const draftCleared = !migrationId || context.consumeDraft(migrationId);
      setMigrationId(null);
      setView(decision ? "history" : "basis");
      setFilter(saved.kind);
      setSection("author");
      setPage(0);
      setQuery("");
      setError("");
      setFeedback(
        !draftCleared
          ? "作品资料已保存，但浏览器旧草稿清理失败。请勿重复导入这一条。"
          : decision
            ? live(
                "资料预览已更新，决定已记录。正式资料尚未改变，仍需重新检查。",
                "资料和调整理由已保存，可以用新内容再对照一次。",
              )
            : live(
                "已保存到本浏览器预览；正式作品资料尚未改变。",
                "作者资料已保存到当前作品。",
              ),
      );
      setAdjusting(false);
      setResolution("");
      setReason("");
    }
  };
  const toggleArchive = async (document: AuthorDocument) => {
    if (blocked) return;
    const saved = {
      ...document,
      archived: !document.archived,
      revision: document.revision + 1,
    };
    if (
      await update((state) => ({
        ...state,
        documents: [
          ...state.documents.filter((d) => d.id !== document.id),
          saved,
        ],
      }))
    )
      setFeedback(
        saved.archived
          ? live(
              "已在预览中归档，可开启“查看已归档”恢复。正式资料不变。",
              "资料已归档，可开启“查看已归档”恢复。",
            )
          : live("已恢复预览资料。", "资料已恢复。"),
      );
  };
  const eligible = documents.filter(
    (d) => !d.archived && d.nature !== "idea" && !formalConflict(d, formal),
  );
  const selectedDocument = documents.find((d) => d.id === documentId);
  const selectedPassage = passages.find((p) => p.id === passageId);
  const pairChanged = Boolean(
    selectedDocument &&
    selectedPassage &&
    selectionStamp !==
      JSON.stringify([
        selectedDocument,
        selectedPassage,
        project.source_revision ?? 0,
      ]),
  );
  const unavailable =
    !selectedDocument ||
    selectedDocument.archived ||
    selectedDocument.nature === "idea" ||
    formalConflict(selectedDocument, formal) ||
    !selectedPassage ||
    pairChanged;
  const choosePair = (docId: string, spanId: string) => {
    if (comparisonDirty) {
      setError("请先记录当前判断，或点击“清空未保存判断”，再更换对照依据。");
      return;
    }
    setDocumentId(docId);
    setPassageId(spanId);
    setSelectionStamp(
      JSON.stringify([
        documents.find((d) => d.id === docId),
        passages.find((p) => p.id === spanId),
        project.source_revision ?? 0,
      ]),
    );
    setError("");
  };
  const record = async () => {
    if (
      blocked ||
      unavailable ||
      !resolution ||
      !selectedDocument ||
      !selectedPassage
    )
      return;
    if (!reason.trim()) {
      setError("请说明你的判断，方便之后回看。");
      return;
    }
    const item: Comparison = {
      id: crypto.randomUUID(),
      document: { ...selectedDocument },
      passage: { ...selectedPassage },
      sourceRevision: project.source_revision ?? 0,
      resolution,
      reason: reason.trim(),
      at: new Date().toISOString(),
    };
    if (
      await update((state) => ({
        ...state,
        comparisons: [item, ...state.comparisons],
      }))
    ) {
      setView("history");
      setPage(0);
      setFeedback(
        resolution === "revise_text"
          ? "已记录待修改事项，正文尚未改变。"
          : "你的决定已保存，只针对这次对照。其他内容仍会正常检查。",
      );
      setReason("");
      setResolution("");
      setError("");
    }
  };
  const changeFile = async (file?: File) => {
    if (!file) return;
    const epoch = ++fileEpoch.current;
    setError("");
    if (!/\.(txt|md|markdown)$/i.test(file.name) || file.size > 1024 * 1024) {
      setError("请选择不超过 1 MiB 的 TXT 或 Markdown 文件。");
      return;
    }
    try {
      const text = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
      if (epoch !== fileEpoch.current) return;
      if (!text.trim() || text.includes("\u0000") || text.length > 30000) {
        setError(
          "文件需为 UTF-8 纯文本，内容为 1 至 30,000 字；较长笔记请选取相关部分粘贴。",
        );
        return;
      }
      setDraft((current) => ({
        ...current,
        content: text,
        title: current.title || file.name.replace(/\.[^.]+$/, "").slice(0, 160),
        origin: `本地文件 · ${file.name}`,
      }));
    } catch {
      if (epoch === fileEpoch.current)
        setError("无法读取文件，请使用 UTF-8 编码的文本，或直接粘贴相关内容。");
    }
  };
  const visible = documents.filter(
    (d) =>
      (showArchived || !d.archived) &&
      (filter === "all" || d.kind === filter) &&
      `${d.title} ${d.content}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
  );
  const memoryList = memories.filter((m) =>
    `${m.subject} ${m.value}`
      .toLocaleLowerCase()
      .includes(query.toLocaleLowerCase()),
  );
  const listLength =
    view === "history"
      ? comparisons.length
      : section === "author"
        ? visible.length
        : memoryList.length;
  const currentPage = Math.min(
    page,
    Math.max(0, Math.ceil(listLength / 5) - 1),
  );
  const titles: Record<View, string> = {
    guide: "准备检查依据",
    basis: "设定与检查依据",
    edit: adjusting
      ? "调整作者资料"
      : draft.id
        ? live("编辑资料预览", "编辑作者资料")
        : "补充作者资料",
    compare: "正文与资料对照",
    history: "我的对照决定",
  };

  return (
    <dialog
      ref={dialog}
      className="dialog author-plan-dialog ac-dialog"
      aria-labelledby="ac-title"
      onCancel={(e) => {
        e.preventDefault();
        navigate(null);
      }}
    >
      <button
        ref={initialFocus}
        className="close"
        type="button"
        aria-label="关闭检查依据"
        onClick={() => navigate(null)}
      >
        ×
      </button>
      <header className="ac-heading">
        <DesignAsset name="paper" />
        <div>
          <p className="eyebrow" title={project.title}>
            {project.title}
          </p>
          <h2 id="ac-title">{titles[view]}</h2>
        </div>
      </header>
      <p className="ac-preview-note">
        {live(
          "前端验收 · 新增资料与决定仅保存在本浏览器，尚未用于真实检查。此处不会运行 AI 或修改正式作品。",
          "保存后，下次打开作品还可以继续查看。你可以自己对照，也可以点击按钮请 AI 帮忙。",
        )}
      </p>
      {project.status === "archived" && (
        <p className="notice" role="note">
          {live(
            "作品已归档，可以查看，不能更改预览资料或决定。",
            "作品已归档，可以查看，不能更改资料或决定。",
          )}
        </p>
      )}
      {snapshot.error && (
        <div className="notice error" role="alert">
          <p>{snapshot.error}</p>
          <button type="button" className="quiet" onClick={refresh}>
            {live("重新读取本地进度", "重新读取作品资料")}
          </button>
        </div>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {feedback && (
        <p className="notice success" role="status">
          {feedback}
        </p>
      )}
      {discard ? (
        <section className="ac-discard" aria-label="未保存内容">
          <h3>保留当前输入吗？</h3>
          <p>
            {live(
              "当前内容尚未保存，离开后需要重新填写。已经保存的预览资料不受影响。",
              "还有内容没保存。继续编辑可以保留这次输入，放弃后就需要重新填写。",
            )}
          </p>
          <div className="actions">
            <button type="button" className="quiet" onClick={acceptDiscard}>
              放弃未保存内容
            </button>
            <button
              type="button"
              className="primary"
              onClick={() => setDiscard(false)}
            >
              继续编辑
            </button>
          </div>
        </section>
      ) : (
        <>
          {view !== "edit" && (
            <nav
              className="author-mode-switch ac-nav"
              aria-label="检查依据流程"
            >
              {(
                [
                  ["guide", "准备"],
                  ["basis", "资料依据"],
                  ["compare", live("对照预览", "正文对照")],
                  ["history", "我的决定"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={view === value ? "current" : "quiet"}
                  aria-pressed={view === value}
                  onClick={() => navigate(value)}
                >
                  {label}
                </button>
              ))}
            </nav>
          )}
          {view === "guide" && (
            <>
              <section className="ac-guide-intro">
                <h3>从你已有的构思开始</h3>
                <p>
                  手边的大纲、角色笔记或零散想法都可以用，先从这次写作需要的内容开始。
                </p>
              </section>
              <div className="ac-guide-options">
                <section>
                  <span className="ac-number">01</span>
                  <h3>我有大纲或设定</h3>
                  <p>
                    粘贴笔记或选择文本文件，再标明哪些已经确定，哪些还在考虑。
                  </p>
                  <button
                    type="button"
                    className="primary"
                    disabled={blocked}
                    onClick={() => edit()}
                  >
                    补充已有资料
                  </button>
                </section>
                <section>
                  <span className="ac-number">02</span>
                  <h3>先看看已经写出的内容</h3>
                  <p>
                    从已写章节和 Story Memory 开始核对。后续的剧情和设定，可以等你想好后再补充。
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      setView("basis");
                      setSection("memory");
                      setQuery("");
                      setPage(0);
                    }}
                  >
                    查看正文依据
                  </button>
                </section>
              </div>
              <div className="ac-coverage">
                <strong>当前可用内容</strong>
                <p>
                  {project.chapter_count} 个已导入章节 · {passages.length}{" "}
                  个可见原文片段 · {memories.length} 条现有 Memory 记录
                </p>
                <small>
                  每次对照都会列出用到的资料和原文，方便你核对范围。
                </small>
              </div>
              <div className="ac-footer">
                <span>还在探索故事方向？可以稍后补充。</span>
                <button
                  type="button"
                  className="quiet"
                  onClick={async () => {
                    if (
                      blocked ||
                      (await update((state) => ({ ...state, skipped: true })))
                    )
                      go("workspace");
                  }}
                >
                  先继续写作
                </button>
              </div>
            </>
          )}

          {view === "basis" && (
            <>
              {backendConnected && context.pendingDrafts.length > 0 && (
                <details className="ac-coverage">
                  <summary>
                    本浏览器还有 {context.pendingDrafts.length}{" "}
                    条本地草稿，等待你确认保存
                  </summary>
                  <p>
                    逐条恢复到编辑表单，核对后明确保存。旧的人工对照记录不会自动上传。
                  </p>
                  {context.pendingDrafts.slice(0, 5).map((localDraft) => (
                    <div className="ac-draft-row" key={localDraft.id}>
                      <div>
                        <strong>{localDraft.title}</strong>
                        <small>
                          {categories[localDraft.kind]} · 旧本地预览
                        </small>
                      </div>
                      <button
                        type="button"
                        disabled={blocked}
                        onClick={() => {
                          const existing = documents.find(
                            (d) => d.id === localDraft.id,
                          );
                          edit({
                            ...localDraft,
                            id: existing?.id ?? "",
                            revision: existing?.revision ?? 0,
                            baseSignature: undefined,
                          });
                          setMigrationId(localDraft.id);
                        }}
                      >
                        恢复到编辑表单
                      </button>
                    </div>
                  ))}
                  {context.pendingDrafts.length > 5 && (
                    <small>处理前 5 条后继续显示剩余草稿。</small>
                  )}
                </details>
              )}
              <div className="ac-section-heading">
                <div className="ac-segment" role="group" aria-label="资料来源">
                  <button
                    type="button"
                    className={section === "author" ? "current" : "quiet"}
                    aria-pressed={section === "author"}
                    onClick={() => {
                      setSection("author");
                      setPage(0);
                    }}
                  >
                    作者资料
                  </button>
                  <button
                    type="button"
                    className={section === "memory" ? "current" : "quiet"}
                    aria-pressed={section === "memory"}
                    onClick={() => {
                      setSection("memory");
                      setPage(0);
                    }}
                  >
                    正文参考
                  </button>
                </div>
                {section === "author" && (
                  <button
                    type="button"
                    className="primary"
                    disabled={blocked}
                    onClick={() =>
                      edit(undefined, filter === "all" ? "world" : filter)
                    }
                  >
                    补充资料
                  </button>
                )}
              </div>
              <div className="ac-toolbar">
                <label>
                  <span className="sr-only">搜索资料</span>
                  <input
                    aria-label="搜索资料"
                    placeholder="搜索资料标题或内容"
                    value={query}
                    onChange={(e) => {
                      setQuery(e.target.value);
                      setPage(0);
                    }}
                  />
                </label>
                {section === "author" && (
                  <>
                    <label>
                      <span className="sr-only">资料分类</span>
                      <select
                        aria-label="资料分类"
                        value={filter}
                        onChange={(e) => {
                          setFilter(e.target.value as Kind | "all");
                          setPage(0);
                        }}
                      >
                        <option value="all">全部分类</option>
                        {Object.entries(categories).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="ac-check">
                      <input
                        type="checkbox"
                        checked={showArchived}
                        onChange={(e) => {
                          setShowArchived(e.target.checked);
                          setPage(0);
                        }}
                      />
                      查看已归档
                    </label>
                  </>
                )}
              </div>
              {section === "author" ? (
                <>
                  <p className="ac-note">
                    {live(
                      "已有规划按原用途展示，未自动判定为明确设定。本地修订只改变预览；待定想法不作为确定的对照依据。",
                      "已有规划也放在这里。你可以标明它是确定的设定、接下来的安排，还是待定想法；待定想法暂不参与检查。",
                    )}
                  </p>
                  <div className="ac-list" aria-label="作者资料列表">
                    {visible
                      .slice(currentPage * 5, currentPage * 5 + 5)
                      .map((d) => {
                        const conflict = formalConflict(d, formal),
                          local = context.local.some(
                            (item) => item.id === d.id,
                          );
                        return (
                          <article key={d.id} className="ac-document">
                            <div className="ac-section-heading">
                              <div>
                                <span className="eyebrow">
                                  {categories[d.kind]} ·{" "}
                                  {local
                                    ? d.baseSignature
                                      ? live("本地修订", "作者修订")
                                      : live("本地预览", "作者补充")
                                    : "已有正式规划"}
                                  {d.archived ? " · 已归档" : ""}
                                </span>
                                <h3>{d.title}</h3>
                              </div>
                              <span className="ac-version">v{d.revision}</span>
                            </div>
                            <Scope document={d} />
                            <p className="ac-excerpt">
                              {d.content || "尚未填写内容"}
                            </p>
                            <small className="ac-origin">
                              {d.origin === "legacy_author_intent"
                                ? "已有作者规划"
                                : d.origin === "author"
                                  ? "作者提供"
                                  : d.origin}
                            </small>
                            {conflict && (
                              <p className="notice" role="note">
                                {backendConnected ? "原来的规划有了改动。请先核对并保存这条资料，再用它对照正文。" : "正式资料已变化，此预览修订暂不能用于新对照。请以最新正式资料重新编辑。"}
                              </p>
                            )}
                            <div className="ac-card-actions">
                              <button
                                type="button"
                                className="quiet"
                                disabled={blocked || (!backendConnected && conflict)}
                                onClick={() => edit(d)}
                              >
                                {local
                                  ? live("编辑预览", "编辑资料")
                                  : live("建立预览修订", "编辑资料用途")}
                              </button>
                              {conflict &&
                                formal.find((item) => item.id === d.id) && (
                                  <button
                                    type="button"
                                    disabled={blocked}
                                    onClick={() =>
                                      edit(
                                        formal.find((item) => item.id === d.id),
                                      )
                                    }
                                  >
                                    以最新正式资料编辑
                                  </button>
                                )}
                              <button
                                type="button"
                                className="quiet"
                                disabled={blocked || (conflict && !d.archived)}
                                onClick={() => toggleArchive(d)}
                              >
                                {d.archived
                                  ? live("恢复预览", "恢复资料")
                                  : live("归档预览", "归档资料")}
                              </button>
                              <button
                                type="button"
                                disabled={
                                  d.archived || d.nature === "idea" || conflict
                                }
                                onClick={() => {
                                  choosePair(d.id, passageId);
                                  setView("compare");
                                  setFeedback("");
                                }}
                              >
                                选择正文对照
                              </button>
                            </div>
                          </article>
                        );
                      })}
                  </div>
                  {!visible.length && (
                    <div className="empty">
                      <strong>
                        {query || filter !== "all" || showArchived
                          ? "当前条件下没有资料"
                          : "还没有作者资料"}
                      </strong>
                      <p>
                        先记下一条设定，或去看看已经写好的内容，都可以。
                      </p>
                      <button
                        type="button"
                        className="quiet"
                        onClick={() => {
                          setSection("memory");
                          setQuery("");
                          setPage(0);
                        }}
                      >
                        查看正文依据
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <div className="ac-coverage">
                    <strong>
                      现有 Story Memory · {memories.length} 条记录
                    </strong>
                    <p>
                      这里展示作品已有的 Story Memory。想确认或修改其中的内容，可以前往 Story Memory 处理。
                    </p>
                    <button
                      type="button"
                      className="quiet"
                      onClick={() => go("memory")}
                    >
                      前往 Story Memory
                    </button>
                    <button
                      type="button"
                      className="quiet"
                      onClick={() => go("sources")}
                    >
                      核对已导入章节
                    </button>
                  </div>
                  <div className="ac-list">
                    {memoryList
                      .slice(currentPage * 5, currentPage * 5 + 5)
                      .map((m) => (
                        <article key={m.id} className="ac-document">
                          <h3>{m.subject}</h3>
                          <p>{m.value}</p>
                          <small>
                            原记录状态：{m.review_status} ·{" "}
                            {m.valid_from === null
                              ? "起始 Memory 版本未标明"
                              : `Memory V${m.valid_from} 起`}
                            {m.valid_to === null
                              ? ""
                              : `，至 Memory V${m.valid_to}`}
                          </small>
                          {m.source ? (
                            <>
                              <blockquote>{m.source.excerpt}</blockquote>
                              <button
                                type="button"
                                className="quiet"
                                onClick={() =>
                                  go(
                                    `sources#span-${encodeURIComponent(m.source!.span_id)}`,
                                  )
                                }
                              >
                                第 {m.source.chapter_number} 章 · 查看来源
                              </button>
                            </>
                          ) : (
                            <p className="ac-note">
                              这条记录暂时没有可打开的原文，建议回到章节中核对。
                            </p>
                          )}
                        </article>
                      ))}
                  </div>
                  {!memoryList.length && (
                    <div className="empty">
                      <strong>
                        {query
                          ? "没有匹配的正文参考"
                          : "目前没有可展示的 Memory 记录"}
                      </strong>
                      <p>
                        可以先阅读已导入的章节，或前往 Story Memory，按提示整理正文记录。
                      </p>
                    </div>
                  )}
                </>
              )}
              <Pager page={currentPage} total={listLength} change={setPage} />
            </>
          )}

          {view === "edit" && (
            <form
              className="ac-form"
              onSubmit={(e) => {
                e.preventDefault();
                saveDraft();
              }}
            >
              <div className="ac-section-heading">
                <p>记下这条设定或安排，再说明它是否已经确定。</p>
                <label className="ac-file-button">
                  读取 TXT / Markdown
                  <input
                    type="file"
                    accept=".txt,.md,.markdown,text/plain,text/markdown"
                    disabled={blocked}
                    onChange={(e) => {
                      void changeFile(e.target.files?.[0]);
                      e.target.value = "";
                    }}
                  />
                </label>
              </div>
              <p className="ac-note">
                文件仅在本机读取，不上传、不自动拆解；UTF-8，最多 1 MiB / 30,000
                字。读取会替换下方内容，保存前可核对。
              </p>
              <div className="author-plan-form-row">
                <label>
                  资料标题
                  <input
                    autoComplete="off"
                    required
                    maxLength={160}
                    value={draft.title}
                    disabled={blocked}
                    onChange={(e) =>
                      setDraft({ ...draft, title: e.target.value })
                    }
                    placeholder="例如：传送的代价"
                  />
                </label>
                <label>
                  资料类别
                  <select
                    value={draft.kind}
                    disabled={blocked}
                    onChange={(e) =>
                      setDraft({ ...draft, kind: e.target.value as Kind })
                    }
                  >
                    {Object.entries(categories).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label>
                资料内容
                <textarea
                  required
                  rows={5}
                  maxLength={30000}
                  value={draft.content}
                  disabled={blocked}
                  onChange={(e) =>
                    setDraft({ ...draft, content: e.target.value })
                  }
                  placeholder="粘贴已有笔记，或写下你希望检查时参考的内容。"
                />
              </label>
              <fieldset className="ac-natures">
                <legend>这条资料的性质</legend>
                {Object.entries(natures).map(([value, label]) => (
                  <label key={value}>
                    <input
                      type="radio"
                      name="document-nature"
                      value={value}
                      disabled={blocked}
                      checked={draft.nature === value}
                      onChange={() =>
                        setDraft({ ...draft, nature: value as Nature })
                      }
                    />
                    <span>
                      <strong>{label}</strong>
                      <small>
                        {value === "setting"
                          ? "已经确定，可作为设定依据"
                          : value === "plan"
                            ? "未来安排，偏离时提醒"
                            : "尚未决定，暂不作为依据"}
                      </small>
                    </span>
                  </label>
                ))}
              </fieldset>
              <details className="ac-details">
                <summary>适用章节与披露范围（可选）</summary>
                <div className="author-plan-form-row">
                  <label>
                    起始章节
                    <input
                      type="number"
                      min={1}
                      max={999999}
                      value={draft.from ?? ""}
                      disabled={blocked}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          from:
                            e.target.value === ""
                              ? null
                              : Number(e.target.value),
                        })
                      }
                      placeholder="未限定"
                    />
                  </label>
                  <label>
                    结束章节
                    <input
                      type="number"
                      min={1}
                      max={999999}
                      value={draft.to ?? ""}
                      disabled={blocked}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          to:
                            e.target.value === ""
                              ? null
                              : Number(e.target.value),
                        })
                      }
                      placeholder="未限定"
                    />
                  </label>
                </div>
                <label>
                  向读者披露的情况
                  <select
                    value={draft.disclosure}
                    disabled={blocked}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        disclosure: e.target
                          .value as AuthorDocument["disclosure"],
                      })
                    }
                  >
                    {Object.entries(disclosures).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  角色知情与例外说明
                  <textarea
                    rows={3}
                    maxLength={3000}
                    value={draft.knowledge}
                    disabled={blocked}
                    onChange={(e) =>
                      setDraft({ ...draft, knowledge: e.target.value })
                    }
                    placeholder="例如：这是作者已知的秘密，主角目前并不知道；第三十章才揭露。"
                  />
                </label>
                <p className="ac-note">
                  作者确定的设定，不等于角色已经知道。未填章节范围，也不代表已检查全篇。
                </p>
              </details>
              {draft.baseSignature && (
                <p className="ac-note">
                  {live(
                    "这是已有作者规划的预览修订，正式内容与原有结构仍保留。",
                    "你正在修改已有规划。保存后会更新这条资料，之前的版本仍会保留。",
                  )}
                </p>
              )}
              {adjusting && (
                <label>
                  调整理由
                  <textarea
                    required
                    maxLength={2000}
                    value={adjustReason}
                    onChange={(e) => setAdjustReason(e.target.value)}
                    placeholder="说明设定或安排为何改变。"
                  />
                </label>
              )}
              <footer className="ac-footer">
                <button
                  type="button"
                  className="quiet"
                  onClick={() => navigate(adjusting ? "compare" : "basis")}
                >
                  取消编辑
                </button>
                <button type="submit" className="primary" disabled={blocked}>
                  {adjusting
                    ? live("保存预览修订并记录理由", "保存资料修订并记录理由")
                    : live("保存资料预览", "保存作者资料")}
                </button>
              </footer>
            </form>
          )}

          {view === "compare" && (
            <>
              <div className="ac-coverage">
                <strong>先看依据，再作判断</strong>
                <p>
                  {live(
                    "人工选择的对照预览，尚未运行 AI 判断。选中两段内容不代表存在矛盾，也不会生成真实检查结果。",
                    "选一条资料和一段正文，看看它们是否符合你的构思。拿不准时，也可以请 AI 帮忙分析。",
                  )}
                </p>
              </div>
              <div className="author-plan-form-row ac-selectors">
                <label>
                  作者资料
                  <select
                    value={documentId}
                    onChange={(e) => {
                      choosePair(e.target.value, passageId);
                    }}
                  >
                    <option value="">请选择一条明确设定或故事安排</option>
                    {eligible.map((d) => (
                      <option value={d.id} key={d.id}>
                        {categories[d.kind]} · {d.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  正文片段
                  <select
                    value={passageId}
                    onChange={(e) => {
                      choosePair(documentId, e.target.value);
                    }}
                  >
                    <option value="">请选择当前作品的原文片段</option>
                    {passages.map((p, index) => (
                      <option value={p.id} key={p.id}>
                        第 {p.number} 章 · {p.title} · 片段 {index + 1}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {!eligible.length && (
                <div className="empty">
                  <strong>还没有可用于对照的作者资料</strong>
                  <p>先补充一条已经确定的设定或故事安排；已有资料若发生变化，请核对后再使用。</p>
                  <button
                    type="button"
                    disabled={blocked}
                    onClick={() => edit()}
                  >
                    补充作者资料
                  </button>
                </div>
              )}
              {!passages.length && (
                <div className="empty">
                  <strong>目前没有可用的原文片段</strong>
                  <p>对照需要用到章节原文，请先查看已导入的章节是否完整。</p>
                  <button
                    type="button"
                    className="quiet"
                    onClick={() => go("sources")}
                  >
                    查看章节来源
                  </button>
                </div>
              )}
              {selectedDocument && selectedPassage && (
                <>
                  <div className="ac-comparison">
                    <section>
                      <span className="eyebrow">
                        作者提供 · v{selectedDocument.revision}
                      </span>
                      <h3>{selectedDocument.title}</h3>
                      <Scope document={selectedDocument} />
                      <p className="ac-fulltext">{selectedDocument.content}</p>
                      {selectedDocument.knowledge && (
                        <div className="ac-knowledge">
                          <strong>角色知情与例外</strong>
                          <p>{selectedDocument.knowledge}</p>
                        </div>
                      )}
                    </section>
                    <section>
                      <span className="eyebrow">
                        实际正文 · 第 {selectedPassage.number} 章
                      </span>
                      <h3>{selectedPassage.title}</h3>
                      <blockquote>{selectedPassage.text}</blockquote>
                      <p className="ac-note">
                        如果拿不准，可以打开章节看看前后文，尤其留意角色的对白和传闻。
                      </p>
                      <button
                        type="button"
                        className="quiet"
                        onClick={() => {
                          if (comparisonDirty) {
                            setError("请先记录或清空当前判断，再打开来源。");
                            return;
                          }
                          source(selectedPassage);
                        }}
                      >
                        打开章节来源
                      </button>
                    </section>
                  </div>
                  {outOfRange(selectedDocument, selectedPassage) && (
                    <p className="notice">
                      这条资料暂不适用于这一章。可以换一段正文，或先核对资料的适用范围。
                    </p>
                  )}
                  {selectedDocument.disclosure === "hidden" && (
                    <p className="notice">
                      这个秘密还没告诉读者。核对时，也想一想：角色在这一刻知道多少？
                    </p>
                  )}
                  {unavailable && (
                    <p className="notice error" role="alert">
                      选中的资料已变化或不再适用，请重新选择后判断。
                    </p>
                  )}
                  {context.remote && (
                    <AuthorContextAnalysis
                      key={`${selectedDocument.id}:${selectedDocument.revision}:${selectedPassage.id}:${project.source_revision}`}
                      remote={context.remote}
                      document={selectedDocument}
                      passage={selectedPassage}
                      sourceRevision={project.source_revision ?? 0}
                      disabled={
                        blocked ||
                        unavailable ||
                        outOfRange(selectedDocument, selectedPassage)
                      }
                    />
                  )}
                  <section className="ac-decision">
                    {comparisonDirty && (
                      <button
                        type="button"
                        className="quiet"
                        onClick={() => {
                          setReason("");
                          setResolution("");
                          setError("");
                        }}
                      >
                        清空未保存判断
                      </button>
                    )}
                    <h3>
                      {selectedDocument.nature === "plan"
                        ? "这段正文与原来的故事安排，需要调整吗？"
                        : "这段正文与资料，需要调整吗？"}
                    </h3>
                    <p>
                      {selectedDocument.nature === "plan"
                        ? "故事也许有了新的方向。和原计划不同，不一定需要改回去。"
                        : live(
                            "这里只提供双方内容，由你决定是否需要调整。",
                            "结合前后文和你的构思，选一个合适的处理方式。",
                          )}
                    </p>
                    <fieldset className="ac-resolutions">
                      <legend className="sr-only">我的判断</legend>
                      {(
                        [
                          "revise_text",
                          "intentional",
                          "not_issue",
                          "later",
                        ] as Resolution[]
                      ).map((value) => (
                        <label key={value}>
                          <input
                            type="radio"
                            name="resolution"
                            value={value}
                            disabled={blocked || unavailable}
                            checked={resolution === value}
                            onChange={() => setResolution(value)}
                          />
                          {resolutions[value]}
                        </label>
                      ))}
                    </fieldset>
                    <label>
                      判断理由
                      <textarea
                        rows={3}
                        maxLength={2000}
                        value={reason}
                        disabled={blocked || unavailable}
                        onChange={(e) => setReason(e.target.value)}
                        placeholder="例如：主角此时并不知道真相，这处描述是有意安排。"
                      />
                    </label>
                    <div className="ac-footer">
                      <button
                        type="button"
                        disabled={blocked || unavailable}
                        onClick={() => {
                          edit(selectedDocument);
                          setAdjusting(true);
                          setAdjustReason(reason);
                        }}
                      >
                        调整作者资料
                      </button>
                      <button
                        type="button"
                        className="primary"
                        disabled={
                          blocked ||
                          unavailable ||
                          !resolution ||
                          !reason.trim()
                        }
                        onClick={record}
                      >
                        记录本次判断
                      </button>
                    </div>
                  </section>
                </>
              )}
            </>
          )}

          {view === "history" && (
            <>
              <p className="ac-note">
                {live(
                  "这些是本浏览器的人工对照记录，不是真实检查生成的问题。决定只对应当时的资料与正文，不形成全局忽略规则。",
                  "这里记着你当时的考虑。每次决定只针对那一处内容；资料或正文改动后，可以再核对一次。",
                )}
              </p>
              {!comparisons.length && (
                <div className="empty">
                  <strong>还没有对照决定</strong>
                  <p>选择资料与原文后，记录你对这一次疑问的处理。</p>
                  <button
                    type="button"
                    className="quiet"
                    onClick={() => setView("compare")}
                  >
                    {live("开始对照预览", "开始正文对照")}
                  </button>
                </div>
              )}
              <div className="ac-list">
                {comparisons
                  .slice(currentPage * 5, currentPage * 5 + 5)
                  .map((item) => {
                    const stale = backendConnected
                      ? Boolean(item.serverStale)
                      : comparisonStale(
                          item,
                          documents,
                          passages,
                          project.source_revision ?? 0,
                        ) || formalConflict(item.document, formal);
                    return (
                      <article key={item.id} className="ac-document">
                        <div className="ac-section-heading">
                          <div>
                            <span className="eyebrow">
                              {item.resolution === "revise_document" ? live("已调整预览资料", "已调整作者资料") : resolutions[item.resolution]}
                            </span>
                            <h3>{item.document.title}</h3>
                          </div>
                          <small>
                            {new Date(item.at).toLocaleDateString("zh-CN")}
                          </small>
                        </div>
                        <p>{item.reason}</p>
                        <p className="ac-note">
                          第 {item.passage.number} 章 · {item.passage.title} ·
                          资料 v{item.document.revision}
                        </p>
                        {item.superseded && <p className="ac-note">你后来更新了决定，这里保留的是之前的记录。</p>}
                        {stale ? (
                          <p className="notice">
                            资料或正文有了改动，建议再核对一次。之前的决定仍保留在这里。
                          </p>
                        ) : item.resolution === "revise_text" ? (
                          <p className="ac-note">
                            已记下要修改的地方。去写作页改好正文后，再检查一次。
                          </p>
                        ) : item.resolution === "revise_document" ? (
                          <p className="ac-note">
                            {live(
                              "仅已调整预览资料，正式内容尚未改变，仍需重新检查。",
                              "资料已经调整好，可以用新内容再检查一次。",
                            )}
                          </p>
                        ) : item.resolution === "later" ? (
                          <p className="ac-note">
                            仍待处理，可以继续其他创作。
                          </p>
                        ) : null}
                        <div className="ac-card-actions">
                          <button
                            type="button"
                            className="quiet"
                            aria-expanded={openHistory === item.id}
                            onClick={() =>
                              setOpenHistory(
                                openHistory === item.id ? null : item.id,
                              )
                            }
                          >
                            查看当时依据
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              choosePair(item.document.id, item.passage.id);
                              setView("compare");
                              setReason("");
                              setResolution("");
                              setFeedback("");
                            }}
                          >
                            重新对照
                          </button>
                          {item.resolution === "revise_text" && (
                            <button
                              type="button"
                              className="quiet"
                              onClick={() => go("workspace")}
                            >
                              前往写作页
                            </button>
                          )}
                        </div>
                        {openHistory === item.id && (
                          <div className="ac-history-evidence">
                            {item.previousDocument && (
                              <>
                                <strong>调整前的资料</strong>
                                <p className="ac-fulltext">
                                  {item.previousDocument.content}
                                </p>
                              </>
                            )}
                            <strong>当时的作者资料</strong>
                            <Scope document={item.document} />
                            <p className="ac-fulltext">
                              {item.document.content}
                            </p>
                            {item.document.knowledge && (
                              <p>{item.document.knowledge}</p>
                            )}
                            <strong>
                              当时的正文 · 第 {item.sourceRevision} 版
                            </strong>
                            <blockquote>{item.passage.text}</blockquote>
                          </div>
                        )}
                      </article>
                    );
                  })}
              </div>
              <Pager
                page={currentPage}
                total={comparisons.length}
                change={setPage}
              />
            </>
          )}
        </>
      )}
    </dialog>
  );
}
