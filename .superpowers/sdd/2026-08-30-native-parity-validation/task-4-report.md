# Task 4 Report: Persistent Runs, Reports, And Acceptance Gate

## Status

DONE_WITH_CONCERNS. Task 4 is implemented directly in the Galaxy-owned parity
module. No subagent, vendor source, network access, real corpus, or fabricated
acceptance evidence was used.

## Implementation

- Added an atomic local `ParityRepository` under the Galaxy application state
  root. Active run envelopes can append new case checkpoints and transition
  once to a terminal status; terminal automated evidence cannot be rewritten.
- Stored manual answers and final acceptance as separate overlays. Manual
  answers may change before acceptance, while acceptance is final and blocks
  later manual rewrites.
- Added canonical, sorted-key JSON and deterministic Markdown projections.
  Reports redact sensitive values and home paths, replace binary payloads with
  byte counts, normalize unordered collections, and reject non-standard JSON
  numbers.
- Added `ParityService` as the public facade for catalogue, corpus, migration,
  run, report, manual-review, and acceptance operations.
- Integrated runs with `TaskRegistry` using kind
  `native-parity-validation`, resources `("cpu", "disk")`, checkpoint/progress
  reporting, serialized `{"run_id": run_id}`, and recovery route
  `/settings/parity`.
- Converted each independent case exception into a redacted failed case and
  continued later cases. Cooperative cancellation keeps completed partial case
  evidence; restored interrupted jobs reconcile the run to `interrupted`.
- Acceptance recomputes the current catalogue and manifest hashes, task/run
  terminal status, effective status from individual checks, and every required
  manual answer. Cancelled, interrupted, failed, blocked,
  manual-pending, incomplete, changed-input, and already accepted runs are
  rejected.
- Added the Vietnamese recovery default for the parity settings workspace.

## TDD Evidence

Initial lifecycle tests failed during collection because `repository.py`,
`reports.py`, and `service.py` did not exist:

```text
3 errors in 0.46s
ModuleNotFoundError: No module named 'app.parity.repository'
ModuleNotFoundError: No module named 'app.parity.reports'
```

The first implementation reached:

```text
27 passed in 1.85s
```

Self-review regressions were then added before their fixes:

```text
FAILED test_acceptance_recomputes_case_status_from_checks
  DID NOT RAISE ParityNotReadyError

FAILED test_canonical_json_normalizes_unordered_and_non_finite_measurements
  ['vram', 'ram', 'wall'] != ['ram', 'vram', 'wall']

FAILED test_start_run_persistence_failure_does_not_leave_active_task
  assert registry.running_count() == 0 (got 1)

FAILED test_canonical_json_normalizes_unordered_and_non_finite_measurements
  "b'raw-consent-audio'" != '<binary:17 bytes>'
```

Each targeted regression passed after the minimal gate/serialization/lifecycle
change. The final focused result is:

```text
31 passed in 2.02s
```

## Verification

```text
python -m pytest tests/parity/test_repository.py tests/parity/test_reports.py tests/parity/test_service.py tests/runtime/test_jobs.py -q
31 passed in 2.02s

python -m pytest tests/parity tests/runtime/test_jobs.py -q -rs
180 passed, 2 skipped in 17.74s

python -m pytest -q -rs
653 passed, 2 skipped, 1 warning, 60 subtests passed in 48.66s

python -m compileall -q app/parity tests/parity
exit 0

git diff --check
exit 0
```

## Self-Review

- Persistence failures before task submission now terminalize the created task
  instead of leaving a false active diagnostic.
- Acceptance derives required status from checks rather than trusting a
  potentially inconsistent aggregate case status.
- Report payloads do not serialize unknown objects via their potentially
  sensitive `repr`; paths and binary values have explicit safe projections.
- Run IDs are confined to one local path component, report formats are an
  allowlist, and all writes use same-directory temporary files plus
  `os.replace`.
- The production patch does not import, patch, launch, or write VoiceStudio and
  introduces no remote operation.

## Concerns

- Two existing parity security tests remain skipped because this Windows
  account lacks symlink privilege (`WinError 1314`).
- The full suite retains the existing Starlette/httpx deprecation warning.
- `ruff` and `black` are not installed in this environment; `compileall`,
  `git diff --check`, focused tests, and the full backend suite were run.
- The required large real-world corpus and manual acceptance remain a user-run
  Phase 15 gate. This task deliberately does not claim or fabricate them.

## Files

