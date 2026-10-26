import { useState, type CSSProperties } from 'react'
import { useJson, type Headlines } from '../api'

// the file only changes when fetch_news.py runs, so a minute is plenty
const REFRESH_MS = 60_000

const TIME = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' })
const DAY_TIME = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
})

/** the time alone reads as today, so older updates also show their day */
function when(iso: string): string {
  const at = new Date(iso)
  return at.toDateString() === new Date().toDateString() ? TIME.format(at) : DAY_TIME.format(at)
}

export function Ticker() {
  const { data, error } = useJson<Headlines>('/api/headlines', REFRESH_MS)
  const [paused, setPaused] = useState(false)
  const headlines = data?.headlines ?? []

  let status: string
  if (error) status = 'News unavailable'
  else if (!data) status = 'Loading news'
  else if (!data.last_updated) status = data.error ?? 'No news yet'
  else status = `${data.stale ? 'Last good update' : 'Updated'} ${when(data.last_updated)}`

  return (
    <div className="flex items-center bg-ink text-paper text-[13px] h-9 shrink-0">
      <span className="px-4 font-semibold uppercase tracking-[0.12em] text-[11px] border-r border-paper/20 h-full flex items-center">
        Markets
      </span>
      <div
        className="ticker relative flex-1 overflow-hidden h-full"
        aria-label="Latest market headlines"
        role="region"
        data-paused={paused || undefined}
      >
        {headlines.length > 0 && (
          <div
            className="ticker-track flex w-max h-full items-center"
            // about 4 seconds per headline keeps the reading speed the same for any count
            style={{ '--ticker-duration': `${headlines.length * 4}s` } as CSSProperties}
          >
            {[0, 1].map((copy) => (
              <ul key={copy} className="flex shrink-0" aria-hidden={copy === 1}>
                {headlines.map((h) => (
                  <li key={h.url} className="px-5 whitespace-nowrap">
                    <span className="text-paper/60 mr-2">{h.source}</span>
                    <a
                      href={h.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      tabIndex={copy === 1 ? -1 : undefined}
                      className="hover:underline underline-offset-2"
                    >
                      {h.title}
                    </a>
                  </li>
                ))}
              </ul>
            ))}
          </div>
        )}
      </div>
      {headlines.length > 0 && (
        <button
          type="button"
          onClick={() => setPaused(!paused)}
          aria-label={paused ? 'Play headlines' : 'Pause headlines'}
          className="px-3 h-full border-l border-paper/20 text-paper/70 hover:text-paper"
        >
          {paused ? '\u25B6' : '\u275A\u275A'}
        </button>
      )}
      <span
        className={`px-4 whitespace-nowrap text-[12px] border-l border-paper/20 h-full flex items-center ${
          data?.stale || error ? 'text-flag' : 'text-paper/60'
        }`}
        title={data?.error ?? error ?? undefined}
      >
        {status}
      </span>
    </div>
  )
}
