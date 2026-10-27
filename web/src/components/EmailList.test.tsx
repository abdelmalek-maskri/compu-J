import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Email } from '../api'
import { EmailList } from './EmailList'

const email: Email = {
  folder_name: 'US, Europe & Asia Market Update',
  bank: 'J. Safra Sarasin',
  date: null,
  market_wrap: 'YES',
  primary_asset_tag: 'Market Wrap',
  asset_tags: ['Market Wrap'],
  companies_mentioned: [],
  industry_subindustry: [],
  pdf_attachment: null,
  source_file: '035245',
  content_type: 'research',
  date_confirmed: true,
  received: null,
  flag_count: 1,
}

describe('EmailList', () => {
  it('shows what a reader needs to pick an email, and reports the pick', async () => {
    const onSelect = vi.fn()
    render(<EmailList emails={[email]} total={200} selectedId={null} onSelect={onSelect} />)

    expect(screen.getByText('1 of 200 emails')).toBeInTheDocument()
    expect(screen.getByText('No publication date found')).toBeInTheDocument()
    expect(screen.getByText('1 to check')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Market Update/ }))
    expect(onSelect).toHaveBeenCalledWith('035245')
  })

  it('marks a date that comes from a link as not confirmed', () => {
    const linked = { ...email, date: '2026-04-13', date_confirmed: false }
    render(<EmailList emails={[linked]} total={200} selectedId={null} onSelect={() => {}} />)
    expect(screen.getByText(/\(not confirmed\)/)).toBeInTheDocument()
  })

  it('says how to recover when nothing matches', () => {
    render(<EmailList emails={[]} total={200} selectedId={null} onSelect={() => {}} />)
    expect(screen.getByText(/Nothing matches/)).toBeInTheDocument()
  })
})
