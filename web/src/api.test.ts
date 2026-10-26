import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useJson } from './api'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useJson', () => {
  it('never lets a slow older answer overwrite a newer one', async () => {
    vi.useFakeTimers()
    const answers: ((body: string) => void)[] = []
    // each call waits until the test answers it, unless it is cancelled first
    const fetchMock = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((resolve, reject) => {
          init.signal?.addEventListener('abort', () =>
            reject(new DOMException('aborted', 'AbortError')),
          )
          answers.push((body) => resolve(new Response(JSON.stringify(body))))
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useJson<string>('/api/headlines', 1000))
    await act(async () => vi.advanceTimersByTime(1000)) // the refresh starts a second request
    await act(async () => answers[1]('new'))
    await act(async () => answers[0]('old'))

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(result.current.data).toBe('new')
  })
})
