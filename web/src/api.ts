import { useEffect, useState } from 'react'

// one entry of GET /api/emails: the brief's ten fields plus what the list needs
export type Email = {
  folder_name: string
  bank: string
  date: string | null
  market_wrap: 'YES' | 'NO'
  primary_asset_tag: string | null
  asset_tags: string[]
  companies_mentioned: string[]
  industry_subindustry: string[]
  pdf_attachment: string[] | null
  source_file: string
  content_type: string | null
  // false when the date comes from a link in the email, or where it came from is unknown
  date_confirmed: boolean
  received: string | null
  flag_count: number
}

export type Flag = {
  kind: 'model_vs_python' | 'model_logic' | 'model_vs_model' | 'inferred'
  field: string
  value_a: unknown
  value_b: unknown
  note: string
  detail?: string | null
}

// the parts of classified_emails_details.json the dashboard shows; the file has more
export type Details = {
  flags?: Flag[]
  // answers a person corrected after review, each with its reason
  reviewed?: string[]
  content_type?: string
}

// remote_images: images on the banks' servers, blocked unless the reader asks for them
export type EmailDetail = { record: Email; details: Details; remote_images: number }

export type Tags = {
  asset_classes: Record<string, string[]>
  industries: Record<string, string[]>
  banks: string[]
}

export type Headline = { title: string; url: string; source: string; published: string | null }

export type Headlines = {
  last_updated: string | null
  stale: boolean
  error: string | null
  headlines: Headline[]
}

export const emailHtmlUrl = (id: string, images: boolean) =>
  `/api/emails/${id}/html${images ? '?images=true' : ''}`

export const emailFileUrl = (id: string, name: string) =>
  `/api/emails/${id}/files/${encodeURIComponent(name)}`

export type SearchMode = 'hybrid' | 'keyword' | 'vector'

// POST /api/ask: a question, the filters applied before searching, and the kind of search
export type AskRequest = {
  question: string
  mode: SearchMode
  bank?: string
  since?: string
  until?: string
  tag?: string
  // only passages describing a picture: 'any', or one kind such as 'cartoon'
  picture?: string
  sources_only?: boolean
  // false: search everything even when the question names a kind of picture ("cartoons")
  read_question?: boolean
}

// one claim of the answer; verified: its quote is in the cited passage, word for word
export type AnswerPoint = {
  claim: string
  source: number
  quote: string
  verified: boolean
  problem: string | null
  // the cited passage is a model's description of a picture, so the picture is worth a look
  from_picture: boolean
}

export type AnswerSource = {
  n: number
  email_id: string
  title: string
  bank: string | null
  date: string | null
  pdf: string | null
  page: number | null
  where: string
  text: string
  // the kind of picture the passage describes ('chart', 'cartoon'...), null for the email's text
  picture: string | null
  // an email's own image, relative to its folder, shown beside the description
  image: string | null
  // each search's own rank for this passage; null when that search did not find it
  keyword_rank: number | null
  vector_rank: number | null
}

export type AskReply = {
  question: string
  mode: SearchMode
  // null when only the sources were asked for
  answered: boolean | null
  missing: string
  // the kind of picture the question asked for, when the search was narrowed to it
  picture_from_question: string | null
  // a comparison: each of these banks was searched on its own, and these had no passage
  banks_from_question: string[]
  banks_without_passages: string[]
  points: AnswerPoint[]
  sources: AnswerSource[]
}

/** the API explains its refusals in `detail`: a sentence, or FastAPI's list of field errors */
function problemOf(body: unknown, response: Response): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).join('; ')
  return `${response.status} ${response.statusText}`
}

export async function askQuestion(request: AskRequest, signal?: AbortSignal): Promise<AskReply> {
  const response = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(problemOf(body, response))
  return body as AskReply
}

type State<T> = { data: T | null; error: string | null }

/** GET a JSON endpoint; `refreshMs` re-fetches on a timer and keeps the last good data */
export function useJson<T>(url: string, refreshMs?: number): State<T> {
  const [state, setState] = useState<State<T> & { url: string }>({
    url,
    data: null,
    error: null,
  })

  useEffect(() => {
    // each request has its own controller and cancels the one before, so a slow older answer
    // can never overwrite a newer one, and leaving cancels whatever is still in flight
    let current: AbortController | undefined
    const load = async () => {
      current?.abort()
      const own = new AbortController()
      current = own
      try {
        const response = await fetch(url, { signal: own.signal })
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
        const data = (await response.json()) as T
        if (!own.signal.aborted) setState({ url, data, error: null })
      } catch (e) {
        if (own.signal.aborted) return
        setState((s) => ({ ...s, url, error: e instanceof Error ? e.message : String(e) }))
      }
    }
    load()
    const timer = refreshMs ? setInterval(load, refreshMs) : undefined
    return () => {
      current?.abort()
      clearInterval(timer)
    }
  }, [url, refreshMs])

  // a new url must not show the previous url's data while it loads
  return state.url === url ? state : { data: null, error: null }
}