- `tools/galaxy_ai_voice_subtitle_studio/app/parity/repository.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/reports.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/service.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/__init__.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/runtime/jobs.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_repository.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_reports.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_service.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/runtime/test_jobs.py`
- `.superpowers/sdd/2026-08-30-native-parity-validation/task-4-report.md`

## Commit

Commit subject: `feat: persist native parity evidence`

---

# Fix Round 1/5 - Independent Review

## Resolution

- **C1:** Acceptance now reconstructs the current catalogue's exact required
  case, check, and manual contract. Missing, duplicate, extra, reordered, and
  aggregate-inconsistent evidence is rejected fail-closed.
- **C2:** `start_run` copies the exact hashed manifest bytes into the immutable
  run directory before submission. The worker inspects that snapshot, resolves
  assets from the original approved root, and verifies the snapshot digest;
  acceptance binds the exact input revision.
- **C3:** Acceptance uses a repository compare-and-commit transaction over the
  run envelope, manual overlay, manifest revision, override evidence, hashes,
  and an exactly matching `DONE` parity task. Concurrent manual/input changes
  invalidate the commit.
- **C4:** All run and report reads, writes, and enumeration use resolved,
  confined managed paths and reject symlinks, reparse points, and Windows
  junctions. Corrupt or unsafe entries are isolated from independent runs.
- **C5:** Finalization compares complete checkpointed `CaseResult` values, so a
  previously appended result cannot be replaced under the same case ID.
- **I1:** JSON and Markdown are written into one content-addressed revision
  directory and published through one atomic pointer. Readers resolve one
  pointer revision and cannot observe a mixed pair.
- **I2:** Threshold overrides persist catalogue/override values, provenance,
  note, and relaxation classification; reports project the evidence.
  Acceptance recomputes effective thresholds. Relaxation requires explicit
  local acceptance evidence, while tightening remains eligible normally.
- **I3:** Strict JSON parsing rejects duplicate keys and overlay duplicates;
  semantic parsers validate IDs, hashes, statuses, field sets, counts, and
  revisions. `list_runs` skips each bad run independently.
- **I4:** The workflow run ID is assigned before `TaskRegistry.create` persists
  the task. Create/persistence and submit failures cannot leave an active task
  or running parity run orphan.

The minor non-string-key issue is also confined naturally: persisted evidence
maps reject non-string keys before canonical report rendering.

## Reviewer Probes

Added regressions for exact contract reconstruction, missing checks, empty and
extra indexes, running task rejection, manifest swap-back, mutated run-owned
input, manual-answer acceptance races, privilege-free junction confinement,
checkpoint content rewrites, atomic report-pair failure, corrupt-run isolation,
duplicate and malformed overlays, submit failure terminalization, persisted
run IDs, threshold relaxation/tightening, and explicit validator relaxation.

TDD RED evidence included 12 initial repository/runtime failures for missing
snapshot and run-ID persistence APIs, three acceptance-state failures, and a
validator regression proving relaxed values remained clamped without explicit
override authorization. Each probe passed after its scoped implementation.

## Verification

```text
python -m pytest tests/parity/test_repository.py tests/parity/test_reports.py tests/parity/test_service.py tests/runtime/test_jobs.py -q
50 passed in 6.17s

python -m pytest tests/parity tests/runtime -q -rs
211 passed, 2 skipped in 17.90s

python -m pytest -q -rs
673 passed, 2 skipped, 1 warning, 60 subtests passed in 53.10s

python -m compileall -q app/parity app/runtime tests/parity tests/runtime
exit 0

git diff --check
exit 0
```

One additional semantic-status isolation probe was added during self-review;
it passed directly through the existing domain status validation.

## Concerns

- Two existing security probes remain skipped because this Windows account
  lacks symlink privilege (`WinError 1314`). The new privilege-free Windows
  junction probe ran and passed.
- The full suite retains the existing Starlette/httpx deprecation warning.
- `ruff` and `black` remain unavailable; focused/full tests, `compileall`, and
  `git diff --check` cover this round's verification.
- No vendor code, network service, or fabricated real corpus/manual acceptance
  was introduced. Real corpus execution and human acceptance remain the user
  gate.

## Files Changed In Round 1

- `tools/galaxy_ai_voice_subtitle_studio/app/parity/__init__.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/corpus.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/reports.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/repository.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/service.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/validators.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/runtime/jobs.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_reports.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_repository.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_service.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_validators.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/runtime/test_jobs.py`
- `.superpowers/sdd/2026-08-30-native-parity-validation/task-4-report.md`
