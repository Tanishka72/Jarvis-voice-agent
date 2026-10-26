"""Guardrails: safety checks around the AI.

1. check_user_input()    - blocks prompt-injection / jailbreak attempts before they reach Gemini.
2. scan_document_text()  - flags PDF text that tries to give the AI instructions
                           ("indirect prompt injection"), so it is never shown to Gemini.
3. check_answer()        - after Gemini answers a document question, measures how well the
                           answer is supported by the retrieved text (groundedness) and checks
                           that every cited page was actually retrieved.
"""
import re

MAX_INPUT_CHARS = 1000

# Phrases typical of prompt-injection and jailbreak attempts.
_INJECTION_PATTERNS = [
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,30}\b(previous|prior|above|earlier|all|your|the)\b"
    r".{0,20}\b(instructions?|prompts?|rules|guidelines|guardrails|safety)\b",
    r"\b(reveal|show|print|repeat|leak|tell me|give me|what is|what's|what are)\b.{0,20}"
    r"\b(your (system prompt|hidden prompt|initial prompt|instructions|rules|api ?keys?)"
    r"|the (system prompt|hidden prompt|initial prompt|api ?keys?))\b",
    r"\byou are (now|no longer)\b",
    r"\b(pretend|act) (to be|as if|like) (you have no|there are no|an? (unrestricted|unfiltered|evil))",
    r"\b(developer|god|dan|jailbreak|unrestricted) mode\b",
    r"\bnew (system )?instructions?\s*:",
    r"<\s*/?\s*(system|assistant|instructions?)\s*>",
    r"\b(do not|don't) (tell|inform) the user\b",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def check_user_input(text: str) -> tuple[bool, str]:
    """Return (allowed, reason). Runs before anything is sent to Gemini."""
    if len(text) > MAX_INPUT_CHARS:
        return False, f"input is longer than {MAX_INPUT_CHARS} characters"
    match = _INJECTION_RE.search(text)
    if match:
        return False, f"possible prompt injection: '{match.group(0)[:60]}'"
    return True, ""


def scan_document_text(text: str) -> bool:
    """True if a chunk of a document looks like it is trying to instruct the AI."""
    return bool(_INJECTION_RE.search(text))


_PAGE_RE = re.compile(r"\bpages?\s+(\d+)(?:\s*(?:,|and|to|-)\s*(\d+))?", re.IGNORECASE)


def cited_pages(answer: str) -> set[int]:
    pages = set()
    for a, b in _PAGE_RE.findall(answer):
        pages.add(int(a))
        if b:
            pages.add(int(b))
    return pages


def check_answer(answer: str, context_vectors: list, retrieved_pages: set[int], embed) -> dict:
    """Groundedness: for each answer sentence, how similar is the closest retrieved sentence?

    `context_vectors` are normalised embeddings of the sentences Gemini was given, and `embed`
    turns texts into normalised vectors. Returns a score from 0 to 1 (higher = better
    supported) plus any sentences that look unsupported.
    """
    import numpy as np

    sentences = [s for s in re.split(r"(?<=[.!?])\s+", answer) if len(s.split()) >= 4]
    result = {"cited_pages": sorted(cited_pages(answer))}
    bad_citations = sorted(cited_pages(answer) - retrieved_pages)
    result["citations_ok"] = not bad_citations
    if bad_citations:
        result["pages_cited_but_not_retrieved"] = bad_citations
    if not sentences or not len(context_vectors):
        result["groundedness"] = None
        return result
    a = np.array(embed(sentences))
    c = np.array(context_vectors)
    best = (a @ c.T).max(axis=1)  # cosine similarity (vectors are normalised)
    result["groundedness"] = round(float(best.mean()), 2)
    result["unsupported_sentences"] = [s for s, score in zip(sentences, best) if score < 0.35]
    return result
