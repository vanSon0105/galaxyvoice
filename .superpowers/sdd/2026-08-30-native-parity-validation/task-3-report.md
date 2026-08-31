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

## Concerns

- Two pre-existing Task 1 symlink tests remain skipped because this Windows
  account lacks symlink privilege (`WinError 1314`); privilege-free reparse
  coverage elsewhere in the parity suite passes.
- The full suite retains one existing Starlette `httpx` deprecation warning.
- The required large real-world corpus and manual acceptance remain a user-run
  Phase 15 gate by design and are not fabricated or claimed here.
