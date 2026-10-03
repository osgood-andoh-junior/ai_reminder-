"use client";
import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Plus, Check, SkipForward, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { LoadingState } from "@/components/loading-state";
import { api } from "@/lib/api";
import type { Calendar, Event, Task, MeetingDraft, Proposal } from "@/lib/types";
import { MeetingDetails, MeetingEditor } from "@/components/meetings";
import { useAuth } from "@/components/provider";
import { Empty, ErrorBox, Heading, Modal, ProposalCard } from "@/components/ui";
import { addDays, dateKey, formatDate, formatTime, localInput, toInstant } from "@/lib/time";
export default function CalendarPage() {
  const { preferences, now } = useAuth();
  const zone = preferences?.timezone || "Africa/Accra";
  const today = now === null ? null : dateKey(new Date(now).toISOString(), zone);
  const [selectedDay, setDay] = useState<string | null>(null);
  const day = selectedDay ?? today;
  const [view, setView] = useState("week");
  const [data, setData] = useState<Calendar | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Event | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<Event | null>(null);
  const [busy, setBusy] = useState(false);
  const [meetingEdit, setMeetingEdit] = useState<{ initial?: MeetingDraft; id?: number } | null>(
    null,
  );
  const [meetingProposal, setMeetingProposal] = useState<Proposal | null>(null);
  const load = useCallback(async () => {
    setError("");
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
  if (!day || !today) return <LoadingState label="Syncing calendar time…" />;
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
    items.some(
      (b, j) =>
        i !== j &&
        Date.parse(a.start) < Date.parse(b.end) &&
        Date.parse(b.start) < Date.parse(a.end),
    ),
  );
  return (
    <div className="page calendar-page">
      <Heading
        eyebrow="A PLACE FOR EVERYTHING"
        title="Calendar"
        description={`Events, focus sessions, and room in between. All times in ${zone}.`}
        action={
          <button
            onClick={() => {
              setError("");
              setEditing(null);
            }}
          >
            <Plus size={18} />
            Add event
          </button>
        }
      />
      <ErrorBox message={error} />
      <button className="secondary" onClick={() => setMeetingEdit({})}>
        New meeting
      </button>
      <p className="muted">
        Invite external attendees through Google Calendar. Only your availability is checked.
      </p>
      {meetingProposal && (
        <ProposalCard
          key={meetingProposal.id}
          proposal={meetingProposal}
          onDone={() => void load()}
        />
      )}
      {meetingEdit && (
        <MeetingEditor
          initial={meetingEdit.initial}
          eventId={meetingEdit.id}
          day={day}
          onClose={() => setMeetingEdit(null)}
          onProposed={(p) => {
            setMeetingProposal(p);
            setMeetingEdit(null);
          }}
        />
      )}
      {error && (
        <button className="secondary" onClick={load}>
          Try again
        </button>
      )}
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
          <button className="secondary small-button" onClick={() => setDay(null)}>
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
        !error && <LoadingState label="Loading your calendar…" />
      ) : (
        <div className={`calendar-grid ${view}`}>
          {days.map((d) => (
            <section
              aria-label={`${d}${d === today ? ", Today" : ""}`}
              className={`calendar-day ${d === today ? "today" : ""}`}
              key={d}
            >
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
                  .sort((a, b) => Date.parse(a.start) - Date.parse(b.start))
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
                      {item.event?.source === "google" && <MeetingDetails event={item.event} />}
                      {conflicts.some((conflict) => conflict.key === item.key) && (
                        <span className="overdue-label">Overlapping time</span>
                      )}
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
                          <>
                            <button
                              className="secondary small-button"
                              disabled={busy}
                              onClick={() =>
                                action(async () => {
                                  const event = await api.getMeeting(item.id);
                                  setData((previous) =>
                                    previous
                                      ? {
                                          ...previous,
                                          events: previous.events.map((e) =>
                                            e.id === event.id ? event : e,
                                          ),
                                        }
                                      : previous,
                                  );
                                })
                              }
                            >
                              Refresh responses
                            </button>
                            {item.event?.meeting_metadata?.organizer?.self &&
                              !item.event.is_recurring &&
                              !item.event.meeting_metadata.all_day && (
                                <>
                                  <button
                                    className="secondary small-button"
                                    disabled={busy}
                                    onClick={() =>
                                      action(async () => {
                                        const e = await api.getMeeting(item.id);
                                        setMeetingEdit({
                                          id: e.id,
                                          initial: {
                                            title: e.title,
                                            description: e.description,
                                            start_time: e.start_time,
                                            duration_minutes:
                                              (Date.parse(e.end_time) - Date.parse(e.start_time)) /
                                              60000,
                                            attendees:
                                              e.meeting_metadata?.attendees.map((a) => ({
                                                name: a.name,
                                                email: a.email,
                                              })) || [],
                                            location: e.meeting_metadata?.location || "",
                                            google_meet: !!e.meeting_metadata?.meet_url,
                                          },
                                        });
                                      })
                                    }
                                  >
                                    Edit meeting
                                  </button>
                                  <button
                                    className="secondary small-button"
                                    disabled={busy}
                                    onClick={() =>
                                      action(async () => {
                                        const result = await api.cancelMeeting(item.id);
                                        setMeetingProposal(result.proposal);
                                      })
                                    }
                                  >
                                    Cancel meeting
                                  </button>
                                </>
                              )}
                          </>
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
                    Add event
                  </button>
                )}
              </div>
            </section>
          ))}
        </div>
      )}
      {data && items.length === 0 && (
        <Empty
          title="Your calendar is clear."
          detail="Add an event, or give a task some time."
          action={
            <Link className="button secondary" href="/assistant">
              Plan with Xenon
            </Link>
          }
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
