import { useEffect, useState } from 'react'
import { fetchLiveWeather, fetchImdNowcast } from '@/services/api'

/**
 * All 8 NER state capitals with precise coordinates.
 * `imdQuery` maps each capital to its IMD district name (substring match,
 * case-insensitive) since capitals are cities, not districts.
 */
const NER_CAPITALS = [
  { id: 'itanagar', name: 'Itanagar', state: 'Arunachal Pradesh', lat: 27.0844, lon: 93.6053, imdQuery: 'papum pare' },
  { id: 'dispur', name: 'Dispur', state: 'Assam', lat: 26.1433, lon: 91.7898, imdQuery: 'kamrup' },
  { id: 'imphal', name: 'Imphal', state: 'Manipur', lat: 24.8170, lon: 93.9368, imdQuery: 'imphal west' },
  { id: 'shillong', name: 'Shillong', state: 'Meghalaya', lat: 25.5788, lon: 91.8933, imdQuery: 'east khasi hills' },
  { id: 'aizawl', name: 'Aizawl', state: 'Mizoram', lat: 23.7271, lon: 92.7176, imdQuery: 'aizawl' },
  { id: 'kohima', name: 'Kohima', state: 'Nagaland', lat: 25.6751, lon: 94.1086, imdQuery: 'kohima' },
  { id: 'gangtok', name: 'Gangtok', state: 'Sikkim', lat: 27.3389, lon: 88.6065, imdQuery: 'gangtok' },
  { id: 'agartala', name: 'Agartala', state: 'Tripura', lat: 23.8315, lon: 91.2868, imdQuery: 'west tripura' },
]

interface CapitalData {
  id: string
  name: string
  state: string
  temp: number | null
  humidity: number | null
  observedRain: number | null
  forecastRain: number | null
  weatherSource: string | null
  imdAlerts: number | null
  imdColor: number | null
  imdMessage: string | null
}

function imdTone(alerts: number | null): string {
  if (alerts == null || alerts <= 0) return 'text-emerald-400'
  if (alerts >= 9) return 'text-red-400'
  if (alerts >= 5) return 'text-orange-400'
  return 'text-yellow-400'
}

export function CapitalsPanel() {
  const [data, setData] = useState<Record<string, CapitalData>>({})
  const [loadedOnce, setLoadedOnce] = useState(false)

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      const entries = await Promise.all(
        NER_CAPITALS.map(async (cap) => {
          const [w, n] = await Promise.all([
            fetchLiveWeather(cap.name),
            fetchImdNowcast(cap.imdQuery),
          ])
          const row: CapitalData = {
            id: cap.id,
            name: cap.name,
            state: cap.state,
            temp: w?.temperature_c ?? null,
            humidity: w?.humidity_pct ?? null,
            observedRain: w?.observed_rainfall_24h_mm ?? null,
            forecastRain: w?.forecast_rainfall_next_24h_mm ?? null,
            weatherSource: w?.source ?? null,
            imdAlerts: n?.alerts_total ?? null,
            imdColor: typeof n?.Color === 'number' ? n.Color : null,
            imdMessage: n?.message || n?.impact || '',
          }
          return [cap.id, row] as const
        }),
      )
      if (!cancelled) {
        setData(Object.fromEntries(entries))
        setLoadedOnce(true)
      }
    }
    void poll()
    const id = setInterval(poll, 60_000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return (
    <div className="space-y-4">
      {/* Summary strip */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-md border border-slate-800 bg-slate-900/60 px-2.5 py-1 font-medium text-slate-300">
          {NER_CAPITALS.length} state capitals
        </span>
        {loadedOnce && (
          <span className="flex items-center gap-1.5 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 font-medium text-emerald-300">
            <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" aria-hidden="true" />
            live · Open-Meteo + IMD nowcast · updates 60s
          </span>
        )}
      </div>

      {/* Capitals grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {NER_CAPITALS.map((cap) => {
          const c = data[cap.id]
          const loading = !c
          const hasWeather = c?.temp != null
          const alertLevel = c?.imdAlerts ?? null
          return (
            <div
              key={cap.id}
              className="solid-card rounded-xl p-4 transition hover:border-emerald-500/40 hover:bg-slate-800/40"
              aria-label={`Capital ${cap.name}, ${cap.state}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-emerald-500/15 text-base"
                    aria-hidden="true"
                  >
                    🏛
                  </span>
                  <div className="min-w-0">
                    <div className="truncate font-mono text-sm font-semibold">{cap.name}</div>
                    <div className="truncate text-[11px] text-slate-500">{cap.state}</div>
                  </div>
                </div>
                {!loading && (
                  <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${alertLevel && alertLevel > 0 ? 'border-orange-500/40 bg-orange-500/10 text-orange-400' : 'border-slate-700 bg-slate-800/60 text-slate-400'}`}>
                    {alertLevel != null && alertLevel > 0 ? `${alertLevel} flags` : 'no nowcast'}
                  </span>
                )}
              </div>

              {loading ? (
                <div className="mt-3 text-xs text-slate-500">connecting to live feeds…</div>
              ) : hasWeather ? (
                <>
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <Stat label="Temp" value={c.temp != null ? `${Math.round(c.temp)}°C` : '—'} tone="text-emerald-400" />
                    <Stat label="Rain 24h" value={c.observedRain != null ? `${c.observedRain.toFixed(1)}mm` : '—'} tone="text-sky-400" />
                    <Stat
                      label="Next 24h"
                      value={c.forecastRain != null ? `${c.forecastRain.toFixed(1)}mm` : '—'}
                      tone={(c.forecastRain ?? 0) >= 10 ? 'text-orange-400' : 'text-slate-200'}
                    />
                    <Stat label="Humidity" value={c.humidity != null ? `${Math.round(c.humidity)}%` : '—'} tone="text-slate-200" />
                  </div>
                  <div className="mt-2 flex items-center gap-1.5 text-[10px] text-emerald-400">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" aria-hidden="true" />
                    live · {c.weatherSource ?? 'open-meteo'}
                  </div>
                </>
              ) : (
                <div className="mt-3 text-xs text-amber-400/80">weather feed unavailable for this district</div>
              )}

              {c?.imdMessage ? (
                <div className={`mt-2 border-t border-slate-800 pt-2 text-[11px] leading-snug ${imdTone(c.imdAlerts)}`}>
                  IMD: {c.imdMessage.slice(0, 120)}
                </div>
              ) : (
                <div className="mt-2 border-t border-slate-800 pt-2 text-[10px] text-slate-600">No active IMD nowcast</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div>
      <div className="text-[9px] font-medium uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-0.5 font-mono text-sm font-bold ${tone}`}>{value}</div>
    </div>
  )
}

export default CapitalsPanel
