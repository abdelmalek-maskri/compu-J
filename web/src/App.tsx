import { useEffect, useMemo, useRef, useState } from 'react'
import { useJson, type Email, type Tags } from './api'
import { EmailList } from './components/EmailList'
import { FilterPanel } from './components/FilterPanel'
import { Reader } from './components/Reader'
import { Ticker } from './components/Ticker'
import { byDate, matches, NO_FILTERS, OTHER, type Filters } from './filters'

/** the open email lives in the address (#035300), so a link or a reload keeps it */
function useHashId(): [string | null, (id: string | null) => void] {
  const read = () => window.location.hash.slice(1) || null
  const [id, setId] = useState(read)
  useEffect(() => {
    const onHash = () => setId(read())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const select = (next: string | null) => {
    history.replaceState(null, '', next ? `#${next}` : window.location.pathname)
    setId(next)
  }
  return [id, select]
}

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))

export default function App() {
  const emails = useJson<Email[]>('/api/emails')
  const { data: tags } = useJson<Tags>('/api/tags')
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const [selectedId, setSelectedId] = useHashId()
  const searchRef = useRef<HTMLInputElement>(null)

  const all = useMemo(() => emails.data ?? [], [emails.data])
  const shown = useMemo(
    () => all.filter((e) => matches(e, filters, query)).sort(byDate),
    [all, filters, query],
  )
  const selected = all.find((e) => e.source_file === selectedId) ?? null
  const banks = new Set(all.map((e) => e.bank)).size
  const toReview = all.filter((e) => e.flag_count > 0).length

  // "/" jumps to search; j/k or the arrow keys move through the list
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return
      if (e.key === '/') {
        e.preventDefault()
        searchRef.current?.focus()
        return
      }
      const step = { ArrowDown: 1, j: 1, ArrowUp: -1, k: -1 }[e.key]
      if (!step || shown.length === 0) return
      e.preventDefault()
      const at = shown.findIndex((x) => x.source_file === selectedId)
      const next = at === -1 ? 0 : Math.min(Math.max(at + step, 0), shown.length - 1)
      setSelectedId(shown[next].source_file)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    <div className="h-dvh flex flex-col">
      <Ticker />

      <header className="flex items-baseline gap-4 px-4 md:px-5 py-3 border-b-2 border-ink">
        <h1 className="font-serif font-semibold text-[22px] tracking-tight whitespace-nowrap">Research Desk</h1>
        {all.length > 0 && (
          <p className="text-[13px] text-muted">
            {all.length} emails from {banks} banks
            {toReview > 0 && (
              <>
                {' \u00B7 '}
                <button
                  type="button"
                  onClick={() => setFilters({ ...NO_FILTERS, other: [OTHER.review] })}
                  className="underline underline-offset-2 hover:text-accent"
                >
                  {toReview} to check
                </button>
              </>
            )}
          </p>
        )}
      </header>

      {emails.error ? (
        <div className="p-8 max-w-xl">
          <h2 className="font-serif text-xl font-semibold mb-2">The API is not answering</h2>
          <p className="text-muted">
            Start it from the repository root with{' '}
            <code className="text-ink">uv run uvicorn api.main:app --reload</code>, then reload this
            page. ({emails.error})
          </p>
        </div>
      ) : (
        <main className="flex-1 min-h-0 grid lg:grid-cols-[minmax(20rem,26rem)_1fr]">
          <div
            className={`min-h-0 overflow-y-auto border-r border-rule ${selected ? 'hidden lg:block' : ''}`}
          >
            <FilterPanel
              emails={all}
              tags={tags}
              filters={filters}
              onFilters={setFilters}
              query={query}
              onQuery={setQuery}
              searchRef={searchRef}
            />
            {emails.data ? (
              <EmailList
                emails={shown}
                total={all.length}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            ) : (
              <p className="px-4 py-6 text-muted text-[14px]">Loading emails</p>
            )}
          </div>

          <div className={`min-h-0 overflow-y-auto ${selected ? '' : 'hidden lg:block'}`}>
            {selected ? (
              <Reader key={selected.source_file} email={selected} onBack={() => setSelectedId(null)} />
            ) : (
              <div className="p-10 max-w-md text-muted">
                <p className="font-serif text-xl text-ink mb-2">Pick an email to read it.</p>
                <p className="text-[14px]">
                  Press <kbd className="border border-rule px-1">/</kbd> to search, and{' '}
                  <kbd className="border border-rule px-1">j</kbd>{' '}
                  <kbd className="border border-rule px-1">k</kbd> to move through the list.
                </p>
              </div>
            )}
          </div>
        </main>
      )}
    </div>
  )
}
