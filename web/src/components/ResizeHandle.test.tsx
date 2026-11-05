import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ResizeHandle } from './ResizeHandle'

// a container 1000 pixels wide, starting 100 pixels from the left of the window
const container = {
  current: { getBoundingClientRect: () => ({ left: 100, width: 1000 }) } as unknown as HTMLElement,
}

function handle(width = 400) {
  const props = { onResize: vi.fn(), onReset: vi.fn(), onDragging: vi.fn() }
  render(<ResizeHandle containerRef={container} width={width} min={288} keepRight={384} {...props} />)
  return { ...props, line: screen.getByRole('separator') }
}

describe('ResizeHandle', () => {
  it('follows the pointer while dragging, within the limits', () => {
    const { line, onResize, onDragging } = handle()
    fireEvent.pointerDown(line, { pointerId: 1, clientX: 500 })
    fireEvent.pointerMove(line, { pointerId: 1, clientX: 600 })
    fireEvent.pointerMove(line, { pointerId: 1, clientX: 1050 })
    fireEvent.pointerMove(line, { pointerId: 1, clientX: 150 })
    fireEvent.pointerUp(line, { pointerId: 1 })
    // 600 - 100 = 500; then capped so the reader keeps 384 of 1000; then the minimum
    expect(onResize.mock.calls).toEqual([[500], [616], [288]])
    expect(onDragging.mock.calls).toEqual([[true], [false]])
  })

  it('ignores the pointer when not dragging', () => {
    const { line, onResize } = handle()
    fireEvent.pointerMove(line, { pointerId: 1, clientX: 600 })
    expect(onResize).not.toHaveBeenCalled()
  })

  it('moves with the arrow keys and resets with Home or a double click', async () => {
    const { line, onResize, onReset } = handle(400)
    line.focus()
    await userEvent.keyboard('{ArrowRight}{ArrowLeft}{Home}')
    expect(onResize.mock.calls).toEqual([[432], [368]])
    await userEvent.dblClick(line)
    expect(onReset).toHaveBeenCalledTimes(2)
  })
})
