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

## Round 1 Review Fixes

Addressed every finding in `task-5-review.md`.

### Changes

- Normalized real-service missing and malformed run IDs before acceptance so
  both manual and acceptance mutations return the same sanitized HTTP 404.
- Constrained request fingerprints to non-empty IDs, `file|directory` kinds,
  lowercase 64-character SHA-256 values, strict non-negative integer counts,
  and exactly one entry for file fingerprints. Validation completes before
  the route can create a run or task.
- Added stable Vietnamese transport errors. Unsafe paths and invalid input are
  HTTP 422; permission and unexpected filesystem failures are HTTP 500;
  missing reports are HTTP 404. Client responses never include the original
  exception text or selected filesystem path.
- Routed operational I/O failures through the existing diagnostics helper,
  which records the operation and exception type without the exception
  message or path.
- Changed application dependency selection to an explicit `is None` check so
  an intentionally falsey injected parity service is retained.

### Exact Probes

- Real `ParityService`, `ParityRepository`, and `TaskRegistry` probes cover
  unknown and malformed run IDs on both mutation routes.
- Malformed source and reference fingerprints cover bad kind, short and
  uppercase hashes, negative and non-strict counts, empty IDs, and invalid
  file entry counts. Every response is 422 with no repository run or registry
  task left behind.
- Missing, unsupported-schema, and unapproved manifests return sanitized 422
  responses before task creation.
- Corpus, migration, start, and report PermissionError probes return the same
  sanitized JSON 500 response without the private path.
- A falsey service probe verifies exact per-app dependency injection.

### Red/Green Evidence

The corrected RED run produced 20 expected failures: unknown acceptance was
500/409, malformed fingerprints returned 202, input errors exposed details or
were misclassified, report I/O returned an unstructured 500, and falsey DI was
replaced. After the fixes:

```text
python -m pytest tests/server/test_parity_api.py -q
32 passed, 1 warning in 12.09s

python -m pytest tests/server/test_parity_api.py tests/parity -q -rs
225 passed, 2 skipped, 1 warning in 56.32s

python -m pytest -q -rs
712 passed, 2 skipped, 1 warning, 60 subtests passed in 108.11s

python -m compileall -q app tests
exit 0

git diff --check
exit 0
```

The two skips remain the Windows symlink-privilege probes and the warning
remains the existing Starlette/httpx deprecation. No vendor source, network
operation, migration apply path, or fabricated acceptance evidence was added.

Round 1 commit subject: `fix: close parity api review gaps`
