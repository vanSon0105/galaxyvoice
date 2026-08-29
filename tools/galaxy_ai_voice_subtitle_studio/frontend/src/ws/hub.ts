import type { ServerEvent } from './types'

/** Tiny in-app event hub: ONE WebSocket per app (opened by useEvents),
 *  any number of subscribers (useTasks, query invalidation, …). */
type Listener = (event: ServerEvent) => void
type ConnectionListener = () => void

const listeners = new Set<Listener>()
const connectionListeners = new Set<ConnectionListener>()

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

export function subscribeConnectionOpen(listener: ConnectionListener): () => void {
  connectionListeners.add(listener)
  return () => {
    connectionListeners.delete(listener)
  }
}

export function publishConnectionOpen(): void {
  for (const listener of [...connectionListeners]) {
    listener()
  }
}
