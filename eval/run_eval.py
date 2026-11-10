"""Run the offline evaluation: retrieval hit@1 / hit@3, abstention and answer checks.

    python eval/run_eval.py                 # golden set, FTS5 and pure-Python BM25
    python eval/run_eval.py --details       # one line per question
    python eval/run_eval.py --set eval/dev_set.json

Equivalent to ``python -m sourcewise eval``. Results for the golden set are written to
``eval/results.json``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sourcewise.evaluation import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
