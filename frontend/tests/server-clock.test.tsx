import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { dateKey } from "@/lib/time";
import { projectedServerTime, useServerClock } from "@/lib/use-server-clock";

vi.mock("@/lib/api", () => ({ api: { time: vi.fn() } }));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("uses server time despite an incorrect device date and crosses local midnight", () => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2020-01-01T00:00:00Z"));
  const now = projectedServerTime("2026-09-29T23:59:59Z", 100, 2100);
  expect(new Date(now).toISOString()).toBe("2026-09-30T00:00:01.000Z");
  expect(dateKey(new Date(now).toISOString(), "Africa/Accra")).toBe("2026-09-30");
  expect(dateKey(new Date(now).toISOString(), "America/Los_Angeles")).toBe("2026-09-29");
});

it("refreshes on resume and prevents an old request overwriting newer time", async () => {
  const first = {
    utc_now: "2026-09-29T23:59:59Z",
    local_now: "2026-09-29T23:59:59Z",
    local_date: "2026-09-29",
    timezone: "Africa/Accra",
    utc_offset: "+00:00",
  };
  vi.mocked(api.time).mockResolvedValueOnce(first);
  const { result } = renderHook(() => useServerClock(7, "Africa/Accra"));
  expect(result.current.now).toBeNull();
  await waitFor(() => expect(result.current.now).toBe(Date.parse(first.utc_now)));
  let finishOld!: (value: typeof first) => void;
  vi.mocked(api.time).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishOld = resolve;
      }),
  );
  act(() => window.dispatchEvent(new Event("focus")));
  const newer = { ...first, utc_now: "2026-09-30T00:01:00Z" };
  vi.mocked(api.time).mockResolvedValueOnce(newer);
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(result.current.now).toBe(Date.parse(newer.utc_now)));
  await act(async () => finishOld(first));
  expect(result.current.now).toBe(Date.parse(newer.utc_now));
});

it("does not fetch an anonymous clock or substitute device time on failure", async () => {
  vi.mocked(api.time).mockClear();
  const { result, rerender } = renderHook(({ id }) => useServerClock(id, "UTC"), {
    initialProps: { id: undefined as number | undefined },
  });
  expect(api.time).not.toHaveBeenCalled();
  vi.mocked(api.time).mockRejectedValueOnce(new Error("offline"));
  rerender({ id: 7 });
  await waitFor(() => expect(result.current.clockError).toContain("Couldn’t sync"));
  expect(result.current.now).toBeNull();
});
