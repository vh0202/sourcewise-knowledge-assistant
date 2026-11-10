"""The written deliverables: honesty label, required sections, no contact details, real numbers."""

from __future__ import annotations

import json
import re
import struct

import pytest

from sourcewise import HONESTY_LABEL
from sourcewise.config import PROJECT_ROOT

README = PROJECT_ROOT / "README.md"
CASE_STUDY = PROJECT_ROOT / "docs" / "case-study.md"
VIDEO_SCRIPT = PROJECT_ROOT / "docs" / "demo-video-script.md"
EVAL_NOTES = PROJECT_ROOT / "eval" / "README.md"
SCREENSHOTS = PROJECT_ROOT / "docs" / "screenshots"
DOCUMENTS = [README, CASE_STUDY, VIDEO_SCRIPT, EVAL_NOTES]
# What scripts/screenshots.py writes: seven screens in the light theme, three of them again in
# the dark theme, and the command palette.
EXPECTED_SCREENSHOTS = {
    "01-login.png",
    "02-chat-cited-answer.png",
    "03-chat-pdf-source-and-abstention.png",
    "04-knowledge-base.png",
    "05-chunk-inspector-pipeline.png",
    "06-chunk-inspector-overlap.png",
    "07-insights.png",
    "08-chat-cited-answer-dark.png",
    "09-knowledge-base-dark.png",
    "10-insights-dark.png",
    "11-command-palette.png",
}

pytestmark = pytest.mark.skipif(not README.exists(), reason="the documentation has not been written yet")


def read(path) -> str:
    return path.read_text(encoding="utf-8")


def test_readme_opens_with_the_honesty_label_and_has_every_required_section() -> None:
    text = read(README)
    assert HONESTY_LABEL in "\n".join(text.splitlines()[:5])
    headings = [line.lstrip("# ").lower() for line in text.splitlines() if line.startswith("## ")]
    for wanted in (
        "features", "architecture", "stack", "quick start", "configuration", "tests", "evaluation",
        "vector store", "deployment", "limitations", "verification status",
    ):
        assert any(wanted in heading for heading in headings), f"README has no section about {wanted!r}"
    assert "```mermaid" in text
    # One-command start for both platforms, and a plain statement of how far the Claude path
    # has been verified: run against the real API on a few questions, accuracy not measured.
    assert "start.ps1" in text and "start.sh" in text
    flat = " ".join(text.split())
    assert "has been run on a small scale, not evaluated" in flat
    assert "it does not measure how often Claude's answers are right" in flat
    assert "not executed" in next(h for h in headings if "deployment" in h)


def test_every_document_carries_the_label_and_no_contact_details() -> None:
    for path in DOCUMENTS:
        text = read(path)
        if path != EVAL_NOTES:
            assert HONESTY_LABEL in text, f"{path.name} does not carry the honesty label"
        emails = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
        assert all(email.endswith("@example.com") for email in emails), f"{path.name}: {emails}"
        for url in re.findall(r"https?://[^\s)>\"']+", text):
            assert re.match(r"https?://(127\.0\.0\.1|localhost|kb\.example\.com)\b", url), f"{path.name} links to {url}"
        for banned in ("linkedin", "github.com", "twitter", "upwork", "whatsapp", "telegram", "skype"):
            assert banned not in text.lower(), f"{path.name} mentions {banned}"


def test_case_study_is_a_short_sample_project_blurb_with_measured_numbers_only() -> None:
    text = read(CASE_STUDY)
    assert "self-initiated sample project" in text
    words = len(re.findall(r"[A-Za-z0-9'%.-]+", text))
    assert 200 <= words <= 300, f"case study is {words} words"
    for banned in ("client said", "testimonial", "our client", "the client"):
        assert banned not in text.lower()
    # Every percentage quoted in the blurb is one the evaluation actually produced.
    results = json.loads(read(PROJECT_ROOT / "eval" / "results.json"))
    measured = {f"{value * 100:.1f}%" for report in results["retrievers"].values() for value in report.values() if isinstance(value, float)}
    quoted = set(re.findall(r"\d+(?:\.\d+)?%", text))
    assert quoted and quoted <= measured, f"not measured: {quoted - measured}"


def test_documented_test_count_matches_the_suite(request: pytest.FixtureRequest) -> None:
    collected = len(request.session.items)
    if collected < 300:
        pytest.skip("only part of the suite is being run")
    assert f"{collected} passed" in read(README)
    assert f"{collected} automated tests" in read(CASE_STUDY)


def test_demo_video_script_has_a_timed_shot_list_and_narration() -> None:
    text = read(VIDEO_SCRIPT)
    shots = re.findall(r"^\| (\d) \| (\d):(\d\d) - (\d):(\d\d) \|", text, re.M)
    assert [int(shot[0]) for shot in shots] == list(range(1, len(shots) + 1)) and len(shots) >= 6
    end_seconds = int(shots[-1][3]) * 60 + int(shots[-1][4])
    assert 60 <= end_seconds <= 90
    narration = text.split("## Narration in one piece")[1].split("## ")[0]
    assert 120 <= len(narration.split()) <= 230  # speakable in 60-90 seconds


def test_screenshots_exist_at_1440_by_900_and_are_the_ones_the_readme_shows() -> None:
    images = sorted(SCREENSHOTS.glob("*.png"))
    assert {image.name for image in images} == EXPECTED_SCREENSHOTS
    for image in images:
        header = image.read_bytes()[:24]
        assert header[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", header[16:24]) == (1440, 900), image.name
    for linked in re.findall(r"\]\((docs/screenshots/[^)]+)\)", read(README)):
        assert (PROJECT_ROOT / linked).exists(), f"README shows a missing image: {linked}"


def test_readme_links_point_at_files_that_exist() -> None:
    for target in re.findall(r"\]\(([^)#][^)]*)\)", read(README)):
        if target.startswith("http"):
            continue
        assert (PROJECT_ROOT / target).exists(), f"README links to a missing file: {target}"


def test_built_frontend_carries_the_footer_label_and_loads_nothing_from_a_cdn() -> None:
    dist = PROJECT_ROOT / "frontend" / "dist"
    if not dist.exists():
        pytest.skip("the frontend has not been built")
    bundle = "".join(read(path) for path in (dist / "assets").glob("*.js"))
    assert "self-initiated portfolio demo, not client work. All data is synthetic." in bundle
    index = read(dist / "index.html")
    assert not re.search(r"(?:src|href)=\"https?://", index)
    # The Content-Security-Policy forbids inline scripts, so the theme bootstrap (which must run
    # before the first paint) is a separate same-origin file, and nothing else is inline either.
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", index), "index.html contains an inline script"
    assert '<script src="/theme-init.js"></script>' in index
    assert "data-theme" in read(dist / "theme-init.js")
    styles = "".join(read(path) for path in (dist / "assets").glob("*.css"))
    assert not re.search(r"url\(\s*[\"']?https?://", styles) and "@import" not in styles
