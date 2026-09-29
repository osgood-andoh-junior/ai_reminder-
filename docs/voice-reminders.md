# Voice and reminder delivery

## Behavior

The assistant's Microphone button starts browser speech recognition. Stop finishes recognition; Cancel abandons recording. The transcript appears in the existing editable composer. Send calls the existing `/api/agent/chat` endpoint. No second agent, scheduler, confirmation path, or browser API key exists. Read aloud replays a response; automatic playback is opt-in for the current page. Navigation stops voice activity. Permission, unsupported-browser, recognition and playback errors leave text chat usable.

Speech recognition depends on browser support, microphone permission and HTTPS (localhost is permitted). It may send audio to the browser vendor's recognition service. Xenon does not store audio. Recognition language follows the browser language. Real device support must be checked in the target browser; automated tests use mocked speech APIs.

Each scheduled task session gets independent reminders for these enabled stages:

| Key | Time |
| --- | --- |
| BEFORE_60 | start minus 60 minutes |
| BEFORE_30 | start minus 30 minutes |
| BEFORE_5 | start minus 5 minutes |
| AFTER_10 | start plus 10 minutes |
| END_10 | end minus 10 minutes |

All five default to enabled. Application code calculates elapsed offsets in UTC, including across DST changes; API timestamps require explicit offsets. Past stage times are skipped, not clamped to now. After-start/end stages are skipped unless strictly inside the session, so sessions of ten minutes or less have no such reminders. Two stages that coincide (e.g. a 20-minute session) remain separate stages. Messages are short deterministic templates and need no OpenAI request.

Settings saves stage preferences and reconciles pending reminders on active sessions. Task `reminder_stages=null` inherits preferences; `[]` disables stages; a list replaces the enabled stages. Task `email_reminders_enabled=false` opts out of email. Global email consent is always required, even with a task override of true. Set overrides through `PATCH /api/tasks/{id}/reminder-preferences`, or ask the assistant, which creates a persisted proposal requiring the normal Confirm button. New-task creation also accepts overrides. Custom reminders and optional deadline reminders remain supported. The legacy default offset remains stored for compatibility; automatic sessions now use stages.

Rescheduling pairs remaining sessions in chronological order, preserves their already-published stages and timestamps, cancels obsolete outbox jobs, and updates pending stages. Additional sessions get their own stages. Removed sessions have pending reminders cancelled. Completing/skipping a session or completing/cancelling a task prevents further delivery. Deleting a task cascades its reminders and delivery records. Delivered stage history is retained for rescheduling/completion/cancellation; explicit deletion removes it. Snoozing explicitly creates a new delivery generation.

The migration preserves existing legacy reminders. Existing sessions adopt stage reminders when replanned or when reminder preferences are saved; deployment does not silently backfill notifications.

## Email and reliability

The existing worker publishes reminders and creates durable channel jobs in one transaction. In-app notification visibility is optional; reminder records remain available on the Reminders page. Browser delivery retains the existing subscription/permission controls. Email and browser push default off until enabled by the user.

`EmailNotificationChannel.send_reminder` is the provider boundary, implemented with the already-installed `httpx` library and Resend. The recipient is taken from `User.email`, never from model arguments or an email input. The sender and credentials are server configuration. Email contains a plain-text subject/message, avoiding HTML injection. Provider errors are recorded as safe codes, never provider bodies or credentials.

| Variable | Value |
| --- | --- |
| EMAIL_PROVIDER | `resend` to enable, otherwise empty |
| EMAIL_FROM | Your verified sender, e.g. `Xenon <reminders@your-domain.example>` |
| RESEND_API_KEY | Server-only API key with sending permission |

Set all three identically on the API and worker. No new dependencies or frontend environment variables are needed. An incomplete configuration appears unavailable in Settings. Existing enabled preferences can still be turned off. Unconfigured delivery jobs fail safely while in-app and push continue. Failed jobs are inspectable through the existing owned reminder deliveries endpoint and are not automatically replayed after configuration changes.

The outbox keeps channel, user, reminder/stage relation, occurrence generation, status, attempt count, safe error, sent timestamp, a unique email idempotency key, immutable payload, and retry deadline. A unique partial index prevents two email jobs for the same occurrence. Jobs use existing per-user locks, conditional claims and two-minute leases. Network/429/5xx failures retry with exponential backoff up to five attempts. Dismissal, rescheduling, task completion and disabled preferences suppress unsent jobs.

