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
attestation, and recording validation for SQLite and the published `.ovsvoice`
shape. Compressed consent media must expose a valid audio stream with codec,
sample-rate, channel, and positive-duration metadata; fake magic, video-only
containers, missing ffprobe, and probe failures remain unconfirmed. They
also cover WAL/journal fail-closed behavior and unchanged sidecar bytes,
deterministic SQLite close, full-bundle archive limits, directory and file
entry traversal defenses, streamed byte bounds, sandbox cleanup, source
fingerprints, recursive candidate key/value redaction, the snapshot's
string-list dub tracks, allowlisted studio/export and discovered-document
mappings, unsupported-field warnings, and all four asset states. The public
operation requires explicit typed confirmation from its caller that the
selected source is a copy, while retaining live-root, repository, filename,
link, and reparse defenses. Settings, secrets, raw engine payloads, logs,
caches, and unsafe exports do not enter candidates.

Verification run from `tools/galaxy_ai_voice_subtitle_studio`:

```text
python -m pytest tests/parity/test_migration.py tests/parity/test_security.py -q -rs
55 passed, 2 skipped in 9.09s

python -m pytest -q -rs
542 passed, 2 skipped, 1 warning, 60 subtests passed in 43.59s
```

The two skips are the existing Windows symlink-privilege cases in Task 1
security coverage; all migration tests executed. The warning is Starlette's
existing `httpx` test-client deprecation warning.

Context: [Native Voice Workspace decisions](../map.md#decisions-so-far).
