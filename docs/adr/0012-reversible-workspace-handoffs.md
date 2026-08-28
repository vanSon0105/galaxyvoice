# ADR 0012: Reversible workspace handoffs

## Status

Accepted

## Context

Galaxy workflows already shared an Active Project, but their documents and
generated files were discovered through separate histories. Passing bare paths
between Studio, Batch, Transcripts, Longform, Dubbing, and media tools made
ownership unclear and provided no reliable way to return to the originating
workflow after downstream work.

## Decision

Galaxy maintains one metadata-only project graph beside application settings.
Each node identifies a workflow owner and references managed, linked, or
generated artifacts without copying or moving them. Workflow services register
their real documents and completed task outputs in the graph. Voice Library
joins a project when a voice is pinned, using its managed Pinned Voice Snapshot
as the owned artifact.

A handoff records the source node and revision, selected input artifacts,
destination workspace and routes, sanitized payload, destination node, and
returned output artifacts. Its lifecycle is `pending`, `opened`, then
`returned`. Supported transitions come from one backend workspace catalogue;
cross-project assets and unsupported transitions are rejected.

The React title bar reads this contract to show the Active Project flow, open a
destination, and return to the source. Workflow documents remain authoritative
for edits; the graph only indexes provenance and navigation.

## Consequences

- Native workspaces can exchange references without destructive file copies.
- Users can see which workflow owns an artifact and retrace downstream output.
- Credentials are excluded from graph metadata.
- New workspaces must declare routes and supported transitions before they can
  participate in handoffs.
- Missing linked files remain a Project Bundle relink concern; the graph does
  not become a media store.
