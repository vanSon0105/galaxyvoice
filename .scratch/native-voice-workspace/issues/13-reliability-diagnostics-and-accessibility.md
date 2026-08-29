# Reliability, diagnostics, and accessibility

Type: task
Status: resolved
Blocked by: 03, 04, 06, 08, 09, 10, 11

## Question

What shared user-facing reliability contract covers first-run setup, model
recommendations, no-GPU fallback, actionable errors, task logs, cancellation,
crash recovery, disk-space checks, keyboard operation, UI responsiveness, and
large-project performance?

## Done when

Every long-running Voice Workspace operation is observable, stoppable,
recoverable, and usable on the target desktop hardware.

## Answer

Galaxy now applies one reliability contract across the native workspaces:

- persistent task records retain bounded, credential-redacted progress logs,
  checkpoints, valid pause/resume/cancel actions, and a workspace recovery route;
- app restart marks unfinished process-bound tasks interrupted and restores them
  from `/api/tasks`; recovery links retain the owning Galaxy project and exact
  Batch, Dubbing, or Longform workflow checkpoint; reconnecting WebSockets
  reconcile another authoritative snapshot and the client bounds retained
  terminal task state;
- a shared operation audit reports runtime readiness, the device actually
  available inside the isolated engine, CPU fallback, and a device-aware model
  recommendation;
- heavy media and voice domain workflows estimate required output space before
  expensive processing starts, preserve a reserve, and report an actionable
  task or HTTP error from both desktop and CLI entry points;
- audio postproduction now runs as a cancellable background task and terminates
  its owned FFmpeg process when cancellation is requested;
- OmniVoice, Audio Separator, and ProPainter installation are disk-guarded
  tasks with persisted progress, sanitized retained logs, and process-tree
  cancellation instead of untracked detached consoles; model downloads use the
  same disk-headroom contract;
- the title-bar diagnostics panel exposes lightweight CPU/RAM/CUDA/disk state,
  capability preflight, recommendations, and redacted rotating logs on demand;
- chatty progress remains live in the UI while job-store writes are throttled;
  trailing updates, checkpoints, and terminal states are always flushed;
- Dubbing saves an ingest checkpoint before AI translation, so every task has
  a stable project and workflow identity even on its first run;
- keyboard focus, skip navigation, semantic task progress, reduced-motion
  handling, virtualized large editors, and route-level code splitting keep the
  shell operable and responsive on the target desktop.

The contract is implemented in Galaxy-owned reliability and runtime modules;
engine adapters report capabilities without leaking their implementation into
HTTP routers or React pages.
