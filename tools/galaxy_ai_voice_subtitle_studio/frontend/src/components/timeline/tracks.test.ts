import { describe, expect, it, vi } from 'vitest'

import type { EditorMedia } from '../../api/editor'
import { createDefaultTracks, createTrack, editorDuration, mediaClip, placeAudioClips } from './tracks'

vi.stubGlobal('crypto', { randomUUID: vi.fn(() => `id-${Math.random()}`) })

const audio = (name: string, seconds: number): EditorMedia => ({
  source_id: name,
  url: `/media/${name}`,
  name,
  path: `D:/${name}`,
  kind: 'audio',
  duration_seconds: seconds,
  width: 0,
  height: 0,
  fps: 0,
  has_audio: true,
})

describe('editor tracks', () => {
  it('starts with one subtitle, video, and audio track', () => {
    expect(createDefaultTracks().map((track) => track.kind)).toEqual(['subtitle', 'video', 'audio'])
  })

  it('measures positioned media clips instead of assuming one linear source', () => {
    const track = createTrack('audio')
    if (track.kind !== 'audio') throw new Error('expected audio track')
    track.clips = [mediaClip(audio('voice.wav', 4), 6_000)]
    expect(editorDuration([track])).toBe(10_000)
  })

  it('packs overlapping generated speech onto another audio lane', () => {
    const subtitle = createTrack('subtitle')
    const first = mediaClip(audio('one.wav', 4), 0)
    const second = mediaClip(audio('two.wav', 2), 3_000)
    const third = mediaClip(audio('three.wav', 1), 6_000)

    const result = placeAudioClips([subtitle], [first, second, third], subtitle.id)
    const audioTracks = result.tracks.filter((track) => track.kind === 'audio')

    expect(audioTracks).toHaveLength(2)
    expect(audioTracks[0].clips.map((clip) => clip.media.name)).toEqual(['one.wav', 'three.wav'])
    expect(audioTracks[1].clips.map((clip) => clip.media.name)).toEqual(['two.wav'])
  })
})
