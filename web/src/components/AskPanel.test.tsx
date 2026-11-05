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
  picture_from_question: null,
  points: [
    {
      claim: 'Brent near 85',
      source: 1,
      quote: 'stay near USD 85',
      verified: true,
      problem: null,
      from_picture: false,
    },
    {
      claim: 'Oil will double',
      source: 2,
      quote: 'double',
      verified: false,
      problem: 'the quote is not in source 2',
      from_picture: false,
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
      picture: null,
      image: null,
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
      picture: null,
      image: null,
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
    expect(screen.getByText('Keywords \u2014 \u00B7 Meaning #1')).toBeInTheDocument()
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

  it('waits for Ask after the search mode changes', async () => {
    const fetchMock = answering(reply)
    render(<AskPanel emails={[email]} tags={null} onOpen={() => {}} />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'oil{Enter}')
    await screen.findByText('Brent near 85')
    await userEvent.click(screen.getByRole('button', { name: 'Meaning' }))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(sent(fetchMock, 1).mode).toBe('vector')
  })

  it('asks for passages only when no answer is wanted', async () => {
    const fetchMock = answering({ ...reply, answered: null, points: [] })
    render(<AskPanel emails={[email]} tags={null} onOpen={() => {}} />)
    await userEvent.click(screen.getByRole('checkbox', { name: /Write an answer/ }))
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

  it('marks picture sources, shows the image and labels points taken from them', async () => {
    const chart = {
      ...reply.sources[0],
      n: 1,
      picture: 'chart',
      image: 'inline/image_1.png',
      text: '[chart] Italy: 0.26',
    }
    answering({
      ...reply,
      points: [{ ...reply.points[0], from_picture: true }],
      sources: [chart],
    })
    render(<AskPanel emails={[email]} tags={null} onOpen={() => {}} />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'gas{Enter}')
    expect(await screen.findByText('chart')).toBeInTheDocument()
    expect(screen.getByRole('img')).toHaveAttribute(
      'src',
      '/api/emails/035241/files/inline%2Fimage_1.png',
    )
    expect(screen.getByText(/From a picture description written by AI/)).toBeInTheDocument()
  })

  it('limits the search to one kind of picture', async () => {
    const fetchMock = answering(reply)
    render(<AskPanel emails={[email]} tags={null} onOpen={() => {}} />)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Pictures' }), 'cartoon')
    await userEvent.type(screen.getByRole('textbox', { name: 'Question' }), 'Iran{Enter}')
    expect(sent(fetchMock).picture).toBe('cartoon')
  })

  it('says when the question narrowed the search to a kind of picture, and can undo it', async () => {
    const fetchMock = answering({ ...reply, picture_from_question: 'cartoon' })
    render(<AskPanel emails={[email]} tags={null} onOpen={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: /funny cartoons with Khamenei/ }))
    expect(sent(fetchMock).picture).toBeUndefined()
    expect(await screen.findByText(/Searched cartoons only/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Search everything instead' }))
    expect(sent(fetchMock, 1).read_question).toBe(false)
  })

  it('starts from the bank picked in the email filters', () => {
    render(<AskPanel emails={[email]} tags={null} initialBank="Barclays" onOpen={() => {}} />)
    expect(screen.getByRole('combobox', { name: 'Bank' })).toHaveValue('Barclays')
  })
})
