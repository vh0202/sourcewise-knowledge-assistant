"""Command line entry point: ``python -m sourcewise <command>``.

    serve    run the web application (API + built frontend) on one port
    seed     create the demo accounts, ingest the sample corpus, add demo activity
    user     create an account, or change the password, name or role of an existing one
    ask      answer one question with the offline engine, printing the retrieval ranking
    eval     run the retrieval / abstention evaluation on the golden question set
"""

from __future__ import annotations

import argparse
import sys

from .config import get_settings


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    host, port = args.host or settings.host, args.port or settings.port
    print(f"SourceWise is starting on http://{host}:{port}  (Ctrl+C to stop)")
    uvicorn.run("sourcewise.main:create_app", factory=True, host=host, port=port, log_level="info")
    return 0


def _seed(args: argparse.Namespace) -> int:
    from .seed import DEMO_USERS, has_data, seed_from_settings

    settings = get_settings()
    if args.if_empty and not args.reset and has_data(settings):
        print("The database already has data - nothing to seed. (Use `seed --reset` to start again.)")
        return 0
    try:
        summary = seed_from_settings(settings, reset=args.reset, with_activity=not args.no_activity)
    except PermissionError:
        print("Could not reset the data folder - stop the running server first.", file=sys.stderr)
        return 1
    print(
        f"Seeded: {summary['documents_total']} documents, {summary['chunks_total']} chunks "
        f"({summary['documents_ingested']} ingested now, {summary['demo_questions_asked']} demo questions asked)."
    )
    for problem in summary["problems"]:  # type: ignore[union-attr]
        print(f"  ! {problem}", file=sys.stderr)
    print("Demo accounts:")
    for user in DEMO_USERS:
        print(f"  {user['role']:<7} {user['email']}  /  {user['password']}")
    return 1 if summary["problems"] else 0


MIN_PASSWORD_LENGTH = 12


def _user(args: argparse.Namespace) -> int:
    """Create an account or update an existing one. The password is typed, never passed as an argument."""
    import getpass

    from sqlalchemy import delete, select

    from . import security
    from .container import build_container
    from .models import AuthSession, User

    email = args.email.strip().lower()
    if "@" not in email:
        print("Give the account's email address.", file=sys.stderr)
        return 1
    password = getpass.getpass(f"New password for {email}: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Use a password of at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat the password: ") != password:
        print("The two passwords do not match.", file=sys.stderr)
        return 1

    container = build_container(get_settings())
    try:
        with container.session_factory() as session:
            user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if user is None:
                user = User(
                    email=email,
                    name=args.name or email.split("@")[0],
                    role=args.role or "member",
                    password_hash=security.hash_password(password),
                )
                session.add(user)
                action = "Created"
            else:
                user.password_hash = security.hash_password(password)
                user.name = args.name or user.name
                user.role = args.role or user.role
                # A changed password signs the account out everywhere.
                session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
                action = "Updated"
            session.commit()
            print(f"{action} {user.role} account {user.email}.")
    finally:
        container.close()
    return 0


def _ask(args: argparse.Namespace) -> int:
    """Answer one question with the offline engine and show what retrieval found (stores nothing)."""
    from .container import build_container

    container = build_container(get_settings().model_copy(update={"engine": "offline", "stream_delay_ms": 0}))
    try:
        with container.session_factory() as session:
            plan, result = container.chat.dry_run(session, " ".join(args.question))
    finally:
        container.close()
    confidence = plan.confidence
    print(f"Retriever: {container.retriever.label}")
    print(f"Coverage {confidence.coverage:.2f}, evidence {confidence.evidence:.2f} -> "
          f"{'answer' if confidence.sufficient else 'abstain'}; unmatched terms: {list(confidence.missing_terms)}")
    for rank, passage in enumerate(plan.passages, start=1):
        page = f", p.{passage.page_start}" if passage.page_start else ""
        print(f"  {rank}. {passage.score:6.2f}  {passage.document_title} > {passage.section}{page}")
    print()
    print(result.text)
    for citation in result.citations:
        print(f"  [{citation.number}] {citation.passage.document_title} > {citation.passage.section}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "eval":
        # The evaluation has its own options; hand everything after "eval" straight to it.
        from .evaluation import main as run_evaluation

        return run_evaluation(argv[1:])

    parser = argparse.ArgumentParser(
        prog="python -m sourcewise", description="SourceWise - an AI knowledge assistant with cited answers."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the web application")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(handler=_serve)

    seed = commands.add_parser("seed", help="load the demo accounts, corpus and activity")
    seed.add_argument("--reset", action="store_true", help="delete the existing database and uploads first")
    seed.add_argument("--no-activity", action="store_true", help="skip the scripted demo conversations")
    seed.add_argument("--if-empty", action="store_true", help="do nothing if the database already has data")
    seed.set_defaults(handler=_seed)

    user = commands.add_parser("user", help="create an account or change its password, name or role")
    user.add_argument("email")
    user.add_argument("--name", default=None, help="display name (default for a new account: the part before @)")
    user.add_argument("--role", choices=["admin", "member"], default=None, help="default for a new account: member")
    user.set_defaults(handler=_user)

    ask = commands.add_parser("ask", help="answer one question offline and show the retrieval ranking")
    ask.add_argument("question", nargs="+")
    ask.set_defaults(handler=_ask)

    commands.add_parser("eval", help="evaluate retrieval and abstention (see: python -m sourcewise eval --help)")

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
