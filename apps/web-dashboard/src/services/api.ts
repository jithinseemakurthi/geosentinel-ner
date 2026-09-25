import type { Alert, CitizenReport, SensorStation, TokenResponse } from '@/types'

const API_BASE = '/api/v1'
const TIMEOUT_MS = 2500

export interface ApiState {
  online: boolean
  token?: string
}

const state: ApiState = { online: false }

export function isOnline() {
  return state.online
}

export function getAccessToken(): string | null {
  return state.token ?? null
}

async function call<T>(path: string, init?: RequestInit): Promise<T | null> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
        ...init?.headers,
      },
    })
    if (!res.ok) return null
    state.online = true
    return (await res.json()) as T
  } catch {
    state.online = false
    return null
  } finally {
    clearTimeout(timer)
  }
}

interface LoginBody {
  username: string
  password: string
}

export async function login(body: LoginBody): Promise<{ ok: boolean; demo: boolean; token?: TokenResponse }> {
  const token = await call<TokenResponse>('/auth/login', { method: 'POST', body: JSON.stringify(body) })
  if (token?.access_token) {
    state.token = token.access_token
    return { ok: true, demo: false, token }
  }
  // Offline/demo fallback — lets Jithin07 sign in even when the API/DB is down
  // (real DB account is also created via scripts/set_jithin07.py when Docker is up)
  if (body.username === 'Jithin07' && body.password === '123456789') {
    state.token = 'dev-jithin07-token'
    return { ok: true, demo: true }
  }
  return { ok: false, demo: false }
}

export async function fetchAlerts(): Promise<{ data: Alert[]; live: boolean }> {
  const res = await call<{ items: Alert[] }>('/alerts')
  if (res?.items) return { data: mapAlerts(res.items), live: true }
  return { data: [], live: false }
}

export async function acknowledgeAlert(id: string): Promise<boolean> {
  const res = await call<{ status: string }>(`/alerts/${id}/acknowledge`, { method: 'POST' })
  return res?.status === 'acknowledged'
}

export async function fetchReports(): Promise<{ data: CitizenReport[]; live: boolean }> {
  const res = await call<{ items: CitizenReport[] }>('/reports')
  if (res?.items) return { data: res.items, live: true }
  return { data: [], live: false }
}

export interface LiveReportsResult {
  data: CitizenReport[]
  internet: CitizenReport[]
  citizen: CitizenReport[]
  live: boolean
}

function _mapLiveItem(raw: Record<string, unknown>): CitizenReport {
  const severity = (raw['severity'] as string) ?? 'moderate'
  const priority =
    severity === 'critical' ? 92 : severity === 'high' ? 78 : severity === 'moderate' ? 55 : severity === 'low' ? 30 : 45
  const eventType = (raw['event_type'] as string) ?? (raw['reportType'] as string) ?? raw['report_type'] as string ?? 'other'
  // Coords may arrive as latitude/longitude, lat/lng, or numeric strings
  const latRaw = raw['latitude'] ?? raw['lat']
  const lonRaw = raw['longitude'] ?? raw['lng'] ?? raw['lon']
  const lat = typeof latRaw === 'number' ? latRaw : typeof latRaw === 'string' && latRaw.trim() !== '' ? Number(latRaw) : undefined
  const lon = typeof lonRaw === 'number' ? lonRaw : typeof lonRaw === 'string' && lonRaw.trim() !== '' ? Number(lonRaw) : undefined
  return {
    id: (raw['id'] as string) ?? crypto.randomUUID(),
    code: (raw['code'] as string) ?? (raw['id'] as string)?.slice(0, 10) ?? 'LIVE',
    reportType: eventType as CitizenReport['reportType'],
    village: (raw['village'] as string) || (raw['district'] as string) || (raw['country'] as string) || 'NER',
    district: (raw['district'] as string) || (raw['village'] as string) || (raw['country'] as string) || 'NER',
    severity,
    description: (raw['description'] as string) || (raw['title'] as string) || '',
    status: (raw['status'] as CitizenReport['status']) ?? 'live_internet',
    priorityScore: (raw['priorityScore'] as number) ?? (raw['priority_score'] as number) ?? priority,
    createdAt: (raw['issued_at'] as string) ?? (raw['createdAt'] as string) ?? (raw['created_at'] as string) ?? new Date().toISOString(),
    source: (raw['source'] as string) ?? 'Live Internet',
    url: (raw['url'] as string) ?? null,
    country: (raw['country'] as string) ?? undefined,
    latitude: Number.isFinite(lat as number) ? (lat as number) : undefined,
    longitude: Number.isFinite(lon as number) ? (lon as number) : undefined,
    problem_tags: (raw['problem_tags'] as string[]) ?? undefined,
    problem_hits: (raw['problem_hits'] as number) ?? undefined,
    confidence: (raw['confidence'] as number) ?? undefined,
    event_type: eventType,
    raw_title: (raw['raw_title'] as string) ?? (raw['title'] as string) ?? undefined,
  }
}

