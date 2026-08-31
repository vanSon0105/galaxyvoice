# Task 5 Report: Typed Parity HTTP API

## Outcome

Implemented and registered the nine typed `/api/parity` operations specified
by the Phase 15 design. The FastAPI adapter remains thin: catalogue,
inspection, run execution, persistence, report access, manual evidence, and
acceptance all delegate to the existing `ParityService` facade.

## Implementation

- Added explicit Pydantic request and response contracts for the catalogue,
  corpus inspection, migration dry-run, run start/list/detail, manual answers,
  and acceptance projections.
- Added JSON and Markdown report responses with pinned runtime and OpenAPI
  content types.
- Mapped unknown runs, reports, and manual items to HTTP 404; premature
  acceptance and changed migration sources to HTTP 409; and invalid,
  unsafe, or unapproved path inputs to HTTP 422.
- Required strict `copied_source_confirmed` input for migration inspection;
  omission and `false` are both rejected with HTTP 422.
- Registered one application-scoped `ParityService` backed by the shared
  `task_registry`, while retaining dependency injection for API tests.
- Exposed no parity operation that starts VoiceStudio, applies migration,
  retires a service, or deletes source data.

## Contract Coverage

The API tests pin:

- the exact nine-operation OpenAPI surface;
- catalogue, corpus, and migration response shapes;
- full `StartParityRun` delegation and the returned task/run IDs;
- run list and detail projections;
- report bytes and content types;
- strict manual answer validation and updated-run responses;
- successful, premature, and unknown-run acceptance behavior; and
- traversal rejection for corpus inspection, migration inspection, and run
  creation.

## Verification

```text
python -m pytest tests/server/test_parity_api.py -q
12 passed, 1 warning in 4.12s

python -m pytest tests/server/test_parity_api.py tests/parity -q
205 passed, 2 skipped, 1 warning in 25.99s

python -m pytest -q -rs
692 passed, 2 skipped, 1 warning, 60 subtests passed in 65.95s

python -m compileall -q app tests
exit 0

git diff --check
exit 0
```

An additional OpenAPI probe reported exactly nine parity operations, marked
`copied_source_confirmed` as required, and reported only `application/json`
and `text/markdown` for successful report responses.

## Self-Review

- Every workflow operation crosses the `ParityService` boundary; router-owned
  code is limited to transport validation, domain request construction,
  response projection, and HTTP error mapping.
- Path values are passed to the service with their explicitly selected roots;
  the router does not weaken or replace the domain confinement checks.
- The patch contains no vendor modification, VoiceStudio import or launch,
  migration apply endpoint, network call, or fabricated acceptance evidence.
- Request models forbid extra fields, non-empty text is trimmed and required,
  and manual booleans use strict validation.

## Concerns

- Two existing parity security tests are skipped because this Windows account
  lacks symlink privilege (`WinError 1314`). The privilege-free path checks and
  the API traversal tests pass.
- The full suite retains the existing Starlette/httpx deprecation warning.
- `ruff` is not installed in this environment. Focused/full tests,
  `compileall`, staged diff checks, and manual review cover this task.
- Real corpus execution and human UAT acceptance remain the explicit Phase 15
  user gate; this API task does not claim either has occurred.

Commit subject: `feat: expose native parity validation api`