Resend [retains idempotency keys for 24 hours](https://resend.com/changelog/idempotency-keys). Xenon stops email retries 23 hours after enqueueing, preserving a safety margin; it never retries outside that window, even after a worker restart. Payloads remain identical across retries. Provider acceptance is not proof of inbox delivery; spam filtering and bounces are outside this implementation. Push display retains its stable tags and seven-day browser ledger; clearing browser storage removes that deduplication history. No external transport can be committed atomically with the database.

## Local migration and checks

From the repository root in PowerShell, with existing dependencies installed:

```powershell
Set-Location backend
..\.runtime\python\python.exe -m alembic upgrade head
..\.runtime\python\python.exe -m pytest -q
..\.runtime\python\python.exe -m ruff check app tests
Set-Location ../frontend
npm test
npm run lint
npm run typecheck
npm run build
```

Migration: `backend/alembic/versions/e42b7190_voice_reminder_delivery.py`, revision `e42b7190`, following `c7e2a901`. It adds stage/user/task settings, inbox visibility, stage uniqueness, and email outbox fields/indexes. It does not change production data manually. Back up your database and stop workers before migration. SQLite downgrade requires SQLite 3.35+ and intentionally deletes email jobs before returning to the push-only schema.

Start the application using the existing launcher, which also migrates:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -SkipInstall
```

Alternatively start the API and worker in separate terminals from `backend`:

```powershell
..\.runtime\python\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
..\.runtime\python\python.exe -m app.worker
```

Run `npm run dev` from `frontend`. With a system Python installation, use `python` in place of the bundled interpreter. For a manual test, schedule a session over an hour in the future, confirm it, and inspect the five reminder rows. Disable a stage and verify the pending row is cancelled. Reschedule and verify pending timestamps move. Enable email only after configuring a verified sender; no live email is sent by automated tests.

## Render and Vercel

1. Back up PostgreSQL. Pause the reminder worker while applying the migration and rolling out the API.
2. Keep the API pre-deploy command `python -m alembic upgrade head`. Build both Python services with `pip install -r requirements-lock.txt`. No dependency changes are required.
3. Add `EMAIL_PROVIDER=resend`, `EMAIL_FROM`, and secret `RESEND_API_KEY` to **both** `tempo-api` and `tempo-reminders` in Render. The blueprint includes empty optional entries. Verify the sender domain in Resend; leave entries empty to run without email.
4. Deploy the API with its existing Uvicorn start command, then deploy/resume the worker with `python -m app.worker`. Both must use the same production database and VAPID configuration. Keep the worker continuously running; Vercel request handlers do not replace it.
5. Deploy the frontend on Vercel with root `frontend`, build `npm run build`, and the existing server-only `BACKEND_URL` pointing to the Render API. Retain existing cookie/proxy/FRONTEND_URL configuration. Use HTTPS for microphone/push permissions. Never put email keys in `NEXT_PUBLIC_*` variables.
6. Sign in, verify Settings reports the expected email availability and account recipient, enable desired delivery channels, and test a future reminder. Check `/api/reminders/{id}/deliveries` for provider acceptance/errors. Test microphone permissions and playback on an actual supported browser.

No commit, push, deployment, live-provider send, or production migration is part of the implementation verification.

## Implementation verification and files

Verified locally: 83 backend tests, 16 frontend component tests, four Playwright HTTP proxy tests, Ruff, ESLint, TypeScript checking, and the Next.js production build. The migration test upgrades legacy SQLite data, downgrades, and upgrades again while preserving a delivered push row. PostgreSQL offline migration SQL generation also passed; no live PostgreSQL migration was run. Existing Starlette deprecation warnings and a Vite plugin deprecation notice remain non-failing. Real microphone hardware, live Resend inbox delivery, Google OAuth, and live OpenAI interpretation were not exercised. Test doubles verify speech events, provider requests, and the agent proposal boundary.

Changed/created files by responsibility:

- Backend policy and data: `app/db/models.py`, `app/schemas.py`, `app/services/application.py`, `app/core/config.py`, `app/api/routes.py`, `alembic/versions/e42b7190_voice_reminder_delivery.py` (under `backend/`).
- Agent integration: `backend/app/agent/agent.py`, `backend/app/agent/tools.py`.
- Notification implementation: `backend/app/notifications/stages.py`, `email.py`, `service.py`.
- Backend tests: `backend/tests/test_application.py`, `test_stages_email.py`, `test_reminder_migration.py`.
- Voice and settings UI: `frontend/app/assistant/page.tsx`, `frontend/app/settings/page.tsx`, `frontend/app/globals.css`, `frontend/components/notification-settings.tsx`, `frontend/components/ui.tsx`, `frontend/lib/use-voice.ts`, `frontend/lib/types.ts`.
- Frontend validation/config: `frontend/tests/voice.test.tsx`, `notifications.test.tsx`, `proxy.spec.ts`, `frontend/next.config.ts`, `frontend/eslint.config.mjs`.
- Environment/deployment/docs: `.env.example`, `backend/.env.example`, `.gitignore`, `compose.yaml`, `render.yaml`, `README.md`, `docs/notifications.md`, `docs/browser-scenario.md`, this guide, and `scripts/verify-reminders.py`.

The optional `TEMPO_E2E=1` test-only environment switch isolates Next.js artifacts in `.next-e2e`; do not set it in production. Run `..\.runtime\python\python.exe` commands from `backend` as above, or run `.\.runtime\python\python.exe scripts/verify-reminders.py` from the repository root for the isolated HTTP suite. The harness requires permission to start and stop its own processes and restores Next.js-generated configuration files after running.
