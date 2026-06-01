"""
scripts/run_eval.py — Automated RAG Quality Evaluation (Option B: Claude-as-Judge)

Loads benchmark questions from data/eval_benchmark.json, sends each to the
RAG chatbot, then asks Claude to score each response. Produces a JSON results
file and a human-readable text report.

Usage:
    python scripts/run_eval.py
    python scripts/run_eval.py --benchmark data/eval_benchmark.json
    python scripts/run_eval.py --output reports/eval_2026-05-18.json
    python scripts/run_eval.py --questions Q01 Q05 Q10   # run subset only
    python scripts/run_eval.py --no-judge                 # skip scoring, raw answers only

Outputs (written to reports/ folder):
    eval_YYYYMMDD_HHMMSS.json   — full structured results
    eval_YYYYMMDD_HHMMSS.txt    — human-readable summary report

Scoring rubric (Claude-as-judge):
    PASS    — Answer addresses the question with relevant, grounded content
    PARTIAL — Answer is on-topic but incomplete, vague, or missing key aspects
    FAIL    — Answer is off-topic, fabricated, refuses to answer, or cites no knowledge base content

Each question is also checked for format compliance:
    - No bibliography / reference list at the end (CITATIONS rule)
    - Prose format preferred over bullet points (RESPONSE FORMAT rule)
    - Appropriate length (<= ~200 words unless complex)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Force UTF-8 output on Windows (prevents UnicodeEncodeError from Rich/emoji)
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Allow running from project root: python scripts/run_eval.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Always load .env from project root regardless of where the script is run from
from dotenv import load_dotenv
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from src.chat import RAGChat, load_system_prompt
from src.embedder import Embedder
from src.store import VectorStore
from src.llm_adapter import chat as llm_chat


# ── Paths ────────────────────────────────────────────────────────────────────

DEFAULT_BENCHMARK = Path("data/eval_benchmark.json")
REPORTS_DIR = Path("reports")


# ── Judge prompt ─────────────────────────────────────────────────────────────

JUDGE_SYSTEM_PROMPT = """You are an impartial evaluator assessing the quality of a RAG chatbot specialising in Digital Health Standards and Interoperability.

You will be given:
1. A benchmark question
2. Expected key topics the answer should cover
3. The chatbot's actual answer

Score the answer using EXACTLY one of these verdicts:
  PASS    — The answer directly addresses the question with relevant, grounded content covering most expected topics.
  PARTIAL — The answer is on-topic but noticeably incomplete, vague, or missing important aspects.
  FAIL    — The answer is off-topic, appears fabricated (hallucinated), refuses to answer, or says it could not find information despite the question being within scope.

Also check format compliance (answer YES or NO to each):
  - no_bibliography: Does the answer avoid a bibliography or reference list at the end (lines like "[1] filename.pdf, page X")?
  - prose_format: Is the answer written in prose paragraphs rather than mostly bullet points?

Respond ONLY in this exact JSON format, nothing else:
{
  "verdict": "PASS" | "PARTIAL" | "FAIL",
  "reason": "One concise sentence explaining the verdict.",
  "no_bibliography": true | false,
  "prose_format": true | false,
  "coverage_score": 0-10
}"""


def judge_response(question: str, expected_topics: list[str], answer: str) -> dict:
    """Call Claude-as-judge to score a single RAG response."""
    topics_str = ", ".join(expected_topics)
    judge_message = f"""QUESTION: {question}

EXPECTED KEY TOPICS: {topics_str}

CHATBOT ANSWER:
{answer}

