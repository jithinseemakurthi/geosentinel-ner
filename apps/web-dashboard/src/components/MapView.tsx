import { useEffect, useRef, useState, useCallback } from 'react'
import type { KeyboardEvent } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import LottieLoader from '@/components/LottieLoader'
import { DISTRICT_COORDS, DEFAULT_CENTER } from '@/lib/districts'
import type { Alert, CitizenReport, SensorStation } from '@/types'

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

/** Risk zones are derived live from active alerts — no hardcoded demo polygons */
function liveRiskZones(alerts: Alert[]): { id: string; name: string; coords: number[][]; risk: number }[] {
  if (!alerts.length) return []
  const byDistrict = new Map<string, { count: number; sum: number }>()
  for (const a of alerts) {
    const d = a.district || '—'
    const cur = byDistrict.get(d) ?? { count: 0, sum: 0 }
    cur.count += 1
    cur.sum += a.probability ?? 0.5
    byDistrict.set(d, cur)
  }
  return Array.from(byDistrict.entries()).map(([district, v], i) => {
    const c = DISTRICT_COORDS[district]
    const risk = Math.min(0.95, v.sum / v.count)
    // Create a small bbox around district centre for visual overlay
    if (c) {
      const d = 0.18
      return { id: `live-${i}-${district}`, name: district, coords: [[c.lng - d, c.lat - d], [c.lng + d, c.lat - d], [c.lng + d, c.lat + d], [c.lng - d, c.lat + d]], risk }
    }
    // Fallback: place near NER centre
    const lng = 92.5 + (i * 0.6), lat = 25.5
    return { id: `live-${i}-${district}`, name: district, coords: [[lng - 0.15, lat - 0.15], [lng + 0.15, lat - 0.15], [lng + 0.15, lat + 0.15], [lng - 0.15, lat + 0.15]], risk }
  })
}

const ALERT_LAYERS = ['alert-cluster-count', 'alert-clusters', 'alert-unclustered']

// Legend severity dots (module-level constant — must not be created after an
// early return, which would violate the Rules of Hooks when using useMemo).
const LEGEND_DOTS = [
  { color: '#EF4444', label: 'Evacuation' },
  { color: '#F97316', label: 'Warning' },
  { color: '#EAB308', label: 'Watch' },
  { color: '#38BDF8', label: 'Advisory' },
]

interface MapViewProps {
  alerts?: Alert[]
  stations?: SensorStation[]
  reports?: CitizenReport[]
  loading?: boolean
  onAlertClick?: (a: Alert) => void
  onStationClick?: (s: SensorStation) => void
}

