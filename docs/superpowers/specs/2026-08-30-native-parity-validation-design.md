# Native Parity Validation And Migration Rehearsal Design

## Purpose

Phase 15 supplies the evidence required to decide whether Galaxy's native
voice workspaces can replace the embedded VoiceStudio reference. It also
absorbs issue 17 by specifying and rehearsing a read-only migration policy
before parity is judged. The result is a Galaxy-owned validation system, not a
VoiceStudio test harness or a production migration command.

The system must never declare native parity merely because automated unit
tests pass. Retirement readiness requires a complete fixed corpus, passing
required checks, completed manual acceptance items, and an explicit local user
sign-off.

## Scope

Phase 15 delivers:

- a typed parity case catalogue covering shared foundations and all six native
  voice workspaces;
- a versioned fixture manifest that identifies small repository fixtures and
  large external media by checksum;
- read-only inspection and dry-run mapping of copied VoiceStudio data;
- deterministic output, portability, recovery, and performance validation;
- persistent parity runs and exportable JSON and Markdown reports;
- a Settings-owned parity page for corpus readiness, execution, findings, and
  user acceptance; and
- binding migration and parity decision records for issues 17 and 15.

Phase 15 does not:

- patch, import, or execute VoiceStudio application source;
- write to a live VoiceStudio data directory or database;
- apply migration plans to the user's real Galaxy library or projects;
- download models or media while reading the catalogue or opening the page;
- make remote network requests;
- enable any Phase 14 deferred or optional capability; or
- retire or delete VoiceStudio. Retirement remains Phase 16.

## Architecture

Galaxy owns a deep `app.parity` module with five public operations:

1. list the immutable validation catalogue;
2. inspect a fixture manifest and report corpus readiness;
3. inspect a copied VoiceStudio data source and produce a migration dry-run;
4. execute a parity run through the existing persistent `TaskRegistry`; and
5. record explicit user acceptance against an unchanged completed run.

HTTP routers only validate requests and serialize these service results. The
React page consumes the same API and does not reproduce validation rules.
Parity runs are stored under Galaxy local application data, outside source
control and outside VoiceStudio's data directory.

## Migration Policy: Phase 15A / Issue 17

### Source boundary

Migration inspection accepts only an explicit user-selected path. The source
must be a copied VoiceStudio data directory, copied `omnivoice.db`, or portable
persona bundle. Inspection opens SQLite in read-only URI mode, never runs
VoiceStudio migrations, never imports a module from `vendor/voicestudio`, and
never follows a path outside the selected source unless the manifest records
that path as an external missing-media candidate.

The dry-run records source fingerprints before and after inspection. A changed
source fingerprint fails the rehearsal because read-only behavior can no
longer be proven.

### Supported source records

| VoiceStudio source | Galaxy dry-run target | Mapping policy |
| --- | --- | --- |
| `voice_profiles` | `VoiceProfileRecord` candidate | Preserve stable source ID as provenance, name, language, kind, description, reference text, instruction, reference/locked audio candidates, seed/design state, timestamps, and consent evidence. `clone` maps to `cloned`, design-like profiles map to `designed`, and unknown kinds map to `imported`. |
| `.ovsvoice` / legacy `.omnivoice` | `.galaxyvoice` import candidate | Inspect ZIP members and normalized metadata without extracting outside a temporary sandbox. Preserve identity, reference assets, tags, license metadata, preview, and consent evidence. Legacy bundles are always unverified. |
| `generation_history` | archival Studio take candidate | Preserve text, mode, language, instruction, profile reference, duration, seed, starred state, timestamps, and existing audio as a managed/linked asset candidate. Engine caches and replay promises are not preserved. |
| `dub_history` | Dubbing project candidate | Parse `tracks` and `job_data` as bounded JSON; preserve source identity, language, segment/track metadata, content hash, and resolvable output paths. Unsupported engine-private fields remain provenance warnings. |
| `studio_projects` | media/project candidate | Preserve name, source video/audio candidates, duration, and parseable state metadata. The dry-run reports which state fields have no Galaxy equivalent rather than dropping them. |
| `export_history` | archival asset candidate | Preserve destination, mode, filename, and timestamp only when the referenced output exists or can be relinked. |
| `glossary_terms` | terminology candidate | Preserve project scope, source, target, note, automatic/manual origin, and timestamp. |
| `pronunciation_entries` | pronunciation candidate | Preserve term, replacement, type, language, enabled state, and timestamp. |

Transcripts, story/audiobook documents, batch manifests, and generated assets
found as files below the selected copied data root are classified by known
JSON/media signatures. They become import or relink candidates only when the
payload is valid and the target Galaxy workflow can represent the required
timing, chapter, cast, or item structure. Unknown files are inventoried but
never interpreted heuristically as executable data.

### Consent and identity

Voice identity is never strengthened during migration:

- `verified_own_voice` is evidence, not an instruction to set Galaxy consent;
- Galaxy `ConsentRecord.confirmed` is true in a rehearsal candidate only when
  non-empty consent text, a resolvable consent recording, and a coherent
  attestation are all present;
