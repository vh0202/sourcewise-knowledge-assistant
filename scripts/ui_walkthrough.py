"""Walk through the main screens in a real browser and check what appears.

    python scripts/ui_walkthrough.py

The flow is the one in docs/demo-video-script.md. The script seeds a temporary database,
starts the server on port 8102 in offline mode, and drives the installed Google Chrome through
Playwright: sign-in, a cited answer with its hover preview and source panel, a PDF citation
with its page number, an abstention, the command palette, deleting and uploading a document,
the chunk inspector, insights, the theme switch, and what a member may not see. It stops at
the first step that fails and exits with status 1.

Requirements: the dev dependencies (``pip install -r requirements-dev.txt``), Google Chrome,
and a built frontend (``frontend/dist`` is committed). Nothing in ``data/`` is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from screenshots import ADMIN, ROOT, VIEWPORT, ask, seeded_server  # noqa: E402

from sourcewise import HONESTY_LABEL  # noqa: E402
from sourcewise.seed import DEMO_USERS  # noqa: E402

MEMBER = next(user for user in DEMO_USERS if user["role"] == "member")
UPLOAD = ROOT / "corpus" / "people" / "travel-and-expense-policy.md"


def done(label: str) -> None:
    print(f"  [ok] {label}")


def sign_in(page: Page, base_url: str, user: dict[str, str]) -> None:
    page.goto(f"{base_url}/login")
    page.get_by_role("button", name=user["email"]).click()
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.wait_for_url("**/chat")


def walk(base_url: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_context(viewport=VIEWPORT, locale="en-GB").new_page()
        problems: list[str] = []
        page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: problems.append(str(error)))

        # 1. Sign in with a demo account; the honesty label is in the footer.
        page.goto(f"{base_url}/login")
        expect(page.get_by_text(HONESTY_LABEL)).to_be_visible()
        sign_in(page, base_url, ADMIN)
        expect(page.get_by_role("heading", name="what would you like to know")).to_be_visible()
        expect(page.get_by_text(HONESTY_LABEL)).to_be_visible()
        expect(page.get_by_text("Extractive (offline) mode").first).to_be_visible()
        done("admin signs in; footer label and engine indicator are shown")

        # 2. A starter question gives a cited answer; the citation previews its sentence on hover
        #    and opens the highlighted passage on click.
        page.get_by_role("button", name="How many days of annual leave do full-time employees get?").click()
        page.locator("[aria-label='Helpful']").first.wait_for()
        page.locator(".citation-chip").first.hover()
        expect(page.get_by_role("tooltip")).to_contain_text("25 days of paid annual leave")
        page.locator(".citation-chip").first.click()
        panel = page.get_by_role("complementary", name="Source")
        expect(panel).to_contain_text("Employee Handbook")
        expect(panel).to_contain_text("Annual leave")
        expect(panel.locator("mark").first).to_contain_text("25 days of paid annual leave")
        done("starter question is answered with a citation; hover previews it and the source panel highlights the cited passage")

        # 3. A citation into the PDF shows its page number.
        ask(page, "How much cash can the front desk accept in one transaction?")
        page.locator(".citation-chip").last.click()
        expect(panel).to_contain_text("Front Desk Standard Operating Procedure")
        expect(panel).to_contain_text("Page 2")
        expect(panel.locator("mark").first).to_contain_text("£200")
        done("PDF citation shows the document, section and page number")

        # 4. A question the documents do not cover is declined.
        ask(page, "Is there staff parking at the Rookfield clinic?")
        expect(page.get_by_text("Not found in the knowledge base", exact=True)).to_be_visible()
        done("uncovered question is declined")

        # 5. The command palette (Ctrl+K) finds a document by name and opens its chunk inspector.
        page.keyboard.press("Control+k")
        palette = page.get_by_role("dialog", name="Command palette")
        palette.get_by_role("combobox").fill("records")
        expect(palette.get_by_role("option", name="Records Retention Schedule")).to_be_visible()
        palette.get_by_role("option", name="Records Retention Schedule").click()
        expect(page.get_by_role("heading", name="Records Retention Schedule")).to_be_visible()
        expect(palette).to_have_count(0)
        done("command palette finds a document and opens it")

        # 6. Knowledge base: delete a document, then upload it again through the pipeline.
        page.get_by_role("link", name="Knowledge base", exact=True).first.click()
        page.get_by_role("table").wait_for()
        title = "Travel and Expense Policy"
        page.get_by_role("button", name=f"Delete {title}", exact=True).click()
        page.get_by_role("button", name="Delete document", exact=True).click()
        expect(page.get_by_role("link", name=title, exact=True)).to_have_count(0)
        done("admin deletes a document")
        page.get_by_label("Collection to upload into").select_option(label="People & Workplace")
        page.get_by_label("Choose documents to upload").set_input_files(str(UPLOAD))
        row = page.get_by_role("row").filter(has=page.get_by_role("link", name=title, exact=True))
        expect(row).to_contain_text("Ready")
        done("uploaded document runs through the pipeline and becomes Ready")

        # 7. Chunk inspector: pipeline stages, the outline, and overlap marked between neighbouring chunks.
        page.get_by_role("link", name="Employee Handbook", exact=True).click()
        expect(page.get_by_role("heading", name="Ingestion pipeline")).to_be_visible()
        for stage in ("Parse", "Normalise", "Chunk", "Index"):
            expect(page.get_by_text(stage, exact=True).first).to_be_visible()
        expect(page.get_by_role("navigation", name="Document outline").get_by_role("button", name="Annual leave")).to_be_visible()
        expect(page.locator(".overlap-text").first).to_be_attached()
        expect(page.get_by_text("124 overlap")).to_have_count(1)
        done("chunk inspector shows the pipeline stages, the outline and the overlapping text")

        # 8. Insights lists the declined question as a knowledge gap.
        page.get_by_role("link", name="Insights", exact=True).click()
        expect(page.get_by_role("heading", name="Knowledge gaps")).to_be_visible()
        expect(page.get_by_role("heading", name="Most-cited documents")).to_be_visible()
        expect(page.get_by_text("Is there staff parking at the Rookfield clinic?")).to_be_visible()
        done("insights shows most-cited documents and the declined question as a gap")

        # 9. The theme switch in the header changes the theme, and the choice survives a reload.
        html = page.locator("html")
        expect(html).to_have_attribute("data-theme", "light")
        page.get_by_role("button", name="Switch to dark theme").click()
        expect(html).to_have_attribute("data-theme", "dark")
        page.reload()
        expect(html).to_have_attribute("data-theme", "dark")
        # The stored choice is applied before the application script runs (here that script is
        # blocked altogether), so a reload never shows a flash of the other theme.
        bare = page.context.new_page()
        bare.route("**/assets/*.js", lambda route: route.abort())
        bare.goto(f"{base_url}/login")
        expect(bare.locator("html")).to_have_attribute("data-theme", "dark")
        red, green, blue = bare.evaluate("getComputedStyle(document.documentElement).backgroundColor.match(/\\d+/g).slice(0, 3).map(Number)")
        assert red + green + blue < 120, f"the page background is not dark before the app loads: rgb({red}, {green}, {blue})"
        bare.close()
        page.get_by_role("button", name="Switch to light theme").click()
        expect(html).to_have_attribute("data-theme", "light")
        done("theme switch changes the theme; the choice is remembered and applied before the app loads")

        # 10. A member sees only the chat, and not the admin's conversations.
        page.get_by_role("button", name="Sign out").click()
        page.wait_for_url("**/login")
        sign_in(page, base_url, MEMBER)
        expect(page.get_by_role("link", name="Chat", exact=True)).to_be_visible()
        expect(page.get_by_role("link", name="Knowledge base")).to_have_count(0)
        expect(page.get_by_role("link", name="Insights")).to_have_count(0)
        expect(page.get_by_text("How much cash can the front desk accept")).to_have_count(0)
        for path in ("/knowledge", "/insights"):
            page.goto(f"{base_url}{path}")
            expect(page.get_by_role("heading", name="Administrators only")).to_be_visible()
        done("member has no admin navigation and is refused the admin pages")

        browser.close()
        if problems:
            raise AssertionError(f"The browser console reported errors: {problems}")
        done("no errors in the browser console")


def main() -> int:
    try:
        with seeded_server(prefix="sourcewise-walk-") as base_url:
            print("Walking through the application ...")
            walk(base_url)
    except (AssertionError, PlaywrightError, RuntimeError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
