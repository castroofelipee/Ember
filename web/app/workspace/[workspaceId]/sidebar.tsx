"use client";

import { useState } from "react";
import {
  Check,
  ChevronDown,
  Plus,
  Search,
} from "lucide-react";

import type { Calendar } from "@/lib/types";

import { MiniCalendar } from "./mini-calendar";

type SidebarProps = {
  calendars: Calendar[];
  selectedDate: Date;
  onSelectDay: (date: Date) => void;
  onCreateEvent: () => void;
  open: boolean;
};

export function Sidebar({
  calendars,
  selectedDate,
  onSelectDay,
  onCreateEvent,
  open,
}: SidebarProps) {
  return (
    <aside className={`sidebar${open ? "" : " sidebar--collapsed"}`}>
      <button type="button" className="sidebar-create-button" onClick={onCreateEvent}>
        <Plus size={18} />
        {open && <span>Create event</span>}
      </button>

      {open && (
        <>
          <MiniCalendar selectedDate={selectedDate} onSelectDay={onSelectDay} />

          <div className="sidebar-search">
            <Search size={16} />
            <input
              type="search"
              className="sidebar-search-input"
              placeholder="Search for people"
            />
          </div>

          <MyCalendars calendars={calendars} />
        </>
      )}

    </aside>
  );
}

function MyCalendars({ calendars }: { calendars: Calendar[] }) {
  const [expanded, setExpanded] = useState(true);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const toggle = (id: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

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
              const checked = !hidden.has(calendar.id);
              return (
                <li key={calendar.id}>
                  <button
                    type="button"
                    className="sidebar-calendar-item"
                    role="checkbox"
                    aria-checked={checked}
                    onClick={() => toggle(calendar.id)}
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
