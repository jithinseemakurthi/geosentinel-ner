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
  reportsToday: number
  live: boolean
  onAlertClick: (a: Alert) => void
  loading?: boolean
}

const DEMO_STATIONS = [
  { id: 's1', code: 'AWS-MNP-01', type: 'AWS', district: 'Imphal West', status: 'online', battery: 96, lastReading: '38.2 mm/h rainfall' },
  { id: 's2', code: 'TILT-AIZ-14', type: 'Tiltmeter', district: 'Aizawl', status: 'online', battery: 88, lastReading: '0.42 deg/day' },
  { id: 's3', code: 'PZO-GGT-07', type: 'Piezometer', district: 'Gangtok', status: 'online', battery: 91, lastReading: '6.4 kPa' },
  { id: 's4', code: 'AWS-SHG-03', type: 'AWS', district: 'East Khasi Hills', status: 'maintenance', battery: 64, lastReading: 'no data' },
  { id: 's5', code: 'GNSS-JRT-09', type: 'GNSS', district: 'Jaintia Hills', status: 'offline', battery: 12, lastReading: 'last seen 2d ago' },
]

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
    <article className="solid-card rounded-xl overflow-hidden transition-all duration-300 hover:shadow-lg hover:border-cyan-500/20" role="listitem">
      <button onClick={onClick} className="w-full flex items-start gap-4 p-4 text-left transition ripple" aria-expanded={isExpanded}>
        <span className="mt-0.5 flex-shrink-0 text-lg animate-float" aria-hidden="true">{icon}</span>
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

export function Overview({ alerts, stations, reportsToday, live, onAlertClick, loading }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)

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

      {/* Alert Feed */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Alert Feed</h2>
          {!live && <span className="flex items-center gap-1 text-[11px] text-amber-400 animate-pulse-soft">● demo mode</span>}
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

      {/* Sensor Network */}
      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">Sensor Network</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {stations.online === 0 && stations.total === 0 ? (
            <EmptyState
              icon="◆"
              title="No sensor stations configured"
              description="Add stations via the admin API to see live readings here."
            />
          ) : (
            DEMO_STATIONS.map((s, idx) => (
              <SensorCard key={s.id} station={{ ...s, icon: '' }} index={idx} />
            ))
          )}
        </div>
      </div>
    </div>
  )
}

export default Overview