// Strict NE filter — mirrors backend NER_BBOX + term gate. Used both for browser-direct fallback
// and as a client-side second gate so a misconfigured backend never leaks global noise to the map.
const NER_REPORT_TERMS = [
  'arunachal', 'assam', 'manipur', 'meghalaya', 'mizoram', 'nagaland', 'sikkim', 'tripura',
  'itanagar', 'dispur', 'imphal', 'shillong', 'aizawl', 'kohima', 'gangtok', 'agartala',
  'northeast india', 'barak', 'brahmaputra', 'churachandpur', 'khasi',
]
const NER_BBOX = { minLat: 21.9, maxLat: 29.7, minLon: 88.0, maxLon: 97.5 }

function _inNerBbox(lat?: number, lon?: number): boolean {
  if (lat == null || lon == null) return false
  return lat >= NER_BBOX.minLat && lat <= NER_BBOX.maxLat && lon >= NER_BBOX.minLon && lon <= NER_BBOX.maxLon
}

function _isNerReport(report: CitizenReport): boolean {
  if (_inNerBbox(report.latitude, report.longitude)) return true
  const value = `${report.description ?? ''} ${report.district} ${report.village} ${report.country ?? ''} ${report.code ?? ''}`.toLowerCase()
  return NER_REPORT_TERMS.some((term) => value.includes(term))
}

export function isNerReport(report: CitizenReport): boolean { return _isNerReport(report) }

async function _fetchDirectLiveReports(limit = 8): Promise<CitizenReport[]> {
  // Browser-direct fallback when gateway is down — only emits NE-bbox-validated events.
  // USGS quakes are bbox-filtered by epicenter; EONET is title-filtered (no coords).
  const out: CitizenReport[] = []
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), 6000)
    const eRes = await fetch(`https://eonet.gsfc.nasa.gov/api/v3/events?limit=${limit * 2}&status=open`, { signal: ctrl.signal })
    clearTimeout(t)
    if (eRes.ok) {
      const j = (await eRes.json()) as { events?: Array<Record<string, unknown>> }
      for (const ev of (j.events ?? [])) {
        const title = String(ev['title'] ?? 'EONET event')
        const cats = ((ev['categories'] as Array<Record<string, unknown>>) ?? []).map((c) => String(c['title'] ?? '')).join(', ')
        const link = String(ev['link'] ?? 'https://eonet.gsfc.nasa.gov/')
        const geom = (ev['geometry'] as Array<Record<string, unknown>>) ?? []
        const date = String(geom[0]?.['date'] ?? new Date().toISOString())
        const candidate = _mapLiveItem({
          id: `eonet-${ev['id']}`,
          code: `EONET-${String(ev['id']).slice(0, 6)}`,
          title: `${title} — ${cats}`,
          district: 'NER',
          country: 'India',
          event_type: 'other',
          severity: 'moderate',
          status: 'live_internet',
          source: 'EONET',
          url: link,
          issued_at: date,
          description: `${title} ${cats}`.slice(0, 500),
        })
        if (_isNerReport(candidate)) out.push(candidate)
        if (out.length >= Math.ceil(limit / 2)) break
      }
    }
  } catch { /* ignore */ }
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), 6000)
    // Wider NE bbox query for USGS (India + Myanmar border)
    const uRes = await fetch(
      `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&limit=${limit * 2}&minmagnitude=4.2&orderby=time&minlatitude=${NER_BBOX.minLat}&maxlatitude=${NER_BBOX.maxLat}&minlongitude=${NER_BBOX.minLon}&maxlongitude=${NER_BBOX.maxLon}`,
      { signal: ctrl.signal },
    )
    clearTimeout(t)
    if (uRes.ok) {
      const j = (await uRes.json()) as { features?: Array<Record<string, unknown>> }
      for (const feat of (j.features ?? [])) {
        const props = (feat['properties'] as Record<string, unknown>) ?? {}
        const geom = (feat['geometry'] as Record<string, unknown>) ?? {}
        const coords = (geom['coordinates'] as number[] | undefined) ?? []
        const place = String(props['place'] ?? 'earthquake')
        const mag = Number(props['mag'] ?? 0)
        const url = String(props['url'] ?? 'https://earthquake.usgs.gov/')
        const timeMs = Number(props['time'] ?? 0)
        const lon = coords[0], lat = coords[1]
        const candidate = _mapLiveItem({
          id: `usgs-${feat['id']}`,
          code: `USGS-${String(feat['id']).slice(0, 6)}`,
          title: `M${mag} earthquake — ${place}`,
          district: place.split(',').pop()?.trim() || 'NE India',
          country: 'India',
          event_type: 'earthquake',
          severity: mag >= 6 ? 'critical' : mag >= 5 ? 'high' : 'moderate',
          status: 'live_internet',
          source: 'USGS',
          url,
          issued_at: timeMs ? new Date(timeMs).toISOString() : new Date().toISOString(),
          description: `Earthquake M${mag} at ${place} — potential landslide trigger in NE hills.`,
          latitude: typeof lat === 'number' ? lat : undefined,
          longitude: typeof lon === 'number' ? lon : undefined,
        })
        if (_isNerReport(candidate)) out.push(candidate)
        if (out.length >= limit) break
      }
    }
  } catch { /* ignore */ }
  return out.filter(_isNerReport).slice(0, limit)
}

