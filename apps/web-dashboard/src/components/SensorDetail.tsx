import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import type { SensorStation } from '@/types'
import { useMap } from '@/hooks/useMap'
import { useDismissable } from '@/hooks/useDismissable'
import { districtCenter } from '@/lib/districts'

interface Props {
  station: SensorStation | null
  onClose: () => void
}

export default function SensorDetail({ station, onClose }: Props) {
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const markerRef = useRef<maplibregl.Marker | null>(null)
  const c = districtCenter(station?.district)
  const { map } = useMap({ containerRef: mapContainerRef, center: [c.lng + 0.02, c.lat + 0.02], zoom: 12 })
  useDismissable(station !== null, onClose)
  const [history, setHistory] = useState<{ time: string; value: number }[]>([])

  useEffect(() => {
    if (!station || !mapContainerRef.current || !map) return
    const cc = districtCenter(station.district)
    if (markerRef.current) {
      markerRef.current.remove()
      markerRef.current = null
    }
    const el = document.createElement('div')
    el.style.cssText = `width:18px;height:18px;border-radius:50%;background:${station.status === 'online' ? '#3fb950' : station.status === 'maintenance' ? '#d29922' : '#f85149'};border:3px solid #0d1117`
    const marker = new maplibregl.Marker({ element: el })
      .setLngLat([cc.lng, cc.lat])
      .setPopup(new maplibregl.Popup({ offset: 12 }).setHTML(`<b>${station.code}</b><br/>${station.lastReading}`))
      .addTo(map)
    markerRef.current = marker
    return () => { markerRef.current?.remove(); markerRef.current = null }
  }, [station, map])

  // Generate mock 24h history
  useEffect(() => {
    if (!station) return
    const now = Date.now()
    const points = Array.from({ length: 48 }, (_, i) => {
      const t = now - (47 - i) * 1800000 // 30-min intervals
      const base = station.type === 'AWS' ? 20 : station.type === 'Tiltmeter' ? 0.2 : station.type === 'Piezometer' ? 5 : 100
      const noise = (Math.random() - 0.5) * (base * 0.3)
      return { time: new Date(t).toISOString(), value: Math.max(0, base + noise) }
    })
    setHistory(points)
  }, [station])

  if (!station) return null

  const statusStyle = {
    online: 'badge-online',
    maintenance: 'badge-maintenance',
    offline: 'badge-offline',
  }[station.status]

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="sensor-title" className="fixed inset-0 z-50 flex justify-end">
      <button aria-label="Close" onClick={onClose} className="flex-1 bg-slate-950/80" />
      <aside className="flex flex-col w-full max-w-2xl border-l border-slate-800 bg-slate-900 shadow-2xl overflow-hidden">
        <header className="flex items-start justify-between gap-4 border-b border-slate-800 p-5">
          <div className="flex items-center gap-3 min-w-0">
            <div className="grid h-10 w-10 place-items-center rounded-lg bg-emerald-500/15 text-lg" aria-hidden="true">◆</div>
<div>
                <div className="flex items-baseline gap-2">
                  <span className="font-mono font-semibold">{station.code}</span>
                  <span className={statusStyle}>{station.status}</span>
                </div>
                <p className="mt-1 text-sm text-slate-400">{station.type} · {station.district}</p>
              </div>
              <p id="sensor-title" className="mt-1 text-sm text-slate-400 font-medium">{station.code} · {station.district}</p>
          </div>
          <button onClick={onClose} className="flex-shrink-0 rounded-lg px-2 py-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-200">✕</button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5 space-y-5">
          {/* Map */}
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Location</h3>
            <div className="relative h-48 min-h-[192px] overflow-hidden rounded-xl border border-slate-800">
              <div ref={mapContainerRef} className="absolute inset-0" />
            </div>
          </section>

          {/* Key metrics */}
          <section>
            <div className="grid grid-cols-2 gap-3">
              <MetricCard label="Battery" value={`${station.battery}%`} tone={station.battery > 30 ? 'text-emerald-400' : 'text-red-400'} sub="last check 5 min ago" />
              <MetricCard label="Last Reading" value={station.lastReading} tone="text-sky-400" sub={station.type} />
              <MetricCard label="District" value={station.district} tone="text-slate-400" />
              <MetricCard label="Type" value={station.type} tone="text-slate-400" />
            </div>
          </section>

          {/* 24h History Sparkline */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Last 24h Readings</h3>
            <div className="h-48 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={history} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="sensorGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#58a6ff" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="#58a6ff" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                  <XAxis dataKey="time" tick={{ fill: '#8b949e', fontSize: 11 }} tickLine={false} axisLine={false} interval="preserveStartEnd" tickFormatter={t => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} />
                  <YAxis tick={{ fill: '#8b949e', fontSize: 11 }} tickLine={false} axisLine={false} width={50} />
                  <Tooltip contentStyle={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '8px', color: '#e6edf3' }} />
                  <Area type="monotone" dataKey="value" stroke="#58a6ff" strokeWidth={2} fillOpacity={1} fill="url(#sensorGradient)" />
                </AreaChart>
              </ResponsiveContainer>
              <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                <span>24h ago</span>
                <span>Now</span>
              </div>
            </div>
          </section>

          {/* Thresholds */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Thresholds & Alerts</h3>
            <div className="space-y-2">
              {getThresholds(station.type).map(t => (
                <div key={t.label} className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-900/50 px-3 py-2">
                  <div>
                    <div className="text-sm font-medium">{t.label}</div>
                    <div className="text-xs text-slate-500">{t.desc}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-mono ${t.value > (t.threshold ?? 0) ? 'text-red-400' : 'text-slate-400'}`}>{t.value} {t.unit}</span>
                    <span className={`h-2 w-2 rounded-full ${t.value > (t.threshold ?? 0) ? 'bg-red-500' : 'bg-emerald-500'}`} />
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Battery History (mock) */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Battery History (7d)</h3>
            <div className="h-32 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={generateBatteryHistory()} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="batteryGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3fb950" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="#3fb950" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                  <XAxis dataKey="day" tick={{ fill: '#8b949e', fontSize: 11 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                  <YAxis domain={[0, 100]} tick={{ fill: '#8b949e', fontSize: 11 }} tickLine={false} axisLine={false} width={30} />
                  <Tooltip contentStyle={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '8px', color: '#e6edf3' }} />
                  <Area type="monotone" dataKey="battery" stroke="#3fb950" strokeWidth={2} fillOpacity={1} fill="url(#batteryGradient)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </section>
        </div>

        <footer className="border-t border-slate-800 p-5">
          <div className="flex gap-2">
            <button className="btn-ghost flex-1">Calibrate</button>
            <button className="btn-ghost flex-1">Maintenance Log</button>
            <button className="btn-primary flex-1">Schedule Maintenance</button>
          </div>
        </footer>
      </aside>
    </div>
  )
}

function MetricCard({ label, value, tone, sub }: { label: string; value: string; tone: string; sub?: string }) {
  return (
    <div className="solid-card rounded-xl p-3">
      <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-bold ${tone}`}>{value}</div>
      {sub && <div className="mt-1 text-[11px] text-slate-500">{sub}</div>}
    </div>
  )
}

function getThresholds(type: string) {
  switch (type) {
    case 'AWS': return [
      { label: 'Rainfall Rate', value: 12.4, threshold: 50, unit: 'mm/h', desc: 'Flash flood trigger' },
      { label: 'Wind Speed', value: 8.2, threshold: 25, unit: 'm/s', desc: 'Landslide trigger' },
    ]
    case 'Tiltmeter': return [
      { label: 'Angular Rate', value: 0.18, threshold: 0.3, unit: '°/day', desc: 'Slope failure precursor' },
      { label: 'Cumulative Tilt', value: 1.2, threshold: 2.0, unit: '°', desc: 'Cumulative displacement' },
    ]
    case 'Piezometer': return [
      { label: 'Pore Pressure', value: 4.8, threshold: 8, unit: 'kPa', desc: 'Slope stability limit' },
      { label: 'Water Level', value: 2.1, threshold: 3.5, unit: 'm', desc: 'Saturation threshold' },
    ]
    case 'GNSS': return [
      { label: 'Horizontal Displacement', value: 4, threshold: 10, unit: 'mm', desc: 'Surface movement' },
      { label: 'Vertical Displacement', value: 1, threshold: 5, unit: 'mm', desc: 'Subsidence/uplift' },
    ]
    default: return []
  }
}

function generateBatteryHistory() {
  return Array.from({ length: 7 }, (_, i) => ({
    day: ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][i],
    battery: 100 - i * 2 - Math.random() * 3,
  }))
}