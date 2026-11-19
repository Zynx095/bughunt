"""Deterministic local fallbacks used when no LLM provider is available.

These are *not* language models. They are labelled `local-fallback` in every
response so the UI and users can tell them apart from LLM output.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.engines.text import WORD_RE, split_sentences


def extractive_summary(text: str, max_sentences: int = 3) -> list[str]:
    sentences = split_sentences(text)
    if len(sentences) <= max_sentences:
        return sentences
    try:
        tfidf = TfidfVectorizer(stop_words="english").fit_transform(sentences)
    except ValueError:  # only stop words
        return sentences[:max_sentences]
    centroid = np.asarray(tfidf.mean(axis=0))
    scores = cosine_similarity(tfidf, centroid).ravel()
    scores += np.linspace(0.05, 0, len(sentences))  # mild lead bias: earlier sentences break ties
    keep = sorted(np.argsort(scores)[::-1][:max_sentences])
    return [sentences[i] for i in keep]


def best_sentences(question: str, passages: list[dict[str, Any]], n: int = 3) -> list[dict[str, Any]]:
    """Pick the sentences from retrieved passages most similar to the question."""
    seen: set[str] = set()
    cands = []
    for p in passages:  # overlapping chunks repeat sentences; keep the first occurrence
        for s in split_sentences(p["text"]):
            if s not in seen:
                seen.add(s)
                cands.append((s, p["citation"]))
    if not cands:
        return []
    try:
        vec = TfidfVectorizer(stop_words="english").fit([question] + [c[0] for c in cands])
    except ValueError:
        return [{"sentence": s, "citation": c} for s, c in cands[:n]]
    sims = cosine_similarity(vec.transform([question]), vec.transform([c[0] for c in cands])).ravel()
    order = [i for i in np.argsort(sims)[::-1][:n] if sims[i] > 0]
    return [{"sentence": cands[i][0], "citation": cands[i][1], "similarity": round(float(sims[i]), 4)} for i in order]


def template_explanation(subject: str, context: dict[str, Any], audience: str) -> str:
    parts: list[str] = []
    score = context.get("score", context.get("risk_score", context.get("combined_score")))
    band = context.get("band") or context.get("risk_band") or context.get("max_severity")
    outcome = context.get("outcome") or context.get("decision")
    head = f"{subject}"
    score_txt = None
    if score is not None:
        score_txt = f"{score:.0f}/100" if isinstance(score, (int, float)) and score > 1 else f"score {score}"
    if band:
        head += f" was assessed as {str(band).upper()}" + (f" ({score_txt})" if score_txt else "")
    elif score_txt:
        head += f" scored {score_txt}"
    if outcome:
        head += f", outcome: {outcome}"
    parts.append(head + ".")
    contribs = context.get("contributions") or []
    if contribs:
        top = ", ".join(f"{c.get('factor')} ({c.get('points', 0):.0f} pts)" for c in contribs[:3] if c.get("points", 0) > 0)
        if top:
            parts.append(f"The largest contributing factors were {top}.")
    findings = context.get("findings") or context.get("matched") or []
    if findings:
        descs = [f.get("description") or f.get("id") if isinstance(f, dict) else str(f) for f in findings]
        descs = list(dict.fromkeys(d for d in descs if d))[:4]
        parts.append("Key findings: " + "; ".join(descs) + ".")
    extra = {k: v for k, v in context.items() if k not in {"score", "risk_score", "combined_score", "band", "risk_band",
             "max_severity", "outcome", "decision", "contributions", "findings", "matched", "recommendation"}
             and isinstance(v, (str, int, float, bool))}
    if extra:
        parts.append("Other facts: " + "; ".join(f"{k.replace('_', ' ')} = {v}" for k, v in list(extra.items())[:6]) + ".")
    if context.get("recommendation"):
        parts.append(f"Recommended next step: {context['recommendation']}.")
    if audience == "public":
        parts.append("This is an automated assessment; a person reviews significant decisions.")
    return " ".join(parts)


PLAIN_LANGUAGE = {
    "in accordance with": "under", "pursuant to": "under", "prior to": "before", "subsequent to": "after",
    "in the event that": "if", "with regard to": "about", "in respect of": "about", "notwithstanding": "despite",
    "commence": "start", "commencement": "start", "terminate": "end", "termination": "ending", "utilise": "use",
    "utilize": "use", "endeavour": "try", "endeavor": "try", "remuneration": "pay", "facilitate": "help",
    "sufficient": "enough", "aforementioned": "this", "henceforth": "from now on", "obtain": "get",
    "approximately": "about", "additional": "more", "assistance": "help", "ascertain": "find out",
    "beneficiary": "person who receives", "eligibility": "who can apply", "expenditure": "spending",
    "forthwith": "now", "in lieu of": "instead of", "is required to": "must", "are required to": "must",
    "shall": "must", "submit": "send", "residence": "home", "reside": "live", "individuals": "people",
    "inform": "tell", "require": "need", "demonstrate": "show", "accordingly": "so", "whereby": "where",
    "a number of": "some", "at this point in time": "now", "for the purpose of": "to",
    "aggregate": "total", "prescribed": "set", "does not exceed": "is not more than", "do not exceed": "are not more than",
    "accompanied by": "with", "documentary evidence": "proof", "the provisions of": "", "entitlement": "right to support",
    "arrears": "back payments", "overpayments": "money paid by mistake", "circumstances": "situation",
    "in order to": "to", "therefore": "so", "the aforementioned": "this",
}


def _match_case(src: str, repl: str) -> str:
    return repl[:1].upper() + repl[1:] if src[:1].isupper() else repl


def _is_proper_noun(text: str, start: int, word: str) -> bool:
    """Capitalised mid-sentence => probably part of a name (e.g. 'Housing Assistance Regulations')."""
    if not word[:1].isupper():
        return False
    before = text[:start].rstrip()
    return bool(before) and before[-1] not in ".!?:;\n"


def plain_language(text: str, max_words: int = 20) -> tuple[str, list[str]]:
    changes: list[str] = []
    out = text
    for phrase in sorted(PLAIN_LANGUAGE, key=len, reverse=True):
        pat = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
        repl = PLAIN_LANGUAGE[phrase]
        hits = 0

        def sub(m: re.Match, _repl: str = repl) -> str:
            nonlocal hits
            if _is_proper_noun(m.string, m.start(), m.group(0)):
                return m.group(0)
            hits += 1
            return _match_case(m.group(0), _repl)

        out = pat.sub(sub, out)
        if hits:
            changes.append(f"'{phrase}' -> '{repl}'" if repl else f"removed '{phrase}'")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s*\([^)]{0,80}\)", "", out)  # drop short parentheticals
    sentences: list[str] = []
    for s in split_sentences(out):
        if len(WORD_RE.findall(s)) <= max_words:
            sentences.append(s)
            continue
        pieces = re.split(r";\s+|,\s+(?=(?:and|but|which|so|while|because|unless)\b)", s)
        if len(pieces) > 1:
            changes.append(f"split a {len(WORD_RE.findall(s))}-word sentence into {len(pieces)}")
        for p in pieces:
            p = re.sub(r"^(and|but|so|while)\s+", "", p.strip(), flags=re.IGNORECASE)
            p = re.sub(r"^however,\s*", "But ", p, flags=re.IGNORECASE)
            p = re.sub(r"^which\b", "This", p)
            if p:
                p = p[0].upper() + p[1:]
                sentences.append(p if p.endswith((".", "!", "?")) else p + ".")
    return " ".join(sentences), changes
