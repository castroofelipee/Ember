"use client";

import { useEffect, useState, type SubmitEvent } from "react";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRequireAuth } from "@/lib/auth-client";

import { LOCALE_OPTIONS, TIMEZONE_OPTIONS } from "./locales";

type Status = "loading" | "ready" | "saving" | "success" | "error";

export function PreferencesForm() {
  const { status: authStatus, accessToken } = useRequireAuth("/signup");
  const [status, setStatus] = useState<Status>("loading");
  const [locale, setLocale] = useState("en-US");
  const [timezone, setTimezone] = useState("UTC");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (authStatus !== "ready") return;
    let cancelled = false;

    fetch("/api/users/me/preferences", {
      headers: { Authorization: `Bearer ${accessToken}` },
    }).then(async (response) => {
      if (cancelled) return;
      if (response.ok) {
        const body = await response.json();
        setLocale(body.locale);
        setTimezone(body.timezone);
      }
      setStatus("ready");
    });

    return () => {
      cancelled = true;
    };
  }, [authStatus, accessToken]);

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
        body: JSON.stringify({ locale, timezone }),
      });

      if (response.ok) {
        setStatus("success");
        return;
      }

      setErrorMessage("Could not save your preferences. Please try again.");
      setStatus("ready");
    } catch {
      setErrorMessage("Could not reach the server. Please try again.");
      setStatus("ready");
    }
  }

  if (status === "loading") {
    return <p className="auth-subtitle">Loading…</p>;
  }

  if (status === "success") {
    return <p className="auth-success">Preferences saved.</p>;
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      <div className="form-field">
        <Label htmlFor="locale" className="form-label">
          Language
        </Label>
        <Select value={locale} onValueChange={setLocale}>
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
        <Select value={timezone} onValueChange={setTimezone}>
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

      {errorMessage && <p className="form-error form-error--summary">{errorMessage}</p>}

      <button className="button-primary" type="submit" disabled={status === "saving"}>
        {status === "saving" ? "Saving…" : "Save preferences"}
      </button>
    </form>
  );
}
