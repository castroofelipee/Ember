"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/** How long before a token's `exp` we treat it as already expired. Covers clock
 * skew between browser and server, plus the request's own flight time. */
const EXPIRY_SKEW_MS = 60_000;
/** How often the background keep-alive checks whether the token is near expiry.
 * Only refreshes when the tab is visible — a hidden tab wakes up on focus. */
const KEEPALIVE_INTERVAL_MS = 60_000;
/** Backoff bounds for retrying a refresh that failed for network reasons
 * (offline, server restarting). A 401 is never retried — that session is gone. */
const RETRY_BASE_MS = 2_000;
const RETRY_MAX_MS = 30_000;

/** Raised when the refresh cookie is missing, expired, revoked, or reused — the
 * only failure mode that should send the user back to /login. Network failures
 * deliberately do NOT produce this: losing wifi for two seconds must not log
 * anyone out. */
export class SessionExpiredError extends Error {
  constructor() {
    super("Session expired");
    this.name = "SessionExpiredError";
  }
}

// Module-scoped, not component-scoped: every hook and every fetch in the app
// shares one token and one in-flight refresh. Two reasons this cannot live in
// React state:
//   1. /api/auth/refresh rotates a single-use token, so two concurrent calls
//      look like token reuse to the backend and get the whole session revoked.
//   2. A page with N components each calling useRequireAuth would otherwise do
//      N refresh round-trips before rendering anything.
let accessToken: string | null = null;
let expiresAtMs = 0;
let refreshPromise: Promise<string> | null = null;

/** Notified when the session is definitively gone, so mounted pages can bounce
 * to /login instead of sitting on a screen whose every request now 401s. */
const sessionLostListeners = new Set<() => void>();

// Cross-tab coordination. The refresh cookie is shared by every tab, but the
// token cache above is not — so two visible tabs would each refresh, and the
// loser would replay a token the backend has already marked used. That is
// indistinguishable from theft to `refresh()` in services/auth.py, which
// revokes the entire session. Both halves below exist to make that impossible:
// a Web Lock serializes refreshes across tabs, and the winner broadcasts its
// token so the others never need to ask.
const REFRESH_LOCK = "ember:auth-refresh";
const REFRESH_CHANNEL = "ember:auth-token";

const tokenChannel =
  typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(REFRESH_CHANNEL);

tokenChannel?.addEventListener("message", (event: MessageEvent<{ token?: string }>) => {
  if (typeof event.data?.token === "string") storeToken(event.data.token);
});

/** Runs `task` under a cross-tab exclusive lock where the browser supports one.
 * Without Web Locks the task still runs — single-tab use is unaffected, and the
 * multi-tab race it guards against is the pre-existing behaviour. */
async function withRefreshLock<T>(task: () => Promise<T>): Promise<T> {
  if (typeof navigator === "undefined" || !navigator.locks) return task();
  return navigator.locks.request(REFRESH_LOCK, task);
}

function onSessionLost(listener: () => void): () => void {
  sessionLostListeners.add(listener);
  return () => sessionLostListeners.delete(listener);
}

function clearSession(): void {
  accessToken = null;
  expiresAtMs = 0;
  for (const listener of sessionLostListeners) listener();
}

/** Reads `exp` out of the JWT payload so we know when to refresh without asking
 * the server. The token is not verified here — the backend is the only authority
 * on validity; this is purely a scheduling hint. An unreadable payload falls
 * back to a short lifetime so we re-check soon rather than hammering refresh. */
function readExpiry(token: string): number {
  try {
    const payload = token.split(".")[1];
    const decoded = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    if (typeof decoded.exp === "number") return decoded.exp * 1000;
  } catch {
    // Fall through to the default below.
  }
  return Date.now() + 5 * 60_000;
}

function storeToken(token: string): void {
  accessToken = token;
  expiresAtMs = readExpiry(token);
}

function isFresh(): boolean {
  return accessToken !== null && Date.now() < expiresAtMs - EXPIRY_SKEW_MS;
}

/** Exchanges the httpOnly refresh cookie for a new access token. Single-flight
 * within the tab, and serialized across tabs by the lock — the token rotates
 * once per expiry no matter how many callers or windows are open. */
