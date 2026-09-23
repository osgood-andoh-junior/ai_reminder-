"use client";
import { useCallback, useEffect, useState } from "react";
import { Bell, Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { Reminder } from "@/lib/types";
import { useAuth } from "@/components/provider";
import { Empty, ErrorBox, Heading, Modal } from "@/components/ui";
import { formatDate, formatTime, toInstant } from "@/lib/time";
import { ReminderActions } from "@/components/reminder-actions";
import { notificationsChanged } from "@/lib/notifications";
export default function Reminders() {
  const { preferences } = useAuth();
  const zone = preferences?.timezone || "Africa/Accra";
  const [items, setItems] = useState<Reminder[]>([]);
  const [show, setShow] = useState(false);
  const [section, setSection] = useState("Upcoming");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try {
      setItems(await api.reminders());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
    const refresh = () => void load();
    const timer = setInterval(refresh, 15000);
    window.addEventListener("reminders-changed", refresh);
    return () => {
      clearInterval(timer);
      window.removeEventListener("reminders-changed", refresh);
    };
  }, [load]);
  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api.createReminder({
        title: f.get("title"),
        message: f.get("message"),
        reminder_time: toInstant(String(f.get("time")), zone),
      });
      setShow(false);
      notificationsChanged();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const visible = items
    .filter(
      (r) =>
        section === "All" ||
        (section === "Upcoming"
          ? r.status === "PENDING"
          : section === "Unread"
            ? r.status === "SENT"
            : section === "Snoozed"
              ? r.status === "SNOOZED"
              : !["PENDING", "SENT", "SNOOZED"].includes(r.status)),
    )
    .sort((a, b) =>
      (a.snoozed_until || a.reminder_time).localeCompare(b.snoozed_until || b.reminder_time),
    );
  return (
    <div className="page">
      <Heading
        eyebrow="A GENTLE NUDGE, RIGHT ON TIME"
        title="One less thing to remember."
        description="Your reminders stay here, even when you step away."
        action={
          <button
            onClick={() => {
              setError("");
              setShow(true);
            }}
          >
            <Plus size={18} />
            New reminder
          </button>
        }
      />
      <div className="toolbar">
        <div className="tabs">
          {["Upcoming", "Unread", "Snoozed", "Past", "All"].map((tab) => (
            <button
              key={tab}
              className={section === tab ? "selected" : ""}
              onClick={() => setSection(tab)}
            >
              {tab}
            </button>
          ))}
        </div>
        <span className="muted small">Updates every 15 seconds</span>
      </div>
      <ErrorBox message={error} />
      <section className="panel">
        {loading ? (
          <p className="loading">Loading reminders…</p>
        ) : visible.length ? (
          visible.map((r) => (
            <article className={`reminder-row ${r.status === "SENT" ? "due" : ""}`} key={r.id}>
              <span className="reminder-icon">
                <Bell size={20} />
              </span>
              <div>
                <h3>{r.title}</h3>
                <p>{r.message}</p>
                <p>
                  {formatDate(r.snoozed_until || r.reminder_time, zone)} ·{" "}
                  {formatTime(r.snoozed_until || r.reminder_time, zone)}{" "}
                  <span className="pill">{r.status === "SENT" ? "DUE" : r.status}</span>
                </p>
              </div>
              <ReminderActions reminder={r} zone={zone} onChange={load} />
            </article>
          ))
        ) : (
          <Empty
            title="You’re all caught up."
            detail="Confirm a schedule to create reminders automatically, or add one of your own."
          />
        )}
      </section>
      <p className="form-hint">
        In-app reminders are processed by the background worker. They appear here when you return;
        enable browser push in Settings to receive notifications outside this page.
      </p>
      {show && (
        <Modal title="A reminder for later" onClose={() => setShow(false)}>
          <form onSubmit={save}>
            <label>
              Title
              <input name="title" required maxLength={200} defaultValue="Reminder" />
            </label>
            <label>
              What should we remind you about?
              <textarea name="message" required autoFocus maxLength={500} rows={3} />
            </label>
            <label>
              When · {zone}
              <input name="time" type="datetime-local" required />
            </label>
            <ErrorBox message={error} />
            <button disabled={busy}>Create reminder</button>
          </form>
        </Modal>
      )}
    </div>
  );
}
