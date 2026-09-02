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

Corpus and migration ZIP inspection now share one pre-extraction archive
policy. It rejects traversal, Windows reserved devices and colon components,
trailing-dot/space aliases, Unicode-normalized duplicates, encrypted entries,
unsupported member types, links, excessive member/total size, and compression
bombs before any member is opened or extracted.

Verification run from `tools/galaxy_ai_voice_subtitle_studio`:

```text
python -m pytest tests/parity/test_migration.py tests/parity/test_security.py tests/parity/test_final_fix_wave.py -q -rs
85 passed in 12.29s

python -m pytest tests -q
751 passed, 1 warning, 60 subtests passed in 76.82s
```

All migration, archive-policy, and final-fix security tests executed. The
warning is Starlette's existing `httpx` test-client deprecation warning.

This resolution is limited to migration policy and read-only dry-run evidence.
It does not provide a production apply/import command, satisfy the real-corpus
and manual acceptance gate in issue 15, or establish native parity. That
boundary is binding in
[ADR 0015](../../../docs/adr/0015-native-parity-validation-is-evidence-gated.md).

Context: [Native Voice Workspace decisions](../map.md#decisions-so-far).
