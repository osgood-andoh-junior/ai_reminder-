"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Bell } from "lucide-react";
import { api } from "@/lib/api";
import type { Reminder } from "@/lib/types";
import { ReminderActions } from "./reminder-actions";
import { formatDate, formatTime } from "@/lib/time";

export function NotificationBell({ zone }: { zone: string }) {
  const [count, setCount] = useState(0);
  const [items, setItems] = useState<Reminder[]>([]);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [unread, recent] = await Promise.all([api.unreadCount(), api.recentReminders()]);
      setCount(unread.count);
      setItems(recent);
      setError("");
    } catch {
      setError("Notifications could not refresh. Try again.");
    }
  }, []);
  useEffect(() => {
    let mounted = true;
    const refresh = () => {
      if (mounted) void load();
    };
    refresh();
    const timer = setInterval(refresh, 15000);
    window.addEventListener("reminders-changed", refresh);
    window.addEventListener("focus", refresh);
    const message = () => refresh();
    navigator.serviceWorker?.addEventListener("message", message);
    return () => {
      mounted = false;
      clearInterval(timer);
      window.removeEventListener("reminders-changed", refresh);
      window.removeEventListener("focus", refresh);
      navigator.serviceWorker?.removeEventListener("message", message);
    };
  }, [load]);
  return (
    <div className="notification-center">
      <button
        className="icon-button notification-bell"
        aria-label={`Notifications, ${count} unread`}
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
          void load();
        }}
      >
        <Bell size={18} />
        {count > 0 && (
          <span className="notification-count" aria-live="polite">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>
      {open && (
        <section className="notification-popover" aria-label="Recent notifications">
          <div className="panel-heading">
            <h2>Notifications</h2>
            <button
              className="icon-button"
              aria-label="Close notifications"
              onClick={() => setOpen(false)}
            >
              ×
            </button>
          </div>
          {error && (
            <p role="alert">
              {error} <button onClick={load}>Retry</button>
            </p>
          )}
          {!items.length && !error && (
            <p className="panel-body muted">No delivered reminders yet.</p>
          )}
          {items.map((item) => (
            <article key={item.id} className="notification-item">
              <strong>{item.title}</strong>
              <p>{item.message}</p>
              <small>
                {formatDate(item.sent_at || item.reminder_time, zone)} ·{" "}
                {formatTime(item.sent_at || item.reminder_time, zone)} · {item.status}
              </small>
              <ReminderActions reminder={item} zone={zone} onChange={load} />
            </article>
          ))}
          <Link className="notification-footer" href="/reminders" onClick={() => setOpen(false)}>
            View all reminders
          </Link>
        </section>
      )}
    </div>
  );
}
