// Days and times as the author's pages show them.

/** Every per-day figure (the writing calendar, the streak, the last days of usage) is cut at midnight in Beijing time,
    UTC+8. The server uses the same constant (author_home.DAY_UTC_OFFSET_HOURS) and sends the days already cut. */
export const DAY_UTC_OFFSET_HOURS = 8;

const parts = (day: string) => day.split("-").map(Number) as [number, number, number];
const pad = (value: number) => String(value).padStart(2, "0");

/** The Beijing-time day (YYYY-MM-DD) a moment falls on. */
export const localDay = (iso: string) => new Date(Date.parse(iso) + DAY_UTC_OFFSET_HOURS * 3_600_000).toISOString().slice(0, 10);
/** The day `count` days after `day` (before, when negative). */
export const shiftDay = (day: string, count: number) => {
  const [year, month, date] = parts(day);
  return new Date(Date.UTC(year, month - 1, date + count)).toISOString().slice(0, 10);
};
/** 0 = Sunday … 6 = Saturday. */
export const weekdayOf = (day: string) => {
  const [year, month, date] = parts(day);
  return new Date(Date.UTC(year, month - 1, date)).getUTCDay();
};
/** "10 月 12 日" */
export const monthDayLabel = (day: string) => {
  const [, month, date] = parts(day);
  return `${month} 月 ${date} 日`;
};
/** "9 月 21 日" for a moment, in Beijing time. */
export const momentDayLabel = (iso: string) => monthDayLabel(localDay(iso));
/** "2026 年 9 月加入" */
export const joinedLabel = (iso: string) => {
  const [year, month] = parts(localDay(iso));
  return `${year} 年 ${month} 月加入`;
};
/** 今天 / 昨天 / 10/12, for the activity feed. */
export const feedDayLabel = (day: string, today: string) => {
  if (day === today) return "今天";
  if (day === shiftDay(today, -1)) return "昨天";
  const [, month, date] = parts(day);
  return `${pad(month)}/${pad(date)}`;
};
/** "10/09", and "今天" for the last of a row of days. */
export const shortDay = (day: string, today: string) => {
  if (day === today) return "今天";
  const [, month, date] = parts(day);
  return `${pad(month)}/${pad(date)}`;
};
/** How long ago, in the author's words. */
export const agoLabel = (iso: string, now = Date.now()) => {
  const minutes = Math.max(0, Math.floor((now - Date.parse(iso)) / 60_000));
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} 小时前`;
  return `${Math.floor(minutes / (24 * 60))} 天前`;
};
/** How long until a moment, as "3 小时 20 分钟" (at least a minute). */
export const untilLabel = (iso: string, now = Date.now()) => {
  const minutes = Math.max(1, Math.ceil((Date.parse(iso) - now) / 60_000));
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} 小时${minutes % 60 ? ` ${minutes % 60} 分钟` : ""}` : `${minutes} 分钟`;
};
