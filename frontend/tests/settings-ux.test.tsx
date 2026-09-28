import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import Settings from "@/app/settings/page";
import { api } from "@/lib/api";
const context = vi.hoisted(() => ({
  user: { id: 1, name: "Alex", email: "alex@example.test" },
  preferences: {
    timezone: "UTC",
    preferred_start_time: "09:00",
    preferred_end_time: "17:00",
    preferred_days: [0, 1, 2, 3, 4],
    default_reminder_minutes: 15,
    preferred_task_length: 60,
    break_preference: 10,
    allow_weekend_scheduling: false,
    personalization_enabled: true,
    browser_notifications_enabled: false,
    email_notifications_enabled: false,
    in_app_notifications_enabled: true,
    reminder_stages: ["BEFORE_60"],
    deadline_reminders_enabled: false,
  },
  refresh: vi.fn(),
}));
vi.mock("@/components/provider", () => ({ useAuth: () => context }));
vi.mock("@/lib/api", () => ({
  api: {
    googleStatus: vi.fn().mockResolvedValue({ configured: false, connected: false }),
    suggestions: vi.fn().mockResolvedValue([]),
    activity: vi.fn().mockResolvedValue([]),
    notificationConfig: vi
      .fn()
      .mockResolvedValue({ push_configured: false, email_configured: false }),
    savePreferences: vi.fn().mockResolvedValue({}),
  },
}));
afterEach(cleanup);
it("keeps scheduling preferences and notification choices when saving Settings", async () => {
  render(<Settings />);
  expect(screen.getByRole("heading", { name: "Settings" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Voice" })).toBeTruthy();
  await screen.findByText(/Email reminders are unavailable/);
  fireEvent.change(screen.getByLabelText("Session length · minutes"), { target: { value: "90" } });
  fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));
  await waitFor(() =>
    expect(api.savePreferences).toHaveBeenCalledWith({
      ...context.preferences,
      preferred_task_length: 90,
    }),
  );
  expect(await screen.findByText("Preferences saved.")).toBeTruthy();
});
