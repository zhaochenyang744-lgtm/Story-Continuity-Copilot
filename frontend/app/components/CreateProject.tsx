"use client";

import { useState, type FormEvent } from "react";
import { labelError } from "../api";
import { CreativeTips, DesignAsset } from "./VisualPrimitives";

export function CreateProject({
  busy,
  error,
  submit,
}: {
  busy: string;
  error: unknown;
  submit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  const [kind, setKind] = useState("小说");
  const [custom, setCustom] = useState("");
  const [summary, setSummary] = useState("");
  const kinds = [
    { value: "小说", icon: "book" },
    { value: "短篇", icon: "file" },
    { value: "剧本", icon: "film" },
    { value: "散文", icon: "feather" },
    { value: "其他", icon: "more" },
  ] as const;
  return (
    <section className="approved-create">
      <header className="design-page-head">
        <div className="design-hero-art" aria-hidden="true" />
        <div className="design-page-heading">
          <p className="breadcrumb">全局 / 作品管理 / 新建作品</p>
          <h1>新建作品</h1>
          <p>填写基础信息，开始你的全新创作。</p>
        </div>
        <div className="design-hero-quote" aria-hidden="true">
          记录想象，
          <br />
          让故事延续。
          <i />
        </div>
      </header>
      <section className="design-creation-panel" aria-label="新建作品表单">
        <form onSubmit={(event) => void submit(event)}>
          <header className="design-section-head">
            <span className="design-icon-tile">
              <DesignAsset name="paper" />
            </span>
            <div>
              <h2>作品信息</h2>
              <p>完善以下信息，让你的作品拥有一个好的开始。</p>
            </div>
          </header>
          <div className="design-field">
            <label htmlFor="new-work-title">
              作品名称 <span className="design-badge required">必填</span>
            </label>
            <p className="design-help" id="new-title-help">
              给你的作品起一个独特的名字，便于后续管理。
            </p>
            <input
              id="new-work-title"
              name="title"
              required
              maxLength={80}
              disabled={Boolean(busy)}
              autoComplete="off"
              placeholder="例如：潮汐之后"
              aria-describedby="new-title-help"
            />
          </div>
          <fieldset className="design-field">
            <legend>
              类型 <span className="design-badge">可选</span>
            </legend>
            <p className="design-help">选择作品的主要形式，便于分类与管理。</p>
            <div className="design-type-options">
              {kinds.map((item) => (
                <label className="design-type-choice" key={item.value}>
                  <input
                    type="radio"
                    name="visual-work-kind"
                    value={item.value}
                    checked={kind === item.value}
                    onChange={() => setKind(item.value)}
                    disabled={Boolean(busy)}
                  />
                  <span>
                    
                    {item.value}
                  </span>
                </label>
              ))}
            </div>
            <input
              type="hidden"
              name="genre"
              value={kind === "其他" ? custom : kind}
            />
            {kind === "其他" && (
              <input
                className="design-custom-type"
                aria-label="其他作品类型"
                maxLength={80}
                placeholder="填写其他类型（可选）"
                value={custom}
                onChange={(event) => setCustom(event.target.value)}
                disabled={Boolean(busy)}
              />
            )}
          </fieldset>
          <div className="design-field design-summary">
            <label htmlFor="new-work-summary">
              简介 <span className="design-badge">可选</span>
            </label>
            <p className="design-help" id="new-summary-help">
              用一两句话说明这部作品的起点。
            </p>
            <div className="design-textarea-wrap">
              <textarea
                id="new-work-summary"
                name="summary"
                maxLength={500}
                value={summary}
                onChange={(event) => setSummary(event.target.value)}
                disabled={Boolean(busy)}
                aria-describedby="new-summary-help"
                placeholder="例如：在一座被潮水淹没的城市里，少年重新听见了世界的声音……"
              />
              <span className="design-char-count">
                {Array.from(summary).length} / 500
              </span>
            </div>
          </div>
          {Boolean(error) && (
            <p className="inline-error" role="alert">
              {labelError(error)}
            </p>
          )}
          <button
            className="primary design-create-button"
            type="submit"
            disabled={Boolean(busy)}
            aria-busy={Boolean(busy)}
          >
            
            {busy || "创建并进入作品"}
          </button>
        </form>
        <CreativeTips />
      </section>
    </section>
  );
}
