"use client";
import { useEffect, useRef, useState } from "react";
import { X, CalendarClock, Check, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { Proposal } from "@/lib/types";
import { formatDate, formatTime } from "@/lib/time";
import { useAuth } from "./provider";
export function ErrorBox({ message }: { message: string }) {
  return message ? (
    <div className="error-box" role="alert">
      {message}
    </div>
  ) : null;
}
export function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty">
      <CalendarClock size={28} />
      <h3>{title}</h3>
      <p>{detail}</p>
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
        <span className="eyebrow">{eyebrow || "A LITTLE CLARITY FOR YOUR DAY"}</span>
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
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <div className="modal-title">
        <h2>{title}</h2>
        <button className="icon-button" aria-label="Close dialog" onClick={onClose}>
          <X />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function ProposalCard({ proposal, onDone }: { proposal: Proposal; onDone: () => void }) {
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
        <span className="pill">PROPOSAL</span>
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
              ? `${plan.scheduled_minutes} minutes, thoughtfully arranged.`
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
            {proposal.kind === "dismiss_reminder" ? (
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
                <p>Update your permanent scheduling preferences:</p>
                <dl>
                  {Object.entries(proposal.payload).map(([key, value]) => (
                    <div key={key}>
                      <dt>{key.replaceAll("_", " ")}</dt>
                      <dd>{String(value)}</dd>
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
            {plan && !plan.feasible ? "Accept partial plan" : "Confirm changes"}
          </button>
          <button disabled={busy} className="secondary" onClick={() => decide(false)}>
            Decline
          </button>
          <small>Expires in 30 minutes</small>
        </div>
      ) : (
        <p className="success">{status === "ACCEPTED" ? "Changes saved" : "Proposal declined"}</p>
      )}
    </section>
  );
}
