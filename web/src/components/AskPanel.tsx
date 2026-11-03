import { useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  askQuestion,
  emailFileUrl,
  type AskReply,
  type AskRequest,
  type Email,
  type SearchMode,
  type Tags,
} from '../api'
import { formatDate, formatDay } from '../filters'

type Props = {
  emails: Email[]
  tags: Tags | null
  // the bank or asset class picked in the email filters, if exactly one, to start from
  initialBank?: string
  initialTag?: string
  onOpen: (id: string) => void
}

const MODES: { value: SearchMode; label: string; hint: string }[] = [
  { value: 'hybrid', label: 'Hybrid', hint: 'both rankings, merged' },
  { value: 'vector', label: 'Meaning', hint: 'embeddings: finds other words for the same idea' },
  { value: 'keyword', label: 'Keywords', hint: 'BM25: finds exact names, tickers and figures' },
]

const EXAMPLES: { question: string; bank?: string }[] = [
  { question: "Is the US central bank's policy too tight?" },
  { question: 'What is the view on oil?', bank: 'Barclays' },
  { question: 'How are prescriptions for weight loss drugs trending?' },
]

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="px-4 py-4 border-t border-rule">
      <h2 className="text-[11px] uppercase tracking-widest text-muted mb-2">{label}</h2>
      {children}
    </section>
  )
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px] uppercase tracking-widest text-muted">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="normal-case tracking-normal text-[13px] text-ink bg-paper border border-rule px-1.5 py-1 hover:border-ink"
      >
        <option value="">Any</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

const rank = (n: number | null) => (n ? `#${n}` : '—')

