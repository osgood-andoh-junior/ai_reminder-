/* eslint-disable @typescript-eslint/no-require-imports */
const { chromium } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");
(async () => {
  const browser = await chromium.launch({ headless: true, channel: "msedge" });
  const output = path.resolve(__dirname, "../../.runtime/xenon-ui");
  fs.mkdirSync(output, { recursive: true });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const preferences = {
    timezone: "UTC",
    preferred_start_time: "09:00",
    preferred_end_time: "17:00",
    preferred_days: [0, 1, 2, 3, 4],
    default_reminder_minutes: 15,
    preferred_task_length: 60,
    break_preference: 10,
    allow_weekend_scheduling: false,
    personalization_enabled: true,
    reminder_stages: ["BEFORE_60", "BEFORE_30", "BEFORE_5", "AFTER_10", "END_10"],
    in_app_notifications_enabled: true,
    browser_notifications_enabled: false,
    email_notifications_enabled: false,
    deadline_reminders_enabled: false,
  };
  const day = new Date().toISOString().slice(0, 10);
  const tasks = [
    {
      id: 1,
      title: "Review the project brief",
      description: "Outline the next steps.",
      priority: "HIGH",
      estimated_duration_minutes: 60,
      deadline: day + "T18:00:00Z",
      status: "SCHEDULED",
    },
  ];
  const events = [
    {
      id: 1,
      title: "Team check-in",
      description: "",
      start_time: day + "T09:00:00Z",
      end_time: day + "T09:30:00Z",
      event_type: "MEETING",
      source: "internal",
      is_recurring: false,
    },
  ];
  const sessions = [
    {
      id: 1,
      task_id: 1,
      start_time: day + "T11:00:00Z",
      end_time: day + "T12:00:00Z",
      status: "SCHEDULED",
    },
  ];
  await page.route("**/api/**", async (route) => {
    const endpoint = new URL(route.request().url()).pathname;
    const fixtures = {
      "/api/auth/me": { id: 9001, name: "Alex", email: "alex@example.test" },
      "/api/preferences": preferences,
      "/api/tasks": tasks,
      "/api/calendar": { events, sessions, reminders: [], timezone: "UTC" },
      "/api/dashboard": {
        tasks,
        events,
        sessions,
        reminders: [],
        timezone: "UTC",
        summary: { active: 1, total: 1, scheduled: 1, completed: 0 },
      },
      "/api/health": { ai_configured: true },
      "/api/reminders/unread-count": { count: 0 },
      "/api/notifications/config": {
        push_configured: false,
        email_configured: false,
        vapid_public_key: "",
      },
      "/api/calendar/google/status": { configured: false, connected: false, synced_at: null },
    };
    await route.fulfill({ json: fixtures[endpoint] ?? [] });
  });
  for (const [size, width, height] of [
    ["desktop", 1440, 1000],
    ["mobile", 390, 844],
    ["small", 320, 640],
  ]) {
    await page.setViewportSize({ width, height });
    for (const route of [
      "dashboard",
      "assistant",
      "tasks",
      "calendar",
      "reminders",
      "settings",
      "login",
      "register",
    ]) {
      await page.goto("http://127.0.0.1:3211/" + route);
      await page
        .locator(
          route === "assistant"
            ? ".assistant-welcome"
            : route === "login" || route === "register"
              ? ".auth-panel"
              : ".page-heading",
        )
        .waitFor();
      if (route === "dashboard") await page.getByText("Today’s timeline").waitFor();
      const scroll = await page.evaluate(() => document.documentElement.scrollWidth);
      if (scroll > width + 1) throw Error(`${route} ${size}: overflow ${scroll}/${width}`);
      if (route === "assistant") {
        const send = await page.getByLabel("Send message").boundingBox();
        if (send.y + send.height > height || send.width < 44)
          throw Error("Composer offscreen or undersized");
      }
      if (size === "mobile" && route === "dashboard") {
        await page.getByRole("button", { name: "Open navigation", exact: true }).click();
        await page.getByRole("link", { name: "Tasks", exact: true }).click();
        await page.getByRole("heading", { name: "Tasks", exact: true }).waitFor();
        if (await page.getByRole("link", { name: "Today", exact: true }).isVisible())
          throw Error("Mobile navigation did not close");
        await page.goto("http://127.0.0.1:3211/dashboard");
        await page.getByText("Today’s timeline").waitFor();
      }
      await page.screenshot({ path: path.join(output, `${route}-${size}.png`), fullPage: true });
    }
    console.log(`${size}: all eight screens fit; composer accessible`);
  }
  if (errors.length) throw Error(errors.join("\n"));
  await browser.close();
  console.log("Brand layout checks passed. Screenshots: " + output);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
