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
import { EventDeleteDialog } from "./event-delete-dialog";
import { EventDialog } from "./event-dialog";
import { AppHeader } from "./app-header";
import { Sidebar } from "./sidebar";
import { CalendarView, WeekView, type WeekEvent } from "./week-view";

type Status = "loading" | "ready" | "not-found";

type DialogState = { open: false } | { open: true; initialStart?: Date };
type SelectedEvent = { event: WeekEvent; anchor: DOMRect };
type DeleteDialogState = { open: false } | { open: true; event: WeekEvent };

function localDateInTimeZone(value: string, timeZone: string): Date {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).formatToParts(new Date(value));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return new Date(Number(values.year), Number(values.month) - 1, Number(values.day));
}

export function WorkspaceView() {
  const router = useRouter();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { status: authStatus, accessToken } = useRequireAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [calendars, setCalendars] = useState<Calendar[]>([]);
  const [hiddenCalendarIds, setHiddenCalendarIds] = useState<Set<string>>(new Set());
  const [preferences, setPreferences] = useState<Preferences>(DEFAULT_PREFERENCES);
  // Focused day shared by the mini-calendar and the main view; `view` toggles
  // between the full week and a single-day view of that day.
  const [focusDate, setFocusDate] = useState<Date>(() => new Date());
  const [view, setView] = useState<CalendarView>("week");
  const [events, setEvents] = useState<WeekEvent[]>([]);
  const [dialog, setDialog] = useState<DialogState>({ open: false });
  const [selected, setSelected] = useState<SelectedEvent | null>(null);
  const [deleteDialog, setDeleteDialog] = useState<DeleteDialogState>({ open: false });
  const [deleting, setDeleting] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  // Remember the span currently on screen so we can refetch after creating.
  const rangeRef = useRef<{ start: Date; end: Date } | null>(null);

  // Per-calendar color/name, so events with no color override fall back to their
  // calendar's color (then the global default), and the detail popover can name
  // the owning calendar.
  const calendarColors = new Map(calendars.map((c) => [c.id, c.color]));
  const calendarNames = new Map(calendars.map((c) => [c.id, c.name]));

  const toWeekEvent = useCallback(
    (item: EventItem): WeekEvent => {
      const start = item.all_day
        ? localDateInTimeZone(item.start_at, preferences.timezone)
        : new Date(item.start_at);
      const end = item.all_day
        ? localDateInTimeZone(item.end_at, preferences.timezone)
        : new Date(item.end_at);
      return {
        id: item.id,
        calendarId: item.calendar_id,
        calendarName: calendarNames.get(item.calendar_id),
        title: item.title,
        description: item.description,
        location: item.location,
        attendees: item.attendees,
        start,
        end,
        allDay: item.all_day,
        color: item.color ?? calendarColors.get(item.calendar_id) ?? DEFAULT_CALENDAR_COLOR,
        recurrence: item.recurrence,
      };
    },
    // calendarColors/Names are derived from calendars each render; key on calendars.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [calendars, preferences.timezone],
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

  const toggleCalendar = useCallback((calendarId: string) => {
    setHiddenCalendarIds((current) => {
      const next = new Set(current);
      if (next.has(calendarId)) next.delete(calendarId);
      else next.add(calendarId);
      return next;
    });
  }, []);

  const moveEvent = useCallback(
    async (event: WeekEvent, start: Date, end: Date) => {
      if (event.allDay) return;

      setSelected(null);
      setEvents((prev) =>
        prev.map((item) =>
          item.id === event.id && item.start.getTime() === event.start.getTime()
            ? { ...item, start: new Date(start), end: new Date(end) }
            : item,
        ),
      );

      const response = await fetch(`/api/events/${event.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({
          start_at: start.toISOString(),
          end_at: end.toISOString(),
          occurrence_start: event.start.toISOString(),
        }),
      });

      if (!response.ok) {
        refetchEvents();
        return;
      }
      refetchEvents();
    },
    [accessToken, refetchEvents],
  );

  const deleteSelectedEvent = useCallback(
    async (event: WeekEvent) => {
      setDeleting(true);
      try {
        const response = await fetch(`/api/events/${event.id}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${accessToken}` },
        });
        if (response.ok) {
          setSelected(null);
          setDeleteDialog({ open: false });
          refetchEvents();
        }
      } finally {
        setDeleting(false);
      }
    },
    [accessToken, refetchEvents],
  );

  const deleteRecurringEvent = useCallback(
    async (event: WeekEvent, mode: "this_only" | "this_and_future") => {
      setDeleting(true);
      try {
        const params = new URLSearchParams({
          mode,
          occurrence_start: event.start.toISOString(),
        });
        const response = await fetch(`/api/events/${event.id}/bulk-delete?${params.toString()}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${accessToken}` },
        });
        if (response.ok) {
          setSelected(null);
          setDeleteDialog({ open: false });
          refetchEvents();
        }
      } finally {
        setDeleting(false);
      }
    },
    [accessToken, refetchEvents],
  );

  const openDeleteDialog = useCallback(() => {
    if (!selected) return;
    setDeleteDialog({ open: true, event: selected.event });
  }, [selected]);

  const handleDeleteAll = useCallback(async () => {
    if (!deleteDialog.open) return;
    await deleteSelectedEvent(deleteDialog.event);
  }, [deleteDialog, deleteSelectedEvent]);

  const handleDeleteThis = useCallback(async () => {
    if (!deleteDialog.open) return;
    await deleteRecurringEvent(deleteDialog.event, "this_only");
  }, [deleteDialog, deleteRecurringEvent]);

  const handleDeleteThisAndFuture = useCallback(async () => {
    if (!deleteDialog.open) return;
    await deleteRecurringEvent(deleteDialog.event, "this_and_future");
  }, [deleteDialog, deleteRecurringEvent]);

  useEffect(() => {
    if (authStatus !== "ready") return;

    let cancelled = false;

    const loadCalendars = async () => {
      await fetch(`/api/workspaces/${workspaceId}/holiday-settings/sync`, {
        method: "POST",
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      const [response, preferencesResponse] = await Promise.all([
        fetch(`/api/workspaces/${workspaceId}/calendars`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        }),
        fetch(`/api/workspaces/${workspaceId}/preferences`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        }),
      ]);
      if (cancelled) return;
      if (response.status === 404) {
        setStatus("not-found");
        return;
      }
      if (response.ok) {
        setCalendars(await response.json());
        if (preferencesResponse.ok) setPreferences(await preferencesResponse.json());
        setStatus("ready");
      }
    };

    void loadCalendars();

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
      <AppHeader
        workspaceId={workspaceId}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((value) => !value)}
      />
      <div className="workspace-content">
        <Sidebar
          calendars={calendars}
          hiddenCalendarIds={hiddenCalendarIds}
          selectedDate={focusDate}
          open={sidebarOpen}
          onSelectDay={(date) => {
            setFocusDate(date);
            setView("day");
          }}
          onCreateEvent={() => setDialog({ open: true })}
          onToggleCalendar={toggleCalendar}
        />
        <main className="calendar-main">
          <WeekView
            calendars={calendars}
            preferences={preferences}
            view={view}
            date={focusDate}
            events={events}
            hiddenCalendarIds={hiddenCalendarIds}
            onDateChange={setFocusDate}
            onViewChange={setView}
            onVisibleRangeChange={handleVisibleRangeChange}
            onSlotClick={(start) => setDialog({ open: true, initialStart: start })}
            onEventClick={(event, anchor) => setSelected({ event, anchor })}
            onEventMove={moveEvent}
          />
        </main>
      </div>

      {selected && (
        <EventDetail
          event={selected.event}
          anchor={selected.anchor}
          timeFormat={preferences.time_format}
          deleting={deleting}
          onClose={() => setSelected(null)}
          onDelete={openDeleteDialog}
        />
      )}

      {deleteDialog.open && (
        <EventDeleteDialog
          event={deleteDialog.event}
          deleting={deleting}
          onClose={() => setDeleteDialog({ open: false })}
          onDeleteAll={handleDeleteAll}
          onDeleteThis={handleDeleteThis}
          onDeleteThisAndFuture={handleDeleteThisAndFuture}
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
