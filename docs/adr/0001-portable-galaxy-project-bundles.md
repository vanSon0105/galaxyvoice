# ADR 0001: Portable Galaxy Project Bundles

Date: 2026-08-25
Status: Accepted

## Context

Galaxy workflows currently persist editable state in a shared workspace JSON
file while renderers create separate output directories and workflow-specific
manifests. Several manifests contain absolute paths. A project therefore cannot
reliably move between folders or machines, and one workflow cannot safely hand
its output to another without out-of-band path copying.

Media projects also contain very large source files. Copying every imported
video into every project would make project creation slow and waste disk space,
while keeping every input external would make backup and transfer unreliable.

## Decision

Galaxy will use a directory-based, versioned Galaxy Project Bundle as the
ownership boundary for editable workflow state, managed assets, generation
runs, exports, resumable jobs, and metadata backups.

The root `galaxy-project.json` is an index. Independently versioned Workflow
Documents store the detailed state for Batch, Transcripts, Dubbing, and
Longform. Stable UUIDs identify records; filenames and paths do not.

Asset ownership is hybrid:

- Critical small inputs, including subtitles, transcripts, covers, voice
  references, and consent records, are managed by the project.
- Media at or above the default 100 MiB threshold is linked by default.
- Users may override import ownership and may Collect Project to make all
  required assets managed.
- Managed and linked assets carry content fingerprints and provenance.

Working projects remain ordinary directories. Transfer and backup use a
validated ZIP64 `.galaxybundle` archive. Credentials are external Secret
References and are never project data.

A single Active Project is shared by native voice workflows. Voice Library
dependencies are captured as Pinned Voice Snapshots so later library changes do
not alter an existing project without an explicit update.

## Consequences

- Project state can be moved, backed up, inspected, repaired, and migrated
  without VoiceStudio or a machine-specific database.
- Large media is not duplicated unless portability is requested.
- Opening and relinking require fingerprint work, which may continue in the
  background for large files.
- Schema migrations, revision checks, locks, package validation, and garbage
  collection become shared infrastructure that must be implemented before the
  native workflows depend on it.
- Legacy Galaxy output manifests need import adapters. They are not rewritten
  in place.
- A `.galaxybundle` is an exchange artifact, not an editable project format.
