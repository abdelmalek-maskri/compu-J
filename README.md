# Research email classifier

Investment banks send their clients research by email: daily market recaps, notes on a
company, views on currencies or interest rates. This project takes 200 of those emails and,
for each one, works out who sent it, when, what it is about, and whether it is a "market
wrap" (a recap of what the markets did). It writes the answers to `classified_emails.json`,
and a small website (the dashboard) lets you search the results and read each email next to
its answers, under a strip of live market headlines.

## What you get

* **`classified_emails.json`**: one entry per email with the ten fields the brief asks for:
  title, bank, date, market wrap (YES or NO), main asset class, all asset classes, companies
  and industries (for company research only), PDF attachments, and the email's folder number.
* **`classified_emails_details.json`**: for each email, where every answer came from, so any
  value can be traced back to the email.
* **The dashboard**: search and filter the 200 emails, read each one safely, open its PDFs, and
  see which emails are worth a second look and why.

**Result:** all 200 emails classified, none failed. 15 emails are marked "worth checking",
each with the reason in plain words. On 20 independently labelled emails, bank and date are
20 of 20 right, and market wrap and main asset class 18 of 20 (details below).

## How each email is read

Every email is read twice, by two readers that work in different ways:

* **The model**: an AI language model (an LLM) that reads the whole email, like a person
  would. It answers every field. It understands meaning, but it can be wrong with confidence.
* **The rules**: ordinary Python code, no AI. They look for the bank's name in the logo or the
  signature, and for a date near the top of the email or in a PDF's file name. They cannot
  understand meaning, but they never invent anything.

The model's answer is used when the email confirms it: the bank it names must appear in the
email, and the date it gives must be quoted from the email. Otherwise the rules' answer is
used. When the two disagree, nothing is decided silently: the email is marked "worth
checking", with the reason, for example *"The AI dated it 13 April 2026, quoting 'April 13',
but that could not be confirmed: the quote must be in the email, give the full date..."*

## Run it

