import { memo } from 'react'
import type { ReactNode, HTMLAttributes } from 'react'

/** Generic skeleton primitives */
export const Skeleton = memo(function Skeleton({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`skeleton ${className}`} {...props} />
})

export const SkeletonCard = memo(function SkeletonCard({ className = '' }: { className?: string }) {
  return (
    <div className={`skeleton-card ${className}`} aria-hidden="true" />
  )
})

export const SkeletonRow = memo(function SkeletonRow({ className = '', cols = 4 }: { className?: string; cols?: number }) {
  return (
    <div className={`grid gap-4 ${className}`} style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }} aria-hidden="true">
      {[...Array(cols)].map((_, i) => <Skeleton key={i} className="h-10 w-full rounded-lg" />)}
    </div>
  )
})

export const SkeletonTable = memo(function SkeletonTable({ rows = 5, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40" aria-hidden="true">
      <div className="bg-slate-900/60 px-4 py-3">
        <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
          {[...Array(cols)].map((_, i) => <Skeleton key={i} className="h-3 w-3/4 rounded" />)}
        </div>
      </div>
      <div className="divide-y divide-slate-800 bg-slate-900/40">
        {[...Array(rows)].map((_, r) => (
          <div key={r} className="grid gap-4 px-4 py-3" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
            {[...Array(cols)].map((_, c) => <Skeleton key={c} className="h-4 w-3/4 rounded" />)}
          </div>
        ))}
      </div>
    </div>
  )
})

export const SkeletonCardGrid = memo(function SkeletonCardGrid({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4" aria-hidden="true">
      {[...Array(count)].map((_, i) => (
        <div key={i} className="skeleton-card p-4" />
      ))}
    </div>
  )
})

export const SkeletonAlertFeed = memo(function SkeletonAlertFeed({ count = 4 }: { count?: number }) {
  return (
    <div className="space-y-3" aria-hidden="true">
      {[...Array(count)].map((_, i) => (
        <div key={i} className="flex items-start gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <Skeleton className="mt-0.5 h-5 w-5 rounded-md" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="h-4 w-1/4 rounded" />
            <Skeleton className="h-3 w-3/4 rounded" />
          </div>
          <Skeleton className="shrink-0 h-4 w-16 rounded" />
        </div>
      ))}
    </div>
  )
})

export const SkeletonSensorGrid = memo(function SkeletonSensorGrid({ count = 5 }: { count?: number }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-hidden="true">
      {[...Array(count)].map((_, i) => (
        <div key={i} className="skeleton-card p-4">
          <div className="flex items-center justify-between">
            <Skeleton className="h-4 w-24 rounded" />
            <Skeleton className="h-2 w-2 rounded-full" />
          </div>
          <Skeleton className="mt-2 h-3 w-3/4 rounded" />
        </div>
      ))}
    </div>
  )
})

/** Empty state with illustration & CTA */
export interface EmptyStateProps {
  icon: ReactNode
  title: string
  description: string
  action?: { label: string; onClick: () => void }
  className?: string
}

export function EmptyState({ icon, title, description, action, className = '' }: EmptyStateProps) {
  return (
    <div className={`empty-state ${className}`} role="status" aria-live="polite">
      <div className="empty-state-icon" aria-hidden="true">{icon}</div>
      <div>
        <h3 className="empty-state-title">{title}</h3>
        <p className="empty-state-desc">{description}</p>
        {action && (
          <button onClick={action.onClick} className="mt-3 btn-primary" type="button">
            {action.label}
          </button>
        )}
      </div>
    </div>
  )
}

/** Loading spinner */
export function Spinner({ size = 'md', className = '' }: { size?: 'sm' | 'md' | 'lg'; className?: string }) {
  const sizeMap = { sm: 'h-4 w-4', md: 'h-6 w-6', lg: 'h-8 w-8' }
  return (
    <svg className={`${sizeMap[size]} animate-spin text-emerald-400 ${className}`} viewBox="0 0 24 24" aria-hidden="true">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" fill="none" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
    </svg>
  )
}