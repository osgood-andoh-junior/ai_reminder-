import type { Dashboard } from "./types";

export function dayItems(data: Dashboard) {
  return [
    ...data.events.map((e) => ({
      id: `e${e.id}`,
      title: e.title,
      start: e.start_time,
      end: e.end_time,
      type: e.event_type,
      href: "/calendar",
    })),
    ...data.sessions
      .filter((s) => s.status === "SCHEDULED")
      .map((s) => ({
        id: `s${s.id}`,
        title: data.tasks.find((t) => t.id === s.task_id)?.title || "Focus session",
        start: s.start_time,
        end: s.end_time,
        type: "Focus",
        href: `/tasks#task-${s.task_id}`,
      })),
  ].sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
}

export function dayContext(data: Dashboard, now: number) {
  const items = dayItems(data);
  return {
    items,
    current: items.filter((item) => Date.parse(item.start) <= now && Date.parse(item.end) > now),
    next: items.find((item) => Date.parse(item.start) > now),
    conflicts: items.filter((a, i) =>
      items.some(
        (b, j) =>
          i !== j &&
          Date.parse(a.start) < Date.parse(b.end) &&
          Date.parse(b.start) < Date.parse(a.end),
      ),
    ),
    overdue: data.tasks.filter(
      (t) =>
        t.deadline &&
        Date.parse(t.deadline) < now &&
        !["COMPLETED", "CANCELLED"].includes(t.status),
    ),
  };
}

export function greeting(now: number, zone: string) {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: zone }).format(
      now,
    ),
  );
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}
