"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  applicationKey,
  pushSupported,
  registerNotifications,
  unsubscribeBrowser,
} from "@/lib/notifications";
import { useAuth } from "./provider";
import { ErrorBox } from "./ui";
import { reminderStages } from "@/lib/reminder-labels";

export function NotificationSettings() {
  const { user, preferences, refresh } = useAuth();
  const [supported, setSupported] = useState(false);
  const [permission, setPermission] = useState<NotificationPermission>("default");
  const [subscribed, setSubscribed] = useState(false);
  const [config, setConfig] = useState<Awaited<ReturnType<typeof api.notificationConfig>> | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const signupMessage = window.sessionStorage.getItem("verification-message");
    if (signupMessage) {
      setNotice(signupMessage);
      window.sessionStorage.removeItem("verification-message");
    }
    setSupported(pushSupported());
    if ("Notification" in window) setPermission(Notification.permission);
    void api
      .notificationConfig()
      .then(setConfig)
      .catch((e) => setError(e.message));
    if (pushSupported())
      void navigator.serviceWorker
        .getRegistration("/")
        .then(async (r) => setSubscribed(Boolean(await r?.pushManager.getSubscription())))
        .catch(() => {});
  }, []);
  async function verifyEmail() {
    setBusy(true);
    setError("");
    try {
      setNotice((await api.requestVerification()).message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function enable() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const granted =
        Notification.permission === "default"
          ? await Notification.requestPermission()
          : Notification.permission;
      setPermission(granted);
      if (granted !== "granted") return;
      const registration = await registerNotifications();
      let sub = await registration.pushManager.getSubscription();
      if (!sub)
        sub = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: applicationKey(config!.vapid_public_key),
        });
      try {
        await api.subscribePush(sub.toJSON());
      } catch (e) {
        await sub.unsubscribe();
        throw e;
      }
      setSubscribed(true);
      await refresh();
      setNotice("Browser notifications are on for this device.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function disable() {
    setBusy(true);
    setError("");
    try {
      await api.notificationPreferences({ browser_notifications_enabled: false });
      await unsubscribeBrowser();
      setSubscribed(false);
      await refresh();
      setNotice("Browser notifications are off for this device.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save(values: Partial<import("@/lib/types").Preferences>) {
    setBusy(true);
    setError("");
    try {
      await api.notificationPreferences(values);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const stages = reminderStages;
  const enabled = preferences?.reminder_stages || stages.map(([key]) => key);
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Notifications</h2>
      </div>
      <div className="panel-body">
        <p>
          Choose your reminder delivery channels. Browser push can reach you when this tab is in the
          background.
        </p>
        <p role="status">
          {!supported
            ? "This browser does not support Web Push here. Try Chrome, Edge or Firefox on localhost or HTTPS."
            : permission === "denied"
              ? "Notifications are blocked. Allow them in your browser's site settings, then reload this page."
              : permission === "granted"
                ? "Browser permission granted."
                : "Browser permission has not been requested."}
        </p>
        {config && !config.push_configured && (
          <p className="form-hint">
            Browser notifications are not available yet. The site administrator needs to finish
            setup.
          </p>
        )}
        <p>
          Browser delivery:{" "}
          {preferences?.browser_notifications_enabled && subscribed
            ? "On for this device"
            : "Off for this device"}
        </p>
        {preferences?.browser_notifications_enabled && subscribed ? (
          <button className="secondary" disabled={busy} onClick={disable}>
            Turn off browser notifications
          </button>
        ) : (
          <button
            disabled={busy || !supported || permission === "denied" || !config?.push_configured}
            onClick={enable}
          >
            Enable browser notifications
          </button>
        )}
        <fieldset disabled={busy}>
          <legend>Reminder delivery</legend>
          <label>
            <input
              type="checkbox"
              checked={preferences?.in_app_notifications_enabled ?? true}
              onChange={(e) => void save({ in_app_notifications_enabled: e.target.checked })}
            />{" "}
            In-app notifications
          </label>
          <label>
            <input
              type="checkbox"
              disabled={
                (!user?.email_verified_at || !config?.email_configured) &&
                !(preferences?.email_notifications_enabled && user?.email_reminders_opted_in_at)
              }
              checked={Boolean(
                preferences?.email_notifications_enabled && user?.email_reminders_opted_in_at,
              )}
              onChange={(e) => void save({ email_notifications_enabled: e.target.checked })}
            />{" "}
            Email reminders
          </label>
          <p>Email address: {user?.email}</p>
          <p role="status">
            {!user?.email_verified_at
              ? "Verify your email to receive task reminders directly in your inbox."
              : preferences?.email_notifications_enabled && user?.email_reminders_opted_in_at
                ? "Email verified, reminders enabled."
                : "Email verified, reminders disabled."}
          </p>
          {!user?.email_verified_at && (
            <button
              type="button"
              disabled={busy || !config?.email_configured}
              onClick={verifyEmail}
            >
              Send or resend verification email
            </button>
          )}
          {config?.email_last_delivery && (
            <p role="status">
              Latest reminder email:{" "}
              {config.email_last_delivery.status === "SENT"
                ? "Accepted by email provider (inbox receipt unconfirmed)"
                : config.email_last_delivery.status}
              {config.email_last_delivery.last_error
                ? ` (${config.email_last_delivery.last_error})`
                : ""}
            </p>
          )}
          {!config && <p role="status">Checking email availability…</p>}
          {config && !config.email_configured && (
            <p className="form-hint">
              Email reminders are unavailable until the site administrator connects an email
              service. No emails will be sent.
            </p>
          )}
        </fieldset>
        <fieldset disabled={busy}>
          <legend>Remind me</legend>
          {stages.map(([key, label]) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={enabled.includes(key)}
                onChange={(e) =>
                  void save({
                    reminder_stages: e.target.checked
                      ? [...enabled, key]
                      : enabled.filter((stage) => stage !== key),
                  })
                }
              />{" "}
              {label}
            </label>
          ))}
          <p className="form-hint">
            Changes update pending session reminders. Ask the assistant to customize a task.
          </p>
        </fieldset>
        <ErrorBox message={error} />
        {notice && <p role="status">{notice}</p>}
      </div>
    </section>
  );
}
