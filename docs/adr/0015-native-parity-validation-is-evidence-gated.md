# ADR 0015: Native parity validation is evidence-gated

## Status

Accepted

## Context

Galaxy now has an automated Phase 15 validation framework: a versioned parity
catalogue, external-corpus readiness checks, read-only migration rehearsal,
validators, persistent reports, manual evidence controls, and a Settings-owned
acceptance workflow. Automated framework completion proves that Galaxy can
collect and guard evidence. It does not prove that the native workspaces have
passed the approved real corpus or that a user has accepted their behavior.

The retirement decision must also remain independent of the implementation
that produces the evidence. A passing unit or integration suite, a partial
parity run, or a report whose inputs changed after execution cannot substitute
for the approved comparison and manual review.

## Decision

Native parity acceptance is evidence-gated.

- Automated Phase 15 implementation and verification are not native parity
  acceptance.
- A parity run is eligible for acceptance only when its catalogue, corpus
  manifest, source and reference fingerprints, thresholds, and recorded
  evidence remain unchanged; every required automated check passes; every
  required manual item has a positive answer and note; and the user records
  explicit final acceptance.
- A required `fail`, `blocked`, or `manual_pending` result prevents acceptance.
  In particular, performance metrics without matched VoiceStudio reference
  evidence remain `blocked`; they are never interpreted as zero or as a pass.
- The canonical JSON report from an explicitly accepted run is an Accepted
  Parity Report. Accepted Parity Reports are the sole valid Phase 16 input for
  deciding whether to retire the embedded VoiceStudio reference.
- VoiceStudio remains installed and available for comparison until an
  Accepted Parity Report exists and the Phase 16 retirement decision is
  explicitly approved. Phase 15 does not retire, remove, patch, or import
  VoiceStudio.

Issue 17 may be resolved from the implemented read-only migration policy and
fixture-backed dry-run evidence. That resolution does not mean a production
migration command exists and does not satisfy issue 15.

Issue 15 remains `ready-for-human` until the approved external corpus is run,
all required manual UAT is completed, and the user explicitly accepts the
unchanged run. No report, selected corpus media, or copied VoiceStudio database
is committed to the repository as proof of that local gate.

After an interruption or application restart, reopen Settings and use the
`Mở đối chiếu parity` command, or navigate directly to `/settings/parity`.
The persistent task record and report identify the interrupted run; the
acceptance service still decides whether that run can continue or be accepted.

## Consequences

- CI and repository verification can close automated implementation work while
  honestly leaving product acceptance open.
- Phase 16 must reject screenshots, verbal approval, test-suite results, and
  unaccepted or changed reports as retirement evidence.
- Missing real-corpus assets, manual observations, or matched reference
  measurements remain visible non-success states with recovery actions.
- VoiceStudio's separate loopback service remains the comparison boundary; no
  Galaxy-owned module imports or modifies its AGPL application source.
- Issue 17 remains resolved, issue 15 remains open for human evidence, and no
  native parity or retirement claim is made by this decision record.
