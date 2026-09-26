import React from 'react'
import { useState } from 'react'
import type { KeyboardEvent } from 'react'
import { EmptyState } from '@/components/Skeleton'
import type { CitizenReport } from '@/types'
import { fetchPowerfulProblems, triggerProblemSearchAndReport } from '@/services/api'

const STATUS_STYLE: Record<string, string> = {
  submitted: 'badge-submitted',
  verified: 'badge-verified',
  assigned: 'badge-assigned',
  resolved: 'badge-resolved',
  live_internet: 'inline-flex items-center gap-1 rounded-full border border-sky-400/30 bg-sky-500/15 px-2 py-0.5 text-[11px] font-bold text-sky-300',
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

export default function ReportsTable({ reports, onOpenDetail }: { reports: CitizenReport[]; onOpenDetail: (r: CitizenReport) => void }) {
  const [sortKey, setSortKey] = useState<keyof CitizenReport>('createdAt')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [filterStatus, setFilterStatus] = useState<string>('all')
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [searchQ, setSearchQ] = useState('landslide in North East India')
  const [searching, setSearching] = useState(false)
  const [powerfulResults, setPowerfulResults] = useState<CitizenReport[] | null>(null)
  const [searchMsg, setSearchMsg] = useState<string | null>(null)

  const liveCount = reports.filter((r) => r.status === 'live_internet' || ['GDACS','ReliefWeb','Open-Meteo','USGS','EONET','GNews','Tavily','Brave'].includes(r.source ?? '')).length
  const nerLiveCount = reports.filter((r) => {
    const v = `${r.description ?? ''} ${r.district} ${r.village} ${r.country ?? ''}`.toLowerCase()
    if (r.latitude != null && r.longitude != null && r.latitude >= 21.9 && r.latitude <= 29.7 && r.longitude >= 88 && r.longitude <= 97.5) return true
    return ['arunachal','assam','manipur','meghalaya','mizoram','nagaland','sikkim','tripura','itanagar','dispur','imphal','shillong','aizawl','kohima','gangtok','agartala'].some(t=>v.includes(t))
  }).length
  if (reports.length === 0) {
    return (
      <EmptyState
        icon="📋"
        title="No reports yet"
        description="Live NE reports (GDACS + ReliefWeb + Open-Meteo NE watch, NE-bbox gated) and citizen reports will appear here. Map shows only North Eastern states. API: /api/v1/live/reports"
      />
    )
  }

  const filtered = reports
    .filter(r => filterStatus === 'all' || r.status === filterStatus)
    .sort((a, b) => {
      const av = a[sortKey] ?? ''
      const bv = b[sortKey] ?? ''
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })

  const statuses = ['all', ...new Set(reports.map(r => r.status))]

  return (
    <div className="space-y-4">
      {liveCount > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-sky-500/20 bg-sky-500/10 px-3 py-2 text-xs">
          <span className="h-2 w-2 animate-pulse rounded-full bg-sky-400" />
          <span className="font-semibold text-sky-300">North East India only — {liveCount} live NE reports ({nerLiveCount} NE-validated)</span>
          <span className="text-sky-300/70">Tavily/Brave + GDACS/ReliefWeb + Open-Meteo NE watch · NE bbox 21.9–29.7°N 88–97.5°E + heuristic problem_tags · auto-refresh 60s</span>
          <a href="/api/v1/live/reports?limit=12" target="_blank" rel="noreferrer" className="ml-auto text-sky-300 underline decoration-sky-400/30 hover:text-sky-200">api/live/reports ↗</a>
          <a href="/api/v1/live/engine/status" target="_blank" rel="noreferrer" className="text-sky-300 underline decoration-sky-400/30 hover:text-sky-200">engine/status ↗</a>
        </div>
      )}
      {/* Powerful Problem Search — searches live internet and adds to reports */}
      <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-amber-300">
          <span>🔍</span> Powerful Problem Search (Tavily/Brave + GDACS + heuristic → reports)
        </div>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            placeholder="e.g. landslide, road blocked, bridge collapse"
            className="input flex-1 text-sm"
            disabled={searching}
          />
          <button
            disabled={searching || !searchQ.trim()}
            onClick={async () => {
              setSearching(true); setSearchMsg(null); setPowerfulResults(null)
              try {
                const items = await fetchPowerfulProblems(searchQ, 8)
                setPowerfulResults(items)
                setSearchMsg(items.length ? `Found ${items.length} NE problems (not yet saved)` : 'No NE problems found — try broader query')
              } catch { setSearchMsg('Search failed — check TAVILY_API_KEY/BRAVE_SEARCH_API_KEY or gateway') }
              finally { setSearching(false) }
            }}
            className="btn-ghost border border-amber-500/30 bg-amber-500/20 text-amber-200 hover:bg-amber-500/30 text-xs px-3 py-2 rounded-lg disabled:opacity-50"
          >
            {searching ? 'Searching…' : 'Search'}
          </button>
          <button
            disabled={searching || !searchQ.trim()}
            onClick={async () => {
              setSearching(true); setSearchMsg(null); setPowerfulResults(null)
              try {
                const { created, items } = await triggerProblemSearchAndReport(searchQ, 6, true)
                setPowerfulResults(items)
                setSearchMsg(created ? `✓ Created ${created} new reports from search — they now appear in Reports + Map` : 'No new problems — all were duplicates or non-NE')
                // Refresh page data by reloading (reports will appear on next fetch)
                if (created) setTimeout(() => window.location.reload(), 1200)
              } catch { setSearchMsg('Search & add failed — check API keys / gateway') }
              finally { setSearching(false) }
            }}
            className="btn-primary bg-amber-500 hover:bg-amber-600 text-white text-xs px-3 py-2 rounded-lg font-semibold disabled:opacity-50"
          >
            Search &amp; Add to Reports
          </button>
        </div>
        {searchMsg && <div className="text-xs text-amber-200/80">{searchMsg}</div>}
        {powerfulResults && powerfulResults.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2">
            {powerfulResults.slice(0, 6).map((r) => (
              <div key={r.id} className="rounded-lg border border-amber-500/20 bg-slate-900/60 p-2 text-xs">
                <div className="font-semibold text-slate-200 truncate">{r.code} — {r.reportType} <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded-full bg-sky-500/20 text-sky-300 border border-sky-400/20">{r.source}</span></div>
                <div className="text-slate-400 truncate">{r.district} · {r.severity} {r.confidence ? `· conf ${r.confidence.toFixed(2)}` : ''}</div>
                <div className="text-slate-500 line-clamp-2 mt-1">{r.description?.slice(0, 140)}</div>
                {r.problem_tags && r.problem_tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {r.problem_tags.slice(0, 4).map((t) => <span key={t} className="px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/20 text-[10px]">{t}</span>)}
                  </div>
                )}
                {r.url && <a href={r.url} target="_blank" rel="noreferrer" className="text-sky-400 underline text-[11px]">source ↗</a>}
              </div>
            ))}
          </div>
        )}
        <div className="text-[11px] text-amber-200/60">Powerful search uses live_engine heuristic (problem_tags, confidence) + NE bbox 21.9–29.7°N 88–97.5°E. Requires TAVILY_API_KEY/BRAVE_SEARCH_API_KEY for web results, else falls back to GDACS/ReliefWeb. “Search & Add” inserts into citizen_report (status submitted) → visible in table + map.</div>
      </div>
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row items-center gap-3">
        <select
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
          className="input w-auto"
          aria-label="Filter by status"
        >
          {statuses.map(s => <option key={s} value={s}>{s === 'all' ? 'All Statuses' : s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
        </select>
        <div className="flex items-center gap-2 ml-auto">
          <span className="text-xs text-slate-500">Sort by:</span>
          <select
            value={sortKey}
            onChange={e => setSortKey(e.target.value as keyof CitizenReport)}
            className="input w-auto"
          >
            <option value="createdAt">Date</option>
            <option value="priorityScore">Priority</option>
            <option value="reportType">Type</option>
            <option value="status">Status</option>
          </select>
          <button onClick={() => setSortDir(sortDir === 'asc' ? 'desc' : 'asc')} className="btn-ghost btn-icon p-1.5" aria-label="Toggle sort direction">
            {sortDir === 'asc' ? '↑' : '↓'}
          </button>
        </div>
      </div>

      <div className="overflow-x-auto sm:overflow-visible rounded-xl border border-slate-800">
        <table className="w-full sm:w-auto text-sm">
          <thead>
            <tr className="table-header">
              <th className="px-4 py-3 cursor-pointer hover:text-slate-300 select-none sm:pr-6" onClick={() => { setSortKey('code'); setSortDir(sortKey === 'code' && sortDir === 'asc' ? 'desc' : 'asc') }}>
                Code {sortKey === 'code' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
              </th>
              <th className="px-4 py-3 cursor-pointer hover:text-slate-300 select-none sm:pr-6" onClick={() => { setSortKey('reportType'); setSortDir(sortKey === 'reportType' && sortDir === 'asc' ? 'desc' : 'asc') }}>
                Type {sortKey === 'reportType' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
              </th>
              <th className="px-4 py-3">Location</th>
              <th className="px-4 py-3 cursor-pointer hover:text-slate-300 select-none sm:pr-6" onClick={() => { setSortKey('priorityScore'); setSortDir(sortKey === 'priorityScore' && sortDir === 'asc' ? 'desc' : 'asc') }}>
                Priority {sortKey === 'priorityScore' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
              </th>
              <th className="px-4 py-3 cursor-pointer hover:text-slate-300 select-none sm:pr-6" onClick={() => { setSortKey('status'); setSortDir(sortKey === 'status' && sortDir === 'asc' ? 'desc' : 'asc') }}>
                Status {sortKey === 'status' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
              </th>
              <th className="px-4 py-3 cursor-pointer hover:text-slate-300 select-none sm:pr-6" onClick={() => { setSortKey('createdAt'); setSortDir(sortKey === 'createdAt' && sortDir === 'asc' ? 'desc' : 'asc') }}>
                Submitted {sortKey === 'createdAt' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
              </th>
              <th className="px-4 py-3 text-right sm:pr-6">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 bg-slate-900/40">
            {filtered.map(r => (
              <React.Fragment key={r.id}>
                <tr
                  tabIndex={0}
                  role="row"
                  aria-expanded={expandedIds.has(r.id)}
                  className={`table-row hover:bg-slate-800/40 transition transform-gpu hover:-translate-y-0.5 ${expandedIds.has(r.id) ? 'sm:grid grid-cols-6 gap-4' : ''}`}
                  onClick={() => setExpandedIds(prev => {
                    const next = new Set(prev)
                    if (next.has(r.id)) next.delete(r.id)
                    else next.add(r.id)
                    return next
                  })}
                  onKeyDown={(e: KeyboardEvent) => {
                    if (e.key === 'Enter') {
                      onOpenDetail(r)
                    }
                    if (e.key === ' ' || e.key === 'Spacebar') {
                      e.preventDefault()
                      setExpandedIds(prev => {
                        const next = new Set(prev)
                        if (next.has(r.id)) next.delete(r.id)
                        else next.add(r.id)
                        return next
                      })
                    }
                  }}
                >
                  <td className="px-4 py-3 font-mono text-xs whitespace-nowrap sm:col-span-2">
                    <span className="flex items-center gap-1.5">
                      {r.code}
                      {r.source && r.source !== 'Citizen' && (
                        <span className="rounded-full border border-sky-400/30 bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-bold text-sky-300">{r.source}</span>
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-3 sm:col-span-2">
                    <span className="flex items-center gap-1.5 capitalize">
                      <span aria-hidden="true">{TYPE_ICON[r.reportType] || (r.source === 'GDACS' ? '🌐' : r.source === 'ReliefWeb' ? '📰' : r.source === 'Tavily' ? '🔍' : r.source === 'Brave' ? '🦁' : '📝')}</span>
                      {r.reportType}
                    </span>
                    {r.problem_tags && r.problem_tags.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {r.problem_tags.slice(0, 3).map((t) => <span key={t} className="px-1 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/20 text-[10px]">{t}</span>)}
                        {r.confidence != null && <span className="px-1 py-0.5 rounded-full bg-slate-700 text-slate-300 text-[10px]">conf {r.confidence.toFixed(2)}</span>}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium">{r.village}</div>
                    <div className="text-xs text-slate-500">{r.district}</div>
                    {r.country && <div className="text-[11px] text-slate-600">{r.country}</div>}
                  </td>
                  <td className="px-4 py-3 font-semibold text-orange-400">{r.priorityScore}</td>
                  <td className="px-4 py-3">
                    <span className={STATUS_STYLE[r.status] ?? 'badge-submitted'}>{r.status}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{new Date(r.createdAt).toLocaleString()}</td>
                  <td className="px-4 py-3 text-right">
                    <span className="inline-flex items-center gap-1">
                      {r.url && (
                        <a href={r.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="rounded-lg p-1.5 text-sky-400 hover:bg-sky-500/10" aria-label={`Open live source for ${r.code}`} title={r.url}>↗</a>
                      )}
                      <button
                        onClick={() => onOpenDetail(r)}
                        className="btn-ghost btn-icon p-1.5 rounded-lg text-slate-400 hover:text-sky-400 hover:bg-sky-500/10"
                        aria-label={`View report ${r.code}`}
                      >
                        👁
                      </button>
                    </span>
                  </td>
                </tr>
                {expandedIds.has(r.id) && (
                  <tr>
                    <td colSpan={7} className="px-4 py-3 bg-slate-800/30">
                      <div className="space-y-2 text-xs">
                        <div className="text-slate-300 leading-relaxed">{r.description}</div>
                        {r.problem_tags && r.problem_tags.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            <span className="text-slate-500">problems:</span>
                            {r.problem_tags.map((t) => <span key={t} className="px-2 py-1 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/20 text-[11px]">{t}</span>)}
                            {r.confidence != null && <span className="px-2 py-1 rounded-full bg-slate-700 text-slate-300 text-[11px]">confidence {r.confidence.toFixed(2)}</span>}
                          </div>
                        )}
                        <div className="flex flex-wrap gap-3 text-slate-500">
                          <span>Source: <span className="text-slate-300">{r.source}</span></span>
                          {r.url && <a href={r.url} target="_blank" rel="noreferrer" className="text-sky-400 underline" onClick={(e)=>e.stopPropagation()}>{r.url.slice(0,60)}↗</a>}
                          <span className="ml-auto">{new Date(r.createdAt).toLocaleString()} · {r.district} / {r.village}</span>
                        </div>
                        <div className="flex gap-2 justify-end">
                          <button onClick={() => onOpenDetail(r)} className="btn-ghost text-sky-400 hover:text-sky-300 text-xs px-3 py-1 rounded-lg border border-sky-500/20">👁 View details</button>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
