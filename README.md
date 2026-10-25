# Research email classifier

Reads market research emails from investment banks, asks an LLM to tag each one with asset
classes, companies and industries, checks the answer, and writes `classified_emails.json`.
A dashboard to browse the results comes next.

> **Status:** the classification pipeline is done. Still to come: a full run over all 200
> emails, an accuracy check on hand labelled emails, the news ticker and the dashboard. This
> README is updated as each part lands.

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
| 6. Tests | `uv run pytest` | 139 tests with fake models | Need no model and no data (the one real data test skips without `Data/`) |

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

## Output

```text
classified_emails.json        the deliverable; only written by a run over every email
output/                       everything else the pipeline creates (not committed)
  cleaned_emails/<id>.txt     what the model reads
  llm_answers/<model>/        saved answers: <id>_<prompt version>_<key>.json
  runs/<run>/                 one folder per classify.py run
    classified_emails.json
    review.csv                flags, with an empty your_verdict column
    summary.txt
  comparisons/<models>_<emails>/
    <model>.json              each model's answers
    review.csv                flags and model vs model differences
    agreement.txt             speed and agreement per field
```

Each record has the brief's ten fields, in its order, plus a `meta` object with everything
else: where each value came from, both answers for bank and date, the market wrap checklist,
flags, warnings and the model and prompt version used.

## Files

```text
classify.py                   classify every email (step 3)
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
* 18 of the 200 emails state no publication date, so their date stays empty unless the model
  finds one it can quote.
* The emails were converted to UTF-8 when they were exported into these folders, but the
  export did not update the encoding written inside the HTML (138 files still say
  `windows-1252`, `iso-8859-1` or similar), and in 140 files it replaced characters it could
  not convert with `�`, mostly apostrophes, quotes, dashes and accents. Those characters are
  lost. The pipeline reads every file as UTF-8 (one file, `035432`, was never converted and is
  read as Windows-1252), ignores the outdated labels, and leaves the `�` as they are.
* The Gemini model names and free limits come from current guides; Google AI Studio shows the
  real ones for your project, and a name is one line in `model_presets.py`.
