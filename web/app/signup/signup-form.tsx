"use client";

import { useEffect, useState, type SubmitEvent } from "react";
import { useRouter } from "next/navigation";

type FieldErrors = Record<string, string>;

function extractFieldErrors(detail: unknown): FieldErrors {
  const errors: FieldErrors = {};
  if (!Array.isArray(detail)) return errors;

  for (const issue of detail) {
    const loc = issue?.loc;
    const field = Array.isArray(loc) ? loc[loc.length - 1] : undefined;
    if (typeof field === "string" && typeof issue?.msg === "string") {
      errors[field] = issue.msg;
    }
  }
  return errors;
}

export function SignupForm() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  // Read the invite code straight from the URL rather than useSearchParams, so
  // the statically-exported signup page needs no Suspense boundary.
  const [inviteCode, setInviteCode] = useState<string | null>(null);

  useEffect(() => {
    // Syncing from the URL (an external system) after mount; deliberately not a
    // lazy initializer, so the prerendered HTML and first client render match.
    const code = new URLSearchParams(window.location.search).get("invite");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (code) setInviteCode(code);
  }, []);

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setPending(true);
    setFormError(null);
    setFieldErrors({});

    const formData = new FormData(form);
    const payload: Record<string, string> = {
      email: String(formData.get("email") ?? "").trim(),
      password: String(formData.get("password") ?? ""),
      display_name: String(formData.get("display_name") ?? "").trim(),
    };
    if (inviteCode) payload.invite_code = inviteCode;

    try {
      const response = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (response.status === 201) {
        form.reset();
        router.push("/onboarding/preferences");
        return;
      }

      if (response.status === 409) {
        setFormError("An account with this email already exists.");
        return;
      }

      if (response.status === 422) {
        const body = await response.json();
        const errors = extractFieldErrors(body?.detail);
        setFieldErrors(errors);
        setFormError("Please fix the highlighted fields.");
        return;
      }

      setFormError("Something went wrong. Please try again.");
    } catch {
      setFormError("Could not reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      {inviteCode && <p className="auth-success">You&apos;re joining via invitation.</p>}
      <div className="form-field">
        <label className="form-label" htmlFor="display_name">
          Name
        </label>
        <input
          className="form-input"
          id="display_name"
          name="display_name"
          type="text"
          autoComplete="name"
          maxLength={120}
          required
        />
        {fieldErrors.display_name && <p className="form-error">{fieldErrors.display_name}</p>}
      </div>

      <div className="form-field">
        <label className="form-label" htmlFor="email">
          Email
        </label>
        <input
          className="form-input"
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
        />
        {fieldErrors.email && <p className="form-error">{fieldErrors.email}</p>}
      </div>

      <div className="form-field">
        <label className="form-label" htmlFor="password">
          Password
        </label>
        <input
          className="form-input"
          id="password"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={12}
          required
        />
        {fieldErrors.password && <p className="form-error">{fieldErrors.password}</p>}
      </div>

      {formError && <p className="form-error form-error--summary">{formError}</p>}

      <button className="button-primary" type="submit" disabled={pending}>
        {pending ? "Creating account…" : "Create account"}
      </button>
    </form>
  );
}
