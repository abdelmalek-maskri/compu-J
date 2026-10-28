import type { Email } from './api'

// in the order the panel shows them: the brief's main question first, then when, who and what
export type Group = 'kind' | 'only' | 'date' | 'bank' | 'asset' | 'sector' | 'industry'
export type Filters = Record<Group, string[]>

export const NO_FILTERS: Filters = {
  kind: [],
  only: [],
  date: [],
  bank: [],
  asset: [],
  sector: [],
  industry: [],
}

export const GROUP_LABELS: Record<Group, string> = {
  kind: 'Show',
  only: 'Only',
  date: 'Date',
  bank: 'Bank',
  asset: 'Asset class',
  sector: 'Sector',
  industry: 'Industry',
}

export const KIND = { wrap: 'Market wraps', research: 'Research' } as const
export const ONLY = { review: 'Worth checking', pdf: 'Has a PDF' } as const
export const NO_DATE = 'No date'
export const MARKET_WRAP = 'Market Wrap'

// "kind" is one choice or none: an email is either a market wrap or not
const SINGLE: Group[] = ['kind']

const sectorOf = (industry: string) => industry.split(' > ')[0]

export function valuesOf(email: Email, group: Group): string[] {
  const industries = email.industry_subindustry.filter((i) => i !== 'Unknown')
  switch (group) {
    case 'kind':
      return [email.market_wrap === 'YES' ? KIND.wrap : KIND.research]
    case 'only':
      return [
        [email.flag_count > 0, ONLY.review],
        [Boolean(email.pdf_attachment?.length), ONLY.pdf],
      ].flatMap(([on, label]) => (on ? [label as string] : []))
    case 'date':
      return [email.date ?? NO_DATE]
    case 'bank':
      return [email.bank]
    case 'asset':
      return email.asset_tags
    case 'sector':
      return [...new Set(industries.map(sectorOf))]
    case 'industry':
      return industries
  }
}

/** how a value reads in the panel: dates as "13 Apr 2026", sectors in normal case, industries
 * without their sector */
export function labelOf(group: Group, value: string): string {
  if (group === 'date' && value !== NO_DATE) return formatDate(value)
  if (group === 'industry') return value.split(' > ')[1] ?? value
  // the brief writes sectors in capitals; in a list of filters that reads as shouting
  if (group === 'sector') return value.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())
  return value
}

function searchText(email: Email): string {
  return [
    email.folder_name,
    email.bank,
    email.source_file,
    ...email.asset_tags,
    ...email.companies_mentioned,
    ...email.industry_subindustry,
  ]
    .join(' ')
    .toLowerCase()
}

/** every word of the query must appear; within a group any chosen value is enough, and every
 * group with a choice must match */
export function matches(email: Email, filters: Filters, query: string): boolean {
  const text = searchText(email)
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.every((w) => text.includes(w))) return false
  return (Object.keys(filters) as Group[]).every((group) => {
    const chosen = filters[group]
    return chosen.length === 0 || valuesOf(email, group).some((v) => chosen.includes(v))
  })
}

/** how many emails each value would show, given the search and the other groups' choices */
export function countValues(
  emails: Email[],
  filters: Filters,
  query: string,
  group: Group,
): Map<string, number> {
  const others = { ...filters, [group]: [] }
  const counts = new Map<string, number>()
  for (const email of emails) {
    if (!matches(email, others, query)) continue
    for (const value of valuesOf(email, group)) counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  return counts
}

export function toggle(filters: Filters, group: Group, value: string): Filters {
  const chosen = filters[group]
  if (chosen.includes(value)) return { ...filters, [group]: chosen.filter((v) => v !== value) }
  return {
    ...filters,
    [group]: SINGLE.includes(group) ? [value] : [...chosen, value],
  }
}

/** newest first; emails without a date go last */
export function byDate(a: Email, b: Email): number {
  if (a.date !== b.date) {
    if (!a.date) return 1
    if (!b.date) return -1
    return b.date.localeCompare(a.date)
  }
  return a.source_file.localeCompare(b.source_file)
}

const DAY = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

export const formatDate = (iso: string) => DAY.format(new Date(`${iso}T00:00:00Z`))

const DAY_MONTH = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  timeZone: 'UTC',
})

/** "13 Apr", for lists where every date is in the same year */
export const formatDay = (iso: string) => DAY_MONTH.format(new Date(`${iso}T00:00:00Z`))
