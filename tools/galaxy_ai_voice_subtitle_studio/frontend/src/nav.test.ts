import { describe, expect, it } from 'vitest'

import { DEFAULT_ROUTE, NAV_ITEMS, VOICE_NAV_ITEMS } from './nav'

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

  it('exposes Voice as one top-level workspace', () => {
    expect(NAV_ITEMS.filter((item) => item.id === 'voice')).toHaveLength(1)
    expect(NAV_ITEMS.some((item) => item.id === 'voicestudio')).toBe(false)
    expect(NAV_ITEMS.some((item) => item.id === 'omnivoice')).toBe(false)
  })

  it('defines the remaining native Voice surfaces', () => {
    expect(VOICE_NAV_ITEMS.map((item) => item.id)).toEqual([
      'studio',
      'batch',
      'library',
    ])
    expect(VOICE_NAV_ITEMS.every((item) => item.route.startsWith('/voice'))).toBe(true)
  })

  it('keeps Gallery inside the Voice Library instead of primary navigation', () => {
    expect(VOICE_NAV_ITEMS.some((item) => item.id === 'gallery')).toBe(false)
    expect(VOICE_NAV_ITEMS.find((item) => item.id === 'library')?.route).toBe('/voice/library')
  })
})
