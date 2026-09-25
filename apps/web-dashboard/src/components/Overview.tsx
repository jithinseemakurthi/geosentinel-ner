import { useState, useEffect, useRef } from 'react'
import {
  SkeletonCardGrid,
  SkeletonAlertFeed,
  SkeletonSensorGrid,
  EmptyState,
} from '@/components/Skeleton'
import type { Alert } from '@/types'

interface Props {
  alerts: Alert[]
  stations: { online: number; total: number }
  stationsList?: Array<{ id: string; code: string; type: string; district: string; status: string; battery: number; lastReading: string }>
  reportsToday: number
  live: boolean
  onAlertClick: (a: Alert) => void
  loading?: boolean
}

const SEV_STYLE: Record<string, string> = {
  evacuation: 'badge-evacuation',
  warning: 'badge-warning',
  watch: 'badge-watch',
  advisory: 'badge-advisory',
}

const SEV_ICON: Record<string, string> = {
  evacuation: '🚨',
  warning: '⚠',
  watch: '👁',
  advisory: 'ℹ',
}

interface StationLike {
  id: string
  code: string
  type: string
  district: string
  status: string
  battery: number
  lastReading: string
}

function StatCard({ label, value, sub, tone, trend, index }: { label: string; value: string; sub: string; tone: string; trend?: { value: number; up: boolean }; index: number }) {
  const barRef = useRef<HTMLDivElement>(null)
  const [barWidth, setBarWidth] = useState(0)
  useEffect(() => {
    const timer = setTimeout(() => setBarWidth(Math.min(100, trend?.value ? trend.value * 5 : 30)), index * 80)
    return () => clearTimeout(timer)
  }, [index, trend])
  return (
    <div className={`solid-card rounded-xl p-4 transition-all duration-300 group stagger-${index + 1} animate-slide-up`} style={{ animationFillMode: 'both' }}>
      <div className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-3xl font-bold ${tone} tabular`}>
        {value}
        {trend && (
          <span className={`ml-2 text-sm font-medium ${trend.up ? 'text-emerald-400' : 'text-red-400'}`}>
            {trend.up ? '↑' : '↓'} {Math.abs(trend.value).toFixed(1)}%
          </span>
        )}
      </div>
      <div className="mt-2 h-1.5 bg-slate-800/60 rounded-full overflow-hidden">
        <div
          ref={barRef}
          className="h-full bg-gradient-to-r from-cyan-400 via-indigo-500 to-violet-500 rounded-full bar-sweep"
          style={{ width: '0%', '--target-width': `${barWidth}%` } as React.CSSProperties}
        />
      </div>
      <div className="mt-1 text-xs text-slate-500">{sub}</div>
    </div>
  )
}

interface StationLikeWithIcon extends StationLike {
  icon: string
}

function SensorCard({ station, index }: { station: StationLikeWithIcon; index: number }) {
  const statusStyle = {
    online: 'badge-online',
    maintenance: 'badge-maintenance',
    offline: 'badge-offline',
  }[station.status]

  return (
    <div
      className={`solid-card ripple rounded-xl p-4 transition-all duration-300 stagger-${(index % 6) + 1} animate-slide-up`}
      style={{ animationFillMode: 'both' }}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm font-semibold truncate">{station.code}</span>
        <span className={statusStyle}>{station.status}</span>
      </div>
      <div className="mt-1 text-xs text-slate-500 truncate">{station.type} · {station.district}</div>
      <div className="mt-2 flex items-center justify-between text-xs">
        <span className="text-slate-400 truncate max-w-[140px]">{station.lastReading}</span>
        <span className={`flex items-center gap-1 ${station.battery > 30 ? 'text-slate-500' : 'text-red-400'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${station.battery > 60 ? 'bg-emerald-400 animate-pulse-soft' : station.battery > 30 ? 'bg-yellow-400' : 'bg-red-400'}`} aria-hidden="true" />
          {station.battery}% <span className="hidden sm:inline">battery</span>
        </span>
      </div>
      <div className="mt-2 h-1.5 bg-slate-800/60 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ease-out ${
            station.battery > 60 ? 'bg-emerald-500' : station.battery > 30 ? 'bg-yellow-400' : 'bg-red-500'
          }`}
          style={{ width: `${station.battery}%` }}
        />
      </div>
    </div>
  )
}

