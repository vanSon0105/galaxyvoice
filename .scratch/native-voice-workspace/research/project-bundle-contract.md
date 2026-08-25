# Galaxy Project Bundle Contract v1

Status: Accepted design contract
Date: 2026-08-25
ADR: `docs/adr/0001-portable-galaxy-project-bundles.md`

## Purpose

This contract defines the storage boundary shared by native Galaxy Batch,
Transcripts, Dubbing, and Longform workflows. It replaces the current split
between editable workspace records in a shared JSON file and unrelated render
output directories.

The contract is independent of VoiceStudio. VoiceStudio migration is specified
separately by ticket 17.

## Invariants

1. A working project is a directory whose root contains
   `galaxy-project.json`.
2. The Project Manifest is an index; detailed editable state belongs to
   independently versioned Workflow Documents.
3. Record identity uses lowercase UUIDs. A filename, display name, or path is
   never an identity.
4. Paths inside a bundle are relative POSIX paths. They must not contain `..`,
   drive letters, URI schemes, NUL bytes, or resolve outside the bundle.
5. Every persisted timestamp is RFC 3339 UTC with a trailing `Z`.
6. Every mutable document has a monotonically increasing `revision`.
7. API keys, tokens, cookies, authorization headers, and raw provider responses
   are forbidden from all project files.
8. Generated artifacts are immutable. A new execution creates a new
   Generation Run and never silently overwrites an earlier run or export.
9. Unknown newer schema versions open read-only. Galaxy never guesses a
   downgrade or destructively rewrites newer data.
10. A failed save, migration, import, or package extraction leaves the last
    valid project state intact.

## Directory layout

