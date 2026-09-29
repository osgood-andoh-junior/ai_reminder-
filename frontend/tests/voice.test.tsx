import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import Assistant from "@/app/assistant/page";
import { api } from "@/lib/api";

vi.mock("@/components/provider", () => ({
  useAuth: () => ({ user: { id: 7, name: "Test" }, preferences: { timezone: "UTC" } }),
}));
vi.mock("@/lib/api", () => ({
  api: { history: vi.fn(), proposals: vi.fn(), dashboard: vi.fn(), health: vi.fn(), chat: vi.fn() },
}));
class Recognition {
  static latest: Recognition;
  onresult?: (event: { results: { transcript: string }[][] }) => void;
  onerror?: (event: { error: string }) => void;
  onend?: () => void;
  start = vi.fn();
  stop = vi.fn();
  abort = vi.fn();
  constructor() {
    Recognition.latest = this;
  }
}
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  Element.prototype.scrollIntoView = vi.fn();
  vi.mocked(api.history).mockResolvedValue([]);
  vi.mocked(api.proposals).mockResolvedValue([]);
  vi.mocked(api.dashboard).mockResolvedValue({
    tasks: [],
    sessions: [],
    events: [],
  } as unknown as Awaited<ReturnType<typeof api.dashboard>>);
  vi.mocked(api.health).mockResolvedValue({ ai_configured: true });
  vi.mocked(api.chat).mockResolvedValue({
    message: "Review your plan",
    actions: [],
    proposals: [],
  });
  vi.stubGlobal("SpeechRecognition", Recognition);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
async function open() {
  render(<Assistant />);
  await screen.findByText(/What can I help you with/);
}
it("sends an editable voice transcript through the existing chat API", async () => {
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Start voice input" }));
  expect(screen.getByText(/Listening/)).toBeTruthy();
  act(() =>
    Recognition.latest.onresult?.({ results: [[{ transcript: "Schedule DSP tomorrow" }]] }),
  );
  expect((screen.getByLabelText("Message your assistant") as HTMLTextAreaElement).value).toBe(
    "Schedule DSP tomorrow",
  );
  expect(api.chat).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Stop voice input" }));
  expect(Recognition.latest.stop).toHaveBeenCalled();
  act(() => Recognition.latest.onend?.());
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(api.chat).toHaveBeenCalledWith("Schedule DSP tomorrow"));
});
it.each(["not-allowed", "network"])(
  "keeps text working after recognition error %s",
  async (error) => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Start voice input" }));
    act(() => Recognition.latest.onerror?.({ error }));
    expect(screen.getByRole("alert")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Message your assistant"), {
      target: { value: "Typed request" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(api.chat).toHaveBeenCalledWith("Typed request"));
  },
);
it("reports unsupported recognition and permits cancellation", async () => {
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Start voice input" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel voice" }));
  expect(Recognition.latest.abort).toHaveBeenCalled();
  expect(api.chat).not.toHaveBeenCalled();
  vi.stubGlobal("SpeechRecognition", undefined);
  fireEvent.click(screen.getByRole("button", { name: "Start voice input" }));
  expect(screen.getByText(/Speech recognition is unsupported/)).toBeTruthy();
});
it("keeps assistant text visible when synthesis fails", async () => {
  vi.mocked(api.history).mockResolvedValue([
    { role: "assistant", content: "Saved response", actions: [] },
  ]);
  vi.stubGlobal("SpeechSynthesisUtterance", class {});
  vi.stubGlobal("speechSynthesis", {
    cancel: vi.fn(),
    speak: () => {
      throw new Error("unavailable");
    },
  });
  render(<Assistant />);
  fireEvent.click(await screen.findByRole("button", { name: "Read response aloud" }));
  expect(screen.getByText(/Speech playback failed/)).toBeTruthy();
  expect(screen.getByText("Saved response")).toBeTruthy();
});
it("preserves existing text across interim results and edits", async () => {
  await open();
  const input = screen.getByLabelText("Message your assistant") as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: "Please" } });
  fireEvent.click(screen.getByLabelText("Start voice input"));
  const result = Recognition.latest.onresult;
  act(() => result?.({ results: [[{ transcript: "plan" }]] }));
  act(() => result?.({ results: [[{ transcript: "plan tomorrow" }]] }));
  expect(input.value).toBe("Please plan tomorrow");
  fireEvent.change(input, { target: { value: "Please plan Friday" } });
  expect(Recognition.latest.abort).toHaveBeenCalled();
  act(() => result?.({ results: [[{ transcript: "late result" }]] }));
  expect(input.value).toBe("Please plan Friday");
  fireEvent.click(screen.getByLabelText("Send message"));
  await waitFor(() => expect(api.chat).toHaveBeenCalledWith("Please plan Friday"));
});
it("keeps drafts on voice errors and cancellation", async () => {
  await open();
  const input = screen.getByLabelText("Message your assistant") as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: "Keep this draft" } });
  fireEvent.click(screen.getByLabelText("Start voice input"));
  act(() => Recognition.latest.onerror?.({ error: "network" }));
  expect(input.value).toBe("Keep this draft");
  fireEvent.click(screen.getByLabelText("Start voice input"));
  fireEvent.click(screen.getByLabelText("Cancel voice"));
  expect(input.value).toBe("Keep this draft");
});
it("blocks processing submissions and restores failed requests", async () => {
  await open();
  const input = screen.getByLabelText("Message your assistant") as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: "Plan tomorrow" } });
  fireEvent.click(screen.getByLabelText("Start voice input"));
  fireEvent.click(screen.getByLabelText("Stop voice input"));
  expect((screen.getByLabelText("Send message") as HTMLButtonElement).disabled).toBe(true);
  fireEvent.submit(input.form!);
  expect(api.chat).not.toHaveBeenCalled();
  act(() => Recognition.latest.onend?.());
  vi.mocked(api.chat).mockRejectedValueOnce(new Error("Try again"));
  fireEvent.submit(input.form!);
  await screen.findByText("Try again");
  expect(input.value).toBe("Plan tomorrow");
});
it("uses Enter to send but preserves Shift+Enter and IME composition", async () => {
  await open();
  const input = screen.getByLabelText("Message your assistant") as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: "Typed request" } });
  fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
  fireEvent.keyDown(input, { key: "Enter", isComposing: true });
  expect(api.chat).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(api.chat).toHaveBeenCalledWith("Typed request"));
});
it("persists auto-read per user and stops the specific response", async () => {
  class Speech {
    onend?: () => void;
    constructor(public text: string) {}
  }
  const speak = vi.fn();
  const cancel = vi.fn();
  vi.stubGlobal("SpeechSynthesisUtterance", Speech);
  vi.stubGlobal("speechSynthesis", { speak, cancel });
  await open();
  expect(screen.queryByText("Idle")).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  fireEvent.click(screen.getByLabelText("Assistant options"));
  fireEvent.click(screen.getByRole("checkbox"));
  expect(localStorage.getItem("tempo:voice-responses:7")).toBe("true");
  cleanup();
  await open();
  fireEvent.change(screen.getByLabelText("Message your assistant"), { target: { value: "Plan" } });
  fireEvent.click(screen.getByLabelText("Send message"));
  await screen.findByLabelText("Stop reading response");
  expect(speak.mock.calls[0][0].text).toBe("Review your plan");
  await waitFor(() =>
    expect((screen.getByLabelText("Stop reading response") as HTMLButtonElement).disabled).toBe(
      false,
    ),
  );
  fireEvent.click(screen.getByLabelText("Stop reading response"));
  expect(cancel).toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText("Read response aloud"));
  expect(speak).toHaveBeenCalledTimes(2);
  act(() => speak.mock.calls[1][0].onend());
  expect(screen.queryByLabelText("Stop reading response")).toBeNull();
});
it("populates suggestions without submitting", async () => {
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Schedule a task" }));
  expect(api.chat).not.toHaveBeenCalled();
  expect((screen.getByLabelText("Message your assistant") as HTMLTextAreaElement).value).toBe(
    "Help me schedule a task before its deadline.",
  );
  fireEvent.click(screen.getByLabelText("Send message"));
  await screen.findByText("Review your plan");
  expect(screen.queryByRole("button", { name: "Schedule a task" })).toBeNull();
});

