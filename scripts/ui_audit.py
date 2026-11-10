"""Audit the built interface in a real browser: overflow, layout shift and colour contrast.

    python scripts/ui_audit.py                 # both themes at 1440, 1024 and 390 px wide
    python scripts/ui_audit.py --themes dark --widths 390

The script seeds a temporary database, starts the server on port 8102 in offline mode and drives
the installed Google Chrome through Playwright. In the light and the dark theme, at each width,
it walks through the screens (sign-in, chat, a cited answer with its source, an abstention, the
command palette, the knowledge base, a dialog, the chunk inspector, insights, the page a member
is refused) and checks three things:

1. **No horizontal overflow.** The document is never wider than the viewport, and no visible
   element sticks out of it sideways.
2. **No layout shift while a page loads.** Each page is loaded from cold and the browser's
   Layout Instability API must report a cumulative layout shift of (practically) zero.
3. **WCAG AA contrast.** Every piece of visible text is measured against the background that is
   actually painted behind it, taken from a screenshot, so translucent surfaces, gradients and
   the highlighted passage are covered. Normal text needs 4.5:1; large text (24px, or 18.66px
   bold) needs 3:1. Disabled controls and purely decorative punctuation (the dot between two
   facts, the arrow in a breadcrumb) are exempt, as in WCAG.

It exits with status 1 if any check fails. Nothing in ``data/`` is touched.

Requirements: the dev dependencies (``pip install -r requirements-dev.txt``), Google Chrome,
and a built frontend (``frontend/dist`` is committed).
"""

from __future__ import annotations

import argparse
import io
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from screenshots import ADMIN, CITED_QUESTION, UNCOVERED_QUESTION, ask, seeded_server  # noqa: E402

from sourcewise.seed import DEMO_USERS  # noqa: E402

MEMBER = next(user for user in DEMO_USERS if user["role"] == "member")
HEIGHTS = {1440: 900, 1024: 768, 390: 844}
MAX_LAYOUT_SHIFT = 0.005  # the API reports fractions of the viewport; this is "nothing moved"

# Records layout shifts from the first frame of every document, and which elements moved.
LAYOUT_SHIFT_OBSERVER = """
window.__layoutShift = 0;
window.__layoutShiftNodes = [];
new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) {
    if (entry.hadRecentInput) continue;
    window.__layoutShift += entry.value;
    for (const source of entry.sources || []) {
      const node = source.node;
      if (!node) continue;
      const element = node.nodeType === 1 ? node : node.parentElement;
      if (element) window.__layoutShiftNodes.push(element.tagName.toLowerCase() + "." + String(element.className).split(" ")[0]);
    }
  }
}).observe({ type: "layout-shift", buffered: true });
"""

# Elements that stick out of the viewport sideways and are not clipped by a scrolling ancestor.
OVERFLOW_SCAN = """
() => {
  const width = document.documentElement.clientWidth;
  const problems = [];
  if (document.documentElement.scrollWidth > width + 1) problems.push(`document is ${document.documentElement.scrollWidth}px wide`);
  const clipped = (element) => {
    for (let node = element.parentElement; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.overflowX !== "visible" || style.position === "fixed") return true;
    }
    return false;
  };
  for (const element of document.body.querySelectorAll("*")) {
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    if (rect.right <= width + 1 && rect.left >= -1) continue;
    const style = getComputedStyle(element);
    if (style.visibility === "hidden" || style.position === "fixed" || clipped(element)) continue;
    const name = element.tagName.toLowerCase() + (element.className && typeof element.className === "string" ? "." + element.className.split(" ")[0] : "");
    problems.push(`${name} spans ${Math.round(rect.left)}..${Math.round(rect.right)}px`);
    if (problems.length > 5) break;
  }
  return problems;
}
"""

