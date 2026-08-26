import React from 'react'
import { useState } from 'react'
import type { KeyboardEvent } from 'react'
import { EmptyState } from '@/components/Skeleton'
import type { CitizenReport } from '@/types'

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

export default function ReportsTable({ reports, onOpenDetail }: { reports: CitizenReport[]; onOpenDetail: (r: CitizenReport) => void }) {
  const [sortKey, setSortKey] = useState<keyof CitizenReport>('createdAt')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [filterStatus, setFilterStatus] = useState<string>('all')
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  if (reports.length === 0) {
    return (
      <EmptyState
        icon="📋"
        title="No citizen reports yet"
        description="Reports from the mobile app and web portal will appear here in realtime."
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
                    next.has(r.id) ? next.delete(r.id) : next.add(r.id)
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
                        next.has(r.id) ? next.delete(r.id) : next.add(r.id)
                        return next
                      })
                    }
                  }}
                >
                  <td className="px-4 py-3 font-mono text-xs whitespace-nowrap sm:col-span-2">{r.code}</td>
                  <td className="px-4 py-3 sm:col-span-2">
                    <span className="flex items-center gap-1.5 capitalize">
                      <span aria-hidden="true">{TYPE_ICON[r.reportType] || '📝'}</span>
                      {r.reportType}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium">{r.village}</div>
                    <div className="text-xs text-slate-500">{r.district}</div>
                  </td>
                  <td className="px-4 py-3 font-semibold text-orange-400">{r.priorityScore}</td>
                  <td className="px-4 py-3">
                    <span className={STATUS_STYLE[r.status]}>{r.status}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{new Date(r.createdAt).toLocaleString()}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => onOpenDetail(r)}
                      className="btn-ghost btn-icon p-1.5 rounded-lg text-slate-400 hover:text-sky-400 hover:bg-sky-500/10"
                      aria-label={`View report ${r.code}`}
                    >
                      👁
                    </button>
                  </td>
                </tr>
                {expandedIds.has(r.id) && (
                  <tr className="sm:grid grid-cols-6 gap-4 text-xs text-slate-400 border-t pt-3">
                    <td colSpan={2} className="font-medium py-2">Village</td>
                    <td colSpan={2} className="text-right py-2">District</td>
                    <td colSpan={2} className="py-2">Priority</td>
                    <td colSpan={2} className="py-2">
                      <span className={STATUS_STYLE[r.status]}>{r.status}</span>
                    </td>
                    <td colSpan={2} className="py-2">
                      <small>{new Date(r.createdAt).toLocaleString()}</small>
                    </td>
                    <td colSpan={2} className="py-2 text-right">
                      <button
                        onClick={() => onOpenDetail(r)}
                        className="btn-ghost text-sky-500 hover:text-sky-400"
                        aria-label={`View full report ${r.code}`}
                      >
                        👁 View details
                      </button>
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