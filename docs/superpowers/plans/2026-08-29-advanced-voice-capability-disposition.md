# Advanced Voice Capability Disposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every advanced VoiceStudio capability an explicit, testable Galaxy disposition and protected extension boundary.

**Architecture:** A Galaxy-owned immutable registry is the single source of truth. A thin FastAPI router serializes it, while Settings renders the read-only catalogue without enabling deferred engines.

**Tech Stack:** Python dataclasses, FastAPI/Pydantic, React, TanStack Query, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-advanced-voice-capability-disposition-design.md`

## Global Constraints

- Do not import, patch, or copy `vendor/voicestudio` application code.
- Every Phase 14 capability is disabled by default.
- The catalogue endpoint is read-only and performs no heavy runtime probe.
- Remote exposure, third-party code execution, and unreviewed model adapters remain unavailable.
- Commit `frontend/dist/` after frontend changes.

---

### Task 1: Typed disposition registry

**Files:**
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/extensions/__init__.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/extensions/capabilities.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/extensions/test_capabilities.py`

**Interfaces:**
- Produces: `DispositionKind`, `AdvancedCapabilityDisposition`, `AdvancedCapabilityRegistry`, and `advanced_capability_registry`.
- Consumes: capability IDs from `app.runtime.defaults.capability_registry` only as string references; no runtime probing.

- [ ] Write tests for the exact eight identifiers, stable order, duplicate rejection, disabled defaults, allowed disposition values, and extension capability references.
- [ ] Run `python -m pytest -q tests/extensions/test_capabilities.py` and confirm the tests fail before implementation.
- [ ] Implement immutable descriptors and the default registry.
- [ ] Run `python -m pytest -q tests/extensions/test_capabilities.py` and confirm all tests pass.

### Task 2: Read-only API

**Files:**
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/server/routers/extensions.py`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/app/server/main.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/server/test_extensions.py`

**Interfaces:**
- Consumes: `advanced_capability_registry.list_capabilities()`.
- Produces: `GET /api/extensions/capabilities` returning `{ capabilities: [...] }`.

- [ ] Write a router test asserting the exact response shape and eight entries.
- [ ] Run `python -m pytest -q tests/server/test_extensions.py` and confirm it fails before implementation.
- [ ] Add the thin router and register it before the SPA mount.
- [ ] Run `python -m pytest -q tests/server/test_extensions.py` and confirm it passes.

### Task 3: Settings catalogue

**Files:**
- Create: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/api/extensions.ts`
- Create: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/components/ExtensionCapabilitiesPanel.tsx`
- Create: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/components/ExtensionCapabilitiesPanel.test.tsx`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/SettingsPage.tsx`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/index.css`
- Rebuild: `tools/galaxy_ai_voice_subtitle_studio/frontend/dist/`

**Interfaces:**
- Consumes: `GET /api/extensions/capabilities`.
- Produces: accessible read-only `Tính năng mở rộng` Settings section.

- [ ] Write component tests for loading, error, all disposition labels, and keyboard-accessible detail disclosure.
- [ ] Run the component test and confirm it fails before implementation.
- [ ] Implement the API client, focused panel, Settings integration, and restrained styles.
- [ ] Run component tests, lint, typecheck, and production build.

### Task 4: Decision records and final verification

**Files:**
- Create: `docs/adr/0014-advanced-capabilities-are-explicit-extensions.md`
- Modify: `.scratch/native-voice-workspace/issues/14-advanced-voice-capability-disposition.md`
- Modify: `.scratch/native-voice-workspace/research/voicestudio-parity-matrix.md`
- Modify: `.scratch/native-voice-workspace/map.md`
- Modify: `CONTEXT.md`

**Interfaces:**
- Consumes: the implemented registry and accepted Phase 14 design.
- Produces: the binding retirement-gate disposition record.

- [ ] Record the exact dispositions, constraints, and revisit triggers in ADR 0014.
- [ ] Mark ticket 14 resolved and update the map/parity matrix without claiming deferred engines are implemented.
- [ ] Add canonical glossary terms for disposition and extension capability.
- [ ] Run full backend tests, frontend tests, lint, typecheck, build, `compileall`, and `git diff --check`.
- [ ] Commit the complete Phase 14 change with message `feat: define advanced voice capability dispositions`.

