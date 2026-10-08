"use client";

import { useEffect, useState } from "react";
import { request } from "../../api";
import type { Onboarding } from "../../model";
import { Button, Num, pad2 } from "../ui";

export function NotFoundPage({ kind, go }: { kind: "page" | "project"; go: (href: string) => void }) {
  return (
    <section className="page not-found" aria-labelledby="not-found-title">
      <Num className="not-found-num">404</Num>
      <h1 id="not-found-title">{kind === "project" ? "找不到这部作品" : "找不到这个页面"}</h1>
      <p>{kind === "project" ? "它可能已经删除，或者不属于当前账号。其他作品不受影响。" : "网址可能输错了，或者这个页面已经不在了。"}</p>
      <div className="form-actions">
        <Button kind="primary" size="lg" onClick={() => go("/projects")}>作品管理</Button>
        <Button size="lg" onClick={() => go("/")}>回到首页</Button>
      </div>
    </section>
  );
}

const tourSteps = ["在资料里找到一条事实，看它出自哪一章", "打开写作页，找到检查结果", "对照草稿和前文依据", "对一处问题作出决定", "完成一次检查"];

/** 导览结束. Opened directly by URL, it must not claim a tour the author never finished. */
export function TutorialCompletePage({ go }: { go: (href: string) => void }) {
  const [status, setStatus] = useState<Onboarding["status"] | null>(null);
  const [tutorialId, setTutorialId] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    request<Onboarding>("/onboarding").then((next) => { if (live) { setStatus(next.status); setTutorialId(next.tutorial?.project_id ?? null); } }).catch(() => { if (live) setStatus("completed"); });
    return () => { live = false; };
  }, []);
  const finished = status === null || status === "completed";
  return (
    <section className="page tour-done" aria-busy={status === null}>
      <p className="label">{finished ? "导览 · 已完成" : status === "skipped" ? "导览 · 已跳过" : "导览 · 进行中"}</p>
      <h1>{finished ? "导览完成了" : status === "skipped" ? "你跳过了导览" : "导览还没走完"}</h1>
      <p className="tour-done-lede">{finished ? "你已经走完了一次检查的完整流程。接下来，带上自己的作品。" : "导览会带你走一遍下面的流程，大约几分钟。"}</p>
      <ol className="tour-steps">
        {tourSteps.map((step, index) => <li key={step} className={finished ? "done" : undefined}><Num>{pad2(index + 1)}</Num><span>{step}</span></li>)}
      </ol>
      <div className="form-actions">
        {!finished && status === "active" && tutorialId && <Button kind="primary" size="lg" onClick={() => go(`/projects/${tutorialId}/overview`)}>继续导览</Button>}
        <Button kind={finished || status !== "active" || !tutorialId ? "primary" : "outline"} size="lg" onClick={() => go("/projects/import")}>导入自己的作品</Button>
        <Button size="lg" onClick={() => go("/projects/new")}>新建空白作品</Button>
        <Button kind="text" onClick={() => go("/")}>回到首页</Button>
      </div>
    </section>
  );
}
