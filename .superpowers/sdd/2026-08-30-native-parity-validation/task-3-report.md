# Task 3 Report: Fixture Corpus And Deterministic Validators

## Status

DONE_WITH_CONCERNS. The Task 3 corpus inspector and deterministic validators
are implemented and verified. This ships the validation framework only; it
does not claim native parity acceptance without the external corpus and manual
UAT required by the Phase 15 design.

## Takeover State

The replacement session began with an uncommitted patch in `models.py`,
`corpus.py`, `validators.py`, `__init__.py`, both Task 3 test modules, and the
small parity fixture directory. The patch was inspected in full before any
edits. Its inherited focused baseline was already green:

```text
python -m pytest tests/parity/test_corpus.py tests/parity/test_validators.py -q
35 passed in 0.29s
```

The inherited implementation was retained and completed rather than replaced.

## Implementation

- Added strict schema-versioned manifest parsing with exact fields, lowercase
  SHA-256 pins, byte-size pins, duplicate role/case rejection, approved-root
  confinement, and per-asset readiness.
- Added standard-library probes for WAV, JSON, UTF-8 text, read-only SQLite,
  and ZIP/persona bundles. Stream media uses the existing local
  `find_ffprobe()` boundary only when a real user inspection requests it.
- Added injectable `MediaProbe` validation for extensions, containers, codecs,
  stream counts, channel count, sample rate, and duration metadata.
- Added pure duration, subtitle, identity, loudness, performance, cancellation,
  and recovery judges with exact status vocabulary.
- Pinned duration to `max(250 ms, 5%)`, narration to `-16 LUFS +/- 2`, matched
  performance ratios to `<= 1.25`, response p95 to `<= 200 ms`, CPU
  cancellation to `<= 2 s`, accelerator cancellation to `<= 5 s`, and the
  interrupted recovery route to `/settings/parity`.
- Case thresholds may tighten global defaults but cannot silently relax them.
  Subtitle timing tolerance is read from case thresholds, not measurement
  payloads.
- Preserved catalogue check IDs when shared pure judges serve aliases such as
  `speaker_mapping`, `interaction_responsiveness`, and `recovery_route`.
- Added only small committed JSON/SRT fixtures. WAV, SQLite, JSON, text, and
  bundle probe fixtures are generated deterministically under pytest temp
  directories.

## TDD Evidence

First completion RED after the inherited green baseline:

```text
3 failed, 36 passed in 0.58s
FAILED test_small_structured_fixtures_use_standard_library_probes
FAILED test_validate_case_preserves_declared_check_ids_for_alias_judges
FAILED test_validate_case_supports_output_stream_checks_with_injected_probe
```

The corresponding GREEN run passed 39 tests. Self-review then added RED tests
for case-owned subtitle tolerance and the fixed recovery route:

```text
2 failed, 28 passed in 0.31s
FAILED test_recovery_reconciles_interrupted_tasks_and_requires_route_for_resumable
FAILED test_validate_case_uses_case_subtitle_tolerance_not_measurement_threshold
```

The corresponding focused GREEN passed 40 tests. A final extension-contract
RED proved that valid `.wav` expectations were rejected because extension was
not yet modeled:

```text
2 failed, 31 passed in 0.36s
FAILED test_validate_case_checks_required_output_extension[.wav-pass]
FAILED test_validate_case_checks_required_output_extension[wav-pass]
```

Final focused GREEN:

```text
python -m pytest tests/parity/test_corpus.py tests/parity/test_validators.py -q
43 passed in 0.45s
```

## Verification

Full backend suite:

```text
python -m pytest -q -rs
585 passed, 2 skipped, 1 warning, 60 subtests passed in 46.78s
```

`python -m compileall -q app/parity tests/parity` and `git diff --check` are
run again immediately before commit and their final results are recorded in
the completion response.

## Self-Review

- Checked every Task 3 requirement against the design and brief, including
  exact boundary inclusivity and blocked behavior for unavailable evidence.
- Confirmed unit tests inject media probes and make no model, GPU, network, or
  vendor calls.
- Confirmed SQLite probing uses `mode=ro`; no corpus probe mutates fixtures.
- Confirmed validators retain each case's declared check ID and never treat
  `blocked`, `manual_pending`, or `not_applicable` as `pass`.
- Confirmed no vendored VoiceStudio file or import was changed and no large
  binary fixture was added.

