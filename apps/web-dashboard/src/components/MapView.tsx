import { useEffect, useRef, useState, useCallback } from 'react'
import type { KeyboardEvent } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import LottieLoader from '@/components/LottieLoader'
import { DISTRICT_COORDS, DEFAULT_CENTER } from '@/lib/districts'
import type { Alert, SensorStation } from '@/types'

/** Keyless, production-usable vector styles */
interface BaseLayer {
  id: string
  name: string
  styleSpec: string | maplibregl.StyleSpecification
}

const BASE_LAYERS: BaseLayer[] = [
  { id: 'streets', name: 'Streets', styleSpec: 'https://tiles.openfreemap.org/styles/liberty' },
  { id: 'light', name: 'Light', styleSpec: 'https://tiles.openfreemap.org/styles/positron' },
  { id: 'dark', name: 'Dark', styleSpec: 'https://tiles.openfreemap.org/styles/dark' },
  { id: 'terrain', name: 'Terrain', styleSpec: 'https://tiles.openfreemap.org/styles/bright' },
]

// Optional basemaps — keys inlined at build time via VITE_* env vars.
// NOTE: TomTom layer/ext combos are strict: basic|hybrid|labels → png, sat → jpg.
const VITE_ENV = (import.meta as unknown as { env?: Record<string, string> }).env ?? {}
const TOMTOM_KEY = VITE_ENV.VITE_TOMTOM_API_KEY
if (TOMTOM_KEY) {
  // NOTE: TomTom layer/ext combos are strict: basic|hybrid|labels → png, sat → jpg.
  const ttTiles = (layer: string, ext = 'png') =>
    [`https://api.tomtom.com/map/1/tile/${layer}/main/{z}/{x}/{y}.${ext}?key=${TOMTOM_KEY}`]
  BASE_LAYERS.unshift(
    { id: 'tt-basic', name: 'TomTom', styleSpec: {
        version: 8,
        sources: { tomtom: { type: 'raster', tiles: ttTiles('basic'), tileSize: 256, attribution: '© TomTom' } },
        layers: [{ id: 'tomtom-tiles', type: 'raster', source: 'tomtom' }],
      } },
  )
}

// MapTiler satellite/hybrid imagery (validated working key)
const MAPTILER_KEY = VITE_ENV.VITE_MAPTILER_API_KEY
if (MAPTILER_KEY) {
  BASE_LAYERS.unshift({
    id: 'mt-satellite',
    name: 'Satellite',
    styleSpec: `https://api.maptiler.com/maps/hybrid/style.json?key=${MAPTILER_KEY}`,
  })
}

const RISK_ZONES: { id: string; name: string; coords: number[][]; risk: number }[] = [
  { id: 'Z-07', name: 'Churachandpur Basin', coords: [[93.5, 24.1], [93.8, 24.1], [93.8, 24.3], [93.5, 24.3]], risk: 0.87 },
  { id: 'Z-03', name: 'Aizawl Ridge', coords: [[92.6, 23.6], [92.9, 23.6], [92.9, 23.8], [92.6, 23.8]], risk: 0.64 },
  { id: 'Z-11', name: 'Gangtok Valley', coords: [[88.5, 27.2], [88.8, 27.2], [88.8, 27.4], [88.5, 27.4]], risk: 0.58 },
  { id: 'Z-05', name: 'Shillong Plateau', coords: [[91.7, 25.4], [92.1, 25.4], [92.1, 25.7], [91.7, 25.7]], risk: 0.42 },
]

const ALERT_LAYERS = ['alert-cluster-count', 'alert-clusters', 'alert-unclustered']

// Legend severity dots (module-level constant — must not be created after an
// early return, which would violate the Rules of Hooks when using useMemo).
const LEGEND_DOTS = [
  { color: '#f85149', label: 'Evacuation' },
  { color: '#fc8d59', label: 'Warning' },
  { color: '#d29922', label: 'Watch' },
  { color: '#58a6ff', label: 'Advisory' },
]

interface MapViewProps {
  alerts?: Alert[]
  stations?: SensorStation[]
  loading?: boolean
  onAlertClick?: (a: Alert) => void
  onStationClick?: (s: SensorStation) => void
}

