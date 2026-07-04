"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { useRequireAuth } from "@/lib/auth-client";
import {
  DEFAULT_CALENDAR_COLOR,
  type Calendar,
  type EventItem,
  type Preferences,
  DEFAULT_PREFERENCES,
} from "@/lib/types";

import { EventDetail } from "./event-detail";
import { EventDialog } from "./event-dialog";
import { Sidebar } from "./sidebar";
import { CalendarView, WeekView, type WeekEvent } from "./week-view";

type Status = "loading" | "ready" | "not-found";

type DialogState = { open: false } | { open: true; initialStart?: Date };
type SelectedEvent = { event: WeekEvent; anchor: DOMRect };

export function WorkspaceView() {
  const router = useRouter();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { status: authStatus, accessToken } = useRequireAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [calendars, setCalendars] = useState<Calendar[]>([]);
  const [preferences, setPreferences] = useState<Preferences>(DEFAULT_PREFERENCES);
  // Focused day shared by the mini-calendar and the main view; `view` toggles
  // between the full week and a single-day view of that day.
  const [focusDate, setFocusDate] = useState<Date>(() => new Date());
  const [view, setView] = useState<CalendarView>("week");
  const [events, setEvents] = useState<WeekEvent[]>([]);
  const [dialog, setDialog] = useState<DialogState>({ open: false });
  const [selected, setSelected] = useState<SelectedEvent | null>(null);
  const [deleting, setDeleting] = useState(false);
  // Remember the span currently on screen so we can refetch after creating.
  const rangeRef = useRef<{ start: Date; end: Date } | null>(null);

  // Per-calendar color/name, so events with no color override fall back to their
  // calendar's color (then the global default), and the detail popover can name
  // the owning calendar.
  const calendarColors = new Map(calendars.map((c) => [c.id, c.color]));
  const calendarNames = new Map(calendars.map((c) => [c.id, c.name]));

  const toWeekEvent = useCallback(
    (item: EventItem): WeekEvent => ({
      id: item.id,
      calendarId: item.calendar_id,
      calendarName: calendarNames.get(item.calendar_id),
      title: item.title,
      description: item.description,
      location: item.location,
      attendees: item.attendees,
      start: new Date(item.start_at),
      end: new Date(item.end_at),
      allDay: item.all_day,
      color: item.color ?? calendarColors.get(item.calendar_id) ?? DEFAULT_CALENDAR_COLOR,
    }),
    // calendarColors/Names are derived from calendars each render; key on calendars.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [calendars],
  );

  const loadEvents = useCallback(
    async (start: Date, end: Date) => {
      if (authStatus !== "ready") return;
      rangeRef.current = { start, end };
      const params = new URLSearchParams({
        start: start.toISOString(),
        end: end.toISOString(),
      });
      const response = await fetch(
        `/api/workspaces/${workspaceId}/events?${params.toString()}`,
        { headers: { Authorization: `Bearer ${accessToken}` } },
      );
      if (response.ok) {
        const items: EventItem[] = await response.json();
        setEvents(items.map(toWeekEvent));
      }
    },
    [authStatus, accessToken, workspaceId, toWeekEvent],
  );

  const handleVisibleRangeChange = useCallback(
    (start: Date, end: Date) => {
      void loadEvents(start, end);
    },
    [loadEvents],
  );

  const refetchEvents = useCallback(() => {
    if (rangeRef.current) void loadEvents(rangeRef.current.start, rangeRef.current.end);
  }, [loadEvents]);

  const handleDelete = useCallback(async () => {
    if (!selected) return;
    setDeleting(true);
    try {
      const response = await fetch(`/api/events/${selected.event.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (response.ok) {
        setSelected(null);
        refetchEvents();
      }
    } finally {
      setDeleting(false);
    }
  }, [selected, accessToken, refetchEvents]);

  useEffect(() => {
    if (authStatus !== "ready") return;

    let cancelled = false;

    fetch(`/api/workspaces/${workspaceId}/calendars`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    }).then(async (response) => {
      if (cancelled) return;
      if (response.status === 404) {
        setStatus("not-found");
        return;
      }
      if (response.ok) {
        setCalendars(await response.json());
        setStatus("ready");
      }
    });

    // Preferences drive how the week renders (start day, working hours, time
    // format); a failure just falls back to the defaults already in state.
    fetch("/api/users/me/preferences", {
      headers: { Authorization: `Bearer ${accessToken}` },
    }).then(async (response) => {
      if (cancelled) return;
      if (response.ok) setPreferences(await response.json());
    });

    return () => {
      cancelled = true;
    };
  }, [authStatus, accessToken, workspaceId]);

  if (authStatus !== "ready" || status === "loading") {
    return (
      <div className="hub-page">
        <div className="hub-header">
          <h1 className="auth-title">Ember</h1>
        </div>
        <p className="auth-subtitle">Loading…</p>
      </div>
    );
  }

  if (status === "not-found") {
    return (
      <div className="hub-page">
        <div className="hub-header">
          <h1 className="auth-title">Ember</h1>
          <p className="auth-subtitle">Workspace not found</p>
        </div>
        <button className="link-button" onClick={() => router.push("/calendars")}>
          Back to workspaces
        </button>
      </div>
    );
  }

  return (
    <div className="workspace-layout">
      <Sidebar
        calendars={calendars}
        selectedDate={focusDate}
        onSelectDay={(date) => {
          setFocusDate(date);
          setView("day");
        }}
        onCreateEvent={() => setDialog({ open: true })}
      />
      <main className="calendar-main">
        <WeekView
          calendars={calendars}
          preferences={preferences}
          view={view}
          date={focusDate}
          events={events}
          onDateChange={setFocusDate}
          onViewChange={setView}
          onVisibleRangeChange={handleVisibleRangeChange}
          onSlotClick={(start) => setDialog({ open: true, initialStart: start })}
          onEventClick={(event, anchor) => setSelected({ event, anchor })}
        />
      </main>

      {selected && (
        <EventDetail
          event={selected.event}
          anchor={selected.anchor}
          timeFormat={preferences.time_format}
          deleting={deleting}
          onClose={() => setSelected(null)}
          onDelete={handleDelete}
        />
      )}

      {dialog.open && (
        <EventDialog
          calendars={calendars}
          accessToken={accessToken}
          initialStart={dialog.initialStart}
          onClose={() => setDialog({ open: false })}
          onCreated={() => {
            setDialog({ open: false });
            refetchEvents();
          }}
        />
      )}
    </div>
  );
}
