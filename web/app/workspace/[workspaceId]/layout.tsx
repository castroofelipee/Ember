import type { ReactNode } from "react";

import { WorkspaceReminders } from "./workspace-reminders";
import { WorkspaceHeader } from "./workspace-header";

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <div className="workspace-route-layout">
      <WorkspaceHeader />
      <div className="workspace-route-content">{children}</div>
      <WorkspaceReminders />
    </div>
  );
}
