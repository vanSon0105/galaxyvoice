# Galaxy Editor Core Rebuild Design

## Purpose

Galaxy will keep the current video editor available while replacing its state
and playback foundations behind stable module interfaces. The rebuild uses the
OpenCut rewrite and changelog as architectural references, not as a source drop
or a second application embedded inside Galaxy.

The OpenCut snapshot in this repository is an early rewrite. Its web editor is
a placeholder and its desktop application only renders shell panels. The
historical changelog describes useful behavior, but the referenced compositor,
ripple, time, and WASM implementations are not present in the snapshot.

## Non-goals

- Do not replace React, FastAPI, pywebview, or Galaxy's FFmpeg runtime.
- Do not modify or depend on the ignored OpenCut reference folder.
- Do not rewrite OCR, subtitle removal, TTS, or export in the foundation phase.
- Do not remove the current editor before the replacement reaches parity.
- Do not maintain two independent project models after migration completes.

## Core Interfaces

### Editor project

`EditorProject` is the Video Editor Workflow Document inside the Active
Project's Galaxy Project Bundle. It is the single persisted source of truth
for editing and owns:

- a versioned schema, stable workflow identity, and monotonic revision;
- the owning Galaxy Project Bundle identity;
- rational frame rate and integer media time;
- deduplicated asset references with managed/linked ownership, mandatory
  content fingerprints, path hints, and provenance (generated files are
  managed assets with generated provenance);
- one permanent main video track;
- ordered visual overlays, where the first track is topmost;
- ordered audio lanes;
- media clips, subtitle cues, trim ranges, and reversible replacements.

Visual ordering is explicit. Overlay tracks always render above the main video
track, and their array order is the z-order shown in the timeline.

### Editor commands

Every user edit crosses one command interface. A transaction may contain
several commands but creates one history entry. This makes actions such as
"drop media and create a lane" undo in one step.

Commands validate the complete resulting project before committing it. Failed
transactions leave the active project unchanged. Locked tracks reject content
edits at the command seam rather than relying on disabled buttons alone.

### Media time

Timeline time is an integer count at 120,000 ticks per second. Frame rates are
rational numerator/denominator values. Milliseconds remain only at legacy HTTP
and UI adapters until those contracts are migrated.

### Adapters

The existing timeline can be converted to and from the new project model. The
bottom visual video lane becomes the main track; video lanes above it remain
overlays. Subtitle and audio identity, trim ranges, and non-destructive cleanup
references survive conversion.

Legacy media must be resolved to bundle asset UUIDs and content fingerprints
before migration. Preview URLs remain runtime-only locators. Subtitle-removal
manifests are referenced by bundle artifact UUID and resolved back to a path
only at the legacy boundary. A visual lane below the main video cannot be
represented by the new model, so the adapter rejects that input rather than
silently changing its z-order.

The adapter is temporary and must be deleted after the current page, preview,
and export all consume `EditorProject` directly.

## Delivery Phases

### Phase 1: Foundation

- Add `MediaTime`, rational frame rates, frame snapping, and legacy conversion.
- Add versioned `EditorProject` schema and persistence validation.
- Add atomic commands, bounded history, undo, and redo.
- Add a loss-aware adapter for the current timeline model.

Acceptance:

1. NTSC frame rates map to exact rational values.
2. A multi-command transaction undoes and redoes as one action.
3. Invalid or locked-track edits cannot partially mutate a project or its
   history through shared caller references.
4. Legacy visual z-order, audio lane order, cue timing, clip trims, and cleanup
   replacement metadata survive migration. Global interleaving of visual and
   audio track rows is intentionally normalized because it has no render
   meaning in the new project model.

### Phase 2: Editor state integration

- Replace `EditorPage` track `useState` calls with one editor session module.
- Route add, delete, split, move, trim, lock, and visibility through commands.
- Add undo/redo buttons and keyboard shortcuts.
- Coalesce an entire pointer gesture into one history transaction.
- Keep the existing timeline visuals and export request adapter.

### Phase 3: Timeline interaction engine

- Separate timeline geometry, selection, gestures, snapping, and ripple logic.
- Support cross-track moves, multi-selection, box selection, and track reorder.
- Compute collision limits before trim or move commits.
- Virtualize clips, ruler ticks, waveform samples, and thumbnails to the visible
  time range.

### Phase 4: Project persistence

- Store the editor Workflow Document through the Galaxy Project Bundle
  repository with atomic save and schema migration.
- Add debounced autosave, explicit save, recovery, and recent projects.
- Persist source identity without copying or modifying source media.
- Detect missing or changed source files and support relinking.

### Phase 5: Playback scheduler

- Replace `video timeupdate -> React state` as the master clock.
- Use one monotonic scheduler for video and audio activation.
- Recover from seek and timing slips without restarting unrelated media.
- Continue through clip boundaries and timeline gaps.
- Keep high-frequency playback state outside React render state.

### Phase 6: Preview compositor

- Render all active visual layers in project z-order.
- Add canvas transforms, crop, opacity, background, and subtitle layout.
- Expose direct manipulation through the same command interface.
- Define preview quality levels and proxy fallback for unsupported codecs.

### Phase 7: Media cache

- Generate thumbnails, RMS waveforms, and edit proxies in background tasks.
- Key artifacts by source fingerprint and settings.
- Read only the visible waveform/thumbnail window during timeline rendering.
- Apply bounded disk retention outside the repository.

### Phase 8: Shared render plan

- Compile `EditorProject` into one deterministic render plan.
- Make preview and FFmpeg export consume the same ordering and timing semantics.
- Preserve cancellation, progress, hardware encoders, and output validation.
- Add fixed project fixtures that compare preview state with exported frames.

### Phase 9: Feature migration and retirement

- Reattach subtitle editing, TTS, OCR, and subtitle removal through commands.
- Migrate existing editor projects through the versioned repository.
- Complete manual desktop QA at short, long, fractional-FPS, and multilayer
  fixtures.
- Remove the legacy track model and adapter only after parity is demonstrated.

## Ownership Rules

- `frontend/src/editor/core/` owns project semantics, time, commands, history,
  validation, and serialization. It cannot import React or HTTP modules.
- `frontend/src/editor/adapters/` owns temporary and external representations.
- Timeline and preview modules read projections and emit commands; they do not
  own project truth.
- FastAPI routers translate HTTP only. Persistence and render planning belong
  to domain modules.
- FFmpeg remains the authoritative export adapter, not the project model.
