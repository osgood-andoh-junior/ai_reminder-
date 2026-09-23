import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NotificationBell } from "@/components/notification-bell";
import { NotificationSettings } from "@/components/notification-settings";
import { ReminderActions } from "@/components/reminder-actions";
import Reminders from "@/app/reminders/page";
import { api } from "@/lib/api";
import type { Reminder } from "@/lib/types";

vi.mock("@/components/provider", () => ({
  useAuth: () => ({
    preferences: { timezone: "Africa/Accra", browser_notifications_enabled: false },
    refresh: vi.fn(),
  }),
}));
vi.mock("@/lib/api", () => ({
  api: {
    unreadCount: vi.fn(),
    recentReminders: vi.fn(),
    readReminder: vi.fn(),
    dismissReminder: vi.fn(),
    snoozeReminder: vi.fn(),
    notificationConfig: vi.fn(),
    subscribePush: vi.fn(),
    notificationPreferences: vi.fn(),
    reminders: vi.fn(),
  },
}));
const reminder: Reminder = {
  id: 1,
  user_id: 1,
  task_id: 2,
  scheduled_task_id: 3,
  title: "AI assignment",
  message: "Starts soon",
  reminder_time: "2030-01-01T12:00:00Z",
  sent_at: "2030-01-01T12:00:00Z",
  read_at: null,
  dismissed_at: null,
  snoozed_until: null,
  generation: 0,
  status: "SENT",
};
const requestPermission = vi.fn();
const subscribe = vi.fn();

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  vi.clearAllMocks();
  vi.mocked(api.unreadCount).mockResolvedValue({ count: 2 });
  vi.mocked(api.recentReminders).mockResolvedValue([reminder]);
  vi.mocked(api.reminders).mockResolvedValue([
    reminder,
    { ...reminder, id: 2, title: "Tomorrow", status: "PENDING" },
  ]);
  vi.mocked(api.notificationConfig).mockResolvedValue({
    push_configured: true,
    vapid_public_key: "BAAA",
    email_configured: false,
  });
  Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
  Object.defineProperty(window, "Notification", {
    configurable: true,
    value: { permission: "default", requestPermission },
  });
  Object.defineProperty(window, "PushManager", { configurable: true, value: {} });
  const registration = {
    pushManager: { getSubscription: vi.fn().mockResolvedValue(null), subscribe },
    getNotifications: vi.fn().mockResolvedValue([]),
  };
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      getRegistration: vi.fn().mockResolvedValue(registration),
      register: vi.fn().mockResolvedValue(registration),
      ready: Promise.resolve(registration),
    },
  });
  requestPermission.mockResolvedValue("granted");
  subscribe.mockResolvedValue({
    toJSON: () => ({ endpoint: "test-endpoint", keys: {} }),
    unsubscribe: vi.fn(),
  });
});
afterEach(cleanup);

describe("notification controls", () => {
  it("shows the unread count and recent delivered reminders", async () => {
    render(<NotificationBell zone="Africa/Accra" />);
    fireEvent.click(await screen.findByRole("button", { name: "Notifications, 2 unread" }));
    expect(await screen.findByText("AI assignment")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open task" }).getAttribute("href")).toBe(
      "/tasks#task-2",
    );
  });
  it("refreshes the bell after a reminder change", async () => {
    render(<NotificationBell zone="Africa/Accra" />);
    await screen.findByRole("button", { name: "Notifications, 2 unread" });
    vi.mocked(api.unreadCount).mockResolvedValue({ count: 0 });
    window.dispatchEvent(new Event("reminders-changed"));
    expect(await screen.findByRole("button", { name: "Notifications, 0 unread" })).toBeTruthy();
  });
  it("snoozes through the backend and dismisses separately", async () => {
    const changed = vi.fn();
    render(<ReminderActions reminder={reminder} zone="Africa/Accra" onChange={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "Snooze" }));
    fireEvent.click(screen.getByRole("button", { name: "30 minutes" }));
    await waitFor(() => expect(api.snoozeReminder).toHaveBeenCalledWith(1, { minutes: 30 }));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(api.dismissReminder).toHaveBeenCalledWith(1));
  });
  it("marks read without dismissing", async () => {
    render(<ReminderActions reminder={reminder} zone="Africa/Accra" onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Mark read" }));
    await waitFor(() => expect(api.readReminder).toHaveBeenCalledWith(1));
    expect(api.dismissReminder).not.toHaveBeenCalled();
  });
  it("never requests browser permission on mount", async () => {
    render(<NotificationSettings />);
    await screen.findByText("Browser permission has not been requested.");
    expect(requestPermission).not.toHaveBeenCalled();
  });
  it("subscribes only after an explicit enable click", async () => {
    render(<NotificationSettings />);
    const enable = await screen.findByRole("button", { name: "Enable browser notifications" });
    await waitFor(() => expect((enable as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(enable);
    await waitFor(() => expect(api.subscribePush).toHaveBeenCalled());
    expect(requestPermission).toHaveBeenCalledTimes(1);
  });
  it("explains denied permission without requesting again", async () => {
    Object.defineProperty(window, "Notification", {
      configurable: true,
      value: { permission: "denied", requestPermission },
    });
    render(<NotificationSettings />);
    expect(await screen.findByText(/Notifications are blocked/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Enable browser notifications" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(requestPermission).not.toHaveBeenCalled();
  });
  it("does not report success when subscription registration fails", async () => {
    vi.mocked(api.subscribePush).mockRejectedValueOnce(new Error("Server unavailable"));
    render(<NotificationSettings />);
    const enable = await screen.findByRole("button", { name: "Enable browser notifications" });
    await waitFor(() => expect((enable as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(enable);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText(/Browser push is enabled/)).toBeNull();
  });
  it("separates upcoming from unread reminders", async () => {
    render(<Reminders />);
    await screen.findByText("Tomorrow");
    expect(screen.queryByText("AI assignment")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Unread" }));
    expect(await screen.findByText("AI assignment")).toBeTruthy();
    expect(screen.queryByText("Tomorrow")).toBeNull();
  });
});
