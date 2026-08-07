"use client";

import { useEffect, useState, type SubmitEvent } from "react";
import { useRouter } from "next/navigation";
import { AtSignIcon, EyeIcon, EyeOffIcon, LockKeyholeIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { adoptAccessToken, getAccessToken } from "@/lib/auth-client";

export function LoginForm() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    // Warm the destination while checking the existing httpOnly refresh
    // cookie. A valid session should never require another password entry.
    router.prefetch("/calendars");
    getAccessToken()
      .then(() => {
        if (!cancelled) router.replace("/calendars");
      })
      .catch(() => {
        // No session (or a temporary network failure): keep the login form
        // usable. The submit path reports connectivity errors explicitly.
      });

    return () => {
      cancelled = true;
    };
  }, [router]);

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setErrorMessage(null);

    const formData = new FormData(event.currentTarget);
    const payload = {
      email: String(formData.get("email") ?? "").trim(),
      password: String(formData.get("password") ?? ""),
    };

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (response.status === 200) {
        const body = await response.json();
        adoptAccessToken(body.access_token as string);
        router.replace("/calendars");
        return;
      }

      if (response.status === 401) {
        setErrorMessage("Invalid email or password.");
        return;
      }

      setErrorMessage("Something went wrong. Please try again.");
    } catch {
      setErrorMessage("Could not reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="space-y-5" onSubmit={handleSubmit}>
      <div className="space-y-2">
        <label className="text-sm font-medium" htmlFor="email">
          Email
        </label>
        <div className="relative">
          <AtSignIcon
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            className="h-11 pl-10"
            id="email"
            name="email"
            type="email"
            placeholder="you@example.com"
            autoComplete="email"
            disabled={pending}
            required
          />
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium" htmlFor="password">
          Password
        </label>
        <div className="relative">
          <LockKeyholeIcon
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            className="h-11 px-10"
            id="password"
            name="password"
            type={showPassword ? "text" : "password"}
            placeholder="Enter your password"
            autoComplete="current-password"
            disabled={pending}
            required
          />
          <button
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            type="button"
            aria-label={showPassword ? "Hide password" : "Show password"}
            aria-pressed={showPassword}
            onClick={() => setShowPassword((visible) => !visible)}
            disabled={pending}
          >
            {showPassword ? (
              <EyeOffIcon className="size-4" aria-hidden="true" />
            ) : (
              <EyeIcon className="size-4" aria-hidden="true" />
            )}
          </button>
        </div>
      </div>

      {errorMessage && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
          {errorMessage}
        </p>
      )}

      <Button className="h-11 w-full" type="submit" disabled={pending}>
        {pending ? "Logging in…" : "Log in"}
      </Button>
    </form>
  );
}
