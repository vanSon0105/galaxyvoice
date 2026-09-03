# Native Dubbing media and URL ingest

Type: task
Status: ready-for-agent
Blocked by: 03, 08, 09, 12

## Question

How should native Galaxy Dubbing start from local video/audio or a remote media
URL instead of requiring a pasted SRT, while preserving the VoiceStudio license
boundary and Galaxy's persistent task contract?

## Required workflow

- Provide one first-stage drop zone and native picker for MP4, MOV, MKV, WEBM,
  MP3, WAV, FLAC, and M4A without copying a large local file through JavaScript.
- Accept a YouTube/video URL through an optional Galaxy-owned `yt-dlp` adapter.
  URL work runs in the persistent task registry with progress, cancellation,
  bounded single-item downloads, managed output, and redacted diagnostics.
- Optionally retrieve source captions and YouTube auto-translations. Preserve all
  retrieved caption artifacts and select a deterministic source track for the
  editable Transcript/Dubbing handoff.
- If no usable caption exists, offer the existing native Transcript ASR flow and
  return its revisioned handoff to Dubbing.
- Accept an optional Netscape cookie file for restricted YouTube media. Pass it
  to only the active downloader process; never persist the path/content in a
  project, task checkpoint, history item, or log.
- Validate local formats and remote URLs, reject credential-bearing/private
  network URLs, expose adapter availability, and explain installation failures.
- Implement Galaxy-owned React, service, API, and tests independently. Do not
  copy, patch, or import the immutable AGPL VoiceStudio snapshot.

## Acceptance

Local ingest is core parity. URL/caption/cookie ingest is optional at runtime
when `yt-dlp` is unavailable, but the UI and capability state remain explicit.
Large local media is represented by a native path, not uploaded into browser
memory. The resulting source media and transcript can be checkpointed, reopened,
translated, cast, rendered, and included in the project graph.

## Deferred implementation note

A test-first draft established the intended seams (`DubbingIngestService`, thin
workspace routes, managed `yt-dlp` subprocess, and a native drop event carrying
`pywebviewFullPath`) but was deliberately removed from the worktree when the
multi-track editor/TTS request became the active priority. Recreate it from this
contract rather than reviving partial unreviewed code.
