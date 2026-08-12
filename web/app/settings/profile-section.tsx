"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Upload } from "lucide-react";

import { apiFetch, useRequireAuth } from "@/lib/auth-client";
import type { CurrentUser } from "@/lib/types";

/** Mirrors MAX_IMAGE_BYTES in core/ember/images.py, so an oversized file is
 * refused before it spends the user's upload bandwidth. */
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

function initialForName(name: string): string {
  return name.trim().charAt(0).toUpperCase() || "?";
}

export function ProfileSection() {
  const { status: authStatus } = useRequireAuth();
  const fileInput = useRef<HTMLInputElement>(null);

  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const response = await apiFetch("/api/users/me");
    if (response.ok) setUser(await response.json());
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

  async function upload(file: File) {
    if (!file.type.startsWith("image/")) {
      setErrorMessage("Choose an image file.");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setErrorMessage("Profile photo must be 10 MB or smaller.");
      return;
    }

    setPending(true);
    setErrorMessage(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await apiFetch("/api/users/me/avatar", { method: "POST", body });
      if (!response.ok) {
        setErrorMessage(
          response.status === 503
            ? "Image uploads are not configured on this server."
            : "Could not upload your photo. Try again.",
        );
        return;
      }
      setUser(await response.json());
    } catch {
      setErrorMessage("Could not upload your photo. Try again.");
    } finally {
      setPending(false);
    }
  }

  async function remove() {
    setPending(true);
    setErrorMessage(null);
    try {
      const response = await apiFetch("/api/users/me/avatar", { method: "DELETE" });
      if (!response.ok) {
        setErrorMessage("Could not remove your photo. Try again.");
        return;
      }
      setUser(await response.json());
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="settings-section">
      <h2 className="settings-section-title">Profile photo</h2>
      <p className="settings-section-hint">
        Shown next to your name on board cards and anywhere your account appears.
      </p>

      {errorMessage && <p className="form-error form-error--summary">{errorMessage}</p>}

      {loading || !user ? (
        <Loader2 className="github-spinner" size={18} />
      ) : (
        <div className="profile-photo-row">
          <span className="profile-photo-preview">
            {user.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- Cloudinary serves this pre-cropped.
              <img src={user.avatar_url} alt="" width={72} height={72} />
            ) : (
              initialForName(user.display_name)
            )}
          </span>

          <div className="profile-photo-info">
            <strong>{user.display_name}</strong>
            <span>{user.email}</span>
          </div>

          <input
            ref={fileInput}
            className="profile-photo-input"
            type="file"
            accept="image/*"
            onChange={(event) => {
              const file = event.target.files?.[0];
              // Cleared so choosing the same file twice in a row still fires.
              event.target.value = "";
              if (file) void upload(file);
            }}
          />
          <button
            type="button"
            className="github-primary-button"
            disabled={pending}
            onClick={() => fileInput.current?.click()}
          >
            <Upload size={16} />
            {user.avatar_url ? "Change photo" : "Upload photo"}
          </button>
          {user.avatar_url && (
            <button
              type="button"
              className="github-secondary-button"
              disabled={pending}
              onClick={remove}
            >
              Remove
            </button>
          )}
        </div>
      )}
    </section>
  );
}
