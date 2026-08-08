"use client";

import { useCallback, useEffect, useState } from "react";
import { GitBranch, Loader2 } from "lucide-react";

import { apiFetch, useRequireAuth } from "@/lib/auth-client";
import type { GitHubStatus } from "@/lib/types";

/** Outcomes the OAuth callback redirects back with (routers/github.py). */
const OUTCOME_MESSAGES: Record<string, { tone: "ok" | "error"; text: string }> = {
  connected: { tone: "ok", text: "GitHub connected." },
  denied: { tone: "error", text: "You declined the authorization on GitHub." },
  invalid_state: {
    tone: "error",
    text: "That sign-in attempt expired or did not match. Try connecting again.",
  },
  error: { tone: "error", text: "GitHub could not be connected. Try again." },
};

export function GitHubSection() {
  const { status: authStatus } = useRequireAuth();

  const [status, setStatus] = useState<GitHubStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Read the callback's outcome straight from the URL rather than
  // useSearchParams, so this page needs no Suspense boundary — same reasoning
  // as signup-form.tsx.
  const [outcome, setOutcome] = useState<string | null>(null);

  const notice = outcome ? OUTCOME_MESSAGES[outcome] : undefined;

  const load = useCallback(async () => {
    const response = await apiFetch("/api/integrations/github/status");
    if (!response.ok) return null;
    const body: GitHubStatus = await response.json();
    setStatus(body);
    return body;
  }, []);

  useEffect(() => {
    if (authStatus !== "ready") return;
    let cancelled = false;

    // Fetching from the backend (an external system) on mount; the setState
    // lands in a promise callback, not synchronously in the effect body.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load()
      .catch(() => null)
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [authStatus, load]);

  useEffect(() => {
    // Syncing from the URL (an external system) after mount; deliberately not a
    // lazy initializer, so the prerendered HTML and first client render match.
    const value = new URLSearchParams(window.location.search).get("github");
    if (!value) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOutcome(value);
    // Strip the parameter once read, so a refresh does not replay a stale
    // "connected" notice. replaceState avoids a re-render/navigation.
    window.history.replaceState(null, "", "/settings");
  }, []);

  async function connect() {
    setPending(true);
    setErrorMessage(null);
    try {
      const response = await apiFetch("/api/integrations/github/authorize");
      if (!response.ok) {
        setErrorMessage(
          response.status === 503
            ? "This server has no GitHub OAuth App configured."
            : "Could not start the GitHub connection.",
        );
        return;
      }
      const body: { url: string } = await response.json();
      // Full navigation: the user has to approve on github.com.
      window.location.assign(body.url);
    } catch {
      setErrorMessage("Could not start the GitHub connection.");
    } finally {
      setPending(false);
    }
  }

  async function disconnect() {
    setPending(true);
    setErrorMessage(null);
    try {
      const response = await apiFetch("/api/integrations/github/connection", {
        method: "DELETE",
      });
      if (!response.ok && response.status !== 409) {
        setErrorMessage("Could not disconnect GitHub.");
        return;
      }
      await load();
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="settings-section">
      <h2 className="settings-section-title">GitHub</h2>
      <p className="settings-section-hint">
        Read issues from your repositories and file new ones from inside Ember. Ember never edits
        or closes an existing issue.
      </p>

      {notice && (
        <p className={notice.tone === "ok" ? "github-notice" : "form-error form-error--summary"}>
          {notice.text}
        </p>
      )}
      {errorMessage && <p className="form-error form-error--summary">{errorMessage}</p>}

      {loading ? (
        <Loader2 className="github-spinner" size={18} />
      ) : !status?.configured ? (
        <p className="settings-section-hint">
          No GitHub OAuth App is configured on this server. See{" "}
          <code>docs/rfc/github-integration.md</code>.
        </p>
      ) : status.connected ? (
        <div className="github-connection">
          {status.avatar_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              className="github-avatar"
              src={status.avatar_url}
              alt={status.login ?? "GitHub account"}
              width={32}
              height={32}
            />
          )}
          <div className="github-connection-info">
            <strong>{status.login}</strong>
            <span>{status.scopes}</span>
          </div>
          <button
            type="button"
            className="github-secondary-button"
            disabled={pending}
            onClick={disconnect}
          >
            Disconnect
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="github-primary-button"
          disabled={pending}
          onClick={connect}
        >
          <GitBranch size={16} />
          Connect GitHub
        </button>
      )}
    </section>
  );
}
