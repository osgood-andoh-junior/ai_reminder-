"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Event, MeetingDraft, MeetingResult, Proposal } from "@/lib/types";
import { useAuth } from "@/components/provider";
import { ErrorBox, Modal } from "@/components/ui";
import { formatDate, formatTime, localInput, toInstant } from "@/lib/time";

export const responseLabel = (status?: string) =>
  ({
    accepted: "Accepted",
    tentative: "Tentative",
    declined: "Declined",
    needsAction: "Awaiting response",
  })[status || "needsAction"] || "Awaiting response";
function safeLink(value?: string | null) {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? value : undefined;
  } catch {
    return undefined;
  }
}
export function MeetingDetails({ event }: { event: Event }) {
  const info = event.meeting_metadata;
  if (!info) return null;
  return (
    <div className="meeting-details">
      {info.attendees.map((a) => (
        <p key={a.email || a.name}>
          {a.name || a.email} — {responseLabel(a.response_status)}
        </p>
      ))}
      {safeLink(info.meet_url) ? (
        <a href={safeLink(info.meet_url)} target="_blank" rel="noreferrer">
          Join meeting
        </a>
      ) : info.conference_status === "failure" ? (
        <p role="status">
          Meeting saved, but Google Meet creation failed. Add a link in Google Calendar.
        </p>
      ) : info.conference_status === "pending" ? (
        <p>Google Meet is being created. Refresh responses shortly.</p>
      ) : null}
      {safeLink(info.calendar_url) && (
        <a href={safeLink(info.calendar_url)} target="_blank" rel="noreferrer">
          Open in Calendar
        </a>
      )}
    </div>
  );
}

export function MeetingEditor({
  initial,
  eventId,
  day,
  onClose,
  onProposed,
}: {
  initial?: MeetingDraft;
  eventId?: number;
  day: string;
  onClose: () => void;
  onProposed: (p: Proposal) => void;
}) {
  const { preferences } = useAuth();
  const zone = preferences?.timezone || "Africa/Accra";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<MeetingResult | null>(null);
  const [draft, setDraft] = useState<MeetingDraft | null>(null);
  const [attendees, setAttendees] = useState(initial?.attendees || [{ name: "", email: "" }]);
  async function propose(value: MeetingDraft) {
    setBusy(true);
    setError("");
    setResult(null);
    setDraft(value);
    try {
      const response = await api.proposeMeeting(value, eventId);
      setResult(response);
      if (response.proposal) onProposed(response.proposal);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={eventId ? "Edit meeting" : "Invite someone"} onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          try {
            await propose({
              title: String(f.get("title")),
              description: String(f.get("description")),
              start_time: toInstant(String(f.get("start")), zone),
              duration_minutes: Number(f.get("duration")),
              attendees: attendees.map((a) => ({ name: a.name, email: a.email || null })),
              location: String(f.get("location")),
              google_meet: f.get("meet") === "on",
            });
          } catch (e) {
            setError((e as Error).message);
          }
        }}
      >
        <label>
          Title
          <input name="title" required maxLength={200} defaultValue={initial?.title} />
        </label>
        <label>
          Starts · {zone}
          <input
            name="start"
            type="datetime-local"
            required
            defaultValue={initial ? localInput(initial.start_time, zone) : `${day}T09:00`}
          />
        </label>
        <label>
          Duration in minutes
          <input
            name="duration"
            type="number"
            min={5}
            max={1440}
            required
            defaultValue={initial?.duration_minutes || 30}
          />
        </label>
        <fieldset>
          <legend>Attendees</legend>
          {attendees.map((a, i) => (
            <div className="meeting-attendee" key={i}>
              <label>
                Name {i + 1}
                <input
                  value={a.name}
                  maxLength={100}
                  onChange={(e) =>
                    setAttendees(
                      attendees.map((p, j) => (j === i ? { ...p, name: e.target.value } : p)),
                    )
                  }
                />
              </label>
              <label>
                Email {i + 1}
                <input
                  type="email"
                  value={a.email || ""}
                  onChange={(e) =>
                    setAttendees(
                      attendees.map((p, j) => (j === i ? { ...p, email: e.target.value } : p)),
                    )
                  }
                />
              </label>
              {(attendees.length > 1 || eventId) && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setAttendees(attendees.filter((_, j) => j !== i))}
                >
                  Remove attendee {i + 1}
                </button>
              )}
            </div>
          ))}
          <small>
            Leave email blank only for an unambiguous saved contact. Contacts are never saved
            automatically.
          </small>
          <button
            type="button"
            className="secondary"
            disabled={attendees.length >= 100}
            onClick={() => setAttendees([...attendees, { name: "", email: "" }])}
          >
            Add attendee
          </button>
        </fieldset>
        <label>
          Location
          <input name="location" maxLength={500} defaultValue={initial?.location} />
        </label>
        <label className="check">
          <input name="meet" type="checkbox" defaultChecked={initial?.google_meet} />
          Create Google Meet link
        </label>
        {eventId && <small>Any existing meeting link will be kept.</small>}
        <label>
          Description
          <textarea name="description" maxLength={5000} defaultValue={initial?.description} />
        </label>
        <p>Google Calendar will send invitations or updates after you review and confirm.</p>
        <ErrorBox message={error} />
        {result?.missing_contacts?.map((a) => (
          <p role="alert" key={a.name}>
            What email address should I use for {a.name}?
            {a.reason === "ambiguous" && " More than one saved contact matches."}
          </p>
        ))}
        {result?.alternatives && (
          <div>
            <p>{result.message}</p>
            {result.alternatives.length === 0 && (
              <p>No free time found in the next week. Choose another date.</p>
            )}
            {result.alternatives.map((slot) => (
              <button
                type="button"
                className="secondary"
                disabled={busy}
                key={slot.start}
                onClick={() => draft && void propose({ ...draft, start_time: slot.start })}
              >
                {formatDate(slot.start, zone)} · {formatTime(slot.start, zone)}
              </button>
            ))}
          </div>
        )}
        <button disabled={busy}>{busy ? "Checking your calendar…" : "Review invitation"}</button>
      </form>
    </Modal>
  );
}

