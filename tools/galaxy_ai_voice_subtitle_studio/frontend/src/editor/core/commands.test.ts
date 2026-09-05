import { describe, expect, it } from 'vitest'

import {
  createEditorProject,
  createEditorSession,
  executeEditorCommand,
  mediaTime,
  redoEditorCommand,
  undoEditorCommand,
  type AudioTrack,
  type MediaSource,
  type OverlayVideoTrack,
} from './index'

const PROJECT_ID = '10000000-0000-4000-8000-000000000001'
const SOURCE_ID = '10000000-0000-4000-8000-000000000002'
const OVERLAY_ID = '10000000-0000-4000-8000-000000000003'
const AUDIO_ID = '10000000-0000-4000-8000-000000000004'
const CLIP_ID = '10000000-0000-4000-8000-000000000005'
const SUBTITLE_ID = '10000000-0000-4000-8000-000000000006'

const source: MediaSource = {
  asset_id: SOURCE_ID,
  kind: 'video',
  name: 'source.mp4',
  ownership: 'linked',
  path_hint: 'D:/source.mp4',
  fingerprint: { algorithm: 'sha256', value: '1'.repeat(64), byte_size: 1_024 },
  provenance: { origin: 'imported', derived_from: [] },
  duration: mediaTime(1_200_000),
  width: 1_920,
  height: 1_080,
  frame_rate: { numerator: 30, denominator: 1 },
  has_audio: true,
}

const overlay: OverlayVideoTrack = {
  id: OVERLAY_ID,
  kind: 'video',
  role: 'overlay',
  name: 'Overlay 1',
  enabled: true,
  locked: false,
  clips: [],
}

describe('editor command session', () => {
  it('commits a multi-step edit as one undoable transaction', () => {
    let session = createEditorSession(createEditorProject({ project_id: PROJECT_ID, now: '2026-09-05T00:00:00.000Z' }))
    session = executeEditorCommand(session, {
      type: 'transaction',
      label: 'Add overlay video',
      commands: [
        { type: 'add-source', source },
        { type: 'add-track', track: overlay },
        {
          type: 'add-item',
          track_id: overlay.id,
          item: {
            id: CLIP_ID,
            kind: 'media',
            asset_id: source.asset_id,
            timeline_start: mediaTime(0),
            source_in: mediaTime(0),
            source_out: mediaTime(600_000),
            enabled: true,
            gain: 1,
          },
        },
      ],
    }, '2026-09-05T00:01:00.000Z')

    expect(session.project.timeline.overlays[0].clips).toHaveLength(1)
    expect(session.past).toHaveLength(1)
    expect(session.project.revision).toBe(1)

    session = undoEditorCommand(session, '2026-09-05T00:02:00.000Z')
    expect(session.project.sources).toEqual([])
    expect(session.project.timeline.overlays).toEqual([])
    expect(session.project.revision).toBe(2)

    session = redoEditorCommand(session, '2026-09-05T00:03:00.000Z')
    expect(session.project.timeline.overlays[0].clips[0].id).toBe(CLIP_ID)
    expect(session.project.revision).toBe(3)
  })

  it('rejects an incompatible transaction without mutating the active project', () => {
    const initial = createEditorSession(createEditorProject({ project_id: PROJECT_ID }))
    const audioTrack: AudioTrack = {
      id: AUDIO_ID,
      kind: 'audio',
      role: 'audio',
      name: 'Audio 1',
      enabled: true,
      locked: false,
      clips: [],
    }

    expect(() => executeEditorCommand(initial, {
      type: 'transaction',
      label: 'Invalid edit',
      commands: [
        { type: 'add-track', track: audioTrack },
        {
          type: 'add-item',
          track_id: audioTrack.id,
          item: { id: SUBTITLE_ID, kind: 'subtitle', start: mediaTime(0), end: mediaTime(120_000), text: 'No' },
        },
      ],
    })).toThrow('incompatible')
    expect(initial.project.timeline.audio).toEqual([])
    expect(initial.past).toEqual([])
  })

  it('clears redo history when a new edit branches from an undone state', () => {
    let session = createEditorSession(createEditorProject({ project_id: PROJECT_ID }))
    session = executeEditorCommand(session, { type: 'add-track', track: overlay })
    session = undoEditorCommand(session)
    session = executeEditorCommand(session, {
      type: 'add-track',
      track: { ...overlay, id: AUDIO_ID, name: 'Overlay 2' },
    })

    expect(session.future).toEqual([])
    expect(session.project.timeline.overlays.map((track) => track.id)).toEqual([AUDIO_ID])
  })

  it('keeps locked tracks immutable until explicitly unlocked', () => {
    let session = createEditorSession(createEditorProject({ project_id: PROJECT_ID }))
    session = executeEditorCommand(session, { type: 'add-track', track: { ...overlay, locked: true } })

    expect(() => executeEditorCommand(session, {
      type: 'add-item',
      track_id: overlay.id,
      item: {
        id: CLIP_ID,
        kind: 'media',
        asset_id: source.asset_id,
        timeline_start: mediaTime(0),
        source_in: mediaTime(0),
        source_out: mediaTime(120_000),
        enabled: true,
        gain: 1,
      },
    })).toThrow('locked')
  })

  it('owns immutable command payloads and requires a finite history bound', () => {
    const mutableOverlay = { ...overlay }
    let session = createEditorSession(createEditorProject({ project_id: PROJECT_ID }), 2)
    session = executeEditorCommand(session, { type: 'add-track', track: mutableOverlay })
    mutableOverlay.name = 'Mutated outside the editor'

    expect(session.project.timeline.overlays[0].name).toBe('Overlay 1')
    expect(Object.isFrozen(session.project.timeline.overlays[0])).toBe(true)
    expect(Object.isFrozen(session.past)).toBe(true)
    expect(Object.isFrozen(session.past[0])).toBe(true)
    expect(() => createEditorSession(session.project, Number.POSITIVE_INFINITY)).toThrow('positive safe integer')
    expect(() => createEditorSession(session.project, Number.NaN)).toThrow('positive safe integer')
  })
})
