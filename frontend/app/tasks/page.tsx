"use client";
import { useCallback, useEffect, useState } from "react";
import {
  Plus,
  Search,
  MoreHorizontal,
  Clock3,
  CalendarClock,
  Check,
  Pencil,
  Trash2,
  RotateCcw,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Task, Plan } from "@/lib/types";
import { useAuth } from "@/components/provider";
import { Empty, ErrorBox, Heading, Modal, ProposalCard } from "@/components/ui";
import { formatDate, toInstant, localInput } from "@/lib/time";
export default function Tasks() {
  const { preferences } = useAuth();
  const zone = preferences?.timezone || "Africa/Accra";
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("active");
  const [editing, setEditing] = useState<Task | null | undefined>(undefined);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planning, setPlanning] = useState<Task | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<Task | null>(null);
  const load = useCallback(async () => {
    try {
      setTasks(await api.tasks());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function action(fn: () => Promise<unknown>) {
    setError("");
    setBusy(true);
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
      const data = {
        title: f.get("title"),
        description: f.get("description"),
        priority: f.get("priority"),
        estimated_duration_minutes: Number(f.get("duration")),
        deadline: f.get("deadline") ? toInstant(String(f.get("deadline")), zone) : null,
      };
      if (editing) await api.updateTask(editing.id, data);
      else await api.createTask(data);
      setEditing(undefined);
    });
  }
  async function createPlan(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    await action(async () => {
      const constraints = {
        ...(f.get("not_before")
          ? { not_before: toInstant(String(f.get("not_before")), zone) }
          : {}),
        ...(f.get("not_after") ? { not_after: toInstant(String(f.get("not_after")), zone) } : {}),
        excluded_dates: f.get("exclude") ? [String(f.get("exclude"))] : [],
      };
      setPlan(await api.plan(planning!.id, constraints));
      setPlanning(null);
    });
  }
  const visible = tasks.filter(
    (t) =>
      t.title.toLowerCase().includes(search.toLowerCase()) &&
      (filter === "all" || filter === "completed"
        ? filter === "all" || t.status === "COMPLETED"
        : !["COMPLETED", "CANCELLED"].includes(t.status)),
  );
  return (
    <div className="page">
      <Heading
        eyebrow="MAKE SPACE FOR YOUR PRIORITIES"
        title="A little progress, every day."
        description="Capture what matters. Find the time to make it happen."
        action={
          <button
            onClick={() => {
              setError("");
              setEditing(null);
            }}
          >
            <Plus size={18} />
            New task
          </button>
        }
      />
      <div className="toolbar">
        <div className="tabs">
          {["active", "completed", "all"].map((f) => (
            <button key={f} className={filter === f ? "selected" : ""} onClick={() => setFilter(f)}>
              {f[0].toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <label className="search">
          <Search size={17} />
          <input
            aria-label="Search tasks"
            placeholder="Find a task…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </div>
      <ErrorBox message={error} />
      <section className="task-list">
        {loading ? (
          <p className="loading">Loading your tasks…</p>
        ) : visible.length ? (
          visible.map((task) => (
            <article className="task-row" id={`task-${task.id}`} key={task.id}>
              <button
                disabled={busy}
                className={`complete-button ${task.status === "COMPLETED" ? "checked" : ""}`}
                aria-label={`Complete ${task.title}`}
                onClick={() =>
                  action(() =>
                    api.updateTask(task.id, {
                      status: task.status === "COMPLETED" ? "PENDING" : "COMPLETED",
                    }),
                  )
                }
              >
                {task.status === "COMPLETED" && <Check size={14} />}
              </button>
              <div className="task-main">
                <h3>{task.title}</h3>
                {task.description && <p>{task.description}</p>}
                <div className="task-meta">
                  <span>
                    <Clock3 size={13} />
                    {task.estimated_duration_minutes} min
                  </span>
                  <span>
                    {task.deadline ? `Due ${formatDate(task.deadline, zone)}` : "No deadline"}
                  </span>
                  <span className={`priority ${task.priority.toLowerCase()}`}>
                    {task.priority.toLowerCase()}
                  </span>
                  <span className="status-label">
                    {task.status.toLowerCase().replaceAll("_", " ")}
                  </span>
                </div>
              </div>
              {!["COMPLETED", "CANCELLED"].includes(task.status) && (
                <button
                  className="secondary small-button"
                  disabled={busy}
                  onClick={() => {
                    setError("");
                    setPlanning(task);
                  }}
                >
                  <CalendarClock size={16} />
                  {task.status === "SCHEDULED" ? "Replan" : "Plan schedule"}
                </button>
              )}
              <details className="menu">
                <summary aria-label={`Actions for ${task.title}`}>
                  <MoreHorizontal size={19} />
                </summary>
                <div>
                  <button
                    onClick={() => {
                      setError("");
                      setEditing(task);
                    }}
                  >
                    <Pencil size={14} />
                    Edit task
                  </button>
                  <button
                    onClick={() => action(() => api.updateTask(task.id, { status: "IN_PROGRESS" }))}
                  >
                    <RotateCcw size={14} />
                    Start working
                  </button>
                  <button
                    onClick={() => action(() => api.updateTask(task.id, { status: "CANCELLED" }))}
                  >
                    Cancel task
                  </button>
                  <button className="danger-text" onClick={() => setDeleting(task)}>
                    <Trash2 size={14} />
                    Delete
                  </button>
                </div>
              </details>
            </article>
          ))
        ) : (
          <Empty
            title="A fresh start."
            detail="Add your first task. We’ll help you find a good time for it."
          />
        )}
      </section>
      {editing !== undefined && (
        <Modal
          title={editing ? "Edit task" : "What needs to get done?"}
          onClose={() => setEditing(undefined)}
        >
          <form onSubmit={save}>
            <label>
              Task name
              <input
                autoFocus
                name="title"
                defaultValue={editing?.title}
                placeholder="e.g. Finish networking assignment"
                required
                maxLength={200}
              />
            </label>
            <label>
              Notes
              <textarea
                name="description"
                defaultValue={editing?.description}
                rows={3}
                maxLength={5000}
              />
            </label>
            <div className="form-grid">
              <label>
                Estimated minutes
                <input
                  name="duration"
                  type="number"
                  min={5}
                  max={10080}
                  defaultValue={editing?.estimated_duration_minutes || 60}
                  required
                />
              </label>
              <label>
                Priority
                <select name="priority" defaultValue={editing?.priority || "MEDIUM"}>
                  {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              Deadline · {zone}
              <input
                name="deadline"
                type="datetime-local"
                defaultValue={editing?.deadline ? localInput(editing.deadline, zone) : ""}
              />
            </label>
            {editing && (
              <p className="form-hint">
                Changing duration or deadline clears the old plan so you can schedule it again.
              </p>
            )}
            <ErrorBox message={error} />
            <button disabled={busy}>{busy ? "Saving…" : "Save task"}</button>
          </form>
        </Modal>
      )}
      {planning && (
        <Modal title={`Plan: ${planning.title}`} onClose={() => setPlanning(null)}>
          <p className="muted">
            We’ll use your calendar and preferences to find time. Optional limits below use {zone}.
          </p>
          <form onSubmit={createPlan}>
            <label>
              Start no earlier than
              <input type="datetime-local" name="not_before" />
            </label>
            <label>
              Finish no later than
              <input type="datetime-local" name="not_after" />
            </label>
            <label>
              A day to keep free
              <input type="date" name="exclude" />
            </label>
            <ErrorBox message={error} />
            <button disabled={busy}>
              <CalendarClock size={17} />
              {busy ? "Finding time…" : "Find available time"}
            </button>
          </form>
        </Modal>
      )}
      {plan && (
        <Modal title="Your proposed schedule" onClose={() => setPlan(null)}>
          {plan.proposal ? (
            <ProposalCard proposal={plan.proposal} onDone={() => void load()} />
          ) : (
            <Empty title="There isn’t enough time." detail={plan.explanation} />
          )}
          <p className="form-hint">
            Times shown in {zone}. Your existing plan stays in place until you confirm.
          </p>
        </Modal>
      )}
      {deleting && (
        <Modal title="Delete this task?" onClose={() => setDeleting(null)}>
          <p>“{deleting.title}” and its sessions and reminders will be permanently removed.</p>
          <ErrorBox message={error} />
          <div className="button-row">
            <button
              disabled={busy}
              className="danger"
              onClick={() =>
                action(async () => {
                  await api.deleteTask(deleting.id);
                  setDeleting(null);
                })
              }
            >
              Delete task
            </button>
            <button className="secondary" onClick={() => setDeleting(null)}>
              Keep task
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
