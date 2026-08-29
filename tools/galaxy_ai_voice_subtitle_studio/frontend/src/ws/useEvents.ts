import { useEffect, useState } from 'react'

import { publishConnectionOpen, publishEvent } from './hub'
import type { ServerEvent } from './types'

export type WsState = 'connecting' | 'open' | 'closed'

const INITIAL_RECONNECT_MS = 2000
const MAX_RECONNECT_MS = 60000

/** Opens the app's single WebSocket with exponential-backoff reconnect.
 *  Incoming messages fan out through the event hub. */
export function useEvents(): WsState {
  const [state, setState] = useState<WsState>('connecting')

  useEffect(() => {
    let stopped = false
    let socket: WebSocket | null = null
    let timer: number | undefined
    let attempt = 0

    const connect = () => {
      if (stopped) return
      setState('connecting')
      const url = `${location.protocol === 'https:' ? 'wss://' : 'ws://'}${location.host}/ws/events`
      socket = new WebSocket(url)
      socket.onopen = () => {
        attempt = 0
        setState('open')
        publishConnectionOpen()
      }
      socket.onmessage = (message) => {
        try {
          publishEvent(JSON.parse(message.data as string) as ServerEvent)
        } catch {
          // Ignore malformed frames; the server sends JSON only.
        }
      }
      socket.onclose = () => {
        if (stopped) return
        setState('closed')
        attempt += 1
        const delay = Math.min(MAX_RECONNECT_MS, INITIAL_RECONNECT_MS * 2 ** attempt)
        timer = window.setTimeout(connect, delay + Math.random() * 1000)
      }
      socket.onerror = () => {
        socket?.close()
      }
    }

    connect()
    return () => {
      stopped = true
      window.clearTimeout(timer)
      socket?.close()
    }
  }, [])

  return state
}
