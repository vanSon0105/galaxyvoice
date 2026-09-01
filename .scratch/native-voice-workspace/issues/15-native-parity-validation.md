# Native parity validation against VoiceStudio

Type: task
Status: ready-for-human
Blocked by: 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 17, 18

## Question

How will Galaxy compare native workflows against the approved parity matrix
while VoiceStudio is still available, including golden media fixtures,
performance thresholds, output validation, migration rehearsal, and user
acceptance tests?

## Done when

The parity report identifies no unmet core workflow and the user accepts the
native replacement as ready for the retirement gate.

## Automated implementation state

The Galaxy-owned Phase 15 framework is implemented: the fixed catalogue,
corpus readiness inspection, read-only migration rehearsal, deterministic
validators and reports, persistent task recovery, manual evidence recording,
and backend-guarded acceptance workflow are available. This closes automated
implementation only. It is not evidence that native parity has been accepted.

After interruption, reopen Settings and select `Mở đối chiếu parity`, or
navigate directly to `/settings/parity`, to return to the persistent run.

## Human evidence still required

- [ ] Select the approved external real corpus for every required case and
  preserve its manifest checksums; do not commit the selected media.
- [ ] Supply the matched VoiceStudio reference artifacts and reference
  measurements while VoiceStudio remains available for comparison.
- [ ] Run the native validation against that unchanged corpus and resolve every
  required `fail` or `blocked` result. Wall time, peak RAM, and peak VRAM stay
  intentionally `blocked` wherever matched reference evidence is unavailable.
- [ ] Complete every required manual UAT item with a positive answer and note,
  including output quality, usability, recovery, and comparison observations.
- [ ] Review the deterministic JSON and Markdown reports and record explicit
  final acceptance on the same unchanged run.

Only the canonical JSON report from that explicitly accepted run is an
Accepted Parity Report and may enter Phase 16. Until then this ticket remains
`ready-for-human`, VoiceStudio remains available, and native parity acceptance
must not be claimed.

Context: [Native Voice Workspace decisions](../map.md#decisions-so-far) and
[ADR 0015](../../../docs/adr/0015-native-parity-validation-is-evidence-gated.md).
