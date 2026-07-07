"use client";

import { useState, type SubmitEvent } from "react";
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

import { LOCALE_OPTIONS, TIMEZONE_OPTIONS } from "./locales";

type Status = "ready" | "saving" | "error";

/** sessionStorage key read by OnboardingTour once the user's first workspace
 * exists — preferences are scoped per workspace, so this step can only stash
 * the choice, not save it (there is no workspace yet to attach it to). */
export const PENDING_PREFERENCES_KEY = "ember:pending-onboarding-preferences";

export function PreferencesForm() {
  const router = useRouter();
  const { status: authStatus } = useRequireAuth("/signup");
  const [status, setStatus] = useState<Status>("ready");
  const [locale, setLocale] = useState("en-US");
  const [timezone, setTimezone] = useState(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (authStatus !== "ready") return;

    setStatus("saving");
    setErrorMessage(null);

    try {
      sessionStorage.setItem(PENDING_PREFERENCES_KEY, JSON.stringify({ locale, timezone }));
      router.push("/calendars");
    } catch {
      setErrorMessage("Could not save your preferences. Please try again.");
      setStatus("error");
    }
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