export function MeetingProposal({ proposal, onDone }: { proposal: Proposal; onDone: () => void }) {
  const { preferences, refresh } = useAuth();
  const zone = preferences?.timezone || "Africa/Accra";
  const [current, setCurrent] = useState(proposal);
  const [status, setStatus] = useState(proposal.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [receipt, setReceipt] = useState<{ message: string; meeting?: Event } | null>(null);
  const cancel = current.kind === "meeting_cancel";
  const meeting = current.payload.meeting;
  const before = current.payload.before;
  const shown = meeting || before;
  async function decide(accept: boolean) {
    setBusy(true);
    setError("");
    try {
      const response = await api.decideMeeting(current.id, accept);
      setReceipt(response);
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
    <section className="proposal meeting-proposal">
      <div className="proposal-title">
        <b>
          {cancel
            ? "Cancel meeting"
            : current.kind === "meeting_update"
              ? "Change meeting"
              : "Meeting invitation"}
        </b>
        <span className="pill">For your review</span>
      </div>
      <h3>{shown?.title}</h3>
      {before && meeting && (
        <p>
          From: {formatDate(before.start_time, zone)} · {formatTime(before.start_time, zone)} –{" "}
          {formatTime(before.end_time, zone)}
        </p>
      )}
      {shown?.start_time && (
        <p>
          {before && meeting ? "To: " : ""}
          {formatDate(shown.start_time, zone)} · {formatTime(shown.start_time, zone)} –{" "}
          {formatTime(shown.end_time, zone)} · {zone}
        </p>
      )}
      {shown?.attendees.map((a) => (
        <p key={a.email || a.name}>
          <b>{a.name}</b> {a.email}
        </p>
      ))}
      {before && meeting && (
        <p>
          Previously invited: {before.attendees.map((a) => a.email).join(", ") || "No attendees"}
        </p>
      )}
      {meeting?.location && <p>Location: {meeting.location}</p>}
      {meeting?.description && <p>{meeting.description}</p>}
      {meeting?.google_meet && <p>Google Meet: will be created if no link exists</p>}
      {!cancel && <p>You’re free during this time. Attendee availability is unknown.</p>}
      <p>
        Google Calendar will{" "}
        {cancel ? "notify attendees of the cancellation" : "send invitations or updates"} after you
        confirm.
      </p>
      <ErrorBox message={error} />
      {status === "PENDING" ? (
        <div className="proposal-footer">
          <button disabled={busy || editing} onClick={() => void decide(true)}>
            {busy
              ? "Saving…"
              : cancel
                ? "Confirm cancellation"
                : current.kind === "meeting_update"
                  ? "Confirm change"
                  : "Confirm & Send"}
          </button>
          {meeting && (
            <button
              className="secondary"
              disabled={busy || editing}
              onClick={() => setEditing(true)}
            >
              Edit
            </button>
          )}
          <button
            className="secondary"
            disabled={busy || editing}
            onClick={() => void decide(false)}
          >
            Cancel
          </button>
          <small>Review by {formatTime(current.expires_at, zone)}</small>
        </div>
      ) : (
        <p role="status">
          {receipt?.message || (status === "ACCEPTED" ? "Meeting changes saved" : "Not applied")}
        </p>
      )}
      {receipt?.meeting && <MeetingDetails event={receipt.meeting} />}
      {editing && meeting && (
        <MeetingEditor
          initial={meeting}
          eventId={current.payload.event_id || undefined}
          day={meeting.start_time.slice(0, 10)}
          onClose={() => setEditing(false)}
          onProposed={(p) => {
            setBusy(true);
            void api
              .decideMeeting(current.id, false)
              .then(() => {
                setCurrent(p);
                setEditing(false);
                onDone();
              })
              .catch(async (e) => {
                setError((e as Error).message);
                await api.decideMeeting(p.id, false).catch(() => {});
              })
              .finally(() => setBusy(false));
          }}
        />
      )}
    </section>
  );
}

export function ContactsPanel() {
  const [contacts, setContacts] = useState<import("@/lib/types").Contact[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  async function load() {
    setBusy(true);
    setError("");
    try {
      setContacts(await api.contacts());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card">
      <h2>Meeting contacts</h2>
      <p>Saved only for your account. Remembering a contact requires confirmation.</p>
      <button className="secondary" disabled={busy} onClick={() => void load()}>
        {busy ? "Loading…" : "Review saved contacts"}
      </button>
      {contacts?.length === 0 && <p>No saved contacts.</p>}
      {contacts?.map((c) => (
        <div className="meeting-attendee" key={c.id}>
          <p>
            {c.name} · {c.email}
          </p>
          <button
            className="secondary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await api.deleteContact(c.id);
                await load();
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Delete {c.name}
          </button>
        </div>
      ))}
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setBusy(true);
          setError("");
          try {
            setProposal(
              await api.proposeContact({
                name: String(f.get("name")),
                email: String(f.get("email")),
              }),
            );
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Contact name
          <input name="name" required maxLength={100} />
        </label>
        <label>
          Contact email
          <input name="email" type="email" required />
        </label>
        <button disabled={busy || !!proposal}>Review contact</button>
      </form>
      {proposal && (
        <div className="proposal">
          <p>
            Remember {proposal.payload.name} · {proposal.payload.email}?
          </p>
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await api.decideMeeting(proposal.id, true);
                setProposal(null);
                await load();
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Confirm contact
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api.decideMeeting(proposal.id, false);
                setProposal(null);
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Cancel
          </button>
        </div>
      )}
      <ErrorBox message={error} />
    </section>
  );
}
