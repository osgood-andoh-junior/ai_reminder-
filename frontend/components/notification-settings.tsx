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

export function NotificationSettings() {
  const { preferences, refresh } = useAuth();
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
      setNotice("Browser push is enabled on this device. Keep the reminder worker running.");
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
      setNotice("Browser delivery is off. In-app reminders remain enabled.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Notifications</h2>
      </div>
      <div className="panel-body">
        <p>
          In-app reminders are always available. Browser push can reach you when this tab is in the
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
            Web Push needs server configuration. See the notification setup guide for VAPID keys.
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
        <p className="form-hint">Email delivery is not configured. No emails will be sent.</p>
        <ErrorBox message={error} />
        {notice && <p role="status">{notice}</p>}
      </div>
    </section>
  );
}