function refreshAccessToken(rejectedToken?: string): Promise<string> {
  refreshPromise ??= withRefreshLock(async () => {
    // Another tab may have refreshed while this one waited for the lock and
    // broadcast the result; replaying our now-stale cookie would look like
    // theft, so take the token it published instead. `rejectedToken` is the one
    // the server just 401'd, so holding it is not "fresh" whatever `exp` says.
    if (isFresh() && accessToken !== rejectedToken) return accessToken as string;

    const response = await fetch("/api/auth/refresh", { method: "POST" });
    if (response.status === 401 || response.status === 403) {
      clearSession();
      throw new SessionExpiredError();
    }
    if (!response.ok) throw new Error(`Refresh failed: ${response.status}`);

    const body = await response.json();
    const token = body.access_token as string;
    storeToken(token);
    tokenChannel?.postMessage({ token });
    return token;
  }).finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

/** Returns a token that is valid now, refreshing only when the cached one is
 * gone or about to expire. Throws SessionExpiredError if the session is over;
 * other errors mean "try again", not "log out".
 *
 * @param force  Ignore the cache — used after a 401, where the server disagrees
 *               with our local expiry (e.g. the session was revoked elsewhere). */
export function getAccessToken(force = false): Promise<string> {
  if (!force && isFresh()) return Promise.resolve(accessToken as string);
  return refreshAccessToken(force ? (accessToken ?? undefined) : undefined);
}

/** The single entry point for authenticated requests. Injects a fresh Bearer
 * token, and if the server still says 401 (revoked session, or an expiry we
 * mis-scheduled), refreshes once and replays the request. A replay is safe even
 * for POST/PATCH/DELETE: a 401'd request never reached the handler.
 *
 * Returns the Response — including a final 401 — so existing `if (response.ok)`
 * call sites keep working; by then the session-lost redirect is already queued. */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  let token: string;
  try {
    token = await getAccessToken();
  } catch (error) {
    if (error instanceof SessionExpiredError) return new Response(null, { status: 401 });
    throw error;
  }

  const send = (bearer: string) => {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${bearer}`);
    // FormData must keep the browser-generated multipart boundary, so only
    // string bodies get a default content type.
    if (typeof init.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    return fetch(input, { ...init, headers });
  };

  const response = await send(token);
  if (response.status !== 401) return response;

  try {
    return await send(await getAccessToken(true));
  } catch (error) {
    if (error instanceof SessionExpiredError) return response;
    throw error;
  }
}

type AuthState = { status: "loading" | "ready" };

/** Gates a client-rendered page on a logged-in user and keeps the shared access
 * token alive for as long as the page is mounted (this app is a static export —
 * there is no server-side auth check, so the gate can only run in the browser).
 *
 * Components no longer receive the token: `apiFetch` reads it at request time,
 * which is what stops a 15-minute-old page from firing dead Bearer headers. */
export function useRequireAuth(redirectTo = "/login"): AuthState {
  const router = useRouter();
  const [status, setStatus] = useState<AuthState["status"]>(() => (isFresh() ? "ready" : "loading"));

  useEffect(() => {
    let cancelled = false;
    let retryDelay = RETRY_BASE_MS;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const expire = () => {
      if (!cancelled) router.replace(redirectTo);
    };

    /** @param force  true for the keep-alive path, which must refresh a token
     *                that is merely near expiry rather than gone. */
    const ensureToken = (force = false) => {
      getAccessToken(force)
        .then(() => {
          if (cancelled) return;
          retryDelay = RETRY_BASE_MS;
          setStatus("ready");
        })
        .catch((error) => {
          if (cancelled) return;
          if (error instanceof SessionExpiredError) {
            expire();
            return;
          }
          // Network-level failure: keep whatever is on screen and retry with
          // backoff instead of logging the user out mid-task.
          retryTimer = setTimeout(() => ensureToken(force), retryDelay);
          retryDelay = Math.min(retryDelay * 2, RETRY_MAX_MS);
        });
    };

    ensureToken();
    const unsubscribe = onSessionLost(expire);

    // Silent renewal: refresh shortly before expiry so an idle tab that the user
    // returns to after an hour acts immediately instead of stalling on a refresh.
    const keepAlive = setInterval(() => {
      if (document.visibilityState !== "visible" || isFresh()) return;
      ensureToken(true);
    }, KEEPALIVE_INTERVAL_MS);

    const onVisible = () => {
      if (document.visibilityState === "visible" && !isFresh()) ensureToken(true);
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      clearInterval(keepAlive);
      document.removeEventListener("visibilitychange", onVisible);
      unsubscribe();
    };
  }, [router, redirectTo]);

  return { status };
}

/** Seeds the cache with the token that /login and /signup already returned, so
 * the first page after authenticating renders without a redundant refresh
 * round-trip (which would also rotate a brand-new refresh token for nothing). */
export function adoptAccessToken(token: string): void {
  storeToken(token);
}
