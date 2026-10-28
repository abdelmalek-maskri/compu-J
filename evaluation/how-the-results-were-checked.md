# How the results were checked and improved

This page explains how I checked the AI's answers after the first full run, what was wrong,
how I found it, and what I changed. It assumes no knowledge of the project beyond the
README's first paragraph.

## A few words first

* **A run** means sending all 200 emails to the AI model once and saving its answers. A run
  takes about five minutes. Answers are saved, so the code around the AI can be changed and
  re-applied to the same answers without asking the AI again.
* **The prompt** is the set of written instructions the AI receives with every email: what
  each field means and which answers are allowed. Each version has a number, and every
  record says which version produced it. Version 1 was only used while building the
  project; the three versions on this page are v2, v3 and v4.
* **The rules** are ordinary Python code, no AI. Some apply the brief's fixed rules (for
  example, a market wrap never lists companies); others check the AI's answers against the
  email (for example, a date must be quoted from the email).
* **A flag** ("worth checking" in the dashboard) is how the system asks a person to look at
  an answer, with the reason in plain words.

## 1. The first run looked fine, so I looked at what the rules had changed

The first full run (prompt v2) classified all 200 emails, and on 20 emails labelled
independently it got the bank and the main asset class right in nearly every case. But a
score on 20 emails cannot show a mistake that happens in other emails, so I also inspected
the 64 changes the rules had made to the AI's answers on their own.

63 of them were the same rule: the brief says a sub-tag brings its asset class, so an email
tagged "Emerging Markets" also gets "Macro". I read every one of those 63 emails to see if
the added class was right. **34 were wrong.** The AI was using sub-tags as labels instead of
topics:

| What the AI did | The rule then added | Example |
| --- | --- | --- |
| Tagged "Emerging Markets" because a company is in China | Macro (the economy) | `035301`, a note on Tencent's cloud prices |
| Tagged "USD" because the bonds are priced in dollars | FX (currencies) | `035246`, US interest rate options |
| Tagged "Energy" because the company works in energy | Commodities | `035318`, a pipeline company |

So filtering the dashboard by "Macro" showed single-company notes that say nothing about any
economy.

**What I did:** the prompt (v3) now explains each sub-tag: "Emerging Markets" means the email
discusses those economies, not that a company is located there; "USD" means the email
discusses the dollar's moves, not that prices are in dollars; and so on.

**Result:** the wrongly added classes went from 34 to 7, and 13 of the 16 that were right were
kept.

## 2. Asking the AI again also changed answers I had not touched

Comparing the second run with the first showed 140 differences across 96 emails, although
the prompt change was only about sub-tags. For example, 6 emails changed between "market
wrap" and "not a market wrap", and 20 titles changed. Some got better, some got worse.

This is normal for an AI model: asked the same question twice, it does not always answer the
same way. It taught me two things:

* Each change to the prompt has to be judged on all 200 emails, not only on the emails it
  was meant to fix.
* Changing the prompt again and again would chase this noise. Mistakes that follow a clear
  pattern are better fixed by checks in Python, which give the same answer every time.

## 3. I read all 200 emails and listed every clear mistake

To know where the second run (prompt v3) really stood, I compared every answer with the
email itself: the start of each email, and the text of its PDFs. **21 clear mistakes**, in
21 emails. Another 22 answers were debatable, where a careful reader could go either way.
The bank was never wrong.

| Field | Mistakes | The pattern |
| --- | --- | --- |
| Market wrap | 7 | all said "yes" wrongly: a list of research notes, a report on one asset class only, or a shipping data tracker |
| Title | 9 | a label above the headline was taken instead of the headline, such as "Kering (PRTP.PA)" or "Biopharma" |
| Asset classes | 3 | a class still added from a sub-tag used as a label |
| Date | 2 | "02.04.2026" read as 4 February instead of 2 April; one date missed |

The market wrap mistakes were not flagged, because the AI's own checklist agreed with its
wrong answer. A list of research notes ticks almost every box of the brief's checklist (many
short sections, several topics, recent news), yet it is a summary of research, not of how
the markets moved.

## 4. What I changed

**The prompt (v4)**, one general rule for each pattern above, not answers for particular
emails:

* A market wrap recaps how prices moved across several asset classes, daily or weekly. A
  list of research notes is not one, and neither is a report on one asset class only, a
  preview of the week ahead, or a note whose purpose is an investment view.
* When a label sits above the headline, the headline is the title.
* A date such as 02.04.2026 is day, month, year.

**Checks in Python**, which apply to every email and every future run:

* **The date is read from the AI's quote.** The AI must quote where it found the date;
  Python now reads that quote itself, so the AI misreading "02.04.2026" no longer matters.
* **An "as of" date is not a publication date.** If the quoted date follows "as of" in the
  email, it is the day the figures refer to, so it is not used.
* **The title is copied from the email.** When the AI's title matches a line of the email,
  the email's own line is used, so no character is lost or guessed.
* **A market wrap answer that contradicts itself is flagged.** If the AI says "market wrap"
  but names a different main asset class, a person is asked to look.

**A person settles only what is flagged.** When the system flags an answer and code cannot
settle it, a person decides, and the decision is one line in `evaluation/reviewed.csv`, with
the reason. Every run applies that file, so a decision is never lost, the dashboard shows it
under "Reviewed", and the AI's own answer stays in the details file next to it. Four answers
were settled this way, each one flagged first:

| Email | Flag | Decision |
| --- | --- | --- |
| `035437` | the AI chose "Market Wrap" as the main asset class but said it is not a market wrap | a market wrap: a weekly market recap behind a link |
| `035375` | the AI said market wrap but chose FX as the main asset class | not a market wrap: a currency preview of the week ahead |
| `035410` | the AI said market wrap but chose Commodities as the main asset class | not a market wrap: a metals and mining weekly |
| `035368` | the AI's title is not in the email | the title is inside an image, so a person typed it |

