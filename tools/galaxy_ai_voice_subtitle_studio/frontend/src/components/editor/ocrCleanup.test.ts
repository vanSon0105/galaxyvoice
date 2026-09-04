import { describe, expect, it } from 'vitest'

import type { EditorMedia } from '../../api/editor'
import type { VideoOcrCue } from '../../api/videoOcr'
import { buildOcrRemovalMasks, sameMediaPath } from './ocrCleanup'

const SOURCE: EditorMedia = {
  source_id: 'video-1',
  url: '/api/editor/source/video-1',
  name: 'video.mp4',
  path: 'D:/video.mp4',
  kind: 'video',
  duration_seconds: 30,
  width: 1920,
  height: 1080,
  fps: 30,
  has_audio: true,
}

describe('buildOcrRemovalMasks', () => {
  it('matches Windows media paths independently of slash direction and case', () => {
    expect(sameMediaPath('D:\\Media\\CLIP.mp4', 'd:/media/clip.mp4')).toBe(true)
    expect(sameMediaPath('D:/media/one.mp4', 'D:/media/two.mp4')).toBe(false)
  })

  it('turns OCR bounds and cue timing into editor cleanup masks', () => {
    const cues: VideoOcrCue[] = [{
      index: 1,
      start_ms: 2_000,
      end_ms: 4_500,
      text: 'Phụ đề cháy',
      confidence: 0.91,
      boxes: [{ x: 192, y: 810, width: 1536, height: 162 }],
    }]

    const masks = buildOcrRemovalMasks(cues, SOURCE, { x: 5, y: 68, width: 90, height: 27 })

    expect(masks).toEqual([expect.objectContaining({
      name: 'OCR 1',
      region: { x: 9, y: 74, width: 82, height: 17 },
      start_seconds: 2,
      end_seconds: 4.5,
    })])
  })

  it('keeps generated masks bounded and batches long OCR results', () => {
    const cues: VideoOcrCue[] = Array.from({ length: 30 }, (_, index) => ({
      index: index + 1,
      start_ms: index * 1_000,
      end_ms: index * 1_000 + 800,
      text: `Câu ${index + 1}`,
      confidence: 0.9,
      boxes: [],
    }))

    const masks = buildOcrRemovalMasks(cues, SOURCE, { x: 5, y: 68, width: 90, height: 27 }, 12)

    expect(masks).toHaveLength(10)
    expect(masks[0]).toEqual(expect.objectContaining({
      region: { x: 5, y: 68, width: 90, height: 27 },
      start_seconds: 0,
      end_seconds: 2.8,
    }))
    expect(masks.at(-1)?.end_seconds).toBe(29.8)
  })
})
