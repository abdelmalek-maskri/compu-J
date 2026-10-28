import { useState, type ReactNode, type RefObject } from 'react'
import type { Email, Tags } from '../api'
import {
  countValues,
  formatDay,
  GROUP_LABELS,
  KIND,
  labelOf,
  NO_DATE,
  NO_FILTERS,
  MARKET_WRAP,
  ONLY,
  toggle,
  type Filters,
  type Group,
} from '../filters'

type Props = {
  emails: Email[]
  tags: Tags | null
  filters: Filters
  onFilters: (f: Filters) => void
  query: string
  onQuery: (q: string) => void
  searchRef: RefObject<HTMLInputElement | null>
}

const byCount = (counts: Map<string, number>) =>
  [...counts.keys()].sort((a, b) => counts.get(b)! - counts.get(a)! || a.localeCompare(b))

function Chip({
  label,
  count,
  on,
  onClick,
}: {
  label: string
  count: number
  on: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`text-[12px] px-2 py-0.5 border ${
        on ? 'bg-accent border-accent text-paper' : 'border-rule hover:border-ink'
      }`}
    >
      {label}
      <span className={`ml-1.5 tabular-nums ${on ? 'text-paper/70' : 'text-muted'}`}>{count}</span>
    </button>
  )
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <fieldset>
      <legend className="text-[11px] uppercase tracking-widest text-muted mb-1.5">{label}</legend>
      {children}
    </fieldset>
  )
}