it("continues across browser session endings without replacing or duplicating speech", async () => {
  await open();
  vi.useFakeTimers();
  fireEvent.click(screen.getByLabelText("Start voice input"));
  const first = Recognition.latest;
  expect((first as unknown as { continuous: boolean }).continuous).toBe(true);
  act(() => first.onresult?.({ results: [[{ transcript: "Plan tomorrow" }]] }));
  act(() => first.onend?.());
  expect(screen.getByLabelText("Stop voice input")).toBeTruthy();
  act(() => vi.advanceTimersByTime(300));
  const second = Recognition.latest;
  expect(second).not.toBe(first);
  act(() => second.onresult?.({ results: [[{ transcript: "and" }]] }));
  act(() => second.onresult?.({ results: [[{ transcript: "and Friday" }]] }));
  expect((screen.getByLabelText("Message your assistant") as HTMLTextAreaElement).value).toBe(
    "Plan tomorrow and Friday",
  );
  fireEvent.click(screen.getByLabelText("Stop voice input"));
  act(() => second.onend?.());
  act(() => vi.advanceTimersByTime(1000));
  expect(Recognition.latest).toBe(second);
  expect(screen.getByLabelText("Start voice input")).toBeTruthy();
});
it.each(["Stop voice input", "Cancel voice", "edit", "unmount"])(
  "cancels a pending reconnect on %s",
  async (action) => {
    await open();
    vi.useFakeTimers();
    fireEvent.click(screen.getByLabelText("Start voice input"));
    const first = Recognition.latest;
    act(() => first.onend?.());
    if (action === "unmount") cleanup();
    else if (action === "edit")
      fireEvent.change(screen.getByLabelText("Message your assistant"), {
        target: { value: "New draft" },
      });
    else fireEvent.click(screen.getByLabelText(action));
    act(() => vi.advanceTimersByTime(1000));
    expect(Recognition.latest).toBe(first);
  },
);
it("reconnects after silence but never retries permission or network errors", async () => {
  await open();
  vi.useFakeTimers();
  fireEvent.click(screen.getByLabelText("Start voice input"));
  const first = Recognition.latest;
  act(() => first.onerror?.({ error: "no-speech" }));
  act(() => first.onend?.());
  act(() => vi.advanceTimersByTime(300));
  expect(Recognition.latest).not.toBe(first);
  const second = Recognition.latest;
  const lateEnd = second.onend;
  act(() => second.onerror?.({ error: "not-allowed" }));
  act(() => lateEnd?.());
  act(() => vi.advanceTimersByTime(1000));
  expect(Recognition.latest).toBe(second);
  expect(screen.getByRole("alert")).toBeTruthy();
});
