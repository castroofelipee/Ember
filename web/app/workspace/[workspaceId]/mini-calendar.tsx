"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

const WEEKDAYS = ["S", "M", "T", "W", "T", "F", "S"];
const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

type MiniCalendarProps = {
  /** The day currently focused in the main view; highlighted here. */
  selectedDate: Date;
  onSelectDay: (date: Date) => void;
};

/**
 * Month view with prev/next navigation. Today is ringed, the focused day is
 * filled. Clicking a day hands it back so the main view can jump to it. The
 * shown month follows the selected day when it changes elsewhere (e.g. paging
 * the week in the main view).
 */
export function MiniCalendar({ selectedDate, onSelectDay }: MiniCalendarProps) {
  const today = new Date();
  const [viewMonth, setViewMonth] = useState(
    () => new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1),
  );

  // Follow the selected day's month when it changes elsewhere (e.g. paging the
  // week in the main view), without clobbering months the user browses here by
  // hand. Adjusting state during render is React's supported pattern for this.
  const selectedKey = `${selectedDate.getFullYear()}-${selectedDate.getMonth()}`;
  const [prevKey, setPrevKey] = useState(selectedKey);
  if (selectedKey !== prevKey) {
    setPrevKey(selectedKey);
    setViewMonth(new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1));
  }

  const year = viewMonth.getFullYear();
  const month = viewMonth.getMonth();
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells: (number | null)[] = [];
  for (let i = 0; i < firstWeekday; i += 1) cells.push(null);
  for (let day = 1; day <= daysInMonth; day += 1) cells.push(day);

  const shiftMonth = (delta: number) => setViewMonth(new Date(year, month + delta, 1));

  return (
    <div className="mini-calendar">
      <div className="mini-calendar-head">
        <button
          type="button"
          className="mini-calendar-nav"
          aria-label="Previous month"
          onClick={() => shiftMonth(-1)}
        >
          <ChevronLeft size={14} />
        </button>
        <span className="mini-calendar-title">
          {MONTHS[month]} {year}
        </span>
        <button
          type="button"
          className="mini-calendar-nav"
          aria-label="Next month"
          onClick={() => shiftMonth(1)}
        >
          <ChevronRight size={14} />
        </button>
      </div>
      <div className="mini-calendar-grid">
        {WEEKDAYS.map((label, index) => (
          <span className="mini-calendar-weekday" key={`wd-${index}`}>
            {label}
          </span>
        ))}
        {cells.map((day, index) => {
          if (day === null) {
            return (
              <span className="mini-calendar-day mini-calendar-day--empty" key={`e-${index}`} />
            );
          }
          const date = new Date(year, month, day);
          const classes = ["mini-calendar-day"];
          if (isSameDay(date, today)) classes.push("mini-calendar-day--today");
          if (isSameDay(date, selectedDate)) classes.push("mini-calendar-day--selected");
          return (
            <button
              type="button"
              className={classes.join(" ")}
              key={`d-${day}`}
              onClick={() => onSelectDay(date)}
            >
              {day}
            </button>
          );
        })}
      </div>
    </div>
  );
}
