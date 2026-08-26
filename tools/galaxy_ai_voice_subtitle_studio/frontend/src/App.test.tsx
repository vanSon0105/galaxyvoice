import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { LegacyVoiceRedirect } from './App'

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
