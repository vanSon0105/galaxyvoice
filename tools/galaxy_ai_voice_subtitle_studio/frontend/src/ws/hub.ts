import type { ServerEvent } from './types'

/** Tiny in-app event hub: ONE WebSocket per app (opened by useEvents),
 *  any number of subscribers (useTasks, query invalidation, …). */
type Listener = (event: ServerEvent) => void

const listeners = new Set<Listener>()

export function subscribeEvents(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function publishEvent(event: ServerEvent): void {
  for (const listener of [...listeners]) {
    listener(event)
  }
}
