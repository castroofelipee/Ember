"use client";

import { useParams } from "next/navigation";

import { useRequireAuth } from "@/lib/auth-client";

import { EventReminders } from "./event-reminders";

export function WorkspaceReminders() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { status } = useRequireAuth();

  if (status !== "ready") return null;

  return <EventReminders workspaceId={workspaceId} />;
}
