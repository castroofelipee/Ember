"use client";

import { useEffect, useState } from "react";

import { apiFetch, useRequireAuth } from "@/lib/auth-client";
import type { Workspace } from "@/lib/types";
import { AppHeader } from "@/app/workspace/[workspaceId]/app-header";

export function SettingsHeader() {
  const { status } = useRequireAuth();
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "ready") return;
    let cancelled = false;

    apiFetch("/api/workspaces").then(async (response) => {
      if (cancelled || !response.ok) return;
      const workspaces: Workspace[] = await response.json();
      setWorkspaceId(workspaces[0]?.id ?? null);
    });

    return () => {
      cancelled = true;
    };
  }, [status]);

  if (!workspaceId) return null;
  return <AppHeader workspaceId={workspaceId} />;
}
