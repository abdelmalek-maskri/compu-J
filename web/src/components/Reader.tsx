import { useState, type ReactNode } from 'react'
import { emailFileUrl, emailHtmlUrl, useJson, type Details, type Email, type EmailDetail } from '../api'
import { formatDate } from '../filters'

const FLAG_KINDS: Record<string, string> = {
  model_vs_python: 'Model and rules disagree',
  model_logic: 'Model contradicts itself',
  model_vs_model: 'Two models disagree',
  inferred: 'Filled in by the model',
}

const CONTENT_TYPES: Record<string, string> = {
  event: 'Event invitation',
  marketing: 'Marketing',
}

/** "llm+python", "llm", "python:logo" as plain words */
function describeSource(source: string | null | undefined): string {
  if (!source) return 'not found'
  if (source === 'llm+python') return 'model and rules agree'
  if (source === 'llm') return 'model, confirmed in the text'
  const [, where] = source.split(':')
  return where ? `rules (${where.replace('_', ' ')})` : source
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="py-4 border-t border-rule first:border-t-0 first:pt-0">
      <h2 className="text-[11px] uppercase tracking-widest text-muted mb-2">{title}</h2>
      {children}
    </section>
  )
}

function Sidebar({ email, details }: { email: Email; details: Details | undefined }) {
  const flags = details?.flags ?? []
  const isEquity = email.asset_tags.includes('Equity')
  return (
    <aside className="text-[14px]">
      {flags.length > 0 && (
        <Section title="To review">
          <ul className="space-y-2">
            {flags.map((f, i) => (
              <li key={i} className="bg-flag text-flag-ink px-3 py-2">
                <span className="block font-semibold text-[13px]">
                  {FLAG_KINDS[f.kind] ?? f.kind}: {f.field}
                </span>
                {f.note}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {isEquity && (
        <Section title="Equity">
          <h3 className="text-[12px] text-muted">Companies</h3>
          {email.companies_mentioned.length > 0 ? (
            <ul className="mb-3 columns-2 gap-4 text-[13px]">
              {email.companies_mentioned.map((c) => (
                <li key={c} className="break-inside-avoid">{c}</li>
              ))}
            </ul>
          ) : (
            <p className="mb-3 text-muted">None named</p>
          )}
          <h3 className="text-[12px] text-muted">Industries</h3>
          <ul className="text-[13px]">
            {email.industry_subindustry.map((i) => {
              const [sector, sub] = i.split(' > ')
              return (
                <li key={i}>
                  {sub ? (
                    <>
                      <span className="text-muted">{sector} {'\u203A'}</span> {sub}
                    </>
                  ) : (
                    sector
                  )}
                </li>
              )
            })}
          </ul>
        </Section>
      )}

      <Section title="How this was read">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
          <dt className="text-muted">Bank</dt>
          <dd>{describeSource(details?.bank_source)}</dd>
          <dt className="text-muted">Date</dt>
          <dd>{describeSource(details?.date_source)}</dd>
          {details?.date_quote && (
            <>
              <dt className="text-muted">Quote</dt>
              <dd className="font-serif italic">{'\u201C'}{details.date_quote}{'\u201D'}</dd>
            </>
          )}
          {details?.model && (
            <>
              <dt className="text-muted">Model</dt>
              <dd className="break-all">{details.model}</dd>
            </>
          )}
          <dt className="text-muted">Folder</dt>
          <dd className="tabular-nums">{email.source_file}</dd>
        </dl>
      </Section>
    </aside>
  )
}

// one choice for every email, kept in this browser; storage can be unavailable (private
// windows, blocked site data), and then images simply stay blocked
const IMAGES_KEY = 'load-remote-images'

function readImagesChoice(): boolean {
  try {
    return localStorage.getItem(IMAGES_KEY) === 'yes'
  } catch {
    return false
  }
}

function saveImagesChoice(on: boolean) {
  try {
    localStorage.setItem(IMAGES_KEY, on ? 'yes' : 'no')
  } catch {
    // not saved: the choice still applies until the next email
  }
}

export function Reader({ email, onBack }: { email: Email; onBack: () => void }) {
  const id = email.source_file
  const { data } = useJson<EmailDetail>(`/api/emails/${id}`)
  const [view, setView] = useState<string | null>(null) // null is the email, else a PDF name
  const [images, setImages] = useState(readImagesChoice)
  const pdfs = email.pdf_attachment ?? []
  const remote = data?.remote_images ?? 0
  const kind = CONTENT_TYPES[data?.details.content_type ?? email.content_type ?? '']

  const tab = (label: string, value: string | null) => (
    <button
      key={label}
      type="button"
      role="tab"
      aria-selected={view === value}
      onClick={() => setView(value)}
      className={`py-2 text-[13px] border-b-2 -mb-px truncate max-w-56 ${
        view === value ? 'border-accent text-ink font-medium' : 'border-transparent text-muted hover:text-ink'
      }`}
    >
      {label}
    </button>
  )

  return (
    <article className="px-5 md:px-8 py-6 min-h-full flex flex-col">
      <button
        type="button"
        onClick={onBack}
        className="lg:hidden self-start mb-4 text-[13px] text-muted hover:text-accent"
      >
        {'\u2039'} All emails
      </button>

      <header className="max-w-240">
        <p className="text-[12px] uppercase tracking-[0.08em] text-accent mb-2">
          {email.market_wrap === 'YES' ? 'Market wrap' : email.asset_tags.join(' \u00B7 ')}
        </p>
        <h1 className="font-serif font-semibold text-[clamp(1.6rem,2.4vw,2.2rem)] leading-[1.15] text-balance">
          {email.folder_name}
        </h1>
        <p className="mt-3 text-[14px] text-muted">
          <span className="text-ink">{email.bank}</span>
          <span aria-hidden> {'\u00B7'} </span>
          {email.date ? (
            <time dateTime={email.date}>{formatDate(email.date)}</time>
          ) : (
            <span>
              No date found
              {email.date_hint && ` (a link in the email suggests ${formatDate(email.date_hint)})`}
            </span>
          )}
          {kind && (
            <>
              <span aria-hidden> {'\u00B7'} </span>
              {kind}
            </>
          )}
        </p>
      </header>

      <div className="mt-6 flex-1 grid gap-8 xl:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="flex flex-col min-h-[70vh]">
          <div className="flex items-end gap-5 border-b border-rule" role="tablist">
            {tab('Email', null)}
            {pdfs.map((name) => tab(name, name))}
            <span className="ml-auto pb-2 text-[12px] text-muted">
              {view === null ? (
                <label className="inline-flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={images}
                    onChange={(e) => {
                      setImages(e.target.checked)
                      saveImagesChoice(e.target.checked)
                    }}
                    className="accent-accent"
                  />
                  <span title="Images on the banks' servers tell the bank who opened this email, and when">
                    Load remote images
                    {!images && remote > 0 && (
                      <span className="text-flag-ink">
                        {' \u00B7 '}
                        {remote === 1 ? '1 blocked' : `${remote} blocked`}
                      </span>
                    )}
                  </span>
                </label>
              ) : (
                <a
                  href={emailFileUrl(id, view)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2 hover:text-accent"
                >
                  Open in a new tab
                </a>
              )}
            </span>
          </div>
          {view === null ? (
            <iframe
              key={`${id}-${images}`}
              title={`Email: ${email.folder_name}`}
              src={emailHtmlUrl(id, images)}
              // no scripts, no same-origin access; links may still open in a new tab
              sandbox="allow-popups allow-popups-to-escape-sandbox"
              className="flex-1 w-full bg-white border-x border-b border-rule"
            />
          ) : (
            <iframe
              key={`${id}-${view}`}
              title={`PDF: ${view}`}
              src={emailFileUrl(id, view)}
              className="flex-1 w-full bg-white border-x border-b border-rule"
            />
          )}
        </div>

        <Sidebar email={email} details={data?.details} />
      </div>
    </article>
  )
}
