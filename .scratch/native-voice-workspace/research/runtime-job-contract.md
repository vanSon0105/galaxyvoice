# Native Runtime, Model, and Job Contract

## Boundary

Galaxy owns the orchestration contract. Engines remain replaceable adapters and
must not expose their database, process model, or application source through a
workflow. VoiceStudio is not imported by this layer.

The shared foundation is split into four modules:

- `CapabilityRegistry` describes an engine and routes explicit preflight checks.
- `ModelRegistry` lists, installs, and later removes models through engine adapters.
- `ResourceScheduler` grants named, capacity-limited resources fairly.
- `TaskRegistry` owns durable job state, cooperative control, progress, and checkpoints.

HTTP routers remain thin callers of these modules. A CLI or future worker can use
the same interfaces without FastAPI.

## Capability Contract

A capability has a stable namespaced ID, kind, human label, runtime ID, supported
devices, default device, installability, and resumability. Preflight is explicit
and lazy: listing capabilities must not import Torch, load a model, probe a GPU,
or access the network.

Preflight returns a structured result rather than raising through the API:

- `ready`: the requested operation can start.
- `unavailable`: a known dependency or credential is missing.
- `error`: the adapter probe failed unexpectedly.

The initial registry covers Edge TTS, Windows SAPI, OmniVoice, faster-whisper,
Pyannote diarization, every configured translation provider, audio-separator,
ProPainter, and FFmpeg.

## Model Contract

Models are addressed by `(capability_id, model_id)`. Catalog entries report
installation state, version, source, size when known, and license identifier when
known. Installation runs as a normal job so cancellation, progress, and resource
limits apply. The first production adapter exposes the audio-separator catalog;
other engines can register adapters without changing workflow code.

Models and credentials are machine dependencies. They are never packed into a
Galaxy Project Bundle by the orchestration layer.

## Job State Machine

States are:

`queued -> running <-> paused -> done | failed | cancelled`

If the process exits while work is active, the next start maps resumable work to
`paused` and other work to `interrupted`. A recovered paused job can resume only
when its job kind has registered a resume handler. Live pause is cooperative;
workflows call `wait_if_paused()` at safe boundaries.

Every job may carry capability, project, workflow, and run IDs plus named resource
keys. Results stay in memory for immediate API delivery. Durable metadata stores
only status, timestamps, progress, messages, resource claims, and a sanitized
checkpoint. API keys, tokens, passwords, authorization values, and callbacks are
not serialized.

The desktop server enables the atomic JSON store at startup. Importing modules or
running tests does not touch the user's persisted job state.

## Resource Policy

Named resources have capacities. The initial shared capacities are one
`accelerator` slot and two `network` slots. Waiters are FIFO only against jobs
that request an overlapping resource, so independent CPU and network work can
continue concurrently. Cancellation removes a waiter immediately.

Current Whisper, OmniVoice, audio-separation, AI subtitle removal, NVENC export,
and long-form render routes declare accelerator usage. `auto` is treated
conservatively as accelerator work until an adapter resolves the final device.

## API Surface

- `GET /api/runtime/capabilities`
- `POST /api/runtime/preflight`
- `GET /api/runtime/resources`
- `GET /api/runtime/models`
- `POST /api/runtime/models/install`
- `GET /api/tasks` and `GET /api/tasks/{id}`
- `POST /api/tasks/{id}/pause|resume|cancel`

WebSocket task events include `queued`, `running`, `paused`, `done`, `failed`,
`cancelled`, and `interrupted`. Existing router calls keep working through the
`server.tasks` compatibility facade.
