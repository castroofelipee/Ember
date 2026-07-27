"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { apiFetch, useRequireAuth } from "@/lib/auth-client";
import type { Workspace } from "@/lib/types";

import { OnboardingTour } from "./onboarding-tour";
import { WorkspacePicker } from "./workspace-picker";

type Status = "loading" | "onboarding" | "picker";

export function CalendarsHub() {
  const router = useRouter();
  const { status: authStatus } = useRequireAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);

  useEffect(() => {
    if (authStatus !== "ready") return;
    let cancelled = false;

    apiFetch("/api/workspaces").then(async (response) => {
      if (cancelled || !response.ok) return;
      const body: Workspace[] = await response.json();
      if (cancelled) return;
      setWorkspaces(body);
      setStatus(body.length === 0 ? "onboarding" : "picker");
    });

    return () => {
      cancelled = true;
    };
  }, [authStatus]);

  if (authStatus !== "ready" || status === "loading") {
    return (
      <div className="hub-page">
        <div className="hub-header">
          <h1 className="auth-title">Ember</h1>
        </div>
        <p className="auth-subtitle">Loading…</p>
      </div>
    );
  }

  if (status === "onboarding") {
    return (
      <div className="hub-page">
        <div className="hub-header">
          <h1 className="auth-title">Ember</h1>
          <p className="auth-subtitle">Let&apos;s set up your first workspace</p>
        </div>
        <div className="hub-content">
          <OnboardingTour
            onDone={(workspaceId) => router.push(`/workspace/${workspaceId}`)}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="hub-page">
      <div className="hub-header">
        <h1 className="auth-title">Ember</h1>
        <p className="auth-subtitle">Choose a workspace</p>
      </div>
      <div className="hub-content hub-content--wide">
        <WorkspacePicker
          workspaces={workspaces}
          onCreated={(workspace) => setWorkspaces((prev) => [...prev, workspace])}
        />
      </div>
    </div>
  );
}
