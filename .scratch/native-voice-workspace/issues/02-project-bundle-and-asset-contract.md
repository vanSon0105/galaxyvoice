# Project Bundle and asset contract

Type: grilling
Status: resolved
Blocked by: 01

## Question

What versioned manifest, asset references, provenance, output layout, backup,
move/relink, and import/export rules let every Galaxy voice workflow reopen a
project independently of VoiceStudio and another machine's data directory?

## Done when

The manifest schema, migration policy, conflict/relink behaviour, and privacy
rules are specified with representative Batch, Transcript, Dubbing, and
Longform fixtures.

## Answer

Galaxy will use a directory-based, versioned Project Bundle with one root
Project Manifest and independently versioned Workflow Documents. Asset
ownership is hybrid: critical/small inputs are managed, media at or above
100 MiB is linked by default, and Collect Project makes a portable copy.

Stable UUIDs and SHA-256 fingerprints separate identity from paths. Saves use
revision checks, atomic replacement, a single-writer Project Lock, and up to ten
metadata-only Recovery Snapshots. Schema migration is staged and sequential;
newer unsupported projects open read-only. Relink never silently accepts
modified content.

Working projects remain directories. Full or compact transfer archives use the
validated ZIP64 `.galaxybundle` format. Secret values and private machine
metadata are excluded. Voice dependencies are captured as revisioned Pinned
Voice Snapshots, while runtimes, large models, and credentials remain external
dependencies.

The accepted contract is in
[`project-bundle-contract.md`](../research/project-bundle-contract.md), the
architectural decision is in
[`ADR 0001`](../../../docs/adr/0001-portable-galaxy-project-bundles.md), and
machine-readable schema plus representative fixtures are under the sibling
`project-bundle-schemas/` and `project-bundle-fixtures/` directories. The root
fixture passes Draft 2020-12 JSON Schema validation; all fixtures pass JSON,
cross-reference, path-containment, and secret-pattern checks.
