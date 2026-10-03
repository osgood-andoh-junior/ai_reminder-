"use client";
import { useCallback, useEffect, useState } from "react";
import { CalendarDays, Link2, Mail, RefreshCw, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { Commitment, CommitmentReview, Integration, Proposal } from "@/lib/types";
import { useAuth } from "@/components/provider";
import { ErrorBox, Modal, ProposalCard } from "@/components/ui";
import { LoadingState } from "@/components/loading-state";
import { formatDate, formatTime, localInput, toInstant } from "@/lib/time";

const states = {
  connected: "Connected",
  not_connected: "Not connected",
  needs_attention: "Needs attention",
  coming_soon: "Coming soon",
};
const errors: Record<string, string> = {
  ai_unavailable:
    "Email detection is unavailable until AI is configured. Your manual tasks and calendar still work.",
  extraction_failed:
    "Xenon couldn’t read the commitments reliably. Check again to retry the email.",
  rate_limited: "Google is limiting requests. Wait a little, then check again.",
  google_unavailable:
    "Google is unavailable. Your existing tasks and calendar still work. Try again later.",
};
function errorText(code: string) {
  return errors[code] || "Gmail needs attention. Reconnect to restore read access, then try again.";
}

export function IntegrationHub() {
  const { preferences } = useAuth();
  const zone = preferences?.timezone || "Africa/Accra";
  const [integrations, setIntegrations] = useState<Integration[] | null>(null);
  const [items, setItems] = useState<Commitment[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState<Commitment | null>(null);
  const [disconnect, setDisconnect] = useState<Integration | null>(null);
  const [revoke, setRevoke] = useState(false);
  const load = useCallback(async () => {
    const [connections, inbox, pending] = await Promise.all([
      api.integrations(),
      api.commitments(),
      api.proposals(),
    ]);
    setIntegrations(connections);
    setItems(inbox);
    setProposals(pending.filter((p) => p.kind === "commitment" || p.kind === "commitment_dismiss"));
  }, []);
  useEffect(() => {
    void load().catch((e) => setError((e as Error).message));
    const result = new URLSearchParams(window.location.search).get("gmail");
    if (result === "connected")
      setNotice("Gmail connected. Check for commitments when you’re ready.");
    else if (result === "failed" || result === "declined")
      setError("Gmail connection wasn’t completed. Connect again and grant read-only access.");
  }, [load]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function propose(item: Commitment, value: CommitmentReview) {
    await run(async () => {
      const result = await api.proposeCommitment(item.id, value);
      if (!result.proposal) {
        setError(
          result.message || "No feasible schedule. Edit the deadline or duration and try again.",
        );
        return;
      }
      setReview(null);
      setNotice("Review the proposal below. Nothing has been added yet.");
    });
  }
  return (
    <section className="panel integration-hub" id="integrations">
      <div className="panel-heading">
        <h2>Integrations</h2>
        <Link2 size={18} />
      </div>
      <div className="panel-body">
        <p>
          Connect the places your commitments come from. You decide what becomes a task or event.
        </p>
        <ErrorBox message={error} />
        {error && (
          <button
            className="secondary small-button"
            disabled={busy}
            onClick={() => run(async () => {})}
          >
            Retry integrations
          </button>
        )}
        {notice && (
          <p className="success-box" role="status">
            {notice}
          </p>
        )}
        {!integrations && !error && <LoadingState label="Loading integrations…" />}
        <div className="integration-cards">
          {integrations?.map((item) => (
            <article className="integration-card" key={item.id} aria-label={item.name}>
              <div className="integration-card-title">
                {item.id === "gmail" ? <Mail size={20} /> : <CalendarDays size={20} />}
                <h3>{item.name}</h3>
                <span className="pill">{states[item.state]}</span>
              </div>
              {item.account && <p>{item.account}</p>}
              {item.state === "coming_soon" ? (
                <p className="muted">Not available yet.</p>
              ) : (
                <>
                  {!item.configured && <p className="form-hint">Connection needs server setup.</p>}
                  {item.error && (
                    <p role="status">
                      {item.id === "gmail"
                        ? errorText(item.error)
                        : "Retry Calendar sync or reconnect your Google account."}
                    </p>
                  )}
                  {item.synced_at && (
                    <small>
                      Last checked {formatDate(item.synced_at, zone)} ·{" "}
                      {formatTime(item.synced_at, zone)}
                    </small>
                  )}
                  <div className="button-row">
                    {item.state !== "connected" && (
                      <button
                        disabled={busy || !item.configured}
                        onClick={() =>
                          run(async () => {
                            const value =
                              item.id === "gmail"
                                ? await api.gmailConnect()
                                : await api.googleConnect();
                            window.location.assign(value.url);
                          })
                        }
                      >
                        {item.state === "needs_attention" ? "Reconnect" : "Connect"} {item.name}
                      </button>
                    )}
                    {item.state !== "not_connected" && (
                      <>
                        <button
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              if (item.id === "gmail") {
                                const result = await api.gmailSync();
                                setNotice(
                                  `Checked ${result.checked} emails. Found ${result.detected} possible commitments.${result.more ? " More recent emails remain; check again to continue." : ""}`,
                                );
                                if (result.error) setError(errorText(result.error));
                              } else {
                                const result = await api.googleSync();
                                setNotice(
                                  `Synced ${result.imported} events.${result.conflicts.length ? " Review overlapping tasks in Calendar." : ""}`,
                                );
                              }
                            })
                          }
                        >
                          <RefreshCw size={15} />
                          {busy
                            ? "Working…"
                            : item.id === "gmail"
                              ? "Check Gmail for commitments"
                              : "Sync Calendar"}
                        </button>
                        <button
                          className="secondary"
                          disabled={busy}
                          onClick={() => {
                            setDisconnect(item);
                            setRevoke(false);
                          }}
                        >
                          Disconnect {item.name}
                        </button>
                      </>
                    )}
                  </div>
                </>
              )}
            </article>
          ))}
        </div>
        <p className="form-hint">
          Gmail is read-only. Checking sends a bounded portion of recent email text to the
          configured AI provider. Xenon stores source metadata and detected details, not full
          bodies. Email never creates tasks or events without your confirmation.
        </p>
        <div className="panel-heading">
          <h3>Commitment inbox</h3>
          <Sparkles size={18} />
        </div>
        {integrations && !items.length && (
          <p className="muted">
            No pending commitments. Check Gmail to look for deadlines and appointments.
          </p>
        )}
        <div className="commitment-list">
          {items.map((item) => (
            <article className="commitment-card" key={item.id}>
              <small>Possible {item.type} · Detected from Gmail</small>
              <h3>{item.title}</h3>
              {(item.deadline || item.start_time) && (
                <p>
                  {item.deadline ? "Due " : "Starts "}
                  {formatDate((item.deadline || item.start_time)!, zone)} ·{" "}
                  {formatTime((item.deadline || item.start_time)!, zone)}
                </p>
              )}
              <p>{item.reason}</p>
              {item.unresolved.length > 0 && (
                <p className="form-hint">Needs your review: {item.unresolved.join(". ")}</p>
              )}
              <div className="button-row">
                <button disabled={busy} onClick={() => setReview(item)}>
                  Review {item.title}
                </button>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() =>
                    propose(item, { action: "dismiss", title: item.title, revision: item.revision })
                  }
                >
                  Dismiss {item.title}
                </button>
              </div>
            </article>
          ))}
        </div>
        {proposals.map((p) => (
          <ProposalCard
            key={p.id}
            proposal={p}
            onDone={() => {
              void load().catch((e) => setError((e as Error).message));
            }}
          />
        ))}
      </div>
      {review && (
        <CommitmentEditor
          key={`${review.id}:${review.revision}`}
          item={review}
          zone={zone}
          busy={busy}
          externalError={error}
          onClose={() => setReview(null)}
          onPropose={(value) => propose(review, value)}
        />
      )}
      {disconnect && (
        <Modal title={`Disconnect ${disconnect.name}?`} onClose={() => setDisconnect(null)}>
          <p>
            {disconnect.id === "gmail"
              ? "Remove Gmail access, source metadata and unconfirmed commitments from Xenon. Approved tasks and events remain."
              : "Remove imported Google events from Xenon. Your Google calendar remains unchanged."}
          </p>
          {disconnect.id === "gmail" && (
            <label>
              <input
                type="checkbox"
                checked={revoke}
                onChange={(e) => setRevoke(e.target.checked)}
              />
              Also revoke Google access. This may require reconnecting Google Calendar because
              Google shares grants for this app.
            </label>
          )}
          <button
            className="danger"
            disabled={busy}
            onClick={() =>
              run(async () => {
                if (disconnect.id === "gmail") {
                  const result = await api.gmailDisconnect(revoke);
                  setNotice(result.warning || "Gmail disconnected.");
                } else {
                  await api.googleDisconnect();
                  setNotice("Google Calendar disconnected.");
                }
                setDisconnect(null);
              })
            }
          >
            Confirm disconnect
          </button>
        </Modal>
      )}
    </section>
  );
}

