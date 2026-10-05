"use client";
import { useEffect, useRef, useState } from "react";
import {
  contextError,
  type ContextAnalysis,
  type createBackendStore,
} from "./author-context-api";
import type { AuthorDocument, Passage } from "./author-context-model";

export function AuthorContextAnalysis({
  remote,
  document,
  passage,
  sourceRevision,
  disabled,
}: {
  remote: ReturnType<typeof createBackendStore>;
  document: AuthorDocument;
  passage: Passage;
  sourceRevision: number;
  disabled: boolean;
}) {
  const [run, setRun] = useState<ContextAnalysis | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const comparison = remote.findComparison(document, passage, sourceRevision);
    if (comparison)
      void remote.api
        .comparison(comparison.id)
        .then(async (item) => {
          if (item.latest_analysis_run_id) {
            const result = await remote.api.readAnalysis(
              item.latest_analysis_run_id,
            );
            if (mounted.current) setRun(result);
          }
        })
        .catch((cause) => {
          if (mounted.current) setError(contextError(cause));
        });
    return () => {
      mounted.current = false;
    };
  }, [remote, document, passage, sourceRevision]);
  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.status)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void remote.api
        .readAnalysis(run.run_id, controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) {
            setRun(result);
            setError("");
          }
        })
        .catch((cause) => {
          if (!controller.signal.aborted) setError(contextError(cause));
        });
    }, 1200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [remote, run]);
  const start = async (retry = false) => {
    if (disabled || busy) return;
    setBusy(true);
    setError("");
    try {
      const next =
        retry && run
          ? await remote.api.retryAnalysis(run.run_id)
          : await remote.api.analyze(
              await remote.comparisonFor(document, passage, sourceRevision),
            );
      if (mounted.current) setRun(next);
    } catch (cause) {
      if (mounted.current) setError(contextError(cause));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };
  const active = Boolean(run && ["queued", "running"].includes(run.status));
  const labels = {
    aligned: "暂未发现明显不一致",
    possible_tension: "有一处值得核对",
    plan_deviation: "可能偏离原有安排",
    insufficient_evidence: "还需要更多内容才能判断",
  };
  return (
    <section className="ac-analysis" aria-label="AI 对照分析">
      <div className="ac-section-heading">
        <div>
          <h3>让 AI 帮你看看</h3>
          <p>AI 会对照这条资料和正文，给你一些参考。怎么处理，还是由你决定。</p>
          {process.env.NEXT_PUBLIC_EXPERIENCE_SIMULATION === "1" && (
            <small>当前是模拟体验，展示的是示例分析，供你熟悉操作。</small>
          )}
        </div>
        {!active && (
          <button
            type="button"
            disabled={disabled || busy}
            onClick={() => void start()}
          >
            {busy ? "正在开始分析…" : "请 AI 帮我对照"}
          </button>
        )}
      </div>
      {error && (
        <div className="notice error" role="alert">
          <p>{error}</p>
          {active && (
            <button
              type="button"
              className="quiet"
              onClick={() =>
                void remote.api
                  .readAnalysis(run!.run_id)
                  .then(setRun)
                  .catch((cause) => setError(contextError(cause)))
              }
            >
              刷新分析进度
            </button>
          )}
        </div>
      )}
      {active && (
        <div className="ac-section-heading" role="status">
          <p>
            {run?.status === "queued" ? "分析已排队" : "正在对照资料与原文…"}
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={async () => {
              if (!run) return;
              setBusy(true);
              try {
                const cancelled = await remote.api.cancelAnalysis(run.run_id);
                if (mounted.current) setRun(cancelled);
              } catch (cause) {
                if (mounted.current) setError(contextError(cause));
              } finally {
                if (mounted.current) setBusy(false);
              }
            }}
          >
            取消分析
          </button>
        </div>
      )}
      {run?.status === "completed" && run.analysis && (
        <div className="ac-analysis-result">
          <span className="eyebrow">AI 分析建议</span>
          <h3>{labels[run.analysis.assessment]}</h3>
          <p>{run.analysis.explanation}</p>
          <small>
            依据：作者资料《{document.title}》与第 {passage.number}{" "}
            章原文。上方可以查看这次用到的具体内容。
          </small>
        </div>
      )}
      {run?.is_stale && (
        <p className="notice">
          资料或正文已经改动，这份建议对应的是之前的内容，可以重新分析一次。
        </p>
      )}
      {run && ["failed", "timed_out", "cancelled"].includes(run.status) && (
        <div className="notice">
          <p>
            {run.status === "cancelled"
              ? "分析已取消，还没有生成建议。"
              : run.status === "timed_out"
                ? "这次分析用时太久，还没能生成建议。可以稍后重试。"
                : "这次没能完成分析，还没有可用的建议。"}
          </p>
          {run.retryable && (
            <button
              type="button"
              className="quiet"
              disabled={disabled || busy}
              onClick={() => void start(true)}
            >
              重试分析
            </button>
          )}
        </div>
      )}
    </section>
  );
}
