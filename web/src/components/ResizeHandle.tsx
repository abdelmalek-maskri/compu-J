import { useRef, type KeyboardEvent, type PointerEvent, type RefObject } from 'react'

type Props = {
  // the element both panels sit in; the left panel's width is measured from its left edge
  containerRef: RefObject<HTMLElement | null>
  width: number
  min: number
  // the reader keeps at least this much room
  keepRight: number
  onResize: (width: number) => void
  onReset: () => void
  onDragging: (dragging: boolean) => void
}

const STEP = 32

/** the line between the list and the reader: drag it, double-click it, or use the arrow keys */
export function ResizeHandle({ containerRef, width, min, keepRight, onResize, onReset, onDragging }: Props) {
  const dragging = useRef(false)

  const clamp = (next: number) => {
    const room = containerRef.current?.getBoundingClientRect().width ?? Infinity
    return Math.round(Math.max(min, Math.min(next, room - keepRight)))
  }

  const start = (e: PointerEvent<HTMLDivElement>) => {
    // the pointer stays with the handle even when it crosses the email's frame
    e.currentTarget.setPointerCapture?.(e.pointerId)
    dragging.current = true
    onDragging(true)
  }
  const move = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return
    const left = containerRef.current?.getBoundingClientRect().left ?? 0
    onResize(clamp(e.clientX - left))
  }
  const end = () => {
    if (!dragging.current) return
    dragging.current = false
    onDragging(false)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowLeft: -STEP, ArrowRight: STEP }[e.key]
    if (step) {
      e.preventDefault()
      onResize(clamp(width + step))
    } else if (e.key === 'Home') {
      e.preventDefault()
      onReset()
    }
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the panels (arrow keys, or double-click to reset)"
      aria-valuenow={width}
      aria-valuemin={min}
      tabIndex={0}
      onPointerDown={start}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      className="group hidden lg:block w-[7px] cursor-col-resize touch-none focus-visible:outline-none"
    >
      <div className="mx-auto h-full w-px bg-rule group-hover:w-[3px] group-hover:bg-accent group-focus-visible:w-[3px] group-focus-visible:bg-accent" />
    </div>
  )
}
