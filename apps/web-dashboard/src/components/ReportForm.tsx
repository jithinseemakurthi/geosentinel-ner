import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { submitReport, uploadReportMedia, reverseGeocode } from '@/services/api'
import type { CitizenReport } from '@/types'
import { useMap } from '@/hooks/useMap'
import { useDismissable } from '@/hooks/useDismissable'

const REPORT_TYPES = ['crack', 'bulge', 'subsidence', 'debris', 'rockfall', 'road_block', 'excavation', 'water_spring', 'other'] as const
const SEVERITIES = ['low', 'medium', 'high'] as const

export default function ReportForm({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (r: CitizenReport) => void
}) {
  const [reportType, setReportType] = useState<string>('crack')
  const [severity, setSeverity] = useState<string>('medium')
  const [description, setDescription] = useState('')
  const [reporterName, setReporterName] = useState('')
  const [lat, setLat] = useState('25.57')
  const [lng, setLng] = useState('91.88')
  const [photos, setPhotos] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // Map for coordinate picking
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const markerRef = useRef<maplibregl.Marker | null>(null)
  const geoSeq = useRef(0)
  const [placeLabel, setPlaceLabel] = useState<string>('')
  // Capture initial center once so typing/dragging never recreates the map
  const [initialCenter] = useState<[number, number]>(() => [Number(lng), Number(lat)])
  const { map } = useMap({ containerRef: mapContainerRef, center: initialCenter })
  useDismissable(open, onClose)

  // Reverse-geocode the pin via server-side HERE proxy (silent on failure)
  const lookupPlace = async (la: number, lo: number) => {
    const seq = ++geoSeq.current
    const res = await reverseGeocode(la, lo)
    if (seq === geoSeq.current) setPlaceLabel(res?.label ?? '')
  }

  // Draggable marker + click-to-place
  useEffect(() => {
    if (!open || !map) return
    if (markerRef.current) {
      markerRef.current.remove()
      markerRef.current = null
    }
    const mk = new maplibregl.Marker({ draggable: true, color: '#38BDF8' })
      .setLngLat([Number(lng), Number(lat)])
      .addTo(map)
    mk.on('dragend', () => {
      const p = mk.getLngLat()
      setLng(p.lng.toFixed(6))
      setLat(p.lat.toFixed(6))
      void lookupPlace(p.lat, p.lng)
    })
    markerRef.current = mk

    const onClick = (e: maplibregl.MapMouseEvent) => {
      markerRef.current?.setLngLat(e.lngLat)
      setLng(e.lngLat.lng.toFixed(6))
      setLat(e.lngLat.lat.toFixed(6))
      void lookupPlace(e.lngLat.lat, e.lngLat.lng)
    }
    map.on('click', onClick)
    return () => {
      map.off('click', onClick)
      markerRef.current?.remove()
      markerRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, map])

  // Keep marker in sync when coordinates are typed manually
  useEffect(() => {
    if (!open || !map || !markerRef.current) return
    const la = Number(lat), lo = Number(lng)
    if (Number.isNaN(la) || Number.isNaN(lo)) return
    markerRef.current.setLngLat([lo, la])
  }, [lat, lng, open, map])

  if (!open) return null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const la = Number(lat), lo = Number(lng)
    if (!description.trim()) { setError('Description is required'); return }
    if (Number.isNaN(la) || Number.isNaN(lo) || la < -90 || la > 90 || lo < -180 || lo > 180) { setError('Coordinates must be valid lat/lng'); return }
    setBusy(true); setError('')
    try {
      const created = await submitReport({ reportType, severity, description: description.trim(), reporterName: reporterName.trim(), lat: la, lng: lo })
      if (photos.length > 0 && !(await uploadReportMedia(created.id, photos))) {
        throw new Error('Report created, but one or more media files could not be uploaded')
      }
      onCreated(created)
      onClose()
    } catch (err: any) {
      setError(err?.message || 'Failed to submit report')
    } finally {
      setBusy(false)
    }
  }

  const field = 'w-full rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2.5 text-sm outline-none transition focus:border-emerald-500/60 focus:ring-2 focus:ring-emerald-500/20'

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="report-title" className="fixed inset-0 z-50 grid place-items-center">
      <button aria-label="Close" onClick={onClose} className="absolute inset-0 bg-slate-950/80" />
      <form onSubmit={handleSubmit} className="relative w-full max-w-3xl space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 id="report-title" className="text-lg font-bold">Submit Citizen Report</h2>
          <button type="button" onClick={onClose} className="rounded-lg px-2 py-1 text-slate-500 hover:bg-slate-800 hover:text-slate-200">✕</button>
        </div>

        {/* Map coordinate picker */}
        <section className="space-y-2">
          <label className="label">Location (click map or enter manually)</label>
          <div className="relative h-56 min-h-[224px] rounded-xl border border-slate-700 overflow-hidden">
            <div ref={mapContainerRef} className="absolute inset-0" />
            <div className="pointer-events-none absolute right-2 top-2 rounded-md bg-slate-900/90 px-2 py-1 text-[11px] text-slate-400">
              Click map to set location · marker is draggable
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="col-span-2">
              <label htmlFor="rlat" className="label">Latitude</label>
              <input id="rlat" value={lat} onChange={e => setLat(e.target.value)} className={field} />
            </div>
            <div className="col-span-1">
              <label htmlFor="rlng" className="label">Longitude</label>
              <input id="rlng" value={lng} onChange={e => setLng(e.target.value)} className={field} />
            </div>
          </div>
          {placeLabel && (
            <p className="text-xs text-slate-400" aria-live="polite">📍 {placeLabel}</p>
          )}
        </section>

        {/* Form fields */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="rtype" className="label">Type</label>
            <select id="rtype" value={reportType} onChange={e => setReportType(e.target.value)} className={field}>
              {REPORT_TYPES.map(t => <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="rsev" className="label">Severity</label>
            <select id="rsev" value={severity} onChange={e => setSeverity(e.target.value)} className={field}>
              {SEVERITIES.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
            </select>
          </div>
        </div>

        <div>
          <label htmlFor="rdesc" className="label">Description</label>
          <textarea id="rdesc" rows={3} value={description} onChange={e => setDescription(e.target.value)} className={field} placeholder="Describe what you observed — landmarks, size, direction, time…" />
        </div>

        {/* Photo upload with preview */}
        <section className="space-y-2">
          <label className="label">Photos / Video (max 5, 25 MB each)</label>
          <div className="relative">
            <input
              id="rphotos"
              type="file"
              accept="image/*,video/*"
              multiple
              onChange={e => {
                const files = Array.from(e.target.files || [])
                if (files.length + photos.length > 5) { setError('Maximum 5 files allowed'); return }
                const valid = files.filter(f => ['image/jpeg','image/png','image/webp','image/heic','video/mp4','video/webm','video/quicktime','audio/mpeg','audio/wav','audio/mp4'].includes(f.type))
                if (valid.length !== files.length) setError('Unsupported file type (jpg, png, webp, heic, mp4, webm, mov, m4a, mp3, wav)')
                if (files.some(f => f.size > 25 * 1024 * 1024)) setError('File exceeds 25 MB')
                setPhotos(prev => [...prev, ...valid])
              }}
              className="absolute inset-0 opacity-0 cursor-pointer"
            />
            <div className="rounded-lg border-2 border-dashed border-slate-700 bg-slate-800/40 p-6 text-center transition hover:border-emerald-500/50 hover:bg-slate-800/60">
              <div className="text-lg">📷</div>
              <p className="mt-1 text-sm text-slate-400">Drag & drop photos/videos here, or click to browse</p>
              <p className="text-[11px] text-slate-600 mt-1">JPG, PNG, WebP, HEIC, MP4, WebM, MOV · max 25 MB each · max 5 files</p>
            </div>
          </div>
          {photos.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {photos.map((f, i) => (
                <div key={i} className="relative rounded-lg border border-slate-700 bg-slate-800/60 p-1">
                  {f.type.startsWith('image/') ? (
                    <img src={URL.createObjectURL(f)} alt="" className="h-16 w-16 object-cover rounded" />
                  ) : (
                    <video src={URL.createObjectURL(f)} className="h-16 w-16 object-cover rounded" muted />
                  )}
                  <button type="button" onClick={() => setPhotos(p => p.filter((_, j) => j !== i))} className="absolute -top-1 -right-1 rounded-full bg-red-500/80 text-white text-[10px] p-0.5 hover:bg-red-500">✕</button>
                </div>
              ))}
            </div>
          )}
        </section>

        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2">
            <label htmlFor="rname" className="label">Reporter name (optional)</label>
            <input id="rname" value={reporterName} onChange={e => setReporterName(e.target.value)} className={field} placeholder="Anonymous" />
          </div>
        </div>

        {error && <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</p>}

        <div className="flex items-center justify-between pt-2">
          <span className="text-[11px] text-slate-600">POST /api/v1/reports · M3 CV triage runs after upload</span>
          <button type="submit" disabled={busy} className="rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-50">
            {busy ? 'Submitting…' : 'Submit report'}
          </button>
        </div>
      </form>
    </div>
  )
}
