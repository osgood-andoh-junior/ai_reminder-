import type {
  User,
  Task,
  Event,
  Reminder,
  Preferences,
  Plan,
  Proposal,
  Message,
  Calendar,
  Dashboard,
  Action,
} from "./types";
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Requested-With": "Tempo" },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  } catch {
    throw new ApiError("Cannot reach the server. Check your connection and try again.", 0);
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.dispatchEvent(new window.Event("auth-expired"));
    const detail = data.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((e: { loc: string[]; msg: string }) => `${e.loc.slice(1).join(" ")}: ${e.msg}`)
              .join(". ")
          : detail?.message || "The request could not be completed.";
    throw new ApiError(message, response.status);
  }
  return data as T;
}
export const api = {
  me: () => request<User>("/auth/me"),
  login: (body: unknown) => request<User>("/auth/login", "POST", body),
  register: (body: unknown) => request<User>("/auth/register", "POST", body),
  logout: () => request("/auth/logout", "POST"),
  health: () => request<{ ai_configured: boolean }>("/health"),
  tasks: () => request<Task[]>("/tasks"),
  createTask: (body: unknown) => request<Task>("/tasks", "POST", body),
  updateTask: (id: number, body: unknown) => request<Task>(`/tasks/${id}`, "PATCH", body),
  deleteTask: (id: number) => request(`/tasks/${id}`, "DELETE"),
  events: () => request<Event[]>("/events"),
  saveEvent: (body: unknown, id?: number) =>
    request<Event>(id ? `/events/${id}` : "/events", id ? "PUT" : "POST", body),
  deleteEvent: (id: number) => request(`/events/${id}`, "DELETE"),
  preferences: () => request<Preferences>("/preferences"),
  savePreferences: (body: Preferences) => request<Preferences>("/preferences", "PUT", body),
  suggestions: () =>
    request<{ message: string; changes: Partial<Preferences> }[]>("/preferences/suggestions"),
  reminders: () => request<Reminder[]>("/reminders"),
  unreadCount: () => request<{ count: number }>("/reminders/unread-count"),
  recentReminders: () => request<Reminder[]>("/reminders/recent"),
  readReminder: (id: number) => request<Reminder>(`/reminders/${id}/read`, "POST"),
  dismissReminder: (id: number) => request<Reminder>(`/reminders/${id}/dismiss`, "POST"),
  snoozeReminder: (id: number, body: { minutes?: number; until?: string }) =>
    request<Reminder>(`/reminders/${id}/snooze`, "POST", body),
  notificationConfig: () =>
    request<{ push_configured: boolean; vapid_public_key: string; email_configured: boolean }>(
      "/notifications/config",
    ),
  notificationPreferences: (body: Partial<Preferences>) =>
    request<Preferences>("/preferences/notifications", "PATCH", body),
  subscribePush: (body: unknown) => request("/notifications/subscriptions", "POST", body),
  unsubscribePush: (endpoint: string) =>
    request("/notifications/subscriptions/remove", "POST", { endpoint }),
  createReminder: (body: unknown) => request<Reminder>("/reminders", "POST", body),
  updateReminder: (id: number, status: string) =>
    request<Reminder>(`/reminders/${id}`, "PATCH", { status }),
  calendar: () => request<Calendar>("/calendar"),
  sessionStatus: (id: number, status: string) =>
    request(`/calendar/sessions/${id}`, "PATCH", { status }),
  plan: (task_id: number, constraints = {}) =>
    request<Plan>("/calendar/plan", "POST", { task_id, ...constraints }),
  proposals: () => request<Proposal[]>("/proposals"),
  decide: (id: number, accept: boolean) => request(`/proposals/${id}/decision`, "POST", { accept }),
  dashboard: () => request<Dashboard>("/dashboard"),
  history: () => request<Message[]>("/agent/history"),
  chat: (message: string) =>
    request<{ message: string; actions: Action[]; proposals: Proposal[] }>("/agent/chat", "POST", {
      message,
    }),
  activity: () => request<{ id: number; action: string; created_at: string }[]>("/activity"),
  googleStatus: () =>
    request<{ configured: boolean; connected: boolean; synced_at: string | null }>(
      "/calendar/google/status",
    ),
  googleConnect: () => request<{ url: string }>("/calendar/google/connect", "POST"),
  googleSync: () =>
    request<{ imported: number; conflicts: number[] }>("/calendar/google/sync", "POST"),
  googleDisconnect: () => request("/calendar/google/disconnect", "POST"),
};
