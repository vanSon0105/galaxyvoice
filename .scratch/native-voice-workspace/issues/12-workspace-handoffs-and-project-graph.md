# Workspace handoffs and project graph

Type: grilling
Status: open
Blocked by: 02, 06, 07, 08, 09, 10, 11

## Question

Which handoffs are first-class and reversible between Studio, Batch, Voice
Library, Transcripts, Longform, Dubbing, the video editor, audio separation,
and subtitle removal, and how is source/output provenance retained?

## Done when

The project graph prevents destructive copies, makes ownership visible, and
defines consistent open-in/return-from behaviours for every supported handoff.
