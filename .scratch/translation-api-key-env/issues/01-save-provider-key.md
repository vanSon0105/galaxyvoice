# Save provider API key to User Environment

Status: ready-for-human

Add a local backend endpoint and dubbing UI flow that persist provider API keys
to the current Windows user's environment using provider-specific Galaxy names.

## Acceptance criteria

- DeepSeek uses `GALAXY_DEEPSEEK_API_KEY`; every provider follows the same rule.
- No secret value is returned by an API or written to app config/logs.
- Paste saves immediately; manual input saves on blur.
- The current process can use the newly saved key without restarting.
- Backend and frontend tests cover the behavior.

## Comments

- Implemented provider-specific Windows User Environment persistence.
- Verified with 349 backend tests and 36 frontend tests, plus typecheck, lint,
  and production build.
