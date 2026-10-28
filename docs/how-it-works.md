# How it works

What happens to each email, from the folder it arrives in to the answer in `classified_emails.json`.

## The steps

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
   ▼  reviewed.csv          flagged answers a person settled, applied on every run
   │
classified_emails.json + classified_emails_details.json
   │
   ▼  api/                  a small server that reads those files and the emails
   ▼  web/                  the dashboard (React)
```

## How each email is read

Every email is read twice, by two readers that work in different ways:

* **The model**: an AI language model (an LLM) that reads the whole email, like a person
  would. It answers every field. It understands meaning, but it can be wrong with confidence.
* **The rules**: ordinary Python code, no AI. They look for the bank's name in the logo or the
  signature, and for a date near the top of the email or in a PDF's file name. They cannot
  understand meaning, but they never invent anything.

The model's answer is used when the email confirms it: the bank it names must appear in the
email, the date it gives must be quoted from the email, and its title is copied from the
email's own line. Otherwise the rules' bank is used; the date works differently (see
[How dates are decided](#how-dates-are-decided)). When something is uncertain, nothing is
decided silently: the email is marked "worth checking", with the reason in plain words, for
example *"The email mentions 15 April 2026, after the day it arrived, so it is probably an
event or a deadline, not the day it was published."*

A third reader is a person, who only looks at flagged answers that code cannot settle. Each
decision is one line in `evaluation/reviewed.csv`, with the reason, and every run applies
them, so a decision is never lost. The dashboard shows them under "Reviewed", next to what the
AI had said. Four answers were settled this way; mistakes that nothing flags are listed, not
corrected by hand (see
[evaluation/how-the-results-were-checked.md](../evaluation/how-the-results-were-checked.md)).

## What the rules fix on their own

The brief sets some answers by rule, whatever the AI says. Python applies those rules after
the AI answers (`pipeline/tag_rules.py`), and writes down every change it makes in the email's
`corrections` list in `classified_emails_details.json`. These are not shown as "worth
checking": the brief decides them, so there is nothing for a person to judge.

| Rule from the brief | Changes on the 200 emails |
| --- | --- |
| A sub-tag brings its asset class: "Emerging Markets" means "Macro" too | 21: Macro 9, FX 5, Commodities 4, Fixed Income 2, Equity 1 |
| Companies and industries are listed only for Equity (research on shares) | 2, for example `035328`, research on a company's bonds |
| A market wrap has the main asset class "Market Wrap", that tag only, and no companies | applied to all 22 market wraps, without a note |
| An email that is not a market wrap cannot carry the "Market Wrap" tag | 1, on an email a person settled as not a market wrap |

To list them all:

```bash
python3 -c "import json; [print(i, c) for i, m in json.load(open('classified_emails_details.json')).items() for c in m['corrections']]"
```

## How dates are decided

The brief asks for the publication date. Most dates in a research email are something else,
so a date is only used when the email confirms it, and an uncertain date is left empty rather
than guessed:

| What the email shows | What is used | What the reader sees | Example |
| --- | --- | --- | --- |
| A date the model quotes from the email, within a month before the email arrived and a day after | that date, read from the quote by Python, so "02.04.2026" is always 2 April | the date | 180 of 200 emails |
| A weekday with no year, such as "Monday, 13 April" | that date: the weekday fits only one year | the date | `035427` |
| The model's date is confirmed, but the rules found another one higher up | the model's date | the date, no note: the email states it, so there is nothing to check | `035334`: "Published 10 Apr, 2026" |
| A date after the email arrived | nothing | "probably an event or a deadline" | `035341` |
| A date only the rules found, which the model rejected | nothing | the date it mentions, and why it is not used | `035255`: an article in a "you might have missed" box |
| A date that follows "as of" or "as at" | nothing: it is the day figures refer to | why it is not used | `035274`: "report as of 31.03.2026" |
| A date the model quoted that is not in the email as written | nothing | why it is not used | `035356`: "as at9 April 2026" |
| No date in the text, but one in a link address (a campaign code like `_20260413`) | the link's date | the date, marked **not confirmed** | `035330`, `035429`, `035437` |
| No date at all | nothing | "No publication date found", and the day it arrived when known | `035243` |

Why not use the day the email arrived instead? It is only known for 66 of the 200 emails (it
comes from the times on attached files), and where both are known it matches the publication
day in only 33 of 56. It is shown beside an empty date as a clue, never as the date.

The rules' date is never used on its own: every time the rules found a date the model
rejected, it was another kind of date (an article listed inside the email, a date in the
attachments' names). The rules still check the model, and when both find the same date it is used even if
the model's quote is incomplete.

What this gives on the 200 emails:

| Outcome | Emails | Which |
| --- | --- | --- |
| Date confirmed by the email | 180 | |
| Date confirmed by its weekday | 3 | `035335`, `035427`, `035428` |
| Date from a link, marked not confirmed | 3 | `035330`, `035429`, `035437` |
| Empty: a date only the rules found | 3 | `035255` (an article in a "you might have missed" box), `035348` (attachment names), `035431` (each note in a digest has its own date) |
| Empty: an "as of" date | 3 | `035258`, `035278` ("Levels as of"), `035274` ("report as of") |
| Empty: a date after the email arrived | 1 | `035341` |
| Empty: a date not in the email as written | 1 | `035356` |
| Empty: no date at all | 6 | `035243`, `035279`, `035327`, `035358`, `035359`, `035375` |

Every email in the empty rows and the link row is marked "worth checking" with its reason,
except the six with no date at all: there is nothing to check, so they only say "No
publication date found".

## Run it step by step

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
`uv run pytest` (231 tests) and `cd web && npm test` (17 tests). They run on every pull request.
