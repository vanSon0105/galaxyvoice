# Dubbing Smart Fit and quality control

Type: task
Status: open
Blocked by: 03, 07, 08

## Question

How should Galaxy implement the full dub pipeline: ingest, transcript,
translation, per-speaker voice mapping, segment synthesis, bounded
pitch-preserving duration fit, gap/overrun scoring, second-pass QC, source
audio/stem mixing, preview, SRT, and final video mux?

## Done when

The Dubbing contract includes editable checkpointed stages, paste-in external
translations, reliable cancellation/resume, and repeatable quality reports.
