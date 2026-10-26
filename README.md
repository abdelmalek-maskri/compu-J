# Research email classifier

Reads 200 market research emails from investment banks, tags each one with asset classes,
companies and industries, and writes `classified_emails.json`. A dashboard shows each result
next to the email it came from, under a live news ticker.

Every email is read twice, by two readers that work in different ways:

* **The model**: an AI language model (Gemini, or a local model through Ollama). It reads the
  whole email and answers every field: the tags, the companies, whether it is a market wrap,
  and also the bank, date and title.
* **The rules**: plain Python, no AI. They find the bank in the logo or the signature, and the
  date near the top of the email or in a PDF's file name. They cannot judge meaning, but they
  never invent anything.

The model's answer is used when the email confirms it. When the two disagree, nothing is
decided silently: the email is marked "worth checking", with the reason in plain words.

**Result on the full set:** 200 emails classified, none failed. The model and the rules agree
on the sending bank for all 200, and 17 disagreements on 15 emails are marked for a person to
check.

## Run it

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.11 itself), Node 22, and the
email folders in `Data/`. They are licensed research, so they are not in this repository.

```bash
uv sync
cp .env.example .env               # choose LLM_MODEL, add GEMINI_API_KEY and FINNHUB_API_KEY
uv run python classify.py          # writes classified_emails.json
```

Then the dashboard, in three terminals:

```bash
uv run uvicorn api.main:app --reload       # the API, on port 8000 (docs at /docs)
uv run python fetch_news.py --every 10     # the news, now and every 10 minutes
cd web && npm ci && npm run dev            # the dashboard, on http://localhost:5173
```

Tests need no model, no key and no data: `uv run pytest` (194 tests) and `cd web && npm test`.
CI runs both, plus linting and the type check, on every pull request.

| `LLM_MODEL` | Runs | Notes |
| --- | --- | --- |
| `gemini-flash-lite` | Google cloud, free key from [AI Studio](https://aistudio.google.com) | used for the submitted results |
| `gemma` | your machine, through [Ollama](https://ollama.com) | private and free, needs about 15 GB of memory |
| `gpt-oss-20b` | your machine, through Ollama | a second local model to compare against |

Answers are saved per email, prompt and model, so a second run only asks the model what it
has not answered yet. `scripts/compare_models.py` runs the same emails through two models and
lists every field they answer differently.

## How it works

```text
Data/<id>/  ─►  clean_emails.py   HTML to text, PDFs' first pages, arrival time,
                                  and the rules' own answer for the bank and date
            ─►  the model (AI)    one structured answer per email, its shape fixed
                                  by the brief's tag lists (schema.py, prompt.py)
            ─►  tag_rules.py      the brief's rules: market wrap values, parent tags,
                                  companies and industries only for Equity
            ─►  check_metadata.py the model's bank, date and title, kept only when
                                  the email confirms them
            ─►  flags.py          every disagreement, in plain words (review.csv)
            ─►  classified_emails.json            the brief's ten fields, nothing else
                classified_emails_details.json    where each value came from

api/   FastAPI: reads those files and the emails, serves them safely
web/   React + TypeScript + Tailwind: list, search, filters, reader, ticker
```

## The decisions that matter

* **The model decides meaning, the rules check facts.** Every wrong value the rules produced
  during development was a reading mistake: "issued by Goldman Sachs" made a UBP email look
  like Goldman's. So the model decides, and its bank, date and title are kept only if the
  email confirms them: the bank's name must appear, and a date must be quoted from the email
  and fall between 31 days before and 1 day after the email arrived.
* **Disagreements are marked, never settled silently.** Both answers are stored on every
  record. Each disagreement, or answer where the model contradicts itself, gets a plain
  reason ("The AI dated it 13 April 2026, quoting 'April 13', but that could not be
  confirmed..."), shown in the dashboard and listed in `review.csv` with a column for a
  person's verdict.
* **The deliverable matches the brief exactly.** `classified_emails.json` has the brief's ten
  fields in its order. Everything else (sources, both answers, flags, the model and prompt
  version) is in a separate details file keyed by folder number.
* **Emails are shown in three layers of protection.** Every exported email carries an
  injected script and many load tracking pixels. The API removes scripts and blocks remote
  images, sends a Content Security Policy, and the dashboard shows the email in a sandboxed
  frame. File requests cannot leave the email's folder.
* **The news is fetched by a script, not by the page.** One request every 10 minutes serves
  every viewer, the key never reaches the browser, and if Finnhub fails the CNBC feed takes
  over; if both fail, the last good headlines stay up, marked as old. Finviz was left out: it
  has no API and its terms discourage scraping.
* **Local models get the whole email.** Ollama reads 4,096 tokens by default and silently cuts
  the rest; the longest email is about 24,700, so the window is set to 32,768 and a smoke test
  proves it is applied.

## What we found in the data

Reading the 200 emails closely, before writing rules, changed the design:

* **No headers.** Folders are numbered and the emails have no subject, sender or date lines,
  so the brief's "folder name is the subject" cannot hold: `folder_name` holds the title read
  from the email, and `source_file` the folder number.
* **The first bank named is often not the sender.** Emails quote other banks' research. The
  sender is in the logo or the signature, and that is where the rules look.
* **Most dates in an email are not its publication date**: deadlines, webinar times, "data as
  of", old chart dates. The arrival window above, taken from the attachments' file times,
  rejects them. Dates like `04/10/2026` are never guessed, because one bank writes both orders.
* **1,563 characters were lost in the export.** Apostrophes, quotes, accents and currency signs
  became `�` in 119 emails. They are put back from context for reading (`KO�s` to `KO’s`,
  `Z�rich` to `Zürich`, `c�800m` to `c£800m` for Whitbread, which reports in pounds). The
  files are never changed, and the model reads the original text.
* **138 files declare the wrong encoding**, and 381 images point at the bank's mail archive
  instead of the copy saved with the email. The API corrects both when it serves an email.

## Known limits

* No accuracy figure yet: that needs emails labelled by hand. Until then the flags show where the model and the rules disagree.
* 14 emails have no date in the output, because none is stated in a form that can be proven.
* The character repair is a checked guess, not a recovery: a currency is taken as the euro unless the sentence was read and listed.
* Built to run on one machine: the API has no login, which it would need before the licensed emails were shown to anyone else.

## Layout

```text
classify.py, fetch_news.py   the two scripts
pipeline/                    cleaning, prompt, model calls, rules, checks, flags, repair
news/                        headline sources and the last good set
api/                         the dashboard's API and the email sanitiser
web/                         the dashboard
scripts/                     preview the cleaned text, smoke test a model, compare models
tests/                       one file per module, made up data only
```
