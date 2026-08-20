import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as removalApi from '../api/removal'
import * as settingsApi from '../api/settings'
import type { SettingsMeta } from '../api/settings'
import { RemovalPage } from './RemovalPage'

const SETTINGS_META: SettingsMeta = {
  tts_engines: [],
  default_tts_engine: '',
  whisper_models: [],
  translation_providers: [],
  default_translation_provider: '',
  source_languages: [],
  target_languages: [],
  processing_devices: [{ code: 'auto', label: 'Tự động' }, { code: 'cpu', label: 'CPU' }],
  audio_methods: [],
  audio_devices: [],
  audio_formats: [],
  removal_modes: [],
  editor_resolutions: [],
  editor_fps: [],
  editor_encoders: [],
  editor_audio_modes: [],
  omnivoice_devices: [],
}

afterEach(() => vi.restoreAllMocks())

describe('RemovalPage', () => {
  it('loads a playable video and exposes AI license controls only for AI modes', async () => {
    vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue({
      output_dir: 'D:/result',
      subtitle_removal_mode: 'blur',
    })
    vi.spyOn(settingsApi, 'fetchSettingsMeta').mockResolvedValue(SETTINGS_META)
    vi.spyOn(removalApi, 'fetchRemovalMeta').mockResolvedValue({
      modes: [
        { code: 'blur', label: 'Làm mờ', uses_ai: false },
        { code: 'fast_ai_inpaint', label: 'Fast AI', uses_ai: true },
      ],
      propainter_ready: true,
      runtime_path: 'python.exe',
      installer_available: true,
    })
    vi.spyOn(removalApi, 'registerRemovalSource').mockResolvedValue({
      source_id: 'source-1',
      url: '/api/removal/source/source-1',
      width: 1920,
      height: 1080,
      duration: 30,
      name: 'clip.mp4',
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={client}>
        <RemovalPage />
      </QueryClientProvider>,
    )

    const pathInput = await screen.findByLabelText('Video đầu vào')
    fireEvent.change(pathInput, { target: { value: 'D:/clip.mp4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Nạp' }))
    const video = await screen.findByText('clip.mp4 · 1920×1080')
    expect(video).toBeInTheDocument()
    expect(document.querySelector('video')).toHaveAttribute('src', '/api/removal/source/source-1')
    expect(screen.queryByText(/phi thương mại/)).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Chế độ'), { target: { value: 'fast_ai_inpaint' } })
    expect(await screen.findByText(/phi thương mại/)).toBeInTheDocument()
    expect(screen.getByLabelText('Thiết bị xử lý')).toHaveValue('auto')
  })
})
