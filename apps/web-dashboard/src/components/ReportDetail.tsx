import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { CitizenReport } from '@/types'
import { useMap } from '@/hooks/useMap'
import { useDismissable } from '@/hooks/useDismissable'
import { districtCenter } from '@/lib/districts'

const STATUS_STYLE: Record<string, string> = {
  submitted: 'badge-submitted',
  verified: 'badge-verified',
  assigned: 'badge-assigned',
  resolved: 'badge-resolved',
}

const TYPE_ICON: Record<string, string> = {
  crack: '⚡',
  bulge: '📈',
  subsidence: '📉',
  debris: '🪨',
  rockfall: '🗿',
  road_block: '🚧',
  excavation: '🚜',
  water_spring: '💧',
  other: '❓',
}

export function ReportDetail({
  report,
  onClose,
  onStatusChange,
}: {
  report: CitizenReport | null
  onClose: () => void
  onStatusChange?: (id: string, status: string) => void
}) {
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const markerRef = useRef<maplibregl.Marker | null>(null)
  const c = districtCenter(report?.district)
  const { map } = useMap({ containerRef: mapContainerRef, center: [c.lng + 0.02, c.lat + 0.02], zoom: 13 })
  useDismissable(report !== null, onClose)

  useEffect(() => {
    if (!report || !mapContainerRef.current || !map) return
    const cc = districtCenter(report.district)
    if (markerRef.current) {
      markerRef.current.remove()
      markerRef.current = null
    }
    const el = document.createElement('div')
    el.style.cssText = 'width:18px;height:18px;border-radius:50%;background:#38BDF8;border:3px solid #0d1117;box-shadow:0 0 12px #38BDF8'
    const marker = new maplibregl.Marker({ element: el })
      .setLngLat([cc.lng, cc.lat])
      .setPopup(new maplibregl.Popup({ offset: 12 }).setHTML(`<b>${report.code}</b><br/>${report.reportType} · ${report.severity}`))
      .addTo(map)
    markerRef.current = marker
    return () => { markerRef.current?.remove(); markerRef.current = null }
  }, [report, map])

  if (!report) return null

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="report-detail-title" className="fixed inset-0 z-50 flex justify-end">
      <button aria-label="Close" onClick={onClose} className="flex-1 bg-slate-950/80" />
      <aside className="flex flex-col w-full max-w-2xl border-l border-slate-800 bg-slate-900 shadow-2xl overflow-hidden">
        <header className="flex items-start justify-between gap-4 border-b border-slate-800 p-5">
          <div className="flex items-center gap-3 min-w-0">
            <span className="grid h-10 w-10 place-items-center rounded-lg bg-emerald-500/15 text-lg" aria-hidden="true">
              {TYPE_ICON[report.reportType] || '📝'}
            </span>
            <div className="min-w-0">
              <div className="flex items-baseline gap-2">
                <span id="report-detail-title" className="font-mono text-sm">{report.code}</span>
                <span className={STATUS_STYLE[report.status]}>{report.status}</span>
              </div>
              <p className="mt-1 truncate text-sm text-slate-400">{report.reportType} · {report.severity}</p>
            </div>
          </div>
          <button onClick={onClose} className="flex-shrink-0 rounded-lg px-2 py-1.5 text-slate-500 transition hover:bg-slate-800 hover:text-slate-200">
            ✕
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5 space-y-5">
          {/* Map */}
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Location</h3>
            <div className="relative h-64 min-h-[256px] overflow-hidden rounded-xl border border-slate-800">
              <div ref={mapContainerRef} className="absolute inset-0" />
            </div>
            <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
              <span>{report.village} · {report.district}</span>
              <button className="btn-ghost btn-icon p-1.5 text-slate-400 hover:text-slate-200" title="Open in full map">
                ⛶
              </button>
            </div>
          </section>

          {/* Details */}
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Observation</h3>
            <p className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm leading-relaxed text-slate-300 whitespace-pre-wrap">
              {report.description || 'No description provided.'}
            </p>
          </section>

          {/* Metadata grid */}
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Metadata</h3>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
                <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">Priority Score</dt>
                <dd className="mt-1 text-2xl font-bold text-orange-400">{report.priorityScore}</dd>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
                <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">Type</dt>
                <dd className="mt-1 capitalize text-slate-300">{report.reportType}</dd>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
                <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">Severity</dt>
                <dd className="mt-1 capitalize text-slate-300">{report.severity}</dd>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
                <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">Submitted</dt>
                <dd className="mt-1 text-slate-300">{new Date(report.createdAt).toLocaleString()}</dd>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
                <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">Reporter</dt>
                <dd className="mt-1 text-slate-300">{report.reporterName || 'Anonymous'}</dd>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
                <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">Location</dt>
                <dd className="mt-1 text-slate-300 truncate">{report.village} · {report.district}</dd>
              </div>
            </dl>
          </section>

          {/* Status timeline */}
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Status Timeline</h3>
            <ol className="space-y-3">
              <li className="relative pl-6 before:absolute before:left-1 before:top-1 before:h-2 before:w-2 before:rounded-full before:bg-emerald-500">
                <div className="text-sm font-medium text-slate-300">Report submitted</div>
                <div className="text-xs text-slate-500">{new Date(report.createdAt).toLocaleString()}</div>
              </li>
              {(report.status === 'verified' || report.status === 'assigned' || report.status === 'resolved') && (
                <li className="relative pl-6 before:absolute before:left-1 before:top-1 before:h-2 before:w-2 before:rounded-full before:bg-sky-500">
                  <div className="text-sm font-medium text-slate-300">Verified by officer</div>
                  <div className="text-xs text-slate-500">—</div>
                </li>
              )}
              {(report.status === 'assigned' || report.status === 'resolved') && (
                <li className="relative pl-6 before:absolute before:left-1 before:top-1 before:h-2 before:w-2 before:rounded-full before:bg-amber-400">
                  <div className="text-sm font-medium text-slate-300">Assigned to field team</div>
                  <div className="text-xs text-slate-500">—</div>
                </li>
              )}
              {report.status === 'resolved' && (
                <li className="relative pl-6 before:absolute before:left-1 before:top-1 before:h-2 before:w-2 before:rounded-full before:bg-emerald-500">
                  <div className="text-sm font-medium text-slate-300">Resolved</div>
                  <div className="text-xs text-slate-500">—</div>
                </li>
              )}
            </ol>
          </section>
        </div>

        <footer className="border-t border-slate-800 p-5 space-y-3">
          {onStatusChange && (
            <select
              onChange={e => onStatusChange(report.id, e.target.value)}
              defaultValue={report.status}
              className="w-full rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2.5 text-sm"
            >
              <option value="submitted">Submitted</option>
              <option value="verified">Verified</option>
              <option value="assigned">Assigned</option>
              <option value="resolved">Resolved</option>
            </select>
          )}
          <div className="flex gap-2">
            <button className="btn-ghost flex-1">Export PDF</button>
            <button className="btn-ghost flex-1">Share</button>
            <button className="btn-primary flex-1">Update Status</button>
          </div>
        </footer>
      </aside>
    </div>
  )
}