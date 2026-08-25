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

### Artifact Provenance

The trace from a generated file back to its Generation Run, input asset
identities, workflow state, and effective engine configuration. Secret values
and unsanitized provider responses are excluded.

### Active Project

The single Galaxy Project Bundle currently shared by the application's voice
workflows. Cross-workflow handoffs create references inside this bundle rather
than unrelated output directories.

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

### Voice Workspace

The Galaxy-owned group of workflows for Studio, Batch, Voice Library,
Transcripts, Longform, and Dubbing. It is implemented independently of the
vendored VoiceStudio service.

### Audio Lip-Sync

Fitting synthesized speech to a source speech interval using accurate timing,
bounded rate adjustment that preserves pitch, and quality checks. It does not
mean altering a face or mouth in video frames.