export default function MapView({
  alerts = [],
  stations = [],
  loading,
  onAlertClick,
  onStationClick,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const controlsRef = useRef<HTMLDivElement | null>(null)
  const stationMarkersRef = useRef<maplibregl.Marker[]>([])
  const appliedStyleRef = useRef<string>('')

  // Latest-value refs so map event callbacks never go stale
  const alertsRef = useRef(alerts)
  const stationsRef = useRef(stations)
  const clusteredRef = useRef(true)
  const showAlertsRef = useRef(true)
  const showStationsRef = useRef(true)
  const timeExtentRef = useRef<[number, number]>([0, 100])
  const onAlertClickRef = useRef(onAlertClick)
  const onStationClickRef = useRef(onStationClick)

  const [currentLayer, setCurrentLayer] = useState('streets')
  const [showRiskZones, setShowRiskZones] = useState(true)
  const [showStations, setShowStations] = useState(true)
  const [showAlerts, setShowAlerts] = useState(true)
  const [timeExtent, setTimeExtent] = useState<[number, number]>([0, 100])
  const [clustered, setClustered] = useState(true)
  const [mapReady, setMapReady] = useState(false)

  alertsRef.current = alerts
  stationsRef.current = stations
  clusteredRef.current = clustered
  showAlertsRef.current = showAlerts
  showStationsRef.current = showStations
  timeExtentRef.current = timeExtent
  onAlertClickRef.current = onAlertClick
  onStationClickRef.current = onStationClick

  const handleControlsKeyDown = useCallback((e: KeyboardEvent) => {
    const container = controlsRef.current
    if (!container) return
    const focusables = Array.from(container.querySelectorAll<HTMLElement>('button, input[type="checkbox"], input[type="range"]'))
    if (focusables.length === 0) return
    const active = document.activeElement as HTMLElement | null
    const idx = Math.max(0, focusables.indexOf(active as HTMLElement))

    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
      e.preventDefault()
      focusables[(idx + 1) % focusables.length]?.focus()
    }
    if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
      e.preventDefault()
      focusables[(idx - 1 + focusables.length) % focusables.length]?.focus()
    }
    if (e.key === 'Home') { e.preventDefault(); focusables[0]?.focus() }
    if (e.key === 'End') { e.preventDefault(); focusables[focusables.length - 1]?.focus() }
  }, [])

  function alertFeatures(): GeoJSON.FeatureCollection {
    const hoursBack = Math.round((timeExtentRef.current[1] / 100) * 72)
    const cutoff = hoursBack >= 72 ? 0 : Date.now() - hoursBack * 3_600_000
    return {
      type: 'FeatureCollection',
      features: alertsRef.current
        .filter(a => !cutoff || !a.issuedAt || Date.parse(a.issuedAt) >= cutoff)
        .map(a => {
          const c = DISTRICT_COORDS[a.district]
          if (!c) return null
          return {
            type: 'Feature',
            properties: {
              id: a.id,
              severity: a.severity,
              probability: a.probability,
              title: a.title,
              district: a.district,
            },
            geometry: { type: 'Point', coordinates: [c.lng, c.lat] },
          } as GeoJSON.Feature
        })
        .filter(Boolean) as GeoJSON.Feature[],
    }
  }

  /** Ensure alert layers exist for current clustering mode and push filtered data */
  function syncAlerts(map: maplibregl.Map) {
    if (!map.getSource('alerts')) {
      map.addSource('alerts', {
        type: 'geojson',
        data: alertFeatures(),
        cluster: clusteredRef.current,
        clusterMaxZoom: 12,
        clusterRadius: 50,
      })
    }
    if (map.getLayer('alert-unclustered')) {
      const alertsSource = map.getSource('alerts') as maplibregl.GeoJSONSource
      alertsSource.setData(alertFeatures())
      return
    }
    // Layers missing (first load or style swap) — (re)create them
    ALERT_LAYERS.forEach(id => { if (map.getLayer(id)) map.removeLayer(id) })
    if (map.getSource('alerts')) map.removeSource('alerts')
    map.addSource('alerts', { type: 'geojson', data: alertFeatures(), cluster: clusteredRef.current, clusterMaxZoom: 12, clusterRadius: 50 })

    if (clusteredRef.current) {
      map.addLayer({
        id: 'alert-clusters',
        type: 'circle',
        source: 'alerts',
        filter: ['has', 'point_count'],
        paint: {
          'circle-color': ['step', ['get', 'point_count'], '#58a6ff', 3, '#fc8d59', 6, '#f85149'],
          'circle-radius': ['step', ['get', 'point_count'], 18, 3, 24, 6, 30],
          'circle-stroke-width': 2,
          'circle-stroke-color': '#0d1117',
        },
        layout: { visibility: showAlertsRef.current ? 'visible' : 'none' },
      })
      map.addLayer({
        id: 'alert-cluster-count',
        type: 'symbol',
        source: 'alerts',
        filter: ['has', 'point_count'],
        layout: {
          'text-field': '{point_count_abbreviated}',
          'text-font': ['Noto Sans Regular'],
          'text-size': 12,
        },
        paint: { 'text-color': '#0d1117', 'text-halo-color': '#fff', 'text-halo-width': 1 },
      })
    }
    map.addLayer({
      id: 'alert-unclustered',
      type: 'circle',
      source: 'alerts',
      filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-color': ['match', ['get', 'severity'], 'evacuation', '#f85149', 'warning', '#fc8d59', 'watch', '#d29922', '#58a6ff'],
        'circle-radius': ['interpolate', ['linear'], ['get', 'probability'], 0, 10, 1, 28],
        'circle-stroke-width': 2,
        'circle-stroke-color': '#0d1117',
        'circle-opacity': 0.9,
      },
      layout: { visibility: showAlertsRef.current ? 'visible' : 'none' },
    })
  }

  function ensureRiskZones(map: maplibregl.Map) {
    if (map.getSource('risk-zones')) return
    map.addSource('risk-zones', {
      type: 'geojson',
      data: {
        type: 'FeatureCollection',
        features: RISK_ZONES.map(z => ({
          type: 'Feature',
          properties: { id: z.id, name: z.name, risk: z.risk },
          geometry: { type: 'Polygon', coordinates: [z.coords] },
        })),
      },
    })
    map.addLayer({
      id: 'risk-zones-fill',
      type: 'fill',
      source: 'risk-zones',
      paint: {
        'fill-color': ['interpolate', ['linear'], ['get', 'risk'], 0.2, '#58a6ff', 0.5, '#fc8d59', 0.8, '#f85149'],
        'fill-opacity': 0.35,
      },
      layout: { visibility: showRiskZones ? 'visible' : 'none' },
    })
    map.addLayer({
      id: 'risk-zones-border',
      type: 'line',
      source: 'risk-zones',
      paint: {
        'line-color': ['interpolate', ['linear'], ['get', 'risk'], 0.2, '#58a6ff', 0.5, '#fc8d59', 0.8, '#f85149'],
        'line-width': 2,
        'line-opacity': 0.8,
      },
      layout: { visibility: showRiskZones ? 'visible' : 'none' },
    })
  }

  function rebuildStationMarkers(map: maplibregl.Map) {
    stationMarkersRef.current.forEach(m => m.remove())
    stationMarkersRef.current = []
    if (!showStationsRef.current) return
    stationsRef.current.forEach((s, idx) => {
      const c = DISTRICT_COORDS[s.district]
      if (!c) return
      const el = document.createElement('button')
      el.type = 'button'
      el.title = `${s.code} · ${s.lastReading} — click for details`
      const isOnline = s.status === 'online'
      const baseColor = isOnline ? '#3fb950' : s.status === 'maintenance' ? '#d29922' : '#f85149'
      el.style.cssText = `
        width:12px;height:12px;border-radius:2px;
        background:${baseColor};
        border:1px solid #0d1117;
        cursor:pointer;padding:0;
        box-shadow:0 0 0 1px #0d1117, 0 0 6px ${baseColor}80;
        transform:scale(0.8);
        transition:transform 0.3s cubic-bezier(.2,.9,.2,1), box-shadow 0.3s ease;
      `
      if (isOnline) {
        el.style.animation = `pulse-ring 2s cubic-bezier(.4,0,.6,1) infinite`
      }
      el.addEventListener('click', ev => {
        ev.stopPropagation()
        onStationClickRef.current?.(s)
      })
      el.addEventListener('mouseenter', () => {
        el.style.transform = 'scale(1.3)'
        el.style.boxShadow = `0 0 0 2px #0d1117, 0 0 14px ${baseColor}aa`
      })
      el.addEventListener('mouseleave', () => {
        el.style.transform = 'scale(1)'
        el.style.boxShadow = `0 0 0 1px #0d1117, 0 0 6px ${baseColor}80`
      })
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([c.lng + 0.15, c.lat + 0.12])
        .addTo(map)
      // Staggered entrance
      requestAnimationFrame(() => {
        el.style.transitionDelay = `${idx * 60}ms`
        el.style.transform = 'scale(1)'
      })
      stationMarkersRef.current.push(marker)
    })
  }

  // Create the map exactly once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const initial = BASE_LAYERS.find(l => l.id === currentLayer) ?? BASE_LAYERS[0]
    appliedStyleRef.current = initial.id

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: initial.styleSpec,
      center: [DEFAULT_CENTER.lng, DEFAULT_CENTER.lat],
      zoom: 5.6,
      attributionControl: false,
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right')
    mapRef.current = map

    const onStyleReady = () => {
      ensureRiskZones(map)
      syncAlerts(map)
      rebuildStationMarkers(map)
      setMapReady(true)
    }
    map.on('load', onStyleReady)
    // Re-add overlays after base-style switches wipe them
    map.on('styledata', () => {
      if (map.isStyleLoaded()) onStyleReady()
    })

    // Interactions (delegated layer events survive style swaps)
    map.on('click', 'alert-unclustered', e => {
      const f = e.features?.[0]
      const id = f?.properties?.id as string | undefined
      if (!id) return
      const alert = alertsRef.current.find(a => a.id === id)
      if (alert) onAlertClickRef.current?.(alert)
    })
    map.on('click', 'alert-clusters', e => {
      const f = e.features?.[0]
      if (!f) return
      const source = map.getSource('alerts') as maplibregl.GeoJSONSource
      const clusterId = f.properties?.cluster_id as number
      void source.getClusterExpansionZoom(clusterId).then(zoom => {
        map.easeTo({
          center: (f.geometry as GeoJSON.Point).coordinates as [number, number],
          zoom: zoom + 0.5,
        })
      }).catch(() => {})
    })
    ;['alert-unclustered', 'alert-clusters'].forEach(layer => {
      map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer' })
      map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = '' })
    })

    return () => {
      map.remove()
      mapRef.current = null
      stationMarkersRef.current = []
      setMapReady(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Switch base layer via setStyle (no map teardown); overlays re-added by styledata
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const target = BASE_LAYERS.find(l => l.id === currentLayer)
    if (!target || appliedStyleRef.current === target.id) return
    appliedStyleRef.current = target.id
    map.setStyle(target.styleSpec)
  }, [currentLayer, mapReady])

  // Push alert data whenever it (or filters) change
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    syncAlerts(map)
    // syncAlerts closes over alertFeatures/filters; re-running on every render
    // would thrash the GeoJSON source, so we deliberately key on data inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alerts, clustered, timeExtent, mapReady])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const vis = showAlerts ? 'visible' : 'none'
    ALERT_LAYERS.forEach(id => {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis)
    })
  }, [showAlerts, mapReady])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const vis = showRiskZones ? 'visible' : 'none'
    if (map.getLayer('risk-zones-fill')) map.setLayoutProperty('risk-zones-fill', 'visibility', vis)
    if (map.getLayer('risk-zones-border')) map.setLayoutProperty('risk-zones-border', 'visibility', vis)
  }, [showRiskZones, mapReady])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    rebuildStationMarkers(map)
  }, [stations, showStations, mapReady])

  if (loading) {
    return (
      <div className="relative h-full min-h-[560px] overflow-hidden rounded-xl solid-card flex items-center justify-center">
        <div className="flex flex-col items-center gap-4 text-slate-500">
          <LottieLoader src="/animations/map-loader.json" className="h-20 w-20" />
          <span className="text-sm">Loading map tiles…</span>
        </div>
      </div>
    )
  }

  return (
    <div className="relative h-full min-h-[560px] overflow-hidden rounded-xl solid-card">
      <div ref={containerRef} className="absolute inset-0" />

      {/* Layer controls */}
      <div className="pointer-events-none absolute left-3 top-3 z-10 flex flex-col gap-2 max-h-[calc(100%-24px)] overflow-y-auto scrollbar-hide" ref={controlsRef} onKeyDown={handleControlsKeyDown}>
        <div className="pointer-events-auto solid-panel rounded-xl p-2 shadow-xl" role="toolbar" aria-label="Map base layers">
          <div className="mb-2 px-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Base Layer</div>
          <div className="flex flex-col gap-1">
            {BASE_LAYERS.map(l => (
              <button
                key={l.id}
                onClick={() => setCurrentLayer(l.id)}
                className={`w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-left transition-all duration-200 focus-visible:ring-2 focus-visible:ring-cyan-500/30 ${
                  currentLayer === l.id
                    ? 'bg-cyan-500/15 text-cyan-200 font-medium'
                    : 'text-slate-300 hover:bg-white/5'
                }`}
                aria-pressed={currentLayer === l.id}
              >
                <span className={`h-2 w-2 shrink-0 rounded-full transition-colors ${currentLayer === l.id ? 'bg-cyan-400' : 'bg-transparent border border-slate-600'}`} />
                {l.name}
              </button>
            ))}
          </div>
        </div>

        <div className="pointer-events-auto solid-panel rounded-xl p-2 shadow-xl" role="toolbar" aria-label="Map overlays and options">
          <div className="mb-2 px-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Overlays</div>
          <div className="space-y-1.5">
            {[
              { key: 'riskZones', label: 'Risk Zones', checked: showRiskZones, onChange: (e: React.ChangeEvent<HTMLInputElement>) => setShowRiskZones(e.target.checked) },
              { key: 'stations', label: 'Stations', checked: showStations, onChange: (e: React.ChangeEvent<HTMLInputElement>) => setShowStations(e.target.checked) },
              { key: 'alerts', label: 'Alerts', checked: showAlerts, onChange: (e: React.ChangeEvent<HTMLInputElement>) => setShowAlerts(e.target.checked) },
              { key: 'clustered', label: 'Cluster Alerts', checked: clustered, onChange: (e: React.ChangeEvent<HTMLInputElement>) => setClustered(e.target.checked) },
            ].map(({ key, label, checked, onChange }) => (
              <label key={key} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-all duration-200 hover:bg-white/5 cursor-pointer has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-cyan-500/30">
                <input aria-label={label} type="checkbox" checked={checked} onChange={onChange} className="h-4 w-4 rounded border-slate-600 bg-slate-800/50 accent-cyan-500 transition" />
                <span className="text-slate-200">{label}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="pointer-events-auto solid-panel rounded-xl p-2 shadow-xl w-44">
          <div className="mb-2 px-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Time Window</div>
          <input
            type="range"
            min={0}
            max={100}
            value={timeExtent[1]}
            onChange={e => setTimeExtent([0, Number(e.target.value)])}
            className="w-full h-1.5 appearance-none bg-slate-800/50 rounded-full accent-cyan-500"
            aria-label="Time window in hours"
            aria-valuetext={`${Math.round((timeExtent[1] / 100) * 72)} hours back`}
          />
          <div className="mt-1 flex justify-between text-[11px] text-slate-500">
            <span>Now</span>
            <span>{Math.round((timeExtent[1] / 100) * 72)}h back</span>
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="pointer-events-none absolute right-3 bottom-3 hidden sm:block">
        <div className="pointer-events-auto solid-panel rounded-xl p-3 shadow-xl animate-slide-up">
          <div className="mb-2 font-semibold uppercase tracking-wider text-slate-400">Legend</div>
          <div className="space-y-1.5 text-xs">
            {LEGEND_DOTS.map((d, i) => (
              <div key={d.label} className="flex items-center gap-2 stagger-${i + 1} animate-slide-up" style={{ animationFillMode: 'both' }}>
                <span className={`h-3 w-3 rounded-full animate-pulse-soft`} style={{ backgroundColor: d.color, animationDelay: `${i * 150}ms` }} />
                <span className="text-slate-300">{d.label}</span>
              </div>
            ))}
            <div className="mt-2 pt-2 border-t border-slate-800/50 flex items-center gap-2">
              <span className="h-2 w-2 rounded-sm bg-emerald-500 animate-pulse-soft" style={{ animationDelay: '0ms' }} />
              <span className="text-slate-300">Sensor online</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-sm bg-yellow-400 animate-pulse-soft" style={{ animationDelay: '100ms' }} />
              <span className="text-slate-300">Maintenance</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-sm bg-red-500 animate-pulse-soft" style={{ animationDelay: '200ms' }} />
              <span className="text-slate-300">Offline · clickable</span>
            </div>
          </div>
        </div>
      </div>

      <div className="pointer-events-none absolute left-3 bottom-3">
        <div className="pointer-events-auto solid-panel rounded-md px-2 py-1 text-[11px] text-slate-400">
          {alerts.length} alert{alerts.length !== 1 ? 's' : ''} · click points for details ·
          {[MAPTILER_KEY && 'MapTiler', TOMTOM_KEY && 'TomTom', 'OpenFreeMap'].filter(Boolean).join(' · ')}
        </div>
      </div>
    </div>
  )
}
