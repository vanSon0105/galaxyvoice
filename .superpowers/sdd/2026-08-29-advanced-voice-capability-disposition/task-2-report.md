# Task 2 Report: Read-only API

## Status

Complete. Task 2 adds the read-only advanced capability catalogue endpoint.
No subagents were dispatched, and no files under `vendor/voicestudio` were
modified.

## Scope Delivered

- Added `GET /api/extensions/capabilities` with the exact
  `{ "capabilities": [...] }` envelope.
- Serialized all fields from the eight immutable Task 1 registry entries in
  stable product order.
- Registered the API router before the frontend SPA mount.
- Exposed no mutation method and introduced no runtime probe, installation,
  network request, or model load.

## Files

- Created
  `tools/galaxy_ai_voice_subtitle_studio/app/server/routers/extensions.py`.
- Modified `tools/galaxy_ai_voice_subtitle_studio/app/server/main.py`.
- Created
  `tools/galaxy_ai_voice_subtitle_studio/tests/server/test_extensions.py`.

## TDD Evidence

### RED

Command:

```text
python -m pytest -q tests/server/test_extensions.py
```

Initial result: `1 failed, 1 passed` with the GET assertion reporting
`404 != 200`. This was the expected failure because the router did not exist.
The POST test already passed through FastAPI's existing method handling.

### GREEN

After adding and registering the thin router, the same focused command passed:

```text
..                                                                       [100%]
2 passed, 1 warning in 1.08s
```

The warning is the repository's existing Starlette deprecation warning for
using `httpx` through `fastapi.testclient`.

## Supporting Verification

Command:

```text
python -m pytest -q tests/server/test_extensions.py tests/extensions/test_capabilities.py tests/server/test_spike.py::ServerApiTests::test_spa_fallback_does_not_hide_missing_api_or_assets
```

Fresh pre-commit result: `10 passed, 1 warning in 1.29s`. This covers the new
router contract, the consumed Task 1 registry contract, and the existing SPA
boundary for missing API paths.

`python -m compileall -q app/server/routers/extensions.py app/server/main.py`
and `git diff --check` both exited successfully.

## Self-Review

- **Requirements:** The endpoint returns one top-level `capabilities` key,
  exactly eight entries, the approved ordered IDs, and all ten disposition
  fields. The first entry is pinned field-for-field to verify tuple-to-array
  JSON serialization and the disabled default.
- **Read-only behavior:** Only a GET route is registered. POST returns 405.
- **Architecture:** The router calls
  `advanced_capability_registry.list_capabilities()` directly and uses
  `dataclasses.asdict`; it contains no workflow or runtime behavior.
- **SPA separation:** The router is included before the SPA mount, and the
  focused GET test verifies JSON is returned at the API path. Existing
  `test_spike.py` coverage continues to pin 404 behavior for missing APIs.
- **Scope:** No Task 3 frontend work, Task 4 documentation, unrelated
  refactoring, or vendor changes were included.
- **Mutation check:** The tests fail for a missing router, wrong envelope,
  missing or extra fields, fewer or reordered entries, incorrect first-entry
  serialization, or an exposed POST handler.

## Concerns

None blocking. The focused run reports one pre-existing Starlette/httpx
deprecation warning; it is unrelated to Task 2 behavior.
