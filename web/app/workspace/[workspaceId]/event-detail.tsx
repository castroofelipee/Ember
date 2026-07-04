"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { AlignLeft, CalendarDays, MapPin, Repeat, Trash2, Users, X } from "lucide-react";

import type { RecurrenceRule, TimeFormat } from "@/lib/types";

import type { WeekEvent } from "./week-view";

type EventDetailProps = {
  event: WeekEvent;
  anchor: DOMRect;
  timeFormat: TimeFormat;
  onClose: () => void;
  onDelete: () => void;
  deleting: boolean;
};

const WEEKDAY_LONG = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];
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

function clock(date: Date, format: TimeFormat): string {
  const h = date.getHours();
  const m = String(date.getMinutes()).padStart(2, "0");
  if (format === "24h") return `${String(h).padStart(2, "0")}:${m}`;
  const period = h < 12 ? "AM" : "PM";
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return date.getMinutes() === 0 ? `${hour12} ${period}` : `${hour12}:${m} ${period}`;
}

function longDate(date: Date): string {
  return `${WEEKDAY_LONG[date.getDay()]}, ${MONTHS[date.getMonth()]} ${date.getDate()}`;
}

// 0=Monday..6=Sunday, matching RecurrenceRule.by_weekday.
const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** Google-Calendar-style summary, e.g. "Every 2 weeks on Mon, Wed, 10 times". */
function describeRecurrence(rule: RecurrenceRule, start: Date): string {
  let base: string;
  if (
    rule.freq === "WEEKLY" &&
    rule.interval === 1 &&
    rule.by_weekday?.length === 5 &&
    [0, 1, 2, 3, 4].every((day) => rule.by_weekday!.includes(day))
  ) {
    base = "Every weekday (Monday to Friday)";
  } else {
    const unit = { DAILY: "day", WEEKLY: "week", MONTHLY: "month", YEARLY: "year" }[rule.freq];
    const every = rule.interval > 1 ? `Every ${rule.interval} ${unit}s` : `Every ${unit}`;
    if (rule.freq === "WEEKLY") {
      const days = rule.by_weekday?.length
        ? rule.by_weekday.map((day) => DAY_NAMES[day].slice(0, 3)).join(", ")
        : DAY_NAMES[(start.getDay() + 6) % 7].slice(0, 3);
      base = `${every} on ${days}`;
    } else {
      base = every;
    }
  }
  if (rule.count) return `${base}, ${rule.count} times`;
  if (rule.until) {
    const until = new Date(rule.until).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    return `${base}, until ${until}`;
  }
  return base;
}

/** Google-Calendar-style detail popover, anchored next to the clicked event. */
export function EventDetail({
  event,
  anchor,
  timeFormat,
  onClose,
  onDelete,
  deleting,
}: EventDetailProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  // Place beside the anchor, flipping to its other side and clamping to the
  // viewport so the card never spills off screen.
  useLayoutEffect(() => {
    const card = cardRef.current;
    if (!card) return;
    const { width, height } = card.getBoundingClientRect();
    const margin = 8;

    let left = anchor.right + margin;
    if (left + width > window.innerWidth - margin) left = anchor.left - width - margin;
    left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));

    let top = anchor.top;
    top = Math.max(margin, Math.min(top, window.innerHeight - height - margin));

    setPos({ top, left });
  }, [anchor]);

  const timeLine = event.allDay
    ? `${longDate(event.start)} · All day`
    : `${longDate(event.start)} · ${clock(event.start, timeFormat)} – ${clock(event.end, timeFormat)}`;

  return (
    <div className="event-detail-backdrop" onClick={onClose}>
      <div
        ref={cardRef}
        className="event-detail"
        role="dialog"
        aria-modal="true"
        aria-label={event.title}
        style={pos ? { top: pos.top, left: pos.left, visibility: "visible" } : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="event-detail-actions">
          <button
            type="button"
            className="event-detail-icon"
            aria-label="Delete event"
            onClick={onDelete}
            disabled={deleting}
          >
            <Trash2 size={16} />
          </button>
          <button
            type="button"
            className="event-detail-icon"
            aria-label="Close"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>

        <div className="event-detail-body">
          <div className="event-detail-title-row">
            <span className="event-detail-swatch" style={{ background: event.color }} />
            <div>
              <h2 className="event-detail-title">{event.title}</h2>
              <p className="event-detail-time">{timeLine}</p>
            </div>
          </div>

          {event.recurrence && (
            <div className="event-detail-line">
              <Repeat size={16} />
              <span>{describeRecurrence(event.recurrence, event.start)}</span>
            </div>
          )}

          {event.location && (
            <div className="event-detail-line">
              <MapPin size={16} />
              <span>{event.location}</span>
            </div>
          )}

          {event.attendees && event.attendees.length > 0 && (
            <div className="event-detail-line event-detail-line--top">
              <Users size={16} />
              <div className="event-detail-guests">
                <span className="event-detail-guests-count">
                  {event.attendees.length} guest{event.attendees.length > 1 ? "s" : ""}
                </span>
                {event.attendees.map((guest) => (
                  <span className="event-detail-guest" key={guest}>
                    {guest}
                  </span>
                ))}
              </div>
            </div>
          )}

          {event.description && (
            <div className="event-detail-line event-detail-line--top">
              <AlignLeft size={16} />
              <span className="event-detail-description">{event.description}</span>
            </div>
          )}

          {event.calendarName && (
            <div className="event-detail-line">
              <CalendarDays size={16} />
              <span>{event.calendarName}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
