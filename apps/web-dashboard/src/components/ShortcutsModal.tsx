import { useDismissable } from '@/hooks/useDismissable'

const GROUPS: { title: string; items: [string, string][] }[] = [
  {
    title: 'Navigation',
    items: [
      ['G then O', 'Overview'],
      ['G then M', 'Live Map'],
      ['G then R', 'Reports'],
      ['G then S', 'Sensors'],
    ],
  },
  {
    title: 'Actions',
    items: [
      ['N', 'New citizen report'],
      ['T', 'Toggle light / dark theme'],
      ['Ctrl K', 'Command palette'],
    ],
  },
  {
    title: 'General',
    items: [
      ['?', 'Show keyboard shortcuts'],
      ['Esc', 'Close dialogs'],
    ],
  },
]

export default function ShortcutsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  useDismissable(open, onClose)

  if (!open) return null

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="shortcuts-title" className="fixed inset-0 z-[60] grid place-items-center p-4">
      <button aria-label="Close shortcuts" onClick={onClose} className="absolute inset-0 bg-slate-950/85" />
      <div className="relative w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl animate-slide-up max-h-[85vh] overflow-y-auto">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="shortcuts-title" className="text-base font-bold">Keyboard Shortcuts</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg px-2 py-1 text-slate-500 transition hover:bg-slate-800 hover:text-slate-200"
          >
            ✕
          </button>
        </div>
        <div className="space-y-5">
          {GROUPS.map(group => (
            <section key={group.title}>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{group.title}</h3>
              <ul className="space-y-1.5">
                {group.items.map(([keys, desc]) => (
                  <li key={keys} className="flex items-center justify-between gap-4 rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2">
                    <span className="text-sm text-slate-300">{desc}</span>
                    <kbd className="shrink-0 rounded-md border border-slate-700 bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-400">{keys}</kbd>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}