# Every visible run of text with its box, colour and size. Hit-testing decides what is on top,
# so pointer-events is forced on for the duration (tooltips are click-through otherwise).
TEXT_SCAN = """
() => {
  const style = document.createElement("style");
  style.textContent = "* { pointer-events: auto !important; }";
  document.head.append(style);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  const cache = new Map();
  const rgba = (color) => {
    if (!cache.has(color)) {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = color;
      context.fillRect(0, 0, 1, 1);
      const data = context.getImageData(0, 0, 1, 1).data;
      cache.set(color, [data[0], data[1], data[2], data[3] / 255]);
    }
    return cache.get(color);
  };
  const items = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.nodeValue.trim();
    const element = node.parentElement;
    if (!/[\\p{L}\\p{N}]/u.test(text)) continue; // nothing to read: white space or a decorative separator
    if (!element || element.closest("script, style, :disabled, [aria-disabled='true']")) continue;
    const computed = getComputedStyle(element);
    if (computed.visibility === "hidden") continue;
    let opacity = 1;
    for (let up = element; up; up = up.parentElement) opacity *= Number(getComputedStyle(up).opacity);
    if (opacity < 0.05) continue;
    range.selectNodeContents(node);
    for (const rect of Array.from(range.getClientRects()).slice(0, 4)) {
      if (rect.width < 3 || rect.height < 6) continue; // visually hidden text
      if (rect.bottom < 0 || rect.top > innerHeight || rect.right < 0 || rect.left > innerWidth) continue;
      const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      if (!top || !(top === element || element.contains(top))) continue; // covered by something else, or clipped
      // SVG text is painted with `fill`, HTML text with `color`.
      const [red, green, blue, alpha] = rgba(element instanceof SVGElement ? computed.fill : computed.color);
      items.push({
        x: rect.left, y: rect.top, width: rect.width, height: rect.height,
        color: [red, green, blue, alpha * opacity],
        size: parseFloat(computed.fontSize), weight: Number(computed.fontWeight) || 400,
        text: text.slice(0, 60),
      });
    }
  }
  style.remove();
  return items;
}
"""


@dataclass
class Report:
    theme: str
    width: int
    screens: int = 0
    worst_shift: float = 0.0
    worst_shift_page: str = ""
    texts: int = 0
    lowest_ratio: float = 99.0
    failures: list[str] = field(default_factory=list)


