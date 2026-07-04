"use client";

import { useState, type SubmitEvent } from "react";
import { Building2, CalendarDays, Plus } from "lucide-react";

import type { Calendar } from "@/lib/types";

type Step = "workspace" | "calendars";

const CALENDAR_COLORS = ["#4f46e5", "#0ea5e9", "#16a34a", "#f59e0b", "#e11d48"];

export function OnboardingTour({
  accessToken,
  onDone,
}: {
  accessToken: string;
  onDone: (workspaceId: string) => void;
}) {
  const [step, setStep] = useState<Step>("workspace");
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [workspaceName, setWorkspaceName] = useState("");
  const [calendarName, setCalendarName] = useState("");
  const [calendars, setCalendars] = useState<Calendar[]>([]);
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleCreateWorkspace(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setErrorMessage(null);

    const response = await fetch("/api/workspaces", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ name: workspaceName }),
    });

    if (!response.ok) {
      setErrorMessage("Could not create the workspace. Please try again.");
      setPending(false);
      return;
    }

    const workspace = await response.json();
    setWorkspaceId(workspace.id);
    setStep("calendars");
    setPending(false);
  }

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

  return (
    <div className="auth-form">
      <div className="tour-steps">
        <span
          className={`tour-step-dot ${step === "workspace" ? "tour-step-dot--active" : "tour-step-dot--done"}`}
        />
        <span className={`tour-step-dot ${step === "calendars" ? "tour-step-dot--active" : ""}`} />
      </div>

      {step === "workspace" && (
        <form className="auth-form" onSubmit={handleCreateWorkspace}>
          <div className="form-field">
            <label className="form-label" htmlFor="workspace-name">
              Workspace name
            </label>
            <input
              className="form-input"
              id="workspace-name"
              value={workspaceName}
              onChange={(event) => setWorkspaceName(event.target.value)}
              placeholder="e.g. Home, Family, Acme Inc."
              maxLength={120}
              required
            />
          </div>

          {errorMessage && <p className="form-error form-error--summary">{errorMessage}</p>}

          <button className="button-primary" type="submit" disabled={pending}>
            <Building2 size={16} />
            {pending ? "Creating…" : "Create workspace"}
          </button>
        </form>
      )}

      {step === "calendars" && (
        <>
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

          <form className="auth-form" onSubmit={handleAddCalendar}>
            <div className="form-field">
              <label className="form-label" htmlFor="calendar-name">
                Calendar name
              </label>
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
              Add calendar
            </button>
          </form>

          <button
            className="button-primary"
            type="button"
            disabled={calendars.length === 0}
            onClick={() => workspaceId && onDone(workspaceId)}
          >
            <CalendarDays size={16} />
            Done — go to workspace
          </button>
        </>
      )}
    </div>
  );
}
