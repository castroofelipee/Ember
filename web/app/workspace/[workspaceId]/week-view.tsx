"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { DEFAULT_PREFERENCES, type Calendar, type Preferences, type TimeFormat } from "@/lib/types";

const HOUR_PX = 56;
const DAY_MS = 24 * 60 * 60 * 1000;
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
// `getDay()` returns 0 (Sun)..6 (Sat), matching WEEKDAYS index order.
const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** A single scheduled block. Events are not wired to the backend yet, so the
 * grid renders empty until an events source is passed in. */
export type WeekEvent = {
  id: string;
  calendarId: string;
  calendarName?: string;
  title: string;
  description?: string | null;
  location?: string | null;
  attendees?: string[];
  start: Date;
  end: Date;
  color: string;
  allDay?: boolean;
};

export type CalendarView = "week" | "day";

type WeekViewProps = {
  calendars: Calendar[];
  preferences?: Preferences;
  /** "week" shows the 7-day grid; "day" shows a single column for `date`. */
  view: CalendarView;
  /** The focused day — the week containing it, or that day itself. Controlled. */
  date: Date;
  onDateChange: (date: Date) => void;
  onViewChange: (view: CalendarView) => void;
  events?: WeekEvent[];
  hiddenCalendarIds?: Set<string>;
  /** Fires when the visible day span changes, so the parent can fetch events. */
  onVisibleRangeChange?: (start: Date, end: Date) => void;
  /** Fires when an empty slot is clicked, to open the create dialog prefilled. */
  onSlotClick?: (start: Date) => void;
  /** Fires when an event block is clicked, to open its detail popover. */
  onEventClick?: (event: WeekEvent, anchor: DOMRect) => void;
};

