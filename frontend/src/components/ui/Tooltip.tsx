import {
  cloneElement,
  useEffect,
  useId,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react'
import { Info } from './icons'

export type TooltipSide = 'top' | 'bottom'

const sides: Record<TooltipSide, string> = {
  top: 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
  bottom: 'top-full left-1/2 -translate-x-1/2 mt-1.5',
}

/** Where explanation lives. Wrap one focusable element; the text shows on
 * hover and keyboard focus and is tied to the element with
 * `aria-describedby`. Keep it short: a tooltip is a hint, not documentation. */
export function Tooltip({
  content,
  side = 'top',
  wide = false,
  children,
}: {
  content: ReactNode
  side?: TooltipSide
  /** Allows wrapping onto several lines (for a sentence or two). */
  wide?: boolean
  children: ReactElement<Record<string, unknown>>
}) {
  const id = useId()
  const [shown, setShown] = useState(false)

  useEffect(() => {
    if (!shown) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShown(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [shown])

  const trigger = cloneElement(children, {
    'aria-describedby': shown ? id : undefined,
  })

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setShown(true)}
      onMouseLeave={() => setShown(false)}
      onFocus={() => setShown(true)}
      onBlur={() => setShown(false)}
    >
      {trigger}
      {shown && (
        <span
          id={id}
          role="tooltip"
          className={`pointer-events-none absolute z-50 rounded-md bg-fg px-2 py-1 text-xs font-medium text-canvas shadow-sm ${
            wide ? 'w-max max-w-64 whitespace-normal' : 'whitespace-nowrap'
          } ${sides[side]}`}
        >
          {content}
        </span>
      )}
    </span>
  )
}

/** A small (i) that explains the thing beside it. Hover or focus shows the
 * text; a tap toggles it on touch screens. The default home for any sentence
 * that used to sit under a heading or field as standing help text. */
export function InfoTip({
  children,
  label = 'More information',
  side = 'top',
}: {
  children: ReactNode
  label?: string
  side?: TooltipSide
}) {
  const id = useId()
  const [pinned, setPinned] = useState(false)
  const [hovered, setHovered] = useState(false)
  const shown = pinned || hovered

  useEffect(() => {
    if (!pinned) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPinned(false)
    }
    const onDown = (e: PointerEvent) => {
      if (!(e.target as Element | null)?.closest(`[data-infotip="${id}"]`))
        setPinned(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown)
    }
  }, [pinned, id])

  return (
    <span
      data-infotip={id}
      className="relative inline-flex align-middle"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        aria-label={label}
        aria-describedby={shown ? id : undefined}
        aria-expanded={pinned}
        onClick={() => setPinned((p) => !p)}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
        // 24px hit area around a 14px glyph: it sits inline with text, so it
        // can't be 32px without stretching the line.
        className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-full text-fg-subtle transition-colors hover:text-fg focus-visible:outline-2 focus-visible:outline-accent"
      >
        <Info size={14} aria-hidden="true" />
      </button>
      {shown && (
        <span
          id={id}
          role="tooltip"
          className={`absolute z-50 w-max max-w-64 whitespace-normal rounded-md bg-fg px-2 py-1 text-left text-xs font-normal text-canvas shadow-sm ${sides[side]}`}
        >
          {children}
        </span>
      )}
    </span>
  )
}