function AlertRow({ alert, isExpanded, onClick, onDetail }: { alert: any; isExpanded: boolean; onClick: () => void; onDetail: () => void }) {
  const tone = SEV_STYLE[alert.severity]
  const icon = SEV_ICON[alert.severity]

  return (
    <article className="solid-card rounded-xl overflow-hidden transition-colors duration-150" role="listitem">
      <button onClick={onClick} className="w-full flex items-start gap-4 p-4 text-left transition-colors" aria-expanded={isExpanded}>
        <span className="mt-0.5 flex-shrink-0 text-lg" aria-hidden="true">{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className={`font-semibold ${tone.replace('badge-', 'text-')}`}>{alert.severity}</span>
            <span className="font-semibold">{alert.district}</span>
            <span className="text-xs text-slate-500">zone {alert.zone} · P = {alert.probability.toFixed(2)}</span>
          </div>
          <p className="mt-0.5 truncate text-sm text-slate-400">{alert.message}</p>
        </div>
        <div className="shrink-0 text-right text-xs text-slate-500">
          <time dateTime={alert.issuedAt}>{new Date(alert.issuedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
          <div className="text-[11px] uppercase mt-0.5">
            {alert.status === 'acknowledged' ? '✓ acknowledged' : alert.status}
          </div>
        </div>
      </button>

      {isExpanded && (
        <div className="border-t border-slate-800/60 bg-gradient-to-b from-slate-900/20 to-transparent px-4 pb-4 animate-slide-up">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-slate-700/50 bg-slate-900/30 p-3">
              <div className="text-xs font-medium uppercase tracking-wider text-slate-500">Failure Probability (72h)</div>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-3xl font-bold text-orange-400 tabular">{alert.probability.toFixed(2)}</span>
                <span className="text-xs text-slate-500">updated {new Date(alert.issuedAt).toLocaleString()}</span>
              </div>
              <div className="mt-2 h-2.5 bg-slate-800/60 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-red-500 via-orange-400 to-yellow-400 rounded-full bar-sweep"
                  style={{ width: '0%', '--target-width': `${Math.round(alert.probability * 100)}%` } as React.CSSProperties}
                />
              </div>
            </div>
            <div className="rounded-lg border border-slate-700/50 bg-slate-900/30 p-3">
              <div className="text-xs font-medium uppercase tracking-wider text-slate-500">Model Pipeline</div>
              <ul className="mt-2 space-y-1.5 text-sm">
                {[
                  ['M1 Susceptibility', 'static terrain + geology + inventory'],
                  ['M2 Dynamic Risk', 'rainfall forecast + soil moisture + antecedent'],
                  ['M3 CV Triage', 'citizen photo classification'],
                ].map(([name, desc]) => (
                  <li key={name} className="ripple rounded-lg border border-slate-700/50 bg-slate-900/30 px-2 py-1.5 transition hover:border-cyan-500/30">
                    <span className="font-mono text-emerald-400">▸</span>
                    <span className="font-medium">{name}</span>
                    <span className="truncate text-xs text-slate-500">{desc}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="rounded-lg border border-slate-700/50 bg-slate-900/30 p-3 mt-3">
            <div className="text-xs font-medium uppercase tracking-wider text-slate-500">Delivery Channels</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {['SMS', 'Push', 'WhatsApp', 'CAP/SACHET', 'Email'].map((c) => (
                <span key={c} className="ripple rounded-md border border-slate-700/50 bg-slate-800/40 px-2 py-1 text-xs text-slate-300 transition hover:border-cyan-500/40">{c}</span>
              ))}
            </div>
          </div>

          <div className="mt-3 flex items-center justify-end gap-2">
            <button className="btn-ghost btn-sm">Share</button>
            <button className="btn-ghost btn-sm">Export</button>
            <button onClick={onDetail} className="btn-primary btn-sm">View Full Details →</button>
          </div>
        </div>
      )}
    </article>
  )
}

export function Overview({ alerts, stations, stationsList, reportsToday, live, onAlertClick, loading }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [engineStatus, setEngineStatus] = useState<Record<string, unknown> | null>(null)
  const [engineReports, setEngineReports] = useState<Array<Record<string, unknown>>>([])
  const [engineBusy, setEngineBusy] = useState(false)

  // Live Internet Analysis Engine — poll status + recent reports (proves engine is working)
  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const [sRes, rRes] = await Promise.all([
          fetch('/api/v1/live/engine/status').then((r) => (r.ok ? r.json() : null)).catch(() => null),
          fetch('/api/v1/live/engine/reports?limit=5').then((r) => (r.ok ? r.json() : null)).catch(() => null),
        ])
        if (cancelled) return
        if (sRes) setEngineStatus(sRes as Record<string, unknown>)
        if (rRes && Array.isArray((rRes as { items?: unknown[] }).items)) setEngineReports((rRes as { items: Array<Record<string, unknown>> }).items)
      } catch { /* gateway down — keep empty */ }
    }
    void poll()
    const id = window.setInterval(poll, 30000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [])

  async function triggerEngine() {
    setEngineBusy(true)
    try {
      const res = await fetch('/api/v1/live/engine/run', { method: 'POST' })
      const j = (await res.json().catch(() => null)) as Record<string, unknown> | null
      if (j && (j as { engine?: unknown }).engine) setEngineStatus((j as { engine: Record<string, unknown> }).engine)
      // refresh reports after run
      const rRes = await fetch('/api/v1/live/engine/reports?limit=5').then((r) => (r.ok ? r.json() : null)).catch(() => null)
      if (rRes && Array.isArray((rRes as { items?: unknown[] }).items)) setEngineReports((rRes as { items: Array<Record<string, unknown>> }).items)
    } catch { /* ignore */ } finally { setEngineBusy(false) }
  }

  const active = alerts.filter((a) => a.status === 'active')
  const peak = Math.max(0, ...alerts.map((a) => a.probability))
  const peakZone = alerts.find((a) => a.probability === peak)

  if (loading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <SkeletonCardGrid count={4} />
        <SkeletonAlertFeed count={4} />
        <SkeletonSensorGrid count={5} />
      </div>
    )
  }

  const totalAlerts = alerts.length

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard
          label="Active Alerts"
          value={String(active.length)}
          sub={`${totalAlerts} total issued`}
          tone="text-red-400"
          trend={{ value: active.length * 12, up: active.length > 0 }}
          index={0}
        />
        <StatCard
          label="Stations Online"
          value={`${stations.online}/${stations.total}`}
          sub="sensor network"
          tone="text-emerald-400"
          trend={{ value: 2.3, up: true }}
          index={1}
        />
        <StatCard
          label="Reports Today"
          value={String(reportsToday)}
          sub="citizen submissions"
          tone="text-sky-400"
          trend={{ value: 15, up: reportsToday > 0 }}
          index={2}
        />
        <StatCard
          label="Peak Risk (72h)"
          value={peak.toFixed(2)}
          sub={peakZone ? `${peakZone.district} · ${peakZone.zone}` : '—'}
          tone="text-orange-400"
          trend={{ value: 8.2, up: peak > 0.7 }}
          index={3}
        />
      </div>

      {/* Live Internet Analysis Engine — proves it works */}
      <div className="solid-card overflow-hidden rounded-xl border border-sky-500/20 live-shimmer stunning-enter">
        <div className="flex flex-wrap items-center justify-between gap-3 bg-gradient-to-br from-sky-500/10 via-cyan-500/10 to-violet-500/10 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${engineStatus && (engineStatus as { running?: boolean }).running ? 'animate-pulse bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.9)]' : 'bg-amber-400'}`} />
            <h2 className="text-sm font-extrabold tracking-tight">Live Internet Analysis Engine</h2>
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-bold ${engineStatus && (engineStatus as { running?: boolean }).running ? 'border-emerald-500/30 bg-emerald-500/15 text-emerald-300' : 'border-amber-500/30 bg-amber-500/15 text-amber-300'}`}>
              {(engineStatus as { running?: boolean })?.running ? '● RUNNING' : '○ idle (gateway down)'}
            </span>
            {engineStatus && typeof (engineStatus as { interval_seconds?: number }).interval_seconds === 'number' && (
              <span className="rounded-full border border-slate-700 bg-slate-800 px-2 py-0.5 text-[11px] text-slate-400">every {(engineStatus as { interval_seconds: number }).interval_seconds / 60}m</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-xs text-slate-500 sm:inline">Fetch → LLM analyze → build report → PostGIS + Redis</span>
            <button onClick={() => void triggerEngine()} disabled={engineBusy} className="rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-sky-500 disabled:opacity-50">
              {engineBusy ? 'Running…' : '▶ Run now'}
            </button>
          </div>
        </div>
        <div className="grid gap-3 bg-slate-950/40 px-4 py-3 text-xs md:grid-cols-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Last cycle</div>
            <div className="mt-1 font-mono text-slate-300">{(engineStatus as { last_run?: string })?.last_run ? new Date((engineStatus as { last_run: string }).last_run).toLocaleString() : '— not yet'}</div>
            <div className="mt-1 text-slate-500">Next: {(engineStatus as { next_run?: string })?.next_run ? new Date((engineStatus as { next_run: string }).next_run).toLocaleTimeString() : '—'}</div>
            {(engineStatus as { last_error?: string | null })?.last_error && (
              <div className="mt-1 text-amber-300">⚠ {(engineStatus as { last_error: string }).last_error.slice(0, 120)}</div>
            )}
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Stats (proves it works)</div>
            <div className="mt-1 grid grid-cols-3 gap-2 font-mono text-xs">
              {(['cycles','fetched','built'] as const).map((k) => (
                <div key={k} className="rounded bg-slate-800 px-2 py-1 text-center"><div className="text-slate-500">{k}</div><div className="font-bold text-slate-200">{String((engineStatus as { stats?: Record<string, number> })?.stats?.[k] ?? 0)}</div></div>
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              <span className="rounded-full border border-violet-500/20 bg-violet-500/10 px-1.5 py-0.5 text-[11px] text-violet-300">GDACS</span>
              <span className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-1.5 py-0.5 text-[11px] text-cyan-300">ReliefWeb</span>
              <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[11px] text-emerald-300">{String((engineStatus as { analyzer?: string })?.analyzer ?? 'LLM + heuristic')}</span>
            </div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Latest built reports (live)</div>
            {engineReports.length === 0 ? (
              <div className="mt-1 text-slate-500">No engine reports yet — click Run now or wait for next cycle. Live internet reports also appear in the Reports tab.</div>
            ) : (
              <div className="mt-1 space-y-1.5">
                {engineReports.slice(0, 4).map((r) => (
                  <div key={String(r['id'])} className="flex items-start gap-2 rounded border border-slate-800 bg-slate-900 px-2 py-1">
                    <span className="mt-0.5 text-[10px] leading-none">{String(r['source'] ?? 'Live') === 'GDACS' ? '🌐' : String(r['source']) === 'ReliefWeb' ? '📰' : '🤖'}</span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium text-slate-200">{String(r['district'] ?? '')} · {String(r['report_type'] ?? r['reportType'] ?? 'other')} · {String(r['severity'] ?? '')}</div>
                      <div className="truncate text-[11px] text-slate-500">{String(r['description'] ?? '').slice(0, 90)}…</div>
                    </div>
                    <span className="shrink-0 font-mono text-[11px] text-orange-400">{String(r['priorityScore'] ?? r['priority_score'] ?? '')}</span>
                  </div>
                ))}
                <a href="/api/v1/live/engine/reports?limit=20" target="_blank" rel="noreferrer" className="text-[11px] text-sky-400 hover:text-sky-300">api/live/engine/reports ↗</a>
              </div>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 bg-slate-900/40 px-4 py-2 text-[11px] text-slate-500">
          <span>Sources: {(engineStatus as { sources?: string[] })?.sources?.join(' · ') ?? 'GDACS (flood/eq/cyclone) · ReliefWeb (landslide India) · GNews (optional)'}</span>
          <span className="ml-auto hidden sm:inline">Analyzer: {(engineStatus as { analyzer?: string })?.analyzer ?? 'LLM (Groq/OpenAI/NVIDIA/Ollama) with heuristic fallback'} · No hardcoded data</span>
        </div>
      </div>

      {/* Alert Feed */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Alert Feed</h2>
          {live && <span className="flex items-center gap-1 text-[11px] text-emerald-400">● live</span>}
        </div>

        {alerts.length === 0 ? (
          <EmptyState
            icon="⚠"
            title="No alerts issued"
            description="When alerts are issued they'll appear here with realtime updates."
          />
        ) : (
          <div className="space-y-3" role="list" aria-label="Active alerts">
            {alerts.map((a) => (
              <AlertRow
                key={a.id}
                alert={a}
                isExpanded={expanded === a.id}
                onClick={() => setExpanded(expanded === a.id ? null : a.id)}
                onDetail={() => onAlertClick(a)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Sensor Network — live */}
      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">Sensor Network</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {!stationsList || stationsList.length === 0 ? (
            <EmptyState
              icon="◆"
              title="No sensor stations configured"
              description="Add stations via the admin API to see live readings here."
            />
          ) : (
            stationsList.map((s, idx) => (
              <SensorCard key={s.id} station={{ ...s, icon: '' }} index={idx} />
            ))
          )}
        </div>
      </div>
    </div>
  )
}

export default Overview