export function FilterPanel({
  emails,
  tags,
  filters,
  onFilters,
  query,
  onQuery,
  searchRef,
}: Props) {
  const [open, setOpen] = useState(false)
  const counts = (group: Group) => countValues(emails, filters, query, group)
  const dates = counts('date')
  const days = [...dates.keys()]
    .filter((d) => d !== NO_DATE)
    .sort()
    .reverse()
  // the year only adds noise when every email is from the same one
  const oneYear = new Set(days.map((d) => d.slice(0, 4))).size <= 1
  const label = (group: Group, value: string) =>
    group === 'date' && value !== NO_DATE && oneYear ? formatDay(value) : labelOf(group, value)

  const chip = (group: Group, value: string, count: number) => (
    <Chip
      key={value}
      label={label(group, value)}
      count={count}
      on={filters[group].includes(value)}
      onClick={() => onFilters(toggle(filters, group, value))}
    />
  )
  // a value with no email under the current choices is hidden, unless it is chosen
  const shown = (group: Group, values: string[], c: Map<string, number>) =>
    values.filter((v) => c.has(v) || filters[group].includes(v))

  // "kind" is always visible, so the chosen chips list only the groups inside the panel
  const inPanel: Group[] = ['only', 'date', 'bank', 'asset', 'sector', 'industry']
  const chosen = inPanel.flatMap((group) => filters[group].map((value) => ({ group, value })))

  const kinds = counts('kind')
  const all = [...kinds.values()].reduce((a, b) => a + b, 0)
  const only = counts('only')

  const assets = counts('asset')
  // market wraps have their own switch at the top, so their tag is not repeated here
  const classes = (tags ? Object.keys(tags.asset_classes) : byCount(assets)).filter(
    (c) => c !== MARKET_WRAP,
  )
  // a sub-tag is shown under its class once the class, or the sub-tag itself, is chosen
  const subRows = classes
    .map((parent) => ({
      parent,
      subs: shown(
        'asset',
        (tags?.asset_classes[parent] ?? []).filter(
          (s) => filters.asset.includes(parent) || filters.asset.includes(s),
        ),
        assets,
      ),
    }))
    .filter((row) => row.subs.length > 0)

  // industries only apply to company research, so they appear once Equity is chosen
  const sectors = counts('sector')
  const industries = counts('industry')
  const showIndustry =
    filters.asset.includes('Equity') || filters.sector.length > 0 || filters.industry.length > 0
  const chosenSectors = filters.sector
  const industryRows = chosenSectors.map((sector) => ({
    sector,
    values: shown(
      'industry',
      byCount(industries).filter((i) => i.startsWith(`${sector} > `)),
      industries,
    ),
  }))

  return (
    <div className="border-b border-rule">
      <div className="flex items-center gap-2 px-4 pt-4 pb-3">
        <input
          ref={searchRef}
          type="search"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Search titles, banks, companies, tags"
          aria-label="Search emails"
          className="flex-1 min-w-0 bg-transparent border-b border-ink/40 py-1.5 text-[15px] placeholder:text-muted focus:outline-none focus:border-accent"
        />
        <kbd className="hidden md:inline text-[11px] text-muted border border-rule px-1.5">/</kbd>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls="filter-groups"
          className="text-[13px] font-medium px-2 py-1.5 hover:text-accent whitespace-nowrap"
        >
          Filters{chosen.length > 0 && ` (${chosen.length})`} {open ? '\u25B4' : '\u25BE'}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pb-3">
        <div role="group" aria-label={GROUP_LABELS.kind} className="flex border border-rule">
          {[null, KIND.wrap, KIND.research].map((value) => {
            const on = value === null ? filters.kind.length === 0 : filters.kind.includes(value)
            return (
              <button
                key={value ?? 'all'}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  onFilters(
                    value === null ? { ...filters, kind: [] } : toggle(filters, 'kind', value),
                  )
                }
                className={`text-[12px] px-2.5 py-1 ${
                  on ? 'bg-ink text-paper' : 'hover:bg-paper-deep'
                }`}
              >
                {value ?? 'All'}
                <span className={`ml-1.5 tabular-nums ${on ? 'text-paper/70' : 'text-muted'}`}>
                  {value === null ? all : (kinds.get(value) ?? 0)}
                </span>
              </button>
            )
          })}
        </div>
        <div role="group" aria-label={GROUP_LABELS.only} className="flex gap-1.5">
          {Object.values(ONLY).map((value) => chip('only', value, only.get(value) ?? 0))}
        </div>
      </div>

      {chosen.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pb-3">
          {chosen.map(({ group, value }) => (
            <button
              key={`${group}:${value}`}
              type="button"
              onClick={() => onFilters(toggle(filters, group, value))}
              className="text-[12px] bg-accent text-paper px-2 py-0.5 hover:bg-ink"
              aria-label={`Remove filter ${label(group, value)}`}
            >
              {label(group, value)} <span aria-hidden>{'\u00D7'}</span>
            </button>
          ))}
          <button
            type="button"
            onClick={() => onFilters({ ...NO_FILTERS, kind: filters.kind })}
            className="text-[12px] text-muted underline underline-offset-2 px-1 hover:text-accent"
          >
            Clear all
          </button>
        </div>
      )}

      {open && (
        <div id="filter-groups" className="px-4 pb-4 space-y-4">
          <Section label={GROUP_LABELS.date}>
            <div className="flex flex-wrap gap-1.5">
              {shown('date', [...days, NO_DATE], dates).map((d) =>
                chip('date', d, dates.get(d) ?? 0),
              )}
            </div>
          </Section>

          <Section label={GROUP_LABELS.bank}>
            <div className="flex flex-wrap gap-1.5">
              {(() => {
                const banks = counts('bank')
                return shown('bank', tags?.banks ?? byCount(banks), banks).map((b) =>
                  chip('bank', b, banks.get(b) ?? 0),
                )
              })()}
            </div>
          </Section>

          <Section label={GROUP_LABELS.asset}>
            <div className="flex flex-wrap gap-1.5">
              {shown('asset', classes, assets).map((c) => chip('asset', c, assets.get(c) ?? 0))}
            </div>
            {subRows.map(({ parent, subs }) => (
              <div key={parent} className="mt-1.5 pl-3 border-l border-rule">
                <span className="block text-[11px] text-muted mb-1">{parent}</span>
                <div className="flex flex-wrap gap-1.5">
                  {subs.map((s) => chip('asset', s, assets.get(s) ?? 0))}
                </div>
              </div>
            ))}
          </Section>

          {showIndustry && (
            <Section label={GROUP_LABELS.sector}>
              <div className="flex flex-wrap gap-1.5">
                {shown('sector', byCount(sectors), sectors).map((s) =>
                  chip('sector', s, sectors.get(s) ?? 0),
                )}
              </div>
              {industryRows.map(({ sector, values }) => (
                <div key={sector} className="mt-1.5 pl-3 border-l border-rule">
                  <span className="block text-[11px] text-muted mb-1">{sector}</span>
                  <div className="flex flex-wrap gap-1.5">
                    {values.map((i) => chip('industry', i, industries.get(i) ?? 0))}
                  </div>
                </div>
              ))}
            </Section>
          )}
        </div>
      )}
    </div>
  )
}