## Files Changed

- `tools/galaxy_ai_voice_subtitle_studio/app/parity/__init__.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/models.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/corpus.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/validators.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_corpus.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_validators.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/fixtures/parity/manifest.json`
- `tools/galaxy_ai_voice_subtitle_studio/tests/fixtures/parity/sample.srt`
- `.superpowers/sdd/2026-08-30-native-parity-validation/task-3-report.md`

## Fix Round 2/5 - I2 And I4

### Takeover State

Round 2 started from clean commit `e919856` (`fix: harden native parity
validators`). The rereview marked C1, I1, I3, I5, and I6 addressed and left
only I2 zero-valued applicable metrics and I4 Windows-unsafe ZIP member names
open. No pre-existing uncommitted patch was present at takeover.

### Findings Addressed

- I2: every applicable native/reference wall-time, peak-RAM, and peak-VRAM
  measurement must now be finite and strictly positive. `None` and zero are
  unavailable measurements and return exact `blocked`; negative, non-finite,
  or malformed measurements remain invalid contracts and return `fail`. VRAM
  remains omittable only through the matched explicit applicability contract.
- I4: ZIP metadata preflight now rejects a `PureWindowsPath.drive`, colons in
  any component (including ADS and drive-relative syntax), Windows reserved
  device basenames (including extensions), and components changed by Windows
  trailing-dot/space normalization. Duplicate detection uses the same
  per-component NFC, case-folded, trailing-dot/space-stripped key, so aliases
  collide before any archive member stream or CRC work begins. All prior
  traversal, member type, size, count, ratio, and streamed-byte bounds remain.

### RED Evidence

The exact rereview regressions were added before implementation. The focused
run reproduced all residual paths:

```text
20 failed, 74 passed in 2.31s
6 failures: zero native/reference wall, RAM, and applicable VRAM
14 failures: ADS, drive-relative, device, trailing component, and normalized collision ZIP names
```

In particular, `safe.txt:stream` and `C:relative.txt` were classified `ready`,
all zero native applicable metrics passed, zero reference metrics failed rather
than consistently blocking as unavailable, and device/trailing aliases were
accepted.

### GREEN Evidence

```text
python -m pytest tests/parity/test_validators.py tests/parity/test_corpus.py -q
94 passed in 1.74s

python -m pytest tests/parity -q -rs
151 passed, 2 skipped in 11.78s

python -m pytest -q -rs
636 passed, 2 skipped, 1 warning, 60 subtests passed in 46.82s

python -m compileall -q app/parity tests/parity
exit 0

git diff --check
git diff --cached --check
exit 0
```

### Round 2 Status And Concerns

DONE_WITH_CONCERNS. I2 and I4 from `task-3-rereview.md` are addressed with the
reviewer-requested zero-native and Windows ZIP path probes. Remaining concerns
are unchanged and external to this patch: two parity security tests skip
because this Windows account lacks symlink privilege (`WinError 1314`), the
backend emits the existing Starlette/httpx deprecation warning, and real-corpus
manual acceptance remains a Phase 15 user-run gate.

### Round 2 Files

- `tools/galaxy_ai_voice_subtitle_studio/app/parity/validators.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_corpus.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_validators.py`
- `.superpowers/sdd/2026-08-30-native-parity-validation/task-3-report.md`

## Concerns

- Two pre-existing Task 1 symlink tests remain skipped because this Windows
  account lacks symlink privilege (`WinError 1314`); privilege-free reparse
  coverage elsewhere in the parity suite passes.
- The full suite retains one existing Starlette `httpx` deprecation warning.
- The required large real-world corpus and manual acceptance remain a user-run
  Phase 15 gate by design and are not fabricated or claimed here.

## Fix Round 1

### Status

DONE_WITH_CONCERNS. C1 and I1-I6 from `task-3-review.md` are fixed with
reviewer-specific regression coverage. The remaining concerns are the two
Windows symlink privilege skips, the existing Starlette deprecation warning,
and the external corpus/manual acceptance gate that Phase 15 intentionally
leaves to a real user run.

### Findings Addressed

- C1: `validate_case()` no longer accepts a caller-supplied `CheckResult` as
  evidence. Core judges require raw measurements; non-core behavioral checks
  use a separate typed `BehavioralCheckEvidence` path. Bare booleans are
  rejected. A precomputed pass for duration now returns `blocked` instead of
  bypassing the duration judge.
