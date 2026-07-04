"use client";

import { useRouter } from "next/navigation";

type MailNavProps = {
  workspaceId: string;
  active: "domains" | "accounts";
};

/** Segmented tab switcher between the Mail sub-pages, reusing the same
 * toggle look as the week/day switch in the calendar header. */
export function MailNav({ workspaceId, active }: MailNavProps) {
  const router = useRouter();

  return (
    <div className="mail-subnav">
      <div className="week-view-toggle">
        <button
          type="button"
          className={`week-view-toggle-button${active === "domains" ? " week-view-toggle-button--active" : ""}`}
          onClick={() => router.push(`/workspace/${workspaceId}/mail/domains`)}
        >
          Domains
        </button>
        <button
          type="button"
          className={`week-view-toggle-button${active === "accounts" ? " week-view-toggle-button--active" : ""}`}
          onClick={() => router.push(`/workspace/${workspaceId}/mail/accounts`)}
        >
          Accounts
        </button>
      </div>
    </div>
  );
}
