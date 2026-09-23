"use client";
import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Plus, Check, SkipForward, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Calendar, Event, Task } from "@/lib/types";
import { useAuth } from "@/components/provider";
import { Empty, ErrorBox, Heading, Modal } from "@/components/ui";
import { addDays, dateKey, formatDate, formatTime, localInput, toInstant } from "@/lib/time";
export default function CalendarPage() {
  const { preferences } = useAuth();
  const zone = preferences?.timezone || "Africa/Accra";
  const today = dateKey(new Date().toISOString(), zone);
  const [day, setDay] = useState(today);
  const [view, setView] = useState("week");
  const [data, setData] = useState<Calendar | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Event | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<Event | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const [calendar, tasks] = await Promise.all([api.calendar(), api.tasks()]);
      setData(calendar);
      setTasks(tasks);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function action(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    await action(async () => {
      await api.saveEvent(
        {
          title: f.get("title"),
          description: f.get("description"),
          start_time: toInstant(String(f.get("start")), zone),
          end_time: toInstant(String(f.get("end")), zone),
          event_type: f.get("type"),
          is_recurring: false,
        },
        editing?.id,
      );
      setEditing(undefined);
    });
  }
  const days = Array.from({ length: view === "week" ? 7 : 1 }, (_, i) => addDays(day, i));
  const items = [
    ...(data?.events || []).map((e) => ({
      key: `e${e.id}`,
      id: e.id,
      title: e.title,
      start: e.start_time,
      end: e.end_time,
      type: e.source === "google" ? "GOOGLE" : e.event_type,
      event: e,
      session: false,
    })),
    ...(data?.sessions || []).map((s) => ({
      key: `s${s.id}`,
      id: s.id,
      title: tasks.find((t) => t.id === s.task_id)?.title || "Focus session",
      start: s.start_time,
      end: s.end_time,
      type: "FOCUS",
      event: null,
      session: true,
    })),
  ];
  const conflicts = items.filter((a, i) =>
    items.some((b, j) => i !== j && a.start < b.end && b.start < a.end),
  );
  return (
    <div className="page calendar-page">
      <Heading
        eyebrow="A PLACE FOR EVERYTHING"
        title="Your time, in perspective."
        description={`Events, focus sessions, and room in between. All times in ${zone}.`}
        action={
          <button
            onClick={() => {
              setError("");
              setEditing(null);
            }}
          >
            <Plus size={18} />
            New event
          </button>
        }
      />
      <ErrorBox message={error} />
      {conflicts.length > 0 && (
        <div className="error-box">
          Some calendar items overlap. <Link href="/tasks">Replan affected tasks</Link> to resolve
          these conflicts.
        </div>
      )}
      <div className="toolbar">
        <div className="calendar-controls">
          <button
            className="icon-button"
            aria-label="Previous period"
            onClick={() => setDay(addDays(day, view === "week" ? -7 : -1))}
          >
            <ChevronLeft size={18} />
          </button>
          <button
            className="icon-button"
            aria-label="Next period"
            onClick={() => setDay(addDays(day, view === "week" ? 7 : 1))}
          >
            <ChevronRight size={18} />
          </button>
          <h2>
            {formatDate(`${day}T12:00:00Z`, "UTC")}
            {view === "week" ? ` – ${formatDate(`${days[6]}T12:00:00Z`, "UTC")}` : ""}
          </h2>
          <button className="secondary small-button" onClick={() => setDay(today)}>
            Today
          </button>
        </div>
        <div className="tabs">
          {["day", "week"].map((v) => (
            <button className={view === v ? "selected" : ""} onClick={() => setView(v)} key={v}>
              {v === "day" ? "Day" : "Week"}
            </button>
          ))}
        </div>
      </div>
      {!data ? (
        <p className="loading">Loading your calendar…</p>
      ) : (
        <div className={`calendar-grid ${view}`}>
          {days.map((d) => (
            <section className={`calendar-day ${d === today ? "today" : ""}`} key={d}>
              <header>
                <span>
                  {new Intl.DateTimeFormat("en", { weekday: "short", timeZone: "UTC" }).format(
                    new Date(d + "T12:00Z"),
                  )}
                </span>
                <strong>{Number(d.slice(-2))}</strong>
              </header>
              <div className="calendar-day-content">
                {items
                  .filter(
                    (item) =>
                      dateKey(item.start, zone) <= d &&
                      dateKey(new Date(new Date(item.end).getTime() - 1).toISOString(), zone) >= d,
                  )
                  .sort((a, b) => a.start.localeCompare(b.start))
                  .map((item) => (
                    <article
                      className={`calendar-event ${item.session ? "focus" : ""} ${item.type === "GOOGLE" ? "google" : ""}`}
                      key={item.key}
                    >
                      <span>
                        {formatTime(item.start, zone)} – {formatTime(item.end, zone)}
                      </span>
                      <h3>{item.title}</h3>
                      <small>{item.type.toLowerCase()}</small>
                      <div className="event-actions">
                        {item.session ? (
                          <>
                            <button
                              className="icon-button"
                              disabled={busy}
                              aria-label={`Complete ${item.title} session`}
                              onClick={() => action(() => api.sessionStatus(item.id, "COMPLETED"))}
                            >
                              <Check size={14} />
                            </button>
                            <button
                              className="icon-button"
                              disabled={busy}
                              aria-label={`Skip ${item.title} session`}
                              onClick={() => action(() => api.sessionStatus(item.id, "SKIPPED"))}
                            >
                              <SkipForward size={14} />
                            </button>
                            <Link href="/tasks">Replan</Link>
                          </>
                        ) : item.event?.source === "internal" ? (
                          <>
                            <button
                              className="icon-button"
                              aria-label={`Edit ${item.title}`}
                              onClick={() => {
                                setError("");
                                setEditing(item.event);
                              }}
                            >
                              <Pencil size={14} />
                            </button>
                            <button
                              className="icon-button"
                              aria-label={`Delete ${item.title}`}
                              onClick={() => setDeleting(item.event)}
                            >
                              <Trash2 size={14} />
                            </button>
                          </>
                        ) : (
                          <small>Edit in Google</small>
                        )}
                      </div>
                    </article>
                  ))}
                {data.reminders
                  .filter((r) => dateKey(r.reminder_time, zone) === d)
                  .map((r) => (
                    <div className="calendar-reminder" key={r.id}>
                      <span>◷ {formatTime(r.reminder_time, zone)}</span>
                      {r.message}
                    </div>
                  ))}
                {!items.some((item) => dateKey(item.start, zone) === d) && (
                  <button
                    className="calendar-add"
                    onClick={() => {
                      setError("");
                      setEditing(null);
                    }}
                  >
                    <Plus size={14} />
                    Add a moment
                  </button>
                )}
              </div>
            </section>
          ))}
        </div>
      )}
      {data && items.length === 0 && (
        <Empty
          title="Start with one thing."
          detail="Add a fixed event here, or plan a task to create focus sessions."
        />
      )}
      <div className="calendar-legend">
        <span>
          <i />
          Calendar event
        </span>
        <span>
          <i className="purple" />
          Focus session
        </span>
        <span>
          <i className="green" />
          Google Calendar
        </span>
      </div>
      {editing !== undefined && (
        <Modal
          title={editing ? "Edit event" : "Make time for something"}
          onClose={() => setEditing(undefined)}
        >
          <form onSubmit={save}>
            <label>
              Event name
              <input
                name="title"
                required
                maxLength={200}
                autoFocus
                defaultValue={editing?.title}
              />
            </label>
            <label>
              Notes
              <textarea name="description" defaultValue={editing?.description} maxLength={5000} />
            </label>
            <label>
              Starts · {zone}
              <input
                name="start"
                type="datetime-local"
                required
                defaultValue={editing ? localInput(editing.start_time, zone) : `${day}T09:00`}
              />
            </label>
            <label>
              Ends · {zone}
              <input
                name="end"
                type="datetime-local"
                required
                defaultValue={editing ? localInput(editing.end_time, zone) : `${day}T10:00`}
              />
            </label>
            <label>
              Type
              <select name="type" defaultValue={editing?.event_type || "FIXED"}>
                {["FIXED", "FLEXIBLE", "PERSONAL", "ACADEMIC", "WORK", "OTHER"].map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
            <ErrorBox message={error} />
            <button disabled={busy}>{busy ? "Saving…" : "Save event"}</button>
          </form>
        </Modal>
      )}
      {deleting && (
        <Modal title="Delete event?" onClose={() => setDeleting(null)}>
          <p>Remove “{deleting.title}” from your calendar?</p>
          <ErrorBox message={error} />
          <button
            className="danger"
            disabled={busy}
            onClick={() =>
              action(async () => {
                await api.deleteEvent(deleting.id);
                setDeleting(null);
              })
            }
          >
            Delete event
          </button>
        </Modal>
      )}
    </div>
  );
}
