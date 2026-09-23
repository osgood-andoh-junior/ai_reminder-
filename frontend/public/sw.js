/* Dedicated notification worker. It does not cache authenticated pages or API data. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

function claimOccurrence(key) {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("tempo-notifications", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("shown");
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result;
      const tx = db.transaction("shown", "readwrite");
      const store = tx.objectStore("shown");
      let fresh = false;
      const found = store.get(key);
      found.onsuccess = () => {
        if (!found.result) {
          store.put(Date.now(), key);
          fresh = true;
        }
      };
      const cursor = store.openCursor();
      cursor.onsuccess = () => {
        const item = cursor.result;
        if (item) {
          if (item.value < Date.now() - 7 * 86400000) item.delete();
          item.continue();
        }
      };
      tx.oncomplete = () => {
        db.close();
        resolve(fresh);
      };
      tx.onerror = () => {
        db.close();
        reject(tx.error);
      };
    };
  });
}

async function currentReminder(data) {
  const response = await fetch(`/api/reminders/${Number(data.reminder_id)}`, {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) return null;
  const reminder = await response.json();
  return reminder.user_id === data.user_id &&
    reminder.generation === data.generation &&
    reminder.status === "SENT"
    ? reminder
    : null;
}

self.addEventListener("push", (event) => {
  event.waitUntil(
    (async () => {
      const data = event.data?.json();
      if (!data || !Number.isInteger(data.reminder_id)) return;
      // Revalidate the current session before showing any task content, including after logout/account switching.
      const reminder = await currentReminder(data);
      if (!reminder) return;
      const tag = `tempo-${data.user_id}-${data.reminder_id}-${data.generation}`;
      if (!(await claimOccurrence(tag))) return;
      const scheduled = reminder.scheduled_start
        ? ` Scheduled for ${new Intl.DateTimeFormat(undefined, { timeZone: reminder.timezone, dateStyle: "medium", timeStyle: "short" }).format(new Date(reminder.scheduled_start))}.`
        : "";
      await self.registration.showNotification(reminder.title || "Tempo", {
        body: reminder.message + scheduled,
        tag,
        renotify: false,
        data: { ...data, url: reminder.task_id ? `/tasks#task-${reminder.task_id}` : "/reminders" },
        actions: [
          { action: "open", title: "Open Tempo" },
          { action: "snooze", title: "Snooze 30 min" },
          { action: "dismiss", title: "Dismiss" },
        ],
      });
      for (const client of await self.clients.matchAll({ type: "window" }))
        client.postMessage({ type: "reminders-changed" });
    })(),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    (async () => {
      const data = event.notification.data;
      const reminder = await currentReminder(data);
      if (reminder && ["snooze", "dismiss"].includes(event.action)) {
        const response = await fetch(`/api/reminders/${data.reminder_id}/${event.action}`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-Requested-With": "Tempo" },
          ...(event.action === "snooze" ? { body: JSON.stringify({ minutes: 30 }) } : {}),
        });
        if (response.ok) {
          for (const client of await self.clients.matchAll({ type: "window" }))
            client.postMessage({ type: "reminders-changed" });
          return;
        }
      }
      const url = new URL(reminder ? data.url : "/reminders", self.location.origin);
      if (url.origin !== self.location.origin) return;
      for (const client of await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      })) {
        if (new URL(client.url).origin === url.origin && "focus" in client) {
          await client.navigate(url.href);
          await client.focus();
          return;
        }
      }
      await self.clients.openWindow(url.href);
    })(),
  );
});
