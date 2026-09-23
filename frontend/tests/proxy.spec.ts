import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("notification worker publishes through real proxy while AI is disabled", async ({
  request,
}) => {
  test.setTimeout(60000);
  await request.post("/api/auth/register", {
    data: {
      name: "Notification Test",
      email: `notify-${randomUUID()}@example.com`,
      password: randomUUID(),
    },
  });
  const result = await request.post("/api/reminders", {
    data: {
      title: "Worker demo",
      message: "Delivered without AI",
      reminder_time: new Date(Date.now() + 2000).toISOString(),
    },
  });
  expect(result.status()).toBe(201);
  const reminder = await result.json();
  await expect
    .poll(async () => (await (await request.get("/api/reminders/unread-count")).json()).count, {
      timeout: 30000,
      intervals: [1000],
    })
    .toBe(1);
  expect((await (await request.get(`/api/reminders/${reminder.id}`)).json()).status).toBe("SENT");
  expect((await request.post(`/api/reminders/${reminder.id}/read`)).status()).toBe(200);
  expect((await (await request.get("/api/reminders/unread-count")).json()).count).toBe(0);
  const snoozed = await request.post(`/api/reminders/${reminder.id}/snooze`, {
    data: { until: new Date(Date.now() + 2000).toISOString() },
  });
  expect((await snoozed.json()).status).toBe("SNOOZED");
  await expect
    .poll(async () => (await (await request.get("/api/reminders/unread-count")).json()).count, {
      timeout: 30000,
      intervals: [1000],
    })
    .toBe(1);
  expect((await request.post(`/api/reminders/${reminder.id}/dismiss`)).status()).toBe(200);
  expect((await (await request.get(`/api/reminders/${reminder.id}`)).json()).status).toBe(
    "DISMISSED",
  );
});

test("real proxy: register, plan, confirm, reminders, reschedule, logout", async ({ request }) => {
  const account = {
    name: "Integration Test",
    email: `test-${randomUUID()}@example.com`,
    password: randomUUID(),
  };
  const registered = await request.post("/api/auth/register", { data: account });
  expect(registered.status()).toBe(201);
  expect(registered.headers()["set-cookie"]).toContain("HttpOnly");
  expect((await request.get("/api/auth/me")).status()).toBe(200);
  expect(
    (
      await request.put("/api/preferences", {
        data: {
          timezone: "Africa/Accra",
          preferred_start_time: "19:00",
          preferred_end_time: "22:00",
          preferred_task_length: 60,
          allow_weekend_scheduling: true,
        },
      })
    ).status(),
  ).toBe(200);
  const start = new Date();
  start.setUTCDate(start.getUTCDate() + 1);
  start.setUTCHours(19, 0, 0, 0);
  const end = new Date(start.getTime() + 3600000);
  const event = await request.post("/api/events", {
    data: {
      title: "Networking Meeting",
      start_time: start.toISOString(),
      end_time: end.toISOString(),
    },
  });
  expect(event.status()).toBe(201);
  const deadline = new Date(start.getTime() + 4 * 86400000);
  const created = await request.post("/api/tasks", {
    data: {
      title: "Networking assignment",
      estimated_duration_minutes: 240,
      deadline: deadline.toISOString(),
    },
  });
  expect(created.status()).toBe(201);
  const task = await created.json();
  const proposed = await request.post("/api/calendar/plan", {
    data: { task_id: task.id, not_before: start.toISOString() },
  });
  expect(proposed.status()).toBe(200);
  const plan = await proposed.json();
  expect(plan.feasible).toBe(true);
  expect(plan.slots).toHaveLength(4);
  for (const slot of plan.slots) {
    expect(Date.parse(slot.start) < end.getTime() && Date.parse(slot.end) > start.getTime()).toBe(
      false,
    );
  }
  expect((await (await request.get("/api/calendar")).json()).sessions).toHaveLength(0);
  expect(
    (
      await request.post(`/api/proposals/${plan.proposal.id}/decision`, { data: { accept: true } })
    ).status(),
  ).toBe(200);
  const calendar = await (await request.get("/api/calendar")).json();
  expect(calendar.sessions).toHaveLength(4);
  expect(calendar.events).toHaveLength(1);
  expect(await (await request.get("/api/reminders")).json()).toHaveLength(4);
  const moved = await (
    await request.post("/api/calendar/plan", {
      data: {
        task_id: task.id,
        not_before: start.toISOString(),
        excluded_dates: [start.toISOString().slice(0, 10)],
      },
    })
  ).json();
  expect(moved.feasible).toBe(true);
  expect(
    moved.slots.every(
      (slot: { start: string }) => slot.start.slice(0, 10) !== start.toISOString().slice(0, 10),
    ),
  ).toBe(true);
  expect(
    (
      await request.post(`/api/proposals/${moved.proposal.id}/decision`, { data: { accept: true } })
    ).status(),
  ).toBe(200);
  const reminders = await (await request.get("/api/reminders")).json();
  expect(reminders.filter((r: { status: string }) => r.status === "CANCELLED")).toHaveLength(4);
  expect(reminders.filter((r: { status: string }) => r.status === "PENDING")).toHaveLength(4);
  expect((await request.post("/api/auth/logout")).status()).toBe(200);
  expect((await request.get("/api/tasks")).status()).toBe(401);
  expect(
    (
      await request.post("/api/auth/login", {
        data: { email: account.email, password: account.password },
      })
    ).status(),
  ).toBe(200);
  expect(await (await request.get("/api/tasks")).json()).toHaveLength(1);
});

test("real proxy: missing key and impossible deadline are explicit failures", async ({
  request,
}) => {
  const registered = await request.post("/api/auth/register", {
    data: {
      name: "Boundary Test",
      email: `test-${randomUUID()}@example.com`,
      password: randomUUID(),
    },
  });
  expect(registered.status()).toBe(201);
  const health = await (await request.get("/api/health")).json();
  expect(health.ai_configured).toBe(false); // Test instance must be explicitly keyless.
  expect(
    (
      await request.post("/api/agent/chat", { data: { message: "Schedule my assignment" } })
    ).status(),
  ).toBe(503);
  const task = await (
    await request.post("/api/tasks", {
      data: {
        title: "Impossible deadline",
        estimated_duration_minutes: 360,
        deadline: new Date(Date.now() + 60000).toISOString(),
      },
    })
  ).json();
  const plan = await (
    await request.post("/api/calendar/plan", { data: { task_id: task.id } })
  ).json();
  expect(plan.feasible).toBe(false);
  expect(plan.unscheduled_minutes).toBe(360);
  expect(plan.proposal).toBeUndefined();
  expect((await (await request.get("/api/calendar")).json()).sessions).toHaveLength(0);
});