export async function fetchLiveReports(limit = 12): Promise<LiveReportsResult> {
  // Primary: merged NE-only live-internet + citizen reports from the gateway (already NE-gated server-side)
  const live = await call<{ items: Array<Record<string, unknown>>; internet_count?: number; citizen_count?: number }>(
    `/live/reports?limit=${limit}&include_citizen=true`,
  )
  if (live?.items?.length) {
    const mapped = live.items.map(_mapLiveItem).filter(_isNerReport as (r: CitizenReport) => boolean)
    // Client second gate: drop any non-NE leak even if backend misconfigured
    const internet = mapped.filter((r) => r.status === 'live_internet' || ['GDACS', 'ReliefWeb', 'EONET', 'USGS', 'Open-Meteo', 'GNews', 'Tavily', 'Brave'].includes(r.source ?? ''))
    const citizen = mapped.filter((r) => r.source === 'Citizen')
    // If backend returned items but none passed NE gate, treat as no live data (fall through to direct)
    if (mapped.length) return { data: mapped, internet, citizen, live: true }
  }
  // Fallback: citizen-only when live endpoint is unreachable (offline demo)
  const fallback = await call<{ items: CitizenReport[] }>('/reports')
  if (fallback?.items?.length) return { data: fallback.items, internet: [], citizen: fallback.items, live: true }
  // Last resort: direct browser live internet (works even when gateway is down)
  const direct = await _fetchDirectLiveReports(limit)
  if (direct.length) {
    const internet = direct.filter((r) => r.source !== 'Citizen')
    return { data: direct, internet, citizen: [], live: true }
  }
  return { data: [], internet: [], citizen: [], live: false }
}

export async function fetchLiveSearch(query: string, count = 6): Promise<Array<{ title: string; url: string; content: string; source: string; score: number }>> {
  const res = await call<{ results: Array<{ title: string; url: string; content: string; source: string; score: number }> }>(
    `/live/search?q=${encodeURIComponent(query)}&count=${count}`,
  )
  return res?.results ?? []
}

export async function fetchPowerfulProblems(query = 'landslide', count = 8): Promise<CitizenReport[]> {
  const res = await call<{ items: Array<Record<string, unknown>> }>(
    `/live/problems/search?q=${encodeURIComponent(query)}&count=${count}`,
  )
  if (!res?.items) return []
  return res.items.map(_mapLiveItem).filter(_isNerReport)
}

export async function triggerProblemSearchAndReport(query = 'landslide in North East India', count = 6, persist = true): Promise<{ created: number; items: CitizenReport[] }> {
  const res = await call<{ created: number; items: Array<Record<string, unknown>> }>(
    `/live/problems/search-and-report?q=${encodeURIComponent(query)}&count=${count}&persist=${persist}`,
    { method: 'POST' },
  )
  if (!res) return { created: 0, items: [] }
  return { created: res.created ?? 0, items: (res.items ?? []).map(_mapLiveItem).filter(_isNerReport) }
}

