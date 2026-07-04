export type Workspace = {
  id: string;
  name: string;
  role: "owner" | "member";
  created_at: string;
};

export type Calendar = {
  id: string;
  workspace_id: string;
  name: string;
  color: string;
  created_at: string;
};

/** Mirrors ember.models.calendar.DEFAULT_CALENDAR_COLOR. */
export const DEFAULT_CALENDAR_COLOR = "#4f46e5";

export type RecurrenceFreq = "DAILY" | "WEEKLY" | "MONTHLY" | "YEARLY";

/** Mirrors ember.schemas.events.RecurrenceRule. `by_weekday` is 0=Monday..6=Sunday
 * (weekly only); at most one of `count`/`until` is set, neither means "never ends". */
export type RecurrenceRule = {
  freq: RecurrenceFreq;
  interval: number;
  by_weekday: number[] | null;
  count: number | null;
  until: string | null;
};

export type EventItem = {
  id: string;
  calendar_id: string;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string;
  all_day: boolean;
  color: string | null;
  attendees: string[];
  recurrence: RecurrenceRule | null;
};

/** Google-style named event colors. `value` is null for "calendar default". */
export const EVENT_COLORS = [
  { name: "Calendar default", value: null },
  { name: "Grape", value: "#7c3aed" },
  { name: "Flamingo", value: "#e11d48" },
  { name: "Tangerine", value: "#ea580c" },
  { name: "Banana", value: "#ca8a04" },
  { name: "Sage", value: "#16a34a" },
  { name: "Peacock", value: "#0891b2" },
  { name: "Blueberry", value: "#4f46e5" },
  { name: "Graphite", value: "#4b5563" },
] as const;

export type TimeFormat = "12h" | "24h";

export type Preferences = {
  locale: string;
  timezone: string;
  /** 0 = Sunday .. 6 = Saturday. */
  week_starts_on: number;
  /** Whole-hour bounds [start, end) shaded as working time in the calendar. */
  work_day_start: number;
  work_day_end: number;
  time_format: TimeFormat;
};

export const DEFAULT_PREFERENCES: Preferences = {
  locale: "en-US",
  timezone: "UTC",
  week_starts_on: 0,
  work_day_start: 9,
  work_day_end: 17,
  time_format: "12h",
};
