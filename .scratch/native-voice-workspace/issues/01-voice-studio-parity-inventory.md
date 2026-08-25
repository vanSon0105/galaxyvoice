# VoiceStudio parity inventory and acceptance matrix

Type: research
Status: claimed

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
