import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { discoverProjectAudio, exportAudio, fetchWaveform } from '../../api/audioPost'
import { AudioPostPanel } from './AudioPostPanel'

vi.mock('../../api/audioPost', async () => {
  const actual = await vi.importActual<typeof import('../../api/audioPost')>('../../api/audioPost')
  return { ...actual, discoverProjectAudio: vi.fn(), exportAudio: vi.fn(), fetchWaveform: vi.fn() }
})

vi.mock('../TaskButton', () => ({
  TaskButton: (props: {
    label: string
    onStart: () => Promise<string>
    onFinish?: (task: object) => void
  }) => (
    <button type="button" onClick={async () => {
      await props.onStart()
      props.onFinish?.({
        taskId: 'audio-post-1', kind: 'audio-post-export', status: 'done', lines: [],
        canPause: false, canResume: false, canCancel: false, updatedAt: 1,
        result: {
          export_id: 'export-1', project_dir: 'D:/project',
          files: { wav: 'D:/project/final.wav', mp3: 'D:/project/final.mp3' },
          media_urls: { wav: '/wav?project=1', mp3: '/mp3?project=1' },
          manifest_path: 'D:/project/audio_export_manifest.json', warnings: [],
        },
      })
    }}>{props.label}</button>
  ),
}))

describe('AudioPostPanel', () => {
  afterEach(cleanup)

  it('loads a bounded waveform and sends the shared post chain', async () => {
    vi.mocked(fetchWaveform).mockResolvedValue({ duration_ms: 1_000, peaks: [0.2, 0.8] })
    vi.mocked(discoverProjectAudio).mockResolvedValue([])
    vi.mocked(exportAudio).mockResolvedValue({ task_id: 'audio-post-1' })
    render(<AudioPostPanel projectId="project-1" workflowId="take-1" workspace="studio" projectDir="D:/project" title="Final" sources={[{ source_id: 'voice', label: 'Voice', path: 'D:/project/voice.wav', role: 'voice', preview_url: '/voice.wav' }]} />)

    fireEvent.click(screen.getByText('Hậu kỳ & xuất audio'))
    fireEvent.click(screen.getByRole('button', { name: 'Tải dạng sóng' }))
    await waitFor(() => expect(fetchWaveform).toHaveBeenCalledWith('D:/project/voice.wav', 'D:/project', 256))
    fireEvent.click(screen.getByRole('button', { name: 'Xuất bản hậu kỳ' }))

    await waitFor(() => expect(exportAudio).toHaveBeenCalledOnce())
    expect(vi.mocked(exportAudio).mock.calls[0][0]).toMatchObject({
      project_id: 'project-1', workflow_id: 'take-1', workspace: 'studio', formats: ['wav', 'mp3'],
      chain: { preset: 'voice_clean', normalize: true },
    })
    expect(await screen.findByRole('link', { name: 'Tải WAV' })).toHaveAttribute('href', '/wav?project=1&download=true')
  })

  it('supports keyboard seeking on the waveform slider', async () => {
    vi.mocked(fetchWaveform).mockResolvedValue({ duration_ms: 20_000, peaks: [0.2, 0.8] })
    vi.mocked(discoverProjectAudio).mockResolvedValue([])
    render(<AudioPostPanel projectId="project-1" workflowId="take-1" workspace="studio" projectDir="D:/project" title="Final" sources={[{ source_id: 'voice', label: 'Voice', path: 'D:/project/voice.wav', role: 'voice', preview_url: '/voice.wav' }]} />)

    fireEvent.click(screen.getByText('Hậu kỳ & xuất audio'))
    fireEvent.click(screen.getByRole('button', { name: 'Tải dạng sóng' }))
    const slider = await screen.findByRole('slider', { name: 'Vị trí phát audio' })
    const audio = document.querySelector('audio') as HTMLAudioElement
    Object.defineProperty(audio, 'currentTime', { value: 0, writable: true })
    fireEvent.keyDown(slider, { key: 'ArrowRight' })
    expect(audio.currentTime).toBe(1)
    fireEvent.keyDown(slider, { key: 'End' })
    expect(audio.currentTime).toBe(20)
  })
})
