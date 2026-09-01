import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

const lazyModules = vi.hoisted(() => ({ parityLoads: 0 }))

vi.mock('./pages/SettingsPage', () => ({
  SettingsPage: () => <div>Cài đặt độc lập</div>,
}))

vi.mock('./pages/ParityPage', () => {
  lazyModules.parityLoads += 1
  return { ParityPage: () => <div>Đối chiếu parity độc lập</div> }
})

import { AppRoutes, LegacyVoiceRedirect } from './App'

afterEach(() => {
  cleanup()
})

function RedirectTarget() {
  const location = useLocation()
  return <div>{`${location.pathname}${location.search}`}</div>
}

describe('legacy Voice routes', () => {
  it('keeps prefilled voice parameters while redirecting to the native route', async () => {
    render(
      <MemoryRouter initialEntries={['/omnivoice?mode=design&language=vi']}>
        <Routes>
          <Route path="/omnivoice" element={<LegacyVoiceRedirect to="/voice" />} />
          <Route path="/voice" element={<RedirectTarget />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('/voice?mode=design&language=vi')).toBeInTheDocument()
  })
})

describe('Settings-owned parity route', () => {
  it('loads the parity bundle only for the nested Settings route', async () => {
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <AppRoutes />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Cài đặt độc lập')).toBeInTheDocument()
    expect(lazyModules.parityLoads).toBe(0)

    cleanup()
    render(
      <MemoryRouter initialEntries={['/settings/parity']}>
        <AppRoutes />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Đối chiếu parity độc lập')).toBeInTheDocument()
    expect(lazyModules.parityLoads).toBe(1)
  })
})
