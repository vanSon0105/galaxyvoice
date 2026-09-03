import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Timeline } from './Timeline'
import { TRACK_LABEL_WIDTH } from './geometry'
import { createDefaultTracks } from './tracks'

afterEach(cleanup)

describe('Timeline playhead', () => {
  it('seeks continuously while the red playhead is dragged', () => {
    const onSeek = vi.fn()
    const { container } = render(
      <Timeline
        durationMs={10_000}
        tracks={createDefaultTracks()}
        selection={null}
        playheadMs={1_000}
        zoom={100}
        onSeek={onSeek}
        onSelect={vi.fn()}
        onChangeCue={vi.fn()}
        onChangeClip={vi.fn()}
        onDropAsset={vi.fn()}
        onToggleTrackEnabled={vi.fn()}
        onToggleTrackLocked={vi.fn()}
        onAddTrack={vi.fn()}
      />,
    )
    const svg = container.querySelector('svg') as SVGSVGElement
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 1_200, bottom: 166,
      width: 1_200, height: 166, toJSON: () => ({}),
    })

    fireEvent.pointerDown(svg, { button: 0, pointerId: 1, clientX: TRACK_LABEL_WIDTH + 100 })
    fireEvent.pointerMove(svg, { pointerId: 1, clientX: TRACK_LABEL_WIDTH + 500 })
    fireEvent.pointerUp(svg, { pointerId: 1, clientX: TRACK_LABEL_WIDTH + 500 })

    expect(onSeek).toHaveBeenLastCalledWith(5_000)
    expect(onSeek).toHaveBeenCalledTimes(2)
  })

  it('offers all three track types from the add button', () => {
    const onAddTrack = vi.fn()
    const { container, getByRole } = render(
      <Timeline
        durationMs={10_000}
        tracks={createDefaultTracks()}
        selection={null}
        playheadMs={0}
        zoom={10}
        onSeek={vi.fn()}
        onSelect={vi.fn()}
        onChangeCue={vi.fn()}
        onChangeClip={vi.fn()}
        onDropAsset={vi.fn()}
        onToggleTrackEnabled={vi.fn()}
        onToggleTrackLocked={vi.fn()}
        onAddTrack={onAddTrack}
      />,
    )
    fireEvent.click(container.querySelector('[title="Thêm track"]') as HTMLButtonElement)
    fireEvent.click(getByRole('menuitem', { name: 'Thêm line audio' }))
    expect(onAddTrack).toHaveBeenCalledWith('audio')
  })
})
