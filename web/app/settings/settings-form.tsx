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
import {
  DEFAULT_HOLIDAY_SETTINGS,
  DEFAULT_PREFERENCES,
  type HolidaySettings,
  type Preferences,
  type TimeFormat,
  type Workspace,
} from "@/lib/types";

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

const COUNTRY_OPTIONS = [
  { value: "BR", label: "Brazil" },
  { value: "US", label: "United States" },
  { value: "PT", label: "Portugal" },
  { value: "ES", label: "Spain" },
  { value: "FR", label: "France" },
  { value: "DE", label: "Germany" },
  { value: "GB", label: "United Kingdom" },
  { value: "CA", label: "Canada" },
  { value: "MX", label: "Mexico" },
  { value: "AR", label: "Argentina" },
] as const;

const OPEN_HOLIDAYS_COUNTRIES = [
  { value: "AL", label: "Albania" },
  { value: "AD", label: "Andorra" },
  { value: "AT", label: "Austria" },
  { value: "BY", label: "Belarus" },
  { value: "BE", label: "Belgium" },
  { value: "BR", label: "Brazil" },
  { value: "BG", label: "Bulgaria" },
  { value: "HR", label: "Croatia" },
  { value: "CZ", label: "Czechia" },
  { value: "EE", label: "Estonia" },
  { value: "FR", label: "France" },
  { value: "DE", label: "Germany" },
  { value: "HU", label: "Hungary" },
  { value: "IE", label: "Ireland" },
  { value: "IT", label: "Italy" },
  { value: "LV", label: "Latvia" },
  { value: "LI", label: "Liechtenstein" },
  { value: "LT", label: "Lithuania" },
  { value: "LU", label: "Luxembourg" },
  { value: "MT", label: "Malta" },
  { value: "MX", label: "Mexico" },
  { value: "MD", label: "Moldova" },
  { value: "MC", label: "Monaco" },
  { value: "NL", label: "Netherlands" },
  { value: "PL", label: "Poland" },
  { value: "PT", label: "Portugal" },
  { value: "RO", label: "Romania" },
  { value: "SM", label: "San Marino" },
  { value: "RS", label: "Serbia" },
  { value: "SK", label: "Slovakia" },
  { value: "SI", label: "Slovenia" },
  { value: "ZA", label: "South Africa" },
  { value: "ES", label: "Spain" },
  { value: "SE", label: "Sweden" },
  { value: "CH", label: "Switzerland" },
  { value: "VA", label: "Vatican City" },
] as const;

