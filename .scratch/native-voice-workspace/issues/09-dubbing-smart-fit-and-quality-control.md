# Dubbing Smart Fit and quality control

Type: task
Status: resolved
Blocked by: 03, 07, 08

## Question

How should Galaxy implement the full dub pipeline: ingest, transcript,
translation, per-speaker voice mapping, segment synthesis, bounded
pitch-preserving duration fit, gap/overrun scoring, second-pass QC, source
audio/stem mixing, preview, SRT, and final video mux?

## Done when

The Dubbing contract includes editable checkpointed stages, paste-in external
translations, reliable cancellation/resume, and repeatable quality reports.

## Answer

Galaxy now owns a revisioned Dubbing Project with source and translated SRT,
speaker/profile casting, editable segment timing and text, source media,
render options, deterministic QC, and the latest render result. External SRT
can be pasted without an AI call; AI translation uses the existing provider
contract and a deterministic cue checkpoint. Translation cue IDs must match
the source so a partial or shifted translation cannot silently mix languages.

The renderer preserves the source timeline, synthesizes and checkpoints each
segment, then applies bounded FFmpeg `atempo` fitting before an exact pad/trim.
Its second-pass report records raw, tempo-adjusted, fitted, clipped, and padded
duration per segment. Preflight and post-render reports share a stable digest
and score invalid timing, overlap, tight gaps, unmapped voices, reading
pressure, underruns, and overruns. Expressive text remains opaque so issue 18
can add parsing without changing this project contract.

The export service supports voice replacement, regular source/stem mixing, or
sidechain ducking, then muxes the original video stream, dubbed AAC audio, and
a selectable SRT subtitle track. FFmpeg and synthesis run through cooperative
task cancellation; interrupted segment renders resume from the workspace job,
and interrupted translations resume when rerun from their cue checkpoint.

The native React workspace provides seven visible stages, optimistic project
revision handling, transcript handoff, speaker-wide casting, virtualized
segment rows, timing edits, split/merge, QC controls, Smart Fit bounds,
mix/export settings, per-segment previews, final audio/video preview, and
secure reopening of previously rendered project media.

## Verification

- `python -m unittest discover -s tests` (409 tests)
- `npm run test -- --run` (54 tests)
- `npm run typecheck`
- `npm run lint`
- `npm run build`
