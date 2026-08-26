# Transcripts, alignment, and speaker workflow

Type: task
Status: resolved
Blocked by: 02, 03, 04

## Question

What transcript project lifecycle supports import, ASR, language detection,
word/cue timestamps, editable text, SRT/VTT/text export, speaker diarization,
speaker extraction where supported, and handoff to Dubbing or Longform?

## Done when

Transcript records preserve source timing and edits, expose model/device
provenance, and remain responsive for long media.

## Answer

Galaxy now owns a project-scoped transcript document with optimistic revision
locking. It accepts SRT, VTT, plain text, audio, and video; media imports run as
background `faster-whisper` jobs and retain cue timing, word timing,
confidence, detected language, model, and resolved device provenance.

The native editor provides media preview, a timing overview, virtualized cue
rows, local undo/redo, split/merge/reorder/delete operations, speaker editing,
and one atomic save per editing session. This keeps the HTTP router thin and
avoids one server revision per keystroke.

Speaker diarization is an optional `pyannote.audio` capability using the local
Hugging Face token. Missing runtime, access, or token degrades to manual speaker
assignment without losing the transcript. Successful diarization can extract a
short local speaker reference; saving it to Voice Library still requires an
explicit consent confirmation.

Exports preserve speaker labels in SRT, VTT, and TXT. Recorded handoffs carry a
versioned payload into Dubbing or Truyện & Sách nói, and both destination pages
hydrate their native editor from that payload. The list endpoint returns
summary records only, while the cue editor renders a buffered viewport; tests
cover a 1,000-cue document.

## Verification

- `python -m unittest tests.server.test_transcripts`
- `npm test -- --run src/pages/voice/TranscriptsPage.test.tsx`
- `npm run typecheck`
- `npm run lint`
