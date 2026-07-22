"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { CalendarDays, Columns3, Grid3X3, LayoutGrid, Mail, Menu, Settings, Sparkles } from "lucide-react";

type AppHeaderProps = {
  workspaceId: string;
  sidebarOpen?: boolean;
  onToggleSidebar?: () => void;
};

export function AppHeader({ workspaceId, sidebarOpen, onToggleSidebar }: AppHeaderProps) {
  const router = useRouter();
  const pathname = usePathname();
  const launcherRef = useRef<HTMLDivElement>(null);
  const [launcherOpen, setLauncherOpen] = useState(false);

  useEffect(() => {
    if (!launcherOpen) return;

    function closeLauncher(event: PointerEvent) {
      if (!launcherRef.current?.contains(event.target as Node)) setLauncherOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setLauncherOpen(false);
    }

    window.addEventListener("pointerdown", closeLauncher);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", closeLauncher);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [launcherOpen]);

  const apps = [
    { label: "Personal", icon: Sparkles, href: "/personal", active: pathname === "/personal" },
    { label: "Workspaces", icon: LayoutGrid, href: "/calendars", active: pathname === "/calendars" },
    {
      label: "Calendar",
      icon: CalendarDays,
      href: `/workspace/${workspaceId}`,
      active: pathname === `/workspace/${workspaceId}`,
    },
    {
      label: "Mail",
      icon: Mail,
      href: `/workspace/${workspaceId}/mail`,
      active: pathname.startsWith(`/workspace/${workspaceId}/mail`),
    },
    {
      label: "Boards",
      icon: Columns3,
      href: `/workspace/${workspaceId}/boards`,
      active: pathname.startsWith(`/workspace/${workspaceId}/boards`),
    },
  ];

  return (
    <header className="app-header">
      <div className="app-header-leading">
        {onToggleSidebar && (
          <button
            type="button"
            className="app-header-icon-button"
            aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
            aria-expanded={sidebarOpen}
            onClick={onToggleSidebar}
          >
            <Menu size={22} />
          </button>
        )}
        <button
          type="button"
          className="app-header-brand"
          onClick={() => router.push(`/workspace/${workspaceId}`)}
        >
          <Image src="/logo.png" alt="" width={40} height={40} className="app-header-logo" priority />
          <span>Ember Calendar</span>
        </button>
      </div>

      <div className="app-header-actions">
        <button
          type="button"
          className={`app-header-icon-button${pathname === "/settings" ? " app-header-icon-button--active" : ""}`}
          aria-label="Settings"
          title="Settings"
          onClick={() => router.push("/settings")}
        >
          <Settings size={21} />
        </button>

        <div className="app-launcher" ref={launcherRef}>
          <button
            type="button"
            className={`app-header-icon-button${launcherOpen ? " app-header-icon-button--active" : ""}`}
            aria-label="Ember apps"
            aria-haspopup="menu"
            aria-expanded={launcherOpen}
            title="Ember apps"
            onClick={() => setLauncherOpen((value) => !value)}
          >
            <Grid3X3 size={21} />
          </button>

          {launcherOpen && (
            <div className="app-launcher-menu" role="menu">
              {apps.map((app) => {
                const Icon = app.icon;
                return (
                  <button
                    type="button"
                    className={`app-launcher-item${app.active ? " app-launcher-item--active" : ""}`}
                    role="menuitem"
                    key={app.label}
                    onClick={() => {
                      setLauncherOpen(false);
                      router.push(app.href);
                    }}
                  >
                    <span className="app-launcher-item-icon"><Icon size={24} /></span>
                    <span>{app.label}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
