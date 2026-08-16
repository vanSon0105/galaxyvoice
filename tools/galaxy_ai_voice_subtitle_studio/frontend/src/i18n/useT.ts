import { useCallback } from 'react'

import { vi } from './vi'

/** Translation hook: falls back to the key when a string is missing. */
export function useT(): (key: string) => string {
  return useCallback((key: string) => vi[key] ?? key, [])
}
