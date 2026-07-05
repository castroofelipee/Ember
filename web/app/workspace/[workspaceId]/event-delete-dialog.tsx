"use client";

import { AlertTriangle, CalendarClock, CalendarDays, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { WeekEvent } from "./week-view";

type DeleteDialogProps = {
  event: WeekEvent;
  deleting: boolean;
  onClose: () => void;
  onDeleteAll: () => void;
  onDeleteThis: () => void;
  onDeleteThisAndFuture: () => void;
};

function recurrenceLabel(event: WeekEvent): string {
  if (!event.recurrence) return "Delete this event.";
  return "Delete one occurrence, this and following events, or the whole series.";
}

export function EventDeleteDialog({
  event,
  deleting,
  onClose,
  onDeleteAll,
  onDeleteThis,
  onDeleteThisAndFuture,
}: DeleteDialogProps) {
  return (
    <div className="event-delete-backdrop" onClick={onClose}>
      <div
        className="event-delete-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="event-delete-title"
        aria-describedby="event-delete-description"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="event-delete-top">
          <div className="event-delete-titlewrap">
            <span className="event-delete-icon">
              <AlertTriangle size={16} />
            </span>
            <div>
              <h2 className="event-delete-title" id="event-delete-title">
                Delete event
              </h2>
              <p className="event-delete-subtitle">{event.title}</p>
            </div>
          </div>
          <button type="button" className="event-delete-close" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="event-delete-body" id="event-delete-description">
          <div className="event-delete-note">
            {recurrenceLabel(event)}
          </div>

          <div className="event-delete-actions">
            {event.recurrence ? (
              <>
                <Button type="button" variant="outline" onClick={onClose} disabled={deleting}>
                  Cancel
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  className="h-auto min-h-9 justify-start whitespace-normal px-3 py-2 text-left"
                  onClick={onDeleteThis}
                  disabled={deleting}
                >
                  <CalendarDays />
                  Just this event
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  className="h-auto min-h-9 justify-start whitespace-normal px-3 py-2 text-left"
                  onClick={onDeleteThisAndFuture}
                  disabled={deleting}
                >
                  <CalendarClock />
                  This and following
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  className="h-auto min-h-9 justify-start whitespace-normal px-3 py-2 text-left"
                  onClick={onDeleteAll}
                  disabled={deleting}
                >
                  <Trash2 />
                  All events
                </Button>
              </>
            ) : (
              <>
                <Button type="button" variant="outline" onClick={onClose} disabled={deleting}>
                  Cancel
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  className="h-auto min-h-9 justify-start whitespace-normal px-3 py-2 text-left"
                  onClick={onDeleteAll}
                  disabled={deleting}
                >
                  <Trash2 />
                  Delete event
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
