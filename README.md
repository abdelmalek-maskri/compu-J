# Research email classifier

Reads market research emails from investment banks, asks an LLM to tag each one with asset
classes, companies and industries, checks the answer, and writes `classified_emails.json`.
A dashboard shows the results next to the emails themselves, under a live news ticker.

> **Status:** the pipeline, the full run over all 200 emails, the news ticker and the
> dashboard are done. Still to come: an accuracy check on hand labelled emails. This README is
> updated as each part lands.

## Quick start

You need [uv](https://docs.astral.sh/uv/) (it installs the right Python, 3.11, by itself).

```bash
uv sync                     # install everything from uv.lock
cp .env.example .env        # then choose a model in .env (see below)
```

Put the email folders in `Data/` (one folder per email, as provided). They are licensed
research, so they are not in this repository.

Choose a model in `.env` with `LLM_MODEL`:

| `LLM_MODEL` | Runs | Needs | Notes |
| --- | --- | --- | --- |
| `gemma` | on your machine, through [Ollama](https://ollama.com) | `ollama pull gemma4:26b-a4b-it-qat` (about 15 GB of memory) | private and free, about 20 to 50 seconds per email |
| `gpt-oss-20b` | on your machine, through Ollama | `ollama pull gpt-oss:20b` (about 12 GB) | private and free |
| `gemini-flash-lite` | Google cloud | `GEMINI_API_KEY` from [AI Studio](https://aistudio.google.com) | fast; free tier about 500 requests a day |
| `gemini-flash` | Google cloud | `GEMINI_API_KEY` | stronger; free tier about 20 requests a day |

## Running it, step by step

| Step | Command | What it does | Why |
| --- | --- | --- | --- |
| 1. Preview | `uv run python -m scripts.preview_cleaned_emails` | Cleans every email and saves what the model will read to `output/cleaned_emails/`. Prints how many banks and dates were found | See exactly what the model gets. No model needed |
| 2. Smoke test | `uv run python -m scripts.smoke_test_llm --model gemma` | Sends two requests: one checks the answer format, one checks that a 12,000 token input is read whole | Catches a wrong key, a missing model or a cut off input in seconds |
| 3. Classify | `uv run python classify.py` | Classifies every email and writes `classified_emails.json` | The brief's main step |
| 4. Review | open `output/runs/<run>/review.csv` | Lists every disagreement found (see "Flags" below), with an empty `your_verdict` column | A person checks the doubtful cases |
| 5. Compare models | `uv run python -m scripts.compare_models --models gemma gemini-flash-lite --emails 10` | Runs the same emails through each model and compares speed and answers | Decide which model to trust |
| 6. News headlines | `uv run python fetch_news.py --every 10` | Fetches financial headlines every 10 minutes into `output/headlines.json` for the dashboard's ticker | The ticker reads a local file, so it is fast and keeps working when the news source is down |
| 7. Dashboard | `uv run uvicorn api.main:app --reload`, and in a second terminal `cd web && npm install && npm run dev` | Starts the API on port 8000 and the dashboard on <http://localhost:5173> | Browse, search and filter the classified emails, read each one safely, and see the news |
| 8. Tests | `uv run pytest`, and `cd web && npm test` | 194 Python tests with fake models, 10 dashboard tests | Need no model and no data (the one real data test skips without `Data/`) |

The dashboard needs Node 22. The API's documentation is at <http://localhost:8000/docs>.

Useful options:

```bash
uv run python classify.py --limit 10            # the first 10 emails only
uv run python classify.py --only 035299 035243  # these emails only
uv run python classify.py --force               # ask the model again, ignore saved answers
LLM_MODEL=gemini-flash-lite uv run python classify.py --limit 5   # another model, once

uv run python -m scripts.compare_models --models gemma gpt-oss-20b --only 035299 035243
uv run python -m scripts.compare_models --models gemma gemini-flash-lite --emails 10 --no-run
```

Answers are saved per email, prompt and model, so a second run, or adding one more model to a
comparison, only asks the model what it has not answered yet. `--no-run` compares saved answers
without calling any model.

## How it works

```text
Data/<id>/emailbody.html + PDFs
  |
  |  clean_emails.py    HTML to text (logos, paragraphs, table rows kept), quarantine banner
  |                     removed, attachments, first pages of PDFs, arrival date, and Python's
  |                     own guess at the bank and date
  v
cleaned text  ->  prompt.py + llm_client.py  ->  the model's answer (shape fixed by schema.py)
                  (answers saved by llm_cache.py)
  |
  |  tag_rules.py       the brief's rules: market wrap values, parent tags, Equity only fields
  |  check_metadata.py  title, bank and date: the model's answer when the email confirms it,
  |                     otherwise Python's
  |  flags.py           disagreements for a person to look at
  v
build_record.py  ->  classified_emails.json  +  review.csv
```

### The main decisions

**The model decides meaning, Python checks facts.** Every wrong value a rule produced during
development was a language mistake: "issued by Goldman Sachs" made a UBP email look like
Goldman's, and a subscription deadline was read as a publication date. So the model decides,
and Python checks what can be checked exactly:

| Field | The model's answer is used when | Otherwise |
| --- | --- | --- |
| bank | that bank's name appears in the email | Python's answer (logo, then signature, then top of the email) |
| date | its quote is in the email, says that date, and falls between 31 days before and 1 day after the email arrived | Python's answer, or empty |
| title | always; marked if it is not found in the email | |
| market wrap | always; its answers to the brief's checklist are kept as its reasons | |

Both the model's and Python's answers are saved on every record, so the two can be compared.

**How "appears in the email" is checked.** Both texts are reduced to their words, in lower
case, before comparing: punctuation and extra spaces do not count, and the words must appear
whole and in the same order. So the model's `Iran's next move` matches the email's
`Iran’s next move` or `Iran�s next move`, but `FX` does not match inside `AFX`. Without this,
correct titles would be flagged as missing, because models retype curly quotes and dashes as
plain ones, and the export left `�` in many emails (see Known limits).

**Flags, not silent choices.** When the model and Python disagree, or the model contradicts
itself (for example "market wrap" while its checklist says the purpose is analytical), the
record gets a flag and `review.csv` gets a row. Comparing two models adds a row for every field
they answered differently.

**The brief and the data differ in one place.** The brief takes the subject from the folder
name, but the folders are numbered (`035239`) and the emails have no headers. So
`folder_name` holds the title found in the email, and `source_file` holds the folder number.

**Local models need a bigger window.** Ollama reads only 4,096 tokens by default and silently
cuts the rest. The longest cleaned email is about 24,700 tokens, so the window is set to 32,768,
and the smoke test proves it is applied.

**A failed email still gets a record**, with what Python found and the error. A problem that
would hit every email (wrong key, missing model, daily quota used up) stops the run, keeps what
was finished, and the next run carries on.

### The news ticker

`fetch_news.py` takes headlines from [Finnhub](https://finnhub.io)'s news API (free key in
`.env` as `FINNHUB_API_KEY`), or from CNBC's public RSS feed when there is no key or Finnhub
fails. Finviz, suggested in the brief, was left out: it has no API, and its terms discourage
automated access, so scraping it would be both fragile and against its rules.

* **One fetch for every viewer.** The script writes a local file and the dashboard reads it,
  so the news source gets one request every 10 minutes (144 a day, against Finnhub's free 60 a
  minute) however many people use the dashboard, and the API key never reaches the browser.
* **Old news beats no news.** If every source fails, the last good headlines are kept and
  marked `"stale": true` with the time they were really fetched, so the ticker can warn
  instead of going blank.
* **Outside data is not trusted.** Headlines are stored as plain text with `https` links
  only, and the RSS feed is read with `defusedxml`, which refuses malicious XML.
**The date field only holds dates the email states.** That means a date printed in the email,
a date in an attachment's file name, or a date the model quotes from the email. A date that is
only inferred, such as a campaign code in a link address (`..._20260413`), is never put in the
date field: it goes in `meta.date_hint` and gets an `inferred` flag, so a person can confirm it.

## What we found in the data

Looking closely at the 200 emails before and while building changed several decisions.

* **No subjects, no senders.** The folders are numbered and the emails have no headers (no
  From, Subject or Date lines), so title, bank and date all have to be read from the body.
* **Other banks' names appear in the text.** "Issued by Goldman Sachs" sits in an email from
  UBP; "Barclays estimates that..." in one from J. Safra Sarasin. The sender is named in the
  logo or the signature, not wherever a bank name first appears.
* **Not every date is the publication date.** Emails also mention subscription deadlines,
  webinar times, the date data is "as of", and old dates on charts. One email even lists
  several articles, each "Published on" its own day. A date must fall between 31 days before
  and 1 day after the email arrived (known from its attachments' file times) to be accepted.
* **Dates are written many ways**: `9 April 2026`, `07-Apr-26`, `10th April 2026`,
  `April 7th, 2026`, `13 Apr, 2026`, `09.04.2026`, and `20260409` in file names. Dates like
  `04/10/2026` are skipped, because they can be read as April 10 or October 4, and even one
  bank writes both orders.
* **17 emails have no date the rules can find.** 16 state none at all. The other, `035433`,
  prints "Published 13 Apr, 2026" only at the very bottom, where the model can find and quote
  it. Three of the 17 have a likely send date hidden in a link address; those are kept as
  hints, not dates.
* **The export damaged some characters.** 140 emails contain `�` where an apostrophe, quote,
  dash, accent or currency sign was lost when the emails were exported. They are put back for
  reading (see the next section).
* **Every email contains an injected script** and many load tracking images from the banks'
  servers, so the dashboard must show emails in a sandbox, without scripts.
* **One email appears twice** (`035428` is a copy of `035427`), and 32 start with an email
  security warning that is removed before classifying.

### Putting back the lost characters

When the emails were exported, every character the exporter could not read became `�`. The
file itself holds `�`, so the original character is gone and cannot be decoded back; it has to
be worked out from the words around it. `pipeline/repair_text.py` does that for all 1,563 signs
in the 200 emails, and none are left in what the dashboard shows. Some real examples:

| In the file | Shown | How it is decided |
| --- | --- | --- |
| `KO�s fundamentals`, `don�t`, `we�ll` | `KO’s`, `don’t`, `we’ll` | a letter, the sign, then `s`, `t`, `ll`, `re`, `ve`, `d` or `m` is an apostrophe (about 480) |
| `the �Bank�`, `(�DFSA�)` | `the “Bank”`, `(“DFSA”)` | before a word it opens a quote, after one it closes it (about 380) |
| `Union Bancaire Priv�e`, `Rh�ne`, `Z�rich`, `BOTA� regulates` | `Privée`, `Rhône`, `Zürich`, `BOTAŞ` | a list of the 28 damaged words found in the emails, mostly accented names in the banks' legal footers |
| `Copyright � 2026 Deutsche Bank` | `Copyright © 2026` | the sign before a year (about 100) |
| `utilities�not staples`, `Mexico � Short-term` | `utilities—not`, `Mexico – Short-term` | between words it is a dash (about 200) |
| `revenue reached �848M` | `€848M` | before a number it is a currency; the research is mostly about European companies, so the euro |
| `Whitbread ... c�800m`, `PAL Group revenue �234.70B` | `c£800m`, `¥234.70B` | 9 phrases about UK or Japanese companies, listed by hand after reading each sentence |
| `Aug �20`, `Q4�25`, `200�000`, `2026�2028` | `Aug ’20`, `Q4’25`, `200’000`, `2026–2028` | years, Swiss thousands and ranges |
| a sign alone in its own cell, before a line of text | `•` | a bullet (about 190) |

Every rule was checked against every place it fires in the real emails, and the tests use
made up sentences for each one. Two limits are worth knowing. A guess can still be wrong where
the text gives too little to go on: a currency is assumed to be the euro unless the sentence
was read and listed. And the repair is for people reading: the dashboard and the titles in
`classified_emails.json` show the repaired text, but the model read the emails as exported, so
its saved answers, and the check that a title really appears in the email, are unchanged.

## Output

```text
classified_emails.json        the deliverable: the brief's ten fields, nothing else
classified_emails_details.json  everything else about each email, by folder number
output/                       everything else the pipeline creates (not committed)
  cleaned_emails/<id>.txt     what the model reads
  headlines.json              the ticker's headlines (fetch_news.py)
  llm_answers/<model>/        saved answers: <id>_<prompt version>_<key>.json
  runs/<run>/                 one folder per classify.py run
    classified_emails.json
    classified_emails_details.json
    review.csv                flags, with an empty your_verdict column
    summary.txt
  comparisons/<models>_<emails>/
    <model>.json              each model's answers
    review.csv                flags and model vs model differences
    agreement.txt             speed and agreement per field
```

`classified_emails.json` has exactly the brief's ten fields for each email, in its order, so it
matches the spec. Everything else is in `classified_emails_details.json`, keyed by folder number
(`source_file`): where each value came from, both the model's and Python's answers for bank
and date, a date hint, the market wrap checklist, corrections, flags, warnings, and the model
and prompt version used. The dashboard joins the two by folder number. Both files are only
written by a finished run over every email.

## Files

```text
classify.py                   classify every email (step 3)
fetch_news.py                 refresh the ticker's headlines (step 6)
news/
  headlines.py                Finnhub and RSS sources, checks, keeping the last good set
pipeline/
  clean_emails.py             read each email folder into clean text, attachments and Python's guesses
  allowed_tags.py             the brief's tag lists, written once
  prompt.py                   the instructions for the model, built from allowed_tags.py
  schema.py                   the shape of the model's answer and of each output record
  model_presets.py            the models above and their settings
  llm_client.py               calls the model: retries, rate limits, answer checks
  llm_cache.py                saves answers so nothing is asked twice
  tag_rules.py                the brief's tagging rules
  check_metadata.py           decides title, bank and date
  flags.py                    finds disagreements and writes review.csv
  build_record.py             puts one output record together
  paths.py                    where every output file goes
scripts/
  preview_cleaned_emails.py   step 1
  smoke_test_llm.py           step 2
  compare_models.py           step 5
tests/                        one test file per module, plus shared test data in factories.py
```

## Known limits

* No accuracy figures yet: they need emails labelled by hand, which comes next.
* 17 of the 200 emails have no date the rules can find, so their date stays empty unless the
  model quotes one from the email (see What we found in the data).
* The emails were converted to UTF-8 when they were exported into these folders, but the
  export did not update the encoding written inside the HTML (138 files still say
  `windows-1252`, `iso-8859-1` or similar), and in 140 files it replaced characters it could
  not convert with `�`, mostly apostrophes, quotes, dashes and accents. The pipeline reads
  every file as UTF-8 (one file, `035432`, was never converted and is read as Windows-1252)
  and ignores the outdated labels. The `�` are put back from their context for reading (see
  "Putting back the lost characters"); that is a well checked guess, not a recovery.
* The Gemini model names and free limits come from current guides; Google AI Studio shows the
  real ones for your project, and a name is one line in `model_presets.py`.
