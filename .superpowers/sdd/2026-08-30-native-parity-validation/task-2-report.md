# Task 2 Report: VoiceStudio Migration Dry-Run And Issue 17

## Status

DONE_WITH_CONCERNS. The migration rehearsal and issue 17 evidence are complete.
The local Windows account cannot create ordinary symlinks, so two existing
Task 1 security tests remain skipped; privilege-free junction coverage and all
migration tests execute.

## Implementation

- Added `inspect_migration_source()` for approved copied directories, SQLite
  databases, and `.ovsvoice` / `.omnivoice` bundles.
- SQLite is opened through a quoted `file:` URI with `mode=ro` and
  `PRAGMA query_only`; only known columns present in `PRAGMA table_info` are
  selected. Unknown tables/columns are forward-version warnings.
- Explicit mapping covers voice profiles, persona bundles, generation and dub
  history, studio projects, exports, glossary terms, pronunciation entries,
  and discovered documents.
- Consent is confirmed only with complete local attestation evidence and a
  resolvable recording. Incomplete and legacy evidence requires
  re-attestation.
- Assets retain managed, linked, missing, or unsafe state and preserve declared
  checksums for future relink.
- ZIP inspection bounds member count, member bytes, total bytes, and compression
  ratio; blocks absolute/traversal/symlink members; and stream-copies only into
  a temporary sandbox.
- Candidate JSON is bounded before mapping, Galaxy voice models parse normalized
  voice candidates in the sandbox, and `TemporaryDirectory` removes all
  rehearsal output before the second source fingerprint.
- No VoiceStudio module or Galaxy repository is imported or invoked.

## TDD Evidence

Initial RED:

```text
python -m pytest tests/parity/test_migration.py -q
ModuleNotFoundError: No module named 'app.parity.migration'
```

Self-review RED added two regression cases before their fixes:

```text
2 failed, 9 passed in 1.93s
FAILED test_bundle_preserves_checksum_for_declared_missing_asset
FAILED test_sandbox_inside_directory_source_is_rejected_without_mutating_source
```

GREEN:

```text
python -m pytest tests/parity/test_migration.py -q
11 passed in 1.95s
```

## Verification

Brief-required focused suite:

```text
python -m pytest tests/parity/test_migration.py tests/parity/test_security.py -q -rs
17 passed, 2 skipped in 1.95s
```

Full backend suite:

```text
python -m pytest -q
504 passed, 2 skipped, 1 warning, 60 subtests passed in 36.28s
```

`python -m compileall -q app/parity tests/parity` exited 0. `git diff --check`
exited 0 with only Git's LF-to-CRLF working-copy notice for the pre-existing
line-ending policy on `app/parity/__init__.py`.

## Self-Review

- Confirmed the implementation contains `mode=ro` and no write SQL.
- Confirmed archive extraction uses normalized sandbox destinations and never
  calls `ZipFile.extract()` or `extractall()`.
- Confirmed source-directory traversal does not follow symlinks or Windows
  reparse points.
- Confirmed no imports or repository references point into
  `vendor/voicestudio`, Voice Library persistence, project graph persistence,
  or workspace persistence.
- Confirmed unsupported tables are inventoried without selecting their rows,
  and unknown columns never enter normalized records.
- Confirmed sandbox containment is checked before creating a directory, so a
  rejected sandbox cannot mutate the copied source.

## Files Changed

- `tools/galaxy_ai_voice_subtitle_studio/app/parity/__init__.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/migration.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_migration.py`
- `.scratch/native-voice-workspace/issues/17-voicestudio-data-migration-policy.md`
- `.superpowers/sdd/2026-08-30-native-parity-validation/task-2-report.md`

## Concerns

- Two ordinary-symlink security tests are skipped locally because Windows
  returns `WinError 1314`. The two privilege-free junction tests pass.
- The full suite emits one existing Starlette `httpx` test-client deprecation
  warning.

## Fix Round 1

### Status

DONE_WITH_CONCERNS. All Critical and Important findings from
`task-2-review.md` are fixed with targeted regression coverage. Issue 17 was
kept open while the fixes were in progress and resolved only after the focused
and full backend suites passed.

### Reviewer Findings Addressed

- C1: consent now requires strict booleans, non-empty parseable timestamps,
  the published attestation method and fields, a declared recording, and valid
  audio content for both database and bundle sources.
