"""Evaluation of the offline pipeline on a question set.

For every question the script runs exactly what the application runs - retrieval, the
retrieval-confidence gate and the extractive engine - against a freshly ingested copy of the
sample corpus, and reports:

* **retrieval hit@1 / hit@3** (answerable questions): is a chunk from the expected document
  *and section* ranked first / in the top three? Document-level hits are reported as well.
* **abstention**: how many unanswerable questions were correctly declined, and how many
  answerable questions were wrongly declined.
* **answer check**: for answerable questions, does the extractive answer contain the
  expected fact?

The Claude engine is not evaluated here: it needs an API key and costs money to run.

    python -m sourcewise eval                      # golden set, default retriever(s)
    python -m sourcewise eval --set eval/dev_set.json --details
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .answering import Passage
from .config import PROJECT_ROOT, Settings, get_settings
from .container import Container, build_container
from .db import make_engine
from .models import Document
from .retrieval import fts5_available
from .seed import seed

DEFAULT_SET = PROJECT_ROOT / "eval" / "golden_set.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "results.json"


@dataclass
class Outcome:
    id: str
    question: str
    answerable: bool
    abstained: bool
    abstain_reason: str | None
    coverage: float
    document_rank: int | None = None  # 1-based rank of the first chunk from an expected document
    section_rank: int | None = None  # ... from an expected document and section
    contains_expected: bool | None = None
    answer: str = ""
    top: list[str] = field(default_factory=list)


@dataclass
class Report:
    retriever: str
    questions: int
    answerable: int
    unanswerable: int
    section_hit_at_1: float
    section_hit_at_3: float
    document_hit_at_1: float
    document_hit_at_3: float
    section_mrr: float
    correctly_abstained: int
    wrongly_abstained: int
    abstain_accuracy: float
    answered: int
    answers_with_expected_fact: int
    answer_accuracy: float
    outcomes: list[Outcome]


def load_questions(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["questions"]


def _rank(passages: list[Passage], filenames: dict[int, str], expected: list[dict[str, str]], *, sections: bool) -> int | None:
    for position, passage in enumerate(passages, start=1):
        filename = filenames.get(passage.document_id)
        headings = [heading.lower() for heading in passage.heading_path]
        for target in expected:
            if filename != target["document"]:
                continue
            wanted = target.get("section", "").lower()
            if not sections or not wanted or any(wanted in heading for heading in headings):
                return position
    return None


def _contains(answer: str, needles: list[str]) -> bool:
    """True if the answer includes at least one of the expected strings (case and spacing ignored)."""
    haystack = " ".join(answer.lower().split())
    return any(" ".join(needle.lower().split()) in haystack for needle in needles)


def evaluate(container: Container, questions: list[dict[str, Any]]) -> Report:
    outcomes: list[Outcome] = []
    with container.session_factory() as session:
        filenames = {doc.id: doc.filename for doc in session.execute(select(Document)).scalars()}
        for item in questions:
            plan, result = container.chat.dry_run(session, item["question"])
            outcome = Outcome(
                id=item["id"],
                question=item["question"],
                answerable=item["answerable"],
                abstained=result.abstained,
                abstain_reason=result.abstain_reason,
                coverage=plan.confidence.coverage,
                answer=result.text if not result.abstained else "",
                top=[f"{p.document_title} > {p.section}" for p in plan.passages[:3]],
            )
            if item["answerable"]:
                outcome.document_rank = _rank(plan.passages, filenames, item["expected"], sections=False)
                outcome.section_rank = _rank(plan.passages, filenames, item["expected"], sections=True)
                if not result.abstained:
                    outcome.contains_expected = _contains(result.text, item.get("answer_contains", []))
            outcomes.append(outcome)

    answerable = [o for o in outcomes if o.answerable]
    unanswerable = [o for o in outcomes if not o.answerable]
    answered = [o for o in answerable if not o.abstained]
    correctly_abstained = sum(1 for o in unanswerable if o.abstained)

    def share(count: int, total: int) -> float:
        return round(count / total, 4) if total else 0.0

    return Report(
        retriever=container.retriever.label,
        questions=len(outcomes),
        answerable=len(answerable),
        unanswerable=len(unanswerable),
        section_hit_at_1=share(sum(1 for o in answerable if o.section_rank == 1), len(answerable)),
        section_hit_at_3=share(sum(1 for o in answerable if o.section_rank and o.section_rank <= 3), len(answerable)),
        document_hit_at_1=share(sum(1 for o in answerable if o.document_rank == 1), len(answerable)),
        document_hit_at_3=share(sum(1 for o in answerable if o.document_rank and o.document_rank <= 3), len(answerable)),
        section_mrr=round(sum(1 / o.section_rank for o in answerable if o.section_rank) / len(answerable), 4) if answerable else 0.0,
        correctly_abstained=correctly_abstained,
        wrongly_abstained=len(answerable) - len(answered),
        abstain_accuracy=share(correctly_abstained + len(answered), len(outcomes)),
        answered=len(answered),
        answers_with_expected_fact=sum(1 for o in answered if o.contains_expected),
        answer_accuracy=share(sum(1 for o in answered if o.contains_expected), len(answerable)),
        outcomes=outcomes,
    )


def run(retriever: str, questions: list[dict[str, Any]], base: Settings) -> tuple[Report, dict[str, int]]:
    """Ingest the corpus into a throwaway database and evaluate one retriever on it."""
    with tempfile.TemporaryDirectory(prefix="sourcewise-eval-") as workdir:
        settings = base.model_copy(
            update={"data_dir": Path(workdir), "engine": "offline", "retriever": retriever, "stream_delay_ms": 0}
        )
        container = build_container(settings)
        try:
            summary = seed(container, with_activity=False)
            if summary["problems"]:
                raise RuntimeError(f"Corpus ingestion failed: {summary['problems']}")
            report = evaluate(container, questions)
            corpus = {"documents": int(summary["documents_total"]), "chunks": int(summary["chunks_total"])}  # type: ignore[arg-type]
        finally:
            container.close()
    return report, corpus


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def format_report(report: Report) -> str:
    lines = [
        f"Retriever: {report.retriever}",
        f"  Questions: {report.questions} ({report.answerable} answerable, {report.unanswerable} unanswerable)",
        f"  Retrieval, expected section   hit@1 {_percent(report.section_hit_at_1)}   hit@3 {_percent(report.section_hit_at_3)}   MRR {report.section_mrr:.3f}",
        f"  Retrieval, expected document  hit@1 {_percent(report.document_hit_at_1)}   hit@3 {_percent(report.document_hit_at_3)}",
        f"  Abstention: {report.correctly_abstained}/{report.unanswerable} unanswerable questions declined; "
        f"{report.wrongly_abstained}/{report.answerable} answerable questions wrongly declined; "
        f"accuracy {_percent(report.abstain_accuracy)}",
        f"  Answers: {report.answers_with_expected_fact}/{report.answerable} answerable questions answered with the expected fact "
        f"({_percent(report.answer_accuracy)}); {report.answered} answered in total",
    ]
    return "\n".join(lines)


def format_details(report: Report) -> str:
    lines = []
    for o in report.outcomes:
        if o.answerable:
            status = "ABSTAINED" if o.abstained else ("ok" if o.contains_expected else "WRONG")
            lines.append(
                f"  {o.id} [{status:9}] rank doc={o.document_rank} sec={o.section_rank} cov={o.coverage:.2f}  {o.question}"
            )
            if status != "ok":
                lines.append(f"       top: {o.top}")
                if o.answer:
                    lines.append(f"       answer: {o.answer[:200]!r}")
        else:
            status = "ok" if o.abstained else "ANSWERED"
            lines.append(f"  {o.id} [{status:9}] cov={o.coverage:.2f}  {o.question}")
            if not o.abstained:
                lines.append(f"       answer: {o.answer[:200]!r}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sourcewise eval", description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", type=Path, default=DEFAULT_SET, help="question set (default: eval/golden_set.json)")
    parser.add_argument("--retriever", choices=["auto", "fts5", "bm25", "both"], default="both")
    parser.add_argument("--out", type=Path, default=None, help="write results as JSON (default: eval/results.json for the golden set)")
    parser.add_argument("--details", action="store_true", help="print one line per question")
    args = parser.parse_args([a for a in (argv or []) if a != "--"])

    base = get_settings()
    questions = load_questions(args.set)
    if args.retriever == "both":
        retrievers = ["fts5", "bm25"] if fts5_available(make_engine("sqlite://")) else ["bm25"]
    else:
        retrievers = [args.retriever]

    results: dict[str, Any] = {}
    corpus: dict[str, int] = {}
    for name in retrievers:
        report, corpus = run(name, questions, base)
        print(format_report(report))
        if args.details:
            print(format_details(report))
        print()
        results[name] = asdict(report)

    out = args.out or (DEFAULT_OUTPUT if args.set.resolve() == DEFAULT_SET.resolve() else None)
    if out is not None:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "question_set": args.set.name,
            "corpus": corpus,
            "settings": {
                "top_k": base.top_k,
                "min_coverage": base.min_coverage,
                "min_evidence": base.min_evidence,
                "chunk_max_chars": base.chunk_max_chars,
                "chunk_overlap_chars": base.chunk_overlap_chars,
            },
            "retrievers": results,
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Results written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
