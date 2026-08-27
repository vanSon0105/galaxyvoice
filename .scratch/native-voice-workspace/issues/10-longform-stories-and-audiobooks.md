# Longform Stories and Audiobooks

Type: task
Status: resolved
Blocked by: 02, 06, 07, 18

## Question

How should one native long-form project model serve story dialogue and
chaptered audiobooks: text/EPUB/PDF import, chapters, cast, narrator,
per-line expression/pause controls, previews, crash-resume rendering,
mastering, cover metadata, and M4B/MP3/WAV exports?

## Done when

Stories and Audiobooks share one project model and renderer while retaining the
different authoring views they need.

## Answer

Stories and Audiobooks now use one revisioned Longform Project and one editable
document model. Plain text, Markdown, EPUB, and PDF imports become chaptered
items with cast/profile selection, per-line spoken text, speed, volume, pause,
emotion, emphasis, spelling, and project pronunciation rules. Large plans use a
virtualized editor and can be saved, reopened, deleted, or resumed after an
interrupted render.

The shared renderer uses the canonical expressive compiler for line preview
and final output, checkpoints each speech span, preserves display text in SRT,
and can export WAV, tagged MP3, chaptered M4B, stems, and a manifest. Optional
mastering uses bounded FFmpeg loudness normalization; MP3/M4B exports carry
title, author, and cover metadata. Preview artifacts live in the local runtime
cache and never replace a project's final result.

HTTP routes delegate Longform construction, persistence, preview selection,
and result attachment to the native Longform service. No VoiceStudio source is
copied or imported across the AGPL boundary.

## Verification

- `python -m pytest -q` (426 tests, 60 subtests)
- `npm run test -- --run` (55 tests)
- `npm run typecheck`
- `npm run lint`
- `npm run build`
