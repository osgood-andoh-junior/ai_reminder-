import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { Preferences } from "@/lib/types";

afterEach(() => vi.unstubAllGlobals());
it("preserves legacy email preference when saving unrelated scheduling settings", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => ({}) });
  vi.stubGlobal("fetch", fetchMock);
  const preferences = {
    email_notifications_enabled: true,
    timezone: "Africa/Accra",
  } as Preferences;
  await api.savePreferences(preferences);
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ timezone: "Africa/Accra" });
  expect(preferences.email_notifications_enabled).toBe(true);
});
