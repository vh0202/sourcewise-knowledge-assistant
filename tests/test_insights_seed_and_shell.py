"""Insights, demo seeding, the application shell and the evaluation tooling."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from sourcewise import HONESTY_LABEL
from sourcewise.config import PROJECT_ROOT
from sourcewise.container import Container, build_container
from sourcewise.db import utcnow
from sourcewise.evaluation import _contains, _rank, evaluate, load_questions
from sourcewise.insights import compute_insights
from sourcewise.main import create_app
from sourcewise.models import Chunk, Citation, Conversation, Document, Message, User
from sourcewise.seed import COLLECTIONS, DEMO_ACTIVITY, DEMO_USERS, seed

from .conftest import make_settings, sign_in
from .test_api_knowledge import create_collection, upload


# -- insights ----------------------------------------------------------------------------------
@pytest.fixture
def activity(admin: TestClient, member: TestClient, container: Container) -> dict:
    """A small knowledge base and a known set of questions asked by two users."""
    collection = create_collection(admin, "Policies")
    upload(admin, collection["id"], "md")  # Leave Policy
    upload(admin, collection["id"], "txt")  # Remote Working Guidelines

    def ask(client: TestClient, question: str) -> dict:
        conversation = client.post("/api/conversations", json={}).json()["id"]
        response = client.post(f"/api/conversations/{conversation}/messages", json={"content": question, "stream": False})
        assert response.status_code == 200, response.text
        return response.json()

    answers = {
        "leave": ask(member, "How many days do full-time staff get?"),
        "core": ask(member, "What are the core hours?"),
        "leave_again": ask(admin, "How many days do full-time staff get?"),
        "gap": ask(member, "Where is the canteen?"),
        "gap_again": ask(admin, "where is the  CANTEEN?"),
        "other_gap": ask(member, "Who is the chief executive?"),
        "greeting": ask(member, "hello"),
    }
    member.post(f"/api/messages/{answers['leave']['id']}/feedback", json={"value": 1})
    member.post(f"/api/messages/{answers['core']['id']}/feedback", json={"value": -1})
    return answers


def test_insights_numbers(admin: TestClient, activity: dict) -> None:
    assert not activity["leave"]["abstained"] and not activity["core"]["abstained"]
    assert activity["gap"]["abstained"] and activity["other_gap"]["abstained"]

    insights = admin.get("/api/insights").json()
    assert insights["days"] == 14
    # Seven messages were sent, but "hello" is not a question about the knowledge base.
    assert (insights["questions"], insights["answered"], insights["abstained"]) == (6, 3, 3)
    assert insights["answer_rate"] == 0.5
    assert (insights["helpful"], insights["not_helpful"]) == (1, 1)
    assert insights["engines"] == {"offline": 6}
    assert insights["median_latency_ms"] >= 0
    assert insights["knowledge_base"]["collections"] == 1 and insights["knowledge_base"]["documents"] == 2
    assert insights["knowledge_base"]["chunks"] > 0


def test_insights_daily_series_covers_the_whole_window(admin: TestClient, activity: dict) -> None:
    insights = admin.get("/api/insights", params={"days": 7}).json()
    daily = insights["daily"]
    assert len(daily) == 7
    assert [day["date"] for day in daily] == sorted(day["date"] for day in daily)
    assert daily[-1]["date"] == utcnow().date().isoformat()
    assert (daily[-1]["answered"], daily[-1]["abstained"]) == (3, 3)
    assert all(day["answered"] == day["abstained"] == 0 for day in daily[:-1])


def test_most_cited_documents_and_knowledge_gaps(admin: TestClient, activity: dict) -> None:
    insights = admin.get("/api/insights").json()

    cited = {row["title"]: row for row in insights["most_cited"]}
    assert set(cited) == {"Leave Policy", "Remote Working Guidelines"}
    assert cited["Leave Policy"]["answers"] == 2 and cited["Leave Policy"]["citations"] >= 2
    assert cited["Remote Working Guidelines"]["answers"] == 1
    assert all(row["in_knowledge_base"] and row["collection"] == "Policies" for row in cited.values())
    assert insights["most_cited"][0]["title"] == "Leave Policy"  # most cited first

    gaps = insights["gaps"]
    assert [(gap["question"], gap["count"]) for gap in gaps] == [
        ("Who is the chief executive?", 1),
        ("where is the  CANTEEN?", 2),  # same question asked twice, latest wording shown
    ]
    assert all(gap["reason"] in ("weak_retrieval", "unsupported") for gap in gaps)
    assert all(gap["last_asked"].endswith("Z") for gap in gaps)


def test_insights_window_excludes_older_activity(admin: TestClient, activity: dict, container: Container) -> None:
    with container.session_factory() as session:
        for message in session.execute(select(Message)).scalars():
            message.created_at = utcnow() - timedelta(days=20)
        session.commit()
    recent = admin.get("/api/insights", params={"days": 14}).json()
    assert (recent["questions"], recent["most_cited"], recent["gaps"], recent["answer_rate"]) == (0, [], [], None)
    assert admin.get("/api/insights", params={"days": 30}).json()["questions"] == 6


def test_citations_of_a_deleted_document_stay_in_history_and_are_flagged(admin: TestClient, activity: dict) -> None:
    leave = next(d for d in admin.get("/api/documents").json() if d["title"] == "Leave Policy")
    assert admin.delete(f"/api/documents/{leave['id']}").status_code == 204

    row = next(r for r in admin.get("/api/insights").json()["most_cited"] if r["title"] == "Leave Policy")
    assert row["in_knowledge_base"] is False
    # The old answer still shows what it was based on.
    conversations = admin.get("/api/conversations").json()
    answers = [
        message
        for conversation in conversations
        for message in admin.get(f"/api/conversations/{conversation['id']}").json()["messages"]
        if message["citations"]
    ]
    assert answers and all(c["passage"] and c["document_title"] == "Leave Policy" for a in answers for c in a["citations"])


def test_insights_validation_and_empty_state(admin: TestClient) -> None:
    empty = admin.get("/api/insights").json()
    assert (empty["questions"], empty["answer_rate"], empty["median_latency_ms"]) == (0, None, None)
    assert len(empty["daily"]) == 14
    assert admin.get("/api/insights", params={"days": 0}).status_code == 422
    assert admin.get("/api/insights", params={"days": 500}).status_code == 422


def test_compute_insights_uses_the_given_clock(container: Container) -> None:
    with container.session_factory() as session:
        insights = compute_insights(session, days=3, now=utcnow().replace(year=2030, month=1, day=10))
    assert [day.date for day in insights.daily] == ["2030-01-08", "2030-01-09", "2030-01-10"]


# -- seeding -----------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory):
    """A fully seeded demo database, including the scripted activity."""
    container = build_container(make_settings(tmp_path_factory.mktemp("demo") / "data"))
    summary = seed(container, with_activity=True)
    yield container, summary
    container.close()


def test_seed_creates_accounts_corpus_and_activity(demo) -> None:
    container, summary = demo
    assert summary["problems"] == []
    assert summary["users_created"] == 2
    assert 8 <= summary["documents_total"] <= 12
    assert summary["documents_ingested"] == summary["documents_total"]
    assert summary["demo_questions_asked"] == sum(len(script.questions) for script in DEMO_ACTIVITY)

    with container.session_factory() as session:
        documents = session.execute(select(Document)).scalars().all()
        assert {document.kind for document in documents} == {"md", "txt", "html", "pdf"}
        assert all(document.status == "ready" for document in documents)
        pdf = next(document for document in documents if document.kind == "pdf")
        assert pdf.page_count >= 2  # a multi-page PDF, with page numbers on its chunks
        assert session.execute(select(func.count(Chunk.id)).where(Chunk.document_id == pdf.id, Chunk.page_start.is_(None))).scalar_one() == 0
        assert session.execute(select(func.count(Conversation.id))).scalar_one() == len(DEMO_ACTIVITY)
        assert {user.role for user in session.execute(select(User)).scalars()} == {"admin", "member"}


def test_seed_is_idempotent(demo) -> None:
    container, first = demo
    again = seed(container, with_activity=True)
    assert again["users_created"] == 0 and again["documents_ingested"] == 0 and again["demo_questions_asked"] == 0
    assert again["documents_total"] == first["documents_total"] and again["chunks_total"] == first["chunks_total"]
    assert again["problems"] == []


def test_seeded_activity_is_real_pipeline_output_spread_over_two_weeks(demo) -> None:
    container, _ = demo
    with container.session_factory() as session:
        answers = session.execute(select(Message).where(Message.role == "assistant")).scalars().all()
        assert all(answer.engine == "offline" for answer in answers)  # the seed never calls the Claude API
        assert any(answer.abstained for answer in answers) and any(not answer.abstained for answer in answers)
        days = {answer.created_at.date() for answer in answers}
        assert len(days) >= 10 and max(days) <= utcnow().date()
        assert (utcnow().date() - min(days)).days <= 13
        assert session.execute(select(func.count(Citation.id))).scalar_one() > 10
        insights = compute_insights(session, days=14)
    assert insights.questions == len(answers)
    assert insights.gaps and insights.most_cited
    assert insights.helpful > 0 and insights.not_helpful > 0


def test_demo_accounts_can_sign_in_and_are_advertised(demo) -> None:
    container, _ = demo
    client = TestClient(create_app(container.settings, container=container))
    meta = client.get("/api/meta").json()
    assert meta["name"] == "SourceWise"
    assert meta["notice"] == HONESTY_LABEL == "Sample project — self-initiated portfolio demo, not client work. All data is synthetic."
    assert meta["engine"] == {"name": "offline", "label": "Extractive (offline) mode", "model": None}
    assert meta["retriever"]["name"] in ("fts5", "bm25")
    assert [(a["email"], a["role"]) for a in meta["demo_accounts"]] == [(u["email"], u["role"]) for u in DEMO_USERS]
    for account in meta["demo_accounts"]:
        assert account["email"].endswith("@example.com")
        assert sign_in(TestClient(create_app(container.settings, container=container)), account).get("/api/auth/me").status_code == 200


def test_demo_accounts_can_be_hidden(tmp_path) -> None:
    container = build_container(make_settings(tmp_path / "data", show_demo_accounts=False))
    try:
        seed(container, with_activity=False)
        client = TestClient(create_app(container.settings, container=container))
        assert client.get("/api/meta").json()["demo_accounts"] == []
    finally:
        container.close()


def test_corpus_is_synthetic_and_free_of_contact_details() -> None:
    files = [path for path in (PROJECT_ROOT / "corpus").rglob("*") if path.is_file()]
    assert 8 <= len(files) <= 12
    assert {path.suffix for path in files} == {".md", ".txt", ".html", ".pdf"}
    assert sorted({path.parent.name for path in files}) == sorted(spec.folder for spec in COLLECTIONS)
    import re

    for path in files:
        if path.suffix == ".pdf":
            continue
        text = path.read_text(encoding="utf-8")
        emails = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
        assert all(email.endswith("@example.com") for email in emails), path.name
        assert not re.search(r"https?://(?!example\.com)", text), f"{path.name} links to an external site"
        assert "lorem ipsum" not in text.lower()


def test_command_line_seed_and_ask(tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    from sourcewise import __main__ as cli

    settings = make_settings(tmp_path / "data")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    documents = len([path for path in (PROJECT_ROOT / "corpus").rglob("*") if path.is_file()])

    # The start scripts call `seed --if-empty`: it seeds a new database...
    assert cli.main(["seed", "--if-empty", "--no-activity"]) == 0
    output = capsys.readouterr().out
    assert f"Seeded: {documents} documents" in output
    assert all(user["email"] in output for user in DEMO_USERS)
    # ...and leaves an existing one alone, so a deleted demo document is not brought back on restart.
    assert cli.main(["seed", "--if-empty"]) == 0
    assert "already has data" in capsys.readouterr().out
    # Without the flag, seeding again is harmless.
    assert cli.main(["seed", "--no-activity"]) == 0
    assert "(0 ingested now" in capsys.readouterr().out

    assert cli.main(["ask", "How", "long", "must", "a", "password", "be?"]) == 0
    output = capsys.readouterr().out
    assert "-> answer" in output and "at least 14 characters" in output
    assert "[1] Information Security Policy > Passwords and sign-in > Passwords" in output
    assert cli.main(["ask", "Can I bring my pet iguana to the office?"]) == 0
    output = capsys.readouterr().out
    assert "-> abstain" in output and "Not found in the knowledge base" in output


def test_command_line_user_creates_accounts_and_changes_passwords(tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    import getpass

    from sourcewise import __main__ as cli

    settings = make_settings(tmp_path / "data")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    def type_passwords(*passwords: str) -> None:
        typed = iter(passwords)
        monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(typed))

    def client() -> TestClient:
        return TestClient(create_app(settings, container=container))

    def can_sign_in(email: str, password: str) -> bool:
        return client().post("/api/auth/login", json={"email": email, "password": password}).status_code == 200

    # A new account is a member unless a role is given; the email is normalised like at sign-in.
    type_passwords("first-long-password", "first-long-password")
    assert cli.main(["user", " Priya.Raman@Example.com ", "--name", "Priya Raman"]) == 0
    assert "Created member account priya.raman@example.com." in capsys.readouterr().out

    container = build_container(settings)
    try:
        signed_in = client()
        login = signed_in.post("/api/auth/login", json={"email": "priya.raman@example.com", "password": "first-long-password"})
        assert login.status_code == 200 and (login.json()["name"], login.json()["role"]) == ("Priya Raman", "member")
        assert signed_in.get("/api/insights").status_code == 403

        # Changing the password (and role) signs the account out everywhere and keeps the name.
        type_passwords("second-long-password", "second-long-password")
        assert cli.main(["user", "priya.raman@example.com", "--role", "admin"]) == 0
        assert "Updated admin account priya.raman@example.com." in capsys.readouterr().out
        assert signed_in.get("/api/auth/me").status_code == 401
        assert not can_sign_in("priya.raman@example.com", "first-long-password")
        again = client()
        login = again.post("/api/auth/login", json={"email": "priya.raman@example.com", "password": "second-long-password"})
        assert (login.json()["name"], login.json()["role"]) == ("Priya Raman", "admin")
        assert again.get("/api/insights").status_code == 200
        with container.session_factory() as session:
            stored = session.execute(select(User).where(User.email == "priya.raman@example.com")).scalar_one()
            assert "second-long-password" not in stored.password_hash  # hashed, never stored as typed

        # Weak, mistyped or malformed input changes nothing.
        type_passwords("short")
        assert cli.main(["user", "priya.raman@example.com"]) == 1
        type_passwords("third-long-password", "third-long-passw0rd")
        assert cli.main(["user", "priya.raman@example.com"]) == 1
        type_passwords("third-long-password", "third-long-password")
        assert cli.main(["user", "not-an-email"]) == 1
        assert "do not match" in capsys.readouterr().err
        assert can_sign_in("priya.raman@example.com", "second-long-password")
    finally:
        container.close()


# -- application shell -------------------------------------------------------------------------
@pytest.fixture
def shell(tmp_path) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>SourceWise</title><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside the web root", encoding="utf-8")
    container = build_container(make_settings(tmp_path / "data", frontend_dist=dist))
    client = TestClient(create_app(container.settings, container=container))
    yield client
    container.close()


def test_frontend_is_served_from_the_same_port_with_spa_fallback(shell: TestClient) -> None:
    index = shell.get("/")
    assert index.status_code == 200 and "<div id=root>" in index.text
    assert index.headers["cache-control"] == "no-cache"
    # Client-side routes get the app shell, static files get themselves.
    for route in ("/login", "/knowledge", "/knowledge/documents/3", "/insights"):
        assert shell.get(route).text == index.text
    assert shell.get("/assets/app.js").text == "console.log('app')"
    assert shell.get("/favicon.svg").headers["content-type"].startswith("image/svg")


def test_unknown_api_paths_are_json_404s_not_the_app_shell(shell: TestClient) -> None:
    response = shell.get("/api/nope")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert shell.get("/api").status_code == 404


def test_path_traversal_is_not_possible(shell: TestClient) -> None:
    for path in ("/../secret.txt", "/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt", "/%2e%2e/secret.txt"):
        assert "outside the web root" not in shell.get(path).text


def test_security_headers_are_set_on_every_response(shell: TestClient) -> None:
    for path in ("/", "/api/health", "/api/nope", "/assets/app.js"):
        headers = shell.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        policy = headers["content-security-policy"]
        assert "default-src 'self'" in policy and "frame-ancestors 'none'" in policy
        assert "http" not in policy  # no third-party origins, so no CDN can be loaded


def test_openapi_schema_is_published_but_no_cdn_backed_docs_page(shell: TestClient) -> None:
    schema = shell.get("/api/openapi.json").json()
    assert schema["info"]["title"] == "SourceWise API"
    assert "/api/conversations/{conversation_id}/messages" in schema["paths"]
    # /docs and /redoc would load scripts from a CDN; they fall through to the app shell instead.
    assert "swagger" not in shell.get("/docs").text.lower()


def test_a_missing_frontend_build_is_explained(anonymous: TestClient) -> None:
    response = anonymous.get("/")
    assert response.status_code == 200
    assert "npm run build" in response.text


# -- evaluation tooling ------------------------------------------------------------------------
EVAL_DIR = PROJECT_ROOT / "eval"


@pytest.mark.parametrize("name", ["golden_set.json", "dev_set.json"])
def test_question_sets_are_well_formed_and_point_at_real_sections(name: str, seeded: Container) -> None:
    questions = load_questions(EVAL_DIR / name)
    assert len({q["id"] for q in questions}) == len(questions)
    assert len({q["question"] for q in questions}) == len(questions)

    with seeded.session_factory() as session:
        rows = session.execute(select(Chunk, Document.filename).join(Document, Chunk.document_id == Document.id)).all()
    sections: dict[str, list[tuple[list[str], str]]] = {}
    for chunk, filename in rows:
        sections.setdefault(filename, []).append(([h.lower() for h in chunk.heading_path], chunk.text))

    for q in questions:
        assert q["question"].strip() and isinstance(q["answerable"], bool)
        if not q["answerable"]:
            assert "expected" not in q
            continue
        assert q["expected"] and q["answer_contains"], q["id"]
        fact_found = False
        for target in q["expected"]:
            assert target["document"] in sections, f"{q['id']}: unknown document {target['document']}"
            wanted = target["section"].lower()
            texts = [text for headings, text in sections[target["document"]] if any(wanted in h for h in headings)]
            assert texts, f"{q['id']}: no section {target['section']!r} in {target['document']}"
            fact_found = fact_found or any(_contains(text, q["answer_contains"]) for text in texts)
        assert fact_found, f"{q['id']}: none of {q['answer_contains']} occurs in the expected section(s)"


def test_golden_set_meets_the_size_requirements_and_is_disjoint_from_the_dev_set() -> None:
    golden = load_questions(EVAL_DIR / "golden_set.json")
    dev = load_questions(EVAL_DIR / "dev_set.json")
    assert sum(q["answerable"] for q in golden) >= 25
    assert sum(not q["answerable"] for q in golden) >= 5
    assert not {q["question"].lower() for q in golden} & {q["question"].lower() for q in dev}
    covered = {target["document"] for q in golden if q["answerable"] for target in q["expected"]}
    corpus = {path.name for path in (PROJECT_ROOT / "corpus").rglob("*") if path.is_file()}
    assert covered == corpus  # every document is exercised


def test_evaluation_metrics_on_a_tiny_known_set(seeded: Container) -> None:
    questions = [
        {"id": "t1", "question": "How many days of annual leave do full-time employees get?", "answerable": True,
         "expected": [{"document": "employee-handbook.md", "section": "Annual leave"}], "answer_contains": ["25 days"]},
        {"id": "t2", "question": "What is the late cancellation fee?", "answerable": True,
         "expected": [{"document": "employee-handbook.md", "section": "Annual leave"}], "answer_contains": ["no such text"]},
        {"id": "t3", "question": "Can I bring my pet iguana to the office?", "answerable": False},
    ]
    report = evaluate(seeded, questions)
    assert (report.questions, report.answerable, report.unanswerable) == (3, 2, 1)
    assert report.section_hit_at_1 == 0.5 and report.section_hit_at_3 == 0.5 and report.section_mrr == 0.5
    assert (report.correctly_abstained, report.wrongly_abstained, report.abstain_accuracy) == (1, 0, 1.0)
    assert (report.answered, report.answers_with_expected_fact, report.answer_accuracy) == (2, 1, 0.5)
    by_id = {o.id: o for o in report.outcomes}
    assert by_id["t1"].section_rank == 1 and by_id["t1"].contains_expected is True
    assert by_id["t2"].section_rank is None and by_id["t2"].contains_expected is False
    assert by_id["t3"].abstained and by_id["t3"].answer == ""
    # The evaluation stores nothing.
    with seeded.session_factory() as session:
        assert not session.execute(select(Message).where(Message.content == "What is the late cancellation fee?")).first()


def test_evaluation_helpers() -> None:
    assert _contains("Staff get  25 DAYS a year [1]", ["25 days"])
    assert _contains("five working days", ["5 working days", "five working days"])
    assert not _contains("Staff get 27 days", ["25 days"])
    assert _rank([], {}, [{"document": "a.md", "section": "x"}], sections=True) is None


def test_results_file_matches_the_readme_if_present() -> None:
    """If eval/results.json exists, the README must quote exactly the numbers in it."""
    results_path = EVAL_DIR / "results.json"
    readme_path = PROJECT_ROOT / "README.md"
    if not results_path.exists() or not readme_path.exists():
        pytest.skip("results.json or README.md has not been generated yet")
    results = json.loads(results_path.read_text(encoding="utf-8"))
    readme = Path(readme_path).read_text(encoding="utf-8")
    for report in results["retrievers"].values():
        for key in ("section_hit_at_1", "section_hit_at_3"):
            assert f"{report[key] * 100:.1f}%" in readme, f"README does not quote {key} = {report[key]}"
        assert f"{report['correctly_abstained']}/{report['unanswerable']}" in readme
