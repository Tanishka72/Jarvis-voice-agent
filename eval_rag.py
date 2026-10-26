"""Evaluate the RAG pipeline on a labelled test set (eval/rag_eval_set.json).

    python eval_rag.py              retrieval metrics only (fast, uses no Gemini quota)
    python eval_rag.py --generate   also lets Gemini answer every question and scores the answers

RETRIEVAL METRICS (is the right text found?)
  Hit rate            - share of questions where at least one kept passage is from a correct page
  MRR                 - Mean Reciprocal Rank: 1 if the first passage is correct, 1/2 if the second...
  Context precision   - share of kept passages that come from a correct page (less noise = higher)
  Out-of-scope reject - share of not-covered questions where the pipeline says "not in the documents"

GENERATION METRICS (is the answer good?), with --generate
  Groundedness        - how well each answer sentence is supported by the retrieved text (0-1)
  Answer relevance    - how closely the answer matches the question's meaning (0-1)
  Citation accuracy   - share of answers whose cited pages were really retrieved
  Correct refusals    - share of not-covered questions where Jarvis said it isn't in the document

The pipeline is compared with a naive baseline (vector search only, top 4, no reranking,
no compression, no "not found" check) to show what the extra stages add.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

import rag

BASE = Path(__file__).parent
EVAL_SET = BASE / "eval" / "rag_eval_set.json"
REPORT = BASE / "logs" / "eval_report.json"


def retrieval_scores(pages: list[int], expected: list[int]) -> dict:
    relevant = [p in expected for p in pages]
    first = relevant.index(True) + 1 if any(relevant) else None
    return {"hit": any(relevant), "rr": 1 / first if first else 0.0,
            "precision": sum(relevant) / len(relevant) if relevant else 0.0}


def baseline_search(question: str) -> tuple[list[int], int]:
    """Naive RAG: top 4 chunks by vector similarity. Returns (pages, characters of context)."""
    col = rag._get_collection()
    vec = rag._embed([question])[0]
    res = col.query(query_embeddings=[vec.tolist()], n_results=4, include=["metadatas", "documents"])
    return [m["page"] for m in res["metadatas"][0]], sum(len(d) for d in res["documents"][0])


def summarize(rows: list[dict], key: str) -> dict:
    covered = [r[key] for r in rows if r["expected_pages"]]
    oos = [r[key] for r in rows if not r["expected_pages"]]
    return {
        "avg_context_chars": round(np.mean([s["context_chars"] for s in covered])),
        "hit_rate": round(np.mean([s["hit"] for s in covered]), 3),
        "mrr": round(np.mean([s["rr"] for s in covered]), 3),
        "context_precision": round(np.mean([s["precision"] for s in covered]), 3),
        "out_of_scope_rejection": round(np.mean([s["rejected"] for s in oos]), 3) if oos else None,
    }


def main():
    rag.on_event = lambda message: None  # keep the output clean
    rag.index_folder(log=lambda m: None)
    tests = json.loads(EVAL_SET.read_text(encoding="utf-8"))["questions"]
    generate = "--generate" in sys.argv
    brain = None
    if generate:
        import agent
        brain = agent.Brain()

    rows = []
    print(f"Evaluating {len(tests)} questions{' (with answer generation)' if generate else ''}...\n")
    for t in tests:
        q, expected = t["question"], t["expected_pages"]
        row = {"question": q, "intent": t["intent"], "expected_pages": expected}

        base, base_chars = baseline_search(q)
        row["baseline"] = {**retrieval_scores(base, expected), "pages": base, "rejected": False,
                           "context_chars": base_chars}

        rag.start_turn()
        started = time.time()
        result = rag.search_documents(q, t["intent"])
        pages = [p["page"] for p in result.get("passages", [])]
        row["pipeline"] = {**retrieval_scores(pages, expected), "pages": pages,
                           "rejected": not result.get("answer_found"),
                           "context_chars": sum(len(p["text"]) for p in result.get("passages", [])),
                           "ms": round((time.time() - started) * 1000)}
        rag.start_turn()

        if generate:
            answer = brain.ask(f"According to my PDF: {q}", log=lambda m: None)
            check = brain.last_check or {}
            vecs = rag._embed([q, answer])
            refused = any(w in answer.lower() for w in
                          ("doesn't", "does not", "not mention", "no mention", "not cover", "isn't", "no information"))
            row["generation"] = {"answer": answer, "groundedness": check.get("groundedness"),
                                 "answer_relevance": round(float(vecs[0] @ vecs[1]), 3),
                                 "citations_ok": check.get("citations_ok", True), "refused": refused}
            time.sleep(3)  # stay under the free per-minute limit

        mark = "OOS" if not expected else ("hit " if row["pipeline"]["hit"] else "MISS")
        print(f"  [{mark}] {q[:60]:<60} pipeline pages {pages or '-'}  baseline {base}")
        rows.append(row)

    report = {"baseline": summarize(rows, "baseline"), "pipeline": summarize(rows, "pipeline"),
              "avg_pipeline_ms": round(np.mean([r["pipeline"]["ms"] for r in rows]))}
    if generate:
        gen_cov = [r["generation"] for r in rows if r["expected_pages"]]
        gen_oos = [r["generation"] for r in rows if not r["expected_pages"]]
        report["generation"] = {
            "groundedness": round(np.mean([g["groundedness"] for g in gen_cov if g["groundedness"] is not None]), 3),
            "answer_relevance": round(np.mean([g["answer_relevance"] for g in gen_cov]), 3),
            "citation_accuracy": round(np.mean([g["citations_ok"] for g in gen_cov]), 3),
            "correct_refusals": round(np.mean([g["refused"] for g in gen_oos]), 3) if gen_oos else None,
        }

    print("\n" + "=" * 64)
    print(f"{'Metric':<26}{'Baseline (vector top-4)':>24}{'Full pipeline':>14}")
    print("-" * 64)
    for k in ("hit_rate", "mrr", "context_precision", "out_of_scope_rejection", "avg_context_chars"):
        print(f"{k:<26}{report['baseline'][k]:>24}{report['pipeline'][k]:>14}")
    print(f"{'avg search time (ms)':<26}{'':>24}{report['avg_pipeline_ms']:>14}")
    if generate:
        print("-" * 64)
        for k, v in report["generation"].items():
            print(f"{k:<26}{'':>24}{v:>14}")
    print("=" * 64)

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps({"summary": report, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Full report saved to {REPORT.relative_to(BASE)}")


if __name__ == "__main__":
    main()
