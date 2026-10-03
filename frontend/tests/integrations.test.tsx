import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { IntegrationHub } from "@/components/integration-hub";
import { api } from "@/lib/api";
import type { Commitment, Integration, Proposal } from "@/lib/types";

vi.mock("@/components/provider", () => ({
  useAuth: () => ({
    preferences: { timezone: "UTC" },
    refresh: vi.fn().mockResolvedValue(undefined),
  }),
}));
vi.mock("@/lib/api", () => ({
  api: {
    integrations: vi.fn(),
    commitments: vi.fn(),
    proposals: vi.fn(),
    gmailSync: vi.fn(),
    gmailConnect: vi.fn(),
    gmailDisconnect: vi.fn(),
    googleConnect: vi.fn(),
    googleSync: vi.fn(),
    googleDisconnect: vi.fn(),
    proposeCommitment: vi.fn(),
    decide: vi.fn(),
  },
}));
const connections: Integration[] = [
  { id: "google_calendar", name: "Google Calendar", configured: true, state: "connected" },
  {
    id: "gmail",
    name: "Gmail",
    configured: true,
    state: "connected",
    account: "mail@example.test",
  },
  ...["Google Tasks", "Microsoft Outlook", "Notion", "Slack"].map((name) => ({
    id: name,
    name,
    configured: false,
    state: "coming_soon" as const,
  })),
];
const item: Commitment = {
  id: 7,
  revision: 0,
  title: "CPEN assignment",
  type: "deadline",
  source: "gmail",
  deadline: "2026-10-02T23:59:00Z",
  start_time: null,
  end_time: null,
  estimated_duration_minutes: null,
  confidence: 0.9,
  reason: "An assignment deadline.",
  unresolved: ["Confirm work duration"],
  status: "PENDING",
  subject: "Assignment due Friday",
  sender: "Tutor",
  snippet: "Submit the report",
  source_message_id: "m1",
  received_at: "2026-09-29T12:00:00Z",
};
const proposal: Proposal = {
  id: 12,
  kind: "commitment",
  status: "PENDING",
  expires_at: "2026-09-29T15:00:00Z",
  payload: {
    commitment_id: 7,
    review: { action: "schedule", title: "Edited assignment" },
    plan: {
      task_id: 0,
      title: "Edited assignment",
      feasible: true,
      scheduled_minutes: 90,
      unscheduled_minutes: 0,
      explanation: "Fits",
      slots: [
        { start: "2026-09-30T09:00:00Z", end: "2026-09-30T10:30:00Z", minutes: 90, score: 1 },
      ],
    },
  },
};
beforeEach(() => {
  vi.resetAllMocks();
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  vi.mocked(api.integrations).mockResolvedValue(connections);
  vi.mocked(api.commitments).mockResolvedValue([]);
  vi.mocked(api.proposals).mockResolvedValue([]);
  vi.mocked(api.decide).mockResolvedValue({});
});
afterEach(cleanup);

it("shows the real supported integrations and noninteractive coming-soon cards", async () => {
  render(<IntegrationHub />);
  expect(screen.getByRole("status").textContent).toContain("Loading integrations");
  expect(await screen.findByText("mail@example.test")).toBeTruthy();
  expect(screen.getAllByText("Coming soon")).toHaveLength(4);
  expect(within(screen.getByRole("article", { name: "Slack" })).queryByRole("button")).toBeNull();
  expect(screen.getByText(/No pending commitments/)).toBeTruthy();
});

