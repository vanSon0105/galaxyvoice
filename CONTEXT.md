# Galaxy AI Studio Context

## Terms

### Galaxy Project Bundle

A self-contained project directory that owns its versioned manifest, editable
workflow data, and produced outputs. Source media may be linked rather than
copied, but the manifest records a portable relative path whenever possible.

### Voice Library

The local-first catalogue of voices usable by Galaxy workflows. A voice may be
a system voice, an imported voice, a cloned profile, or a designed profile.
It is not a public marketplace or community gallery.

### Voice Profile

A reusable local voice definition with its consent record, engine capability,
reference material where needed, tags, and preview/history metadata.

### Voice Workspace

The Galaxy-owned group of workflows for Studio, Batch, Voice Library,
Transcripts, Longform, and Dubbing. It is implemented independently of the
vendored VoiceStudio service.

### Audio Lip-Sync

Fitting synthesized speech to a source speech interval using accurate timing,
bounded rate adjustment that preserves pitch, and quality checks. It does not
mean altering a face or mouth in video frames.
