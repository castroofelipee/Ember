"use client";

import { usePathname, useParams } from "next/navigation";

import { AppHeader } from "./app-header";

export function WorkspaceHeader() {
  const pathname = usePathname();
  const { workspaceId } = useParams<{ workspaceId: string }>();

  // The calendar owns its header because its menu controls the calendar sidebar.
  if (pathname === `/workspace/${workspaceId}`) return null;

  return <AppHeader workspaceId={workspaceId} />;
}