it("shows connect, reconnect and configuration states honestly", async () => {
  vi.mocked(api.integrations).mockResolvedValue([
    { ...connections[0], configured: false, state: "not_connected" },
    { ...connections[1], state: "needs_attention", error: "access_expired_or_revoked" },
  ]);
  render(<IntegrationHub />);
  const connect = await screen.findByRole("button", { name: "Connect Google Calendar" });
  expect((connect as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByRole("button", { name: "Reconnect Gmail" })).toBeTruthy();
  expect(screen.getByText("Needs attention")).toBeTruthy();
});

it("checks Gmail only on request and shows detected candidates", async () => {
  vi.mocked(api.gmailSync).mockImplementation(async () => {
    vi.mocked(api.commitments).mockResolvedValue([item]);
    return { checked: 1, detected: 1, failed: 0, more: false, error: null };
  });
  render(<IntegrationHub />);
  const button = await screen.findByRole("button", { name: "Check Gmail for commitments" });
  expect(api.gmailSync).not.toHaveBeenCalled();
  fireEvent.click(button);
  expect(await screen.findByText("CPEN assignment")).toBeTruthy();
  expect(api.gmailSync).toHaveBeenCalledOnce();
  expect(screen.getByText(/Checked 1 emails/)).toBeTruthy();
  expect(api.decide).not.toHaveBeenCalled();
});

it("reviews edits, previews deterministic sessions, then uses the dedicated confirmation endpoint", async () => {
  vi.mocked(api.commitments).mockResolvedValue([item]);
  vi.mocked(api.proposeCommitment).mockImplementation(async () => {
    vi.mocked(api.proposals).mockResolvedValue([proposal]);
    return { proposal };
  });
  render(<IntegrationHub />);
  fireEvent.click(await screen.findByRole("button", { name: "Review CPEN assignment" }));
  const dialog = screen.getByRole("dialog", { name: "Review commitment" });
  fireEvent.change(within(dialog).getByLabelText("Title"), {
    target: { value: "Edited assignment" },
  });
  fireEvent.change(within(dialog).getByLabelText("Estimated duration · minutes"), {
    target: { value: "90" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Preview proposal" }));
  const confirm = await screen.findByRole("button", { name: "Schedule it" });
  expect(api.proposeCommitment).toHaveBeenCalledWith(
    7,
    expect.objectContaining({
      action: "schedule",
      title: "Edited assignment",
      estimated_duration_minutes: 90,
      deadline: "2026-10-02T23:59:00Z",
    }),
  );
  expect(api.decide).not.toHaveBeenCalled();
  expect(screen.getByText(/90 minutes planned/)).toBeTruthy();
  fireEvent.click(confirm);
  await waitFor(() => expect(api.decide).toHaveBeenCalledWith(12, true));
});

it("can change the review action to a calendar event", async () => {
  vi.mocked(api.commitments).mockResolvedValue([item]);
  vi.mocked(api.proposeCommitment).mockResolvedValue({ proposal: { ...proposal, payload: {} } });
  render(<IntegrationHub />);
  fireEvent.click(await screen.findByRole("button", { name: "Review CPEN assignment" }));
  fireEvent.change(screen.getByLabelText("Action"), { target: { value: "event" } });
  fireEvent.change(screen.getByLabelText("Start time"), { target: { value: "2026-09-30T10:00" } });
  fireEvent.change(screen.getByLabelText("End time"), { target: { value: "2026-09-30T11:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview proposal" }));
  await waitFor(() =>
    expect(api.proposeCommitment).toHaveBeenCalledWith(
      7,
      expect.objectContaining({
        action: "event",
        start_time: "2026-09-30T10:00:00Z",
        end_time: "2026-09-30T11:00:00Z",
      }),
    ),
  );
});

it("dismisses through a proposal and permits rejection without changing the commitment", async () => {
  vi.mocked(api.commitments).mockResolvedValue([item]);
  const dismiss: Proposal = {
    ...proposal,
    kind: "commitment_dismiss",
    payload: { commitment_id: 7, review: { title: item.title, action: "dismiss" } },
  };
  vi.mocked(api.proposeCommitment).mockImplementation(async () => {
    vi.mocked(api.proposals).mockResolvedValue([dismiss]);
    return { proposal: dismiss };
  });
  render(<IntegrationHub />);
  fireEvent.click(await screen.findByRole("button", { name: "Dismiss CPEN assignment" }));
  fireEvent.click(await screen.findByRole("button", { name: "Not now" }));
  await waitFor(() => expect(api.decide).toHaveBeenCalledWith(12, false));
});

it("shows sync and infeasibility errors without claiming an action succeeded", async () => {
  vi.mocked(api.gmailSync).mockResolvedValue({
    checked: 1,
    detected: 0,
    failed: 1,
    more: false,
    error: "ai_unavailable",
  });
  vi.mocked(api.commitments).mockResolvedValue([item]);
  vi.mocked(api.proposeCommitment).mockResolvedValue({
    proposal: null,
    message: "Only 0 minutes could be allocated.",
  });
  render(<IntegrationHub />);
  fireEvent.click(await screen.findByRole("button", { name: "Check Gmail for commitments" }));
  expect(await screen.findByText(/Email detection is unavailable/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Review CPEN assignment" }));
  fireEvent.change(screen.getByLabelText("Estimated duration · minutes"), {
    target: { value: "60" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview proposal" }));
  await waitFor(() =>
    expect(
      within(screen.getByRole("dialog")).getByText("Only 0 minutes could be allocated."),
    ).toBeTruthy(),
  );
  expect(api.decide).not.toHaveBeenCalled();
});

it("requires a disconnect decision and keeps revocation opt-in", async () => {
  vi.mocked(api.gmailDisconnect).mockResolvedValue({ warning: null });
  render(<IntegrationHub />);
  fireEvent.click(await screen.findByRole("button", { name: "Disconnect Gmail" }));
  expect(api.gmailDisconnect).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));
  await waitFor(() => expect(api.gmailDisconnect).toHaveBeenCalledWith(false));
});
