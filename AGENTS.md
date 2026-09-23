# Project conventions

Keep AI orchestration separate from authorized application services and deterministic scheduling. Never add demo data to production paths. All resource reads and writes must be scoped to the authenticated user. Store instants in UTC and require explicit offsets at API boundaries. Run backend tests, Ruff, frontend type checks and the production build after substantive changes. Significant agent mutations must produce persisted proposals confirmed through the dedicated API, never through a model-supplied confirmation flag.