export async function fetchStations(): Promise<{ data: SensorStation[]; live: boolean }> {
  const res = await call<{ items: Array<Record<string, unknown>> }>('/sensors/stations')
  if (res?.items && res.items.length) {
    // Map backend SensorStationRead (station_code, station_type, geom, ... ) to frontend SensorStation
    const mapped: SensorStation[] = res.items.map((raw) => {
      const r = raw as Record<string, unknown>
      const code = (r['station_code'] as string) ?? (r['code'] as string) ?? '—'
      const name = (r['name'] as string) ?? code
      // Derive district from name / station_code prefix
      let district = '—'
      const lower = `${name} ${code}`.toLowerCase()
      if (lower.includes('aizawl')) district = 'Aizawl'
      else if (lower.includes('imphal')) district = 'Imphal'
      else if (lower.includes('shillong')) district = 'Shillong'
      else if (lower.includes('gangtok')) district = 'Gangtok'
      else if (lower.includes('itanagar')) district = 'Itanagar'
      else if (lower.includes('agartala')) district = 'Agartala'
      else if (lower.includes('kohima')) district = 'Kohima'
      else if (lower.includes('dispur')) district = 'Dispur'
      const status = (r['status'] as SensorStation['status']) ?? 'offline'
      const updated = (r['updated_at'] as string) ?? (r['created_at'] as string) ?? new Date().toISOString()
      const battery = status === 'online' ? 88 : status === 'maintenance' ? 52 : 14
      return {
        id: (r['id'] as string) ?? crypto.randomUUID(),
        code,
        type: (r['station_type'] as SensorStation['type']) ?? 'AWS',
        district,
        status,
        battery,
        lastReading: updated,
      }
    })
    return { data: mapped, live: true }
  }
  return { data: [], live: false }
}

/** Dev-mode only: obtain a functional WS-capable token without a database */
export async function fetchDevSession(): Promise<boolean> {
  const res = await call<{ access_token?: string }>('/dev/session', { method: 'POST' })
  if (res?.access_token) {
    state.token = res.access_token
    return true
  }
  return false
}

export interface LiveWeather {
  district: string
  source: string
  observed_rainfall_24h_mm: number | null
  forecast_rainfall_next_24h_mm: number | null
  temperature_c: number | null
  humidity_pct: number | null
}

/** Live observed+forecast weather for a district (data-ingestion → Open-Meteo, keyless) */
const weatherCache = new Map<string, { at: number; data: LiveWeather }>()
const WEATHER_TTL_MS = 55_000

