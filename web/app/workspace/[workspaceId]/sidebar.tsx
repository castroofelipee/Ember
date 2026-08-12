"use client";

import { useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  Plus,
  Search,
  X,
} from "lucide-react";

import type { Calendar } from "@/lib/types";
import { EXPANDED_LAYOUT, useMediaQuery } from "@/lib/use-media-query";

import { MiniCalendar } from "./mini-calendar";

type SidebarProps = {
  calendars: Calendar[];
  hiddenCalendarIds: Set<string>;
  selectedDate: Date;
  onSelectDay: (date: Date) => void;
  onCreateEvent: () => void;
  onToggleCalendar: (id: string) => void;
  open: boolean;
  onClose: () => void;
};

export function Sidebar({
  calendars,
  hiddenCalendarIds,
  selectedDate,
  onSelectDay,
  onCreateEvent,
  onToggleCalendar,
  open,
  onClose,
}: SidebarProps) {
  const isExpanded = useMediaQuery(EXPANDED_LAYOUT);
  const isDrawer = !isExpanded;

  useEffect(() => {
    if (!isDrawer || !open) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isDrawer, open, onClose]);

  return (
    <>
      {isDrawer && open && (
        <div className="sidebar-scrim" onClick={onClose} aria-hidden="true" />
      )}

      <aside
        className={`sidebar${open ? "" : " sidebar--collapsed"}`}
        aria-label="Calendar controls"
        inert={isDrawer && !open}
      >
        <div className="sidebar-drawer-top">
          <button
            type="button"
            className="sidebar-create-button"
            onClick={() => {
              onCreateEvent();
              if (isDrawer) onClose();
            }}
          >
            <Plus size={18} />
            {open && <span>Create event</span>}
          </button>

          {isDrawer && (
            <button
              type="button"
              className="sidebar-drawer-close"
              aria-label="Close calendar controls"
              onClick={onClose}
            >
              <X size={20} />
            </button>
          )}
        </div>

        {open && (
          <>
            <MiniCalendar
              selectedDate={selectedDate}
              onSelectDay={(date) => {
                onSelectDay(date);
                if (isDrawer) onClose();
              }}
            />

            <div className="sidebar-search">
              <Search size={16} />
              <input
                type="search"
                className="sidebar-search-input"
                placeholder="Search for people"
              />
            </div>

            <MyCalendars
              calendars={calendars}
              hiddenCalendarIds={hiddenCalendarIds}
              onToggleCalendar={onToggleCalendar}
            />
          </>
        )}
      </aside>
    </>
  );
}

function MyCalendars({
  calendars,
  hiddenCalendarIds,
  onToggleCalendar,
}: {
  calendars: Calendar[];
  hiddenCalendarIds: Set<string>;
  onToggleCalendar: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="sidebar-section">
      <button
        type="button"
        className="sidebar-section-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span>My calendars</span>
        <ChevronDown
          size={16}
          className={`sidebar-chevron${expanded ? "" : " sidebar-chevron--collapsed"}`}
        />
      </button>

      {expanded && (
        <ul className="sidebar-calendar-list">
          {calendars.length === 0 ? (
            <li className="sidebar-calendar-empty">No calendars yet.</li>
          ) : (
            calendars.map((calendar) => {
              const checked = !hiddenCalendarIds.has(calendar.id);
              return (
                <li key={calendar.id}>
                  <button
                    type="button"
                    className="sidebar-calendar-item"
                    role="checkbox"
                    aria-checked={checked}
                    onClick={() => onToggleCalendar(calendar.id)}
                  >
                    <span
                      className={`sidebar-check${checked ? " sidebar-check--on" : ""}`}
                      style={
                        checked
                          ? { background: calendar.color, borderColor: calendar.color }
                          : { borderColor: calendar.color }
                      }
                    >
                      {checked && <Check size={12} strokeWidth={3} />}
                    </span>
                    <span className="sidebar-calendar-name">{calendar.name}</span>
                  </button>
                </li>
              );
            })
          )}
        </ul>
      )}
    </div>
  );
}