function CommitmentEditor({
  item,
  zone,
  busy,
  externalError,
  onClose,
  onPropose,
}: {
  item: Commitment;
  zone: string;
  busy: boolean;
  externalError: string;
  onClose: () => void;
  onPropose: (value: CommitmentReview) => Promise<void>;
}) {
  const [action, setAction] = useState<CommitmentReview["action"]>(
    item.type === "deadline" || item.type === "task" ? "schedule" : "event",
  );
  const [error, setError] = useState("");
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    const form = new FormData(e.currentTarget);
    try {
      const instant = (key: string) =>
        form.get(key) ? toInstant(String(form.get(key)), zone) : null;
      await onPropose({
        action,
        revision: item.revision,
        title: String(form.get("title")),
        deadline: action !== "event" ? instant("deadline") : null,
        start_time: action === "event" ? instant("start") : null,
        end_time: action === "event" ? instant("end") : null,
        estimated_duration_minutes: action !== "event" ? Number(form.get("duration")) : null,
      });
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <Modal title="Review commitment" onClose={onClose}>
      <form className="settings-form" onSubmit={submit}>
        <p>
          Detected type: {item.type}. All times in {zone}. Confirm or correct the details before
          creating a proposal.
        </p>
        <label>
          Title
          <input name="title" defaultValue={item.title} required maxLength={200} />
        </label>
        <label>
          Action
          <select
            value={action}
            onChange={(e) => setAction(e.target.value as CommitmentReview["action"])}
          >
            <option value="task">Add as task</option>
            <option value="event">Add to calendar</option>
            <option value="schedule">Schedule with Xenon</option>
          </select>
        </label>
        {action === "event" ? (
          <div key="event-fields">
            <label>
              Start time
              <input
                name="start"
                type="datetime-local"
                required
                defaultValue={item.start_time ? localInput(item.start_time, zone) : ""}
              />
            </label>
            <label>
              End time
              <input
                name="end"
                type="datetime-local"
                required
                defaultValue={item.end_time ? localInput(item.end_time, zone) : ""}
              />
            </label>
          </div>
        ) : (
          <div key="task-fields">
            <label>
              Deadline
              <input
                name="deadline"
                type="datetime-local"
                required={action === "schedule"}
                defaultValue={item.deadline ? localInput(item.deadline, zone) : ""}
              />
            </label>
            <label>
              Estimated duration · minutes
              <input
                name="duration"
                type="number"
                min={5}
                max={10080}
                required
                defaultValue={item.estimated_duration_minutes ?? ""}
              />
            </label>
          </div>
        )}
        <details>
          <summary>Source email information</summary>
          <p>{item.subject}</p>
          <p>From: {item.sender}</p>
          <p>{item.snippet}</p>
          {item.received_at && (
            <p>
              Received {formatDate(item.received_at, zone)} · {formatTime(item.received_at, zone)}
            </p>
          )}
          <p>
            Detection confidence: {Math.round(item.confidence * 100)}% · Please verify against the
            email.
          </p>
        </details>
        {item.unresolved.length > 0 && <p>{item.unresolved.join(". ")}</p>}
        <ErrorBox message={error || externalError} />
        <button disabled={busy}>{busy ? "Preparing…" : "Preview proposal"}</button>
        <small>This step creates a proposal. Nothing is added until you confirm it.</small>
      </form>
    </Modal>
  );
}
