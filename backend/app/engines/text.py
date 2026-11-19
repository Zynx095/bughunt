"""Deterministic text utilities: sentence splitting, readability, entity extraction."""
from __future__ import annotations

import re

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    for block in re.split(r"\n\s*\n|\n(?=\s*[-*•\d]+[.)]?\s)", text):
        block = " ".join(block.split())
        if block:
            parts.extend(s.strip() for s in SENTENCE_RE.split(block) if s.strip())
    return parts


def count_syllables(word: str) -> int:
    w = word.lower().strip("'")
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def readability(text: str) -> dict:
    sentences = split_sentences(text)
    words = WORD_RE.findall(text)
    n_s, n_w = max(1, len(sentences)), max(1, len(words))
    syllables = [count_syllables(w) for w in words]
    n_syl = sum(syllables)
    complex_words = sum(1 for s in syllables if s >= 3)
    wps, spw = n_w / n_s, n_syl / n_w
    return {
        "sentences": len(sentences),
        "words": len(words),
        "characters": len(text),
        "avg_words_per_sentence": round(wps, 2),
        "avg_syllables_per_word": round(spw, 3),
        "complex_word_ratio": round(complex_words / n_w, 3),
        "long_sentences": sum(1 for s in sentences if len(WORD_RE.findall(s)) > 25),
        "flesch_reading_ease": round(206.835 - 1.015 * wps - 84.6 * spw, 1),
        "flesch_kincaid_grade": round(0.39 * wps + 11.8 * spw - 15.59, 1),
    }


ENTITY_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    "url": re.compile(r"\bhttps?://[^\s<>\"')\]]+", re.IGNORECASE),
    "ipv4": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
    "sha256": re.compile(r"\b[a-fA-F0-9]{64}\b"),
    "sha1": re.compile(r"\b[a-fA-F0-9]{40}\b"),
    "md5": re.compile(r"\b[a-fA-F0-9]{32}\b"),
    "cve": re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE),
    "phone": re.compile(r"(?<![\w.])\+?\d{1,3}?[\s\-.]?\(?\d{2,4}\)?[\s\-.]\d{3,4}[\s\-.]\d{3,4}\b"),
    "date": re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4})\b"),
    "time": re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\b"),
    "money": re.compile(r"(?:[$€£₹]\s?\d[\d,]*(?:\.\d{1,2})?|\b\d[\d,]*(?:\.\d{1,2})?\s?(?:USD|EUR|GBP|INR)\b)"),
    "btc_address": re.compile(r"\b(?:bc1[a-z0-9]{25,39}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b"),
}


def extract_entities(text: str, types: list[str] | None = None) -> dict[str, list[str]]:
    wanted = types or list(ENTITY_PATTERNS)
    out: dict[str, list[str]] = {}
    for name in wanted:
        pat = ENTITY_PATTERNS.get(name)
        if pat is None:
            continue
        found = list(dict.fromkeys(m.group(0).rstrip(".,;:") for m in pat.finditer(text)))
        if found:
            out[name] = found[:200]
    # Word boundaries stop the MD5/SHA-1 patterns matching inside longer digests.
    return out
