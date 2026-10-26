import { describe, expect, it } from 'vitest'
import type { Email } from './api'
import { byDate, countValues, matches, NO_FILTERS, OTHER, toggle, valuesOf } from './filters'

const email = (over: Partial<Email>): Email => ({
  folder_name: 'FX Daily',
  bank: 'Deutsche Bank',
  date: '2026-04-10',
  market_wrap: 'NO',
  primary_asset_tag: 'FX',
  asset_tags: ['FX', 'JPY'],
  companies_mentioned: [],
  industry_subindustry: [],
  pdf_attachment: null,
  source_file: '035300',
  content_type: 'research',
  date_hint: null,
  flag_count: 0,
  ...over,
})

const fx = email({})
const tech = email({
  folder_name: 'Technip Energies',
  bank: 'UBP',
  primary_asset_tag: 'Equity',
  asset_tags: ['Equity', 'Company Research'],
  companies_mentioned: ['TECHNIP ENERGIES'],
  industry_subindustry: ['ENERGY > Energy'],
  pdf_attachment: ['NL0014559478.pdf'],
  source_file: '035333',
  flag_count: 2,
})
const wrap = email({ market_wrap: 'YES', asset_tags: ['Market Wrap'], date: null, source_file: '035245' })

describe('matches', () => {
  it('needs every word of the search, in any field, ignoring case', () => {
    expect(matches(tech, NO_FILTERS, 'technip ubp')).toBe(true)
    expect(matches(tech, NO_FILTERS, 'technip barclays')).toBe(false)
    expect(matches(tech, NO_FILTERS, '  energy  ')).toBe(true)
  })

  it('treats choices in one group as "any of" and groups as "all of"', () => {
    const banks = toggle(toggle(NO_FILTERS, 'bank', 'UBP'), 'bank', 'Deutsche Bank')
    expect([fx, tech].every((e) => matches(e, banks, ''))).toBe(true)
    const banksAndEquity = toggle(banks, 'asset', 'Equity')
    expect(matches(fx, banksAndEquity, '')).toBe(false)
    expect(matches(tech, banksAndEquity, '')).toBe(true)
  })

  it('matches sub tags, not just the primary tag', () => {
    expect(matches(fx, toggle(NO_FILTERS, 'asset', 'JPY'), '')).toBe(true)
  })
})

describe('valuesOf', () => {
  it('derives the "other" facts from the record', () => {
    expect(valuesOf(tech, 'other')).toEqual([OTHER.pdf, OTHER.review])
    expect(valuesOf(wrap, 'other')).toEqual([OTHER.wrap, OTHER.nodate])
  })

  it('leaves the Unknown industry out of the filter', () => {
    expect(valuesOf(email({ industry_subindustry: ['Unknown'] }), 'industry')).toEqual([])
  })
})

describe('countValues', () => {
  it('counts each value with the other groups applied, but not its own group', () => {
    const filters = toggle(NO_FILTERS, 'bank', 'UBP')
    expect(countValues([fx, tech, wrap], filters, '', 'bank')).toEqual(
      new Map([
        ['Deutsche Bank', 2],
        ['UBP', 1],
      ]),
    )
    expect(countValues([fx, tech, wrap], filters, '', 'asset').get('FX')).toBeUndefined()
  })
})

describe('toggle', () => {
  it('adds and removes a value without changing the input', () => {
    const on = toggle(NO_FILTERS, 'bank', 'UBP')
    expect(on.bank).toEqual(['UBP'])
    expect(toggle(on, 'bank', 'UBP').bank).toEqual([])
    expect(NO_FILTERS.bank).toEqual([])
  })
})

describe('byDate', () => {
  it('puts the newest first and emails without a date last', () => {
    const older = email({ date: '2026-04-01', source_file: '035001' })
    expect([wrap, older, fx].sort(byDate).map((e) => e.source_file)).toEqual([
      '035300',
      '035001',
      '035245',
    ])
  })
})
