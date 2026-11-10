"""Text analysis used for both indexing and querying.

``analyze()`` is the single definition of "a term" in SourceWise: lower-cased, accent-folded,
split on non-alphanumerics, stop-words removed, Porter-stemmed. The lexical retrievers, the
retrieval-confidence gate and the extractive answer engine all call it, so they agree on what
it means for a passage to "contain" a query term.
"""

from __future__ import annotations

import re
import unicodedata

from .stemmer import stem

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# "1,000" and "12,500" are single numbers, not the tokens "1" and "000".
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
# In "how long", "how many" the second word is part of the question word, not the topic.
_HOW_DEGREE_RE = re.compile(r"\bhow\s+(long|often|soon|quickly|fast|far|late|early|old|big|large)\b")

# Words that say nothing about the topic of a sentence or a question. Three groups:
# English function words; the fragments left behind by contractions ("I'm" -> "m"); and the
# generic verbs and fillers of conversational questions ("am I allowed to ...", "someone says
# ...", "where do I find ..."). Negations are included because a bag-of-words ranker cannot
# use them. The list is applied to raw tokens, before stemming, so that "allowed" can be
# dropped without also dropping "allowance".
STOPWORDS = frozenset(
    """
    a about above across after again against all almost along already also although always am
    among an and any are aren around as at be because been before behind being below beside
    between beyond both but by can cannot could couldn did didn do does doesn doing don done
    down during each either else etc ever few for from further had hadn has hasn have haven
    having he her here hers herself him himself his how however i if in instead into is isn it
    its itself just many may me might more most much must mustn my myself near neither no nor
    not now of off on once only onto or other ought our ours ourselves out over own per perhaps
    quite rather same shall shan she should shouldn since so some such than that the their
    theirs them themselves then there these they this those though through to too toward
    towards under unless until up upon us very via was wasn we were weren what when where
    whether which while who whom why will with within without won would wouldn yet you your
    yours yourself yourselves

    d ll m o re s t ve y

    able actually allowed anybody anyone anything ask asked asking bit came come comes coming
    couple everybody everyone everything exactly find finding gave get gets getting give given
    gives giving go goes going gone got hello help hey hi keep keeping keeps kept kind know
    knows let like liked look looking lot lots made make makes making maybe need needed needs
    ok okay please possible put puts putting really roughly said say saying says see somebody
    someone something sorry sort still take taken takes taking tell thank thanks thing things
    took try trying use used uses using usually want wanted wants way went yes
    """.split()
)


def fold(text: str) -> str:
    """Lower-case and strip diacritics so that "café" and "cafe" index identically."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def tokenize(text: str) -> list[str]:
    """Split text into lower-case alphanumeric tokens (no stop-word removal, no stemming)."""
    return _TOKEN_RE.findall(_THOUSANDS_RE.sub("", fold(text)))


def analyze(text: str) -> list[str]:
    """Return the searchable terms of ``text`` in order, duplicates preserved."""
    return [stem(token) for token in tokenize(text) if token not in STOPWORDS]


def query_terms(text: str) -> list[str]:
    """Distinct searchable terms of a question, in first-seen order."""
    seen: dict[str, None] = {}
    for term in analyze(_HOW_DEGREE_RE.sub(" ", fold(text))):
        seen.setdefault(term)
    return list(seen)
