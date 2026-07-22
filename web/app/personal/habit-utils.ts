// Pure, React-free helpers for the habit tracker. Dates are ISO YYYY-MM-DD in
// UTC to match how completions are stored in personal-space (`today()` uses
// `toISOString().slice(0, 10)`). Weekdays are 0=Mon..6=Sun, matching
// RecurrenceRule.by_weekday in web/lib/types.ts.
import type { HabitData, HabitSchedule } from "@/lib/types";

const MAX_LOOKBACK_DAYS = 800;

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

/** ISO YYYY-MM-DD for a Date, in UTC. */
export function toISO(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Parse an ISO date to a UTC-midnight Date. */
export function fromISO(iso: string): Date {
  return new Date(`${iso}T00:00:00Z`);
}

/** Weekday for an ISO date, 0=Mon..6=Sun. */
export function weekdayOf(iso: string): number {
  return (fromISO(iso).getUTCDay() + 6) % 7;
}

/** Coerce arbitrary `data` into a valid schedule; legacy habits default daily. */
export function normalizeSchedule(data: Pick<HabitData, "schedule"> | Record<string, unknown>): HabitSchedule {
  const schedule = (data as Partial<HabitData>).schedule;
  if (Array.isArray(schedule)) {
    const days = schedule.filter((day): day is number => typeof day === "number" && day >= 0 && day <= 6);
    return days.length ? Array.from(new Set(days)).sort((a, b) => a - b) : "daily";
  }
  return "daily";
}

/** Completion dates from arbitrary `data`, ignoring malformed entries. */
export function habitDates(data: Record<string, unknown>): string[] {
  return Array.isArray(data.dates) ? (data.dates.filter((d) => typeof d === "string") as string[]) : [];
}

export function isScheduled(schedule: HabitSchedule, iso: string): boolean {
  return schedule === "daily" || schedule.includes(weekdayOf(iso));
}

/** Consecutive scheduled days completed, counting back from today. A missed
 * past scheduled day breaks the streak; today-not-yet-done is grace. */
export function computeStreak(dates: string[], schedule: HabitSchedule): number {
  const done = new Set(dates);
  const today = todayISO();
  const cursor = fromISO(today);
  let streak = 0;
  for (let i = 0; i < MAX_LOOKBACK_DAYS; i++) {
    const iso = toISO(cursor);
    if (isScheduled(schedule, iso)) {
      if (done.has(iso)) streak++;
      else if (iso !== today) break;
    }
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
  return streak;
}

/** Longest run of consecutive scheduled-and-done days from the first completion
 * through today. */
export function longestStreak(dates: string[], schedule: HabitSchedule): number {
  if (!dates.length) return 0;
  const done = new Set(dates);
  const cursor = fromISO([...dates].sort()[0]);
  const end = fromISO(todayISO());
  let best = 0;
  let run = 0;
  while (cursor <= end) {
    const iso = toISO(cursor);
    if (isScheduled(schedule, iso)) {
      if (done.has(iso)) {
        run += 1;
        best = Math.max(best, run);
      } else {
        run = 0;
      }
    }
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return best;
}

/** Share of scheduled days completed in [sinceISO, today], 0..1. */
export function completionRate(dates: string[], schedule: HabitSchedule, sinceISO: string): number {
  const done = new Set(dates);
  const cursor = fromISO(sinceISO);
  const end = fromISO(todayISO());
  let scheduled = 0;
  let completed = 0;
  while (cursor <= end) {
    const iso = toISO(cursor);
    if (isScheduled(schedule, iso)) {
      scheduled += 1;
      if (done.has(iso)) completed += 1;
    }
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return scheduled === 0 ? 0 : completed / scheduled;
}

/** ISO date `days` ago from today (inclusive window start for rates). */
export function daysAgoISO(days: number): string {
  const cursor = fromISO(todayISO());
  cursor.setUTCDate(cursor.getUTCDate() - days);
  return toISO(cursor);
}

export type WeekDay = {
  iso: string;
  weekday: number;
  scheduled: boolean;
  done: boolean;
  isToday: boolean;
  isFuture: boolean;
};
export type WeekProgress = { done: number; total: number; days: WeekDay[] };

/** The 7 days of the current week (weekStartsOn: 0=Sun..6=Sat, default Monday). */
export function weekProgress(dates: string[], schedule: HabitSchedule, weekStartsOn = 1): WeekProgress {
  const done = new Set(dates);
  const today = todayISO();
  const start = fromISO(today);
  const offset = (start.getUTCDay() - weekStartsOn + 7) % 7;
  start.setUTCDate(start.getUTCDate() - offset);
  const days: WeekDay[] = [];
  let completed = 0;
  let total = 0;
  for (let i = 0; i < 7; i++) {
    const cur = new Date(start);
    cur.setUTCDate(start.getUTCDate() + i);
    const iso = toISO(cur);
    const scheduled = isScheduled(schedule, iso);
    const isDone = done.has(iso);
    if (scheduled) {
      total += 1;
      if (isDone) completed += 1;
    }
    days.push({ iso, weekday: weekdayOf(iso), scheduled, done: isDone, isToday: iso === today, isFuture: iso > today });
  }
  return { done: completed, total, days };
}

/** Bucket a 0..1 fraction into a heat level for the violet ramp. */
export function heatLevel(fraction: number): 0 | 1 | 2 | 3 | 4 {
  if (fraction <= 0) return 0;
  if (fraction >= 1) return 4;
  if (fraction < 0.34) return 1;
  if (fraction < 0.67) return 2;
  return 3;
}

/** GitHub-style grid: `weeks` columns of 7 ISO dates (rows = weekStartsOn..+6),
 * ending on the last day of the current week. */
export function heatGrid(weeks: number, weekStartsOn = 1): string[][] {
  const today = fromISO(todayISO());
  const endOffset = (weekStartsOn + 6 - today.getUTCDay() + 7) % 7;
  const start = new Date(today);
  start.setUTCDate(today.getUTCDate() + endOffset - (weeks * 7 - 1));
  const columns: string[][] = [];
  for (let w = 0; w < weeks; w++) {
    const column: string[] = [];
    for (let r = 0; r < 7; r++) {
      const cur = new Date(start);
      cur.setUTCDate(start.getUTCDate() + w * 7 + r);
      column.push(toISO(cur));
    }
    columns.push(column);
  }
  return columns;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Month label per grid column (empty unless the month changed at its top cell). */
export function monthLabels(columns: string[][]): string[] {
  let previous = -1;
  return columns.map((column) => {
    const month = fromISO(column[0]).getUTCMonth();
    if (month !== previous) {
      previous = month;
      return MONTHS[month];
    }
    return "";
  });
}
