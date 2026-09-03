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

### Phase 7: Parity and retirement

- Validate editor/removal workflows against fixed fixtures and manual visual
  checks.
- Hide the standalone `Xoa phu de` navigation entry only after parity passes.
- Retain its route and backend for one compatibility cycle before considering
  deletion.

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
