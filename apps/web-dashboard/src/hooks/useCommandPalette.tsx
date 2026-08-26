/* eslint-disable react-refresh/only-export-components */
// This file intentionally exports both the hook and its shared Command type.
import { useEffect, useRef, useState, useCallback, useMemo } from 'react'

export interface Command {
  id: string
  label: string
  description?: string
  shortcut?: string
  icon?: React.ReactNode
  action: () => void
  keywords?: string[]
  category?: string
}

interface UseCommandPaletteOptions {
  commands: Command[]
  onOpen?: () => void
  onClose?: () => void
}

export function useCommandPalette({ commands, onOpen, onClose }: UseCommandPaletteOptions) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const filtered = useMemo(() => {
    if (!query) return commands
    const q = query.toLowerCase()
    return commands.filter(c =>
      c.label.toLowerCase().includes(q) ||
      c.description?.toLowerCase().includes(q) ||
      c.keywords?.some(k => k.toLowerCase().includes(q)) ||
      c.shortcut?.toLowerCase().includes(q)
    )
  }, [commands, query])

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (!open) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setOpen(true)
        onOpen?.()
      }
      return
    }

    switch (e.key) {
      case 'Escape':
        e.preventDefault()
        setOpen(false)
        setQuery('')
        setSelectedIndex(0)
        onClose?.()
        break
      case 'ArrowDown':
        e.preventDefault()
        setSelectedIndex(i => Math.min(i + 1, filtered.length - 1))
        break
      case 'ArrowUp':
        e.preventDefault()
        setSelectedIndex(i => Math.max(i - 1, 0))
        break
      case 'Enter':
        e.preventDefault()
        if (filtered[selectedIndex]) {
          filtered[selectedIndex].action()
          setOpen(false)
          setQuery('')
          setSelectedIndex(0)
          onClose?.()
        }
        break
      default:
        if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) {
          setQuery(q => q + e.key.toLowerCase())
        } else if (e.key === 'Backspace') {
          setQuery(q => q.slice(0, -1))
        }
        break
    }
  }, [open, filtered, selectedIndex, onClose, onOpen])

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [open])

  return { open, setOpen, query, setQuery, filtered, selectedIndex, inputRef }
}

/** Renderless component — renders the palette UI when open */
export function CommandPalette({
  open,
  onClose,
  query,
  setQuery,
  filtered,
  selectedIndex,
  inputRef,
}: {
  open: boolean
  onClose: () => void
  query: string
  setQuery: (q: string) => void
  filtered: ReturnType<typeof useCommandPalette>['filtered']
  selectedIndex: number
  inputRef: React.RefObject<HTMLInputElement>
}) {
  const listRef = useRef<HTMLUListElement>(null)

  useEffect(() => {
    const item = listRef.current?.children[selectedIndex]
    item?.scrollIntoView({ block: 'nearest' })
  }, [selectedIndex, filtered.length])

  if (!open) return null

  return (
    <div className="cmd-palette" role="dialog" aria-modal="true" aria-label="Command palette">
      <div className="cmd-backdrop" onClick={onClose} />
      <div className="cmd-window animate-slide-up">
        <div className="relative flex items-center gap-3 border-b border-slate-700 px-4 py-3">
          <kbd className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-slate-800 px-1.5 text-[10px] font-mono text-slate-500">⌘</kbd>
          <kbd className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-slate-800 px-1.5 text-[10px] font-mono text-slate-500">K</kbd>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Type a command…"
            className="flex-1 bg-transparent text-sm text-slate-100 placeholder:text-slate-500 outline-none"
            autoComplete="off"
            spellCheck={false}
          />
          <span className="text-[11px] text-slate-500">{filtered.length} command{filtered.length !== 1 ? 's' : ''}</span>
        </div>

        <div className="max-h-96 overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="p-8 text-center text-slate-500">No commands match</div>
          ) : (
            <ul ref={listRef} role="listbox" aria-label="Commands">
              {filtered.map((cmd, i) => (
                <li key={cmd.id} role="option" aria-selected={i === selectedIndex}>
                  <button
                    onClick={() => { cmd.action(); onClose() }}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-left text-sm transition ${
                      i === selectedIndex
                        ? 'bg-emerald-500/10 text-emerald-300'
                        : 'text-slate-300 hover:bg-slate-800/50'
                    }`}
                  >
                    {cmd.icon && <span className="text-base">{cmd.icon}</span>}
                    <div className="flex-1 min-w-0">
                      <span className="font-medium truncate">{cmd.label}</span>
                      {cmd.description && <span className="block text-[11px] text-slate-500 truncate">{cmd.description}</span>}
                    </div>
                    {cmd.shortcut && <kbd className="px-1.5 py-0.5 text-[10px] font-mono text-slate-500 rounded bg-slate-800">{cmd.shortcut}</kbd>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

/** Helper to build commands from categories */
export function categorizeCommands(commands: Command[]) {
  const cats = new Map<string, Command[]>()
  commands.forEach(c => {
    const cat = c.category || 'General'
    if (!cats.has(cat)) cats.set(cat, [])
    cats.get(cat)!.push(c)
  })
  return Array.from(cats.entries()).map(([category, cmds]) => ({ category, commands: cmds }))
}