import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Timeline } from './Timeline'

describe('Timeline playhead', () => {
  it('seeks continuously while the red playhead is dragged', () => {
    const onSeek = vi.fn()
    const { container } = render(
      <Timeline
        durationMs={10_000}
        audioOffsetMs={0}
        cues={[]}
        selectedCue={null}
        playheadMs={1_000}
        zoom={100}
        onSeek={onSeek}
        onSelectCue={vi.fn()}
        onChangeCue={vi.fn()}
        onAudioOffset={vi.fn()}
        onDropAsset={vi.fn()}
      />,
    )
    const svg = container.querySelector('svg') as SVGSVGElement
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 1_200, bottom: 166,
      width: 1_200, height: 166, toJSON: () => ({}),
    })

    fireEvent.pointerDown(svg, { button: 0, pointerId: 1, clientX: 188 })
    fireEvent.pointerMove(svg, { pointerId: 1, clientX: 588 })
    fireEvent.pointerUp(svg, { pointerId: 1, clientX: 588 })

    expect(onSeek).toHaveBeenLastCalledWith(5_000)
    expect(onSeek).toHaveBeenCalledTimes(2)
  })
})
