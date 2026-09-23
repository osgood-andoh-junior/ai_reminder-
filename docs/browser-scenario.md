# Repeatable browser verification

Use a **dedicated test database**, never a production account or database. The application does not seed test accounts. The implementation verification used `.runtime/browser-tests.db`, API port 8001, and frontend port 3100.

Start the backend from `backend`, setting `DATABASE_URL=sqlite:///../.runtime/browser-tests.db`, `FRONTEND_URL=http://localhost:3100`, `ENVIRONMENT=test`, and `AI_ENABLED=false`. Run Alembic, then Uvicorn on port 8001. Start the frontend from `frontend` with `BACKEND_URL=http://127.0.0.1:8001` and `npm run dev -- --port 3100`. This prevents live model calls even if a backend environment file contains credentials. With these servers running, `npm run test:e2e` runs the real HTTP proxy integration scenarios without launching an automated browser.

Also start `python -m app.worker` from `backend` with the same test `DATABASE_URL`, `AI_ENABLED=false`, and `REMINDER_POLL_INTERVAL_SECONDS=1`. The notification integration scenario requires this separate worker and verifies actual due/snooze delivery with AI disabled. Only run one Next.js development instance per checkout; stop the normal port-3000 instance before starting the test frontend.

1. Visit `http://localhost:3100/register`; create a disposable test user. Confirm the app redirects to Assistant and shows the no-key notice.
2. Open Settings. Choose Africa/Accra, 19:00–22:00, 60-minute sessions, and 15-minute breaks. Save. Navigate away and back to confirm persistence.
3. Add a fixed event, “Networking Meeting”, next Wednesday 19:00–20:00.
4. Create “Networking assignment”, duration 240 minutes, with a deadline Friday 23:00.
5. Select Plan schedule, then Find available time. Verify four one-hour sessions, no overlap with the meeting, and no time past the deadline. Times are computed from the actual test date; do not assert hardcoded dates.
6. Confirm. Verify the task is Scheduled, the meeting is unchanged, four sessions appear in Calendar, four pending reminders appear in Reminders, and the dashboard/history update.
7. Replan with Wednesday as “A day to keep free”. Verify no proposed session occurs Wednesday. Confirm. Verify the old reminders are CANCELLED and the four replacement reminders are PENDING.
8. Mark a session done; ensure only remaining work is included in the next proposal. Mark the entire task completed; ensure remaining scheduled sessions and active reminders disappear.
9. Add a task requiring six hours with a deadline only five minutes away. Verify no fabricated complete plan appears. If a partial plan is possible, verify it is labeled with remaining minutes.
10. Sign out. Verify private pages require login. Sign in again and check persistence.
11. Repeat basic navigation at a 390px phone viewport. Verify the menu opens/closes, forms fit, and task/reminder actions are usable. Restore the default viewport afterward.

Natural-language interpretation and Google authorization require external credentials and are separate live-integration checks. The automated scripted-model test validates the agent's tool pipeline without a live API. Never describe that double as a real model call.
