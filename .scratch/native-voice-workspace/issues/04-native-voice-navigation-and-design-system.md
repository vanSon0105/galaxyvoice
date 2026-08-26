# Native Voice Workspace information architecture

Type: prototype
Status: resolved
Blocked by: 01, 02

## Question

How should Galaxy expose the six stable Voice Workspace surfaces — Studio,
Batch, Voice Library, Transcripts, Truyen & Sach noi, and Dubbing — while
keeping Galaxy's top-level video, separation, and subtitle-removal tools clear
and avoiding duplicate VoiceStudio navigation?

## Done when

A navigable prototype defines routes, project switcher, shared actions,
empty/loading/error states, and the removal path for the embedded VoiceStudio
tab.

## Answer

The accepted navigation and state contract is recorded in
[`../research/native-voice-information-architecture.md`](../research/native-voice-information-architecture.md).

The React shell now exposes one top-level Voice workspace with six canonical
`/voice/*` surfaces. Gallery is nested inside Voice Library, all prior
`/omnivoice/*` routes redirect without breaking saved links, and VoiceStudio is
available only as an explicit parity-reference action. A shared local project
switcher supports create/select/refresh and stale-selection recovery. Reusable
loading, empty, and error components plus shared spacing/control tokens define
the visual contract for the feature tickets that follow.
