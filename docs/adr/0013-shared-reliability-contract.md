# ADR 0013: Shared reliability contract

## Status

Accepted

## Context

Native voice and media workspaces launch long-running local AI and FFmpeg
operations on hardware ranging from CPU-only laptops to CUDA desktops. Separate
loading indicators and runtime checks left failures hard to diagnose, task
state disappeared after restart, and output jobs could fail late when disk
space ran out.

## Decision

Galaxy owns one reliability domain above engine adapters. An Operation Audit
combines capability preflight, the device visible inside the isolated runtime,
CPU fallback, model recommendation, and output disk headroom. Heavy domain
workflows run the shared disk guard before creating output artifacts, so CLI
and HTTP callers share the same protection.

Background tasks persist bounded redacted logs, checkpoints, valid cooperative
controls, and a Recovery Route. Progress events remain live while persistence
is throttled to avoid rewriting the complete job store for every log line;
trailing progress, checkpoints, and terminal transitions still flush. Process-bound tasks become interrupted after a
restart because their Python thread and subprocess cannot survive; the owning
Batch, Dubbing, or Longform repository resumes from its durable checkpoint. Recovery
links carry both the Galaxy project and workflow identifiers. The web shell
bootstraps this state over HTTP, reconciles after every WebSocket reconnect,
and bounds retained terminal tasks. Rotating
application logs and the same audits are exposed through an on-demand
diagnostics panel.

The React shell provides semantic progress, keyboard focus and skip navigation,
reduced-motion support, virtualized large editors, and route-level code
splitting. Runtime probes remain lazy so diagnostics do not delay startup.

## Consequences

- Long operations remain observable and actionable across app restarts.
- API keys and authorization values are excluded from persisted task data,
  live task events, and retained installer or diagnostic logs.
- A requested GPU is rejected when the engine's own runtime cannot use it,
  even if the host reports compatible hardware.
- Disk estimates reserve headroom and may conservatively stop an operation
  before execution; users can select another output drive and retry.
- New long-running workflows must report progress, expose cancellation, declare
  recovery behavior, and use the shared output-space guard.
- Runtime installers are managed tasks with captured, sanitized diagnostic
  output instead of detached consoles, so installation failures and
  cancellation follow the same contract as generation workflows.
