# VoiceStudio parity inventory and acceptance matrix

Type: research
Status: resolved

## Question

What user-facing workflows, data, controls, outputs, and recovery paths exist
in the vendored VoiceStudio snapshot, and where does each belong in the native
Galaxy Voice Workspace?

The answer must produce an explicit matrix for all snapshot surfaces, including
Studio, Batch, profiles/personas, Gallery, transcription, diarization,
Dubbing, Stories, Audiobook, generation history, pronunciation, audio/stems,
exports, model setup, GPU queueing, cancellation/resume, diagnostics,
dictation, local API/MCP, remote backend, and provenance/watermarking. For
each item record: native destination, parity level, dependency, test fixture,
and whether it is core or a deferred extension.

## Done when

The matrix is reviewed by the user and becomes the release gate used by the
final retirement ticket.

## Answer

The primary-source inventory and native acceptance matrix is captured in
[`../research/voicestudio-parity-matrix.md`](../research/voicestudio-parity-matrix.md).

It establishes these binding conclusions:

- Native parity is grouped into six Galaxy workspaces plus shared foundations;
  it is not a copy of VoiceStudio's route or engine catalogue.
- Galaxy already has meaningful foundations, but Studio, Batch, Voice Library,
  Transcripts, Dubbing and Longform all have explicit partial-parity gaps.
- Smart Fit, timing score and second-pass QC are shipped Dubbing parity.
  Wav2Lip visual lip-sync is an upstream roadmap claim and cannot block cutover.
- Community/marketplace is explicitly out; local voice import/export remains
  required.
- Auxiliary shipped capabilities are recorded for explicit disposition rather
  than silently omitted.
- Pronunciation/terminology and legacy-data migration need dedicated tickets
  because they cross several workspace boundaries.

The matrix is now the acceptance input for all downstream tickets and the final
VoiceStudio retirement gate.
