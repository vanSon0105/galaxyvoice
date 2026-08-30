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

Phase 15A now has a Galaxy-owned, read-only migration rehearsal for copied
SQLite databases, copied data directories, and portable persona bundles. It
does not apply an import or write to Galaxy repositories.

The fixture-backed tests prove that supported records map into explicit dry-run
groups; incomplete consent is downgraded for local re-attestation; managed,
linked, missing, and unsafe assets remain distinct; unknown schemas and
unsupported settings/jobs/logs/model caches are inventoried; oversized JSON
and archive members are rejected; traversal is blocked; temporary sandbox
content is removed; and source fingerprints, table inventory, and row counts
remain unchanged.

Verification run from `tools/galaxy_ai_voice_subtitle_studio`:

```text
python -m pytest tests/parity/test_migration.py tests/parity/test_security.py -q -rs
17 passed, 2 skipped in 1.95s

python -m pytest -q
504 passed, 2 skipped, 1 warning, 60 subtests passed in 36.28s
```

The two skips are the existing Windows symlink-privilege cases in Task 1
security coverage; all migration tests executed. The warning is Starlette's
existing `httpx` test-client deprecation warning.

Context: [Native Voice Workspace decisions](../map.md#decisions-so-far).
