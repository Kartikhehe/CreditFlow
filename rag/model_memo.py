"""Draft a model validation memo grounded in retrieved guidance and measured results.

Two grounding sources are assembled before generation, and the prompt forbids
going outside either. Regulatory statements must cite a retrieved passage by
its bracketed source name; quantitative statements must come from the metric
files the pipeline wrote. The model is told explicitly to say the evidence is
insufficient rather than fill a gap.

That instruction is the point of the module. The failure mode of an ungrounded
model writing validation documentation is not an awkward sentence, it is a
confidently fabricated test result in a document that a supervisor will read as
an assertion of fact.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types

from rag.retrieve import retrieve
from src.paths import GOVERNANCE, METRICS, TABLES, ensure_results_dirs

MODEL = "gemini-3.6-flash"
# Seven sections of validation narrative over eight evidence tables does not
# fit in a smaller budget, and a truncated memo stops mid-sentence rather than
# failing, so the shortfall is silent. Current Gemini models also spend part of
# the output allowance on internal reasoning, so this is set well above the
# length of the finished document.
MAX_TOKENS = 32000

PASSAGES_PER_TOPIC = 3
PASSAGE_CHARS = 1200

OUTPUT_PATH = GOVERNANCE / "model_validation_memo.md"

RETRIEVAL_TOPICS = [
    "model development documentation requirements",
    "ongoing monitoring and outcomes analysis expectations",
    "effective challenge and independent validation",
    "model limitations and assumptions disclosure",
    "benchmarking against alternative models",
    "governance of model use and change control",
]

# Each entry is an artifact the pipeline produces and the heading it appears
# under in the evidence block handed to the model.
EVIDENCE_SOURCES: list[tuple[str, Path]] = [
    ("Champion scorecard performance by split", METRICS / "scorecard_metrics.csv"),
    ("Reduced scorecard performance by split", METRICS / "scorecard_reduced_metrics.csv"),
    ("Challenger performance by split", METRICS / "challenger_metrics.csv"),
    ("Population stability, development against out-of-time", METRICS / "psi_report.csv"),
    ("Predictor information values", METRICS / "information_value.csv"),
    ("Profit-optimal decision thresholds", METRICS / "optimal_cutoffs.csv"),
    ("Swap-set analysis against the incumbent policy", TABLES / "swap_set_analysis.csv"),
    ("Reject inference sensitivity to the rejection penalty", TABLES / "reject_inference.csv"),
]

MEMO_SECTIONS = """1. Model purpose and intended use
2. Data and development sample, including the accepted-only sampling bias and
   what the reject inference sensitivity shows about it
3. Discrimination and calibration assessment
4. Stability assessment and what the measured index values imply for deployment
5. Benchmarking: champion against challenger, and the basis for retaining the champion
6. Limitations, assumptions and the compensating controls they require
7. Monitoring plan with explicit thresholds and review triggers"""


def gather_evidence() -> str:
    """Assemble the measured results the memo is allowed to cite."""
    blocks = []
    missing = []
    for heading, path in EVIDENCE_SOURCES:
        if not path.exists():
            missing.append(path.name)
            continue
        blocks.append(f"{heading}:\n{pd.read_csv(path).to_string(index=False)}")

    if not blocks:
        raise FileNotFoundError(
            "no measured results found. Run `make model` and `make decide` before "
            "generating the memo."
        )
    if missing:
        blocks.append(
            "Artifacts not produced by this run, and therefore not available as "
            f"evidence: {', '.join(missing)}"
        )
    return "\n\n".join(blocks)


def gather_context() -> str:
    """Retrieve the guidance passages the memo may cite."""
    passages = []
    seen: set[str] = set()
    for topic in RETRIEVAL_TOPICS:
        for passage in retrieve(topic, k=PASSAGES_PER_TOPIC):
            if passage["chunk_id"] in seen:
                continue
            seen.add(passage["chunk_id"])
            passages.append(f"[{passage['source']}] {passage['text'][:PASSAGE_CHARS]}")

    if not passages:
        raise ValueError(
            "retrieval returned no passages; check that the index was built over "
            "the guidance corpus"
        )
    return "\n\n---\n\n".join(passages)


def build_prompt(context: str, evidence: str) -> str:
    return f"""You are a model validation analyst writing an independent validation
memo for a retail credit probability-of-default model.

SUPERVISORY GUIDANCE EXTRACTS. Cite the bracketed source name inline whenever a
statement rests on one of these:
{context}

MEASURED MODEL EVIDENCE. This is the only source of quantitative statements:
{evidence}

Write the memo with these sections:
{MEMO_SECTIONS}

Rules:
- Every regulatory claim cites a bracketed source from the extracts above.
- Every number appears in the measured evidence above. Never introduce one that
  does not.
- Where the evidence does not support a conclusion, say so plainly and state
  what additional testing would settle it.
- Write in the register of an internal validation document, not marketing copy."""


def main() -> None:
    ensure_results_dirs()
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add a key."
        )

    prompt = build_prompt(gather_context(), gather_evidence())
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=MAX_TOKENS),
    )
    memo = response.text

    OUTPUT_PATH.write_text(memo)
    print(f"validation memo written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