- absent or incomplete evidence produces an unconfirmed candidate with an
  actionable re-attestation warning;
- reference audio remains local and is never uploaded; and
- duplicate names do not overwrite Galaxy voices. The eventual importer must
  create a new ID or require an explicit merge decision.

### Missing media and rollback

Every asset candidate is `managed`, `linked`, `missing`, or `unsafe`. Missing
assets retain the original relative or redacted absolute hint and an expected
checksum when available so a future import can offer relink. Paths escaping a
portable bundle or copied data root are `unsafe` until explicitly selected by
the user.

Phase 15 rehearsal writes normalized candidates only into a temporary sandbox,
validates that Galaxy models can parse them, exports the dry-run report, and
then deletes the sandbox. It does not mutate the real Voice Library, project
graph, history repositories, or source. Rollback is therefore deletion of the
sandbox and report; source fingerprints prove the source stayed unchanged.

### Explicitly unsupported data

The following are inventoried with reasons but never migrated: encrypted or
plain settings and tokens, analytics identifiers, crash/runtime logs, model
caches, downloaded engines, active jobs and job events, MCP client bindings,
remote-backend credentials, marketplace/community state, temporary previews,
and process locks. Unknown database tables or newer schema columns produce a
forward-version warning and cannot silently enter a Galaxy record.

Resolving issue 17 means the policy, source fixture schemas, dry-run report,
consent behavior, missing-media behavior, sandbox rollback, and unsupported
warnings are implemented and tested. It does not mean a production apply
migration is available.

## Fixture Corpus

### Manifest

`ParityFixtureManifest` has a schema version, corpus ID, creation metadata, and
ordered cases. Every file entry contains a logical role, relative path within
an approved root, SHA-256 checksum, byte size, and optional media expectations.
Absolute paths are local configuration and are excluded from exported reports.

Small text, JSON, SQLite, SRT, WAV, and bundle fixtures live under
`tests/fixtures/parity/`. Large real-world media stays outside Git and is
selected by the user. The manifest verifies it by checksum so two runs cannot
quietly use different source media.

The required corpus is:

1. short single-speaker TTS;
2. long TTS with expressive text and terminology;
3. noisy clone-reference audio with consent variants;
4. a 50-item batch containing successes and deterministic failures;
5. a 45-minute multilingual video with timed captions;
6. a two-speaker dubbing project with mixed source audio;
7. a multi-character story script; and
8. EPUB and PDF audiobook sources with chapter boundaries.

Each case can point to pre-generated VoiceStudio reference artifacts and
Galaxy native artifacts. VoiceStudio is not required to be running during a
parity run. Regenerating reference outputs remains a deliberate comparison
action while the separate reference service is still available.

### Readiness

Corpus inspection reports `ready`, `missing`, `checksum_mismatch`,
`unsupported`, or `unsafe_path` per asset. A required missing or mismatched
asset blocks execution of its case but does not prevent unrelated cases from
being inspected. No validation result is reused after an input checksum or
threshold changes.

## Validation Catalogue

Every `ParityCase` has a stable ID, owning area, title, required flag, fixture
roles, ordered checks, manual acceptance prompts, and default thresholds. Core
areas are Shared Foundation, Studio, Batch, Voice Library, Transcripts,
Dubbing, Longform, Migration, and Reliability.

Check results use exactly these states:

- `pass`: the measured assertion met its threshold;
- `fail`: the assertion ran and missed its threshold;
- `blocked`: required input, tool, or completed artifact was unavailable;
- `manual_pending`: an explicit human observation is still required; and
- `not_applicable`: an optional check is excluded by the case contract.

`blocked` and `manual_pending` are never treated as success. A run is ready for
sign-off only when every required automated check passes and every required
manual item has been answered positively.

## Validators And Thresholds

### Output validators

- File/container checks use `ffprobe` when media streams are involved and the
  standard library for WAV, ZIP, JSON, text, and SQLite fixtures.
- Required output extensions, codecs, audio/video stream presence, channel
  count, sample rate, and subtitle stream presence are explicit case data.
- Duration passes when the absolute delta is no more than the larger of 250 ms
  or 5 percent, unless a stricter fixture threshold is declared.
- Subtitle cue count and order are exact. Timing tolerances are declared per
  case; text normalization may normalize line endings and Unicode whitespace
  but cannot reorder or omit cues.
- Language and speaker mappings are exact normalized IDs. Display labels are
  reported separately and do not substitute for identity.
- Loudness uses the existing audio postproduction measurement path. The default
  narration target is -16 LUFS with a 2 LU tolerance; a fixture may declare a
  different approved target.
- Project reopen, moved-directory portability, missing-media relink,
  checkpoint resume, and handoff return are behavioral validators over Galaxy
  repositories, not string checks against manifests.

### Performance validators

Performance samples record hardware identity, resolved device, app version,
wall time, peak process RAM, peak accelerator memory when measurable,
cancellation acknowledgement latency, and UI/API responsiveness samples.
Secrets and absolute user paths are redacted before persistence.

Default gates are:

