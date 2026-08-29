# Galaxy AI Studio Context

## Terms

### Galaxy Project Bundle

A self-contained project directory that owns its versioned manifest, editable
workflow data, and produced outputs. Source media may be linked rather than
copied, but the manifest records a portable relative path whenever possible.

### Managed Asset

An input or generated file owned by a Galaxy Project Bundle and stored inside
that bundle. Moving the bundle preserves the asset without relinking.

### Linked Asset

An input file that remains outside a Galaxy Project Bundle. The bundle records
its location, identity fingerprint, and provenance so Galaxy can detect a
missing or changed file and guide the user through relinking it.

### Collect Project

The operation that copies linked assets into a Galaxy Project Bundle and
rewrites their references as managed assets, making the project portable for
backup or transfer to another machine.

### Project Manifest

The versioned root index of a Galaxy Project Bundle. It identifies the project
and references its assets, workflow documents, generated artifacts, exports,
and resumable jobs without embedding all workflow state in one large file.

### Workflow Document

The independently versioned, editable state owned by one workflow inside a
Galaxy Project Bundle, such as Batch, Transcripts, Dubbing, or Longform.

### Asset Identity

A stable asset ID plus a content fingerprint that survives file and folder
renames. Paths are locations of an asset, not its identity.

### Relink

The recovery operation that reconnects a missing Linked Asset to a candidate
file after validating its identity. Galaxy prefers bundle-relative locations
and uses the last absolute location only as a fallback hint.

### Project Revision

A monotonically increasing edit number used to prevent stale project state
from overwriting a newer save.

### Project Lock

A short-lived ownership record that permits one Galaxy process to modify a
project while additional processes open it read-only. A stale lock left by a
terminated process may be explicitly reclaimed.

### Recovery Snapshot

A metadata-only backup created before schema migration or a significant edit.
It excludes large source and generated media that already exist elsewhere in
the bundle.

### Schema Migration

A registered, one-version-at-a-time transformation of a Project Manifest or
Workflow Document. It runs against staged data after a Recovery Snapshot and
replaces live metadata only after validation succeeds.

### Asset State

The verified availability of an asset: available, missing, or modified. A
modified Linked Asset requires an explicit replacement decision before a
dependent workflow can render, while unrelated project data remains usable.

### Galaxy Bundle Archive

A validated ZIP64 archive with the `.galaxybundle` extension, created from a
working Project Bundle for backup or transfer. It may be full or compact, but
it is not edited in place.

### Secret Reference

The name of an external credential source required by a workflow, such as an
environment variable. Project data may store the reference name but never the
credential value.

### Package Report

The pre-export inventory of source media, generated files, transcripts, voice
samples, consent records, and omitted private machine metadata that will make
up a Galaxy Bundle Archive.

### Generation Run

An immutable record of one workflow execution, identified by a stable run ID
and linked to its inputs, effective settings, engine versions, status,
diagnostics, and produced artifacts.

### Studio Take

An immutable successful output of a single-script Generation Run created by
Studio. It records the engine-neutral request, generation run identity,
effective engine identity, output artifacts, project association, rerun
lineage, and warnings without storing credentials. Failed and cancelled runs
remain runtime jobs and do not become takes. Deleting a Studio Take removes its
history record, not its files.

### Primary Studio Take

The project annotation that selects one Studio Take as the preferred audio for
an Active Project. The mutable reference is stored outside the immutable take.
Selecting a new Primary Studio Take atomically replaces the previous selection
for that project. Other takes remain available for comparison and reruns.

### Batch Run

A persistent ordered execution of multiple synthesis items under one Active
Project and one shared default voice configuration. A Batch Run records item
attempts and outcomes independently, can preserve partial success, and may be
continued without regenerating completed items. Its portable manifest contains
relative artifact references; machine-local resume data lives in a separate
sidecar.

### Batch Item

One synthesis request inside a Batch Run. It inherits language, voice, speed,
duration, and formats from the run unless it declares an override. Its state is
`pending`, `running`, `done`, or `failed`; retry increments its attempt count
without changing successful sibling items.

### Artifact Provenance

The trace from a generated file back to its Generation Run, input asset
identities, workflow state, and effective engine configuration. Secret values
and unsanitized provider responses are excluded.

### Active Project

The single Galaxy Project Bundle currently shared by the application's voice
workflows. Cross-workflow handoffs create references inside this bundle rather
than unrelated output directories.

### Project Graph Node

The Active Project index entry owned by one workflow document or completed task.
It records the workspace route, owner ID, revision, artifact references, and
sanitized metadata. The node is a provenance index, not a second copy of the
workflow's editable state.

### Workspace Handoff

A reversible transfer of selected artifact references from one Project Graph
Node to a supported destination workspace. Its lifecycle is `pending`,
`opened`, then `returned`, and it retains the source revision and both routes.

### Return Record

The immutable completion data on a Workspace Handoff: destination node and
produced artifact IDs. Returning never deletes or replaces the source assets,
and a completed handoff cannot be reopened as a new transfer.

### Pinned Voice Snapshot

A project-owned, revisioned copy of the voice definition, consent metadata,
engine identity, and required reference material used by a workflow. Library
changes do not alter the snapshot until the user explicitly updates it.

### Voice Library

The local-first catalogue of voices usable by Galaxy workflows. A voice may be
a system voice, an imported voice, a cloned profile, or a designed profile.
It is not a public marketplace or community gallery.

### Voice Profile

A reusable local voice definition with its consent record, engine capability,
reference material where needed, tags, and preview/history metadata.

### Voice Consent Record

The ownership or permission assertion attached to a cloned voice, including
its basis, statement, timestamp, and reference provenance. Galaxy refuses to
save a new cloned profile without explicit confirmation.

### Galaxy Voice Bundle

A versioned `.galaxyvoice` transfer archive containing one Voice Profile,
consent metadata, and optional reference or prompt assets. It is a Galaxy
format and is not an alias for a third-party persona format.

### Voice Workspace

The Galaxy-owned group of workflows for Studio, Batch, Voice Library,
Transcripts, Longform, and Dubbing. It is implemented independently of the
vendored VoiceStudio service.

### Audio Lip-Sync

Fitting synthesized speech to a source speech interval using accurate timing,
bounded rate adjustment that preserves pitch, and quality checks. It does not
mean altering a face or mouth in video frames.

### Audio Post Chain

The engine-neutral ordered settings applied after synthesis or separation:
source and segment gain, trim, silence removal, fades, tonal preset, loudness
normalization, sample rate, and channel layout. Workspaces submit the contract;
the source engine does not define export behavior.

### Audio Export

An immutable Project Bundle artifact produced from selected voice, mix,
background, or stem sources through an Audio Post Chain. Its manifest records
source hashes and ownership, effective settings, metadata, formats, and
project-relative outputs without credentials.

### Waveform Cache

A bounded set of display peaks derived from an audio artifact and cached under
the owning project. It is keyed by source identity and requested resolution,
may be deleted safely, and is never the authoritative audio source.

### Operation Audit

A user-requested readiness check for one runtime capability, model, device, and
output destination. It reports the device the isolated runtime can actually
use, any CPU fallback, a model recommendation, required remediation, and disk
headroom without starting the operation.

### Task Diagnostic

The persistent, credential-redacted operational record for a background task:
status, bounded progress log, checkpoint, valid control actions, and recovery
route. It is diagnostic state, not the authoritative workflow document or a
place to store API keys.

### Recovery Route

The native workspace URL and user-facing instruction attached to a task so an
interrupted or failed operation can return to the owning workflow after an app
restart. A route provides navigation; workflow checkpoints decide whether work
can resume or must be rerun.
