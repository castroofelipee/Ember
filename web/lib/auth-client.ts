"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

// Module-scoped (not component-scoped) dedup for concurrent callers:
// /api/auth/refresh rotates a single-use token, so calling it twice at once
// (e.g. React Strict Mode's intentional double-invocation of effects in dev)
// would make the second call look like token reuse to the backend, which
// revokes the session. The cache is cleared once the call settles, so it only
// collapses truly-concurrent calls — a later, separate visit to any page
// still gets its own fresh refresh.
let refreshPromise: Promise<string | null> | null = null;

export function getAccessToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = fetch("/api/auth/refresh", { method: "POST" })
      .then(async (response) => {
        if (!response.ok) return null;
        const body = await response.json();
        return body.access_token as string;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

type AuthState =
  | { status: "loading"; accessToken: null }
  | { status: "ready"; accessToken: string };

/** Redirects to `redirectTo` if there's no valid session; otherwise hands back
 * a fresh access token. Shared by every client-rendered page that requires a
 * logged-in user (this app has no server-side auth check available — static
 * export ships no Node server, so the gate can only run in the browser). */
export function useRequireAuth(redirectTo = "/login"): AuthState {
  const router = useRouter();
  const [state, setState] = useState<AuthState>({ status: "loading", accessToken: null });

  useEffect(() => {
    let cancelled = false;

    getAccessToken().then((token) => {
      if (cancelled) return;
      if (!token) {
        router.replace(redirectTo);
        return;
      }
      setState({ status: "ready", accessToken: token });
    });

    return () => {
      cancelled = true;
    };
  }, [router, redirectTo]);

  return state;
}
