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
