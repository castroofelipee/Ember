"use client";

import { Bell, BellRing, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { EventItem } from "@/lib/types";

const REMINDER_MS = 10 * 60 * 1000;
const CHECK_INTERVAL_MS = 30 * 1000;
const SEEN_STORAGE_KEY = "ember:event-reminders:v2";
const SEEN_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;

type EventRemindersProps = {
  workspaceId: string;
  accessToken: string;
};

type Reminder = {
  key: string;
  title: string;
  start: Date;
  location: string | null;
};

type AudioWindow = Window &
  typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
  };

function reminderKey(event: EventItem): string {
  return `${event.id}:${event.start_at}`;
}

function readSeen(now: number): Record<string, number> {
  try {
    const stored = JSON.parse(localStorage.getItem(SEEN_STORAGE_KEY) ?? "{}") as Record<
      string,
      number
    >;
    return Object.fromEntries(
      Object.entries(stored).filter(([, timestamp]) => now - timestamp < SEEN_RETENTION_MS),
    );
  } catch {
    return {};
  }
}

function formatStart(start: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(start);
}

export function EventReminders({ workspaceId, accessToken }: EventRemindersProps) {
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">(() =>
    typeof window !== "undefined" && "Notification" in window
      ? Notification.permission
      : "unsupported",
  );
  const [reminder, setReminder] = useState<Reminder | null>(null);
  const [askingPermission, setAskingPermission] = useState(false);
  const audioContextRef = useRef<AudioContext | null>(null);

  const unlockAudio = useCallback(() => {
    if (audioContextRef.current) {
      void audioContextRef.current.resume();
      return;
    }
    const AudioContextClass =
      window.AudioContext ?? (window as AudioWindow).webkitAudioContext;
    if (AudioContextClass) {
      audioContextRef.current = new AudioContextClass();
      void audioContextRef.current.resume();
    }
  }, []);

  const playSound = useCallback(() => {
    const context = audioContextRef.current;
    if (!context || context.state !== "running") return;

    const gain = context.createGain();
    gain.gain.setValueAtTime(0.0001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.2, context.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.75);
    gain.connect(context.destination);

    [0, 0.22].forEach((offset, index) => {
      const oscillator = context.createOscillator();
      oscillator.type = "sine";
      oscillator.frequency.value = index === 0 ? 784 : 1046.5;
      oscillator.connect(gain);
      oscillator.start(context.currentTime + offset);
      oscillator.stop(context.currentTime + offset + 0.42);
    });
  }, []);

  const showReminder = useCallback(
    (event: EventItem) => {
      const nextReminder = {
        key: reminderKey(event),
        title: event.title,
        start: new Date(event.start_at),
        location: event.location,
      };
      setReminder(nextReminder);
      playSound();

      if ("Notification" in window && Notification.permission === "granted") {
        try {
          const notification = new Notification(event.title, {
            body: `Starts at ${formatStart(nextReminder.start)}${event.location ? ` · ${event.location}` : ""}`,
            icon: "/logo.png",
            tag: `ember-${nextReminder.key}`,
          });
          notification.onclick = () => {
            window.focus();
            notification.close();
          };
        } catch {
          // Some mobile browsers expose the API but only deliver notifications
          // through push. The in-app reminder and sound still work.
        }
      }
    },
    [playSound],
  );

  const checkUpcomingEvents = useCallback(async () => {
    const now = Date.now();
    const params = new URLSearchParams({
      start: new Date(now).toISOString(),
      end: new Date(now + REMINDER_MS + CHECK_INTERVAL_MS).toISOString(),
    });

    try {
      const response = await fetch(
        `/api/workspaces/${workspaceId}/events?${params.toString()}`,
        { headers: { Authorization: `Bearer ${accessToken}` } },
      );
      if (!response.ok) return;

      const events: EventItem[] = await response.json();
      const seen = readSeen(now);
      let changed = false;

      events
        .filter((event) => !event.all_day)
        .sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at))
        .forEach((event) => {
          const key = reminderKey(event);
          const startsAt = Date.parse(event.start_at);
          const isStartingSoon = startsAt > now && startsAt - now <= REMINDER_MS;
          if (!seen[key] && isStartingSoon) {
            seen[key] = now;
            changed = true;
            showReminder(event);
          }
        });

      if (changed) localStorage.setItem(SEEN_STORAGE_KEY, JSON.stringify(seen));
    } catch {
      // A transient network failure is retried at the next interval.
    }
  }, [accessToken, showReminder, workspaceId]);

  useEffect(() => {
    const onFirstInteraction = () => unlockAudio();
    window.addEventListener("pointerdown", onFirstInteraction, { once: true });
    window.addEventListener("keydown", onFirstInteraction, { once: true });
    return () => {
      window.removeEventListener("pointerdown", onFirstInteraction);
      window.removeEventListener("keydown", onFirstInteraction);
    };
  }, [unlockAudio]);

  useEffect(() => {
    void checkUpcomingEvents();
    const interval = window.setInterval(() => void checkUpcomingEvents(), CHECK_INTERVAL_MS);
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void checkUpcomingEvents();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [checkUpcomingEvents]);

  const enableNotifications = useCallback(async () => {
    unlockAudio();
    setAskingPermission(true);
    try {
      const result = await Notification.requestPermission();
      setPermission(result);
    } finally {
      setAskingPermission(false);
    }
  }, [unlockAudio]);

  return (
    <>
      {permission === "default" && (
        <div className="reminder-permission" role="status">
          <Bell size={18} aria-hidden="true" />
          <span>Get an alert with sound 10 minutes before events.</span>
          <button type="button" onClick={enableNotifications} disabled={askingPermission}>
            {askingPermission ? "Enabling…" : "Enable"}
          </button>
        </div>
      )}

      {permission === "denied" && (
        <div className="reminder-permission reminder-permission--denied" role="status">
          <Bell size={18} aria-hidden="true" />
          <span>
            Notifications are blocked. Allow notifications for Ember in your browser settings.
          </span>
        </div>
      )}

      {reminder && (
        <div className="event-reminder" role="alert" aria-live="assertive">
          <div className="event-reminder-icon">
            <BellRing size={22} aria-hidden="true" />
          </div>
          <div className="event-reminder-content">
            <strong>{reminder.title}</strong>
            <span>
              Starts in 10 minutes · {formatStart(reminder.start)}
              {reminder.location ? ` · ${reminder.location}` : ""}
            </span>
          </div>
          <button
            type="button"
            className="event-reminder-close"
            aria-label="Dismiss reminder"
            onClick={() => setReminder(null)}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
      )}
    </>
  );
}
