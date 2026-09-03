# Multi-track editor and subtitle-to-voice workflow

Type: task
Status: ready-for-human
Blocked by: 02, 05, 07, 12

## Question

How should Galaxy's video editor support multiple ordered subtitle, video, and
audio tracks plus generation of editable audio clips from selected subtitle
cues or all cues?

## Current delivery

- Add tracks from a single `+` menu with Subtitle, Video, and Audio choices.
- Permit multiple tracks of every kind, with explicit vertical order and
  independent visibility/mute/lock controls.
- Generate speech from one selected subtitle cue or all cues using a compatible
  Voice Library profile, including cloned/imported profiles.
- Put generated speech on audio tracks at subtitle timing. Overlapping or
  overlong generated clips must occupy additional audio lanes instead of
  silently overwriting existing clips, so the user can move, split, trim, or
  delete them manually.
- Keep preview and export ordering deterministic.

## Implemented

- Dynamic Subtitle, Video, and Audio tracks with independent visibility/mute
  and lock controls.
- Positioned media clips with drag, edge trim, split-at-playhead, and delete.
- Selected cue, current subtitle track, or all subtitle tracks can be rendered
  through a compatible Voice Library voice.
- Generated speech is placed at cue timing and packed onto extra audio lanes
  when clips overlap.
- Multi-track video composition and audio mixing are included in export while
  the previous single-source export contract remains supported.

## Deferred Smart Fit

AI-assisted subtitle shortening is a later stage. It must propose shorter text
that preserves meaning, keep the original text and timing as recoverable source
data, preview the resulting voice duration, and require explicit user approval
before replacing a cue. It must not be coupled to the first multi-track schema
migration.
