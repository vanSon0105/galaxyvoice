# Advanced VoiceStudio capability disposition

Type: research
Status: resolved
Blocked by: 01, 03

## Question

For each auxiliary VoiceStudio capability — live dictation, local
OpenAI-compatible API, MCP bindings, remote backend, watermarking, visual
lip-sync, and plugin marketplace — should Galaxy provide a native feature,
an extension point, or an explicit non-goal, and what license/security/runtime
conditions apply?

## Done when

No upstream capability is silently lost: each has a recorded disposition and,
when deferred, a protected extension seam and revisit trigger.

## Answer

ADR 0014 and the Galaxy-owned advanced capability registry record eight final
dispositions:

- live dictation, local transcript refinement, the OpenAI-compatible local
  audio API, and MCP voice bindings are extensions over named Galaxy contracts;
- the remote backend is deferred pending an approved threat model, ownership,
  authentication, TLS, secret-storage, and revocation design;
- audio watermarking and visual lip-sync are optional adapters that require
  separate compatibility, runtime, quality, and license review before any
  implementation is registered; and
- the plugin marketplace is an explicit non-goal that only a new product
  decision can reopen.

Phase 14 implements the immutable disposition registry, read-only API, and
Settings catalogue. It does not implement or enable dictation, transcript
refinement, the compatible audio API, MCP bindings, remote access,
watermarking, visual lip-sync, or a plugin marketplace. Every catalogue entry
is disabled by default, and reading the catalogue performs no runtime probe,
installation, model load, or network request.

The exact boundaries, constraints, protected dependencies, and objective
revisit triggers are binding in
`docs/adr/0014-advanced-capabilities-are-explicit-extensions.md`.

## Context

[The native workspace map](../map.md#decisions-so-far) records these explicit
dispositions as retirement-gate context without promoting deferred or optional
capabilities into implemented parity.

## Verification

- `python -m pytest -q` (485 tests and 60 subtests passed)
- `npm test` (23 files and 74 tests passed)
- `npm run lint`
- `npm run typecheck`
- `npm run build` (126 modules transformed)
- `python -m compileall -q app tests`
- `git diff --check`