**The quickest way, with [Docker](https://www.docker.com/products/docker-desktop/):** copy the
email folders into `Data/`, optionally copy `.env.example` to `.env` and add a free
[Finnhub key](https://finnhub.io) for the headlines (without one, CNBC's public feed is used),
then:

```bash
docker compose up --build          # then open http://localhost:8000
```

This starts the dashboard and the headline fetcher, which refreshes every 10 minutes. It shows
the results already in this repository; nothing is sent to an AI model. The emails are read
from `Data/` but never copied into the image, and neither is `.env`.

**Without Docker, or to classify the emails again**, you need three things installed:
[uv](https://docs.astral.sh/uv/) (it sets up Python 3.11 and the project's packages),
[Node 22](https://nodejs.org) (for the dashboard), and the email folders, copied into `Data/`.
The emails are licensed research, so they are not in this repository.

```bash
uv sync                            # install the Python packages
cp .env.example .env               # then fill in the two keys below
uv run python classify.py          # classify every email, writes classified_emails.json
```

`.env` needs a free [Gemini key](https://aistudio.google.com) for the model and a free
[Finnhub key](https://finnhub.io) for the headlines. To run the model on your own machine
instead, install [Ollama](https://ollama.com) and set `LLM_MODEL=gemma` (it needs about 15 GB
of memory). Answers are saved, so running `classify.py` again costs nothing.

Then start the dashboard, in three terminals:

```bash
uv run uvicorn api.main:app --reload       # the server the dashboard reads from (port 8000)
uv run python fetch_news.py --every 10     # fetches headlines now, then every 10 minutes
cd web && npm ci && npm run dev            # the dashboard: open http://localhost:5173
```

**With `make`** (macOS and Linux have it), the same steps have short names: `make setup`,
`make classify`, `make dev` (the three above in one terminal; Ctrl+C stops them),
`make docker` and `make test`. `make` alone lists them all.

Tests use made up emails and a fake model, so they need no key and no data:
`uv run pytest` (197 tests) and `cd web && npm test` (10 tests). They run on every pull request.

## How it works

```text
Data/<folder>/        the email (HTML), its PDFs, its images
   │
   ▼  clean_emails.py       turn the HTML into plain text, read the PDFs' first pages,
   │                        and let the rules find the bank and date
   ▼  the model             one answer per email, in a fixed shape: only the brief's
   │                        tag names are accepted
   ▼  tag_rules.py          the brief's rules, for example: a market wrap gets no companies
   ▼  check_metadata.py     keep the model's bank, date and title only if the email confirms them
   ▼  flags.py              note every disagreement, in plain words
   │
classified_emails.json + classified_emails_details.json
   │
   ▼  api/                  a small server that reads those files and the emails
   ▼  web/                  the dashboard (React)
```

## What I found in the data, and what I did about it

I read through the emails before writing any rules. Most of the design comes from what turned
up:

1. **The emails have no subject, sender or date lines.** The brief says the folder name is the
   subject, but the folders are just numbers (`035239`). So the title, bank and date all have
   to be read from the body. The title goes in `folder_name`, the number in `source_file`.
2. **The first bank named is often not the sender.** A UBP email says "issued by Goldman
   Sachs"; a J. Safra Sarasin email quotes Barclays. So the rules look where the sender
   really appears (the logo, then the signature) instead of taking the first bank they see.
3. **Most dates in an email are not when it was published.** Subscription deadlines, webinar
   times, "data as of" dates, old dates on charts. I found that the times on each email's
   attached files show when it arrived, so a date is only accepted if it falls between a month
   before and a day after that.
4. **The AI first rejected good titles.** It retyped `’` as `'`, so its title did not match
   the email letter for letter. Titles are now compared word by word, ignoring punctuation.
5. **Local AI models were silently reading only part of each email.** Ollama reads 4,096
   tokens unless told otherwise; the longest email is about 24,700. I set it to 32,768 and
   wrote a test that proves the whole email is read.
6. **1,563 characters were lost when the emails were exported.** In 119 emails, apostrophes,
   quotes, accents and currency signs became `�`. The real character is gone from the file,
   so I worked each one out from its context: `KO�s` is `KO’s`, `Z�rich` is `Zürich`, and
   Whitbread's `c�800m` is `c£800m` because Whitbread reports in pounds. Every rule was checked
   against every place it applies. Only what people read is repaired; the files and what the
   AI reads are untouched.
7. **138 files say they use an old text encoding, but do not.** Browsers believed the label
   and garbled the accents, so the server ignores it and states the real one (UTF-8).
8. **Every email contains a hidden script, and many contain tracking images** that tell the
   bank who opened the email and when. The dashboard shows emails with scripts removed,
   blocked by the browser, and inside a sealed frame; images from the banks' servers load only
   if you ask.
9. **381 images pointed at the bank's internal mail archive** instead of the copy saved next
   to the email, so every saved logo and chart showed as broken. The server now points them at
   the saved copy.
10. **One email appears twice** (`035428` is a copy of `035427`), and 32 start with a security
    warning from the company's email filter. The warning is removed before the AI reads them.

## Accuracy

20 emails, picked to cover all seven main asset classes and seven banks, were labelled
independently and compared with the results (`evaluation/labels.csv`, scored by
`uv run python -m scripts.accuracy --score`):

| Field | Right | The model alone | The rules alone |
| --- | --- | --- | --- |
| Bank | 20 of 20 | 20 of 20 | 20 of 20 |
| Date | 20 of 20 | 19 of 20 | 20 of 20 |
| Market wrap | 18 of 20 | | |
| Main asset class | 18 of 20 | | |

Both mistakes are in emails the system had already marked "worth checking", so the marking
pointed a person at exactly the errors. One is T. Rowe Price's "Weekly market recap", which
the model wrongly called not a market wrap; the other is a Barclays digest of research notes
that it called a market wrap (debatable: it recaps research, not the markets). Combining the
two readers also fixed the one date the model missed on its own.

The labels were made by Claude, a different AI model from the one being scored, reading each
email; the judgement calls are explained in the file. 20 emails give a rough figure, not a
precise one.

## Known limits

* The accuracy check covers 20 emails, labelled by a second AI model: a rough figure, not a
  precise one.
* 14 emails have no date in the output, because none is stated in a way that can be proven.
* The character repair is a careful guess: a currency sign is taken as the euro unless the
  sentence was checked by hand.
* The dashboard is built to run on one computer. It has no login, which it would need before
  the licensed emails were shown to anyone else.
* The headlines come from Finnhub, with CNBC's public feed as a backup. Finviz, suggested in
  the brief, has no API and its terms discourage scraping, so it is not used.

## Where things are

```text
classify.py          classify every email
fetch_news.py        fetch the headlines
pipeline/            reading, cleaning, the model, the rules, the checks, the character repair
news/                the headline sources, and keeping the last good headlines if both fail
api/                 the server for the dashboard, and the code that makes emails safe to show
web/                 the dashboard
scripts/             preview what the model reads, test a model, compare two models, accuracy
evaluation/          the hand labels and the accuracy report
tests/               made up data only, never the licensed emails
Dockerfile, docker-compose.yml   the one command setup
```
