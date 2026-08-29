import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ExtensionCapabilitiesPanel } from './ExtensionCapabilitiesPanel'

const CAPABILITIES_RESPONSE = {
  capabilities: [
    {
      capability_id: 'dictation.live',
      label: 'Live dictation',
      category: 'voice_input',
      disposition: 'extension',
      summary: 'Capture microphone speech as text in other applications.',
      boundary: 'Reuse the Transcript ASR adapter.',
      constraints: ['Microphone access requires explicit permission.'],
      revisit_triggers: ['A supported capture contract is available.'],
      extension_capability_ids: ['asr.faster-whisper'],
      default_enabled: false,
    },
    {
      capability_id: 'backend.remote',
      label: 'Remote backend',
      category: 'deployment',
      disposition: 'deferred',
      summary: 'Run Galaxy voice services beyond the local desktop boundary.',
      boundary: 'Keep the desktop service on loopback.',
      constraints: ['Remote access needs a dedicated threat model.'],
      revisit_triggers: ['A remote ownership plan is approved.'],
      extension_capability_ids: [],
      default_enabled: false,
    },
    {
      capability_id: 'audio.watermarking',
      label: 'Audio watermarking',
      category: 'provenance',
      disposition: 'optional_adapter',
      summary: 'Apply an optional provenance mark to generated audio.',
      boundary: 'Use a separately licensed adapter.',
      constraints: ['A fresh license review is required.'],
      revisit_triggers: ['A compatible implementation passes review.'],
      extension_capability_ids: [],
      default_enabled: false,
    },
    {
      capability_id: 'marketplace.plugins',
      label: 'Plugin marketplace',
      category: 'ecosystem',
      disposition: 'non_goal',
      summary: 'Publish and execute third-party Galaxy extensions.',
      boundary: 'Keep marketplace execution outside the desktop product.',
      constraints: ['Third-party execution is not a protected boundary.'],
      revisit_triggers: ['A new product decision changes this non-goal.'],
      extension_capability_ids: [],
      default_enabled: false,
    },
  ],
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ExtensionCapabilitiesPanel />
    </QueryClientProvider>,
  )
}

function respondWith(body: unknown, status = 200) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    if (String(input) !== '/api/extensions/capabilities') {
      throw new Error(`Unexpected request: ${String(input)}`)
    }
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as Response
  }))
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ExtensionCapabilitiesPanel', () => {
  it('shows an explicit loading state while the catalogue request is pending', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))

    renderPanel()

    expect(screen.getByRole('status')).toHaveTextContent('Đang tải danh mục tính năng mở rộng')
  })

  it('shows an explicit error when the catalogue cannot be loaded', async () => {
    respondWith({ detail: 'Catalogue unavailable' }, 400)

    renderPanel()

    expect(await screen.findByRole('alert')).toHaveTextContent('Không thể tải danh mục tính năng mở rộng')
  })

  it('shows text labels for every disposition without enable controls', async () => {
    respondWith(CAPABILITIES_RESPONSE)

    renderPanel()

    expect(await screen.findByText('Tiện ích mở rộng')).toBeInTheDocument()
    expect(screen.getByText('Tạm hoãn')).toBeInTheDocument()
    expect(screen.getByText('Bộ điều hợp tùy chọn')).toBeInTheDocument()
    expect(screen.getByText('Không phải mục tiêu')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('uses a keyboard-focusable native disclosure for capability details', async () => {
    respondWith(CAPABILITIES_RESPONSE)

    renderPanel()

    const capabilityName = await screen.findByText('Live dictation')
    const summary = capabilityName.closest('summary')
    const details = summary?.closest('details')
    expect(summary).not.toBeNull()
    expect(details).not.toBeNull()
    if (summary === null || details === null) throw new Error('Missing native disclosure')

    summary.focus()
    expect(summary).toHaveFocus()
    fireEvent.click(summary)

    expect(details).toHaveAttribute('open')
    expect(screen.getByText('Reuse the Transcript ASR adapter.')).toBeVisible()
    expect(screen.getByText('Microphone access requires explicit permission.')).toBeVisible()
    expect(screen.getByText('A supported capture contract is available.')).toBeVisible()
  })
})
