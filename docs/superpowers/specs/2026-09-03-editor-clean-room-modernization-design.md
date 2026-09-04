# Editor Clean-room Modernization Design

## Purpose

Galaxy will absorb the useful editing workflows observed in ezmaxsub without
decrypting protected assets, bypassing licensing, importing proprietary
modules, or copying implementation code. Public UI behavior and HTTP contract
shapes may be used as product references; every Galaxy implementation remains
independent and uses Galaxy-owned domain services.

## Product Direction

The video editor becomes the single workspace for media assembly, subtitle
speech, timing repair, and hard-subtitle removal. Existing standalone tools
remain available while parity is being built so behavior can be compared and
recovery remains possible. Navigation is simplified only after validation.

All generated media is non-destructive. Source files are never overwritten.
Processed outputs enter the editor media bin first and are placed or used to
replace clips only through an explicit editor action.

## Delivery Phases

### Phase 1: Subtitle removal inside Editor

- Add a `Hard subtitle removal` inspector mode to the video editor.
- Use the currently selected video clip as the source.
- Reuse Galaxy's existing removal API and task registry.
- Support strip, blur, and locally installed AI modes, including region
  selection, processing device, preview, and license gating.
- Add a completed clean video to the editor media bin without changing the
  selected clip or source file.
- Keep the standalone removal route as a compatibility view.

### Phase 2: Editor-native speech jobs

- Introduce an editor speech request that preserves cue and track identity.
- Deliver completed cue audio incrementally through task events.
- Insert each completed item into the first non-overlapping audio lane.
- Preserve cancellation, retry, and the existing generic Batch workflow.

### Phase 3: Throughput and warmup

- Add bounded concurrency for independent Edge and SAPI work, defaulting to
  three workers and clamped to one through eight.
- Prewarm selected engines before large jobs.
- Throttle persistence and progress snapshots rather than rewriting the full
  batch after every cue.
- Keep single-worker execution for engines that are not concurrency-safe.

### Phase 4: Short-cue planning and cache

- Plan adjacent short cues into bounded clusters using character count, cue
  count, time span, and join-gap limits.
- Render shared-context clusters, split output back to cue identities, and
  fall back to individual rendering when alignment cannot be proven.
- Cache deterministic renders by normalized text, voice revision, engine, and
  synthesis settings.

### Phase 5: Timing fit

- Compute speech-to-cue fit before placement.
- Report overflow and safe speed suggestions.
- Offer optional meaning-preserving condensation through the configured AI
  provider, always showing the proposed text before it replaces a cue.
- Never silently truncate speech or subtitle text.

### Phase 6: Advanced hard-subtitle cleanup

- Add named region presets, multiple masks, and per-range activation.
- Add before/after frame comparison and explicit quality warnings.
- Allow a clean result to replace a selected clip while retaining a reversible
  project reference to the original media.

### Phase 7: Burned-subtitle OCR and retirement

#### Phase 7A: Fast local OCR

- Add editor-native burned-subtitle recognition for the selected video clip.
- Run RapidOCR in an isolated local runtime; do not add OCR dependencies to the
  desktop shell process.
- Limit work to a user-selected region and use a two-pass selective pipeline:
  group visually stable probes first, OCR representative frames, vote across
  each temporal run, then rescue weak runs before cue assembly.
- Cache completed results by source fingerprint and OCR settings.
- Write both editable SRT and a Galaxy-owned manifest containing cue timing,
  confidence, and recognized text bounds.
- Add completed SRT to the editor media bin without placing it on the timeline.

#### Phase 7B: OCR review and timeline handoff

- Provide an OCR review surface for low-confidence text and timing boundaries.
- Let the user explicitly place accepted SRT on a selected subtitle lane.
- Preserve the original OCR manifest so edits remain distinguishable from raw
  recognition output.

#### Phase 7C: OCR-guided cleanup

- Convert OCR text bounds and cue timing into a bounded set of editable dynamic
  cleanup masks in the same editor inspector.
- Reuse the Phase 6 non-destructive replacement and restore workflow.
- Keep manual masks available for missed text and non-text overlays.

#### Phase 7D: Parity and retirement

- Validate editor OCR/removal workflows against fixed fixtures and manual
  visual checks.
- Delete the standalone `Xoa phu de` frontend page and navigation entry; keep a
  compatibility redirect from `/removal` to `/editor`.
- Retain the backend removal engine because the integrated editor uses it.

## Boundaries

- Do not execute untrusted ezmaxsub binaries for analysis.
- Do not decrypt `.sealed` assets or defeat license/integrity checks.
- Do not copy Cython, bundled JavaScript, model data, or visual assets.
- Do not modify the immutable VoiceStudio vendor snapshot.
- Keep HTTP routers thin and place new workflow behavior in domain services.

## Phase 1 Acceptance

1. Selecting a video clip and opening the removal tool shows that clip as the
   source.
2. Starting removal sends the selected source path, current output directory,
   configured mode, region, strength, device, and license state.
