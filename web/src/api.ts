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
  date_hint: string | null
  flag_count: number
}

export type Flag = {
  kind: 'model_vs_python' | 'model_logic' | 'model_vs_model' | 'inferred'
  field: string
  value_a: unknown
  value_b: unknown
  note: string
}

// classified_emails_details.json for one email; empty when no details file exists
export type Details = {
  bank_source?: string
  date_source?: string | null
  date_quote?: string | null
  title_verified?: boolean | null
  flags?: Flag[]
  corrections?: string[]
  content_type?: string
  warnings?: string[]
  model?: string
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

type State<T> = { data: T | null; error: string | null }

/** GET a JSON endpoint; `refreshMs` re-fetches on a timer and keeps the last good data */
export function useJson<T>(url: string, refreshMs?: number): State<T> {
  const [state, setState] = useState<State<T> & { url: string }>({
    url,
    data: null,
    error: null,
  })

  useEffect(() => {
    let controller = new AbortController()
    const load = async () => {
      try {
        const response = await fetch(url, { signal: controller.signal })
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
        const data = (await response.json()) as T
        setState({ url, data, error: null })
      } catch (e) {
        if (controller.signal.aborted) return
        setState((s) => ({ ...s, url, error: e instanceof Error ? e.message : String(e) }))
      }
    }
    load()
    const timer = refreshMs
      ? setInterval(() => {
          controller = new AbortController()
          load()
        }, refreshMs)
      : undefined
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [url, refreshMs])

  // a new url must not show the previous url's data while it loads
  return state.url === url ? state : { data: null, error: null }
}
