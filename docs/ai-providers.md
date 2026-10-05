# Xenon AI providers

Xenon uses Perplexity exclusively for AI requests. There is no provider fallback.
Provider selection applies to both conversational orchestration and the isolated email commitment extractor.
API startup and manual operations do not require an AI key. `/api/health` reports whether the selected
provider has a key and AI is enabled; this is configuration status, not a live connectivity probe.

## Render backend configuration

Set these environment variables on the Render **API web service** (the blueprint calls it `tempo-api`):

```dotenv
AI_PROVIDER=perplexity
AI_ENABLED=true
PERPLEXITY_API_KEY=<your Perplexity API key>
PERPLEXITY_MODEL=perplexity/sonar
```

Save and redeploy the API. No new dependencies or database migrations are required.
Keep existing Google OAuth, database, encryption, timezone, push, and email configuration.
The deterministic reminder worker does not need an AI key. Do not put the key in the frontend,
Vercel's public environment, source control, logs, or a `NEXT_PUBLIC_*` variable.
The local ignored `.env` files are deliberately not modified by this change.

`AI_ENABLED=false` disables AI. Save configuration and redeploy the latest backend code.

## Verified API contract

Checked against Perplexity's current official documentation on October 5, 2026:

- [Models](https://docs.perplexity.ai/docs/agent-api/models): the exact Sonar ID is `perplexity/sonar`.
- [Create Agent Response](https://docs.perplexity.ai/api-reference/agent-post): authenticated JSON
  `POST https://api.perplexity.ai/v1/agent` with `Authorization: Bearer <key>`.
- Xenon uses its existing `httpx` dependency to call the canonical Agent endpoint directly.
- [Custom functions](https://docs.perplexity.ai/docs/agent-api/tools/custom-functions): tools have
  top-level `type: function`, `name`, `description`, `parameters`, and `strict`. Returned `output`
  items with `type: function_call` contain JSON-string `arguments` and a `call_id`. Xenon replays
  output items, including any thought signature, then adds `function_call_output` with that ID
  and a JSON-string `output`. Final prose comes from assistant message `output_text` content.
- [Disabling search](https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/how-to): omit
  `web_search` and avoid presets. Preset tools cannot be cleared with `tools: []`. Xenon sends an
  explicit direct model and custom functions only, with no preset, profile, connectors, hosted
  tools, or search. Extraction sends an empty tool list.
- [Structured output](https://docs.perplexity.ai/docs/agent-api/output-control): extraction uses
  `response_format: {type: json_schema, json_schema: {name, schema}}`; local Pydantic and evidence
  validation remain authoritative.

Requests use a bounded timeout and `store=false`. Perplexity documents `store=false` as hiding
responses from retrieval, not as a guarantee of zero retention. Xenon supplies its own conversation
history and does not use `previous_response_id`. Perplexity retries are not automatic. Tool calls
are executed sequentially by Xenon, at most four per round and `AGENT_MAX_ITERATIONS` rounds.
Malformed or incomplete envelopes fail before their tools run; invalid tool arguments return
errors to the model. Provider bodies and keys are never included in user-facing errors or logs.

## Application boundaries

The provider receives the existing prompt, authenticated user's bounded chat history, current
timezone-aware server snapshot, server-resolved relative-date references, and tool definitions.
It selects tools; `Registry` validates arguments, user-owned IDs, email provenance and date
references, then calls the existing application services. Providers have no database or Google
Calendar handles. Availability and durations are computed by application code.

A request such as “Schedule a 30-minute meeting with Elliot tomorrow at 3 PM” resolves a saved
contact or asks for the address, uses a server-issued date reference, and calls `propose_meeting`.
The existing meeting service checks only the organizer's availability and persists a proposal.
Only the dedicated authenticated proposal-decision API can confirm it and send the Google
invitation (and request Google Meet when asked). Neither a model flag nor a tool named `confirm`
can approve it. Rescheduling, cancellation, and saving contacts retain their existing proposals.

Completed tool receipts and pending proposals remain available if a later model request fails.
Users see “The AI service is temporarily unavailable. Please retry shortly.” Manual scheduling,
task management, calendar operations, proposal decisions, and reminder delivery remain independent.

## Offline verification

Backend tests clear the Perplexity key independently of local `.env` files. Perplexity tests mock
HTTP responses and exercise actual tool execution, meeting confirmation and Google invitation
transport, server time references, failure handling, and manual operation. Injected provider doubles exercise orchestration. No test requires or uses a real Perplexity key.

Run from `backend`: `python -m pytest -q` and `python -m ruff check .`.
Run from `frontend`: `npm test`, `npm run typecheck`, `npm run lint`, and `npm run build`.
From the project root, `python scripts/verify-reminders.py` runs the Playwright HTTP proxy suite
with isolated services, a separate reminder worker, and both AI credentials cleared.
`python diagnose_ai.py` (from `backend`) is a separate, opt-in **live** check, never part of tests.

Perplexity-only cleanup verification on October 5, 2026: the full backend run passed
199 tests and exposed one obsolete SDK assertion. After updating it to check the provider
protocol, all 22 email tests and all 35 provider tests passed. Ruff, frontend TypeScript
checking and the Next.js production build passed. Backend tests reported two existing
Starlette/AnyIO deprecation warnings. No live AI or Google request was made for this cleanup;
Render deployment and live Perplexity behavior remain unverified. No commits or pushes were made.
