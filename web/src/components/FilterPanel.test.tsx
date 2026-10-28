import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { Email, Tags } from '../api'
import { NO_FILTERS, type Filters } from '../filters'
import { FilterPanel } from './FilterPanel'

const base: Email = {
  folder_name: 'FX Daily',
  bank: 'Deutsche Bank',
  date: '2026-04-10',
  market_wrap: 'NO',
  primary_asset_tag: 'Macro',
  asset_tags: ['Macro', 'Emerging Markets'],
  companies_mentioned: [],
  industry_subindustry: [],
  pdf_attachment: null,
  source_file: '035300',
  content_type: 'research',
  date_confirmed: true,
  received: null,
  flag_count: 0,
}
const emails: Email[] = [
  base,
  {
    ...base,
    source_file: '035301',
    market_wrap: 'YES',
    asset_tags: ['Market Wrap'],
    date: '2026-04-13',
  },
  {
    ...base,
    source_file: '035302',
    asset_tags: ['Equity', 'Company Research'],
    industry_subindustry: ['HEALTHCARE > Biotechnology'],
  },
]
const tags: Tags = {
  asset_classes: {
    Macro: ['Developed Markets', 'Emerging Markets'],
    Equity: ['Company Research'],
    'Market Wrap': [],
  },
  industries: {},
  banks: ['Deutsche Bank'],
}

function Panel() {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  return (
    <FilterPanel
      emails={emails}
      tags={tags}
      filters={filters}
      onFilters={setFilters}
      query=""
      onQuery={() => {}}
      searchRef={{ current: null }}
    />
  )
}

describe('FilterPanel', () => {
  it('shows market wraps and research first, with their counts', () => {
    render(<Panel />)
    expect(screen.getByRole('button', { name: /^All\s*3$/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: /^Market wraps\s*1$/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Research\s*2$/ })).toBeInTheDocument()
  })

  it('reveals sub-tags under a chosen class, and industries once Equity is chosen', async () => {
    render(<Panel />)
    await userEvent.click(screen.getByRole('button', { name: /Filters/ }))
    expect(screen.getByRole('button', { name: /^13 Apr\s*1$/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Emerging Markets/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Healthcare/ })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /^Macro\s*1$/ }))
    expect(screen.getByRole('button', { name: /Emerging Markets/ })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /^Equity/ }))
    expect(screen.getByRole('button', { name: /Healthcare/ })).toBeInTheDocument()
  })
})
