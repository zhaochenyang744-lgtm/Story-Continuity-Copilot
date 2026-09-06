import Image from "next/image";
import type { ReactNode } from "react";

export function DesignIcon({
  name,
}: {
  name:
    | "edit"
    | "book"
    | "file"
    | "bulb"
    | "grid"
    | "feather"
    | "film"
    | "more"
    | "spark"
    | "shield";
}) {
  const paths: Record<typeof name, ReactNode> = {
    edit: (
      <path d="m14 5 5 5m-9 9 11-11a2 2 0 0 0-5-5L5 14l-1 6ZM11 4H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6" />
    ),
    book: (
      <path d="M12 5C9 3 5 3 3 4v16c3-1 6-1 9 1 3-2 6-2 9-1V4c-2-1-6-1-9 1Zm0 0v16" />
    ),
    file: (
      <path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8Zm0 0v5h5M9 12h6m-6 4h6" />
    ),
    bulb: (
      <path d="M8 17c0-3-3-4-3-8a7 7 0 0 1 14 0c0 4-3 5-3 8Zm1 4h6m-3-4v-6m-2-2 2 2 2-2M2 2 1 1m21 1 1-1M1 10H0m24 0h-1" />
    ),
    grid: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </>
    ),
    feather: (
      <path d="M3 22 16 9M7 18C3 10 10 3 21 2c0 9-5 18-14 16Zm7-7 5 1" />
    ),
    film: (
      <path d="M3 8h18v13H3Zm0 0-1-4 18-3 1 4ZM7 3l2 4m4-5 2 4m-3 6 4 3-4 3Z" />
    ),
    more: (
      <>
        <circle cx="5" cy="12" r="1" />
        <circle cx="12" cy="12" r="1" />
        <circle cx="19" cy="12" r="1" />
      </>
    ),
    spark: (
      <path d="m10 2 2.5 6.5L19 11l-6.5 2.5L10 20l-2.5-6.5L1 11l6.5-2.5Zm9 13 1.1 2.9L23 19l-2.9 1.1L19 23l-1.1-2.9L15 19l2.9-1.1Z" />
    ),
    shield: <path d="m12 2 9 4v6c0 5-6 8-9 10-3-2-9-5-9-10V6Zm-5 9 3 3 7-7" />,
  };
  return (
    <svg className="design-icon" viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}

export function DesignAsset({ name }: { name: "paper" | "bulb" }) {
  return <Image className={`design-raster design-raster-${name}`} src={name === "bulb" ? "/assets/v140/creative-bulb.png" : "/assets/v140/manuscript-glass.png"} alt="" aria-hidden="true" width={80} height={80} unoptimized />;
}

export function CreativeTips({ importing = false }: { importing?: boolean }) {
  const tips = importing
    ? [
        {
          icon: "file" as const,
          title: "建议按章节划分",
          text: "使用清晰的章节标题，有助于准确拆分内容。",
        },
        {
          icon: "shield" as const,
          title: "由你决定何时发送",
          text: "选择文件后，点击预览才会将内容发送到当前应用服务。",
        },
        {
          icon: "book" as const,
          title: "确认后才创建作品",
          text: "先核对章节片段，再确认导入；预览阶段可以取消。",
        },
      ]
    : [
        {
          icon: "file" as const,
          title: "清晰的作品名称",
          text: "一个好的名字，能让读者更容易记住你的作品。",
        },
        {
          icon: "grid" as const,
          title: "选择合适的类型",
          text: "为故事选择一种表达形式，之后也可以随时调整。",
        },
        {
          icon: "feather" as const,
          title: "写下作品的起点",
          text: "不需要很长，一两句话即可，之后也可以随时修改。",
        },
      ];
  return (
    <aside
      className="design-tips"
      aria-label={importing ? "导入提示" : "创建提示"}
    >
      <header className="design-section-head">
        <span className="design-icon-tile">
          <DesignAsset name="bulb" />
        </span>
        <div>
          <h2>{importing ? "导入小提示" : "创作小提示"}</h2>
          <p>
            {importing
              ? "让故事的每一章，都有迹可循。"
              : "好的开始，是成功的一半。"}
          </p>
        </div>
      </header>
      <ol>
        {tips.map((tip, index) => (
          <li key={tip.title}>
            <span className="design-tip-icon">
              <span className="design-tip-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
            </span>
            <div>
              <h3>{tip.title}</h3>
              <p>{tip.text}</p>
            </div>
          </li>
        ))}
      </ol>
      {(
        <div className="design-closing">
          <blockquote>
            {importing ? "「 让已有的故事，" : "「 每一个故事，"}
            <br />
            <span>{importing ? "在这里继续生长。 」" : "都从一个想法开始。 」"}</span>
          </blockquote>
          <i />
          <span>STORY CONTINUITY</span>
        </div>
      )}
    </aside>
  );
}
