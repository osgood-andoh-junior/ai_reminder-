"use client";
import { useEffect, useId, useRef, useState } from "react";
import { X, CalendarClock, Check, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { Proposal } from "@/lib/types";
import { formatDate, formatTime } from "@/lib/time";
import { useAuth } from "./provider";
import { reminderStages } from "@/lib/reminder-labels";
import { MeetingProposal } from "./meetings";

function PreferenceValue({ name, value }: { name: string; value: unknown }) {
  if (value === null) return <>Use your defaults</>;
  if (typeof value === "boolean") return <>{value ? "On" : "Off"}</>;
  if (Array.isArray(value))
    return (
      <>
        {value.length
          ? value
              .map((item) =>
                name === "preferred_days"
                  ? ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][
                      Number(item)
                    ]
                  : reminderStages.find(([key]) => key === item)?.[1] || String(item),
              )
              .join(", ")
          : "None"}
      </>
    );
  if (typeof value === "object")
    return (
      <dl>
        {Object.entries(value).map(([key, entry]) => (
          <div key={key}>
            <dt>{key.replaceAll("_", " ")}</dt>
            <dd>
              <PreferenceValue name={key} value={entry} />
            </dd>
          </div>
        ))}
      </dl>
    );
  return <>{String(value)}</>;
}
export function ErrorBox({ message }: { message: string }) {
  return message ? (
    <div className="error-box" role="alert">
      {message}
    </div>
  ) : null;
}
export function Empty({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <CalendarClock size={28} />
      <h3>{title}</h3>
      <p>{detail}</p>
      {action}
    </div>
  );
}
export function Heading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <div className="modal-title">
        <h2 id={titleId}>{title}</h2>
        <button className="icon-button" aria-label="Close dialog" onClick={onClose}>
          <X />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function ProposalCard(props: { proposal: Proposal; onDone: () => void }) {
  return props.proposal.kind.startsWith("meeting_") ? (
    <MeetingProposal {...props} />
  ) : (
    <GenericProposalCard {...props} />
  );
}
function GenericProposalCard({ proposal, onDone }: { proposal: Proposal; onDone: () => void }) {
  const { preferences, refresh } = useAuth();
  const zone = preferences?.timezone || "Africa/Accra";
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(proposal.status);
  const [error, setError] = useState("");
  const plan = proposal.payload.plan;
  async function decide(accept: boolean) {
    setBusy(true);
    setError("");
    try {
      await api.decide(proposal.id, accept);
      setStatus(accept ? "ACCEPTED" : "REJECTED");
      await refresh();
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="proposal">
      <div className="proposal-title">
        <Sparkles size={18} />
        <b>{plan ? plan.title : proposal.kind.replaceAll("_", " ")}</b>
        <span className="pill">For your review</span>
      </div>
      {proposal.payload.plans?.map((p) => (
        <div key={p.task_id} className="proposal-details">
          <b>{p.title}</b>
          {p.slots.map((s) => (
            <p key={s.start}>
              {formatDate(s.start, zone)} · {formatTime(s.start, zone)} – {formatTime(s.end, zone)}
            </p>
          ))}
        </div>
      ))}
      {plan ? (
        <>
          <p>
            {plan.feasible
              ? `${plan.scheduled_minutes} minutes planned. Review the times below.`
              : `Partial plan: ${plan.scheduled_minutes} minutes allocated; ${plan.unscheduled_minutes} minutes still need time.`}
          </p>
          <div className="proposal-slots">
            {plan.slots.map((s) => (
              <div key={s.start}>
                <CalendarClock size={18} />
                <span>
                  <b>{formatDate(s.start, zone)}</b>
                  <small>
                    {formatTime(s.start, zone)} – {formatTime(s.end, zone)}
                  </small>
                </span>
                <span className="muted">{s.minutes} min</span>
              </div>
            ))}
          </div>
        </>
      ) : (
        !proposal.payload.plans && (
          <div className="proposal-details">
            {proposal.kind === "save_contact" ? (
              <p>
                Remember {proposal.payload.name} · {proposal.payload.email} for future invitations?
              </p>
            ) : proposal.kind === "commitment_dismiss" ? (
              <p>
                Dismiss “{proposal.payload.review?.title}” from your commitment inbox? No task or
                event will be created.
              </p>
            ) : proposal.kind === "commitment" ? (
              <>
                <p>
                  {proposal.payload.review?.action === "event"
                    ? "Add to your Xenon calendar"
                    : "Add as a task"}
                  : {proposal.payload.review?.title}
                </p>
                {proposal.payload.event && (
                  <p>
                    {formatDate(proposal.payload.event.start_time, zone)} ·{" "}
                    {formatTime(proposal.payload.event.start_time, zone)} –{" "}
                    {formatTime(proposal.payload.event.end_time, zone)}
                  </p>
                )}
                {proposal.payload.task && (
                  <p>
                    {proposal.payload.task.estimated_duration_minutes} minutes
                    {proposal.payload.task.deadline &&
                      ` · Due ${formatDate(proposal.payload.task.deadline, zone)} at ${formatTime(proposal.payload.task.deadline, zone)}`}
                  </p>
                )}
                <small>Detected from Gmail. Confirm only after reviewing the details.</small>
              </>
            ) : proposal.kind === "dismiss_reminder" ? (
              <p>Dismiss reminder #{proposal.payload.reminder_id}? Its history will be retained.</p>
            ) : proposal.kind === "delete_event" ? (
              <p>Delete calendar event #{proposal.payload.event_id}?</p>
            ) : proposal.kind === "update_event" ? (
              <>
                <p>{proposal.payload.event?.title}</p>
                <p>
                  {proposal.payload.event && formatDate(proposal.payload.event.start_time, zone)} ·{" "}
                  {proposal.payload.event && formatTime(proposal.payload.event.start_time, zone)}
                </p>
              </>
            ) : (
              <>
                <p>
                  {proposal.kind === "task_reminders"
                    ? "Update reminder settings for this task:"
                    : "Update your permanent scheduling preferences:"}
                </p>
                <dl>
                  {Object.entries(proposal.payload).map(([key, value]) => (
                    <div key={key}>
                      <dt>{key.replaceAll("_", " ")}</dt>
                      <dd>
                        <PreferenceValue name={key} value={value} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </>
            )}
          </div>
        )
      )}
      <ErrorBox message={error} />
      {status === "PENDING" ? (
        <div className="proposal-footer">
          <button disabled={busy} onClick={() => decide(true)}>
            <Check size={16} />
            {busy
              ? "Saving…"
              : plan && !plan.feasible
                ? "Accept partial plan"
                : plan
                  ? "Schedule it"
                  : "Confirm changes"}
          </button>
          <button disabled={busy} className="secondary" onClick={() => decide(false)}>
            Not now
          </button>
          <small>Review by {formatTime(proposal.expires_at, zone)}</small>
        </div>
      ) : (
        <p className="success" role="status">
          {status === "ACCEPTED"
            ? plan
              ? "Scheduled"
              : "Changes saved"
            : status === "EXPIRED"
              ? "This proposal has expired. Ask Xenon for a fresh plan."
              : "Not applied"}
        </p>
      )}
    </section>
  );
}
