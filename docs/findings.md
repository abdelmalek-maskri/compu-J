# What I found, and what I decided

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
   before and a day after that. Uncertain dates are left empty, with the reason (see
   [How dates are decided](how-it-works.md#how-dates-are-decided)).
4. **The AI retypes titles.** It turned `’` into `'`, dropped lost characters ("isnt") or
   guessed them, so its title did not match the email letter for letter. Titles are now
   compared word by word, and when the AI's title matches a line of the email, the email's
   own line is used.
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
11. **The AI sometimes gives two answers that do not fit together, and the brief decides.**
    `035328` (Barclays, "Vedanta Resources") is about the company's bonds, not its shares. The
    AI named the company but did not call the email Equity (research on shares). The brief
    lists companies only for Equity research, so the names were removed. The result is right;
    the email is still marked "worth checking" so a person can see the AI disagreed with
    itself.
12. **Some emails only link to the report.** `035437` (T. Rowe Price, "Weekly market recap")
    is a short cover note with a button to the recap. The AI judged only the note and said it
    is not a market wrap, while choosing "Market Wrap" as its main asset class. That contradiction
    is flagged, and a person settled it in `evaluation/reviewed.csv`, which every run
    applies (see [How each email is read](how-it-works.md#how-each-email-is-read)).
13. **The AI used sub-tags as labels, not topics.** It tagged a note on Tencent "Emerging
    Markets" because Tencent is Chinese, and the brief's rule then added "Macro", although
    the note says nothing about any economy. I found 34 such cases by reading every email the
    rule had changed, and rewrote the AI's instructions to say what each sub-tag means.
14. **Asking the AI again changes some answers.** A second run moved 140 answers in 96
    emails, including some the change was not about. So each change was judged on all 200
    emails, and patterns were fixed with checks in Python, which answer the same way every
    time, rather than with more instructions to the AI.
15. **Lists of research notes looked like market wraps.** A daily list of company notes ticks
    almost every box of the brief's market wrap checklist, yet it summarises research, not how
    the markets moved. I added that distinction to the AI's instructions, which fixed most of
    them, and a market wrap answer that names another main asset class is now flagged. The AI
    still calls four such emails market wraps; nothing flags them, so they are listed as known
    mistakes rather than corrected by hand.

The whole process, with the numbers at each step, is in
[evaluation/how-the-results-were-checked.md](../evaluation/how-the-results-were-checked.md).
