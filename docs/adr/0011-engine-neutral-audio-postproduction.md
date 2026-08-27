# ADR 0011: Engine-neutral audio postproduction

## Status

Accepted

## Context

Studio, Batch, Dubbing, and Longform each produced playable audio, but preview,
gain, mastering, stem selection, metadata, and format conversion were either
duplicated or absent. Keeping those operations inside individual TTS engines
would make output behavior inconsistent and prevent reliable project tracing.

## Decision

Galaxy owns one `AudioPostproductionService` outside every synthesis and
separation adapter. Workspaces describe selected audio sources and an Audio Post
Chain, then receive immutable exports inside their owning project directory.
Each export includes a manifest with source hashes, path ownership, settings,
metadata, and relative output paths. The artifact directory is bound to its
stable project/workspace identity on first export. Waveform display data is
bounded, streamed in chunks, cached by content hash, and reproducible.

The contract supports WAV, MP3, FLAC, and M4A. The UI uses one shared panel on
completed Studio, Batch, Dubbing, and Longform results. Existing Longform
mastering delegates to the shared service.

## Consequences

- A new engine only needs to produce an audio artifact; it inherits Galaxy's
  preview and export workflow without implementing it again.
- Linked stems remain external inputs but are fingerprinted in the manifest.
- Export history is portable with the owning Project Bundle.
- Waveform caches can be rebuilt and excluded from transfer archives.
- Future mastering improvements can change behind the service without changing
  workspace APIs.
