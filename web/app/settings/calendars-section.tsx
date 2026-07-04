"use client";

import { useEffect, useState, type SubmitEvent } from "react";
import { Plus } from "lucide-react";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRequireAuth } from "@/lib/auth-client";
import type { Calendar, Workspace } from "@/lib/types";

const CALENDAR_COLORS = ["#4f46e5", "#0ea5e9", "#16a34a", "#f59e0b", "#e11d48"];

export function CalendarsSection() {
  const { status: authStatus, accessToken } = useRequireAuth();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [calendars, setCalendars] = useState<Calendar[]>([]);
  const [calendarName, setCalendarName] = useState("");
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (authStatus !== "ready") return;
    let cancelled = false;

    fetch("/api/workspaces", {
      headers: { Authorization: `Bearer ${accessToken}` },
    }).then(async (response) => {
      if (cancelled || !response.ok) return;
      const body: Workspace[] = await response.json();
      setWorkspaces(body);
      if (body.length > 0) setWorkspaceId(body[0].id);
    });

    return () => {
      cancelled = true;
    };
  }, [authStatus, accessToken]);

  useEffect(() => {
    if (authStatus !== "ready" || !workspaceId) return;
    let cancelled = false;

    fetch(`/api/workspaces/${workspaceId}/calendars`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    }).then(async (response) => {
      if (cancelled || !response.ok) return;
      setCalendars(await response.json());
    });

    return () => {
      cancelled = true;
    };
  }, [authStatus, accessToken, workspaceId]);

  async function handleAddCalendar(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!calendarName.trim() || !workspaceId) return;
    setPending(true);
    setErrorMessage(null);

    const color = CALENDAR_COLORS[calendars.length % CALENDAR_COLORS.length];
    const response = await fetch(`/api/workspaces/${workspaceId}/calendars`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ name: calendarName, color }),
    });

    if (!response.ok) {
      setErrorMessage("Could not create the calendar. Please try again.");
      setPending(false);
      return;
    }

    const calendar: Calendar = await response.json();
    setCalendars((prev) => [...prev, calendar]);
    setCalendarName("");
    setPending(false);
  }

  if (workspaces.length === 0) return null;

  return (
    <section className="settings-section">
      <h2 className="settings-section-title">Calendars</h2>
      <p className="settings-section-hint">Add calendars to a workspace to organize your events.</p>

      <div className="form-field">
        <Label htmlFor="calendars-workspace" className="form-label">
          Workspace
        </Label>
        <Select value={workspaceId ?? undefined} onValueChange={setWorkspaceId}>
          <SelectTrigger id="calendars-workspace" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {workspaces.map((workspace) => (
              <SelectItem key={workspace.id} value={workspace.id}>
                {workspace.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {calendars.length > 0 && (
        <div className="calendar-list">
          {calendars.map((calendar) => (
            <div className="calendar-chip" key={calendar.id}>
              <span className="calendar-chip-dot" style={{ background: calendar.color }} />
              {calendar.name}
            </div>
          ))}
        </div>
      )}

      <form className="settings-grid" onSubmit={handleAddCalendar}>
        <div className="form-field">
          <Label htmlFor="calendar-name" className="form-label">
            Calendar name
          </Label>
          <input
            className="form-input"
            id="calendar-name"
            value={calendarName}
            onChange={(event) => setCalendarName(event.target.value)}
            placeholder="e.g. Personal, Work"
            maxLength={120}
          />
        </div>

        {errorMessage && <p className="form-error form-error--summary">{errorMessage}</p>}

        <button
          className="button-primary"
          type="submit"
          disabled={pending || !calendarName.trim()}
        >
          <Plus size={16} />
          {pending ? "Adding…" : "Add calendar"}
        </button>
      </form>
    </section>
  );
}
