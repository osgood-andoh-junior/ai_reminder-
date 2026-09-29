"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";
import { useAuth } from "@/components/provider";
import { Heading, Empty, ErrorBox } from "@/components/ui";
import { LoadingState } from "@/components/loading-state";
import { XenonMark } from "@/components/xenon-mark";
import { dayContext, greeting } from "@/lib/day-context";
import { dateKey, formatDate, formatTime } from "@/lib/time";
export default function Today() {
  const { user, preferences } = useAuth();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState<number | null>(null);
  const load = useCallback(async () => {
    setError("");
    try {
      setData(await api.dashboard());
    } catch {
      setError("Xenon couldn’t load your day. Check your connection and try again.");
    }
  }, []);
  const zone = data?.timezone || preferences?.timezone || "Africa/Accra";
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    let day = dateKey(new Date().toISOString(), zone);
    const tick = () => {
      const current = Date.now();
      setNow(current);
      const nextDay = dateKey(new Date(current).toISOString(), zone);
      if (nextDay !== day) {
        day = nextDay;
        void load();
      }
    };
    tick();
    const timer = setInterval(tick, 60000);
    return () => clearInterval(timer);
  }, [zone, load]);
  const context = data && now !== null ? dayContext(data, now) : null;
  const firstName = user?.name.trim().split(/\s+/)[0];
  return (
    <div className="page today-page">
      <Heading
        eyebrow="TODAY"
        title={`${now === null ? "Welcome" : greeting(now, zone)}${firstName ? `, ${firstName}` : ""}.`}
        description={
          now === null
            ? "Here’s what your day looks like."
            : `${formatDate(new Date(now).toISOString(), zone)} · Here’s what your day looks like.`
        }
        action={
          <Link className="button" href="/assistant">
            <XenonMark size={18} />
            Plan with Xenon
          </Link>
        }
      />
      <ErrorBox message={error} />
      {error && (
        <button className="secondary" onClick={load}>
          Try again
        </button>
      )}
      {!context || !data ? (
        !error && <LoadingState label="Loading your day…" />
      ) : (
        <>
          <section className="day-overview" aria-label="Your day at a glance">
            <div>
              <span className="eyebrow">NOW</span>
              <h2>
                {context.current.length
                  ? context.current.map((item) => item.title).join(" · ")
                  : "No commitment right now"}
              </h2>
              <p>
                {context.current.length
                  ? `Until ${formatTime(context.current[0].end, zone)}`
                  : "A moment to choose your next priority."}
              </p>
            </div>
            <div>
              <span className="eyebrow">UP NEXT</span>
              <h2>{context.next?.title || "Nothing else planned today"}</h2>
              <p>
                {context.next
                  ? `${formatTime(context.next.start, zone)} – ${formatTime(context.next.end, zone)}`
                  : "Your next commitment will appear here."}
              </p>
            </div>
            <div>
              <span className="eyebrow">NEEDS ATTENTION</span>
              <h2>
                {context.conflicts.length
                  ? `${context.conflicts.length} overlapping commitments`
                  : context.overdue.length
                    ? "A deadline has passed"
                    : "No calendar overlaps"}
              </h2>
              <Link className="text-link" href={context.conflicts.length ? "/calendar" : "/tasks"}>
                {context.conflicts.length ? "Review calendar" : "Review tasks"}
                <ArrowUpRight size={15} />
              </Link>
            </div>
          </section>
          <div className="today-columns">
            <section className="today-timeline">
              <div className="panel-heading">
                <h2>Today’s timeline</h2>
                <Link href="/calendar">
                  Calendar <ArrowUpRight size={15} />
                </Link>
              </div>
              {context.items.length ? (
                context.items.map((item) => (
                  <Link
                    href={item.href}
                    className={`timeline-item ${context.current.some((current) => current.id === item.id) ? "is-current" : ""}`}
                    key={item.id}
                  >
                    <time dateTime={item.start}>{formatTime(item.start, zone)}</time>
                    <div>
                      <h3>{item.title}</h3>
                      <p>
                        {formatTime(item.start, zone)} – {formatTime(item.end, zone)} ·{" "}
                        {item.type.toLowerCase().replaceAll("_", " ")}
                      </p>
                      {context.current.some((current) => current.id === item.id) && (
                        <span className="status-label">Happening now</span>
                      )}
                      {context.conflicts.some((conflict) => conflict.id === item.id) && (
                        <span className="overdue-label"> Overlaps another commitment</span>
                      )}
                    </div>
                  </Link>
                ))
              ) : (
                <Empty
                  title="Your day is clear."
                  detail="Add an event or make a plan for something that matters."
                  action={
                    <Link className="button secondary" href="/calendar">
                      Open calendar
                    </Link>
                  }
                />
              )}
              <p className="form-hint">
                Times in {zone}. Ask Xenon to find available time around your scheduling
                preferences.
              </p>
            </section>
            <div className="today-priorities">
              <section>
                <div className="panel-heading">
                  <h2>Next priorities</h2>
                  <Link href="/tasks">
                    All tasks <ArrowUpRight size={15} />
                  </Link>
                </div>
                {data.tasks.length ? (
                  data.tasks.map((task) => (
                    <Link className="overview-task" href={`/tasks#task-${task.id}`} key={task.id}>
                      <span className="task-dot" />
                      <div>
                        <b>{task.title}</b>
                        <p>
                          {task.deadline ? `Due ${formatDate(task.deadline, zone)}` : "No deadline"}{" "}
                          · {task.estimated_duration_minutes} min
                        </p>
                        {context.overdue.some((t) => t.id === task.id) && (
                          <span className="overdue-label">Overdue</span>
                        )}
                      </div>
                    </Link>
                  ))
                ) : (
                  <Empty
                    title="Nothing here yet."
                    detail="Add something you need to get done."
                    action={
                      <Link className="text-link" href="/tasks">
                        Add a task
                      </Link>
                    }
                  />
                )}
              </section>
              <section>
                <div className="panel-heading">
                  <h2>Reminders</h2>
                  <Link href="/reminders">
                    View all <ArrowUpRight size={15} />
                  </Link>
                </div>
                {data.reminders.length ? (
                  data.reminders.slice(0, 3).map((reminder) => (
                    <Link href="/reminders" className="overview-reminder" key={reminder.id}>
                      <div>
                        <b>{reminder.title || reminder.message}</b>
                        <p>
                          {formatDate(reminder.reminder_time, zone)} ·{" "}
                          {formatTime(reminder.reminder_time, zone)}
                        </p>
                      </div>
                    </Link>
                  ))
                ) : (
                  <p className="muted">No reminders waiting. Add one or confirm a task schedule.</p>
                )}
              </section>
            </div>
          </div>
          <div className="today-summary" aria-label="Task totals">
            <span>{data.summary.active} active tasks</span>
            <span>{data.summary.scheduled} scheduled</span>
            <span>{data.summary.completed} completed</span>
          </div>
        </>
      )}
    </div>
  );
}