const BRAZIL_STATES = [
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
  "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
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
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [holidays, setHolidays] = useState<HolidaySettings>(DEFAULT_HOLIDAY_SETTINGS);
  const holidayCountryOptions = holidays.provider === "openholidays"
    ? OPEN_HOLIDAYS_COUNTRIES
    : COUNTRY_OPTIONS;

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
      else setStatus("ready");
    });

    return () => {
      cancelled = true;
    };
  }, [authStatus, accessToken]);

  useEffect(() => {
    if (authStatus !== "ready" || !workspaceId) return;
    let cancelled = false;

    Promise.all([
      fetch(`/api/workspaces/${workspaceId}/preferences`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      }),
      fetch(`/api/workspaces/${workspaceId}/holiday-settings`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      }),
    ]).then(async ([preferencesResponse, holidayResponse]) => {
      if (cancelled) return;
      if (preferencesResponse.ok) setPrefs(await preferencesResponse.json());
      if (holidayResponse.ok) setHolidays(await holidayResponse.json());
      else setHolidays(DEFAULT_HOLIDAY_SETTINGS);
      setStatus((prev) => (prev === "loading" ? "ready" : prev));
    });

    return () => {
      cancelled = true;
    };
  }, [authStatus, accessToken, workspaceId]);

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
    if (authStatus !== "ready" || !workspaceId) return;

    setStatus("saving");
    setErrorMessage(null);

    try {
      const response = await fetch(`/api/workspaces/${workspaceId}/preferences`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify(prefs),
      });

      if (!response.ok) throw new Error("Could not save your settings. Please try again.");
      setPrefs(await response.json());
      const holidayResponse = await fetch(`/api/workspaces/${workspaceId}/holiday-settings`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify(holidays),
      });
      if (!holidayResponse.ok) {
        const body = await holidayResponse.json().catch(() => null);
        throw new Error(body?.detail ?? "Could not synchronize holidays.");
      }
      setHolidays(await holidayResponse.json());
      setStatus("success");
      return;
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not reach the server. Please try again.");
      setStatus("ready");
    }
  }

  if (workspaces.length === 0 && status === "loading") {
    return <p className="auth-subtitle">Loading…</p>;
  }

  if (workspaces.length === 0) {
    return <p className="auth-subtitle">Create a workspace to configure its settings.</p>;
  }

  return (
    <form className="settings-form" onSubmit={handleSubmit}>
      <section className="settings-section">
        <h2 className="settings-section-title">Workspace</h2>
        <p className="settings-section-hint">
          Each workspace has its own schedule and settings.
        </p>
        <div className="form-field">
          <Label htmlFor="settings-workspace" className="form-label">
            Workspace
          </Label>
          <Select value={workspaceId ?? undefined} onValueChange={setWorkspaceId}>
            <SelectTrigger id="settings-workspace" className="w-full">
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
      </section>

      {status === "loading" && <p className="auth-subtitle">Loading…</p>}

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

      <section className="settings-section">
        <h2 className="settings-section-title">Holidays</h2>
        <p className="settings-section-hint">
          Synchronize national and local holidays as all-day events in a separate calendar.
        </p>
        <label className="settings-holiday-toggle">
          <input
            type="checkbox"
            checked={holidays.enabled}
            onChange={(event) => setHolidays((prev) => ({ ...prev, enabled: event.target.checked }))}
          />
          <span>Show holidays in this workspace</span>
        </label>
        <div className="settings-grid">
          <div className="form-field">
            <Label htmlFor="holiday-provider" className="form-label">Provider</Label>
            <Select
              value={holidays.provider}
              onValueChange={(value) => setHolidays((prev) => ({
                ...prev,
                provider: value as HolidaySettings["provider"],
                country: value === "openholidays"
                  && !OPEN_HOLIDAYS_COUNTRIES.some((country) => country.value === prev.country)
                  ? "BR"
                  : prev.country,
                region: value === "openholidays"
                  && !OPEN_HOLIDAYS_COUNTRIES.some((country) => country.value === prev.country)
                  ? ""
                  : prev.region,
                city: "",
              }))}
            >
              <SelectTrigger id="holiday-provider" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="calendarific">Calendarific</SelectItem>
                <SelectItem value="openholidays">OpenHolidays</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="form-field">
            <Label htmlFor="holiday-country" className="form-label">Country</Label>
            <Select
              value={holidays.country}
              onValueChange={(country) => setHolidays((prev) => ({ ...prev, country, region: "", city: "" }))}
            >
              <SelectTrigger id="holiday-country" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {holidayCountryOptions.map((country) => (
                  <SelectItem value={country.value} key={country.value}>{country.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="form-field">
            <Label htmlFor="holiday-region" className="form-label">State or region</Label>
            {holidays.country === "BR" ? (
              <Select
                value={holidays.region || "national"}
                onValueChange={(region) => setHolidays((prev) => ({ ...prev, region: region === "national" ? "" : region, city: "" }))}
              >
                <SelectTrigger id="holiday-region" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="national">National only</SelectItem>
                  {BRAZIL_STATES.map((state) => <SelectItem value={state} key={state}>{state}</SelectItem>)}
                </SelectContent>
              </Select>
            ) : (
              <input
                id="holiday-region"
                className="form-input"
                value={holidays.region}
                onChange={(event) => setHolidays((prev) => ({ ...prev, region: event.target.value.toUpperCase() }))}
                placeholder="ISO subdivision, e.g. CA"
              />
            )}
          </div>
          <div className="form-field">
            <Label htmlFor="holiday-city" className="form-label">City</Label>
            <input
              id="holiday-city"
              className="form-input"
              value={holidays.city}
              disabled
              onChange={(event) => setHolidays((prev) => ({ ...prev, city: event.target.value }))}
              placeholder="Not supported by this provider"
            />
          </div>
        </div>
        {holidays.synced_events > 0 && (
          <p className="settings-section-hint">{holidays.synced_events} holidays synchronized.</p>
        )}
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
