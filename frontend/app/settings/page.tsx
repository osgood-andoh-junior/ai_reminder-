"use client";
import { useCallback, useEffect, useState } from "react";
import { Save, Link2, RefreshCw, Sparkles, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { Preferences } from "@/lib/types";
import { useAuth } from "@/components/provider";
import { ErrorBox, Heading, Modal } from "@/components/ui";
import { NotificationSettings } from "@/components/notification-settings";
export default function Settings() {
  const { user, preferences, refresh } = useAuth();
  const [draft, setDraft] = useState<Preferences | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [disconnect, setDisconnect] = useState(false);
  const [google, setGoogle] = useState<{
    configured: boolean;
    connected: boolean;
    synced_at: string | null;
  } | null>(null);
  const [suggestions, setSuggestions] = useState<
    { message: string; changes: Partial<Preferences> }[]
  >([]);
  const [activity, setActivity] = useState<{ id: number; action: string; created_at: string }[]>(
    [],
  );
  useEffect(() => {
    if (preferences) setDraft({ ...preferences });
  }, [preferences]);
  const load = useCallback(async () => {
    try {
      const [g, s, a] = await Promise.all([api.googleStatus(), api.suggestions(), api.activity()]);
      setGoogle(g);
      setSuggestions(s);
      setActivity(a);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const field = <K extends keyof Preferences>(key: K, value: Preferences[K]) =>
    setDraft((d) => (d ? { ...d, [key]: value } : d));
  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!draft) return;
    const form = new FormData(e.currentTarget);
    const values: Preferences = {
      browser_notifications_enabled: preferences?.browser_notifications_enabled || false,
      email_notifications_enabled: false,
      deadline_reminders_enabled: form.has("deadline_reminders_enabled"),
      timezone: String(form.get("timezone")),
      preferred_start_time: String(form.get("preferred_start_time")),
      preferred_end_time: String(form.get("preferred_end_time")),
      preferred_days: form.getAll("preferred_days").map(Number),
      default_reminder_minutes: Number(form.get("default_reminder_minutes")),
      preferred_task_length: Number(form.get("preferred_task_length")),
      break_preference: Number(form.get("break_preference")),
      allow_weekend_scheduling: form.has("allow_weekend_scheduling"),
      personalization_enabled: form.has("personalization_enabled"),
    };
    await run(async () => {
      await api.savePreferences(values);
      await refresh();
      setNotice("Your preferences have been saved.");
    });
  }
  return (
    <div className="page settings-page">
      <Heading
        eyebrow="YOUR DAY, YOUR WAY"
        title="Find your natural rhythm."
        description="A few preferences help us build a plan that feels like you."
      />
      <ErrorBox message={error} />
      {notice && (
        <div className="success-box" role="status">
          {notice}
        </div>
      )}
      <div className="settings-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>Scheduling preferences</h2>
            <span className="pill">PERSONAL</span>
          </div>
          {draft && (
            <form className="settings-form" onSubmit={save}>
              <label>
                Timezone
                <input
                  name="timezone"
                  value={draft.timezone}
                  onChange={(e) => field("timezone", e.target.value)}
                  list="timezones"
                  required
                />
                <datalist id="timezones">
                  {[
                    "Africa/Accra",
                    "Africa/Lagos",
                    "Europe/London",
                    "America/New_York",
                    "America/Los_Angeles",
                    "Asia/Kolkata",
                    "Asia/Tokyo",
                    "Australia/Sydney",
                    "UTC",
                  ].map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </datalist>
                <small>Use an IANA timezone, such as Africa/Accra.</small>
              </label>
              <div className="form-grid">
                <label>
                  Preferred start
                  <input
                    type="time"
                    required
                    name="preferred_start_time"
                    key={draft.preferred_start_time}
                    defaultValue={draft.preferred_start_time}
                  />
                </label>
                <label>
                  Preferred end
                  <input
                    type="time"
                    required
                    name="preferred_end_time"
                    key={draft.preferred_end_time}
                    defaultValue={draft.preferred_end_time}
                  />
                </label>
              </div>
              <fieldset>
                <legend>Preferred days</legend>
                <div className="day-toggles">
                  {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d, i) => (
                    <label key={d} className={draft.preferred_days.includes(i) ? "selected" : ""}>
                      <input
                        type="checkbox"
                        name="preferred_days"
                        value={i}
                        checked={draft.preferred_days.includes(i)}
                        onChange={(e) =>
                          field(
                            "preferred_days",
                            e.target.checked
                              ? [...draft.preferred_days, i]
                              : draft.preferred_days.filter((x) => x !== i),
                          )
                        }
                      />
                      {d}
                    </label>
                  ))}
                </div>
              </fieldset>
              <label className="check-label">
                <input
                  type="checkbox"
                  name="allow_weekend_scheduling"
                  checked={draft.allow_weekend_scheduling}
                  onChange={(e) => field("allow_weekend_scheduling", e.target.checked)}
                />
                <span>
                  Allow scheduling on weekends
                  <small>Turn this off to keep Saturday and Sunday free.</small>
                </span>
              </label>
              <div className="form-grid">
                <label>
                  Session length · minutes
                  <input
                    type="number"
                    min={15}
                    max={240}
                    required
                    name="preferred_task_length"
                    value={draft.preferred_task_length}
                    onChange={(e) => field("preferred_task_length", Number(e.target.value))}
                  />
                </label>
                <label>
                  Break between sessions · minutes
                  <input
                    type="number"
                    min={0}
                    max={120}
                    required
                    name="break_preference"
                    value={draft.break_preference}
                    onChange={(e) => field("break_preference", Number(e.target.value))}
                  />
                </label>
              </div>
              <label>
                Remind me before sessions · minutes
                <input
                  type="number"
                  min={0}
                  max={10080}
                  required
                  name="default_reminder_minutes"
                  value={draft.default_reminder_minutes}
                  onChange={(e) => field("default_reminder_minutes", Number(e.target.value))}
                />
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  name="personalization_enabled"
                  checked={draft.personalization_enabled}
                  onChange={(e) => field("personalization_enabled", e.target.checked)}
                />
                <span>
                  Learn from my scheduling patterns
                  <small>
                    Tempo suggests changes after repeated behavior. You decide whether to apply
                    them.
                  </small>
                </span>
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  name="deadline_reminders_enabled"
                  checked={draft.deadline_reminders_enabled}
                  onChange={(e) => field("deadline_reminders_enabled", e.target.checked)}
                />
                <span>
                  Deadline reminders
                  <small>Remind me one day and one hour before active task deadlines.</small>
                </span>
              </label>
              <p className="form-hint">
                Preferred hours are a ranking preference. If necessary, a proposal may use other
                hours between 06:00 and 23:00 to meet a deadline.
              </p>
              <button disabled={busy}>
                <Save size={17} />
                {busy ? "Saving…" : "Save preferences"}
              </button>
            </form>
          )}
        </section>
        <div className="settings-side">
          <NotificationSettings />
          <section className="panel">
            <div className="panel-heading">
              <h2>Your account</h2>
              <ShieldCheck size={18} />
            </div>
            <div className="panel-body">
              <b>{user?.name}</b>
              <p>{user?.email}</p>
              <p className="form-hint">
                Your tasks, calendar, and conversations are private to your account.
              </p>
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>Google Calendar</h2>
              <Link2 size={18} />
            </div>
            <div className="panel-body">
              <p>
                {google?.connected
                  ? "Your Google Calendar is connected."
                  : "Bring your existing commitments into your plan."}
              </p>
              {google?.synced_at && (
                <small className="muted">
                  Last synced {new Date(google.synced_at).toLocaleString()}
                </small>
              )}
              {google?.configured === false && (
                <p className="form-hint">
                  Google OAuth is not configured yet. Your internal calendar works independently.
                </p>
              )}
              <div className="button-row">
                {google?.connected ? (
                  <>
                    <button
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          const result = await api.googleSync();
                          setNotice(
                            `Synced ${result.imported} events.${result.conflicts.length ? ` Conflicts affect task IDs ${result.conflicts.join(", ")}; replan these tasks.` : ""}`,
                          );
                        })
                      }
                    >
                      <RefreshCw size={15} />
                      Sync now
                    </button>
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() => setDisconnect(true)}
                    >
                      Disconnect
                    </button>
                  </>
                ) : (
                  <button
                    disabled={busy || !google?.configured}
                    onClick={() =>
                      run(async () => {
                        const result = await api.googleConnect();
                        window.location.assign(result.url);
                      })
                    }
                  >
                    <Link2 size={15} />
                    Connect Google
                  </button>
                )}
              </div>
              <p className="form-hint">
                Sync imports your primary calendar from 30 days ago through the next 90 days. Edit
                imported events in Google, then sync again.
              </p>
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>Learning your rhythm</h2>
              <Sparkles size={18} />
            </div>
            <div className="panel-body">
              {suggestions.length ? (
                suggestions.map((s, i) => (
                  <div key={i}>
                    <p>{s.message}</p>
                    <button
                      className="secondary"
                      onClick={() => {
                        setDraft((d) => (d ? { ...d, ...s.changes } : d));
                        setNotice(
                          "Suggestion added to the form. Review it and select Save preferences to confirm.",
                        );
                      }}
                    >
                      Review suggestion
                    </button>
                  </div>
                ))
              ) : (
                <p className="muted">
                  As you adjust your plans, repeated patterns can become helpful suggestions.
                </p>
              )}
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>Recent activity</h2>
            </div>
            <div className="panel-body activity-list">
              {activity.slice(0, 8).map((a) => (
                <div key={a.id}>
                  <span>{a.action.toLowerCase().replaceAll("_", " ")}</span>
                  <small>{new Date(a.created_at).toLocaleDateString()}</small>
                </div>
              ))}
              {!activity.length && <p className="muted">Your activity will appear here.</p>}
            </div>
          </section>
        </div>
      </div>
      {disconnect && (
        <Modal title="Disconnect Google Calendar?" onClose={() => setDisconnect(false)}>
          <p>
            Imported Google events will be removed from Tempo. Your Google calendar remains
            unchanged.
          </p>
          <button
            disabled={busy}
            className="danger"
            onClick={() =>
              run(async () => {
                await api.googleDisconnect();
                setDisconnect(false);
                setNotice(
                  "Disconnected. You can revoke Tempo access in your Google account permissions.",
                );
              })
            }
          >
            Disconnect
          </button>
        </Modal>
      )}
    </div>
  );
}
