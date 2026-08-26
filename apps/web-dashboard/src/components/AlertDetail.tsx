import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { useMap } from '@/hooks/useMap'
import { useDismissable } from '@/hooks/useDismissable'
import { districtCenter } from '@/lib/districts'
import { acknowledgeAlert } from '@/services/api'
import type { Alert } from '@/types'

const SEV_TONE: Record<string, { chip: string; bar: string; text: string }> = {
  evacuation: { chip: 'badge-evacuation', bar: '#f85149', text: 'text-red-400' },
  warning:    { chip: 'badge-warning',    bar: '#fc8d59', text: 'text-orange-400' },
  watch:      { chip: 'badge-watch',      bar: '#d29922', text: 'text-yellow-300' },
  advisory:   { chip: 'badge-advisory',   bar: '#58a6ff', text: 'text-sky-400' },
}

const SEV_COLOR: Record<string, string> = {
  evacuation: '#f85149', warning: '#fc8d59', watch: '#d29922', advisory: '#58a6ff',
}

function AlertDetail({
  alert,
  onClose,
  onAcknowledge,
}: {
  alert: Alert | null
  onClose: () => void
  onAcknowledge: (id: string) => void
}) {
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const markerRef = useRef<maplibregl.Marker | null>(null)
  const c = districtCenter(alert?.district)
  const { map } = useMap({ containerRef: mapContainerRef, center: [c.lng, c.lat], zoom: 10 })
  useDismissable(alert !== null, onClose)
  const [ackPending, setAckPending] = useState(false)
  const [chartData] = useState(() => generateTrendData(alert?.probability ?? 0.5))

  useEffect(() => {
    if (!alert || !mapContainerRef.current || !map) return
    const cc = districtCenter(alert.district)
    if (markerRef.current) {
      markerRef.current.remove()
      markerRef.current = null
    }
    const el = document.createElement('div')
    const size = 14 + alert.probability * 22
    el.style.cssText = `width:${size}px;height:${size}px;border-radius:9999px;background:${SEV_COLOR[alert.severity]};opacity:.9;border:2px solid #0d1117;box-shadow:0 0 12px ${SEV_COLOR[alert.severity]}`
    const marker = new maplibregl.Marker({ element: el })
      .setLngLat([cc.lng, cc.lat])
      .setPopup(new maplibregl.Popup({ offset: 12 }).setHTML(`<b>${alert.severity.toUpperCase()}</b> · ${alert.district}<br/>P(failure)=${alert.probability.toFixed(2)}<br/><small>${alert.message}</small>`))
      .addTo(map)
    markerRef.current = marker
    return () => { markerRef.current?.remove(); markerRef.current = null }
  }, [alert, map])

  if (!alert) return null

  const tone = SEV_TONE[alert.severity] ?? SEV_TONE.advisory
  const acknowledged = alert.status === 'acknowledged'

  const handleAcknowledge = async () => {
    setAckPending(true)
    try {
      await acknowledgeAlert(alert.id)
      onAcknowledge(alert.id)
    } finally {
      setAckPending(false)
    }
  }

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="alert-title" className="fixed inset-0 z-50 flex justify-end">
      <button aria-label="Close" onClick={onClose} className="flex-1 bg-slate-950/80" />
      <aside className="flex flex-col w-full max-w-2xl border-l border-slate-800 bg-slate-900 shadow-2xl overflow-hidden">
        <header className="flex items-start justify-between gap-4 border-b border-slate-800 p-5">
          <div className="min-w-0">
            <span className={tone.chip}>{alert.severity}</span>
            <h2 id="alert-title" className="mt-2 text-lg font-bold leading-snug">{alert.title}</h2>
            <p className="mt-1 text-xs text-slate-500">
              Zone {alert.zone} · {alert.district} · issued {new Date(alert.issuedAt).toLocaleString()}
              {alert.expiresAt ? ` · expires ${new Date(alert.expiresAt).toLocaleString()}` : ''}
            </p>
          </div>
          <button onClick={onClose} className="flex-shrink-0 rounded-lg px-2 py-1.5 text-slate-500 transition hover:bg-slate-800 hover:text-slate-200">✕</button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5 space-y-5">
          {/* Map */}
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Location</h3>
            <div className="relative h-56 min-h-[224px] overflow-hidden rounded-xl border border-slate-800">
              <div ref={mapContainerRef} className="absolute inset-0" />
            </div>
          </section>

          {/* Probability gauge */}
          <section>
            <div className="flex items-baseline justify-between mb-2">
              <span className="text-xs font-medium uppercase tracking-wider text-slate-500">Failure Probability (72h)</span>
              <span className={`text-2xl font-bold ${tone.text}`}>{alert.probability.toFixed(2)}</span>
            </div>
            <div className="h-3 overflow-hidden rounded-full bg-slate-800">
              <div className={`h-full rounded-full ${tone.bar} transition-all duration-500`} style={{ width: `${Math.round(alert.probability * 100)}%` }} />
            </div>
            <div className="mt-2 flex justify-between text-[11px] text-slate-600">
              <span>0</span><span>0.25</span><span>0.50</span><span>0.75</span><span>1.0</span>
            </div>
          </section>

          {/* Risk trend chart */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Risk Trend (Last 72h)</h3>
            <div className="h-56 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="riskGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#f85149" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="#f85149" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="riskGradient2" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#fc8d59" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="#fc8d59" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="riskGradient3" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#d29922" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="#d29922" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                  <XAxis
                    dataKey="time"
                    tick={{ fill: '#8b949e', fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    domain={[0, 1]}
                    tick={{ fill: '#8b949e', fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={v => (v * 100).toFixed(0) + '%'}
                    width={30}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '8px', color: '#e6edf3' }}
                    formatter={(v: number) => [(v * 100).toFixed(1) + '%', 'Probability']}
                    labelFormatter={t => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  />
                  <Area
                    type="monotone"
                    dataKey="probability"
                    stroke="#f85149"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#riskGradient)"
                  />
                  <Area
                    type="monotone"
                    dataKey="m1"
                    stroke="#fc8d59"
                    strokeWidth={1}
                    strokeDasharray="4 4"
                    fillOpacity={0}
                  />
                  <Area
                    type="monotone"
                    dataKey="m2"
                    stroke="#d29922"
                    strokeWidth={1}
                    strokeDasharray="4 4"
                    fillOpacity={0}
                  />
                </AreaChart>
              </ResponsiveContainer>
              <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-slate-500">
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-f85149" /> Current (M2)</span>
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded border border-dashed border-fc8d59" /> M2 Forecast</span>
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded border border-dashed border-d29922" /> M1 Static</span>
              </div>
            </div>
          </section>

          {/* Message */}
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Model Message</h3>
            <p className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm leading-relaxed text-slate-300">{alert.message}</p>
          </section>

          {/* Model breakdown */}
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Model Pipeline</h3>
            <ol className="space-y-2 text-sm">
              {[
                ['M1 Susceptibility', 'static terrain + geology + historical inventory'],
                ['M2 Dynamic Risk', 'rainfall forecast + soil moisture + antecedent indices'],
                ['M3 CV Triage', 'citizen photo classification (crack/bulge/debris)'],
              ].map(([name, desc]) => (
                <li key={name} className="flex items-center gap-3 rounded-lg border border-slate-700 bg-slate-900/50 px-3 py-2">
                  <span className="font-mono text-emerald-400">▸</span>
                  <span className="font-medium">{name}</span>
                  <span className="truncate text-xs text-slate-500">{desc}</span>
                </li>
              ))}
            </ol>
          </section>

          {/* Delivery */}
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Delivery Channels</h3>
            <div className="flex flex-wrap gap-2">
              {['SMS', 'Push', 'WhatsApp', 'CAP/SACHET', 'Email'].map(c => (
                <span key={c} className="rounded-md border border-slate-700 bg-slate-800/60 px-2.5 py-1 text-xs text-slate-300">{c}</span>
              ))}
            </div>
          </section>
        </div>

        <footer className="border-t border-slate-800 p-5">
          {acknowledged ? (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300 flex items-center gap-2">
              <span>✓</span>
              <span>Acknowledged{alert.acknowledgedAt ? ` at ${new Date(alert.acknowledgedAt).toLocaleString()}` : ''} — teams notified.</span>
            </div>
          ) : (
            <button
              onClick={handleAcknowledge}
              disabled={ackPending}
              className="w-full rounded-lg bg-emerald-600 py-3 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-50"
            >
              {ackPending ? 'Acknowledging…' : 'Acknowledge & Dispatch Field Teams'}
            </button>
          )}
        </footer>
      </aside>
    </div>
  )
}

function generateTrendData(currentProb: number) {
  const now = Date.now()
  const hours = 72
  const interval = 3600000 // 1 hour
  const base = currentProb * 0.6
  const trend = Array.from({ length: hours + 1 }, (_, i) => {
    const t = now - (hours - i) * interval
    // M1: static base
    const m1 = base + (Math.random() - 0.5) * 0.05
    // M2: dynamic with some noise
    const m2 = Math.min(1, base + (i / hours) * 0.3 + (Math.random() - 0.5) * 0.1)
    // Current: blend
    const prob = Math.min(1, Math.max(0, m2 + (Math.random() - 0.5) * 0.05))
    return { time: new Date(t).toISOString(), probability: prob, m1, m2 }
  })
  return trend
}

export default AlertDetail