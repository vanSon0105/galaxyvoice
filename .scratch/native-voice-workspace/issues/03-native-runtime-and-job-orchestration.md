# Native runtime, model, and job orchestration

Type: research
Status: resolved
Blocked by: 01

## Question

What Galaxy-owned capability registry and job runner are needed for model
installation, device selection, GPU serialization, progress, cancellation,
resume, crash recovery, and engine preflight across TTS, ASR, diarization,
translation, and audio processing?

## Done when

A minimal common contract is chosen without coupling Galaxy workflows to
VoiceStudio's runtime or database.

## Answer

Galaxy now owns a lazy capability registry, replaceable model adapters, a fair
named-resource scheduler, and a persistent cooperative job runner. The common
state machine supports queueing, progress, cancellation, live pause/resume,
sanitized checkpoints, restart recovery, and registered resume handlers without
depending on VoiceStudio internals.

The server exposes runtime discovery, preflight, model management, resource
inspection, and job-control endpoints. Existing service routers use the same
runner through a compatibility facade, and accelerator-heavy routes now serialize
their GPU use. The frontend recognizes queued, paused, and interrupted states.

The accepted contract and extension rules are documented in
[`runtime-job-contract.md`](../research/runtime-job-contract.md). The implementation
lives under `app/runtime/` and is covered by runtime, server, domain, and frontend
tests.