/** Translucent fill from a hex color, for the frosted event blocks. */
function hexToRgba(hex: string, alpha: number): string {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const WEEKDAY_LONG = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

/** Midnight of the week containing `date`, respecting the user's chosen first
 * weekday (0 = Sunday .. 6 = Saturday). */
function startOfWeek(date: Date, weekStartsOn: number): Date {
  const result = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const shift = (result.getDay() - weekStartsOn + 7) % 7;
  result.setDate(result.getDate() - shift);
  return result;
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function formatHour(hour: number, format: TimeFormat): string {
  if (format === "24h") return `${String(hour).padStart(2, "0")}:00`;
  if (hour === 0) return "12 AM";
  if (hour === 12) return "Noon";
  if (hour < 12) return `${hour} AM`;
  return `${hour - 12} PM`;
}

function formatClock(date: Date, format: TimeFormat): string {
  const h = date.getHours();
  const m = String(date.getMinutes()).padStart(2, "0");
  if (format === "24h") return `${String(h).padStart(2, "0")}:${m}`;
  const period = h < 12 ? "AM" : "PM";
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return date.getMinutes() === 0 ? `${hour12} ${period}` : `${hour12}:${m} ${period}`;
}

/** Google-Calendar-style calendar: sticky day header + all-day row over a
 * scrollable 24-hour time grid. Renders a 7-day week or a single day depending
 * on `view`. Follows the app's fixed dark theme. */
export function WeekView({
  calendars,
  preferences = DEFAULT_PREFERENCES,
  view,
  date,
  onDateChange,
  onViewChange,
  events = [],
  hiddenCalendarIds,
  onVisibleRangeChange,
  onSlotClick,
  onEventClick,
}: WeekViewProps) {
  const today = useMemo(() => new Date(), []);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState(() => new Date());

  const { week_starts_on, work_day_start, work_day_end, time_format } = preferences;
  const isDay = view === "day";

  const days = useMemo(() => {
    if (isDay) {
      return [new Date(date.getFullYear(), date.getMonth(), date.getDate())];
    }
    const weekStart = startOfWeek(date, week_starts_on);
    return Array.from({ length: 7 }, (_, i) => new Date(weekStart.getTime() + i * DAY_MS));
  }, [isDay, date, week_starts_on]);

  // Column template shared by every row so the header, all-day row, and body
  // stay aligned whether there are 7 columns or 1.
  const columnStyle = { gridTemplateColumns: `4rem repeat(${days.length}, minmax(0, 1fr))` };

  const visibleEvents = useMemo(
    () =>
      events.filter(
        (event) => !hiddenCalendarIds || !hiddenCalendarIds.has(event.calendarId),
      ),
    [events, hiddenCalendarIds],
  );

  const rangeStart = days[0];
  const rangeEnd = new Date(days[days.length - 1].getTime() + DAY_MS);

  // Tell the parent which span is on screen so it can load matching events.
  useEffect(() => {
    onVisibleRangeChange?.(rangeStart, rangeEnd);
    // Depend on the millisecond bounds, not the callback identity, to avoid a
    // refetch loop if the parent passes a fresh function each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rangeStart.getTime(), rangeEnd.getTime()]);

  // Scroll so the start of the working day sits near the top on mount.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = Math.max(work_day_start - 1, 0) * HOUR_PX;
    }
  }, [work_day_start]);

  // Advance the current-time indicator each minute.
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  const hasCalendars = calendars.length > 0;
  const nowOffset = (now.getHours() * 60 + now.getMinutes()) / 60 * HOUR_PX;

  const step = isDay ? DAY_MS : 7 * DAY_MS;
  const shift = (delta: number) => onDateChange(new Date(date.getTime() + delta * step));

  return (
    <div className="week-view">
      <header className="week-header">
        <h1 className="week-title">
          {isDay ? (
            <>
              {WEEKDAY_LONG[date.getDay()]}, {MONTHS[date.getMonth()]}{" "}
              <span>
                {date.getDate()}, {date.getFullYear()}
              </span>
            </>
          ) : (
            <>
              {MONTHS[days[3].getMonth()]} <span>{days[3].getFullYear()}</span>
            </>
          )}
        </h1>
        <div className="week-nav">
          <div className="week-view-toggle">
            <button
              type="button"
              className={`week-view-toggle-button${!isDay ? " week-view-toggle-button--active" : ""}`}
              onClick={() => onViewChange("week")}
            >
              Week
            </button>
            <button
              type="button"
              className={`week-view-toggle-button${isDay ? " week-view-toggle-button--active" : ""}`}
              onClick={() => onViewChange("day")}
            >
              Day
            </button>
          </div>
          <button
            type="button"
            className="week-nav-button"
            aria-label={isDay ? "Previous day" : "Previous week"}
            onClick={() => shift(-1)}
          >
            <ChevronLeft size={18} />
          </button>
          <button
            type="button"
            className="week-today-button"
            onClick={() => onDateChange(new Date())}
          >
            Today
          </button>
          <button
            type="button"
            className="week-nav-button"
            aria-label={isDay ? "Next day" : "Next week"}
            onClick={() => shift(1)}
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </header>

      <div className="week-columns week-daybar" style={columnStyle}>
        <div className="week-gutter-cell" />
        {days.map((day) => {
          const isToday = isSameDay(day, today);
          return (
            <div className="week-dayhead" key={day.toISOString()}>
              <span className="week-dayhead-name">{WEEKDAYS[day.getDay()]}</span>
              <span className={`week-dayhead-date${isToday ? " week-dayhead-date--today" : ""}`}>
                {day.getDate()}
              </span>
            </div>
          );
        })}
      </div>

      <div className="week-columns week-allday" style={columnStyle}>
        <div className="week-gutter-cell week-allday-label">all-day</div>
        {days.map((day) => {
          const dayAllDay = visibleEvents.filter(
            (event) => event.allDay && isSameDay(event.start, day),
          );
          return (
            <div className="week-allday-cell" key={day.toISOString()}>
              {dayAllDay.map((event) => (
                <div
                  className="week-event week-event--allday"
                  key={event.id}
                  style={{
                    background: hexToRgba(event.color, 0.32),
                    borderLeft: `3px solid ${event.color}`,
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onEventClick?.(event, e.currentTarget.getBoundingClientRect());
                  }}
                >
                  {event.title}
                </div>
              ))}
            </div>
          );
        })}
      </div>

      <div className="week-scroll" ref={scrollRef}>
        <div
          className="week-columns week-body"
          style={{ ...columnStyle, height: 24 * HOUR_PX }}
        >
          <div className="week-gutter">
            {Array.from({ length: 24 }, (_, hour) => (
              <div className="week-gutter-hour" key={hour} style={{ height: HOUR_PX }}>
                {hour > 0 && (
                  <span className="week-gutter-time">{formatHour(hour, time_format)}</span>
                )}
              </div>
            ))}
          </div>

          {days.map((day) => {
            const isToday = isSameDay(day, today);
            const dayEvents = visibleEvents.filter(
              (event) => !event.allDay && isSameDay(event.start, day),
            );
            return (
              <div
                className="week-col"
                key={day.toISOString()}
                onClick={(e) => {
                  if (!onSlotClick) return;
                  const rect = e.currentTarget.getBoundingClientRect();
                  const hour = Math.max(
                    0,
                    Math.min(23, Math.floor((e.clientY - rect.top) / HOUR_PX)),
                  );
                  onSlotClick(new Date(day.getFullYear(), day.getMonth(), day.getDate(), hour));
                }}
              >
                {work_day_start > 0 && (
                  <div
                    className="week-offhours"
                    style={{ top: 0, height: work_day_start * HOUR_PX }}
                  />
                )}
                {work_day_end < 24 && (
                  <div
                    className="week-offhours"
                    style={{ top: work_day_end * HOUR_PX, height: (24 - work_day_end) * HOUR_PX }}
                  />
                )}

                {Array.from({ length: 24 }, (_, hour) => (
                  <div className="week-hour" key={hour} style={{ height: HOUR_PX }} />
                ))}

                {isToday && (
                  <div className="week-now" style={{ top: nowOffset }}>
                    <span className="week-now-dot" />
                  </div>
                )}

                {dayEvents.map((event) => {
                  const top =
                    (event.start.getHours() * 60 + event.start.getMinutes()) / 60 * HOUR_PX;
                  const height = Math.max(
                    (event.end.getTime() - event.start.getTime()) / 3_600_000 * HOUR_PX,
                    18,
                  );
                  return (
                    <div
                      className="week-event"
                      key={event.id}
                      style={{
                        top,
                        height,
                        background: hexToRgba(event.color, 0.24),
                        borderLeftColor: event.color,
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        onEventClick?.(event, e.currentTarget.getBoundingClientRect());
                      }}
                    >
                      <span className="week-event-title">{event.title}</span>
                      {height > 32 && (
                        <span className="week-event-time">
                          {formatClock(event.start, time_format)}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>

      {!hasCalendars && (
        <p className="week-empty-hint">No calendars yet — create one to start scheduling.</p>
      )}
    </div>
  );
}
