# Native Voice Workspace information architecture

Status: Accepted prototype contract
Date: 2026-08-26

## Purpose

Galaxy exposes voice work as one top-level workspace rather than presenting an
engine name or the embedded VoiceStudio application as peer products. The
workspace owns six stable surfaces. Engine selection and the VoiceStudio
comparison build remain implementation details behind those workflows.

## Route contract

| Surface | Canonical route | Owns |
| --- | --- | --- |
| Studio | `/voice` | Single-script generation, clone/design entry and takes |
| Batch | `/voice/batch` | Multi-item generation and queue operations |
| Voice Library | `/voice/library` | Saved local voices and designed-voice gallery |
| Transcripts | `/voice/transcripts` | Searchable transcripts and future ASR editor |
| Truyen & Sach noi | `/voice/longform` | Story and audiobook authoring |
| Dubbing | `/voice/dubbing` | Timed segments, voice assignment and dub rendering |

Gallery is a view inside Voice Library at `/voice/library/gallery`; it is not a
seventh workspace. VoiceStudio is available only through the explicit
`/voice/reference` comparison action while parity work is in progress.

Every previous `/omnivoice/*` browser route redirects to its canonical native
route. API routes and engine identifiers keep their existing names until their
own adapter migrations; navigation names do not imply a breaking backend
rename.

## Project switcher

The Voice header owns one active project selection shared by all six surfaces.
It lists local workspace projects by most-recent update, remembers the selected
ID on the current machine, recovers from a stale or deleted ID, and permits a
small project record to be created in the current surface.

During the transition, this control uses the existing local workspace project
repository. It does not write a fake `galaxy-project.json`. Project Bundle
adoption later replaces the repository adapter without changing the header or
its context contract.

## Shared actions and states

- `Tao du an` creates and selects a local project record.
- `Lam moi` refreshes the project list without reloading the workspace.
- `Ban doi chieu` opens the isolated VoiceStudio reference surface.
- Loading uses a compact spinner and keeps the surrounding layout stable.
- Empty states explain what is absent and name the next meaningful action.
- Error states use an alert role, a short remedy and an explicit retry action.
- Destructive actions remain local to the owning surface and require
  confirmation; they do not belong in the shared header.

These states are implemented as reusable Galaxy-owned components so later
Studio, Batch, Transcript and Dubbing tickets do not invent page-specific
variants.

## VoiceStudio removal path

1. Phase 4 removes VoiceStudio and OmniVoice as top-level/navigation peers.
2. The reference build remains reachable only through `Ban doi chieu` and its
   immutable loopback HTTP boundary.
3. Parity tickets use that reference for behavioural comparison; no native
   module imports or copies its application source.
4. Final cutover removes the comparison action and redirects only after the
   parity matrix passes and the user explicitly approves retirement.
5. Runtime/data cleanup is a separate migration decision; hiding navigation
   never silently deletes installed files or user data.

## Visual system

The workspace extends the existing dark Galaxy palette with named spacing,
control-height and radius tokens. Navigation is dense, horizontal and
scan-friendly. One accent line indicates selection; accent fill is reserved for
primary actions. Project controls remain in the workspace header rather than a
decorative card, and content surfaces keep the existing compact panel system.