export function AskPanel({ emails, tags, initialBank = '', initialTag = '', onOpen }: Props) {
  const [question, setQuestion] = useState('')
  const [bank, setBank] = useState(initialBank)
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [tag, setTag] = useState(initialTag)
  const [mode, setMode] = useState<SearchMode>('hybrid')
  const [withAnswer, setWithAnswer] = useState(true)
  const [reply, setReply] = useState<AskReply | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const inFlight = useRef<AbortController | null>(null)

  const banks = useMemo(() => [...new Set(emails.map((e) => e.bank))].sort(), [emails])
  const days = useMemo(
    () => [...new Set(emails.flatMap((e) => (e.date ? [e.date] : [])))].sort(),
    [emails],
  )
  const assets = useMemo(
    () => Object.entries(tags?.asset_classes ?? {}).flatMap(([parent, subs]) => [parent, ...subs]),
    [tags],
  )

  const run = async (request: AskRequest) => {
    // a newer question cancels the one still being answered
    inFlight.current?.abort()
    const own = new AbortController()
    inFlight.current = own
    setLoading(true)
    setError(null)
    try {
      const answer = await askQuestion(request, own.signal)
      if (!own.signal.aborted) setReply(answer)
    } catch (e) {
      if (own.signal.aborted) return
      setReply(null)
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (!own.signal.aborted) setLoading(false)
    }
  }

  const request = (overrides: Partial<AskRequest> = {}): AskRequest => ({
    question: question.trim(),
    mode,
    bank: bank || undefined,
    since: since || undefined,
    until: until || undefined,
    tag: tag || undefined,
    sources_only: !withAnswer,
    ...overrides,
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (question.trim()) run(request())
  }

  // after a first answer, switching the search mode asks again, to compare what each finds
  const pickMode = (next: SearchMode) => {
    setMode(next)
    if (reply && question.trim()) run(request({ mode: next }))
  }

  const tryExample = (example: (typeof EXAMPLES)[number]) => {
    setQuestion(example.question)
    setBank(example.bank ?? '')
    run(request({ question: example.question, bank: example.bank }))
  }

  const sourceOf = (n: number) => reply?.sources.find((s) => s.n === n)

  return (
    <div className="text-[14px]">
      <form onSubmit={onSubmit} className="px-4 py-4 space-y-3">
        <div>
          <h2 className="font-serif text-lg font-semibold">Ask the research</h2>
          <p className="text-[13px] text-muted">
            Answers use only these emails and their PDFs. Every quote is checked against its source.
          </p>
        </div>

        <label className="block">
          <span className="sr-only">Question</span>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) onSubmit(e)
            }}
            maxLength={500}
            rows={2}
            placeholder="What is Barclays' view on oil?"
            className="w-full bg-paper border border-ink px-2.5 py-2 placeholder:text-muted resize-none"
          />
        </label>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Select label="Bank" value={bank} onChange={setBank} options={banks.map((b) => ({ value: b, label: b }))} />
          <Select label="Asset" value={tag} onChange={setTag} options={assets.map((a) => ({ value: a, label: a }))} />
          <Select label="From" value={since} onChange={setSince} options={days.map((d) => ({ value: d, label: formatDay(d) }))} />
          <Select label="To" value={until} onChange={setUntil} options={days.map((d) => ({ value: d, label: formatDay(d) }))} />
        </div>

        <fieldset>
          <legend className="text-[11px] uppercase tracking-widest text-muted mb-1">Search by</legend>
          <div className="flex" role="group">
            {MODES.map((m) => (
              <button
                key={m.value}
                type="button"
                aria-pressed={mode === m.value}
                title={m.hint}
                onClick={() => pickMode(m.value)}
                className={`flex-1 text-[13px] px-2 py-1 border -ml-px first:ml-0 ${
                  mode === m.value ? 'bg-ink border-ink text-paper' : 'border-rule hover:border-ink'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
          <p className="text-[12px] text-muted mt-1">{MODES.find((m) => m.value === mode)?.hint}</p>
        </fieldset>

        <div className="flex items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-[13px]">
            <input type="checkbox" checked={withAnswer} onChange={(e) => setWithAnswer(e.target.checked)} className="accent-accent" />
            Write an answer (unticked: passages only, no AI)
          </label>
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="bg-accent text-paper px-4 py-1.5 font-semibold disabled:opacity-50"
          >
            {loading ? 'Asking…' : 'Ask'}
          </button>
        </div>
      </form>

      <div aria-live="polite">
        {loading && <p className="px-4 pb-3 text-muted">Searching the emails and reading the passages found{'…'}</p>}

        {error && (
          <div role="alert" className="mx-4 mb-4 bg-flag text-flag-ink px-3 py-2">
            <span className="block font-semibold text-[13px]">No answer</span>
            {error}
          </div>
        )}

        {!reply && !error && !loading && (
          <Section label="Try">
            <ul className="space-y-1.5">
              {EXAMPLES.map((ex) => (
                <li key={ex.question}>
                  <button type="button" onClick={() => tryExample(ex)} className="text-left underline underline-offset-2 hover:text-accent">
                    {ex.question}
                    {ex.bank && <span className="text-muted no-underline"> (bank: {ex.bank})</span>}
                  </button>
                </li>
              ))}
            </ul>
            <p className="text-[12px] text-muted mt-3">
              Switch between Meaning and Keywords after an answer to see what each search finds.
            </p>
          </Section>
        )}

        {reply && reply.answered !== null && (
          <Section label="Answer">
            {!reply.answered || reply.points.length === 0 ? (
              <p className="font-serif">The passages found do not answer this question.</p>
            ) : (
              <ul className="space-y-3">
                {reply.points.map((p, i) => {
                  const source = sourceOf(p.source)
                  return (
                    <li key={i} className={p.verified ? '' : 'bg-flag text-flag-ink px-3 py-2'}>
                      <p className="font-serif">
                        {p.claim}{' '}
                        <button
                          type="button"
                          onClick={() => source && onOpen(source.email_id)}
                          disabled={!source}
                          aria-label={`Open source ${p.source}`}
                          className="text-[12px] font-sans tabular-nums text-accent hover:underline"
                        >
                          [{p.source}]
                        </button>
                      </p>
                      <p className="text-[13px] text-muted italic">{`“${p.quote}”`}</p>
                      {!p.verified && <p className="text-[12px] font-semibold mt-1">Not verified: {p.problem}</p>}
                    </li>
                  )
                })}
              </ul>
            )}
            {reply.missing && <p className="text-[13px] text-muted mt-3">Not covered: {reply.missing}</p>}
          </Section>
        )}

        {reply && (
          <Section label={`Sources · ${MODES.find((m) => m.value === reply.mode)?.label} search`}>
            {reply.sources.length === 0 ? (
              <p className="text-muted">No passage matches the question and filters.</p>
            ) : (
              <ol className="space-y-3">
                {reply.sources.map((s) => (
                  <li key={s.n} className="flex gap-2">
                    <span className="text-[12px] tabular-nums text-muted pt-0.5">[{s.n}]</span>
                    <div className="min-w-0">
                      <button type="button" onClick={() => onOpen(s.email_id)} className="text-left font-semibold hover:text-accent hover:underline">
                        {s.title}
                      </button>
                      <p className="text-[12px] text-muted">
                        {s.bank ?? 'Unknown bank'} {'·'} {s.date ? formatDate(s.date) : 'no date'} {'·'}{' '}
                        {s.pdf && s.page ? (
                          <a href={`${emailFileUrl(s.email_id, s.pdf)}#page=${s.page}`} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:text-accent">
                            {s.where} {'↗'}
                          </a>
                        ) : (
                          s.where
                        )}
                      </p>
                      <p className="text-[12px] text-muted tabular-nums">
                        Keywords {rank(s.keyword_rank)} {'·'} Meaning {rank(s.vector_rank)}
                      </p>
                      <p className="text-[13px] mt-1 line-clamp-3">{s.text}</p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Section>
        )}
      </div>
    </div>
  )
}
