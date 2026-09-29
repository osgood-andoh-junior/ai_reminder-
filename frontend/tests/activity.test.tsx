import { expect, it } from "vitest";
import { activityMessage, type Activity } from "@/lib/activity";
const activity = (action: string, details?: Activity["details"]): Activity => ({
  id: 1,
  action,
  details,
  created_at: "2026-09-28T09:00:00Z",
});
it("distinguishes push network failures and historical retries from in-app delivery", () => {
  const message = activityMessage(
    activity("REMINDER_FAILED", { channel: "push", code: "push_network", retry: true }),
  );
  expect(message.title).toBe("Browser notification attempt failed");
  expect(message.detail).toContain("worker could not reach");
  expect(message.detail).toContain("A retry was scheduled");
  expect(message.detail).toContain("in-app reminder");
});
it("explains exhausted email attempts without suggesting they are still retrying", () => {
  const message = activityMessage(
    activity("REMINDER_FAILED", { channel: "email", code: "email_not_configured", retry: false }),
  );
  expect(message.title).toBe("Email reminder attempt failed");
  expect(message.detail).toContain("server setup");
  expect(message.detail).toContain("No automatic retries remain");
});
it("distinguishes provider acceptance from a guaranteed device popup", () => {
  expect(activityMessage(activity("REMINDER_PUSH_ACCEPTED")).detail).toContain("device controls");
  expect(activityMessage(activity("REMINDER_SENT")).detail).toContain("tracked separately");
});
it("retains older activity records without details", () => {
  expect(activityMessage(activity("REMINDER_FAILED")).title).toBe(
    "Reminder delivery attempt failed",
  );
  expect(activityMessage(activity("TASK_CREATED")).title).toBe("task created");
});
