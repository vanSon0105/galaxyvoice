# VoiceStudio legacy data migration policy

Type: research
Status: resolved
Blocked by: 02, 07, 08, 09, 10

## Question

Which VoiceStudio profiles, persona bundles, projects, transcripts, histories,
and generated assets can be safely imported into Galaxy Project Bundles and
Voice Library records without executing or depending on VoiceStudio code?

## Done when

The supported source schemas, field mappings, consent handling, missing-media
behaviour, dry-run report, rollback strategy, and unsupported-data warnings are
specified against fixture copies of the vendored snapshot's data structures.

## Answer

Phase 15A has a Galaxy-owned, read-only migration rehearsal for typed copied
SQLite databases, copied data directories, and portable persona bundles. It
rejects live VoiceStudio, vendor, Galaxy runtime, top-level link/reparse, and
untyped SQLite sources. It does not apply an import or write to Galaxy
repositories.

Fixture-backed tests now prove strict consent types, valid timestamps, coherent
attestation, and real recording validation for SQLite and the published
`.ovsvoice` shape. They also cover WAL/journal fail-closed behavior and
unchanged sidecar bytes, deterministic SQLite close, full-bundle archive
limits, duplicate/control/traversal defenses, streamed byte bounds, sandbox
cleanup, source fingerprints, redaction, allowlisted dub/studio/export and
discovered-document mappings, unsupported-field warnings, and all four asset
states. Settings, secrets, raw engine payloads, logs, caches, and unsafe exports
do not enter candidates.

Verification run from `tools/galaxy_ai_voice_subtitle_studio`:

```text
python -m pytest tests/parity/test_migration.py tests/parity/test_security.py -q -rs
46 passed, 2 skipped in 7.42s

python -m pytest -q -rs
533 passed, 2 skipped, 1 warning, 60 subtests passed in 71.79s
```

The two skips are the existing Windows symlink-privilege cases in Task 1
security coverage; all migration tests executed. The warning is Starlette's
existing `httpx` test-client deprecation warning.

Context: [Native Voice Workspace decisions](../map.md#decisions-so-far).
