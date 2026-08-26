import { useCallback, useEffect, useRef, useState } from 'react'

export interface RealtimeEvent {
  type: string
  payload: Record<string, unknown>
  timestamp?: string
}

export type RealtimeStatus = 'connecting' | 'online' | 'offline'

/**
 * Native WebSocket client for /api/.../{API_PREFIX}/ws.
 * - Auto-reconnects with exponential backoff (1s → 30s cap).
 * - Sends app-level ping every 25 s; server replies pong.
 * - Demo-safe: when the gateway is down it just reports "offline".
 */
export function useRealtime(
  enabled: boolean,
  token: string | null,
  onEvent: (event: RealtimeEvent) => void,
): RealtimeStatus {
  const [status, setStatus] = useState<RealtimeStatus>('offline')
  const [clientId] = useState(() => crypto.randomUUID())
  const wsRef = useRef<WebSocket | null>(null)
  const attemptRef = useRef(0)
  const timerRef = useRef<number | null>(null)
  const eventRef = useRef(onEvent)
  eventRef.current = onEvent

  const connect = useCallback(() => {
    if (!enabled) return
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = new URL(`${proto}://${window.location.host}/api/v1/ws/${clientId}`)
    if (token) url.searchParams.set('token', token)

    let ws: WebSocket
    try {
      ws = new WebSocket(url.toString())
    } catch {
      scheduleReconnect()
      return
    }
    wsRef.current = ws

    ws.onopen = () => {
      attemptRef.current = 0
      setStatus('online')
    }

    ws.onmessage = (messageEvent) => {
      try {
        const parsed = JSON.parse(messageEvent.data) as RealtimeEvent
        if (parsed?.type === 'pong' || parsed?.type === 'connection.established') return
        eventRef.current(parsed)
      } catch {
        /* malformed frame — ignore */
      }
    }

    ws.onclose = () => {
      setStatus('offline')
      wsRef.current = null
      scheduleReconnect()
    }

    ws.onerror = () => {
      try {
        ws.close()
      } catch {
        /* already closing */
      }
    }

    function scheduleReconnect() {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      const delay = Math.min(30_000, 1000 * 2 ** attemptRef.current)
      attemptRef.current += 1
      timerRef.current = window.setTimeout(connect, delay)
    }
  }, [clientId, enabled, token])

  useEffect(() => {
    if (!enabled) {
      setStatus('offline')
      return
    }
    connect()

    // App-level keepalive so proxies don't idle-kill the socket.
    const pingTimer = window.setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }))
      }
    }, 25_000)

    // Browsers auto-close sockets when the tab sleeps; nudge on wake.
    const onVisible = () => {
      if (document.visibilityState === 'visible' && wsRef.current === null) {
        attemptRef.current = 0
        connect()
      }
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      window.clearInterval(pingTimer)
      document.removeEventListener('visibilitychange', onVisible)
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      const ws = wsRef.current
      wsRef.current = null
      if (ws && ws.readyState <= WebSocket.OPEN) {
        ws.onclose = null
        ws.close()
      }
    }
  }, [connect, enabled])

  return status
}
