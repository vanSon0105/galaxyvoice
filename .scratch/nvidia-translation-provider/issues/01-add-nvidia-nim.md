# Add NVIDIA NIM translation provider

Status: ready-for-human

Add NVIDIA NIM to the dubbing translation workflow.

## Acceptance criteria

- NVIDIA uses `GALAXY_NVIDIA_API_KEY` with `NVIDIA_API_KEY` as a fallback.
- Hosted requests use `https://integrate.api.nvidia.com/v1`.
- `nvidia/riva-translate-4b-instruct-v2` is the default model.
- Dynamic discovery excludes models that cannot translate text and keeps the
  recommended Riva model first.
- NVIDIA requests are serialized and paced to avoid the account's 40 RPM limit.
- Riva responses preserve one translated result per subtitle cue.
- Backend and frontend metadata tests pass without exposing API keys.

## Comments

- Added NVIDIA NIM provider metadata, Galaxy/User Environment key lookup, and
  OpenAI-compatible model discovery.
- Riva Translate v2 uses its language-pair prompt and validates one result per
  subtitle cue; other NVIDIA text models keep the generic chat translation flow.
- NVIDIA calls are serialized, paced below 40 RPM, and retry HTTP 429 responses.
- Verified against the live NVIDIA model catalog, 356 backend tests plus 60
  subtests, 36 frontend tests, typecheck, lint, and production build.
