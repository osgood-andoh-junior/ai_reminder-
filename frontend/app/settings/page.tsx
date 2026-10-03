"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Save, Sparkles, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { Preferences } from "@/lib/types";
import { useAuth } from "@/components/provider";
import { ErrorBox, Heading } from "@/components/ui";
import { IntegrationHub } from "@/components/integration-hub";
import { ContactsPanel } from "@/components/meetings";
import { NotificationSettings } from "@/components/notification-settings";
import { activityMessage, type Activity } from "@/lib/activity";
export default function Settings() {
  const { user, preferences, refresh } = useAuth();
  const [draft, setDraft] = useState<Preferences | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<
    { message: string; changes: Partial<Preferences> }[]
  >([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  useEffect(() => {
    if (preferences) setDraft({ ...preferences });
  }, [preferences]);
  const load = useCallback(async () => {
    try {
      const [s, a] = await Promise.all([api.suggestions(), api.activity()]);
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
      email_notifications_enabled: preferences?.email_notifications_enabled ?? false,
      in_app_notifications_enabled: preferences?.in_app_notifications_enabled ?? true,
      reminder_stages: preferences?.reminder_stages ?? [],
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
      setNotice("Preferences saved.");
    });
  }
  return (
    <div className="page settings-page">
      <Heading
        eyebrow="YOUR DAY, YOUR WAY"
        title="Settings"
        description="Your time, your preferences. Make Xenon work for you."
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
                <small>Choose your local timezone, such as Africa/Accra.</small>
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
                Default reminder lead time · minutes
                <input
                  type="number"
                  min={0}
                  max={10080}
                  required
                  aria-describedby="legacy-reminder-hint"
                  name="default_reminder_minutes"
                  value={draft.default_reminder_minutes}
                  onChange={(e) => field("default_reminder_minutes", Number(e.target.value))}
                />
              </label>
              <p id="legacy-reminder-hint" className="form-hint">
                Saved for older reminders. For scheduled sessions, choose reminder timings in
                Notifications.
              </p>
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
                    Xenon suggests changes after repeated behavior. You decide whether to apply
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
              <h2>Voice</h2>
            </div>
            <div className="panel-body">
              <p>
                Type or speak to Xenon. Automatic response playback can be turned on in the
                conversation’s options.
              </p>
              <Link className="text-link" href="/assistant">
                Open Xenon voice options
              </Link>
            </div>
          </section>
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
          <IntegrationHub />
          <ContactsPanel />
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
              <p className="form-hint">
                Past delivery attempts are shown here. A browser or email failure does not mean the
                in-app reminder failed.
              </p>
              <Link className="text-link" href="/reminders">
                View your reminders
              </Link>
              {activity.slice(0, 8).map((a) => {
                const message = activityMessage(a);
                return (
                  <div key={a.id}>
                    <span>
                      {message.title}
                      {message.detail && (
                        <small className="activity-detail">{message.detail}</small>
                      )}
                    </span>
                    <time dateTime={a.created_at}>
                      {new Date(a.created_at).toLocaleString(undefined, {
                        timeZone: preferences?.timezone || "UTC",
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </time>
                  </div>
                );
              })}
              {!activity.length && <p className="muted">Your activity will appear here.</p>}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