Mistakes that nothing flags are not corrected by hand, even when I know of them from reading
the emails. Correcting them would make the submitted file partly hand made, and it would not
work for thousands of emails. They are listed below instead.

## 5. Where it ended

| | First run (v2) | Second run (v3) | Third run (v4) | Submitted |
| --- | --- | --- | --- | --- |
| Classes added from a sub-tag used as a label (of the 34 found) | 34 | 7 | 7 | 7 |
| Emails wrongly called a market wrap | 12 | 8 | 6 | 4 |
| Titles that are a label or empty | 8 | 10 | 10 | 9 |
| Titles with a lost or garbled character | 4 | 3 | 5 | 0 |
| Dates misread or missed | 0 | 2 | 1 | 0 |
| Market wrap, on the 20 labelled emails | 19 of 20 | 19 of 20 | 20 of 20 | 20 of 20 |
| Main asset class, on the 20 labelled emails | 19 of 20 | 19 of 20 | 20 of 20 | 20 of 20 |

The first five rows count the mistakes found by reading the emails, so each column counts
only the kinds of mistake listed in sections 1 and 3. The first run's market wrap figure
includes four emails that later runs got right, which I judged when comparing the runs.

To get the submitted column I read all 200 submitted results once more, the same way as in
section 3.

## Accuracy on 20 labelled emails

20 emails, picked to cover all seven main asset classes and seven banks, were labelled
independently and compared with the results (`evaluation/labels.csv`, scored by
`uv run python -m scripts.accuracy --score`):

| Field | Right | The model alone | The rules alone |
| --- | --- | --- | --- |
| Bank | 20 of 20 | 20 of 20 | 20 of 20 |
| Date | 18 of 20 | 19 of 20 | 20 of 20 |
| Market wrap | 20 of 20 | | |
| Main asset class | 20 of 20 | | |

"The model alone" and "the rules alone" score each reader's own answer before the two are
combined; market wrap and main asset class come from the model only. One of the 20 labelled
emails, T. Rowe Price's "Weekly market recap", is among the answers a person settled
([finding 12](../docs/findings.md)), so without that correction market wrap and main asset class would be 19 of 20.

The two date misses follow from choices described in
[How dates are decided](../docs/how-it-works.md#how-dates-are-decided). The Barclays digest lists notes with their
own dates, and none is stated as the digest's, so its date is left empty; the labeller took
the newest note's. The T. Rowe Price recap states no date, so it shows the date from its
links, marked not confirmed; the label says none.

The labels were made by Claude, a different AI model from the one being scored, reading each
email; the judgement calls are explained in the file. 20 emails give a rough figure, not a
precise one, which is why I also read all 200 results, as described above.

## Known mistakes in the submitted file

20 mistakes in 18 emails, none of them flagged, so none corrected by hand. The bank, the
date and the main asset class have none.

| Field | Mistakes | Emails |
| --- | --- | --- |
| Market wrap | 4 | `035329` and `035435` (daily lists of company research notes), `035360` (Japanese equities only), `035261` (technical analysis with views) |
| Title | 9 | a label taken instead of the headline: `035338`, `035347`, `035384`, `035394`, `035413`, `035421`, `035422`; a table's first line on two rates sheets: `035258`, `035278` |
| Asset classes | 5 classes in 4 emails | a class added from a sub-tag used as a label: `035315` (two), `035367`, `035374`, `035438` |
| Companies | 2 | `035314` leaves out the two companies in its title; `035394` lists peers mentioned only in passing |

Another 20 or so answers are debatable, where a careful reader could go either way.

## What is still not perfect

* **Seven added classes remain from the list of 34.** Five are clearly wrong (the five in the
  table above, in four emails), such as Macro
  on `035374` (a note on Chinese healthcare companies) and FX on `035367` (euro government
  bonds); two are debatable. They are not the same seven as in the second run: another sign
  that each run moves some answers.
* **These figures are optimistic.** The same 200 emails were used to find the problems, to
  write the new instructions and checks, and then to measure the result, and I did the
  measuring. On emails the system has never seen, the error rate would very likely be
  higher. A fair measure needs a fresh set of emails.
* **Some market wrap decisions are a matter of definition.** For example, the Asia-Pacific
  weekly equity report (`035383`) is called a market wrap while similar reports for China,
  Japan and Europe are not.
* **Wrongly added classes could only be reduced with a new run.** An added class is one the
  brief's sub-tag rule adds, such as Macro for "Emerging Markets". Of the 21 classes the rule
  added in the submitted run, 11 are right, 5
  debatable and 5 wrong. Python cannot tell a sub-tag used as a topic from one used as a
  label, so any change in code treats all 21 alike:

  | Option | What happens | Result |
  | --- | --- | --- |
  | Keep adding the class (submitted) | the brief's rule, applied as written | 5 wrong, 11 right |
  | Drop the stray sub-tag instead | no class added, the sub-tag removed | fixes the 5 but breaks the 11 right ones, such as `035313` (Japan's wages and central bank) losing Fixed Income and FX |
  | Flag every case for a person | 21 new flags | 16 are false alarms, and asset classes would be corrected by hand |
  | Change the shape of the AI's answer | the AI picks each asset class first and may only choose sub-tags under it, so a stray sub-tag cannot happen | removes the cause, but needs a new run of all 200 emails |

  The submitted run keeps the first option, the best that code alone can do here. The last
  option is the proper fix for a future run.
* **The known mistakes above reach no one through the system.** The next step would be a
  second AI model reading the same emails, so that the answers where the two disagree are
  flagged for a person. The project already has a script for that comparison
  (`scripts/compare_models.py`).
