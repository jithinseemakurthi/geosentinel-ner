import { useEffect } from 'react'

/**
 * Modal behavior: Escape closes, background scroll is locked while open.
 * Call before any conditional early-return so hooks run unconditionally.
 */
export function useDismissable(open: boolean, onClose: () => void): void {
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prevOverflow
    }
  }, [open])
}