- C2 and I6: copied SQLite sources with WAL/SHM/journal sidecars fail closed,
  sidecars are checked before and after direct inspection, source bytes are
  proven unchanged, and every connection is deterministically closed.
- I1: candidate data is allowlisted and recursively redacted; report-level
  warnings redact embedded home paths and secrets; settings and sensitive JSON
  are unsupported instead of copied.
- I2: archive member count, declared and streamed total size, member size,
  compression ratio, case-insensitive duplicates, semantic control-member
  duplicates, control characters, traversal, absolute paths, and links reject
  the complete bundle before a candidate is emitted.
- I3 and I4: the published top-level `members`, `tags`, `preview`, `license`,
  persona identity/design fields, and `verified_own_voice` consent shape are
  mapped. Dub, studio, export, discovered document, and generated-media
  mappings are structural, asset-aware, and omit raw engine state.
- I5: the public operation verifies a typed copied-source boundary and rejects
  live VoiceStudio/Galaxy roots, repository/vendor paths, renamed arbitrary
  SQLite files, and top-level links/reparse points.
- I7: ticket 17 now cites only the passing evidence below.

### TDD Evidence

Targeted RED runs reproduced every reviewer class, including truthy-string and
invalid-audio consent, WAL sidecars and handle lifetime, archive fail-open
limits, published bundle shape, raw secret/path leakage, incomplete structured
mappings, and copied-source boundary probes. The final self-review added two
more RED probes for a sidecar created during inspection and an absolute path
embedded inside a global warning; both are now GREEN.

```text
python -m pytest tests/parity/test_migration.py tests/parity/test_security.py -q -rs
46 passed, 2 skipped in 7.42s

python -m pytest -q -rs
533 passed, 2 skipped, 1 warning, 60 subtests passed in 71.79s
```

`python -m compileall -q app/parity tests/parity` and `git diff --check` also
exit 0. The diff contains no VoiceStudio imports or vendor changes, retains the
exact SQLite `mode=ro` URI, extracts only into `TemporaryDirectory`, and does
not invoke Galaxy persistence repositories.

### Fix Round Files

- `tools/galaxy_ai_voice_subtitle_studio/app/parity/migration.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/security.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_migration.py`
- `.scratch/native-voice-workspace/issues/17-voicestudio-data-migration-policy.md`
- `.superpowers/sdd/2026-08-30-native-parity-validation/task-2-report.md`

### Remaining Concerns

- M1 (aggregate database/report limits) and M2 (module decomposition) remain
  explicitly deferred to final review, as permitted by Fix Round 1.
- Two ordinary-symlink tests are skipped because this Windows account lacks
  symlink privilege (`WinError 1314`); privilege-free junction/reparse coverage
  passes. The full suite also retains one pre-existing Starlette `httpx`
  deprecation warning.

## Fix Round 2

### Status

DONE_WITH_CONCERNS. C1, I1, I2, I4, I5, and I7 from the scoped re-review are
fixed. Issue 17 was moved back to `claimed` during verification and resolved
only after the focused regressions, compile check, and full backend suite all
passed.

### Reviewer Findings Addressed

- C1: compressed consent recordings now require a successful local ffprobe
  duration probe; fake MP3 magic bytes fail unconfirmed. WAV remains validated
  by the strict standard-library parser.
- I1: report redaction now covers candidate source IDs, targets, consent
  fields, asset roles/hints/checksums, nested data (including names/titles),
  findings, and warnings.
- I2: ZIP directory entries pass through duplicate, control-character,
  traversal, link/reparse, count, size, and compression checks before any
  extraction filtering; one unsafe directory rejects the whole bundle.
- I4: the snapshot's published `dub_history.tracks` shape (`list[str]`) is
  preserved structurally, while object tracks remain allowlisted and raw
  engine payloads remain omitted.
- I5: `inspect_migration_source()` now requires the caller to pass the typed,
  keyword-only `copied_source_confirmed=True`; omission and false reject while
  all existing denylist, format, filename, link, and reparse defenses remain.
- I7: issue 17's claims and verification counts now match this round's passing
  fixtures and suites.

### TDD Evidence

The copied-source contract test first failed because omission did not reject.
After that contract was added, the remaining four regression probes failed on
their reviewed symptoms:

