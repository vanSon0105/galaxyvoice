import { describe, expect, it } from 'vitest'

import { DEFAULT_ROUTE, NAV_ITEMS } from './nav'

describe('nav', () => {
  it('has unique ids and routes', () => {
    const ids = new Set(NAV_ITEMS.map((item) => item.id))
    const routes = new Set(NAV_ITEMS.map((item) => item.route))
    expect(ids.size).toBe(NAV_ITEMS.length)
    expect(routes.size).toBe(NAV_ITEMS.length)
  })

  it('default route is the first workspace', () => {
    expect(DEFAULT_ROUTE).toBe(NAV_ITEMS[0].route)
  })

  it('covers every workspace route', () => {
    for (const item of NAV_ITEMS) {
      expect(item.route.startsWith('/')).toBe(true)
    }
  })

  it('routes the top-level VoiceStudio tab to its nested workspace', () => {
    expect(NAV_ITEMS.find((item) => item.id === 'voicestudio')?.route).toBe(
      '/omnivoice/voicestudio',
    )
  })
})
