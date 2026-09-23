"use client";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { notificationsChanged } from "@/lib/notifications";
import { toInstant } from "@/lib/time";
import type { Reminder } from "@/lib/types";
import { ErrorBox, Modal } from "./ui";

export function ReminderActions({
  reminder,
  zone,
  onChange,
}: {
  reminder: Reminder;
  zone: string;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [snooze, setSnooze] = useState(false);
  const [error, setError] = useState("");
  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      setSnooze(false);
      notificationsChanged();
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const active = ["PENDING", "SENT", "READ", "SNOOZED"].includes(reminder.status);
  return (
    <div className="reminder-actions">
      <div className="button-row">
        {reminder.task_id && (
          <Link className="text-link" href={`/tasks#task-${reminder.task_id}`}>
            Open task
          </Link>
        )}
        {reminder.status === "SENT" && (
          <button
            className="secondary small-button"
            disabled={busy}
            onClick={() => run(() => api.readReminder(reminder.id))}
          >
            Mark read
          </button>
        )}
        {active && (
          <>
            <button
              className="secondary small-button"
              disabled={busy}
              onClick={() => setSnooze(true)}
            >
              Snooze
            </button>
            <button
              className="secondary small-button"
              disabled={busy}
              onClick={() => run(() => api.dismissReminder(reminder.id))}
            >
              Dismiss
            </button>
          </>
        )}
      </div>
      <ErrorBox message={error} />
      {snooze && (
        <Modal title="Snooze reminder" onClose={() => setSnooze(false)}>
          <p>{reminder.title}</p>
          <div className="button-row">
            {[10, 30, 60].map((minutes) => (
              <button
                key={minutes}
                disabled={busy}
                className="secondary"
                onClick={() => run(() => api.snoozeReminder(reminder.id, { minutes }))}
              >
                {minutes === 60 ? "1 hour" : `${minutes} minutes`}
              </button>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const value = new FormData(e.currentTarget).get("until");
              void run(async () =>
                api.snoozeReminder(reminder.id, { until: toInstant(String(value), zone) }),
              );
            }}
          >
            <label>
              Custom time · {zone}
              <input name="until" type="datetime-local" required />
            </label>
            <ErrorBox message={error} />
            <button disabled={busy}>Snooze until this time</button>
          </form>
        </Modal>
      )}
    </div>
  );
}
