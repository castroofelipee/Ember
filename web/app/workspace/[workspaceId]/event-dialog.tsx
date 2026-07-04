"use client";

import { useMemo, useState, type SubmitEvent } from "react";
import { Check, MapPin, Users, X } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EVENT_COLORS, type Calendar } from "@/lib/types";

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
