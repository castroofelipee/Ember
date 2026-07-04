"use client";

import { useEffect, useMemo, useState, type SubmitEvent } from "react";
import { useRouter } from "next/navigation";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRequireAuth } from "@/lib/auth-client";
import { DEFAULT_PREFERENCES, type Preferences, type TimeFormat } from "@/lib/types";

import { LOCALE_OPTIONS, TIMEZONE_OPTIONS } from "../onboarding/preferences/locales";

type Status = "loading" | "ready" | "saving" | "success" | "error";

const WEEK_START_OPTIONS = [
  { value: 0, label: "Sunday" },
  { value: 1, label: "Monday" },
  { value: 6, label: "Saturday" },
] as const;

const TIME_FORMAT_OPTIONS: { value: TimeFormat; label: string }[] = [
  { value: "12h", label: "12-hour (1 PM)" },
  { value: "24h", label: "24-hour (13:00)" },
];

function hourLabel(hour: number, format: TimeFormat): string {
  if (format === "24h") return `${String(hour).padStart(2, "0")}:00`;
  if (hour === 0 || hour === 24) return "12 AM";
  if (hour === 12) return "12 PM";
  return hour < 12 ? `${hour} AM` : `${hour - 12} PM`;
}

export function SettingsForm() {
  const router = useRouter();
  const { status: authStatus, accessToken } = useRequireAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [prefs, setPrefs] = useState<Preferences>(DEFAULT_PREFERENCES);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (authStatus !== "ready") return;
    let cancelled = false;

    fetch("/api/users/me/preferences", {
      headers: { Authorization: `Bearer ${accessToken}` },
    }).then(async (response) => {
      if (cancelled) return;
      if (response.ok) setPrefs(await response.json());
      setStatus("ready");
    });

    return () => {
      cancelled = true;
    };
  }, [authStatus, accessToken]);

  const set = <K extends keyof Preferences>(key: K, value: Preferences[K]) => {
    setPrefs((prev) => ({ ...prev, [key]: value }));
    if (status === "success") setStatus("ready");
  };

  // work_day_end is exclusive, so it can run to 24 (midnight) and must stay
  // above the chosen start.
  const startHours = useMemo(() => Array.from({ length: 24 }, (_, h) => h), []);
  const endHours = useMemo(
    () => Array.from({ length: 24 }, (_, i) => i + 1).filter((h) => h > prefs.work_day_start),
    [prefs.work_day_start],
  );

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (authStatus !== "ready") return;

    setStatus("saving");
    setErrorMessage(null);

    try {
      const response = await fetch("/api/users/me/preferences", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify(prefs),
      });

      if (response.ok) {
        setPrefs(await response.json());
        setStatus("success");
        return;
      }

      setErrorMessage("Could not save your settings. Please try again.");
      setStatus("ready");
    } catch {
      setErrorMessage("Could not reach the server. Please try again.");
      setStatus("ready");
    }
  }

  if (status === "loading") {
    return <p className="auth-subtitle">Loading…</p>;
  }

  return (
    <form className="settings-form" onSubmit={handleSubmit}>
      <section className="settings-section">
        <h2 className="settings-section-title">General</h2>
        <div className="settings-grid">
          <div className="form-field">
            <Label htmlFor="locale" className="form-label">
              Language
            </Label>
            <Select value={prefs.locale} onValueChange={(v) => set("locale", v)}>
              <SelectTrigger id="locale" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LOCALE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="form-field">
            <Label htmlFor="timezone" className="form-label">
              Timezone
            </Label>
            <Select value={prefs.timezone} onValueChange={(v) => set("timezone", v)}>
              <SelectTrigger id="timezone" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIMEZONE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <h2 className="settings-section-title">Calendar view</h2>
        <p className="settings-section-hint">Controls how the week appears in your workspace.</p>
        <div className="settings-grid">
          <div className="form-field">
            <Label htmlFor="week-start" className="form-label">
              Week starts on
            </Label>
            <Select
              value={String(prefs.week_starts_on)}
              onValueChange={(v) => set("week_starts_on", Number(v))}
            >
              <SelectTrigger id="week-start" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {WEEK_START_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={String(option.value)}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="form-field">
            <Label htmlFor="time-format" className="form-label">
              Time format
            </Label>
            <Select
              value={prefs.time_format}
              onValueChange={(v) => set("time_format", v as TimeFormat)}
            >
              <SelectTrigger id="time-format" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIME_FORMAT_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <h2 className="settings-section-title">Working hours</h2>
        <p className="settings-section-hint">
          Hours outside this range are dimmed in the calendar so your workday stands out.
        </p>
        <div className="settings-grid">
          <div className="form-field">
            <Label htmlFor="work-start" className="form-label">
              Start
            </Label>
            <Select
              value={String(prefs.work_day_start)}
              onValueChange={(v) => {
                const start = Number(v);
                setPrefs((prev) => ({
                  ...prev,
                  work_day_start: start,
                  work_day_end: Math.max(prev.work_day_end, start + 1),
                }));
                if (status === "success") setStatus("ready");
              }}
            >
              <SelectTrigger id="work-start" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {startHours.map((hour) => (
                  <SelectItem key={hour} value={String(hour)}>
                    {hourLabel(hour, prefs.time_format)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="form-field">
            <Label htmlFor="work-end" className="form-label">
              End
            </Label>
            <Select
              value={String(prefs.work_day_end)}
              onValueChange={(v) => set("work_day_end", Number(v))}
            >
              <SelectTrigger id="work-end" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {endHours.map((hour) => (
                  <SelectItem key={hour} value={String(hour)}>
                    {hourLabel(hour, prefs.time_format)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </section>

      {errorMessage && <p className="form-error form-error--summary">{errorMessage}</p>}
      {status === "success" && <p className="auth-success">Settings saved.</p>}

      <div className="settings-actions">
        <button
          type="button"
          className="link-button"
          onClick={() => router.back()}
        >
          Back
        </button>
        <button className="button-primary" type="submit" disabled={status === "saving"}>
          {status === "saving" ? "Saving…" : "Save settings"}
        </button>
      </div>
    </form>
  );
}
