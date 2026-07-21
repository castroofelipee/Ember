"use client";

import { useEffect, useState } from "react";

import { useRequireAuth } from "@/lib/auth-client";
import type { Workspace } from "@/lib/types";
import { AppHeader } from "@/app/workspace/[workspaceId]/app-header";

export function SettingsHeader() {
  const { status, accessToken } = useRequireAuth();
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "ready") return;
    let cancelled = false;

    fetch("/api/workspaces", {
      headers: { Authorization: `Bearer ${accessToken}` },
    }).then(async (response) => {
      if (cancelled || !response.ok) return;
      const workspaces: Workspace[] = await response.json();
      setWorkspaceId(workspaces[0]?.id ?? null);
    });

    return () => {
      cancelled = true;
    };
  }, [accessToken, status]);

  if (!workspaceId) return null;
  return <AppHeader workspaceId={workspaceId} />;
}
