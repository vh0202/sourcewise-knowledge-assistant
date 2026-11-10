# Demo video script (about 90 seconds)

A screen recording of the seeded application in extractive (offline) mode, with voice-over.
Sample project — self-initiated portfolio demo, not client work. All data is synthetic.

## Before recording

1. Reset the demo data and start the app. The first line keeps the built-in offline engine
   even when an API key is configured on the machine:

   ```powershell
   $env:SOURCEWISE_ENGINE = "offline"
   .venv\Scripts\python -m sourcewise seed --reset
   .venv\Scripts\python -m sourcewise serve
   ```

2. Open <http://127.0.0.1:8102> in a browser window of 1440x900 (or 1920x1080 at 125% zoom).
   Hide the bookmarks bar. Start in the light theme: the moon or sun button at the top right
   of every page switches it, and shot 8 switches to the dark theme on camera.
3. Sign in as `admin@example.com`, open **Knowledge base**, and delete **Travel and Expense
   Policy** (bin icon at the end of its row, then **Delete document**). It is uploaded again on
   camera in shot 5. Sign out with the arrow button beside the name at the bottom of the
   sidebar, so the recording starts on the sign-in page.
4. Have `corpus/people/travel-and-expense-policy.md` ready in a file-manager window for the
   upload.
5. Leave animations switched on in the operating system. The interface honours the "reduce
   motion" setting, and with it the streaming, the sliding panel and the highlight pulse of
   shot 2 would not be shown.
6. Record at 30 fps. Move the pointer slowly and pause for about a second after each click.

## Shot list

| # | Time | On screen: exact actions | Narration |
|---|---|---|---|
| 1 | 0:00 - 0:10 | Sign-in page, with the product preview on the left. Under **Demo accounts** click `admin@example.com` (the form fills in and the row is ticked). Click **Sign in**. | "This is SourceWise, a sample knowledge assistant. It answers staff questions from a company's own documents, and shows the source of every statement." |
| 2 | 0:10 - 0:25 | Chat opens on "Hello Dana, what would you like to know?". Under **Try asking**, click **How many days of annual leave do full-time employees get?** The answer streams in word by word. Rest the pointer on the gold citation chip **1** until the preview of the cited sentence appears, then click the chip. The **Source** panel slides in on the right and the highlighted text pulses once. | "I'll ask about annual leave. The answer streams in with a numbered citation. Hovering it previews the cited sentence, and one click opens the passage, highlighted in its place in the document." |
| 3 | 0:25 - 0:35 | Click the question box, type `How much cash can the front desk accept in one transaction?` and press Enter. When the answer is complete, click its citation chip **1**. The Source panel now shows **Front Desk Standard Operating Procedure**, the section trail **5. Taking payments › 5.1 Payment methods** and **Page 2**. | "Sources can be PDFs. This answer comes from page two of the front-desk procedure." |
| 4 | 0:35 - 0:43 | Type `Is there staff parking at the Rookfield clinic?` and press Enter. The reply is a dashed card titled **Not found in the knowledge base**. | "And when the documents don't cover a question, it says so instead of guessing." |
| 5 | 0:43 - 0:57 | Press **Ctrl+K**, type `know` and press Enter: the command palette opens **Knowledge base**. In the upload box, set **Into** to **People & Workplace**, click **Browse files** and choose `travel-and-expense-policy.md`. A row appears under the box with a progress bar, then four pipeline stages that turn green; the document joins the table with the status **Ready**. | "A command palette jumps to any page or document. Administrators manage the knowledge base, and every upload runs through a visible pipeline: parse, normalise, chunk, index." |
| 6 | 0:57 - 1:07 | In the table click **Employee Handbook**. The chunk inspector opens: pause on **Ingestion pipeline**, then click **Annual leave** in the **Outline** on the left. Chunk **7** starts with hatched text, carries the tag **124 overlap**, and is tied to chunk 6 above it. | "The chunk inspector shows how a document was split. Chunks follow its outline, and text shared with the previous chunk is marked." |
| 7 | 1:07 - 1:18 | Click **Insights** in the sidebar. Hover a column in **Answered and abstained, per day** to show its tooltip, then scroll to **Most-cited documents** and **Knowledge gaps**. | "Insights shows how many questions were answered or declined, which documents are cited most, and the questions nobody could answer. Those are the gaps to fill next." |
| 8 | 1:18 - 1:30 | Scroll back up. Click the moon button at the top right: the interface switches to the dark theme. Move the pointer to the status chip beside it ("Extractive (offline) mode"), then to the footer line. | "There is a dark theme too. The chip in the header always shows which engine is answering: here the offline one, or Claude with an API key. It's a sample project, and all the data is synthetic." |

## Narration in one piece (about 195 words)

This is SourceWise, a sample knowledge assistant. It answers staff questions from a company's
own documents, and shows the source of every statement.

I'll ask about annual leave. The answer streams in with a numbered citation. Hovering it
previews the cited sentence, and one click opens the passage, highlighted in its place in the
document.

Sources can be PDFs. This answer comes from page two of the front-desk procedure.

And when the documents don't cover a question, it says so instead of guessing.

A command palette jumps to any page or document. Administrators manage the knowledge base,
and every upload runs through a visible pipeline: parse, normalise, chunk, index.

The chunk inspector shows how a document was split. Chunks follow its outline, and text
shared with the previous chunk is marked.

Insights shows how many questions were answered or declined, which documents are cited most,
and the questions nobody could answer. Those are the gaps to fill next.

There is a dark theme too. The chip in the header always shows which engine is answering:
here the offline one, or Claude with an API key. It's a sample project, and all the data is
synthetic.

## Notes for the recording

- The script records the offline engine. The live API path was verified with a real key on
  2026-11-11 (see the README), so a Claude answer may be shown instead; if it is, say that the
  call is billed to the key's owner and re-check the answer against its source before recording.
- The Insights numbers depend on the seeded demo activity plus whatever was asked during the
  recording, so they will differ slightly from the screenshots in `docs/screenshots`.
- Keep the footer line visible in at least the first and last shots.
- From 1280 pixels wide the source panel is docked beside the conversation and its left edge
  can be dragged to resize it; the width is remembered, so reset it (double-click the edge)
  before recording if it was changed.
