# Architecture

Four small parts, joined by files rather than a database. Each one can be run, tested and
replaced on its own.

```text
Data/<folder>/  ──►  classify.py  ──►  classified_emails.json            ──►  api/  ──►  web/
(the emails)          │   ▲             classified_emails_details.json        (server)   (dashboard)
                      ▼   │                                                     ▲
                    the AI model                                                │
                    (Gemini or Ollama)                                          │
                                                                                │
news sources  ──►  fetch_news.py  ──►  output/headlines.json  ────────────────────┘
(Finnhub, CNBC)    (every 10 minutes)
```

## The parts

| Part | What it does | Runs |
| --- | --- | --- |
| **The classifier** (`classify.py`, `pipeline/`) | reads every email, asks the AI model, checks the answers, writes the two result files | once, by hand, when the emails or the rules change |
| **The news fetcher** (`fetch_news.py`, `news/`) | fetches market headlines and saves them to a file; keeps the last good set if every source fails | in the background, every 10 minutes |
| **The server** (`api/`) | reads the result files, the emails and the headlines, and serves them to the dashboard; makes each email safe to show | while the dashboard is open |
| **The dashboard** (`web/`) | the website: search, filters, the email reader, the headline strip | in the browser |

The AI model is only called by the classifier. The server and the dashboard never call it, so
browsing the results costs nothing and works offline.

## Where data lives

| File | Written by | Holds |
| --- | --- | --- |
| `classified_emails.json` | the classifier | the brief's ten fields for each email, nothing else |
| `classified_emails_details.json` | the classifier | for each email: where every answer came from, both readers' answers, flags, corrections |
| `evaluation/reviewed.csv` | a person | decisions on flagged answers, applied on every run |
| `output/llm_answers/` | the classifier | every AI answer, saved, so the same question is never asked twice |
| `output/runs/<run>/` | the classifier | each run's own copy of the results, its review list and a summary |
| `output/headlines.json` | the news fetcher | the latest headlines |

`Data/` holds the emails. They are licensed research, so they are not in the repository.

## The server's API

| Request | Returns |
| --- | --- |
| `GET /api/emails` | every email's ten fields, plus what the list needs: content type, whether the date is confirmed, the day it arrived, the number of flags |
| `GET /api/emails/{id}` | one email's fields, its details, and how many images it would load from the bank's servers |
| `GET /api/emails/{id}/html` | the email itself, made safe to show (`?images=true` also loads remote images) |
| `GET /api/emails/{id}/files/{name}` | a PDF or an image saved with the email |
| `GET /api/tags` | the brief's lists of banks, asset classes and industries, so the filters are never typed by hand |
| `GET /api/headlines` | the latest headlines, marked stale if the last fetch failed |
| `GET /api/health` | whether the result files and headlines are there |

The same server also serves the built dashboard at `/`.

## Safety

* **Emails are shown with their scripts removed**, inside a sealed frame, and the browser is
  told to refuse any script that is left.
* **Images from the banks' servers load only when the reader asks**, because they tell the
  bank who opened the email and when.
* **The server only hands out files from an email's own folder**, and only PDFs and images.
* **The server has no login**, so Docker makes it reachable from this computer only.
* **API keys stay on the server.** The dashboard never sees them.

## Running anywhere

`docker compose up --build` starts two containers from one image: the server (with the built
dashboard) and the news fetcher. They share the headlines file. The emails are read from
`Data/` on this computer, never copied into the image, and neither is `.env`.

## Where things are

```text
classify.py          classify every email
fetch_news.py        fetch the headlines
pipeline/            reading, cleaning, the model, the rules, the checks, the character repair
news/                the headline sources, and keeping the last good headlines if both fail
api/                 the server for the dashboard, and the code that makes emails safe to show
web/                 the dashboard
scripts/             preview what the model reads, test a model, compare two models, accuracy
evaluation/          the hand labels, the accuracy report, flagged answers a person settled,
                     and how the results were checked
tests/               made up data only, never the licensed emails
docs/                how it works, this page, decisions, screenshots
Dockerfile, docker-compose.yml   the one command setup
```
