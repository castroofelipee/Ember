import type { ReactNode } from "react";

import { WorkspaceReminders } from "./workspace-reminders";

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <WorkspaceReminders />
    </>
  );
}
