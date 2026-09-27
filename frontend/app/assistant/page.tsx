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
import { useVoice } from "@/lib/use-voice";
import { Mic, Square, Volume2, Copy, Check, SlidersHorizontal, X } from "lucide-react";
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
  const dictationBase = useRef("");
  const voice = useVoice((text) => setInput((dictationBase.current + text).slice(0, 4000)));
  const [speakingMessage, setSpeakingMessage] = useState<number | null>(null);
  const [copiedMessage, setCopiedMessage] = useState<number | null>(null);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [readResponses, setReadResponses] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  const end = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    try {
      setReadResponses(
        user?.id != null && localStorage.getItem(`tempo:voice-responses:${user.id}`) === "true",
      );
    } catch {
      setReadResponses(false);
    }
  }, [user?.id]);
  function startVoice() {
    dictationBase.current = input ? `${input.trimEnd()} ` : "";
    voice.start();
  }
  const listening = voice.state === "Listening";
  const processing = voice.state === "Processing";
  const speaking = voice.state === "Speaking";
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
    if (messages.length)
      end.current?.scrollIntoView({
        behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
        block: "nearest",
      });
  }, [messages, busy]);
  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || submitting.current || processing || configured === false) return;
    submitting.current = true;
    const text = input.trim();
    voice.cancel();
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
      if (readResponses) {
        setSpeakingMessage(messages.length + 1);
        voice.speak(result.message);
      }
      setProposals(await api.proposals());
      setDashboard(await api.dashboard());
    } catch (e) {
      setError((e as Error).message);
      setInput(text);
    } finally {
      submitting.current = false;
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
          <div
            className="assistant-options"
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setOptionsOpen(false);
                e.currentTarget.querySelector("button")?.focus();
              }
            }}
          >
            <button
              type="button"
              className="assistant-icon"
              aria-label="Assistant options"
              title="Assistant options"
              aria-expanded={optionsOpen}
              aria-controls="assistant-options"
              onClick={() => setOptionsOpen(!optionsOpen)}
            >
              <SlidersHorizontal size={18} />
            </button>
            {optionsOpen && (
              <div id="assistant-options" className="assistant-options-panel">
                <strong>Voice responses</strong>
                <label>
                  <input
                    type="checkbox"
                    checked={readResponses}
                    onChange={(e) => {
                      setReadResponses(e.target.checked);
                      try {
                        if (user?.id != null)
                          localStorage.setItem(
                            `tempo:voice-responses:${user.id}`,
                            String(e.target.checked),
                          );
                      } catch {
                        setError("Your voice preference could not be saved in this browser.");
                      }
                    }}
                  />{" "}
                  Automatically read AI responses aloud
                </label>
                <p>
                  Saved for you in this browser. Speech recognition may use your browser’s speech
                  provider.
                </p>
              </div>
            )}
          </div>
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
                {message.role === "assistant" && (
                  <div className="message-actions">
                    <button
                      type="button"
                      className="assistant-icon"
                      aria-label={
                        speaking && speakingMessage === i
                          ? "Stop reading response"
                          : "Read response aloud"
                      }
                      title={
                        speaking && speakingMessage === i
                          ? "Stop reading response"
                          : "Read response aloud"
                      }
                      aria-pressed={speaking && speakingMessage === i}
                      disabled={listening || processing || busy}
                      onClick={() => {
                        if (speaking && speakingMessage === i) voice.cancel();
                        else {
                          setSpeakingMessage(i);
                          voice.speak(message.content);
                        }
                      }}
                    >
                      {speaking && speakingMessage === i ? (
                        <Square size={15} />
                      ) : (
                        <Volume2 size={16} />
                      )}
                    </button>
                    <button
                      type="button"
                      className="assistant-icon"
                      aria-label="Copy response"
                      title="Copy response"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(message.content);
                          setCopiedMessage(i);
                        } catch {
                          setError("Could not copy this response. Select the text to copy it.");
                        }
                      }}
                    >
                      {copiedMessage === i ? <Check size={16} /> : <Copy size={16} />}
                    </button>
                    {copiedMessage === i && <span role="status">Copied</span>}
                  </div>
                )}
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
                        {!action.ok && <small>Please try again or rephrase your request.</small>}
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
          <ErrorBox message={voice.error} />
          <form className={`composer ${listening ? "is-listening" : ""}`} onSubmit={send}>
            <textarea
              ref={textarea}
              value={input}
              onChange={(e) => {
                if (listening || processing) voice.cancel();
                setInput(e.target.value);
              }}
              readOnly={busy}
              maxLength={4000}
              aria-label="Message your assistant"
              placeholder="Ask Tempo anything…"
              rows={2}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  e.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <div className="composer-footer">
              <span role="status" aria-live="polite" aria-atomic="true">
                {listening ? (
                  <>
                    <span className="voice-wave" aria-hidden="true">
                      <i />
                      <i />
                      <i />
                    </span>{" "}
                    Listening…
                  </>
                ) : processing || busy ? (
                  <>
                    <span className="spinner" /> {busy ? "Thinking…" : "Finishing transcript…"}
                  </>
                ) : speaking ? (
                  <>
                    <Volume2 size={15} /> Speaking…
                  </>
                ) : (
                  <>
                    <Sparkles size={14} /> Your context
                  </>
                )}
              </span>
              <div className="composer-actions">
                {(listening || processing) && (
                  <button
                    type="button"
                    className="assistant-icon"
                    onClick={voice.cancel}
                    aria-label="Cancel voice"
                    title="Cancel voice"
                  >
                    <X size={18} />
                  </button>
                )}
                <button
                  type="button"
                  className={`assistant-icon ${listening || speaking ? "active" : ""}`}
                  disabled={busy || processing}
                  onClick={listening ? voice.stop : speaking ? voice.cancel : startVoice}
                  aria-label={
                    listening
                      ? "Stop voice input"
                      : speaking
                        ? "Stop playback"
                        : "Start voice input"
                  }
                  title={
                    listening
                      ? "Stop voice input"
                      : speaking
                        ? "Stop playback"
                        : "Start voice input"
                  }
                >
                  {listening || speaking ? <Square size={17} /> : <Mic size={19} />}
                </button>
                <button
                  className="send-message"
                  disabled={!input.trim() || busy || processing || configured === false}
                  aria-label="Send message"
                  title="Send message"
                >
                  <ArrowUp size={20} />
                </button>
              </div>
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