export async function fetchLiveWeather(district: string): Promise<LiveWeather | null> {
  const key = district.toLowerCase()
  const cached = weatherCache.get(key)
  if (cached && Date.now() - cached.at < WEATHER_TTL_MS) return cached.data
  const controller = new AbortController()
  const t = setTimeout(() => controller.abort(), 8000)
  try {
    const res = await fetch(`/weather/current/${encodeURIComponent(district)}`, { signal: controller.signal })
    if (res.ok) {
      const data = (await res.json()) as LiveWeather
      weatherCache.set(key, { at: Date.now(), data })
      return data
    }
  } catch {
    /* try direct Open-Meteo fallback below */
  } finally {
    clearTimeout(t)
  }
  // Fallback: direct Open-Meteo (works without Docker, student free, no key)
  try {
    const { DISTRICT_COORDS } = await import('@/lib/districts')
    const coords = DISTRICT_COORDS[district] || DISTRICT_COORDS['Aizawl']
    if (!coords) return null
    const ctrl2 = new AbortController()
    const t2 = setTimeout(() => ctrl2.abort(), 8000)
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${coords.lat}&longitude=${coords.lng}&hourly=precipitation,temperature_2m,relative_humidity_2m&past_hours=24&forecast_days=1&timezone=UTC`
    const r = await fetch(url, { signal: ctrl2.signal })
    clearTimeout(t2)
    if (!r.ok) return null
    const j = (await r.json()) as { hourly?: { time: string[]; precipitation: number[]; temperature_2m: number[]; relative_humidity_2m: number[] } }
    const prec = j.hourly?.precipitation || []
    const temps = j.hourly?.temperature_2m || []
    const hums = j.hourly?.relative_humidity_2m || []
    const obs = prec.slice(0, 24).reduce((a: number, v: number) => a + (v || 0), 0)
    const fore = prec.slice(24, 48).reduce((a: number, v: number) => a + (v || 0), 0)
    const data: LiveWeather = {
      district,
      source: 'open-meteo-direct',
      observed_rainfall_24h_mm: Math.round(obs * 100) / 100,
      forecast_rainfall_next_24h_mm: Math.round(fore * 100) / 100,
      temperature_c: temps[temps.length - 1] ?? null,
      humidity_pct: hums[hums.length - 1] ?? null,
    }
    weatherCache.set(key, { at: Date.now(), data })
    return data
  } catch {
    return null
  }
}

export interface ImdNowcastEntry {
  District?: string
  State_District?: string
  State?: string
  Date?: string
  alerts_total?: number
  cats_active?: Record<string, number>
  message?: string
  impact?: string
  action?: string
  Color?: number | string
  update_time?: string
  vupto?: string
  toi?: string
}

/** Live district nowcast warnings from IMD's public GeoServer (keyless) */
const imdCache = new Map<string, { at: number; data: ImdNowcastEntry }>()
export async function fetchImdNowcast(district: string): Promise<ImdNowcastEntry | null> {
  const key = district.toLowerCase()
  const cached = imdCache.get(key)
  if (cached && Date.now() - cached.at < WEATHER_TTL_MS) return cached.data
  const controller = new AbortController()
  const t = setTimeout(() => controller.abort(), 2500)
  try {
    const res = await fetch(`/imd/nowcast?district=${encodeURIComponent(district)}`, { signal: controller.signal })
    if (res.ok) {
      const data = (await res.json()) as { data?: ImdNowcastEntry[] }
      const entry = data.data?.[0] ?? null
      if (entry) {
        imdCache.set(key, { at: Date.now(), data: entry })
        return entry
      }
    }
  } catch {
    /* live only */
  } finally {
    clearTimeout(t)
  }
  return null
}

export interface ReverseGeoResult {
  label: string | null
  village: string | null
  district: string | null
  state: string | null
}

/** HERE-powered reverse geocode (server-proxied; null when offline/unconfigured) */
export async function reverseGeocode(lat: number, lng: number): Promise<ReverseGeoResult | null> {
  return call<ReverseGeoResult>(`/geo/reverse?lat=${lat}&lon=${lng}`)
}

export async function submitReport(payload: {
  reportType: string
  severity: string
  description: string
  reporterName: string
  lat: number
  lng: number
}): Promise<CitizenReport> {
  const body = {
    report_type: payload.reportType,
    severity: payload.severity,
    description: payload.description,
    reporter_name: payload.reporterName || undefined,
    geom: { type: 'Point', coordinates: [payload.lng, payload.lat] },
  }
  const res = await call<Record<string, unknown>>('/reports', { method: 'POST', body: JSON.stringify(body) })
  if (!res) throw new Error('Report submission failed — API unavailable')
  const serverCode = res['report_code'] as string | undefined
  if (!serverCode) throw new Error('Report submission failed — invalid server response')
  return {
    id: (res['id'] as string) ?? crypto.randomUUID(),
    code: serverCode,
    reportType: payload.reportType as CitizenReport['reportType'],
    village: '—',
    district: '—',
    severity: payload.severity,
    description: payload.description,
    status: 'submitted',
    priorityScore: Number(res['priority_score'] ?? 40),
    createdAt: new Date().toISOString(),
  }
}

export async function uploadReportMedia(reportId: string, files: File[]): Promise<boolean> {
  for (let index = 0; index < files.length; index++) {
    const form = new FormData()
    form.append('file', files[index])
    form.append('is_primary', String(index === 0))
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 30_000)
    try {
      const res = await fetch(`${API_BASE}/reports/${encodeURIComponent(reportId)}/media`, {
        method: 'POST',
        body: form,
        signal: controller.signal,
        headers: state.token ? { Authorization: `Bearer ${state.token}` } : {},
      })
      if (!res.ok) return false
    } catch {
      return false
    } finally {
      clearTimeout(timer)
    }
  }
  return true
}

interface RawAlert {
  id?: string
  severity?: string
  title?: string
  message?: string
  status?: string
  issued_at?: string
  expires_at?: string | null
  acknowledged_at?: string | null
  zone_id?: string | null
  probability?: number
  metadata?: Record<string, unknown> | null
}

function mapAlerts(items: RawAlert[]): Alert[] {
  return items.map((a) => ({
    id: a.id ?? crypto.randomUUID(),
    severity: (a.severity ?? 'advisory') as Alert['severity'],
    title: a.title ?? 'Alert',
    zone: a.zone_id ?? '—',
    district: (typeof a.metadata?.district === 'string' && a.metadata.district) || '—',
    message: a.message ?? '',
    probability: typeof a.probability === 'number' ? a.probability : 0.5,
    issuedAt: a.issued_at ?? new Date().toISOString(),
    expiresAt: a.expires_at ?? undefined,
    status: (a.status ?? 'active') as Alert['status'],
    acknowledgedAt: a.acknowledged_at ?? null,
  }))
}
