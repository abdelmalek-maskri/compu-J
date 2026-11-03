import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AskReply, Email } from '../api'
import { AskPanel } from './AskPanel'

const email: Email = {
  folder_name: 'Fragile ceasefire',
  bank: 'Barclays',
  date: '2026-04-09',
  market_wrap: 'NO',
  primary_asset_tag: 'Commodities',
  asset_tags: ['Commodities', 'Oil'],
  companies_mentioned: [],
  industry_subindustry: [],
  pdf_attachment: null,
  source_file: '035241',
  content_type: 'research',
  date_confirmed: true,
  received: null,
  flag_count: 0,
}

const reply: AskReply = {
  question: 'What is the view on oil?',
  mode: 'hybrid',
  answered: true,
  missing: '',
  points: [
    { claim: 'Brent near 85', source: 1, quote: 'stay near USD 85', verified: true, problem: null },
    {
      claim: 'Oil will double',
      source: 2,
      quote: 'double',
      verified: false,
      problem: 'the quote is not in source 2',
    },
  ],
  sources: [
    {
      n: 1,
      email_id: '035241',
      title: 'Fragile ceasefire',
      bank: 'Barclays',
      date: '2026-04-09',
      pdf: null,
      page: null,
      where: 'email body',
      text: 'Brent crude should stay near USD 85.',
      keyword_rank: null,
      vector_rank: 1,
    },
    {
      n: 2,
      email_id: '035432',
      title: 'Weekly Advisory Call',
      bank: 'Julius Baer',
      date: '2026-04-13',
      pdf: '13.04.2026 WAC.pdf',
      page: 26,
      where: '13.04.2026 WAC.pdf, page 26',
      text: 'Oil and gold.',
      keyword_rank: 4,
      vector_rank: 9,
    },
  ],
}

function answering(body: unknown, status = 200) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const sent = (fetchMock: ReturnType<typeof answering>, call = 0) =>
  JSON.parse((fetchMock.mock.calls[call] as unknown as [string, RequestInit])[1].body as string)

afterEach(() => vi.unstubAllGlobals())

describe('AskPanel', () => {
  it('sends the question with its filters and shows the checked answer', async () => {
    const fetchMock = answering(reply)
    render(<AskPanel emails={[email]} tags={null} onOpen={() => {}} />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'What is the view on oil?')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Bank' }), 'Barclays')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(sent(fetchMock)).toEqual({
      question: 'What is the view on oil?',
      mode: 'hybrid',
      bank: 'Barclays',
      sources_only: false,
    })
    expect(await screen.findByText('Brent near 85')).toBeInTheDocument()
    expect(screen.getByText('Not verified: the quote is not in source 2')).toBeInTheDocument()
    expect(screen.getByText('Keywords — · Meaning #1')).toBeInTheDocument()
  })

  it('links a PDF passage to its page', async () => {
    answering(reply)
    render(<AskPanel emails={[email]} tags={null} onOpen={() => {}} />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'oil{Enter}')
    const link = await screen.findByRole('link', { name: /page 26/ })
    expect(link).toHaveAttribute('href', '/api/emails/035432/files/13.04.2026%20WAC.pdf#page=26')
  })

  it('opens the cited email from the answer and from the sources', async () => {
    answering(reply)
    const onOpen = vi.fn()
    render(<AskPanel emails={[email]} tags={null} onOpen={onOpen} />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'oil{Enter}')
    await userEvent.click(await screen.findByRole('button', { name: 'Open source 2' }))
    await userEvent.click(screen.getByRole('button', { name: 'Fragile ceasefire' }))
    expect(onOpen.mock.calls).toEqual([['035432'], ['035241']])
  })

  it('asks again when the search mode changes after an answer', async () => {
    const fetchMock = answering(reply)
    render(<AskPanel emails={[email]} tags={null} onOpen={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Keywords' }))
    expect(fetchMock).not.toHaveBeenCalled()
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'oil{Enter}')
    await screen.findByText('Brent near 85')
    await userEvent.click(screen.getByRole('button', { name: 'Meaning' }))
    expect(sent(fetchMock, 1).mode).toBe('vector')
  })

  it('asks for passages only when no answer is wanted', async () => {
    const fetchMock = answering({ ...reply, answered: null, points: [] })
    render(<AskPanel emails={[email]} tags={null} onOpen={() => {}} />)
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'oil{Enter}')
    expect(sent(fetchMock).sources_only).toBe(true)
    expect(await screen.findByText('Fragile ceasefire', { selector: 'button' })).toBeInTheDocument()
    expect(screen.queryByText('Answer')).not.toBeInTheDocument()
  })

  it("shows the API's reason when it cannot answer", async () => {
    answering({ detail: 'no search index yet: run `uv run python -m rag.ingest`' }, 503)
    render(<AskPanel emails={[email]} tags={null} onOpen={() => {}} />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'oil{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('rag.ingest')
  })

  it('starts from the bank picked in the email filters', () => {
    render(<AskPanel emails={[email]} tags={null} initialBank="Barclays" onOpen={() => {}} />)
    expect(screen.getByRole('combobox', { name: 'Bank' })).toHaveValue('Barclays')
  })
})
