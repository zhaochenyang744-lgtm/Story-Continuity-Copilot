"use client";

// An empty conversation: questions to start from, made from a template (no model is asked): where the previous chapter
// ends, one for each of the two people who appear most in the draft, and one asking for advice (which threads are still open). A visitor on the sample work gets the same, counted in the
// sample's own draft.

export type Starter = { text: string; why: string; icon: "chapter" | "person" | "threads"; /** Shown at the row's right end (a person's count); the rest say `why` when pointed at. */ aside?: string };

/** How often `name` is in `body`. */
const occurrences = (body: string, name: string) => (name ? body.split(name).length - 1 : 0);

export function starterQuestions({ lastChapter, characters, draftBody }: {
  /** The chapter before the draft (the last written one), or null when there is none. */
  lastChapter: number | null;
  characters: { name: string }[];
  draftBody: string;
}): Starter[] {
  const found = characters
    .map((person) => ({ name: person.name, count: occurrences(draftBody, person.name) }))
    .filter((person) => person.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 2);
  return [
    ...(lastChapter ? [{ text: `第 ${lastChapter} 章结尾写到哪了？`, why: "接着写之前", icon: "chapter" as const }] : []),
    ...found.map((person, index) => ({ text: index === 0 ? `${person.name}现在知道些什么？` : `${person.name}上一次出场在做什么？`, why: `草稿里出现 ${person.count} 次`, aside: `出现 ${person.count} 次`, icon: "person" as const })),
    { text: "有哪些伏笔还没收？", why: "请助手出主意，每条都带出处", icon: "threads" as const },
  ];
}

const ICONS: Record<Starter["icon"] | "recap", string> = {
  chapter: "M5 3h6v10l-3-2-3 2z",
  person: "M8 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM3.5 13.5c.6-2.3 2.3-3.5 4.5-3.5s3.9 1.2 4.5 3.5",
  threads: "M4 3v10M4 8c0-2.5 2-3.5 4.5-3.5H12M10 2.5l2 2-2 2",
  recap: "M8 3.5A4.5 4.5 0 1 1 3.6 7M3.5 3.5V7H7M8 5.5V8l1.8 1.2",
};
function Glyph({ name }: { name: keyof typeof ICONS }) {
  return <svg className="a-glyph" viewBox="0 0 16 16" aria-hidden="true"><path d={ICONS[name]} fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

/** A small hello at the foot of the empty panel (just above the box): what the assistant does, 写前回顾 as its own row on the writing page, and the
    questions to start from as a list. */
export function Starters({ intro, items, ask, recap, disabled = false }: {
  intro: string;
  items: Starter[];
  ask: (question: string) => void;
  /** The day's allowance is used up: the questions stay in view but cannot be pointed at. */
  disabled?: boolean;
  /** 写前回顾 (the writing page only); null elsewhere. `chapter` is the chapter about to be written. */
  recap: { run: () => void; reason: string; chapter: number | null } | null;
}) {
  return (
    <div className="a-start">
      <div className="a-hello">
        <p className="a-hello-title"><i className="a-mark" aria-hidden="true" />问这部作品里的人、事、物</p>
        <p className="a-intro">{intro}</p>
      </div>
      {recap && (
        <button type="button" className="a-recap-row" disabled={disabled || Boolean(recap.reason)} title={recap.reason || undefined} onClick={recap.run}>
          <Glyph name="recap" />
          <span className="what">
            <strong>写前回顾</strong>
            <small>{recap.reason || `${recap.chapter ? `动笔第 ${recap.chapter} 章前：` : ""}上一章停在哪、人物现在的状态、还没收的线`}</small>
          </span>
        </button>
      )}
      {items.length > 0 && (
        <div className="a-start-list">
          <p className="a-start-label">可以先问</p>
          <ul className={`a-starters${disabled ? " off" : ""}`} aria-label="可以先问这些">
            {items.map((item) => (
              <li key={item.text}>
                <button type="button" disabled={disabled} title={item.aside ? undefined : item.why} onClick={() => ask(item.text)}>
                  <Glyph name={item.icon} />
                  <span className="q">{item.text}</span>
                  {item.aside && <span className="why">{item.aside}</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
