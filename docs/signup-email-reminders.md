# Signup email reminders: implementation and deployment

## Existing systems and changes

Xenon already provided email/password signup, hashed cookie sessions, account email normalization, user notification preferences, task overrides, five deterministic UTC reminder stages, in-app notifications, Web Push, the Resend channel, and a durable leased notification outbox. These are reused. Google Calendar, Gmail, Perplexity and proposal confirmation remain separate.

Added authenticated email verification, explicit reminder consent, signup messaging, verification and resend controls in existing Settings, a confirmation page, and eligibility checks when queuing and sending reminder emails. Email includes the task title/message, scheduled start or custom reminder time in the user's timezone with UTC offset, and a link to the authenticated reminders page. Task descriptions are not included. Latest email delivery status in Settings is scoped to the signed-in account; provider acceptance does not claim inbox receipt.

## Accounts and migration

Revision `91d2c4ab` follows `a12e93b4`. Upgrade adds nullable `users.email_verified_at` and `users.email_reminders_opted_in_at`, plus `email_verifications` containing owner ID, address snapshot, SHA-256 token digest, creation/expiration/consumption timestamps, and delivery status. Upgrade uses additive operations; it never recreates existing tables. Existing IDs, email, password hashes, sessions, tasks, calendar data, preferences, reminders, notification history and integration records are untouched. Saving scheduling preferences omits email consent, preserving legacy email values without accidentally opting users in. Both new columns start NULL; old email preferences are preserved but do not authorize email delivery without new verification and explicit consent. Downgrade removes only this feature's fields/table and is not recommended in production because it discards verification and consent history.

A populated SQLite migration test checks legacy columns byte-for-byte and checks existing password login. Existing migration tests also cover notification and Google connection preservation. PostgreSQL migration SQL is generated and checked, but a live PostgreSQL migration/concurrency test has not been executed.

New users: signup sends a verification message when email is configured, keeps normal session login, and opens Settings with the actual delivery outcome. Existing users: log in normally, send verification from Settings, follow the link while signed into the owning account, and explicitly enable Email reminders. No Google account is required. Disabling email leaves push/in-app preferences unchanged.

No account-email editing endpoint exists. Tokens bind to the current registered address; queued emails whose destination differs from the current address are cancelled. Any future email-change flow must clear verification and consent, and require verification of the new address.

## Verification security and delivery

Tokens use `secrets.token_urlsafe(48)`, expire in one hour, and are consumed atomically once under the existing user lock. Successful verification invalidates other outstanding links. Only SHA-256 digests are persisted; raw tokens exist briefly in memory and in the outgoing verification email. The URL fragment keeps tokens out of URL access logs/referrers; the page removes the fragment immediately. Tokens are sent in a protected POST body, and validation errors omit submitted inputs. Do not enable request-body logging or email-provider click tracking for verification messages. Sign in first, then reopen the verification email if opening it in a signed-out browser.

Resends require a session, have a persistent one-minute cooldown and five requests per hour per user, and also use the existing IP auth limiter. They accept no arbitrary target email, preventing account enumeration through this API. Failed sends are recorded and can be retried after the cooldown. Provider acceptance never verifies an account. Verification messages are sent synchronously through the existing Resend channel; they do not use an automatic retry queue because raw tokens are not persisted. If the API crashes before committing a send, request another message. Worker cleanup removes verification metadata more than one day after expiry.

