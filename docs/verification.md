# Verification report

Verified locally on 23 September 2026.

## Automated checks

- Backend: **61 tests passed**. Includes the existing auth/scheduling/agent/Google coverage plus due/future reminders, snooze/read/dismiss, worker restart, concurrency, retries, expired subscriptions, ownership, SSRF rejection, timezone/DST and actual push encryption/VAPID signing with a mocked network transport.
- Ruff formatting and lint: passed.
- Frontend TypeScript and ESLint: passed.
- Next.js production build: passed.
- Frontend components: **9 Vitest tests passed**, covering bell counts, refresh, reminder tabs/actions, enable interaction, denied permission and failed registration.
- Full-stack HTTP integration: **3 Playwright tests passed** through the running Next.js proxy and FastAPI server, including an independent real worker delivering and re-delivering a snoozed reminder while AI was disabled. These use APIRequestContext, not browser automation.
- SQLite migrations: upgrade, downgrade to base, re-upgrade and Alembic schema drift check passed on an isolated database.
- PostgreSQL migration SQL generation: passed. A live PostgreSQL migration was not tested.
- Windows local launcher: started the API, reminder worker and frontend successfully after normalizing duplicate Path/PATH environment entries. The proxied health endpoint and login page returned HTTP 200 on port 3000.

The backend test runner reports two dependency deprecation warnings from Starlette/AnyIO; no tests failed.

## Manual browser checks

Used an isolated SQLite database and disposable account. Verified registration, missing-key assistant state, preference persistence, event creation, task creation, schedule preview and confirmation, calendar sessions, reminders and rescheduling with an excluded date.

A four-hour assignment was split into four one-hour sessions around a 19:00–20:00 meeting, respecting evening preferences and 15-minute breaks. Rescheduling to exclude the first day replaced the sessions and cancelled the four obsolete reminders while creating four replacement reminders. Desktop calendar layout was inspected. Mobile reminder layout was inspected and subsequently adjusted; the final mobile adjustment has not been visually rechecked.

## External and deployment boundaries

The OpenAI connection failed in the restricted process environment and succeeded when run with network access. A live minimal request accepted the configured model and updated tool definitions. The actual Assistant UI subsequently returned a successful response to a no-task-change availability check. Backend tests still inject model/Google responses; HTTP integration tests disable AI. No live Google requests were made. Existing secrets were preserved; newly generated local VAPID keys were appended to ignored backend configuration.

The live Settings page and permission flow were inspected. Browser permission was granted, but the embedded browser returned `jmt17.google.com`, Chromium's legacy staging endpoint, outside the supported provider allowlist. Tempo correctly displayed registration failure instead of claiming success. Live OS push presentation remains unverified. Use a supported regular browser for the documented demo. No provider allowlist was weakened to force an unsupported subscription through.

Docker configuration is supplied, but the local Docker engine was not running. Container startup, live PostgreSQL, Vercel and Render deployment remain unverified. Render compute identifiers were checked against the official [Blueprint reference](https://render.com/docs/blueprint-spec).

See [browser-scenario.md](browser-scenario.md) for a repeatable isolated scenario and [README.md](../README.md) for setup, architecture, configuration and limitations.
