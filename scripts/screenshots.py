"""Regenerate docs/screenshots/*.png against a freshly seeded copy of the app.

    python scripts/screenshots.py

The script seeds a temporary database, starts the server on port 8102 with the offline engine
(so no API key is used even if one is configured), drives the installed Google Chrome through
Playwright at 1440x900, and stops the server again. Nothing in ``data/`` is touched.

It writes eleven images: the seven main screens in the light theme, the cited answer, the
knowledge base and the insights page again in the dark theme, and the command palette. The
browser is told that the visitor prefers reduced motion, so nothing is caught mid-animation.

Requirements: the dev dependencies (``pip install -r requirements-dev.txt``), Google Chrome,
and a built frontend (``frontend/dist`` is committed). Use ``--base-url`` to capture an
already-running instance instead; it must have been seeded with ``python -m sourcewise seed``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sourcewise.seed import DEMO_USERS  # noqa: E402

OUTPUT = ROOT / "docs" / "screenshots"
PORT = 8102
VIEWPORT = {"width": 1440, "height": 900}
ADMIN = next(user for user in DEMO_USERS if user["role"] == "admin")

# A two-part question: the answer cites two sentences, each highlighted inside a longer passage.
CITED_QUESTION = "How much annual leave do full-time staff get, and can unused leave be carried over?"
PDF_QUESTION = "How much cash can the front desk accept in one transaction?"
UNCOVERED_QUESTION = "Is there staff parking at the Rookfield clinic?"


def wait_until_healthy(base_url: str, timeout: float = 40.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    raise RuntimeError(f"The server at {base_url} did not become healthy within {timeout:.0f} s")


def port_in_use(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=1):
            return True
    except (urllib.error.URLError, OSError):
        return False


def stop(server: subprocess.Popen) -> None:
    """Stop the server and everything it started.

    In a Windows virtual environment ``python.exe`` is a launcher that runs the real
    interpreter as a child process, so terminating the launcher alone would leave the
    server running; ``taskkill /T`` ends the whole process tree.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=10)
    time.sleep(0.5)  # give the operating system a moment to release the database files


# Resolves when every animation or transition that is going to end has ended.
ANIMATIONS_FINISHED = """
() => Promise.all(
  document.getAnimations()
    .filter((animation) => animation.effect?.getComputedTiming().endTime !== Infinity)
    .map((animation) => animation.finished.catch(() => undefined)),
)
"""


def shoot(page: Page, name: str) -> None:
    page.wait_for_timeout(350)  # let scrolling settle and data arrive
    page.evaluate(ANIMATIONS_FINISHED)
    path = OUTPUT / name
    page.screenshot(path=str(path), full_page=False)
    print(f"  wrote {path.relative_to(ROOT)}")


def ask(page: Page, question: str) -> None:
    """Type a question, send it, and wait until the answer has finished streaming."""
    answers = page.locator("[aria-label='Helpful']")
    before = answers.count()
    page.get_by_label("Your question").fill(question)
    page.get_by_label("Send question").click()
    page.wait_for_function("count => document.querySelectorAll(\"[aria-label='Helpful']\").length > count", arg=before)


def new_page(browser: Browser, theme: str) -> Page:
    """A 1440x900 page whose visitor prefers the given colour scheme (the app follows it) and reduced motion."""
    context = browser.new_context(
        viewport=VIEWPORT, device_scale_factor=1, locale="en-GB", color_scheme=theme, reduced_motion="reduce"
    )
    return context.new_page()


def open_source(page: Page, chip: int) -> None:
    """Click the nth citation chip on the page and wait for the source panel."""
    page.locator(".citation-chip").nth(chip).click()
    page.get_by_role("complementary", name="Source").wait_for()
    page.mouse.move(700, 620)  # away from the chip, so that its hover preview does not cover the answer


def hover_chart_day(page: Page) -> None:
    """Show the tooltip of one day of the insights chart (the tenth of fourteen)."""
    page.get_by_role("heading", name="Answered and abstained, per day").wait_for()
    page.locator("[data-day]").nth(9).hover()
    page.get_by_role("tooltip").wait_for()


