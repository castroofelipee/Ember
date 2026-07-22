"use client";
import { useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  Bike, BookOpen, Brain, CalendarDays, Check, Coffee, Droplets, Dumbbell, Flame, Footprints,
  Heart, Languages, Moon, Music, PenLine, Pencil, Plus, Salad, Sprout, Sun, Target, Trash2, Wallet,
  type LucideIcon,
} from "lucide-react";
import { EVENT_COLORS, type HabitData, type HabitSchedule, type PersonalItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { HabitHeatmap } from "./habit-heatmap";
import {
  completionRate,
  computeStreak,
  daysAgoISO,
  habitDates,
  heatLevel,
  isScheduled,
  longestStreak,
  normalizeSchedule,
  todayISO,
  weekProgress,
} from "./habit-utils";

const AGGREGATE_WEEKS = 53;
const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
// Reuse the calendar's named palette so habits feel consistent with events.
const HABIT_COLORS: string[] = EVENT_COLORS.map((color) => color.value).filter((value) => value !== null) as string[];
const DEFAULT_COLOR = "#a78bfa";

/** Translucent tint of a hex, matching the calendar's frosted event fills. */
function tint(hex: string, alpha: number): string {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// Minimalist line icons (lucide, monochrome stroke) — no emoji, no fill.
const HABIT_ICONS: { name: string; Icon: LucideIcon }[] = [
  { name: "dumbbell", Icon: Dumbbell }, { name: "run", Icon: Footprints }, { name: "bike", Icon: Bike },
  { name: "book", Icon: BookOpen }, { name: "meditate", Icon: Brain }, { name: "water", Icon: Droplets },
  { name: "grow", Icon: Sprout }, { name: "target", Icon: Target }, { name: "write", Icon: PenLine },
  { name: "sleep", Icon: Moon }, { name: "wake", Icon: Sun }, { name: "eat", Icon: Salad },
  { name: "coffee", Icon: Coffee }, { name: "music", Icon: Music }, { name: "study", Icon: Languages },
  { name: "health", Icon: Heart }, { name: "money", Icon: Wallet },
];
const HABIT_ICON_MAP: Record<string, LucideIcon> = Object.fromEntries(HABIT_ICONS.map((entry) => [entry.name, entry.Icon]));
const DEFAULT_HABIT_ICON = Target;

function HabitIcon({ name, size = 18 }: { name?: string; size?: number }) {
  const Icon = (name && HABIT_ICON_MAP[name]) || DEFAULT_HABIT_ICON;
  return <Icon size={size} />;
}

type HabitTrackerProps = {
  habits: PersonalItem[];
  onCreate: (title: string, data: HabitData) => Promise<void>;
  onUpdate: (item: PersonalItem, data: Record<string, unknown>) => void;
  onToggle: (item: PersonalItem, iso: string) => void;
  onRemove: (item: PersonalItem) => void;
};

type FormState = {
  name: string;
  mode: "daily" | "weekdays";
  weekdays: number[];
  icon: string;
  color: string;
  description: string;
};

const EMPTY_FORM: FormState = { name: "", mode: "daily", weekdays: [1, 2, 3, 4, 5], icon: "", color: DEFAULT_COLOR, description: "" };

function scheduleLabel(schedule: HabitSchedule): string {
  if (schedule === "daily") return "Every day";
  if (schedule.length === 7) return "Every day";
  return schedule.map((day) => WEEKDAY_LABELS[day]).join(" · ");
}

export function HabitTracker({ habits, onCreate, onUpdate, onToggle, onRemove }: HabitTrackerProps) {
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<PersonalItem | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const today = todayISO();

  const scheduledToday = habits.filter((habit) => isScheduled(normalizeSchedule(habit.data), today));
  const restToday = habits.filter((habit) => !isScheduled(normalizeSchedule(habit.data), today));

  // Aggregate: per day, share of scheduled habits completed → heat level.
  const aggregateLevel = useMemo(() => {
    const prepared = habits.map((habit) => ({
      schedule: normalizeSchedule(habit.data),
      done: new Set(habitDates(habit.data)),
    }));
    return (iso: string): number => {
      let scheduled = 0;
      let completed = 0;
      for (const habit of prepared) {
        if (isScheduled(habit.schedule, iso)) {
          scheduled += 1;
          if (habit.done.has(iso)) completed += 1;
        }
      }
      if (scheduled === 0) return -1;
      return heatLevel(completed / scheduled);
    };
  }, [habits]);

  const aggregateLabel = useMemo(() => {
    const prepared = habits.map((habit) => ({
      schedule: normalizeSchedule(habit.data),
      done: new Set(habitDates(habit.data)),
    }));
    return (iso: string): string => {
      let scheduled = 0;
      let completed = 0;
      for (const habit of prepared) {
        if (isScheduled(habit.schedule, iso)) {
          scheduled += 1;
          if (habit.done.has(iso)) completed += 1;
        }
      }
      if (scheduled === 0) return `${iso} · rest day`;
      return `${iso} · ${completed}/${scheduled} habits`;
    };
  }, [habits]);

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setDrawerOpen(true);
  }

  function openEdit(habit: PersonalItem) {
    const schedule = normalizeSchedule(habit.data);
    setEditing(habit);
    setForm({
      name: habit.title,
      mode: schedule === "daily" ? "daily" : "weekdays",
      weekdays: schedule === "daily" ? EMPTY_FORM.weekdays : schedule,
      icon: typeof habit.data.icon === "string" ? habit.data.icon : "",
      color: typeof habit.data.color === "string" ? habit.data.color : DEFAULT_COLOR,
      description: typeof habit.data.description === "string" ? habit.data.description : "",
    });
    setDrawerOpen(true);
  }

  function toggleWeekday(day: number) {
    setForm((current) => ({
      ...current,
      weekdays: current.weekdays.includes(day)
        ? current.weekdays.filter((value) => value !== day)
        : [...current.weekdays, day].sort((a, b) => a - b),
    }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.name.trim()) return;
    if (form.mode === "weekdays" && form.weekdays.length === 0) return;
    const schedule: HabitSchedule = form.mode === "daily" ? "daily" : [...form.weekdays].sort((a, b) => a - b);
    const base: HabitData = {
      dates: editing ? habitDates(editing.data) : [],
      schedule,
      ...(form.icon ? { icon: form.icon } : {}),
      ...(form.color && form.color !== DEFAULT_COLOR ? { color: form.color } : {}),
      ...(form.description.trim() ? { description: form.description.trim() } : {}),
    };
    if (editing) onUpdate(editing, { ...editing.data, ...base });
    else await onCreate(form.name.trim(), base);
    setDrawerOpen(false);
  }

  return (
    <div className="habits">
      <div className="habits-toolbar">
        <div>
          <strong>Your habits</strong>
          <span>Small actions, tracked daily. Keep the streak alive.</span>
        </div>
        <button onClick={openCreate}>
          <Plus size={17} />
          New habit
        </button>
      </div>

      {habits.length === 0 ? (
        <button className="habits-empty" onClick={openCreate}>
          <Flame size={26} />
          <strong>Start your first habit</strong>
          <span>Define what you want to do, then check it off each day.</span>
        </button>
      ) : (
        <>
          <section className="habits-today">
            <header>
              <h2>Today</h2>
              <span>
                {scheduledToday.filter((habit) => habitDates(habit.data).includes(today)).length}/{scheduledToday.length} done
              </span>
            </header>
            <div className="habit-card-grid">
              {scheduledToday.map((habit) => (
                <HabitCard key={habit.id} habit={habit} today={today} onToggle={onToggle} onEdit={openEdit} onRemove={onRemove} onOpenCalendar={() => router.push("/calendars")} />
              ))}
              {scheduledToday.length === 0 && <p className="habits-restday">Nothing scheduled today — enjoy the rest. 🌙</p>}
            </div>
            {restToday.length > 0 && (
              <details className="habits-rest">
                <summary>Not scheduled today ({restToday.length})</summary>
                <div className="habit-card-grid">
                  {restToday.map((habit) => (
                    <HabitCard key={habit.id} habit={habit} today={today} muted onToggle={onToggle} onEdit={openEdit} onRemove={onRemove} onOpenCalendar={() => router.push("/calendars")} />
                  ))}
                </div>
              </details>
            )}
          </section>

          <section className="habits-momentum">
            <header>
              <h2>Momentum</h2>
              <span>Last year across all habits</span>
            </header>
            <div className="habit-aggregate">
              <HabitHeatmap weeks={AGGREGATE_WEEKS} level={aggregateLevel} label={aggregateLabel} />
              <HeatLegend />
            </div>
            <div className="habit-strip-list">
              {habits.map((habit) => (
                <HabitStatRow key={habit.id} habit={habit} />
              ))}
            </div>
          </section>
        </>
      )}

      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-md">
          <SheetHeader className="border-b">
            <SheetTitle>{editing ? "Edit habit" : "Create a habit"}</SheetTitle>
            <SheetDescription>Define what you want to do and when.</SheetDescription>
          </SheetHeader>

          <form id="habit-form" onSubmit={submit} className="flex flex-1 flex-col gap-5 overflow-y-auto p-4">
            <div className="grid gap-2">
              <Label htmlFor="habit-name">Habit name</Label>
              <Input id="habit-name" autoFocus value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="e.g. Read 20 minutes" maxLength={240} />
            </div>

            <div className="grid gap-2">
              <Label>Schedule</Label>
              <div className="flex gap-2">
                <Button type="button" size="sm" variant={form.mode === "daily" ? "default" : "outline"} className="flex-1" onClick={() => setForm({ ...form, mode: "daily" })}>
                  Every day
                </Button>
                <Button type="button" size="sm" variant={form.mode === "weekdays" ? "default" : "outline"} className="flex-1" onClick={() => setForm({ ...form, mode: "weekdays" })}>
                  Specific weekdays
                </Button>
              </div>
              {form.mode === "weekdays" && (
                <div className="flex gap-1.5">
                  {WEEKDAY_LABELS.map((label, day) => (
                    <Button key={day} type="button" size="icon-sm" variant={form.weekdays.includes(day) ? "default" : "outline"} onClick={() => toggleWeekday(day)}>
                      {label[0]}
                    </Button>
                  ))}
                </div>
              )}
            </div>

            <div className="grid gap-2">
              <Label>Icon</Label>
              <div className="flex flex-wrap gap-1.5">
                {HABIT_ICONS.map(({ name, Icon }) => (
                  <Button key={name} type="button" size="icon" variant={form.icon === name ? "default" : "outline"} aria-label={name} onClick={() => setForm({ ...form, icon: name })}>
                    <Icon />
                  </Button>
                ))}
              </div>
            </div>

            <div className="grid gap-2">
              <Label>Accent</Label>
              <div className="flex flex-wrap gap-2">
                {HABIT_COLORS.map((color) => (
                  <button type="button" key={color} className={`size-7 rounded-full border backdrop-blur-sm transition ${form.color === color ? "ring-2 ring-foreground ring-offset-2 ring-offset-background" : ""}`} style={{ background: tint(color, 0.32), borderColor: color }} aria-label={color} onClick={() => setForm({ ...form, color })} />
                ))}
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="habit-note">Motivation note (optional)</Label>
              <Input id="habit-note" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Why does this matter to you?" maxLength={240} />
            </div>
          </form>

          <SheetFooter className="flex-row justify-end border-t">
            <Button type="button" variant="ghost" onClick={() => setDrawerOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" form="habit-form" disabled={!form.name.trim() || (form.mode === "weekdays" && form.weekdays.length === 0)}>
              {editing ? "Save changes" : "Create habit"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  );
}

type HabitCardProps = {
  habit: PersonalItem;
  today: string;
  muted?: boolean;
  onToggle: (item: PersonalItem, iso: string) => void;
  onEdit: (item: PersonalItem) => void;
  onRemove: (item: PersonalItem) => void;
  onOpenCalendar: () => void;
};

function HabitCard({ habit, today, muted, onToggle, onEdit, onRemove, onOpenCalendar }: HabitCardProps) {
  const schedule = normalizeSchedule(habit.data);
  const dates = habitDates(habit.data);
  const accent = typeof habit.data.color === "string" ? habit.data.color : DEFAULT_COLOR;
  const icon = typeof habit.data.icon === "string" ? habit.data.icon : "";
  const description = typeof habit.data.description === "string" ? habit.data.description : "";
  const done = dates.includes(today);
  const streak = computeStreak(dates, schedule);
  const week = weekProgress(dates, schedule);

  return (
    <article className={`habit-card${muted ? " is-muted" : ""}${done ? " is-done" : ""}`} style={{ ["--habit-accent" as string]: accent }}>
      <div className="habit-card-head">
        <span className="habit-card-icon"><HabitIcon name={icon} size={18} /></span>
        <div className="habit-card-title">
          <h3>{habit.title}</h3>
          <span>{scheduleLabel(schedule)}</span>
        </div>
        {streak > 0 && (
          <span className="habit-streak" title={`${streak}-day streak`}>
            <Flame size={13} />
            {streak}
          </span>
        )}
      </div>
      {description && <p className="habit-card-note">{description}</p>}
      <div className="habit-week-dots">
        {week.days.map((day) => (
          <span
            key={day.iso}
            className={`habit-dot${day.done ? " done" : ""}${day.scheduled ? " scheduled" : ""}${day.isToday ? " today" : ""}${day.isFuture ? " future" : ""}`}
            title={`${WEEKDAY_LABELS[day.weekday]} ${day.iso}`}
          >
            {WEEKDAY_LABELS[day.weekday][0]}
          </span>
        ))}
      </div>
      <div className="habit-card-actions">
        <button className={`habit-check${done ? " done" : ""}`} onClick={() => onToggle(habit, today)}>
          <Check size={16} />
          {done ? "Done today" : "Mark done"}
        </button>
        <button className="habit-icon-btn" title="Open calendar" onClick={onOpenCalendar}>
          <CalendarDays size={15} />
        </button>
        <button className="habit-icon-btn" title="Edit" onClick={() => onEdit(habit)}>
          <Pencil size={15} />
        </button>
        <button className="habit-icon-btn" title="Delete" onClick={() => onRemove(habit)}>
          <Trash2 size={15} />
        </button>
      </div>
    </article>
  );
}

function HabitStatRow({ habit }: { habit: PersonalItem }) {
  const schedule = normalizeSchedule(habit.data);
  const dates = habitDates(habit.data);
  const icon = typeof habit.data.icon === "string" ? habit.data.icon : "";
  const streak = computeStreak(dates, schedule);
  const best = longestStreak(dates, schedule);
  const rate = Math.round(completionRate(dates, schedule, daysAgoISO(29)) * 100);

  return (
    <div className="habit-strip">
      <span className="habit-strip-title">
        <span className="habit-card-icon"><HabitIcon name={icon} size={15} /></span>
        {habit.title}
      </span>
      <div className="habit-strip-stats">
        <span title="Current streak">
          <Flame size={12} />
          {streak}
        </span>
        <span title="Longest streak">Best {best}</span>
        <span title="30-day completion">{rate}%</span>
      </div>
    </div>
  );
}

function HeatLegend() {
  return (
    <div className="habit-legend">
      <span>Less</span>
      {[0, 1, 2, 3, 4].map((value) => (
        <span key={value} className="habit-heat-cell" data-level={value} />
      ))}
      <span>More</span>
    </div>
  );
}
