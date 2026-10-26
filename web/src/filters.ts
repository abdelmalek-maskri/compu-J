import type { Email } from './api'

export type Group = 'bank' | 'asset' | 'industry' | 'other'
export type Filters = Record<Group, string[]>

export const NO_FILTERS: Filters = { bank: [], asset: [], industry: [], other: [] }

export const GROUP_LABELS: Record<Group, string> = {
  bank: 'Bank',
  asset: 'Asset class',
  industry: 'Industry',
  other: 'Other',
}

export const OTHER = {
  wrap: 'Market wrap',
  pdf: 'Has a PDF',
  review: 'Needs review',
  nodate: 'No date',
} as const

export function valuesOf(email: Email, group: Group): string[] {
  switch (group) {
    case 'bank':
      return [email.bank]
    case 'asset':
      return email.asset_tags
    case 'industry':
      return email.industry_subindustry.filter((i) => i !== 'Unknown')
    case 'other':
      return [
        [email.market_wrap === 'YES', OTHER.wrap],
        [Boolean(email.pdf_attachment?.length), OTHER.pdf],
        [email.flag_count > 0, OTHER.review],
        [!email.date, OTHER.nodate],
      ].flatMap(([on, label]) => (on ? [label as string] : []))
  }
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
  return {
    ...filters,
    [group]: chosen.includes(value) ? chosen.filter((v) => v !== value) : [...chosen, value],
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