export default function MapView({
  alerts = [],
  stations = [],
  reports = [],
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
  const reportsRef = useRef(reports)

  const [currentLayer, setCurrentLayer] = useState('streets')
  const [showRiskZones, setShowRiskZones] = useState(true)
  const [showStations, setShowStations] = useState(true)
  const [showAlerts, setShowAlerts] = useState(true)
  const [showLiveReports, setShowLiveReports] = useState(true)
  const [timeExtent, setTimeExtent] = useState<[number, number]>([0, 100])
  const [clustered, setClustered] = useState(true)
  const [showTerrain3D, setShowTerrain3D] = useState(false)
  const [mapReady, setMapReady] = useState(false)

  alertsRef.current = alerts
  stationsRef.current = stations
  clusteredRef.current = clustered
  showAlertsRef.current = showAlerts
  showStationsRef.current = showStations
  timeExtentRef.current = timeExtent
  onAlertClickRef.current = onAlertClick
  onStationClickRef.current = onStationClick
  reportsRef.current = reports

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
          'circle-color': ['step', ['get', 'point_count'], '#38BDF8', 3, '#F97316', 6, '#EF4444'],
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
        'circle-color': ['match', ['get', 'severity'], 'evacuation', '#EF4444', 'warning', '#F97316', 'watch', '#EAB308', '#38BDF8'],
        'circle-radius': ['interpolate', ['linear'], ['get', 'probability'], 0, 10, 1, 28],
        'circle-stroke-width': 2,
        'circle-stroke-color': '#0d1117',
        'circle-opacity': 0.9,
      },
      layout: { visibility: showAlertsRef.current ? 'visible' : 'none' },
    })
  }

  function ensureRiskZones(map: maplibregl.Map) {
    const zones = liveRiskZones(alertsRef.current)
    const geojson: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: zones.map(z => ({
        type: 'Feature',
        properties: { id: z.id, name: z.name, risk: z.risk },
        geometry: { type: 'Polygon', coordinates: [z.coords] },
      })),
    }

    const existing = map.getSource('risk-zones') as maplibregl.GeoJSONSource | undefined
    if (existing) {
      existing.setData(geojson)
      return
    }
    map.addSource('risk-zones', { type: 'geojson', data: geojson })
    map.addLayer({
      id: 'risk-zones-fill',
      type: 'fill',
      source: 'risk-zones',
      paint: {
        'fill-color': ['interpolate', ['linear'], ['get', 'risk'], 0.2, '#38BDF8', 0.5, '#F97316', 0.8, '#EF4444'],
        'fill-opacity': 0.35,
      },
      layout: { visibility: showRiskZones ? 'visible' : 'none' },
    })
    map.addLayer({
      id: 'risk-zones-border',
      type: 'line',
      source: 'risk-zones',
      paint: {
        'line-color': ['interpolate', ['linear'], ['get', 'risk'], 0.2, '#38BDF8', 0.5, '#F97316', 0.8, '#EF4444'],
        'line-width': 2,
        'line-opacity': 0.8,
      },
      layout: { visibility: showRiskZones ? 'visible' : 'none' },
    })
  }

  // NE Live-only report layer — every feature is already NE-gated server-side; client re-checks for safety
  const NER_BBOX_MAP = { minLat: 21.9, maxLat: 29.7, minLon: 88.0, maxLon: 97.5 }
  function _isNerMapReport(r: CitizenReport): boolean {
    if (r.latitude != null && r.longitude != null) {
      if (r.latitude >= NER_BBOX_MAP.minLat && r.latitude <= NER_BBOX_MAP.maxLat && r.longitude >= NER_BBOX_MAP.minLon && r.longitude <= NER_BBOX_MAP.maxLon) return true
    }
    const hay = `${r.description ?? ''} ${r.district} ${r.village} ${r.country ?? ''} ${r.source ?? ''}`.toLowerCase()
    return ['arunachal','assam','manipur','meghalaya','mizoram','nagaland','sikkim','tripura','itanagar','dispur','imphal','shillong','aizawl','kohima','gangtok','agartala','northeast','barak','brahmaputra'].some(t=>hay.includes(t))
  }

  function syncReports(map: maplibregl.Map) {
    // Strict NE filter — never plot global noise even if backend leaked
    const nerReports = reportsRef.current.filter(_isNerMapReport)
    const features = nerReports.map((report) => {
      const districtKey = Object.keys(DISTRICT_COORDS).find((name) => name.toLowerCase() === (report.district || '').toLowerCase())
      const center = report.longitude != null && report.latitude != null
        ? { lng: report.longitude, lat: report.latitude }
        : districtKey ? DISTRICT_COORDS[districtKey] : null
      // For NE districts without coords, skip silently — prevents Global (0,0) ghost pins
      if (!center) return null
      const isLive = report.status === 'live_internet' || (report.source && ['GDACS','ReliefWeb','Open-Meteo','USGS','EONET','GNews'].includes(report.source))
      return {
        type: 'Feature',
        properties: {
          id: report.id,
          severity: report.severity,
          title: (report.description || report.reportType || '').slice(0, 120),
          source: report.source || 'Citizen',
          isLive: isLive ? 1 : 0,
          village: report.village,
          district: report.district,
        },
        geometry: { type: 'Point', coordinates: [center.lng, center.lat] },
      } as GeoJSON.Feature
    }).filter(Boolean) as GeoJSON.Feature[]
    const data: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features }
    const source = map.getSource('report-events') as maplibregl.GeoJSONSource | undefined
    if (source) {
      source.setData(data)
      return
    }
    map.addSource('report-events', { type: 'geojson', data })
    map.addLayer({
      id: 'report-events',
      type: 'circle',
      source: 'report-events',
      paint: {
        // Live NE reports get a brighter sky stroke so they pop against citizen dots
        'circle-color': ['match', ['get', 'severity'], 'critical', '#EF4444', 'high', '#F97316', 'moderate', '#EAB308', 'low', '#38BDF8', '#38bdf8'],
        'circle-radius': ['case', ['==', ['get', 'isLive'], 1], 10, 7],
        'circle-stroke-width': ['case', ['==', ['get', 'isLive'], 1], 3, 1.5],
        'circle-stroke-color': ['case', ['==', ['get', 'isLive'], 1], '#38bdf8', '#0d1117'],
        'circle-opacity': 0.92,
      },
    })
    // Live pulse halo — only for live_internet features (duplicate draw with low opacity)
    map.addLayer({
      id: 'report-events-halo',
      type: 'circle',
      source: 'report-events',
      filter: ['==', ['get', 'isLive'], 1],
      paint: {
        'circle-color': ['match', ['get', 'severity'], 'critical', '#EF4444', 'high', '#F97316', 'moderate', '#EAB308', '#38bdf8'],
        'circle-radius': 18,
        'circle-opacity': 0.14,
        'circle-stroke-width': 0,
      },
    })
    map.addLayer({
      id: 'report-event-labels',
      type: 'symbol',
      source: 'report-events',
      layout: { 'text-field': ['get', 'source'], 'text-size': 10, 'text-offset': [0, 1.55], 'text-allow-overlap': false },
      paint: { 'text-color': '#e6edf3', 'text-halo-color': '#0d1117', 'text-halo-width': 1 },
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
      const baseColor = isOnline ? '#22C55E' : s.status === 'maintenance' ? '#EAB308' : '#EF4444'
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
      fadeDuration: 0,
      collectResourceTiming: false,
      maxTileCacheSize: 64,
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right')
    mapRef.current = map

    let styleReadyDebounce: number | null = null
    const onStyleReady = () => {
      // Defer overlays to next frame so style has settled — avoids jank on tile-heavy bright/dark styles
      if (styleReadyDebounce !== null) window.clearTimeout(styleReadyDebounce)
      styleReadyDebounce = window.setTimeout(() => {
        ensureRiskZones(map)
        syncAlerts(map)
        syncReports(map)
        rebuildStationMarkers(map)
        setMapReady(true)
      }, 30)
    }
    map.on('load', onStyleReady)
    // styledata fires for every tile/source — use style.load (once per style change) instead
    map.on('style.load', onStyleReady)

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
    // Live NE reports — click opens source URL or shows popup
    map.on('click', 'report-events', e => {
      const f = e.features?.[0]
      if (!f) return
      const props = f.properties as Record<string, unknown>
      const id = props?.id as string | undefined
      const report = reportsRef.current.find(r => r.id === id)
      if (!report) return
      // Prefer opening source URL for live internet reports, otherwise just fly to the point
      const coords = (f.geometry as GeoJSON.Point).coordinates as [number, number]
      map.flyTo({ center: coords, zoom: Math.max(map.getZoom(), 7), duration: 800 })
      // Show a lightweight popup with key fields
      const html = `<div style="font:12px system-ui; line-height:1.4; min-width:160px"><b>${(report.code||'').replace(/</g,'&lt;')}</b> <span style="border:1px solid #38bdf8; color:#38bdf8; border-radius:999px; padding:1px 6px; font-size:10px">${(report.source||'').replace(/</g,'&lt;')}</span><br/><span style="text-transform:capitalize">${report.reportType}</span> · <span style="color:${report.severity==='critical'?'#EF4444':report.severity==='high'?'#F97316':'#38BDF8'}">${report.severity}</span><br/><span style="color:#94a3b8">${(report.district||'') + ' · ' + (report.village||'')}</span><br/><span>${(report.description||'').slice(0,120).replace(/</g,'&lt;')}</span>${report.url ? `<br/><a href="${report.url}" target="_blank" rel="noreferrer" style="color:#38bdf8">Open source ↗</a>` : ''}</div>`
      new maplibregl.Popup({ closeButton: true, maxWidth: '280px' }).setLngLat(coords).setHTML(html).addTo(map)
    })
    ;['alert-unclustered', 'alert-clusters', 'report-events'].forEach(layer => {
      map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer' })
      map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = '' })
    })

    return () => {
      if (styleReadyDebounce !== null) window.clearTimeout(styleReadyDebounce)
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

  // 3D terrain: SimReady DEM heightfield (Terrarium, keyless) — mirrors CAD-to-SimReady DEM→USD pipeline
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const hasTerrain = !!map.getSource('simready-dem')
    if (showTerrain3D && !hasTerrain) {
      try {
        map.addSource('simready-dem', {
          type: 'raster-dem',
          tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
          encoding: 'terrarium',
          tileSize: 256,
          maxzoom: 14,
          attribution: '© AWS Terrain Tiles',
        })
        map.setTerrain({ source: 'simready-dem', exaggeration: 1.4 })
        map.setPitch(58)
        map.setBearing(-12)
      } catch { /* terrain unsupported in this style */ }
    } else if (!showTerrain3D && hasTerrain) {
      try {
        map.setTerrain(null)
        if (map.getSource('simready-dem')) map.removeSource('simready-dem')
        map.setPitch(0)
        map.setBearing(0)
      } catch { /* ignore */ }
    }
  }, [showTerrain3D, mapReady])

  // Push alert + live risk-zone data whenever alerts change
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    syncAlerts(map)
    syncReports(map)
    ensureRiskZones(map)
    // syncAlerts closes over alertFeatures/filters; re-running on every render
    // would thrash the GeoJSON source, so we deliberately key on data inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alerts, reports, clustered, timeExtent, mapReady])

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
    const vis = showLiveReports ? 'visible' : 'none'
    if (map.getLayer('report-events')) map.setLayoutProperty('report-events', 'visibility', vis)
    if (map.getLayer('report-events-halo')) map.setLayoutProperty('report-events-halo', 'visibility', vis)
    if (map.getLayer('report-event-labels')) map.setLayoutProperty('report-event-labels', 'visibility', vis)
  }, [showLiveReports, mapReady])

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
              { key: 'liveReports', label: 'Live NE Reports', checked: showLiveReports, onChange: (e: React.ChangeEvent<HTMLInputElement>) => setShowLiveReports(e.target.checked) },
              { key: 'clustered', label: 'Cluster Alerts', checked: clustered, onChange: (e: React.ChangeEvent<HTMLInputElement>) => setClustered(e.target.checked) },
              { key: 'terrain3D', label: '3D Terrain (SimReady DEM)', checked: showTerrain3D, onChange: (e: React.ChangeEvent<HTMLInputElement>) => setShowTerrain3D(e.target.checked) },
            ].map(({ key, label, checked, onChange }) => (
              <label key={key} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-all duration-200 hover:bg-white/5 cursor-pointer has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-cyan-500/30">
                <input aria-label={label} type="checkbox" checked={checked} onChange={onChange} className="h-4 w-4 rounded border-slate-600 bg-slate-800/50 accent-cyan-500 transition" />
                <span className="text-slate-200">{label}</span>
              </label>
            ))}
          </div>
          {showTerrain3D && (
            <a href="?tab=simready" onClick={(e) => { e.preventDefault(); window.history.replaceState(null, '', '?tab=simready'); window.dispatchEvent(new PopStateEvent('popstate')) }} className="mt-2 block rounded-lg border border-cyan-500/20 bg-cyan-500/10 px-2 py-1.5 text-center text-xs font-semibold text-cyan-300 hover:bg-cyan-500/15">
              ⬢ Convert this DEM to SimReady USD →
            </a>
          )}
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
              <span className="h-3 w-3 rounded-full bg-sky-400 shadow-[0_0_8px_rgba(56,189,248,0.5)] animate-pulse-soft" />
              <span className="text-slate-300">Live NE Report</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-sky-400/40" />
              <span className="text-slate-300">Live halo (NE only)</span>
            </div>
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

      <div className="pointer-events-none absolute left-3 bottom-3 flex flex-col gap-1">
        <div className="pointer-events-auto solid-panel rounded-md px-2 py-1 text-[11px] text-slate-400">
          {alerts.length} alert{alerts.length !== 1 ? 's' : ''} · {reports.filter(r=>r.status==='live_internet'||['GDACS','ReliefWeb','Open-Meteo','USGS','EONET'].includes(r.source||'')).length} live NE · {stations.length} stations · {reports.length} reports total · click points for details
        </div>
        <div className="pointer-events-auto solid-panel rounded-md px-2 py-1 text-[11px] text-sky-300/80 border-sky-500/20">
          Live NE algorithm: NE bbox 21.9–29.7°N 88–97.5°E + text gate (8 states) · only NE hits reach map · auto-refresh 60s + WS
        </div>
        <div className="pointer-events-none text-[11px] text-slate-500">
          {[MAPTILER_KEY && 'MapTiler', TOMTOM_KEY && 'TomTom', 'OpenFreeMap'].filter(Boolean).join(' · ')}
        </div>
      </div>
    </div>
  )
}
