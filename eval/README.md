# Evaluation

How the offline pipeline (BM25 retrieval, the confidence gate and the extractive engine) is
measured, what was measured, and what the numbers do and do not show. The Claude engine is not
part of this evaluation: it needs an API key and paid calls, neither of which was available.

## Files

| File | Purpose |
|---|---|
| `golden_set.json` | 63 held-out questions (51 answerable, 12 unanswerable). The reported results come from this file |
| `dev_set.json` | 71 questions (53 answerable, 18 unanswerable) used while building and tuning the pipeline |
| `results.json` | Output of the last golden-set run, including the outcome of every question |
| `run_eval.py` | Wrapper for `python -m sourcewise eval` |

## Running it

```powershell
.venv\Scripts\python -m sourcewise eval                             # golden set, writes eval/results.json
.venv\Scripts\python -m sourcewise eval --details                   # one line per question
.venv\Scripts\python -m sourcewise eval --set eval/dev_set.json     # development set
.venv\Scripts\python -m sourcewise eval --retriever bm25            # one retriever only
```

On macOS / Linux use `.venv/bin/python`. The script ingests `corpus/` into a temporary
database, so it does not touch `data/` and gives the same numbers on every run.

## Question format

```json
{
  "id": "n01",
  "question": "Do I get a break if I'm on a seven-hour shift, and is it paid?",
  "answerable": true,
  "expected": [{"document": "employee-handbook.md", "section": "Breaks"}],
  "answer_contains": ["30 minutes"]
}
```

- `expected` names the document and the section heading that contain the answer. A question
  may list more than one where the same fact appears in two documents.
- `answer_contains` lists short strings; an answer counts as correct if it contains at least
  one of them (case and spacing ignored).
- Unanswerable questions have `"answerable": false` and no `expected`. They are plausible
  questions for the fictional organisation that the corpus does not cover.

The questions were written the way a member of staff would ask them, not by copying the
wording of the documents. A test (`test_question_sets_are_well_formed_and_point_at_real_sections`)
checks that every expected section exists and really contains the expected fact, and that the
golden and development sets share no question.

## Metrics

For every question the script runs what the application runs in offline mode.

| Metric | Definition |
|---|---|
| Retrieval hit@1 / hit@3 (section) | Share of answerable questions for which a chunk from the expected document **and** section is ranked first / in the top three |
| Retrieval hit@1 / hit@3 (document) | The same, requiring only the expected document |
| MRR (section) | Mean of 1 / rank of the first chunk from the expected section (0 if it is not among the 6 retrieved) |
| Unanswerable questions declined | Unanswerable questions on which the assistant abstained |
| Answerable questions wrongly declined | Answerable questions on which it abstained |
| Decision accuracy | Share of all questions where the answer-or-abstain decision was right |
| Answered with the expected fact | Answerable questions whose extractive answer contains an `answer_contains` string |

## Protocol, including what went wrong

1. A first set of 22 short, keyword-style questions was written to develop the retriever and
   to pick an abstention threshold.
2. A golden set of 49 conversational questions was then written and run. The result was poor:
   24 of its 39 answerable questions were wrongly declined. The threshold chosen on
   keyword-style questions did not survive contact with the way people actually ask.
3. Because that run had now influenced the design, the 49 questions could no longer serve as a
   held-out set. They were moved into `dev_set.json`, and a **new** golden set of 63 questions
   was written and frozen before the abstention gate was redesigned.
4. The gate and the extractive engine were reworked using the development set only (a longer
   stop-word list for conversational filler, IDF-weighted coverage, a reduced weight for
   question words that occur nowhere in the corpus, and the thresholds in
   `sourcewise/config.py`).
5. With the pipeline frozen, the golden set was run **once**. Those are the numbers below.
   Nothing was changed in response to them.
6. The run is deterministic. Repeating it afterwards from a clean install, as a
   reproducibility check, gave the same outcome for every question.

## Results

Golden set, 63 questions, 11 documents / 168 chunks, `top_k` 6, `min_coverage` 0.55,
`min_evidence` 0.5, chunks of up to 700 characters with up to 150 characters of overlap.