- native wall time, peak RAM, and peak VRAM each stay at or below 1.25 times
  the matched VoiceStudio reference measurement;
- foreground UI/API interaction p95 stays at or below 200 ms while a job runs;
- cancellation is acknowledged within 2 seconds for CPU jobs and 5 seconds
  for accelerator jobs; and
- after a forced shutdown, no task remains falsely `running`, and every
  interrupted resumable workflow exposes its recorded recovery route.

If a reference measurement or supported metric is unavailable, the result is
`blocked`, not zero and not pass. Fixture manifests may tighten thresholds but
cannot relax the defaults without recording an explicit local override in the
report. An override prevents automatic retirement readiness and requires a
manual acceptance note.

## Run Lifecycle And Persistence

A parity run is immutable after completion except for manual answers and the
final acceptance record. It records catalogue version, fixture manifest hash,
app version, source/reference fingerprints, thresholds, checks, measurements,
warnings, timestamps, and report paths.

Execution uses `TaskRegistry` with kind `native-parity-validation`, recovery
route `/settings/parity`, cooperative cancellation, progress, and redacted
logs. Independent cases continue after another case fails. A cancelled or
interrupted run remains available as evidence but cannot be accepted.

Reports are written atomically beneath Galaxy local application data. JSON is
the canonical machine-readable form; Markdown is a deterministic projection
for human review. Neither report contains API keys, tokens, raw consent audio,
absolute home paths, or copied VoiceStudio database contents.

## HTTP API

The thin router exposes typed Pydantic responses:

- `GET /api/parity/catalogue` lists case definitions and catalogue version;
- `POST /api/parity/corpus/inspect` validates a fixture manifest and approved
  roots without running workflows;
- `POST /api/parity/migration/inspect` performs the read-only migration dry-run;
- `POST /api/parity/runs` starts a persistent validation task;
- `GET /api/parity/runs` lists summaries;
- `GET /api/parity/runs/{run_id}` returns a complete run;
- `GET /api/parity/runs/{run_id}/report?format=json|markdown` returns an
  existing report;
- `POST /api/parity/runs/{run_id}/manual-items/{item_id}` records a positive or
  negative UAT answer with a note; and
- `POST /api/parity/runs/{run_id}/accept` records final local acceptance only
  when the service recomputes the run as sign-off ready.

Mutation endpoints reject paths outside user-selected approved roots. The API
does not expose a VoiceStudio start, migration apply, retirement, or deletion
operation.

## Frontend

`/settings/parity` is a lazy-loaded Settings-owned route, not a seventh Voice
workspace and not a top-level navigation item. Settings contains one concise
entry action to open it.

The page contains:

- corpus readiness and selected-root summary;
- migration dry-run totals grouped by importable, relink, unsupported, and
  warning;
- required case matrix with text status labels and expandable measurements;
- failure and blocked reasons with recovery actions;
- run, cancel, refresh, and report-export commands;
- explicit manual acceptance items; and
- a final acceptance command disabled until the backend says the run is ready.

Long result lists are collapsed by case, controls remain keyboard accessible,
and loading/error states are isolated so a failed optional report download
does not take down Settings or the run summary.

## Security And License Boundary

- `vendor/voicestudio` remains immutable and AGPL-boundary isolated.
- Galaxy may use documented file/database shapes as compatibility evidence but
  cannot copy or import VoiceStudio application implementation.
- SQLite is opened read-only, portable archives are protected from ZIP path
  traversal and decompression limits, and source fingerprints are verified.
- Reports redact sensitive keys, user-home paths, consent recordings, and raw
  database payloads.
- The validation runner remains loopback-only and makes no network request.
- Phase 14 deferred capabilities remain disabled and never count as required
  core parity.

## Testing

Domain tests pin catalogue order, required cases, states, threshold behavior,
report determinism, input hash invalidation, cancellation, and acceptance
gating. Migration tests construct fixture SQLite databases and persona bundles
without importing VoiceStudio code, then assert mappings, consent downgrade,
unsafe paths, missing assets, unknown schemas, source immutability, and sandbox
cleanup.

Router tests pin typed OpenAPI contracts, read-only catalogue behavior, path
validation, report formats, and refusal of premature acceptance. Frontend tests
cover route isolation, readiness states, grouped findings, cancellation,
manual answers, keyboard disclosures, and disabled/enabled acceptance states.
The committed production bundle is rebuilt after frontend changes.

Full verification includes backend tests, frontend tests, lint, typecheck,
production build, `compileall`, and `git diff --check`. Tests use deterministic
small fixtures; the large external corpus is a user-run acceptance gate and is
not fabricated in CI.

## Completion And Ticket State

Issue 17 is resolved when Phase 15A's migration policy, fixture-backed dry-run,
consent and relink behavior, unsupported warnings, source immutability, and
sandbox rollback all pass automated verification.

Issue 15 remains open after the framework ships if the required real corpus or
manual acceptance is incomplete. It becomes resolved only when the latest
unchanged run has no required `fail`, `blocked`, or `manual_pending` result and
the user records explicit final acceptance. That accepted report is the only
valid input to Phase 16's VoiceStudio retirement decision.
