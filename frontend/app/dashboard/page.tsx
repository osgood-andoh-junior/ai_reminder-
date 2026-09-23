"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Sparkles, CheckCircle2, Clock3, ListTodo } from "lucide-react";
import { api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";
import { useAuth } from "@/components/provider";
import { Heading, Empty, ErrorBox } from "@/components/ui";
import { formatDate, formatTime } from "@/lib/time";
export default function Overview() {
  const { user } = useAuth();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);
  const zone = data?.timezone || "Africa/Accra";
  return (
    <div className="page">
      <Heading
        title={`A good day starts here, ${user?.name.split(" ")[0]}.`}
        description={formatDate(new Date().toISOString(), zone)}
        action={
          <Link className="button" href="/assistant">
            <Sparkles size={17} />
            Plan with Tempo
          </Link>
        }
      />
      <ErrorBox message={error} />
      {!data ? (
        <p className="loading">Loading your overview…</p>
      ) : (
        <>
          <div className="stat-grid">
            {[
              { label: "Tasks on your plate", value: data.summary.active, icon: ListTodo },
              { label: "Tasks scheduled", value: data.summary.scheduled, icon: Clock3 },
              { label: "Tasks completed", value: data.summary.completed, icon: CheckCircle2 },
            ].map(({ label, value, icon: Icon }) => (
              <div className="stat" key={label}>
                <Icon size={21} />
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <div className="overview-grid">
            <section className="panel">
              <div className="panel-heading">
                <h2>Today’s schedule</h2>
                <Link href="/calendar">
                  View calendar <ArrowUpRight size={15} />
                </Link>
              </div>
              {data.events.length + data.sessions.length === 0 ? (
                <Empty
                  title="Some room to breathe."
                  detail="Your planned events and focus sessions will appear here."
                />
              ) : (
                [
                  ...data.events.map((e) => ({
                    key: `e${e.id}`,
                    title: e.title,
                    start: e.start_time,
                    end: e.end_time,
                    type: e.event_type,
                  })),
                  ...data.sessions.map((s) => ({
                    key: `s${s.id}`,
                    title: data.tasks.find((t) => t.id === s.task_id)?.title || "Focus session",
                    start: s.start_time,
                    end: s.end_time,
                    type: "FOCUS",
                  })),
                ]
                  .sort((a, b) => a.start.localeCompare(b.start))
                  .map((e) => (
                    <div className="overview-event" key={e.key}>
                      <span>{formatTime(e.start, zone)}</span>
                      <div>
                        <b>{e.title}</b>
                        <p>
                          {formatTime(e.start, zone)} – {formatTime(e.end, zone)} ·{" "}
                          {e.type.toLowerCase()}
                        </p>
                      </div>
                    </div>
                  ))
              )}
            </section>
            <section className="panel">
              <div className="panel-heading">
                <h2>Next priorities</h2>
                <Link href="/tasks">
                  All tasks <ArrowUpRight size={15} />
                </Link>
              </div>
              {data.tasks.length ? (
                data.tasks.map((t) => (
                  <Link className="overview-task" href="/tasks" key={t.id}>
                    <span className="task-dot" />
                    <div>
                      <b>{t.title}</b>
                      <p>
                        {t.deadline ? `Due ${formatDate(t.deadline, zone)}` : "No deadline"} ·{" "}
                        {t.estimated_duration_minutes} min
                      </p>
                    </div>
                    <span className={`priority ${t.priority.toLowerCase()}`}>
                      {t.priority.toLowerCase()}
                    </span>
                  </Link>
                ))
              ) : (
                <Empty
                  title="Nothing waiting on you."
                  detail="Add a task when your next priority comes along."
                />
              )}
            </section>
            <section className="panel">
              <div className="panel-heading">
                <h2>Upcoming reminders</h2>
                <Link href="/reminders">
                  View all <ArrowUpRight size={15} />
                </Link>
              </div>
              {data.reminders.length ? (
                data.reminders.map((r) => (
                  <div className="overview-reminder" key={r.id}>
                    <Clock3 size={17} />
                    <div>
                      <b>{r.message}</b>
                      <p>
                        {formatDate(r.reminder_time, zone)} · {formatTime(r.reminder_time, zone)}
                      </p>
                    </div>
                  </div>
                ))
              ) : (
                <Empty
                  title="We’ll keep an eye on the time."
                  detail="Reminders are created when you confirm a schedule."
                />
              )}
            </section>
            <Link className="assistant-shortcut" href="/assistant">
              <Sparkles size={28} />
              <h2>
                Plans change.
                <br />
                Your assistant can help.
              </h2>
              <p>Talk through your priorities and find a new rhythm for your day.</p>
              <span>
                Open your assistant <ArrowUpRight size={18} />
              </span>
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
