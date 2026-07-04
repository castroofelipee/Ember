"use client";

import { useState } from "react";
import { Check, Copy, UserPlus } from "lucide-react";

import { useRequireAuth } from "@/lib/auth-client";

type Invite = { link: string; expiresAt: string };

function formatExpiry(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * Generates a single-use signup invite link the user can share so a new member
 * can create an account (registration is invite-only). The raw code is only
 * returned once at creation, so the link is shown until a new one is made.
 */
export function InviteMembers() {
  const { status: authStatus, accessToken } = useRequireAuth();
  const [invite, setInvite] = useState<Invite | null>(null);
  const [creating, setCreating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function createInvite() {
    if (authStatus !== "ready") return;
    setCreating(true);
    setError(null);
    setCopied(false);
    try {
      const response = await fetch("/api/invites", {
        method: "POST",
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (response.status === 201) {
        const body = await response.json();
        const link = `${window.location.origin}/signup?invite=${encodeURIComponent(body.code)}`;
        setInvite({ link, expiresAt: body.expires_at });
        return;
      }
      setError("Could not create an invite. Please try again.");
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setCreating(false);
    }
  }

  async function copyLink() {
    if (!invite) return;
    try {
      await navigator.clipboard.writeText(invite.link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy the link. Copy it manually.");
    }
  }

  return (
    <section className="settings-section">
      <h2 className="settings-section-title">Invite members</h2>
      <p className="settings-section-hint">
        Share a link so a new member can create their account. Each link works once and expires.
      </p>

      {invite && (
        <div className="invite-result">
          <div className="invite-link-row">
            <input className="event-dialog-input" value={invite.link} readOnly />
            <button type="button" className="event-dialog-add" onClick={copyLink}>
              {copied ? <Check size={16} /> : <Copy size={16} />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="settings-section-hint">Expires {formatExpiry(invite.expiresAt)}.</p>
        </div>
      )}

      {error && <p className="form-error form-error--summary">{error}</p>}

      <button
        type="button"
        className="button-primary invite-create-button"
        onClick={createInvite}
        disabled={creating || authStatus !== "ready"}
      >
        <UserPlus size={16} />
        {creating ? "Creating…" : invite ? "Create another link" : "Create invite link"}
      </button>
    </section>
  );
}
