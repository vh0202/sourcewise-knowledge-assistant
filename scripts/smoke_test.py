"""Smoke-test a running, seeded SourceWise instance over HTTP (standard library only).

    python scripts/smoke_test.py                              # http://127.0.0.1:8102
    python scripts/smoke_test.py --base-url http://127.0.0.1:8102

Start the app first (``start.ps1`` / ``start.sh`` or ``python -m sourcewise serve``). The script
signs in with the seeded demo accounts, asks one answerable and one unanswerable question
(as JSON and as a server-sent event stream), checks that permissions are enforced, and
deletes the conversations it created. It exits with status 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sourcewise import HONESTY_LABEL  # noqa: E402
from sourcewise.seed import DEMO_USERS  # noqa: E402

ANSWERABLE = "How many days of annual leave do full-time employees get?"
UNANSWERABLE = "Can I bring my pet iguana to the office?"


class Client:
    """A tiny JSON client with its own cookie jar (one per signed-in user)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, str, str]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        # errors="replace": the app shell also references a binary asset (the preloaded font),
        # whose body is only fetched to see that it is served, not to be read as text.
        try:
            with self.opener.open(request, timeout=60) as response:
                return response.status, response.headers.get("content-type", ""), response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get("content-type", ""), error.read().decode("utf-8", errors="replace")

    def json(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        status, _, text = self.request(method, path, body)
        return status, (json.loads(text) if text else None)

    def sign_in(self, role: str) -> None:
        user = next(u for u in DEMO_USERS if u["role"] == role)
        status, _ = self.json("POST", "/api/auth/login", {"email": user["email"], "password": user["password"]})
        if status != 200:
            raise RuntimeError(f"Could not sign in as {user['email']} (HTTP {status}). Was the database seeded?")


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name, data = None, None
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name is not None and data is not None:
            events.append((name, data))
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8102")
    args = parser.parse_args()

    failures = 0

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if passed else 1
        print(f"  [{'ok' if passed else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))

    print(f"Smoke test against {args.base_url}")
    anonymous = Client(args.base_url)
    try:
        status, health = anonymous.json("GET", "/api/health")
    except (urllib.error.URLError, OSError) as error:
        print(f"  [FAIL] the app is not reachable: {error}")
        return 1
    check("health endpoint", status == 200 and health == {"status": "ok"})

    # -- the built frontend is served from the same port, with no third-party assets ----------
    status, content_type, index = anonymous.request("GET", "/")
    check("app shell is served at /", status == 200 and 'id="root"' in index and content_type.startswith("text/html"))
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', index)
    check("app shell references bundled assets only", bool(assets) and not re.search(r'(?:src|href)="https?://', index))
    for asset in assets:
        status, _, _ = anonymous.request("GET", asset)
        check(f"asset {asset}", status == 200)
    status, meta = anonymous.json("GET", "/api/meta")
    check("honesty label is published", status == 200 and meta["notice"] == HONESTY_LABEL)
    print(f"       engine: {meta['engine']['label']}; retriever: {meta['retriever']['label']}")

    # -- authentication and permissions -------------------------------------------------------
    status, _ = anonymous.json("GET", "/api/conversations")
    check("anonymous requests are rejected", status == 401, f"HTTP {status}")
    status, _ = anonymous.json("POST", "/api/auth/login", {"email": DEMO_USERS[0]["email"], "password": "wrong-password"})
    check("a wrong password is rejected", status == 401, f"HTTP {status}")

    member, admin = Client(args.base_url), Client(args.base_url)
    member.sign_in("member")
    admin.sign_in("admin")
    for path in ("/api/insights", "/api/documents"):
        status, _ = member.json("GET", path)
        check(f"member cannot read {path}", status == 403, f"HTTP {status}")
    status, documents = admin.json("GET", "/api/documents")
    ready = [d for d in documents if d["status"] == "ready"] if status == 200 else []
    check("admin lists the knowledge base", status == 200 and len(ready) == len(documents) > 0, f"{len(ready)} documents ready")
    status, insights = admin.json("GET", "/api/insights")
    check("admin reads insights", status == 200 and insights["questions"] > 0, f"{insights['questions']} questions in the window")

    # -- asking questions ---------------------------------------------------------------------
    status, conversation = member.json("POST", "/api/conversations", {})
    check("member starts a conversation", status == 201)
    path = f"/api/conversations/{conversation['id']}/messages"

    status, answer = member.json("POST", path, {"content": ANSWERABLE, "stream": False})
    cited = status == 200 and not answer["abstained"] and len(answer["citations"]) >= 1
    check("answerable question gets a cited answer", cited)
    if cited:
        citation = answer["citations"][0]
        quote_in_passage = citation["passage"][citation["start_char"] : citation["end_char"]] == citation["quote"]
        check("citation points at an exact span of its passage", quote_in_passage and "[1]" in answer["content"])
        print(f"       {answer['content'][:110]!r}")
        print(f"       [1] {citation['document_title']} > {' > '.join(citation['heading_path'])}")

    status, answer = member.json("POST", path, {"content": UNANSWERABLE, "stream": False})
    declined = status == 200 and answer["abstained"] and not answer["citations"]
    check("unanswerable question is declined", declined and answer["content"].startswith("Not found in the knowledge base"))

    status, content_type, stream = member.request("POST", path, {"content": "How long must a password be?"})
    events = parse_sse(stream)
    names = [name for name, _ in events]
    check("streaming answer arrives as server-sent events", status == 200 and content_type.startswith("text/event-stream"))
    check(
        "stream has start, text, citation and done events",
        names[:1] == ["start"] and names[-1:] == ["done"] and "delta" in names and "citation" in names,
        f"{len(events)} events",
    )
    if names[-1:] == ["done"]:
        final = events[-1][1]["message"]
        streamed = "".join(data.get("text", "") for name, data in events if name == "delta")
        check("streamed text equals the stored answer", streamed == final["content"])

    status, _ = admin.json("GET", f"/api/conversations/{conversation['id']}")
    check("another user cannot open the conversation", status == 404, f"HTTP {status}")

    # -- clean up -----------------------------------------------------------------------------
    status, _, _ = member.request("DELETE", f"/api/conversations/{conversation['id']}")
    check("the test conversation is deleted", status == 204)
    for client in (member, admin):
        client.request("POST", "/api/auth/logout")
    status, _ = member.json("GET", "/api/auth/me")
    check("signing out ends the session", status == 401, f"HTTP {status}")

    print("PASSED" if not failures else f"FAILED ({failures} check(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
