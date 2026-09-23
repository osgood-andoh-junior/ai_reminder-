"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowUp,
  ArrowUpRight,
  Sparkles,
  CalendarDays,
  Clock3,
  ListTodo,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Message, Proposal, Dashboard } from "@/lib/types";
import { useAuth } from "@/components/provider";
import { ErrorBox, ProposalCard } from "@/components/ui";
import { formatTime } from "@/lib/time";
const prompts = [
  {
    icon: ListTodo,
    title: "Find time for a task",
    text: "Help me schedule a task before its deadline.",
  },
  { icon: CalendarDays, title: "See my day clearly", text: "What do I have on my calendar today?" },
  {
    icon: Clock3,
    title: "Make room for a change",
    text: "I need to move a scheduled task. Can you help?",
  },
];
export default function Assistant() {
  const { user, preferences } = useAuth();
  const zone = preferences?.timezone || "Africa/Accra";
  const [messages, setMessages] = useState<Message[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const refresh = useCallback(async () => {
    try {
      const [history, pending, day, health] = await Promise.all([
        api.history(),
        api.proposals(),
        api.dashboard(),
        api.health(),
      ]);
      setMessages(history);
      setProposals(pending);
      setDashboard(day);
      setConfigured(health.ai_configured);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (messages.length) end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, busy]);
  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || busy) return;
    const text = input.trim();
    setBusy(true);
    setError("");
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text, actions: [] }]);
    try {
      const result = await api.chat(text);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: result.message, actions: result.actions },
      ]);
      setProposals(await api.proposals());
      setDashboard(await api.dashboard());
    } catch (e) {
      setError((e as Error).message);
      setInput(text);
    } finally {
      setBusy(false);
    }
  }
  const todayItems = [
    ...(dashboard?.events || []).map((e) => ({
      id: `e${e.id}`,
      title: e.title,
      start: e.start_time,
      type: e.event_type,
    })),
    ...(dashboard?.sessions || []).map((s) => ({
      id: `s${s.id}`,
      title: dashboard?.tasks.find((t) => t.id === s.task_id)?.title || "Focus session",
      start: s.start_time,
      type: "FOCUS",
    })),
  ].sort((a, b) => a.start.localeCompare(b.start));
  return (
    <div className="assistant-page">
      <div className="assistant-main">
        <div className="assistant-toolbar">
          <div>
            <span className="assistant-mark">
              <Sparkles size={17} />
            </span>
            <strong>Your personal assistant</strong>
            <span className="pill">TEMPO AI</span>
          </div>
          <span className="muted small">A plan that fits you</span>
        </div>
        <div className={`conversation ${messages.length ? "has-messages" : ""}`}>
          {!messages.length && !loading && (
            <div className="assistant-welcome">
              <div className="welcome-symbol">
                <Sparkles size={30} />
                <span />
              </div>
              <span className="eyebrow">LESS JUGGLING. MORE FOCUS.</span>
              <h1>
                What’s on your mind,
                <br />
                <em>{user?.name.split(" ")[0]}?</em>
              </h1>
              <p>
                Tell me what needs to get done.
                <br />
                We’ll find the right time for it, together.
              </p>
              <div className="prompt-grid">
                {prompts.map(({ icon: Icon, title, text }) => (
                  <button
                    className="prompt-card"
                    key={title}
                    onClick={() => {
                      setInput(text);
                      textarea.current?.focus();
                    }}
                  >
                    <Icon size={20} />
                    <strong>{title}</strong>
                    <ArrowUpRight size={16} />
                  </button>
                ))}
              </div>
            </div>
          )}
          {loading && (
            <p className="loading">
              <span className="spinner" /> Opening your conversations…
            </p>
          )}
          {messages.map((message, i) => (
            <article className={`message ${message.role}`} key={message.id || `new-${i}`}>
              <span className="message-avatar">
                {message.role === "user" ? user?.name.slice(0, 1) : <Sparkles size={18} />}
              </span>
              <div>
                <span className="message-author">{message.role === "user" ? "You" : "Tempo"}</span>
                <p>{message.content}</p>
                {message.actions.length > 0 && (
                  <details className="action-receipts">
                    <summary>
                      {message.actions.length} tool{" "}
                      {message.actions.length === 1 ? "result" : "results"}
                    </summary>
                    {message.actions.map((action, j) => (
                      <div key={j} className={action.ok ? "tool-ok" : "tool-error"}>
                        {action.ok ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
                        <span>{action.tool.replaceAll("_", " ")}</span>
                        <small>{action.ok ? "Succeeded" : "Failed"}</small>
                        {!action.ok && <pre>{JSON.stringify(action.result)}</pre>}
                      </div>
                    ))}
                  </details>
                )}
              </div>
            </article>
          ))}
          {busy && (
            <div className="thinking" role="status">
              <span className="spinner" /> Checking your tasks, preferences, and available time…
            </div>
          )}
          {proposals.map((p) => (
            <ProposalCard proposal={p} onDone={() => void refresh()} key={p.id} />
          ))}
          <div ref={end} />
        </div>
        <div className="composer-wrap">
          {configured === false && (
            <div className="setup-notice">
              <Sparkles size={17} />
              <span>
                AI will be ready when you add your API key. Until then,{" "}
                <Link href="/tasks">create a task and plan its schedule</Link>.
              </span>
            </div>
          )}
          <ErrorBox message={error} />
          <form className="composer" onSubmit={send}>
            <textarea
              ref={textarea}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              maxLength={4000}
              aria-label="Message your assistant"
              placeholder="I need to finish an assignment before Friday…"
              rows={2}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  e.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <div>
              <span>
                <Sparkles size={14} /> Your calendar. Your preferences. Your pace.
              </span>
              <button
                disabled={!input.trim() || busy || configured === false}
                aria-label="Send message"
              >
                <ArrowUp size={20} />
              </button>
            </div>
          </form>
          <p className="composer-note">
            You review schedule changes before they’re saved. <span>↵ Send · Shift ↵ New line</span>
          </p>
        </div>
      </div>
      <aside className="day-panel">
        <div className="day-panel-heading">
          <h2>A look at today</h2>
          <span>
            {new Intl.DateTimeFormat("en", {
              weekday: "long",
              month: "short",
              day: "numeric",
              timeZone: zone,
            }).format(new Date())}
          </span>
        </div>
        <div className="daily-count">
          <span>{todayItems.length}</span>
          <div>
            planned moments<small>Room to make progress.</small>
          </div>
          <CalendarDays size={22} />
        </div>
        <div className="section-label">ON YOUR CALENDAR</div>
        {todayItems.length ? (
          todayItems.map((item) => (
            <div className="day-item" key={item.id}>
              <span>{formatTime(item.start, zone)}</span>
              <div>
                <b>{item.title}</b>
                <small>{item.type.toLowerCase().replaceAll("_", " ")}</small>
              </div>
            </div>
          ))
        ) : (
          <div className="day-empty">
            <span className="empty-ring" />
            <h3>A clear canvas.</h3>
            <p>
              No events planned for today.
              <br />
              Give your priorities a little space.
            </p>
          </div>
        )}
        <Link className="text-link" href="/calendar">
          Open calendar <ArrowUpRight size={15} />
        </Link>
        <div className="focus-note">
          <span className="eyebrow">ONE THING AT A TIME</span>
          <p>
            A little structure.
            <br />A lot more headspace.
          </p>
          <div className="focus-lines">
            <span />
            <span />
            <span />
          </div>
        </div>
        <div className="section-label">COMING UP</div>
        {dashboard?.tasks.slice(0, 3).map((task) => (
          <Link className="mini-task" href="/tasks" key={task.id}>
            <span className="task-dot" />
            <div>
              <b>{task.title}</b>
              <small>
                {task.estimated_duration_minutes} min · {task.priority.toLowerCase()}
              </small>
            </div>
          </Link>
        ))}
        {!dashboard?.tasks.length && (
          <p className="muted small">Your next priority will appear here.</p>
        )}
      </aside>
    </div>
  );
}
