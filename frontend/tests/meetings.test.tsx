import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ContactsPanel, MeetingDetails, MeetingEditor } from "@/components/meetings";
import { ProposalCard } from "@/components/ui";
import { api } from "@/lib/api";
import type { Event, Proposal } from "@/lib/types";

vi.mock("@/components/provider", () => ({
  useAuth: () => ({
    preferences: { timezone: "UTC" },
    refresh: vi.fn().mockResolvedValue(undefined),
  }),
}));
vi.mock("@/lib/api", () => ({
  api: {
    proposeMeeting: vi.fn(),
    decideMeeting: vi.fn(),
    contacts: vi.fn(),
    deleteContact: vi.fn(),
    proposeContact: vi.fn(),
  },
}));
const proposal: Proposal = {
  id: 8,
  kind: "meeting_create",
  status: "PENDING",
  expires_at: "2026-10-03T15:30:00Z",
  payload: {
    meeting: {
      title: "Project meeting",
      description: "A review",
      start_time: "2026-10-04T15:00:00Z",
      end_time: "2026-10-04T15:30:00Z",
      duration_minutes: 30,
      timezone: "UTC",
      attendees: [
        { name: "Elliot", email: "elliot@example.com" },
        { name: "Ama", email: "ama@example.com" },
      ],
      google_meet: true,
      location: "",
    },
  },
};
beforeEach(() => {
  vi.clearAllMocks();
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true;
  });
  vi.mocked(api.decideMeeting).mockResolvedValue({
    message: "Meeting saved. Google Calendar was asked to notify attendees.",
  });
});
afterEach(cleanup);

it("reviews attendees and Meet before a dedicated confirmation", async () => {
  render(<ProposalCard proposal={proposal} onDone={vi.fn()} />);
  expect(screen.getByText("Elliot")).toBeTruthy();
  expect(screen.getByText("Ama")).toBeTruthy();
  expect(screen.getByText(/Google Meet: will be created/)).toBeTruthy();
  expect(api.decideMeeting).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Confirm & Send" }));
  await waitFor(() => expect(api.decideMeeting).toHaveBeenCalledWith(8, true));
  expect(await screen.findByRole("status")).toBeTruthy();
});
it("rejects invitations without sending", async () => {
  render(<ProposalCard proposal={proposal} onDone={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(api.decideMeeting).toHaveBeenCalledWith(8, false));
});
it("shows errors and keeps the confirmation available for retry", async () => {
  vi.mocked(api.decideMeeting).mockRejectedValue(new Error("Google Calendar unavailable"));
  render(<ProposalCard proposal={proposal} onDone={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Confirm & Send" }));
  expect(await screen.findByText("Google Calendar unavailable")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Confirm & Send" })).toBeTruthy();
});
it("disables sending while a request is in progress", async () => {
  vi.mocked(api.decideMeeting).mockImplementation(() => new Promise(() => {}));
  render(<ProposalCard proposal={proposal} onDone={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Confirm & Send" }));
  expect(
    ((await screen.findByRole("button", { name: "Saving…" })) as HTMLButtonElement).disabled,
  ).toBe(true);
});
it("edits into a fresh proposal and rejects the old one", async () => {
  vi.mocked(api.proposeMeeting).mockResolvedValue({ proposal: { ...proposal, id: 9 } });
  render(<ProposalCard proposal={proposal} onDone={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Edited title" } });
  fireEvent.submit(screen.getByRole("button", { name: "Review invitation" }).closest("form")!);
  await waitFor(() =>
    expect(api.proposeMeeting).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Edited title" }),
      undefined,
    ),
  );
  await waitFor(() => expect(api.decideMeeting).toHaveBeenCalledWith(8, false));
  expect(api.decideMeeting).not.toHaveBeenCalledWith(9, true);
});
it("warns about cancellation notifications and uses confirmation", async () => {
  render(
    <ProposalCard
      proposal={{
        ...proposal,
        kind: "meeting_cancel",
        payload: {
          event_id: 2,
          before: {
            title: "Project meeting",
            start_time: "2026-10-04T15:00:00Z",
            end_time: "2026-10-04T15:30:00Z",
            attendees: proposal.payload.meeting!.attendees,
          },
        },
      }}
      onDone={vi.fn()}
    />,
  );
  expect(screen.getByText(/notify attendees of the cancellation/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Confirm cancellation" }));
  await waitFor(() => expect(api.decideMeeting).toHaveBeenCalledWith(8, true));
});
it("supports a Meet toggle, multiple attendees and missing-contact clarification", async () => {
  vi.mocked(api.proposeMeeting).mockResolvedValue({
    proposal: null,
    missing_contacts: [{ name: "Elliot", reason: "unknown" }],
  });
  render(<MeetingEditor day="2026-10-04" onClose={vi.fn()} onProposed={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Project meeting" } });
  fireEvent.change(screen.getByLabelText("Name 1"), { target: { value: "Elliot" } });
  fireEvent.click(screen.getByRole("button", { name: "Add attendee" }));
  fireEvent.change(screen.getByLabelText("Email 2"), { target: { value: "ama@example.com" } });
  fireEvent.click(screen.getByLabelText("Create Google Meet link"));
  fireEvent.submit(screen.getByRole("button", { name: "Review invitation" }).closest("form")!);
  await waitFor(() =>
    expect(api.proposeMeeting).toHaveBeenCalledWith(
      expect.objectContaining({
        google_meet: true,
        attendees: [
          { name: "Elliot", email: null },
          { name: "", email: "ama@example.com" },
        ],
      }),
      undefined,
    ),
  );
  expect(await screen.findByText(/What email address should I use for Elliot/)).toBeTruthy();
});
it("displays only organizer-event RSVP statuses and returned links", () => {
  const event = {
    meeting_metadata: {
      attendees: ["accepted", "tentative", "declined", "needsAction"].map((response_status, i) => ({
        name: `Person ${i}`,
        email: `${i}@example.com`,
        response_status,
      })),
      meet_url: "https://meet.google.com/returned",
      calendar_url: "https://calendar.google.com/event",
    },
  } as Event;
  render(<MeetingDetails event={event} />);
  for (const status of ["Accepted", "Tentative", "Declined", "Awaiting response"])
    expect(screen.getByText(new RegExp(status))).toBeTruthy();
  expect(screen.getByRole("link", { name: "Join meeting" }).getAttribute("href")).toBe(
    "https://meet.google.com/returned",
  );
});
it("does not invent a conference link when creation fails", () => {
  render(
    <MeetingDetails
      event={
        { meeting_metadata: { attendees: [], conference_status: "failure" } } as unknown as Event
      }
    />,
  );
  expect(screen.queryByRole("link", { name: "Join meeting" })).toBeNull();
  expect(screen.getByText(/Google Meet creation failed/)).toBeTruthy();
});
it("allows reviewing and deleting saved contacts", async () => {
  vi.mocked(api.contacts).mockResolvedValue([
    { id: 3, name: "Elliot", email: "elliot@example.com" },
  ]);
  vi.mocked(api.deleteContact).mockResolvedValue(undefined);
  render(<ContactsPanel />);
  fireEvent.click(screen.getByRole("button", { name: "Review saved contacts" }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete Elliot" }));
  await waitFor(() => expect(api.deleteContact).toHaveBeenCalledWith(3));
});