```text
project-name/
|-- galaxy-project.json
|-- assets/
|   `-- <asset-id>/
|       `-- <safe-original-name>
|-- workflows/
|   |-- batch/<workflow-id>.json
|   |-- transcripts/<workflow-id>.json
|   |-- dubbing/<workflow-id>.json
|   |-- longform/<workflow-id>.json
|   `-- voices/<voice-snapshot-id>.json
|-- generated/
|   `-- <workflow-id>/<run-id>/
|       |-- run.json
|       `-- <artifacts>
|-- exports/
|   `-- <export-id>/
|       |-- export.json
|       `-- <exported-files>
|-- jobs/
|   `-- <job-id>.json
|-- backups/
|   `-- <timestamp>-r<revision>/
|       |-- galaxy-project.json
|       `-- workflows/...
|-- cache/
`-- .galaxy-project.lock
```

`cache/` and `.galaxy-project.lock` are never packaged. A compact package also
omits reproducible intermediate artifacts. A full package includes managed
source assets and retained outputs, but sanitizes resumable jobs into a paused,
process-independent form.

## Project Manifest v1

`galaxy-project.json` uses UTF-8 JSON and contains these required top-level
fields:

| Field | Contract |
| --- | --- |
| `schema_version` | Integer `1`. |
| `project_id` | Stable lowercase UUID. |
| `revision` | Positive integer incremented by every successful save. |
| `name` | User-visible project name; not an identity. |
| `created_at`, `updated_at` | RFC 3339 UTC timestamps. |
| `created_by` | Galaxy application and version that created the project. |
| `paths` | Canonical relative roots for each bundle area. |
| `assets` | Asset index records. |
| `voice_snapshots` | Pinned Voice Snapshot index records. |
| `workflows` | Workflow Document index records. |
| `runs` | Lightweight Generation Run index records. |
| `exports` | User-created export index records. |
| `jobs` | Resumable job index records. |
| `secret_references` | Credential source names only; never values. |

Indexes contain identity, type, state, relative document path, revision where
applicable, and timestamps. Detailed segments, scripts, diagnostics, and
settings stay out of the root manifest.

### Asset record

An asset record contains:

- `asset_id`: stable UUID.
- `kind`: `video`, `audio`, `subtitle`, `transcript`, `image`, `document`, or
  `other`.
- `role`: workflow-independent role such as `source_video`, `reference_voice`,
  `cover`, or `glossary`.
- `ownership`: `managed` or `linked`.
- `state`: `available`, `missing`, or `modified`.
- `bundle_path`: required only for managed assets.
- `relative_hint` and `absolute_hint`: local lookup hints for linked assets.
- `fingerprint`: algorithm, digest, size, and modified-time hint.
- `provenance`: import source, original filename, import time, and replacement
  history.

`absolute_hint` is local metadata and is removed from `.galaxybundle` archives.
The canonical identity digest is a full SHA-256. Hashing may run in the
background, but automatic relink requires a completed digest match. Size and
modified time may shortlist candidates but never prove identity.

### Asset ownership policy

- Subtitle, transcript, cover, voice-reference, and consent inputs are managed
  by default.
- Other files smaller than 100 MiB are managed by default.
- Video and audio files at or above 100 MiB are linked by default.
- Import UI always permits an explicit ownership override.
- Generated files and exports are always managed.
- Collect Project copies every required linked asset into `assets/<asset-id>/`,
  verifies its SHA-256, atomically changes ownership, and preserves origin
  provenance.

### Workflow index record

A workflow index records `workflow_id`, `type`, `name`, `schema_version`,
`revision`, `status`, `document_path`, and timestamps. Valid v1 types are
`batch`, `transcript`, `dubbing`, and `longform`.

## Workflow Document envelope

Every Workflow Document has this common envelope:

```json
{
  "schema_version": 1,
  "workflow_id": "uuid",
  "type": "batch",
  "revision": 1,
  "name": "Display name",
  "status": "draft",
  "created_at": "2026-08-25T08:00:00Z",
  "updated_at": "2026-08-25T08:00:00Z",
  "inputs": [],
  "voice_snapshot_ids": [],
  "settings": {},
  "content": {},
  "handoffs": []
}
```

`inputs` reference Asset IDs or upstream Workflow IDs, never bare paths.
`handoffs` record explicit cross-workflow lineage. Workflow-specific content is
demonstrated by the accepted fixtures.

## Pinned Voice Snapshots

Assigning a Voice Profile to an Active Project creates a Pinned Voice Snapshot
under `workflows/voices/`. Its index and document record:

- stable snapshot and source profile IDs;
- snapshot revision and source profile revision;
- display metadata and consent statement;
- engine adapter, model ID, model revision, language, and capabilities;
- managed reference Asset IDs where required;
- effective synthesis defaults;
- creation/update timestamps.

Project workflows render against the snapshot revision. A newer library profile
is reported as available but never applied automatically. Updating a snapshot
creates a new revision and does not invalidate prior Generation Runs.

System voices that cannot be packaged declare an external dependency with a
preflight capability check. Models and runtimes are identified but not copied
into the project. Credentials use Secret References.

## Generation Runs, jobs, and exports

### Generation Run

Each run owns `generated/<workflow-id>/<run-id>/run.json`. It records:

- `run_id`, `workflow_id`, and the source workflow revision;
- job identity and terminal status;
- input Asset IDs and fingerprints;
- Pinned Voice Snapshot IDs and revisions;
- engine/provider/model identifiers and versions;
- effective settings and a stable input/settings digest;
- start/end timestamps, sanitized warnings, and sanitized diagnostics;
- artifact records containing IDs, roles, media metadata, and bundle paths.

The digest may be used to offer reuse, but reuse is explicit in provenance.

### Job

A job checkpoint records stable IDs, workflow/run association, resumability,
progress, completed unit IDs, sanitized error state, and engine-independent
resume data. PID, process handles, temporary absolute paths, and credentials
are runtime state and are not portable.

### Export

An export is a user-requested presentation of one or more artifacts. It has a
stable Export ID and records source artifact IDs, format settings, output
fingerprints, and creation time. A conflicting display filename creates a new
revision or asks for an explicit replacement; it never overwrites silently.

Deleting a workflow does not delete referenced runs or exports. Garbage
collection is a separate previewable operation and may remove only unreferenced
generated files or cache data.

## Save, locking, and recovery

1. Editable changes autosave after approximately one second of inactivity.
2. The client saves with its expected revision. A stale expected revision is a
   conflict and cannot overwrite newer state.
3. JSON writes use a same-directory temporary file, flush, and atomic replace.
4. One process owns `.galaxy-project.lock`; additional processes open read-only.
5. A lock contains project ID, process ID, host instance ID, and heartbeat time.
   A dead process or expired heartbeat may be explicitly reclaimed.
6. Schema migrations and significant edits create metadata-only Recovery
   Snapshots. The newest ten are retained.
7. Recovery selects the highest internally consistent manifest/workflow
   revision and never substitutes media content.

## Migration policy

The Project Manifest and each Workflow Document have independent integer schema
versions. Migrations are registered one version at a time and run against a
staged copy:

1. Validate the current document.
2. Create a Recovery Snapshot.
3. Copy affected metadata into a staging directory.
4. Apply every registered `n -> n+1` migration in order.
5. Validate references, paths, IDs, revisions, and target schemas.
6. Atomically replace live metadata only after all checks pass.

Failure leaves the original project untouched. A newer unsupported schema opens
read-only. Automatic downgrade and implicit merge are forbidden.

Existing Galaxy workflow manifests are imported through explicit legacy
adapters into a new Project Bundle. Original output folders are not mutated.
VoiceStudio data follows the separate migration policy in ticket 17.

## Open, verify, and relink

Opening a project validates schema, containment, index/document consistency,
and required asset state. Asset lookup order is:

1. managed `bundle_path`;
2. valid bundle-relative hint;
3. last absolute hint on the same machine;
4. user-selected search roots.

An exact SHA-256 match may relink automatically. Directory relink may resolve
many candidates, but ambiguous matches require selection. A file whose path is
unchanged but digest differs becomes `modified` and is never consumed silently.

For a modified asset, the user may accept it as a replacement while appending
provenance history, add it as a new Asset ID, or keep the dependency unresolved.
Only dependent renders are blocked; unrelated project data remains editable and
old outputs remain available.

## Packaging and import

`.galaxybundle` is a ZIP64 exchange format with `galaxy-project.json` at the
archive root.

- **Full** includes all required managed sources and retained outputs.
- **Compact** includes editable state, required source/reference assets, and
  selected final outputs while omitting cache and reproducible intermediates.

Before packaging, Galaxy shows a Package Report listing included source media,
transcripts, scripts, voice samples, consent records, outputs, and omissions.
Linked requirements must be collected or explicitly reported as unresolved.

Import extracts to a staging directory, rejects absolute/traversal paths,
symlinks and special files, enforces configured size/count limits, validates
schemas and hashes, and only then installs the project. A duplicate Project ID
imports as a copy with a new Project ID by default. Explicit replacement first
creates a Recovery Snapshot. V1 does not merge projects.

## Privacy rules

- Secret values are rejected recursively using a denylist and credential-value
  detection before save and package.
- Secret References may name environment variables such as
  `GALAXY_DEEPSEEK_API_KEY`.
- Absolute paths, usernames, host IDs, live locks, process IDs, and unsanitized
  logs are removed from archives.
- Project text, transcripts, prompts, voice samples, and consent records are
  project data and appear in the Package Report.
- Galaxy does not upload bundle content except when the user starts a workflow
  whose selected provider requires that content.
- Provider/model/version and request timing may be retained; authorization and
  raw responses are not.

## Active Project behaviour

All native voice tabs share one Active Project. Creating, opening, viewing
recent projects, and closing are application-level actions. If a task starts
without an Active Project, Galaxy creates one in the configured Projects root
and identifies it before execution.

Cross-workflow operations create internal references and handoff provenance.
Legacy per-tab Output Folder controls become export destinations; they no longer
own editable project state.

## Acceptance fixtures

The sibling `project-bundle-fixtures/` directory is normative for v1 field
shape and cross-document references:

- `galaxy-project.json`
- `workflows/voices/voice-snapshot.json`
- `workflows/batch/batch.json`
- `workflows/transcripts/transcript.json`
- `workflows/dubbing/dubbing.json`
- `workflows/longform/longform.json`

All fixture JSON must parse, all referenced IDs must exist, all internal paths
must be relative and contained, and no fixture may contain a credential value.
