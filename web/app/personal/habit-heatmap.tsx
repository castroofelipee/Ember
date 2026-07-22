"use client";
// GitHub-style contribution grid in Ember's violet ramp. Reused for both the
// aggregate momentum grid and each habit's compact strip — the caller supplies
// `level(iso)` returning -1 (not applicable, faint) or 0..4 (heat).
import { useMemo } from "react";
import { heatGrid, monthLabels, todayISO } from "./habit-utils";

type HabitHeatmapProps = {
  weeks: number;
  level: (iso: string) => number;
  /** Native-tooltip text per day. */
  label?: (iso: string) => string;
  weekStartsOn?: number;
  showMonths?: boolean;
};

export function HabitHeatmap({ weeks, level, label, weekStartsOn = 1, showMonths = true }: HabitHeatmapProps) {
  const columns = useMemo(() => heatGrid(weeks, weekStartsOn), [weeks, weekStartsOn]);
  const months = useMemo(() => (showMonths ? monthLabels(columns) : []), [columns, showMonths]);
  const today = todayISO();

  return (
    <div className="habit-heatmap" style={{ ["--cols" as string]: columns.length }}>
      {showMonths && (
        <div className="habit-heatmap-months" aria-hidden="true">
          {months.map((month, index) => (
            <span key={index}>{month}</span>
          ))}
        </div>
      )}
      <div className="habit-heatmap-grid" role="img" aria-label="Habit completion history">
        {columns.map((column, index) => (
          <div className="habit-heatmap-col" key={index}>
            {column.map((iso) => {
              const value = level(iso);
              const future = iso > today;
              return (
                <span
                  key={iso}
                  className={`habit-heat-cell${future ? " is-future" : ""}${value < 0 ? " is-off" : ""}`}
                  data-level={value < 0 ? 0 : value}
                  title={label ? label(iso) : iso}
                />
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
