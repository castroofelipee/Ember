"use client";

import { useState, type SubmitEvent } from "react";
import { Check, X } from "lucide-react";

import { EVENT_COLORS } from "@/lib/types";

import type { WeekEvent } from "./week-view";

/** How far an edit to one occurrence of a series reaches, matching the
 * backend's EventUpdateScope. Ignored for one-off events. */
export type EventUpdateScope = "this_only" | "this_and_future" | "all";

export type EventEdit = {
  title: string;
  start: Date;
  end: Date;
  /** null clears the override, so the event falls back to its calendar color. */
  color: string | null;
  scope: EventUpdateScope;
};

type EventEditDialogProps = {
  event: WeekEvent;
  saving: boolean;
  onClose: () => void;
  onSave: (edit: EventEdit) => void;
};

function dateValue(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function timeValue(date: Date): string {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/** Retime and repaint an existing event. Recurring events also ask how far the
 * change reaches; the series itself is edited from the create dialog. */
export function EventEditDialog({ event, saving, onClose, onSave }: EventEditDialogProps) {
  const [title, setTitle] = useState(event.title);
  const [startDate, setStartDate] = useState(dateValue(event.start));
  const [startTime, setStartTime] = useState(timeValue(event.start));
  const [endDate, setEndDate] = useState(dateValue(event.end));
  const [endTime, setEndTime] = useState(timeValue(event.end));
  const [color, setColor] = useState<string | null>(event.colorOverride ?? null);
  const [scope, setScope] = useState<EventUpdateScope>("this_only");
  const [error, setError] = useState<string | null>(null);

  const allDay = Boolean(event.allDay);

  function handleSubmit(formEvent: SubmitEvent<HTMLFormElement>) {
    formEvent.preventDefault();

    if (!title.trim()) {
      setError("Add a title for your event.");
      return;
    }

    // All-day events span midnight to midnight after the end date, the same
    // shape the create dialog sends.
    const start = allDay
      ? new Date(`${startDate}T00:00`)
      : new Date(`${startDate}T${startTime}`);
    const end = allDay
      ? new Date(new Date(`${endDate}T00:00`).getTime() + 24 * 60 * 60 * 1000)
      : new Date(`${endDate}T${endTime}`);

    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
      setError("Pick a valid date and time.");
      return;
    }
    if (end.getTime() <= start.getTime()) {
      setError("The end time needs to be after the start time.");
      return;
    }

    setError(null);
    onSave({ title: title.trim(), start, end, color, scope });
  }

  return (
    <div className="event-dialog-backdrop" onClick={onClose}>
      <div
        className="event-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`Edit ${event.title}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="event-dialog-top">
          <span className="event-dialog-heading">Edit event</span>
          <button type="button" className="event-dialog-close" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <form className="event-dialog-form" onSubmit={handleSubmit}>
          <input
            className="event-dialog-title-input"
            aria-label="Event title"
            placeholder="Add title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />

          <div className="event-dialog-times">
            <input
              type="date"
              className="event-dialog-input"
              aria-label="Start date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
            {!allDay && (
              <input
                type="time"
                className="event-dialog-input"
                aria-label="Start time"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
              />
            )}
            <span className="event-dialog-dash">–</span>
            {!allDay && (
              <input
                type="time"
                className="event-dialog-input"
                aria-label="End time"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
              />
            )}
            <input
              type="date"
              className="event-dialog-input"
              aria-label="End date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
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

          {event.recurrence && (
            <div className="event-dialog-field">
              <span className="event-dialog-label">Apply to</span>
              <div className="event-dialog-ends">
                <label className="event-dialog-ends-option">
                  <input
                    type="radio"
                    name="edit-scope"
                    checked={scope === "this_only"}
                    onChange={() => setScope("this_only")}
                  />
                  This event
                </label>
                <label className="event-dialog-ends-option">
                  <input
                    type="radio"
                    name="edit-scope"
                    checked={scope === "this_and_future"}
                    onChange={() => setScope("this_and_future")}
                  />
                  This and following events
                </label>
                <label className="event-dialog-ends-option">
                  <input
                    type="radio"
                    name="edit-scope"
                    checked={scope === "all"}
                    onChange={() => setScope("all")}
                  />
                  All events
                </label>
              </div>
            </div>
          )}

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
