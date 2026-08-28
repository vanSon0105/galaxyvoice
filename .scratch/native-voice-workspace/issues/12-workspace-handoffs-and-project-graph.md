# Workspace handoffs and project graph

Type: grilling
Status: resolved
Blocked by: 02, 06, 07, 08, 09, 10, 11

## Question

Which handoffs are first-class and reversible between Studio, Batch, Voice
Library, Transcripts, Longform, Dubbing, the video editor, audio separation,
and subtitle removal, and how is source/output provenance retained?

## Done when

The project graph prevents destructive copies, makes ownership visible, and
defines consistent open-in/return-from behaviours for every supported handoff.

## Decision

- One Galaxy-owned project graph indexes workflow nodes, artifact references,
  and handoff records under the Active Project. It stores metadata only and
  never copies, moves, or deletes media.
- Asset references declare `managed`, `linked`, or `generated` ownership and
  preserve source-to-output derivation. Secret-like metadata is removed before
  persistence.
- Handoffs follow `pending -> opened -> returned`. A returned handoff keeps its
  source revision, routes, selected inputs, target node, and produced outputs;
  it cannot be reopened and silently overwrite its return record.
- The supported transition matrix and workspace routes live in one backend
  catalogue consumed by the React panel. Unsupported and cross-project links
  are rejected.
- Studio, Batch, pinned Voice Library snapshots, Transcripts, Longform,
  Dubbing, the editor, audio separation, and subtitle removal register their
  real documents and outputs. The latter three receive the shared Active
  Project ID when a task starts.
- The title bar exposes the current graph, ownership summary, first-class
  open-in actions, and a return-to-source action. Existing workflow documents
  remain the owners of editable state.

## Verification

- Domain tests cover reversible lifecycle, route resolution, secret stripping,
  unsupported transitions, cross-project nodes/assets, and immutable returns.
- API tests cover graph discovery plus Transcript, Studio, Batch, Voice Library,
  editor, separation, and subtitle-removal provenance.
- Frontend tests cover project ownership visibility, destination opening, and
  return navigation. Type checking, production build, and full backend/frontend
  suites are required before the phase commit.