def capture(base_url: str) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = new_page(browser, "light")

        # 1. Sign-in page, with a demo account chosen.
        page.goto(f"{base_url}/login")
        page.get_by_role("button", name=ADMIN["email"]).click()
        shoot(page, "01-login.png")
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url("**/chat")

        # 2. A cited answer with the source panel open on the passage behind the second citation.
        ask(page, CITED_QUESTION)
        open_source(page, 1)
        shoot(page, "02-chat-cited-answer.png")
        cited_conversation = page.url

        # 3. A citation into a PDF (with its page number), then a question the documents do not cover.
        page.get_by_role("button", name="New chat").click()
        page.get_by_role("heading", name="what would you like to know").wait_for()
        ask(page, PDF_QUESTION)
        open_source(page, 0)
        ask(page, UNCOVERED_QUESTION)
        shoot(page, "03-chat-pdf-source-and-abstention.png")

        # 11. The command palette (Ctrl+K) over the conversation: pages, conversations and documents.
        page.keyboard.press("Control+k")
        page.get_by_role("dialog", name="Command palette").wait_for()
        page.get_by_role("option", name="Calderwick Care Plan: Product FAQ").wait_for()
        shoot(page, "11-command-palette.png")
        page.keyboard.press("Escape")

        # 4. Knowledge-base administration.
        page.get_by_role("link", name="Knowledge base", exact=True).click()
        page.get_by_role("heading", name="Knowledge base").wait_for()
        page.get_by_role("table").wait_for()
        shoot(page, "04-knowledge-base.png")

        # 5. Chunk inspector for the multi-page PDF: pipeline stages and the document map.
        page.get_by_role("link", name="Front Desk Standard Operating Procedure", exact=True).click()
        page.get_by_role("heading", name="Ingestion pipeline").wait_for()
        shoot(page, "05-chunk-inspector-pipeline.png")

        # 6. Chunks of a document with a long section, against its outline; consecutive chunks overlap.
        page.get_by_role("link", name="Knowledge base", exact=True).first.click()
        page.get_by_role("table").wait_for()
        page.get_by_role("link", name="Employee Handbook", exact=True).click()
        page.get_by_role("heading", name="Ingestion pipeline").wait_for()
        # Put the chunk before the first overlapping one at the top, so that both are in view.
        page.locator(".overlap-text").first.evaluate("element => element.closest('li').previousElementSibling.scrollIntoView({ block: 'start' })")
        shoot(page, "06-chunk-inspector-overlap.png")

        # 7. Insights, with one day's tooltip showing.
        page.get_by_role("link", name="Insights", exact=True).click()
        hover_chart_day(page)
        shoot(page, "07-insights.png")

        # 8-10. The dark theme: the same conversation, knowledge base and insights. Nothing more is
        # asked, so these show exactly the data of the light screenshots.
        dark = new_page(browser, "dark")
        dark.goto(f"{base_url}/login")
        dark.get_by_role("button", name=ADMIN["email"]).click()
        dark.get_by_role("button", name="Sign in", exact=True).click()
        dark.wait_for_url("**/chat")

        dark.goto(cited_conversation)
        dark.locator("[aria-label='Helpful']").first.wait_for()
        open_source(dark, 1)
        shoot(dark, "08-chat-cited-answer-dark.png")

        dark.get_by_role("link", name="Knowledge base", exact=True).click()
        dark.get_by_role("table").wait_for()
        shoot(dark, "09-knowledge-base-dark.png")

        dark.get_by_role("link", name="Insights", exact=True).click()
        hover_chart_day(dark)
        shoot(dark, "10-insights-dark.png")

        browser.close()


@contextmanager
def seeded_server(prefix: str = "sourcewise-shots-") -> Iterator[str]:
    """Seed a temporary database, serve it on port 8102 in offline mode, and stop the server afterwards."""
    base_url = f"http://127.0.0.1:{PORT}"
    if port_in_use(base_url):
        raise RuntimeError(f"Port {PORT} is already in use. Stop the running server first.")

    # ignore_cleanup_errors: on Windows the database files can stay locked for a moment after
    # the server process has gone; a leftover temporary folder is harmless.
    with tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True) as workdir:
        env = {
            **os.environ,
            "SOURCEWISE_DATA_DIR": workdir,
            "SOURCEWISE_ENGINE": "offline",
            "SOURCEWISE_STREAM_DELAY_MS": "0",
            "SOURCEWISE_PORT": str(PORT),
            "PYTHONIOENCODING": "utf-8",
        }
        print("Seeding a temporary database ...")
        subprocess.run([sys.executable, "-m", "sourcewise", "seed"], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
        print(f"Starting the server on port {PORT} ...")
        server = subprocess.Popen(
            [sys.executable, "-m", "sourcewise", "serve"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            wait_until_healthy(base_url)
            yield base_url
        finally:
            stop(server)
            print("Server stopped.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", help="capture an already-running, seeded instance instead of starting one")
    args = parser.parse_args()

    if args.base_url:
        wait_until_healthy(args.base_url.rstrip("/"), timeout=5)
        capture(args.base_url.rstrip("/"))
        return 0

    try:
        with seeded_server() as base_url:
            capture(base_url)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