- I1: pure judges validate runtime shapes and return `fail` for malformed
  nested objects. The case dispatcher converts malformed thresholds and any
  unexpected nested exception into an exact fail result. Probe unavailability
  remains `blocked`; timeout and arbitrary probe failures return `fail`.
- I2: `PerformanceSample.applicable_metrics` makes metric applicability
  explicit. Wall time and peak RAM are always required, native/reference
  contracts must match, and VRAM can be omitted only when both samples declare
  it not applicable. Missing applicable values or references are `blocked`.
- I3: `/settings/parity` is a validator policy constant. Recovery evidence no
  longer contains an expected-route field and cannot redefine or disable the
  route policy.
- I4: ZIP probing preflights every member before opening a stream. It rejects
  traversal and absolute paths, control characters, normalized duplicates,
  links, unsupported member types, encrypted members, directory payloads, and
  count/member/total/compression-ratio excess. CRC reads are chunked and enforce
  member and aggregate streamed-byte limits.
- I5: path resolution, fingerprinting, and media probing isolate `OSError` per
  asset. Disappearance is `missing`; permission/lock errors are `unsupported`
  with a typed finding; unrelated assets continue inspection.
- I6: the manifest and JSON fixture probe share a strict `object_pairs_hook`
  parser that rejects duplicate keys at every object nesting level.

### TDD Evidence

C1/I1 reviewer probes first reproduced all bypass/escape paths:

```text
5 failed, 33 passed in 0.43s
FAILED test_validate_case_rejects_precomputed_result_for_core_judge
FAILED test_pure_judges_fail_closed_for_malformed_nested_objects
FAILED test_validate_case_fails_closed_for_malformed_threshold
FAILED test_validate_case_fails_closed_for_probe_exceptions[error0]
FAILED test_validate_case_fails_closed_for_probe_exceptions[error1]
```

A follow-up C1 RED proved that typed behavioral evidence was not yet accepted
while bare `True` still passed a non-core check. Both probes now pass: typed
evidence is accepted only after core dispatch, and bare booleans are blocked.

I2 was implemented through three RED/GREEN steps: both-side RAM/VRAM omission
first passed instead of blocking; `PerformanceSample` lacked an applicability
contract; and explicit CPU applicability still blocked while a contract that
omitted RAM was not rejected. The final targeted contract run passed 2 tests.

I3 first reproduced a caller-controlled route pass, then proved the policy
field still existed after behavior was fixed:

```text
FAILED test_recovery_route_policy_cannot_be_redefined_by_evidence
FAILED test_recovery_evidence_does_not_expose_expected_route_policy
```

I4's initial adversarial run failed all 11 probes: unsafe names, duplicate and
link members were accepted, all four limits were absent, and `testzip()` opened
member streams before metadata rejection. The final ZIP set passed 10 binding
probes; a self-review RED additionally proved directory payload bytes were
silently skipped before that path was fixed.

I5 and I6 reproduced their reviewed symptoms exactly:

```text
3 failed in 0.35s
FAILED test_asset_fingerprint_io_error_is_isolated_per_asset[error0-missing]
FAILED test_asset_fingerprint_io_error_is_isolated_per_asset[error1-unsupported]
FAILED test_asset_fingerprint_io_error_is_isolated_per_asset[error2-unsupported]

3 failed in 0.30s
FAILED test_manifest_rejects_duplicate_json_keys_at_any_nesting[...-schema_version]
FAILED test_manifest_rejects_duplicate_json_keys_at_any_nesting[...-path]
FAILED test_manifest_rejects_duplicate_json_keys_at_any_nesting[...-container]
```

### Verification

```text
python -m pytest tests/parity/test_corpus.py tests/parity/test_validators.py -q
74 passed in 1.01s

python -m pytest tests/parity -q -rs
131 passed, 2 skipped in 11.26s

python -m pytest -q -rs
616 passed, 2 skipped, 1 warning, 60 subtests passed in 46.00s
```

`python -m compileall -q app/parity tests/parity`, working-tree and staged
`git diff --check`, and the final commit inspection are run after this report
append and recorded in the completion response.

### Fix Round Files

- `tools/galaxy_ai_voice_subtitle_studio/app/parity/corpus.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/validators.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_corpus.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_validators.py`
- `.superpowers/sdd/2026-08-30-native-parity-validation/task-3-report.md`
