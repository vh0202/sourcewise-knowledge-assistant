"""Porter stemming algorithm (M. F. Porter, 1980), implemented from the published description.

The same stemmer is applied at index time and at query time, so "refunds", "refunded" and
"refundable" all meet at the stem "refund". Keeping it in-repo (about 150 lines) avoids a
dependency on NLTK for one function and makes the retrieval analysis fully deterministic.
"""

from __future__ import annotations

from functools import lru_cache

_VOWELS = frozenset("aeiou")


def _is_consonant(word: str, i: int) -> bool:
    ch = word[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        # "y" is a consonant at the start of a word or after a vowel (toy), a vowel after a consonant (syzygy).
        return i == 0 or not _is_consonant(word, i - 1)
    return True


def _measure(stem: str) -> int:
    """Number of vowel-consonant sequences: the m in [C](VC)^m[V]."""
    m = 0
    previous_was_vowel = False
    for i in range(len(stem)):
        consonant = _is_consonant(stem, i)
        if consonant and previous_was_vowel:
            m += 1
        previous_was_vowel = not consonant
    return m


def _has_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and _is_consonant(word, len(word) - 1)


def _ends_cvc(word: str) -> bool:
    """True for consonant-vowel-consonant endings where the final consonant is not w, x or y."""
    if len(word) < 3:
        return False
    n = len(word)
    return (
        _is_consonant(word, n - 3)
        and not _is_consonant(word, n - 2)
        and _is_consonant(word, n - 1)
        and word[-1] not in "wxy"
    )


_STEP2 = (
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"), ("izer", "ize"),
    ("abli", "able"), ("alli", "al"), ("entli", "ent"), ("eli", "e"), ("ousli", "ous"),
    ("ization", "ize"), ("ation", "ate"), ("ator", "ate"), ("alism", "al"), ("iveness", "ive"),
    ("fulness", "ful"), ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
)
_STEP3 = (
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"), ("ical", "ic"),
    ("ful", ""), ("ness", ""),
)
_STEP4 = (
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent", "ion",
    "ou", "ism", "ate", "iti", "ous", "ive", "ize",
)


def _longest_suffix(word: str, suffixes: tuple[str, ...]) -> str | None:
    best: str | None = None
    for suffix in suffixes:
        if word.endswith(suffix) and (best is None or len(suffix) > len(best)):
            best = suffix
    return best


def _step1(word: str) -> str:
    # 1a - plurals
    if word.endswith("sses") or word.endswith("ies"):
        word = word[:-2]
    elif word.endswith("ss"):
        pass
    elif word.endswith("s"):
        word = word[:-1]

    # 1b - past participles and gerunds
    if word.endswith("eed"):
        if _measure(word[:-3]) > 0:
            word = word[:-1]
    else:
        stripped: str | None = None
        if word.endswith("ed") and _has_vowel(word[:-2]):
            stripped = word[:-2]
        elif word.endswith("ing") and _has_vowel(word[:-3]):
            stripped = word[:-3]
        if stripped is not None:
            word = stripped
            if word.endswith(("at", "bl", "iz")):
                word += "e"
            elif _ends_double_consonant(word) and word[-1] not in "lsz":
                word = word[:-1]
            elif _measure(word) == 1 and _ends_cvc(word):
                word += "e"

    # 1c - terminal y
    if word.endswith("y") and _has_vowel(word[:-1]):
        word = word[:-1] + "i"
    return word


def _step2_3(word: str, rules: tuple[tuple[str, str], ...]) -> str:
    suffix = _longest_suffix(word, tuple(s for s, _ in rules))
    if suffix is None:
        return word
    stem_part = word[: -len(suffix)]
    if _measure(stem_part) > 0:
        return stem_part + dict(rules)[suffix]
    return word


def _step4(word: str) -> str:
    suffix = _longest_suffix(word, _STEP4)
    if suffix is None:
        return word
    stem_part = word[: -len(suffix)]
    if _measure(stem_part) <= 1:
        return word
    if suffix == "ion" and not stem_part.endswith(("s", "t")):
        return word
    return stem_part


def _step5(word: str) -> str:
    if word.endswith("e"):
        stem_part = word[:-1]
        m = _measure(stem_part)
        if m > 1 or (m == 1 and not _ends_cvc(stem_part)):
            word = stem_part
    if _measure(word) > 1 and _ends_double_consonant(word) and word.endswith("l"):
        word = word[:-1]
    return word


@lru_cache(maxsize=50_000)
def stem(word: str) -> str:
    """Return the Porter stem of a lower-case alphabetic word.

    Words of one or two letters and tokens containing digits are returned unchanged.
    """
    if len(word) <= 2 or not word.isalpha() or not word.isascii():
        return word
    word = _step1(word)
    word = _step2_3(word, _STEP2)
    word = _step2_3(word, _STEP3)
    word = _step4(word)
    return _step5(word)
