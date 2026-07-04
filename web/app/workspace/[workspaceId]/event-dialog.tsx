"use client";

import { useMemo, useState, type SubmitEvent } from "react";
import { Check, MapPin, Repeat, Users, X } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EVENT_COLORS, type Calendar, type RecurrenceFreq, type RecurrenceRule } from "@/lib/types";

type EventDialogProps = {
  calendars: Calendar[];
  accessToken: string;
  defaultCalendarId?: string;
  initialStart?: Date;
  onClose: () => void;
  onCreated: () => void;
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Rounds up to the next whole hour so a fresh dialog defaults to a clean slot. */
function nextHour(): Date {
  const date = new Date();
  date.setMinutes(0, 0, 0);
  date.setHours(date.getHours() + 1);
  return date;
}

function dateValue(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function timeValue(date: Date): string {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

// 0=Monday..6=Sunday, matching RecurrenceRule.by_weekday — JS's Date.getDay()
// is 0=Sunday..6=Saturday, one slot off.
const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const DAY_LETTERS = ["M", "T", "W", "T", "F", "S", "S"];

function jsDayToRecurrenceDay(jsDay: number): number {
  return (jsDay + 6) % 7;
}

function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  const suffix = ["th", "st", "nd", "rd"][n % 10] ?? "th";
  return `${n}${suffix}`;
}

const MONTH_NAMES = [
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

type RepeatPreset = "none" | "daily" | "weekly" | "weekdays" | "monthly" | "yearly" | "custom";

type EndsMode = "never" | "on" | "after";

/** Builds the RecurrenceRule to send to the API, or null for "Does not repeat". */
function buildRecurrence(
  preset: RepeatPreset,
  custom: { freq: RecurrenceFreq; interval: number; byWeekday: number[] },
  ends: EndsMode,
  endDate: string,
  endCount: number,
): RecurrenceRule | null {
  if (preset === "none") return null;

  let freq: RecurrenceFreq;
  let interval = 1;
  let byWeekday: number[] | null = null;

  switch (preset) {
    case "daily":
      freq = "DAILY";
      break;
    case "weekly":
      freq = "WEEKLY";
      break;
    case "monthly":
      freq = "MONTHLY";
      break;
    case "yearly":
      freq = "YEARLY";
      break;
    case "weekdays":
      freq = "WEEKLY";
      byWeekday = [0, 1, 2, 3, 4];
      break;
    case "custom":
      freq = custom.freq;
      interval = custom.interval;
      if (freq === "WEEKLY" && custom.byWeekday.length > 0) byWeekday = custom.byWeekday;
      break;
  }

  return {
    freq,
    interval,
    by_weekday: byWeekday,
    count: ends === "after" ? endCount : null,
    until: ends === "on" && endDate ? new Date(`${endDate}T23:59:59`).toISOString() : null,
  };
}

export function EventDialog({
  calendars,
  accessToken,
  defaultCalendarId,
  initialStart,
  onClose,
  onCreated,
}: EventDialogProps) {
  const start = useMemo(() => initialStart ?? nextHour(), [initialStart]);
  const end = useMemo(() => new Date(start.getTime() + 60 * 60 * 1000), [start]);

  const [title, setTitle] = useState("");
  const [calendarId, setCalendarId] = useState(
    defaultCalendarId ?? calendars[0]?.id ?? "",
  );
  const [allDay, setAllDay] = useState(false);
  const [startDate, setStartDate] = useState(dateValue(start));
  const [startTime, setStartTime] = useState(timeValue(start));
  const [endDate, setEndDate] = useState(dateValue(end));
  const [endTime, setEndTime] = useState(timeValue(end));
  const [color, setColor] = useState<string | null>(null);
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [guests, setGuests] = useState<string[]>([]);
  const [guestInput, setGuestInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [repeat, setRepeat] = useState<RepeatPreset>("none");
  const [customFreq, setCustomFreq] = useState<RecurrenceFreq>("WEEKLY");
  const [customInterval, setCustomInterval] = useState(1);
  const [customByWeekday, setCustomByWeekday] = useState<number[]>([jsDayToRecurrenceDay(start.getDay())]);
  const [recurEnds, setRecurEnds] = useState<EndsMode>("never");
  const [recurUntil, setRecurUntil] = useState(dateValue(start));
  const [recurCount, setRecurCount] = useState(10);

  const startDateObj = useMemo(() => new Date(`${startDate}T00:00`), [startDate]);
  const repeatLabels: Record<Exclude<RepeatPreset, "custom">, string> = {
    none: "Does not repeat",
    daily: "Daily",
    weekly: `Weekly on ${DAY_NAMES[jsDayToRecurrenceDay(startDateObj.getDay())]}`,
    weekdays: "Every weekday (Monday to Friday)",
    monthly: `Monthly on the ${ordinal(startDateObj.getDate())}`,
    yearly: `Annually on ${MONTH_NAMES[startDateObj.getMonth()]} ${startDateObj.getDate()}`,
  };

  function addGuest() {
    const email = guestInput.trim();
    if (!email) return;
    if (!EMAIL_RE.test(email)) {
      setError("That doesn't look like a valid email.");
      return;
    }
    if (!guests.some((g) => g.toLowerCase() === email.toLowerCase())) {
      setGuests((prev) => [...prev, email]);
    }
    setGuestInput("");
    setError(null);
  }

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!title.trim()) {
      setError("Add a title for your event.");
      return;
    }
    if (!calendarId) {
      setError("Pick a calendar to add this event to.");
      return;
    }

    // All-day events run from midnight of the start date to midnight after the
    // end date, so the backend's end > start rule holds for a single day too.
    const startMs = allDay
      ? new Date(`${startDate}T00:00`).getTime()
      : new Date(`${startDate}T${startTime}`).getTime();
    const endMs = allDay
      ? new Date(`${endDate}T00:00`).getTime() + 24 * 60 * 60 * 1000
      : new Date(`${endDate}T${endTime}`).getTime();

    if (endMs <= startMs) {
      setError("The end time needs to be after the start time.");
      return;
    }

    const startIso = new Date(startMs).toISOString();
    const endForAllDay = new Date(endMs).toISOString();

    setSaving(true);
    setError(null);
    try {
      const response = await fetch(`/api/calendars/${calendarId}/events`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim() || null,
          location: location.trim() || null,
          start_at: startIso,
          end_at: endForAllDay,
          all_day: allDay,
          color,
          attendees: guests,
          recurrence: buildRecurrence(
            repeat,
            { freq: customFreq, interval: customInterval, byWeekday: customByWeekday },
            recurEnds,
            recurUntil,
            recurCount,
          ),
        }),
      });

      if (response.ok) {
        onCreated();
        return;
      }
      setError("Could not save the event. Please try again.");
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="event-dialog-backdrop" onClick={onClose}>
      <div
        className="event-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Create event"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="event-dialog-top">
          <span className="event-dialog-heading">New event</span>
          <button type="button" className="event-dialog-close" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <form className="event-dialog-form" onSubmit={handleSubmit}>
          <input
            className="event-dialog-title-input"
            placeholder="Add title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />

          <label className="event-dialog-check">
            <input
              type="checkbox"
              checked={allDay}
              onChange={(e) => setAllDay(e.target.checked)}
            />
            All day
          </label>

          <div className="event-dialog-times">
            <input
              type="date"
              className="event-dialog-input"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
            {!allDay && (
              <input
                type="time"
                className="event-dialog-input"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
              />
            )}
            <span className="event-dialog-dash">–</span>
            {!allDay && (
              <input
                type="time"
                className="event-dialog-input"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
              />
            )}
            <input
              type="date"
              className="event-dialog-input"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </div>

          <div className="event-dialog-field">
            <span className="event-dialog-label">
              <Repeat size={14} /> Repeat
            </span>
            <Select value={repeat} onValueChange={(value) => setRepeat(value as RepeatPreset)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{repeatLabels.none}</SelectItem>
                <SelectItem value="daily">{repeatLabels.daily}</SelectItem>
                <SelectItem value="weekly">{repeatLabels.weekly}</SelectItem>
                <SelectItem value="weekdays">{repeatLabels.weekdays}</SelectItem>
                <SelectItem value="monthly">{repeatLabels.monthly}</SelectItem>
                <SelectItem value="yearly">{repeatLabels.yearly}</SelectItem>
                <SelectItem value="custom">Custom…</SelectItem>
              </SelectContent>
            </Select>

            {repeat === "custom" && (
              <div className="event-dialog-recur-panel">
                <div className="event-dialog-recur-row">
                  <span>Repeat every</span>
                  <input
                    type="number"
                    min={1}
                    max={999}
                    className="event-dialog-input event-dialog-recur-number"
                    value={customInterval}
                    onChange={(e) => setCustomInterval(Math.max(1, Number(e.target.value) || 1))}
                  />
                  <Select
                    value={customFreq}
                    onValueChange={(value) => setCustomFreq(value as RecurrenceFreq)}
                  >
                    <SelectTrigger className="w-28">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="DAILY">day{customInterval > 1 ? "s" : ""}</SelectItem>
                      <SelectItem value="WEEKLY">week{customInterval > 1 ? "s" : ""}</SelectItem>
                      <SelectItem value="MONTHLY">month{customInterval > 1 ? "s" : ""}</SelectItem>
                      <SelectItem value="YEARLY">year{customInterval > 1 ? "s" : ""}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {customFreq === "WEEKLY" && (
                  <div className="event-dialog-weekday-toggle">
                    {DAY_LETTERS.map((letter, day) => {
                      const selected = customByWeekday.includes(day);
                      return (
                        <button
                          type="button"
                          key={day}
                          className={`event-dialog-weekday-button${selected ? " event-dialog-weekday-button--selected" : ""}`}
                          aria-label={DAY_NAMES[day]}
                          aria-pressed={selected}
                          onClick={() =>
                            setCustomByWeekday((prev) =>
                              prev.includes(day)
                                ? prev.filter((d) => d !== day)
                                : [...prev, day].sort((a, b) => a - b),
                            )
                          }
                        >
                          {letter}
                        </button>
                      );
                    })}
                  </div>
                )}

                <div className="event-dialog-ends">
                  <span className="event-dialog-label">Ends</span>
                  <label className="event-dialog-ends-option">
                    <input
                      type="radio"
                      name="recur-ends"
                      checked={recurEnds === "never"}
                      onChange={() => setRecurEnds("never")}
                    />
                    Never
                  </label>
                  <label className="event-dialog-ends-option">
                    <input
                      type="radio"
                      name="recur-ends"
                      checked={recurEnds === "on"}
                      onChange={() => setRecurEnds("on")}
                    />
                    On
                    <input
                      type="date"
                      className="event-dialog-input"
                      value={recurUntil}
                      disabled={recurEnds !== "on"}
                      onChange={(e) => {
                        setRecurUntil(e.target.value);
                        setRecurEnds("on");
                      }}
                    />
                  </label>
                  <label className="event-dialog-ends-option">
                    <input
                      type="radio"
                      name="recur-ends"
                      checked={recurEnds === "after"}
                      onChange={() => setRecurEnds("after")}
                    />
                    After
                    <input
                      type="number"
                      min={1}
                      max={730}
                      className="event-dialog-input event-dialog-recur-number"
                      value={recurCount}
                      disabled={recurEnds !== "after"}
                      onChange={(e) => {
                        setRecurCount(Math.max(1, Number(e.target.value) || 1));
                        setRecurEnds("after");
                      }}
                    />
                    occurrences
                  </label>
                </div>
              </div>
            )}
          </div>

          <div className="event-dialog-row">
            <div className="event-dialog-field">
              <span className="event-dialog-label">Calendar</span>
              <Select value={calendarId} onValueChange={setCalendarId}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select a calendar" />
                </SelectTrigger>
                <SelectContent>
                  {calendars.map((calendar) => (
                    <SelectItem key={calendar.id} value={calendar.id}>
                      {calendar.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="event-dialog-field">
            <span className="event-dialog-label">Color</span>
            <div className="event-dialog-swatches">
              {EVENT_COLORS.map((option) => {
                const selected = color === option.value;
                const swatch = option.value ?? "#6b7280";
                return (
                  <button
                    type="button"
                    key={option.name}
                    className={`event-swatch${selected ? " event-swatch--selected" : ""}`}
                    style={{ background: swatch }}
                    title={option.name}
                    aria-label={option.name}
                    aria-pressed={selected}
                    onClick={() => setColor(option.value)}
                  >
                    {selected && <Check size={12} strokeWidth={3} />}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="event-dialog-field">
            <span className="event-dialog-label">
              <Users size={14} /> Guests
            </span>
            <div className="event-dialog-guest-entry">
              <input
                type="email"
                className="event-dialog-input"
                placeholder="Add people by email"
                value={guestInput}
                onChange={(e) => setGuestInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === ",") {
                    e.preventDefault();
                    addGuest();
                  }
                }}
              />
              <button type="button" className="event-dialog-add" onClick={addGuest}>
                Add
              </button>
            </div>
            {guests.length > 0 && (
              <div className="event-dialog-chips">
                {guests.map((guest) => (
                  <span className="event-guest-chip" key={guest}>
                    {guest}
                    <button
                      type="button"
                      aria-label={`Remove ${guest}`}
                      onClick={() => setGuests((prev) => prev.filter((g) => g !== guest))}
                    >
                      <X size={12} />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="event-dialog-field">
            <span className="event-dialog-label">
              <MapPin size={14} /> Location
            </span>
            <input
              className="event-dialog-input"
              placeholder="Add location"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            />
          </div>

          <div className="event-dialog-field">
            <span className="event-dialog-label">Description</span>
            <textarea
              className="event-dialog-input event-dialog-textarea"
              placeholder="Add description"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          {error && <p className="form-error form-error--summary">{error}</p>}

          <div className="event-dialog-actions">
            <button type="button" className="link-button" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="button-primary" disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