API database dependencies now use FastAPI function scope, committing before sending responses. This fixes a real proxy test race where a follow-up request could see uncommitted signup/task/reminder changes. FastAPI 0.121+ is required; the existing lock file already pins 0.141.1. See [FastAPI dependency lifecycle](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#early-exit-and-scope).

## Reminder worker

`python -m app.worker` runs independently of the web server and browser. Existing transactional publication and unique email occurrence index prevent duplicate outbox creation. Atomic leases and user locks serialize delivery; expired leases resume after worker restarts. Emails retain a stable Resend idempotency key and frozen payload, retry up to five attempts with bounded exponential backoff, and stop after the existing 23-hour retry window. Resend's deduplication window is [24 hours](https://resend.com/changelog/idempotency-keys), so later retries are deliberately refused. This is not an unlimited exactly-once guarantee.

At delivery time the worker checks ownership, active task/session, reminder generation/status, verification, explicit consent, user email preference, task override, and the destination against the registered email. Changed addresses, revoked consent, completion, cancellation or rescheduling suppress obsolete emails. All five existing stage calculations and DST handling remain unchanged. `SENT` for an email means Resend accepted it; inbox delivery and bounce status require provider diagnostics/live validation.

## Required configuration

On both Render API and worker set:

- `DATABASE_URL`: same existing Render PostgreSQL database.
- `FRONTEND_URL`: public HTTPS Vercel/custom-domain Xenon URL; used for verification and reminder links.
- `EMAIL_PROVIDER=resend`.
- `EMAIL_FROM=Xenon <reminders@your-verified-domain>`.
- `RESEND_API_KEY`: backend-only secret with sending permissions.
- Preserve existing `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` for push.

API also keeps `ENVIRONMENT=production`, `COOKIE_SECURE=true`, existing `SECRET_KEY` (32+ characters), session and Google/Perplexity settings. Worker keeps `REMINDER_POLL_INTERVAL_SECONDS=10` (or the existing desired interval). Vercel uses server-only `BACKEND_URL` pointing at the Render API. Never put Resend or provider secrets in `NEXT_PUBLIC_*`. No new verification configuration variables are required.

## Exact deployment steps (approval required; not performed)

1. Back up the existing Render PostgreSQL database and record the current Alembic revision and row counts. Rehearse this additive migration against a restored staging copy. Do not create a replacement production database or rerun initial schema creation.
2. In Resend, verify the sending domain and required DNS records. Configure the three email variables above on both existing Render services. Set the same HTTPS `FRONTEND_URL` on API and worker. Disable click tracking on verification emails and verify fragments survive the real mail client.
3. Deploy approved backend changes to the existing Render API: root directory `backend`, build `pip install -r requirements-lock.txt`, pre-deploy `python -m alembic upgrade head`, start `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log`, health path `/api/health`. Verify revision `91d2c4ab` before starting the new worker. Render pre-deploy commands require an eligible paid service; if unavailable, execute the migration once through an authorized Render shell/job before rollout. [Render deployment lifecycle](https://render.com/docs/deploys).
4. The repository already declares worker `tempo-reminders` in `render.yaml`; its actual deployment has not been confirmed. In Render, confirm it exists and is running. If absent, choose New → Background Worker, select the approved repository/branch, Python runtime, root `backend`, build `pip install -r requirements-lock.txt`, start `python -m app.worker`, and apply the environment variables above. Use the existing database connection string. [Render background workers](https://render.com/docs/background-workers).
5. Deploy the approved frontend to the existing Vercel project (root `frontend`, production build `npm run build`) with the existing server-side `BACKEND_URL`. Keep cookies, domains and Google callbacks unchanged. The Blueprint now prompts for email configuration instead of overwriting it with empty strings.
6. Run the live checklist below using consenting test accounts. Production automatic email reminders are not verified until receipt is confirmed.

## Production verification checklist

- Existing account logs in with its original password; existing sessions and user/task/calendar/integration IDs are preserved.
- Existing notification preferences/history are intact, with verification and new consent unset.
- New signup succeeds and shows truthful verification delivery status, including configuration or delivery failures.
- Verification message arrives at the registered address; valid link confirms only its owner. Expired/reused/wrong-account links fail. Resend cooldown works.
- Verification alone leaves reminders off. Explicit enable in Settings records consent. Disable preserves in-app and browser channels.
- Create and confirm a task schedule; inspect all five configured checkpoints and task overrides.
- Close the browser; confirm the independent worker creates/claims email outbox jobs at the expected UTC instants.
- Inspect outbox/provider results and verify actual inbox receipt, sender domain, local date/time and secure Xenon link.
- Retry a transient error in staging; restart the worker and test concurrent workers without duplicate acceptance.
- Complete/reschedule tasks or disable email before delivery and confirm obsolete emails are cancelled.
- Confirm push/in-app delivery still works and another account cannot read status or verify the first account.
- Confirm Google Calendar sync, meeting proposals/Meet creation/invitations and optional Gmail reading still work.

## Validation results

Executed on 2026-10-09 using the bundled `.runtime/python/python.exe` (the local `.venv` lacks pytest/Ruff):

- Backend: `python -m pytest -q` from `backend`: **219 passed**, two existing dependency deprecation warnings.
- Ruff: `python -m ruff check backend`: **passed**.
- Frontend: `npm test`: **64 passed** in nine test files.
- Frontend: `npm run typecheck` and `npm run lint`: **passed**.
- Frontend: `npm run build`: **passed**, including `/verify-email`.
- Isolated real Next.js proxy/API/background worker: all **4 Playwright scenarios passed** after fixing transaction timing. The harness returned nonzero because sandbox permissions blocked process cleanup; all three test servers were subsequently stopped using authorized process-management commands. Assertions passed; the harness exit status is not reported as success.
- SQLite populated migration and legacy login: **passed**. PostgreSQL offline migration SQL: **passed**.
- `git diff --check`: **passed** (only line-ending notices).

Initial failures exposed an outdated frontend verification expectation and an incorrect migration predecessor; both were corrected before the final checks. No external provider sends occur in these tests.

## Limitations

No production configuration was changed, no live email was sent, and no commit/push/merge/deploy was performed. Google live credentials and real inbox receipt remain production checklist items. PostgreSQL was checked through offline SQL generation, not a live server. Verification has safe manual resend rather than persisted automatic retries. Provider acceptance is not inbox receipt. Existing frontend/backend test tools emit dependency/navigation deprecation warnings.

## Exact changed files

The implementation changes are listed below; generated test-server files are not feature changes.

- `.env.example`
- `README.md`
- `backend/.env.example`
- `backend/app/api/routes.py`
- `backend/app/core/security.py`
- `backend/app/db/models.py`
- `backend/app/main.py`
- `backend/app/notifications/service.py`
- `backend/app/schemas.py`
- `backend/app/services/application.py`
- `backend/app/worker.py`
- `backend/requirements.txt`
- `backend/tests/conftest.py`
- `backend/tests/test_stages_email.py`
- `frontend/components/auth-form.tsx`
- `frontend/components/notification-settings.tsx`
- `frontend/components/provider.tsx`
- `frontend/lib/api.ts`
- `frontend/lib/types.ts`
- `frontend/tests/notifications.test.tsx`
- `render.yaml`
- `backend/alembic/versions/91d2c4ab_email_verification.py`
- `backend/app/services/email_verification.py`
- `backend/tests/test_email_verification.py`
- `backend/tests/test_email_verification_migration.py`
- `docs/signup-email-reminders.md`
- `frontend/app/verify-email/page.tsx`
- `frontend/tests/email-consent.test.tsx`

