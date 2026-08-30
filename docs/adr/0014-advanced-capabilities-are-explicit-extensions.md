# ADR 0014: Advanced capabilities are explicit extensions

## Status

Accepted

## Context

VoiceStudio exposes auxiliary surfaces beyond Galaxy's six native voice
workspaces. Silently dropping them would make the retirement gate incomplete,
while treating their presence upstream as a requirement would pull remote
access, third-party execution, and separately licensed models into the core
desktop product without the required product, security, or license decisions.

Galaxy therefore needs a durable disposition for each advanced capability. A
disposition records a future boundary and objective revisit conditions; it is
not evidence that the capability itself is installed, implemented, or enabled.

## Decision

Galaxy owns an immutable `AdvancedCapabilityRegistry` and exposes it through a
read-only Settings catalogue and `GET /api/extensions/capabilities`. Every
Phase 14 entry has `default_enabled` set to `false`. Reading the catalogue does
not probe a runtime, load a model, install an adapter, make a network request,
or enable any of the capabilities below.

### Live dictation

- ID and disposition: `dictation.live`, `extension`.
- Boundary: Reuse the Transcript ASR adapter while keeping microphone capture,
  global hotkeys, and auto-paste outside core Transcripts.
- Constraints: Microphone access requires an explicit operating-system
  permission. Global hotkeys and auto-paste must be opt-in and independently
  disabled.
- Revisit triggers: A supported cross-platform capture and hotkey contract is
  available. User demand justifies a dedicated hands-free transcription
  workflow.
- Protected dependency: `asr.faster-whisper`.

### Local transcript refinement

- ID and disposition: `transcripts.local_refinement`, `extension`.
- Boundary: Reuse the shared translation and AI provider contract without
  making refinement a dependency of transcription.
- Constraints: Core transcription must remain usable when refinement is
  unavailable. Source timing and speaker data must survive text refinement.
- Revisit triggers: The local provider contract supports structured transcript
  edits. Quality fixtures show repeatable improvement without timing loss.
- Protected dependency: `translation.ollama`.

### OpenAI-compatible local audio API

- ID and disposition: `api.openai_audio`, `extension`.
- Boundary: Build over Galaxy TTS, ASR, and Voice Library contracts instead of
  accessing engines directly.
- Constraints: The service must bind to loopback by default. Remote exposure
  requires explicit authentication and secret redaction.
- Revisit triggers: Galaxy TTS, ASR, and Voice Library contracts are stable.
  Compatibility fixtures define the supported OpenAI audio surface.
- Protected dependencies: `tts.edge`, `tts.sapi`, `tts.omnivoice`, and
  `asr.faster-whisper`.

### MCP voice bindings

- ID and disposition: `mcp.voice`, `extension`.
- Boundary: Build over the local audio API with no separate creative workspace
  or direct engine access.
- Constraints: MCP calls must inherit Galaxy authentication and secret
  redaction. Bindings cannot bypass API capability or consent checks.
- Revisit triggers: The local audio API has a stable authenticated contract. A
  concrete MCP client workflow has end-to-end acceptance fixtures.

### Remote backend

- ID and disposition: `backend.remote`, `deferred`.
- Boundary: Keep the current desktop service on its loopback boundary.
- Constraints: Remote access needs authentication, TLS, secret storage, and
  revocation. A dedicated remote threat model must precede implementation.
- Revisit triggers: A remote deployment threat model and ownership plan are
  approved. Authentication, TLS, secret storage, and revocation designs are
  accepted.

### Audio watermarking

- ID and disposition: `audio.watermarking`, `optional_adapter`.
- Boundary: Integrate only through a separately licensed provenance adapter.
- Constraints: The implementation requires a fresh compatibility and license
  review. Provenance must record applied, unavailable, and failed outcomes.
- Revisit triggers: A compatible implementation passes license review. A
  provenance format and verification workflow are approved.

### Visual lip-sync

- ID and disposition: `video.visual_lip_sync`, `optional_adapter`.
- Boundary: Keep visual synthesis separate from Galaxy Audio Lip-Sync and
  isolate it behind an optional adapter.
- Constraints: Each model and implementation requires an independent license
  review. GPU and runtime dependencies must be isolated from native Dubbing.
- Revisit triggers: A suitable model passes quality, runtime, and license
  review. Visual synthesis has an isolated GPU scheduling contract.

### Plugin marketplace

- ID and disposition: `marketplace.plugins`, `non_goal`.
- Boundary: Public discovery, publishing, payments, and third-party code
  execution remain outside the local-first desktop product.
- Constraints: Marketplace execution is not a protected Galaxy extension
  boundary. Local Voice Library import and export remain separate capabilities.
- Revisit trigger: Only a new product decision can change this explicit
  non-goal.

## Consequences

- The catalogue, API representation, and Settings presentation are implemented;
  the eight described capability behaviors and adapters are not implemented or
  enabled by Phase 14.
- Extension entries preserve named Galaxy contracts for future work without
  granting direct engine access or adding creative-workspace tabs.
- Deferred and optional-adapter entries do not block VoiceStudio retirement
  once the required native parity gate passes, but their stated reviews and
  triggers must precede implementation.
- Remote service exposure remains disabled and loopback-only.
- No watermarking or visual lip-sync implementation may be registered before
  the required compatibility, runtime, quality, and license reviews.
- The plugin marketplace has no protected extension seam and remains an
  explicit product non-goal unless a new product decision supersedes this ADR.
- No VoiceStudio application code is copied, imported, patched, or executed by
  this disposition mechanism.