def luminance(color: tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def background_of(image: Image.Image, box: tuple[int, int, int, int], text_colour: tuple[float, float, float]) -> tuple[float, float, float] | None:
    """The colour painted behind a run of text: the dominant colour in its box once the glyphs are set aside.

    Pixels close to the text's own colour are ignored first (on a gradient the glyphs, being one
    flat colour, would otherwise win the vote). If hardly anything is left, text and background
    really are alike, and the plain dominant colour is used.
    """
    left, top, right, bottom = box
    left, top = max(left, 0), max(top, 0)
    right, bottom = min(right, image.width), min(bottom, image.height)
    if right - left < 2 or bottom - top < 2:
        return None
    raw = image.crop((left, top, right, bottom)).tobytes()  # RGB triples
    pixels = [(raw[index], raw[index + 1], raw[index + 2]) for index in range(0, len(raw), 3)]
    behind =[pixel for pixel in pixels if sum((channel - wanted) ** 2 for channel, wanted in zip(pixel, text_colour, strict=True)) > 48**2]
    if len(behind) < 0.15 * len(pixels):
        behind = pixels
    bins = Counter((red >> 3, green >> 3, blue >> 3) for red, green, blue in behind)
    dominant = bins.most_common(1)[0][0]
    members = [pixel for pixel in behind if (pixel[0] >> 3, pixel[1] >> 3, pixel[2] >> 3) == dominant]
    return tuple(sum(pixel[index] for pixel in members) / len(members) for index in range(3))  # type: ignore[return-value]


def check_contrast(page: Page, label: str, report: Report) -> None:
    page.wait_for_timeout(250)  # let fades finish, so that pixels and computed colours agree
    items = page.evaluate(TEXT_SCAN)
    image = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
    for item in items:
        box = (int(item["x"]), int(item["y"]), int(item["x"] + item["width"]) + 1, int(item["y"] + item["height"]) + 1)
        red, green, blue, alpha = item["color"]
        background = background_of(image, box, (red, green, blue))
        if background is None:
            continue
        text_colour = tuple(channel * alpha + behind * (1 - alpha) for channel, behind in zip((red, green, blue), background, strict=True))
        ratio = contrast_ratio(text_colour, background)  # type: ignore[arg-type]
        large = item["size"] >= 24 or (item["size"] >= 18.66 and item["weight"] >= 700)
        report.texts += 1
        report.lowest_ratio = min(report.lowest_ratio, ratio)
        if ratio < (3.0 if large else 4.5) - 0.005:
            report.failures.append(f"{label}: contrast {ratio:.2f}:1 for {item['text']!r} ({item['size']:.0f}px)")


def check_screen(page: Page, label: str, report: Report, *, contrast: bool) -> None:
    report.screens += 1
    for problem in page.evaluate(OVERFLOW_SCAN):
        report.failures.append(f"{label}: horizontal overflow, {problem}")
    if contrast:
        check_contrast(page, label, report)


def check_load(page: Page, label: str, report: Report) -> None:
    """After a cold page load: how much did the layout move?"""
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(700)
    shift = page.evaluate("window.__layoutShift ?? 0")
    if shift > report.worst_shift:
        moved = ", ".join(dict.fromkeys(page.evaluate("window.__layoutShiftNodes ?? []")))
        report.worst_shift, report.worst_shift_page = shift, f"{label}: {moved}"
    if shift > MAX_LAYOUT_SHIFT:
        report.failures.append(f"{label}: layout shift of {shift:.4f} while loading ({report.worst_shift_page})")


def scroll_page(page: Page, top: int) -> None:
    page.evaluate("top => document.querySelector('main .overflow-y-auto')?.scrollTo(0, top)", top)
    page.wait_for_timeout(150)


def sign_in(page: Page, base_url: str, user: dict[str, str]) -> None:
    page.goto(f"{base_url}/login")
    page.get_by_role("button", name=user["email"]).click()
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.wait_for_url("**/chat")


def audit(base_url: str, theme: str, width: int) -> Report:
    report = Report(theme, width)
    docked = width >= 1280  # the source panel is docked beside the conversation from this width
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": width, "height": HEIGHTS.get(width, 900)},
            device_scale_factor=1,
            locale="en-GB",
            color_scheme=theme,  # type: ignore[arg-type]
            reduced_motion="reduce",
        )
        context.add_init_script(LAYOUT_SHIFT_OBSERVER)
        page = context.new_page()

        def screen(label: str) -> None:
            check_screen(page, label, report, contrast=True)

        # Sign-in, including the error message.
        page.goto(f"{base_url}/login")
        page.get_by_role("button", name=ADMIN["email"]).wait_for()
        check_load(page, "sign-in", report)
        screen("sign-in")
        page.get_by_label("Email").fill(ADMIN["email"])
        page.get_by_label("Password", exact=True).fill("not-the-password")
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.get_by_role("alert").wait_for()
        screen("sign-in, wrong password")
        sign_in(page, base_url, ADMIN)

        # Chat: empty, a cited answer, the citation preview, the source, an abstention.
        page.goto(f"{base_url}/chat")
        page.get_by_role("heading", name="what would you like to know").wait_for()
        check_load(page, "chat", report)
        screen("chat, empty")
        ask(page, CITED_QUESTION)
        screen("chat, cited answer")
        page.locator(".citation-chip").first.hover()
        page.get_by_role("tooltip").wait_for()
        screen("chat, citation preview")
        page.mouse.move(2, 2)
        page.locator(".citation-chip").nth(1).click()
        page.get_by_role("complementary", name="Source").wait_for()
        screen("chat, source panel")
        if not docked:
            page.get_by_role("button", name="Close source panel").click()
            page.get_by_role("complementary", name="Source").wait_for(state="detached")
        ask(page, UNCOVERED_QUESTION)
        screen("chat, not found")
        page.locator("[aria-label='Copy answer']").first.click()
        page.get_by_text("Answer copied").or_(page.get_by_text("Could not copy the answer")).wait_for()
        screen("chat, toast")
        conversation_url = page.url
        page.goto(conversation_url)
        page.locator("[aria-label='Helpful']").first.wait_for()
        check_load(page, "conversation", report)

        # Navigation drawer (small screens), command palette, conversation menu and dialog.
        if width < 1024:
            page.get_by_role("button", name="Open navigation").click()
            page.get_by_role("dialog", name="Navigation").wait_for()
            screen("navigation drawer")
            page.keyboard.press("Escape")
            page.get_by_role("dialog", name="Navigation").wait_for(state="detached")
        page.keyboard.press("Control+k")
        page.get_by_role("dialog", name="Command palette").wait_for()
        screen("command palette")
        page.keyboard.type("pol")
        screen("command palette, with a query")
        page.keyboard.press("Escape")

        # Knowledge base, a collection, the delete dialog.
        page.goto(f"{base_url}/knowledge")
        page.get_by_role("table").wait_for()
        check_load(page, "knowledge base", report)
        screen("knowledge base")
        page.get_by_role("tab", name="Clinic Operations").click()
        page.get_by_role("button", name="Collection actions").click()
        page.get_by_role("menu").wait_for()
        screen("knowledge base, collection menu")
        page.keyboard.press("Escape")
        page.get_by_role("button", name="New collection").click()
        page.get_by_role("dialog").wait_for()
        screen("knowledge base, dialog")
        page.keyboard.press("Escape")

        # Chunk inspector: the top of the page, then the chunks with the overlap.
        page.get_by_role("tab", name="All documents").click()
        page.get_by_role("link", name="Employee Handbook", exact=True).click()
        page.get_by_role("heading", name="Ingestion pipeline").wait_for()
        page.goto(page.url)
        page.get_by_role("heading", name="Ingestion pipeline").wait_for()
        check_load(page, "chunk inspector", report)
        screen("chunk inspector")
        page.locator(".overlap-text").first.evaluate("element => element.closest('li').scrollIntoView({ block: 'center' })")
        screen("chunk inspector, overlap")

        # Insights: tiles and chart, a chart tooltip, the table view, the lower half.
        page.goto(f"{base_url}/insights")
        page.get_by_role("heading", name="Knowledge gaps").wait_for()
        check_load(page, "insights", report)
        screen("insights")
        page.locator("[data-day]").nth(9).hover()
        page.get_by_role("tooltip").wait_for()
        screen("insights, chart tooltip")
        page.mouse.move(2, 2)
        page.get_by_role("button", name="Show as table").click()
        screen("insights, table view")
        scroll_page(page, 100_000)
        screen("insights, lower half")

        # What a member sees instead of an admin page.
        if width < 1024:
            page.get_by_role("button", name="Open navigation").click()
        page.get_by_role("button", name="Sign out").click()
        page.wait_for_url("**/login")
        sign_in(page, base_url, MEMBER)
        page.goto(f"{base_url}/knowledge")
        page.get_by_role("heading", name="Administrators only").wait_for()
        check_load(page, "administrators only", report)
        screen("administrators only")

        browser.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--themes", default="light,dark")
    parser.add_argument("--widths", default="1440,1024,390")
    args = parser.parse_args()

    reports: list[Report] = []
    try:
        for theme in args.themes.split(","):
            for width in (int(value) for value in args.widths.split(",")):
                # A fresh database for every run keeps the screens identical from run to run.
                with seeded_server(prefix="sourcewise-audit-") as base_url:
                    print(f"Auditing the {theme} theme at {width}px ...")
                    reports.append(audit(base_url, theme, width))
    except (PlaywrightError, RuntimeError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1

    print()
    print(f"{'theme':<6} {'width':>5} {'screens':>8} {'texts measured':>15} {'lowest contrast':>16} {'worst layout shift':>19}  failures")
    failed = 0
    for report in reports:
        failed += len(report.failures)
        print(
            f"{report.theme:<6} {report.width:>5} {report.screens:>8} {report.texts:>15} "
            f"{report.lowest_ratio:>14.2f}:1 {report.worst_shift:>19.4f}  {len(report.failures)}"
        )
    for report in reports:
        if report.worst_shift > 0:
            print(f"  [note] {report.theme} {report.width}px - largest layout shift {report.worst_shift:.4f} on {report.worst_shift_page}")
        for failure in dict.fromkeys(report.failures):  # unique, in order
            print(f"  [FAIL] {report.theme} {report.width}px - {failure}")
    print("PASSED" if not failed else f"FAILED ({failed} finding(s))")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
