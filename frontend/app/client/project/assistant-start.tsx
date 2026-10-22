"use client";

// An empty conversation: questions to start from, made from a template (no model is asked): where the previous chapter
// ends, one for each of the two people who appear most in the draft, and one asking for advice (which threads are still open). A visitor on the sample work gets the same, counted in the
// sample's own draft.

export type Starter = { text: string; why: string };

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
    ...(lastChapter ? [{ text: `第 ${lastChapter} 章结尾写到哪了？`, why: "接着写之前" }] : []),
    ...found.map((person, index) => ({ text: index === 0 ? `${person.name}现在知道些什么？` : `${person.name}上一次出场在做什么？`, why: `草稿里出现 ${person.count} 次` })),
    { text: "有哪些伏笔还没收？", why: "请助手出主意，每条都带出处" },
  ];
}

/** The three questions as a list of buttons, and (on the writing page) a 写前回顾 button under it. */
export function Starters({ intro, items, ask, recap }: {
  intro: string;
  items: Starter[];
  ask: (question: string) => void;
  /** 写前回顾 (the writing page only); null elsewhere. */
  recap: { run: () => void; reason: string } | null;
}) {
  return (
    <div className="a-start">
      <p className="a-intro">{intro}</p>
      {items.length > 0 && (
        <ul className="a-starters" aria-label="可以先问这些">
          {items.map((item) => (
            <li key={item.text}>
              <button type="button" onClick={() => ask(item.text)}>
                <span>{item.text}<span className="why">　{item.why}</span></span>
                <span className="arrow" aria-hidden="true">→</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {recap && <button type="button" className="a-recap-btn" disabled={Boolean(recap.reason)} title={recap.reason || undefined} onClick={recap.run}>写前回顾</button>}
    </div>
  );
}
