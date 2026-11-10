# Case study: SourceWise, an AI knowledge assistant with cited answers

*Sample project — self-initiated portfolio demo, not client work. All data is synthetic.*

## The problem

Teams keep policies and procedures in handbooks, PDFs and intranet pages that nobody can
search well. A chatbot over those documents is only useful if people can check where each
answer came from, and if it admits when the documents have no answer.

## The solution

SourceWise is a self-initiated sample project that shows how I build that kind of assistant.
Administrators upload Markdown, text, HTML or PDF files; a pipeline parses them, splits them
along their headings and indexes them for BM25 search. Staff ask questions in a chat. Every
answer carries numbered citations, and one click opens the source passage with the cited text
highlighted, next to its document, section and PDF page. When the evidence is too thin, the
assistant replies "Not found in the knowledge base".

## Highlights

- Two interchangeable answer engines: Claude through the official Anthropic SDK, with its
  citations mapped to exact character ranges, and a deterministic extractive engine that
  needs no API key.
- A chunk inspector, and insights on answer rates, most-cited documents and unanswered
  questions.
- Admin and member roles enforced on the server.
- 381 automated tests, plus an evaluation on 63 held-out questions phrased the way staff ask.
  Offline, the right document was in the top three for 94.1% of answerable questions and the
  right section ranked first for 49.0%; 10 of 12 uncovered questions were declined.
- The Claude path was run against the real API on eleven questions: eight answered with
  exact-span citations, three uncovered ones declined by the model. Its accuracy has not been
  measured.

## Stack

Python 3.12, FastAPI, SQLAlchemy, SQLite FTS5, pypdf, Anthropic SDK; React, TypeScript, Vite,
Tailwind CSS; pytest, Playwright.