```text
FAILED test_published_bundle_consent_rejects_fake_compressed_audio_magic
FAILED test_every_source_controlled_candidate_field_is_redacted
FAILED test_dub_mapping_preserves_published_string_track_identifiers
FAILED test_archive_unsafe_directory_entry_rejects_whole_bundle
4 failed in 0.79s
```

Each fix then passed its targeted test before the next finding was changed.

### Verification

```text
python -m pytest tests/parity/test_migration.py tests/parity/test_security.py -q -rs
51 passed, 2 skipped in 11.97s

python -m compileall -q app/parity tests/parity
exit 0

python -m pytest -q -rs
538 passed, 2 skipped, 1 warning, 60 subtests passed in 86.81s
```

`git diff --check` exits 0 apart from Git's LF-to-CRLF working-copy notices.
The diff keeps SQLite `mode=ro`, does not import or edit vendored VoiceStudio,
and does not invoke Galaxy persistence repositories.

### Fix Round Files

- `tools/galaxy_ai_voice_subtitle_studio/app/parity/migration.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_migration.py`
- `.scratch/native-voice-workspace/issues/17-voicestudio-data-migration-policy.md`
- `.superpowers/sdd/2026-08-30-native-parity-validation/task-2-report.md`

### Remaining Concerns

- M1 (aggregate database/report limits) and M2 (module decomposition) remain
  deferred minors from the original review.
- Two ordinary-symlink security tests remain skipped because this Windows
  account lacks symlink privilege (`WinError 1314`); junction/reparse coverage
  passes. The full suite retains one existing Starlette `httpx` deprecation
  warning.

## Fix Round 3

### Status

DONE_WITH_CONCERNS. C1, I1, and I7 from `task-2-rereview-round2.md` are fixed.
Issue 17 remained `claimed` until the focused regressions, compile check, diff
check, and full backend suite passed, then its supported claims and counts were
updated before resolution.

### Reviewer Findings Addressed

- C1: compressed consent media now runs a fail-closed ffprobe query selecting
  `a:0` and requires an audio codec, positive sample rate, channel count, and
  duration. A real video-only MP4 stays unconfirmed; missing/failed probes and
  fake compressed data stay unconfirmed; a generated valid FLAC confirms.
- I1: `redact_report_value()` now recursively sanitizes string mapping keys as
  well as values. Stable safe schema keys remain unchanged, sensitive-key
  values remain masked, and nested keys containing home paths or credential
  assignments are redacted without mutating the source mapping.
- I7: issue 17 was reopened during implementation and resolved only after all
  new focused regressions and the full suite passed with the counts below.

### TDD Evidence

Initial targeted runs reproduced both findings:

```text
FAILED test_published_bundle_consent_rejects_video_only_timed_container
FAILED test_every_source_controlled_candidate_field_is_redacted
2 failed, 1 passed in 5.13s

FAILED test_published_bundle_consent_rejects_compressed_audio_without_ffprobe
1 failed in 4.76s

FAILED test_redaction_sanitizes_nested_source_controlled_mapping_keys
1 failed in 0.16s
```

The corresponding targeted GREEN runs passed before the complete migration
and security suites were run.

### Verification

```text
python -m pytest tests/parity/test_migration.py tests/parity/test_security.py -q -rs
55 passed, 2 skipped in 9.09s

python -m compileall -q app/parity tests/parity
exit 0

python -m pytest -q -rs
542 passed, 2 skipped, 1 warning, 60 subtests passed in 43.59s

git diff --check
exit 0
```

The diff keeps SQLite `mode=ro`, uses only the Galaxy-owned local ffprobe
boundary, does not import or edit vendored VoiceStudio, and does not invoke
Galaxy persistence repositories.

### Fix Round Files

- `tools/galaxy_ai_voice_subtitle_studio/app/parity/migration.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/security.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_migration.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_security.py`
- `.scratch/native-voice-workspace/issues/17-voicestudio-data-migration-policy.md`
- `.superpowers/sdd/2026-08-30-native-parity-validation/task-2-report.md`

### Remaining Concerns

- M1 (aggregate database/report limits) and M2 (module decomposition) remain
  deferred minors from the original review.
- Two ordinary-symlink security tests remain skipped because this Windows
  account lacks symlink privilege (`WinError 1314`); junction/reparse coverage
  passes. The full suite retains one existing Starlette `httpx` deprecation
  warning.
