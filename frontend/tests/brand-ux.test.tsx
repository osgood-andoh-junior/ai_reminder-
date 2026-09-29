import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import Today from "@/app/dashboard/page";
import { AuthForm } from "@/components/auth-form";
import { Shell } from "@/components/shell";
import { ProposalCard } from "@/components/ui";
import { api } from "@/lib/api";
import { dayContext, greeting } from "@/lib/day-context";
import type { Dashboard, Proposal } from "@/lib/types";

const mocks = vi.hoisted(() => ({ refresh: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push: mocks.push }),
}));
vi.mock("@/components/notification-bell", () => ({ NotificationBell: () => null }));
vi.mock("@/components/provider", () => ({
  useAuth: () => ({
    user: { id: 7, name: "Alex Smith", email: "alex@example.test" },
    preferences: { timezone: "UTC" },
    refresh: mocks.refresh,
  }),
}));
vi.mock("@/lib/api", () => ({ api: { dashboard: vi.fn(), decide: vi.fn(), login: vi.fn() } }));
const empty: Dashboard = {
  tasks: [],
  events: [],
  sessions: [],
  reminders: [],
  summary: { active: 0, total: 0, scheduled: 0, completed: 0 },
  timezone: "UTC",
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.dashboard).mockResolvedValue(empty);
});
afterEach(cleanup);

it("brands sign-in as Xenon and opens Today after authentication", async () => {
  render(<AuthForm />);
  expect(screen.getByText("Make time for what matters.")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Xenon" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Email address"), {
    target: { value: "alex@example.test" },
  });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/dashboard"));
  expect(api.login).toHaveBeenCalledWith({ email: "alex@example.test", password: "password" });
});
it("retains routes and closes navigation after selecting a page", () => {
  render(
    <Shell>
      <p>Workspace</p>
    </Shell>,
  );
  expect(screen.getByRole("link", { name: "Today" }).getAttribute("href")).toBe("/dashboard");
  expect(screen.getByRole("link", { name: "Xenon" }).getAttribute("href")).toBe("/assistant");
  fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
  expect(document.querySelector(".mobile-menu")?.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(screen.getByRole("link", { name: "Tasks" }));
  expect(
    screen.getByRole("button", { name: "Open navigation" }).getAttribute("aria-expanded"),
  ).toBe("false");
});
it("shows honest empty and loading states without invented availability", async () => {
  render(<Today />);
  expect(screen.getByRole("status").textContent).toContain("Loading your day");
  expect(await screen.findByText("Your day is clear.")).toBeTruthy();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Alex");
  expect(screen.getByText("No commitment right now")).toBeTruthy();
  expect(screen.queryByText(/minutes free/)).toBeNull();
});
it("offers a working retry without reporting a clear day after a load error", async () => {
  vi.mocked(api.dashboard).mockRejectedValueOnce(new Error("failure"));
  render(<Today />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByText("Your day is clear.")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Your day is clear.")).toBeTruthy();
});
it("uses timezone-aware greetings and numeric instants for overlaps", () => {
  const now = Date.parse("2030-01-01T10:00:00Z");
  expect(greeting(now, "UTC")).toBe("Good morning");
  expect(greeting(now, "Asia/Tokyo")).toBe("Good evening");
  const data = {
    ...empty,
    events: [
      {
        id: 1,
        title: "Current",
        start_time: "2030-01-01T11:00:00+02:00",
        end_time: "2030-01-01T13:00:00+02:00",
        event_type: "EVENT",
      },
      {
        id: 2,
        title: "Next",
        start_time: "2030-01-01T10:30:00Z",
        end_time: "2030-01-01T11:30:00Z",
        event_type: "EVENT",
      },
    ],
  } as Dashboard;
  const context = dayContext(data, now);
  expect(context.current.map((item) => item.title)).toEqual(["Current"]);
  expect(context.next?.title).toBe("Next");
  expect(context.conflicts).toHaveLength(2);
});
it.each([true, false])(
  "saves a scheduling decision only after explicit review: %s",
  async (accept) => {
    const proposal: Proposal = {
      id: 11,
      kind: "schedule_task",
      status: "PENDING",
      expires_at: "2030-01-01T11:00:00Z",
      payload: {
        plan: {
          task_id: 2,
          title: "Study",
          feasible: true,
          slots: [
            { start: "2030-01-01T12:00:00Z", end: "2030-01-01T13:00:00Z", minutes: 60, score: 1 },
          ],
          scheduled_minutes: 60,
          unscheduled_minutes: 0,
          explanation: "",
        },
      },
    };
    render(<ProposalCard proposal={proposal} onDone={vi.fn()} />);
    expect(api.decide).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: accept ? "Schedule it" : "Not now" }));
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith(11, accept));
    expect(await screen.findByRole("status")).toHaveProperty(
      "textContent",
      accept ? "Scheduled" : "Not applied",
    );
  },
);
it("shows reminder timing names in proposals without raw JSON", () => {
  const proposal = {
    id: 12,
    kind: "task_reminders",
    status: "PENDING",
    expires_at: "2030-01-01T11:00:00Z",
    payload: {
      task_id: 2,
      changes: { reminder_stages: ["BEFORE_60", "END_10"], email_reminders_enabled: false },
    },
  } as unknown as Proposal;
  render(<ProposalCard proposal={proposal} onDone={vi.fn()} />);
  expect(screen.getByText("1 hour before, 10 minutes before ending")).toBeTruthy();
  expect(screen.getByText("Off")).toBeTruthy();
  expect(screen.queryByText(/BEFORE_60/)).toBeNull();
  expect(api.decide).not.toHaveBeenCalled();
});