Evaluate the answer and respond in the required JSON format."""

    raw = llm_chat(
        system_prompt=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": judge_message}],
        max_tokens=300,
    )

    # Parse JSON from response
    try:
        # Strip any markdown code fences if present
        clean = raw.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:])
        if clean.endswith("```"):
            clean = "\n".join(clean.split("\n")[:-1])
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "verdict": "PARSE_ERROR",
            "reason": f"Judge returned unparseable response: {raw[:100]}",
            "no_bibliography": None,
            "prose_format": None,
            "coverage_score": None,
        }


# ── Report helpers ────────────────────────────────────────────────────────────

def verdict_symbol(verdict: str) -> str:
    return {"PASS": "✓", "PARTIAL": "~", "FAIL": "✗"}.get(verdict, "?")


def format_report(results: list[dict], meta: dict) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("  SI ASSISTANT — AUTOMATED EVALUATION REPORT")
    lines.append(f"  Run: {meta['run_timestamp']}")
    lines.append(f"  Model: {meta.get('llm_model', 'unknown')}")
    lines.append(f"  Total questions: {meta['total_questions']}")
    lines.append("=" * 70)
    lines.append("")

    # Summary counts
    verdicts = [r["judge"].get("verdict", "UNKNOWN") for r in results if r.get("judge")]
    pass_count = verdicts.count("PASS")
    partial_count = verdicts.count("PARTIAL")
    fail_count = verdicts.count("FAIL")
    judged = pass_count + partial_count + fail_count
    pass_pct = round(pass_count / judged * 100) if judged else 0
    partial_pct = round(partial_count / judged * 100) if judged else 0
    fail_pct = round(fail_count / judged * 100) if judged else 0

    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  PASS    {pass_count:>3}  ({pass_pct}%)")
    lines.append(f"  PARTIAL {partial_count:>3}  ({partial_pct}%)")
    lines.append(f"  FAIL    {fail_count:>3}  ({fail_pct}%)")
    lines.append(f"  Total judged: {judged}")
    lines.append("")

    # Format compliance
    no_bib = [r for r in results if r.get("judge") and r["judge"].get("no_bibliography") is True]
    prose = [r for r in results if r.get("judge") and r["judge"].get("prose_format") is True]
    lines.append("FORMAT COMPLIANCE")
    lines.append("-" * 40)
    lines.append(f"  No bibliography: {len(no_bib)}/{judged}")
    lines.append(f"  Prose format:    {len(prose)}/{judged}")
    lines.append("")

    # Per-category breakdown
    categories = {}
    for r in results:
        cat = r.get("category", "Unknown")
        v = r.get("judge", {}).get("verdict", "UNKNOWN")
        categories.setdefault(cat, []).append(v)

    lines.append("RESULTS BY CATEGORY")
    lines.append("-" * 40)
    for cat, vlist in sorted(categories.items()):
        cat_pass = vlist.count("PASS")
        cat_total = len(vlist)
        symbols = "".join(verdict_symbol(v) for v in vlist)
        lines.append(f"  {cat:<40} {symbols}  {cat_pass}/{cat_total}")
    lines.append("")

    # Per-question detail
    lines.append("DETAILED RESULTS")
    lines.append("-" * 40)
    for r in results:
        qid = r["id"]
        q = r["question"]
        verdict = r.get("judge", {}).get("verdict", "NOT JUDGED")
        reason = r.get("judge", {}).get("reason", "")
        coverage = r.get("judge", {}).get("coverage_score", "?")
        elapsed = r.get("elapsed_seconds", "?")
        sym = verdict_symbol(verdict)

        lines.append(f"\n[{qid}] {sym} {verdict}  (coverage: {coverage}/10, {elapsed}s)")
        lines.append(f"  Q: {q[:90]}{'...' if len(q) > 90 else ''}")
        lines.append(f"  Judge: {reason}")

        # Show answer excerpt
        answer = r.get("answer", "")
        excerpt = answer[:200].replace("\n", " ")
        if len(answer) > 200:
            excerpt += "..."
        lines.append(f"  Answer: {excerpt}")

        # Sources retrieved
        sources = r.get("sources_retrieved", [])
        if sources:
            src_names = [s.get("metadata", {}).get("source_file", "?") for s in sources[:3]]
            lines.append(f"  Sources: {', '.join(src_names)}")

    lines.append("")
    lines.append("=" * 70)
    lines.append(f"  Overall score: {pass_count}/{judged} PASS ({pass_pct}%)")
    lines.append("=" * 70)

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_eval(
    benchmark_path: Path,
    output_path: Path | None = None,
    question_ids: list[str] | None = None,
    skip_judge: bool = False,
    delay_seconds: float = 1.0,
) -> None:
    """
    Run the full evaluation loop.

    Args:
        benchmark_path:  Path to eval_benchmark.json
        output_path:     Optional explicit output file path
        question_ids:    If given, only run these IDs (e.g. ["Q01", "Q05"])
        skip_judge:      If True, collect answers but skip scoring
        delay_seconds:   Pause between questions (be kind to rate limits)
    """
    REPORTS_DIR.mkdir(exist_ok=True)

    # Load benchmark
    with open(benchmark_path, encoding="utf-8") as f:
        benchmark = json.load(f)

    questions = benchmark["questions"]
    if question_ids:
        questions = [q for q in questions if q["id"] in question_ids]
        if not questions:
            print(f"ERROR: No questions found for IDs: {question_ids}")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  SI Assistant — Evaluation Run")
    print(f"  Questions: {len(questions)}")
    print(f"  Benchmark: {benchmark_path}")
    print(f"  Judge:     {'DISABLED' if skip_judge else 'Claude-as-judge'}")
    print(f"{'='*60}\n")

    # Initialise RAG
    print("Loading knowledge base...")
    embedder = Embedder()
    store = VectorStore()
    system_prompt = load_system_prompt()
    llm_model = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-6")
    print(f"Model: {llm_model}")
    print(f"KB stats: {store.stats()['total_chunks']} total chunks\n")

    results = []
    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_slug = datetime.now().strftime("%Y%m%d_%H%M%S")

    for idx, q in enumerate(questions, 1):
        qid = q["id"]
        question = q["question"]
        category = q["category"]
        expected = q.get("expected_topics", [])

        print(f"[{idx}/{len(questions)}] {qid} — {category}")
        print(f"  Q: {question[:80]}{'...' if len(question) > 80 else ''}")

        # Create fresh RAGChat per question (no history bleed between questions)
        rag = RAGChat(
            system_prompt=system_prompt,
            embedder=embedder,
            store=store,
        )

        # Get RAG answer
        t0 = time.time()
        try:
            answer, sources = rag.chat(question)
            elapsed = round(time.time() - t0, 1)
            print(f"  Answer: {answer[:100].replace(chr(10), ' ')}... ({elapsed}s)")
        except Exception as e:
            elapsed = round(time.time() - t0, 1)
            answer = f"ERROR: {e}"
            sources = []
            print(f"  ERROR: {e}")

        # Score with judge
        judge_result = {}
        if not skip_judge and not answer.startswith("ERROR:"):
            print("  Judging...", end="", flush=True)
            try:
                judge_result = judge_response(question, expected, answer)
                v = judge_result.get("verdict", "?")
                c = judge_result.get("coverage_score", "?")
                print(f" {verdict_symbol(v)} {v} (coverage {c}/10)")
            except Exception as e:
                print(f" JUDGE ERROR: {e}")
                judge_result = {"verdict": "JUDGE_ERROR", "reason": str(e)}
        elif skip_judge:
            print("  (judge skipped)")

        results.append({
            "id": qid,
            "category": category,
            "complexity": q.get("complexity", "unknown"),
            "question": question,
            "expected_topics": expected,
            "answer": answer,
            "answer_length_words": len(answer.split()),
            "sources_retrieved": [
                {
                    "metadata": s.get("metadata", {}),
                    "score": s.get("score"),
                }
                for s in (sources or [])
            ],
            "elapsed_seconds": elapsed,
            "judge": judge_result,
        })

        print()  # blank line between questions

        # Rate-limit courtesy pause
        if idx < len(questions):
            time.sleep(delay_seconds)

    # ── Write outputs ──────────────────────────────────────────────────────

    meta = {
        "run_timestamp": run_timestamp,
        "benchmark_version": benchmark.get("version", "unknown"),
        "llm_model": llm_model,
        "total_questions": len(results),
        "skip_judge": skip_judge,
    }

    full_output = {"meta": meta, "results": results}

    # Determine file paths
    if output_path:
        json_path = Path(output_path)
        txt_path = json_path.with_suffix(".txt")
    else:
        json_path = REPORTS_DIR / f"eval_{run_slug}.json"
        txt_path = REPORTS_DIR / f"eval_{run_slug}.txt"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2, ensure_ascii=False)

    if not skip_judge:
        report_text = format_report(results, meta)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(report_text)
        print(f"\nJSON results: {json_path}")
        print(f"Text report:  {txt_path}")
    else:
        print(f"\nAnswers saved (judge skipped): {json_path}")

    # Quick final summary
    if not skip_judge:
        verdicts = [r["judge"].get("verdict", "") for r in results]
        pass_n = verdicts.count("PASS")
        total = len(verdicts)
        pct = round(pass_n / total * 100) if total else 0
        print(f"\n{'='*40}")
        print(f"  OVERALL: {pass_n}/{total} PASS ({pct}%)")
        print(f"{'='*40}\n")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Automated RAG evaluation using Claude-as-judge."
    )
    parser.add_argument(
        "--benchmark",
        default=str(DEFAULT_BENCHMARK),
        help=f"Path to benchmark JSON (default: {DEFAULT_BENCHMARK})",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (without extension). Default: reports/eval_TIMESTAMP",
    )
    parser.add_argument(
        "--questions",
        nargs="+",
        metavar="ID",
        help="Run only specific question IDs, e.g. --questions Q01 Q05 Q10",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Collect answers only — skip Claude-as-judge scoring",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to pause between questions (default: 1.0)",
    )
    args = parser.parse_args()

    run_eval(
        benchmark_path=Path(args.benchmark),
        output_path=Path(args.output) if args.output else None,
        question_ids=args.questions,
        skip_judge=args.no_judge,
        delay_seconds=args.delay,
    )


if __name__ == "__main__":
    main()
