# Advanced Voice Capability Disposition Design

## Purpose

Phase 14 records an explicit Galaxy-owned disposition for every auxiliary
VoiceStudio capability that is outside the six native voice workspaces. The
result prevents deferred work from disappearing during the native cutover
without importing, modifying, or executing VoiceStudio application code.

## Decision

Galaxy will expose a read-only typed catalogue of advanced capabilities. Each
entry records its product disposition, implementation boundary, constraints,
and objective revisit triggers. The catalogue is visible in Settings and over
a local HTTP endpoint, but it does not install or enable deferred engines.

The dispositions are:

| Capability | Disposition | Boundary |
| --- | --- | --- |
| Live dictation | Extension | Reuse the Transcript ASR adapter; microphone capture, global hotkey, and auto-paste remain outside core Transcripts. |
| Local transcript refinement | Extension | Reuse the shared translation/AI provider contract; transcription must remain usable without it. |
| OpenAI-compatible local audio API | Extension | Build over stabilized Galaxy TTS, ASR, and Voice Library contracts; bind to loopback by default and require explicit authentication before remote exposure. |
| MCP voice bindings | Extension | Build over the local audio API; no separate creative workspace or direct engine access. |
| Remote backend | Deferred | Requires a separate threat model, authentication, TLS, secret-storage, and revocation design. |
| Audio watermarking | Optional adapter | Requires a compatible licensed implementation; provenance must state whether marking was applied, unavailable, or failed. |
| Visual lip-sync | Optional adapter | Separate from Galaxy Audio Lip-Sync; requires independent model/license review and GPU/runtime isolation. |
| Plugin marketplace | Non-goal | Public discovery, publishing, payments, and third-party code execution are outside the local-first desktop product. |

## Domain Model

`AdvancedCapabilityDisposition` is immutable and contains:

- stable `capability_id` and localized-ready `label`;
- `category` and one of `extension`, `deferred`, `optional_adapter`, or
  `non_goal`;
- `summary`, `boundary`, `constraints`, and `revisit_triggers`;
- optional `extension_capability_ids` naming existing Galaxy runtime
  capabilities that the future implementation must consume;
- `default_enabled`, which is false for every Phase 14 entry.

`AdvancedCapabilityRegistry` rejects duplicate identifiers, returns entries in
stable order, and provides lookup by identifier. The default catalogue is
created in Galaxy-owned code and has no VoiceStudio imports.

## HTTP And UI

`GET /api/extensions/capabilities` returns the complete catalogue as JSON. It
is read-only and performs no runtime probe, installation, network request, or
model load.

Settings gains a `Tính năng mở rộng` section. It presents a compact disposition
summary and expandable detail for boundaries, constraints, and revisit
triggers. Status uses text as well as colour, remains keyboard accessible, and
does not imply that deferred capabilities can be enabled from this screen.

## Security And Licensing

- Remote access remains disabled; the current desktop service keeps its
  loopback boundary.
- Future remote or MCP work cannot bypass Galaxy authentication and secret
  redaction contracts.
- Watermark and visual lip-sync adapters require a fresh license review before
  an implementation is registered.
- Marketplace execution is not a protected extension seam because it is an
  explicit product non-goal.
- No code or data is copied from `vendor/voicestudio`.

## Verification

Domain tests assert the exact capability set, dispositions, disabled defaults,
stable ordering, duplicate rejection, and valid extension references. Router
tests assert the read-only response and SPA/API separation. Frontend tests
assert every disposition is visible, details can be opened with the keyboard,
and loading/error states remain explicit.
