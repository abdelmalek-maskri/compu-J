import { useState, type RefObject } from 'react'
import type { Email, Tags } from '../api'
import {
  countValues,
  GROUP_LABELS,
  NO_FILTERS,
  OTHER,
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

type Option = { value: string; sub?: boolean }

/** the order the brief gives (banks, asset classes with their sub tags); industries by count */
function optionsFor(group: Group, tags: Tags | null, counts: Map<string, number>): Option[] {
  const byCount = () =>
    [...counts.keys()].sort((a, b) => counts.get(b)! - counts.get(a)! || a.localeCompare(b))
  switch (group) {
    case 'bank':
      return (tags?.banks ?? byCount()).map((value) => ({ value }))
    case 'asset':
      if (!tags) return byCount().map((value) => ({ value }))
      return Object.entries(tags.asset_classes).flatMap(([primary, subs]) => [
        { value: primary },
        ...subs.map((value) => ({ value, sub: true })),
      ])
    case 'industry':
      return byCount().map((value) => ({ value }))
    case 'other':
      return Object.values(OTHER).map((value) => ({ value }))
  }
}

export function FilterPanel({ emails, tags, filters, onFilters, query, onQuery, searchRef }: Props) {
  const [open, setOpen] = useState(false)
  const groups = Object.keys(GROUP_LABELS) as Group[]
  const chosen = groups.flatMap((group) => filters[group].map((value) => ({ group, value })))

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

      {chosen.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pb-3">
          {chosen.map(({ group, value }) => (
            <button
              key={`${group}:${value}`}
              type="button"
              onClick={() => onFilters(toggle(filters, group, value))}
              className="text-[12px] bg-accent text-paper px-2 py-0.5 hover:bg-ink"
              aria-label={`Remove filter ${value}`}
            >
              {value} <span aria-hidden>{'\u00D7'}</span>
            </button>
          ))}
          <button
            type="button"
            onClick={() => onFilters(NO_FILTERS)}
            className="text-[12px] text-muted underline underline-offset-2 px-1 hover:text-accent"
          >
            Clear all
          </button>
        </div>
      )}

      {open && (
        <div id="filter-groups" className="px-4 pb-4 space-y-4">
          {groups.map((group) => {
            const counts = countValues(emails, filters, query, group)
            const options = optionsFor(group, tags, counts).filter(
              (o) => counts.has(o.value) || filters[group].includes(o.value),
            )
            if (options.length === 0) return null
            return (
              <fieldset key={group}>
                <legend className="text-[11px] uppercase tracking-widest text-muted mb-1.5">
                  {GROUP_LABELS[group]}
                </legend>
                <div className="flex flex-wrap gap-1.5">
                  {options.map(({ value, sub }) => {
                    const on = filters[group].includes(value)
                    return (
                      <button
                        key={value}
                        type="button"
                        aria-pressed={on}
                        onClick={() => onFilters(toggle(filters, group, value))}
                        className={`text-[12px] px-2 py-0.5 border ${
                          on
                            ? 'bg-accent border-accent text-paper'
                            : 'border-rule hover:border-ink'
                        } ${sub ? 'italic' : ''}`}
                      >
                        {value}
                        <span className={`ml-1.5 tabular-nums ${on ? 'text-paper/70' : 'text-muted'}`}>
                          {counts.get(value) ?? 0}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </fieldset>
            )
          })}
        </div>
      )}
    </div>
  )
}