3. A completed result is loaded through the editor media API and appears in the
   media bin.
4. The existing timeline clip still references its original media.
5. No video selection produces a clear disabled state.
6. Existing standalone removal behavior and tests remain intact.

## Phase 2 Acceptance

1. Editor speech requests carry a client job ID plus each cue's item, track,
   cue, and timeline-start identity.
2. The backend emits one item event as soon as each cue succeeds or fails,
   while the task result retains all item outcomes for reconnect recovery.
3. Successful audio enters the media bin immediately and is placed after its
   source subtitle track in the first lane where it does not overlap.
4. Duplicate item and terminal events cannot insert the same audio twice.
5. Task cancellation remains cooperative for system voices and interrupts the
   shared OmniVoice worker through its coordinator.
6. The public Batch create, resume, and retry workflow remains unchanged.

## Phase 3 Acceptance

1. Edge and SAPI jobs use three workers by default and clamp requested worker
   counts to the supported range of one through eight.
2. Engines that do not declare parallel safety, including OmniVoice, continue
   to run with one worker.
3. Jobs with at least three pending items prewarm the selected engine once
   before synthesis begins.
4. Batch manifests, checkpoints, and task progress are persisted at a bounded
   interval, with a forced write for terminal and cancellation states.
5. Batch retry semantics, editor cue identity, incremental item events, and
   deterministic result ordering remain unchanged.

## Phase 4 Acceptance

1. Adjacent short cues are clustered only while character count, cue count,
   time span, join gap, track, and language boundaries remain valid.
2. A clustered render keeps shared text context but returns one WAV and the
   original editor identity for every source cue.
3. Cluster output is split only when the expected silence boundaries can be
   proven; missing or ambiguous boundaries fall back to individual renders.
4. Reusable WAV renders are cached outside the repository by normalized text,
   voice revision, engine, model, voice selection, and synthesis settings.
5. Cache hits are materialized inside the current editor job, and changing the
   voice revision or synthesis context invalidates the prior entry.
6. Phase 4 does not alter subtitle text, fit audio to cue duration, or introduce
   the Phase 5 shortening and timing-fit behavior.

## Phase 5 Acceptance

1. Every generated editor WAV is measured against its source cue before the
   completed item event is emitted and before frontend placement begins.
2. The result reports cue duration, audio duration, actual overflow, fit status,
   and a bounded speed suggestion only when the required speed is considered
   safe.
3. Audio that cannot fit within the safe speed bound is reported without being
   clipped, truncated, stretched, or silently moved.
4. Condensation uses the AI provider, model, base URL, and environment-backed
   API key already configured for Galaxy.
5. AI output is presented beside the unchanged source cue as a proposal; only
   an explicit Apply action replaces the cue text.
6. A stale proposal cannot replace a cue whose source text changed while the AI
   request was running, and applying a proposal requires generating audio again
   for a new fit measurement.

## Phase 6 Acceptance

1. A cleanup job accepts up to twelve named masks, each with its own frame
   region and optional activation range.
2. Built-in region presets can populate the active mask without removing the
   ability to adjust its coordinates manually.
3. Blur, smart-fill, and AI cleanup honor every mask and activation range; AI
   chunk processing evaluates ranges against the original video timeline.
4. The editor shows explicit quality warnings before processing and the
   backend-recorded warnings after completion.
5. The editor can compare matching source and cleaned frames at the same
   timestamp.
6. A completed clean result enters the media bin first and replaces only the
   explicitly selected matching clip after a separate user action.
7. Replacing a clip retains its original media reference and cleanup manifest,
   and the editor can restore that original clip without rerunning cleanup.

## Phase 7A Acceptance

1. OCR always uses the selected timeline video clip and a region fully bounded
   by that video's frame.
2. Fast mode samples at 2 fps and accurate mode at 4 fps; neither decodes an
   image for OCR more often than its configured sample rate.
3. Visually stable sampled frames reuse the prior OCR observation and report
   sampled, inferred, and reused frame counts.
4. Repeated or near-identical observations become one cue, while blank frames,
   changed text, and large time gaps close the active cue.
5. The result includes editable SRT plus a manifest with cue confidence and
   source-frame text bounds.
6. Running the same source fingerprint, mode, language, and region again uses
   Galaxy's local cache.
7. A completed SRT enters the editor media bin and is not placed on a subtitle
   lane until the user explicitly asks for it.

## Phase 7C Acceptance

1. OCR and hard-subtitle cleanup share one editor inspector and always operate
   on the selected timeline video clip.
2. OCR bounds are padded, converted from pixels to frame percentages, and
   combined with cue timing to create no more than twelve editable masks.
3. Long OCR results are partitioned into ordered time batches rather than
   dropping cues beyond the mask limit.
4. Manual mask editing remains available after OCR planning.
5. Recognition still preserves editable SRT in the media bin, while cleanup
   remains non-destructive until the user explicitly replaces the selected
   clip.
6. The standalone removal page and navigation item no longer exist, and old
   `/removal` links redirect to the editor.
