# Audio postproduction and export contract

Type: task
Status: resolved
Blocked by: 02, 03, 05, 08

## Question

Which reusable Galaxy audio operations cover preview playback, segment gain,
normalization/mastering, vocal/stem use, waveform data, selective export,
metadata, and format support for every Voice Workspace output?

## Done when

Audio operations have one engine-neutral contract and outputs remain traceable
inside the owning Project Bundle.

## Decision

- `AudioPostproductionService` is the engine-neutral boundary shared by Studio,
  Batch, Dubbing, and Longform. TTS and separation engines only provide source
  artifacts; they do not own mastering or export policy.
- An Audio Post Chain covers trim, silence removal, source gain, time-bounded
  segment gain, fades, voice/podcast presets, loudness normalization, sample
  rate, and channel layout.
- An Audio Export can select one or more voice, mix, background, or stem sources
  and write WAV, MP3, FLAC, or M4A with user metadata.
- Every export is immutable under `exports/audio/<export-id>/` and includes an
  `audio_export_manifest.json` that records source hashes, managed/linked path
  ownership, the effective chain, settings, and project-relative output paths.
- The first export binds its artifact directory to one stable project/workspace
  identity; later exports with a conflicting identity are rejected.
- Completed workspace artifacts are discovered lazily when the panel opens, so
  Batch items and Longform stems remain selectable without bloating initial UI.
- Waveform peaks are bounded and cached beneath the owning project. The cache is
  reproducible and is not an authoritative project artifact.
- The shared React postproduction panel is available on completed Studio, Batch,
  Dubbing, and Longform results. Longform's existing mastering action delegates
  to the same domain service.

## Verification

- Domain tests cover bounded waveform caching, multi-source filter construction,
  trace manifests, and invalid project destinations.
- API tests cover waveform success and missing-source validation.
- Frontend tests cover waveform loading and submission of the shared post chain.