| Metric | BM25 (SQLite FTS5) | BM25 (pure Python) |
|---|---|---|
| Retrieval hit@1, expected section | 49.0% (25/51) | 49.0% (25/51) |
| Retrieval hit@3, expected section | 68.6% (35/51) | 68.6% (35/51) |
| MRR, expected section | 0.585 | 0.585 |
| Retrieval hit@1, expected document | 68.6% (35/51) | 68.6% (35/51) |
| Retrieval hit@3, expected document | 94.1% (48/51) | 94.1% (48/51) |
| Unanswerable questions declined | 10/12 (83.3%) | 10/12 (83.3%) |
| Answerable questions wrongly declined | 14/51 (27.5%) | 14/51 (27.5%) |
| Decision accuracy | 74.6% (47/63) | 74.6% (47/63) |
| Answered with the expected fact | 23/51 (45.1%) | 23/51 (45.1%) |

The two retrievers agree because the pure-Python BM25 implements the same formula, field
weights and analyser as the FTS5 index; a test checks that their scores match.

For comparison, the development set, on which the thresholds were tuned, gives: section hit@1
66.0%, hit@3 84.9%, MRR 0.761; document hit@1 83.0%, hit@3 96.2%; 12/18 unanswerable declined;
14/53 answerable wrongly declined; decision accuracy 71.8%; 28/53 answered with the expected
fact. The gap between the two sets is the usual cost of tuning on one set and measuring on
another, and the reason the golden set is the one reported.

## Error analysis (golden set)

What happened to the 51 answerable questions:

| Outcome | Count |
|---|---:|
| Answered with the expected fact | 23 |
| Answered, but without the expected fact | 14 |
| Wrongly declined | 14 |

**Retrieval.** In 16 questions the expected section was not in the top three (in 11 of them it
was not among the six retrieved passages at all). Nearly all are vocabulary gaps between the
question and the document:

| The question says | The document says |
|---|---|
| "My dad has just died. How much time off am I entitled to?" | "compassionate leave following the death or serious illness of a close relative" |
| "When does IT switch off the login of someone who is leaving?" | "When someone leaves, their accounts are disabled by 18:00" |
| "How long do we keep the HR file of someone who has left the company?" | "Personnel files: 6 years after employment ends" |
| "A member has broken her ankle and can't come in for a while" | "a plan can be frozen for up to three months" with a note from a doctor |
| "What does it cost to add my husband to my plan?" | "Can family members be added?" |
| "Is there a deadline for making a complaint?" | "A complaint should be made within 12 months of the event" |

Stemming handles inflection ("cancelling" and "cancelled" share a stem) but not synonyms or
paraphrase. This is the expected ceiling of lexical retrieval and the reason the code has a
plug-in point for an embedding retriever. No embedding provider is integrated, so that
improvement is not measured here.

**Abstention.** Of the 14 wrongly declined questions, 7 had the right section among the top
three passages (5 ranked first, 2 ranked third) and were declined anyway. They are long,
narrative questions ("I got a parking ticket while visiting another clinic. Will the company
cover it?") whose informative words are only partly present in the passage, so coverage fell
under the 0.55 threshold. In the other 7 the right section had not been retrieved at all, and
declining was the right thing to do with the passages at hand.

The two unanswerable questions that were answered are near-misses on topic. "Is there a
student discount on physiotherapy sessions?" was answered with the staff discount, and "When
is the next all-staff meeting?" with a sentence about quarterly reporting to the board. A
lexical gate cannot tell that a passage has the right words but answers a different question.

**Answers.** When the expected section was ranked first (25 questions), the extractive answer
contained the expected fact 18 times; 5 were declined and 2 quoted a sentence from a different
passage. Of the 14 answers without the expected fact, 12 followed from retrieval ranking the
right section below first place or not at all. The extractive engine quotes the sentences that
best match the question's words; it does not understand the question.

## What these numbers do not show

- They describe one small synthetic corpus and 63 questions. They do not transfer to other
  documents, and with 12 unanswerable questions each one moves the abstention figure by 8
  points.
- The corpus and both question sets were written by the same author, who therefore knew what
  the documents contain. Real users ask about things nobody anticipated.
- `answer_contains` is a string check. It can pass an answer that quotes the fact alongside
  irrelevant text, and it cannot judge wording.
- Nothing here measures the Claude engine. An LLM reading the same top-6 passages can answer
  from a passage ranked second or third and can decline off-topic passages, so its answer
  quality should differ from the extractive engine's. That has been seen on a handful of
  questions sent to the real API (see "Verification status" in the main README), not measured
  on these sets. With Claude as the engine the gate is also looser than the one evaluated
  here: of the 28 answerable questions in the two sets that the strict gate declines, 27 would
  reach the model.
