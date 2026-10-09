# Run results

Produced by `make all` on 2026-10-09, on the full Lending Club extract plus FRED
series. Artifacts themselves are not committed — `results/` is regenerated from
source, as [`results/README.md`](results/README.md) explains. This file records
what one complete run measured.

| | |
|---|---|
| Applications in the funnel | 29,908,121 |
| Funded loans | 2,260,668 |
| With a terminal outcome (modellable) | 1,348,099 |
| Train / validation / test split | 829,355 / 293,105 / 225,639 |
| Split basis | Origination year: ≤2015 / 2016 / 2017+ |

## Model performance

Out-of-time window (2017–18), never seen during fitting.

| Model | AUC | Gini | KS | Brier |
|---|---|---|---|---|
| WOE scorecard — **champion** | 0.6966 | 0.3932 | 0.2853 | 0.15556 |
| LightGBM — challenger | 0.7100 | 0.4200 | 0.3073 | 0.15312 |
| Reduced scorecard — 5 shared columns | 0.6374 | 0.2747 | 0.1985 | 0.16264 |

**The challenger leads by 1.34 AUC points.** That gap is the measured cost of
deploying a model whose declines can be explained attribute by attribute, rather
than an assumption about it.

Roughly 0.70 out of time is the expected range for consumer credit. A figure in
the nineties would indicate a post-origination column had leaked into the
features, not a better model.

The reduced scorecard is deliberately impoverished — it may use only the five
attributes the declined extract also publishes. Its weaker discrimination is the
honest ceiling on what reject inference can establish.

### Features selected into the scorecard

14 of 25 candidates cleared the 0.02 information-value floor:

| Feature | IV | | Feature | IV |
|---|---|---|---|---|
| `grade` | 0.469 | | `annual_income` | 0.032 |
| `interest_rate` | 0.468 | | `income_vs_state` | 0.031 |
| `term_months` | 0.238 | | `installment_burden` | 0.030 |
| `loan_to_income` | 0.126 | | `inquiries_6m` | 0.028 |
| `fico_score` | 0.122 | | `revolving_utilisation` | 0.023 |
| `debt_to_income` | 0.075 | | `home_ownership` | 0.021 |
| `verification_status` | 0.050 | | `funded_amount` | 0.036 |

Notably the macro features did **not** qualify, which turns out to matter for the
stability result below.

## Decision

| Model | Optimal cutoff (PD) | Approval rate | Expected profit |
|---|---|---|---|
| Scorecard | 0.575 | 99.9% | $212.1M |
| Challenger | 0.490 | 93.8% | $70.3M |

The profit curve is **flat near its peak** — the challenger runs $68.9M → $70.1M
→ $70.2M → $69.3M across a wide band of cutoffs. Several approval rates sit
within noise of optimal, so the choice among them is a risk-appetite decision
rather than an arithmetic one. Quoting the peak to three decimals would be false
precision.

### On the high approval rates

Both optima approve nearly everyone, which deserves challenge. Two things
explain it, and neither is a defect in the sweep:

- These applications **already passed Lending Club's own screen**. This is the
  accepted population, not the through-the-door population — the clearly
  unacceptable applicants were filtered out before this data existed.
- At a 13.8% average coupon, interest covers expected loss even in the riskiest
  decile. The realised data agrees: in the seasoned 2013 cohort, grade G loans
  returned **+19.7%** against grade A's **+8.7%**. Risk-based pricing was
  working.

The framework models no capital requirement, no concentration limit and no
funding cost that scales with book size. Any of those would tighten the answer
materially.

### Unit economics, validated against realised cash flow

| Assumption | Value |
|---|---|
| Loss given default | 0.65 |
| Cost of funds | 3.5% annual |
| Operating cost | $120 per booked loan |
| Prepayment retention | 0.95 |
| Average balance factor | 0.55 |

The last two were corrected during this run. Interest, funding cost and loss on
default all accrue on the **balance outstanding**, not on original principal —
these are amortising loans, so average exposure is roughly half the amount
funded. Charging any leg on full principal for the full term overstates it about
twofold, and the errors do not cancel: funding cost is a straight subtraction
while interest is scaled by survival. The earlier formulation reported losses at
every cutoff.

Validation used the seasoned 2012–14 vintages, old enough that nearly every loan
has terminated, so their realised return is a fact rather than a projection:

| | Return on funded |
|---|---|
| Realised, 2012–14 | **+11.33%** |
| Modelled, perfect foresight | **+7.56%** |
| Modelled under the earlier formula | −0.23% |

Conservative by 3.8 percentage points, which is a defensible place for a
decision model to sit. This back-test is the most useful check in the decision
layer, because it needs no assumptions at all.

## Swap sets against the incumbent policy

Incumbent proxied by the percentile rank of the priced interest rate. Approval
volume held equal, which is what makes the comparison fair.

| Approval rate | Swap-in bad rate | Swap-out bad rate | Improvement |
|---|---|---|---|
| 50% | 15.48% | 24.57% | **+9.09 pp** |
| 65% | 20.20% | 30.17% | **+9.97 pp** |
| 80% | 24.93% | 37.09% | **+12.16 pp** |

Read the middle row: at identical volume, the applications the challenger admits
and the incumbent rejected default at 20.2%, while those it turns away default at
30.2%. It is exchanging bad risk for good risk at matched volume — the question a
credit committee asks, and one an AUC comparison cannot answer.

## Population stability

| Feature | PSI | Verdict |
|---|---|---|
| `state_unemployment_at_origination` | 9.8432 | Significant shift |
| `macro_stress` | 2.5894 | Significant shift |
| `revolving_utilisation` | 0.1876 | Moderate shift |
| `interest_rate` | 0.1043 | Moderate shift |
| **`MODEL_SCORE`** | **0.0079** | **Stable** |

The macro drift is genuine, not a defect: training spans 2007–15 including the
financial crisis, while the test window is 2017–18 in a recovery. State
unemployment was substantively a different variable across those periods.

**The governing row is `MODEL_SCORE` at 0.0079 — stable.** Those macro features
fell below the information-value floor and never entered the scorecard, so their
drift cannot move the approved population. This is the distinction
[`docs/governance.md`](docs/governance.md) draws: a feature can move without
changing the decision, whereas a moving score means the approved population
changed with nobody authorising it. Here the score held.

## Reject inference

143,827 declined applications scored with the reduced scorecard, carried as
fractional good/bad weights rather than hard labels. The incumbent approved
7.56% of through-the-door applications.

| Rejection penalty | Inferred bad rate, declined | Through-the-door rate | Understatement ratio |
|---|---|---|---|
| 1.00 | 22.78% | 22.46% | 1.23× |
| 1.25 | 28.48% | 27.72% | 1.54× |
| 1.50 | 34.18% | 32.99% | 1.85× |
| 1.75 | 39.87% | 38.25% | 2.16× |
| 2.00 | 45.57% | 43.52% | 2.47× |

Observed bad rate on the accepted development sample is 18.46%. Even at the most
conservative penalty, the accepted-only sample understates through-the-door risk
by **1.23×**; at a penalty of 1.5 it understates by **1.85×**.

The penalty is not estimable from this data, so the table reports a range rather
than defending one value. A reader who disagrees with the assumption can read
their own figure off it.

## Analytical findings

Quarter-on-quarter movement in the default rate, attributed directionally across
40 origination quarters:

| Flag | Quarters |
|---|---|
| Improving | 22 |
| Unexplained, investigate | 11 |
| Underwriting mix shift | 7 |

The flag is directional rather than a decomposition — it narrows the follow-up
question instead of claiming how much each cause contributed.

## Copilot and governance

**Text-to-SQL benchmark: 19/25 (76%)**

| | Passed |
|---|---|
| Answerable questions | 16 / 22 |
| **Refusal cases** | **3 / 3** |

All three guardrail cases behaved correctly: the agent declined the ambiguous
question, the one outside the schema, and the one reachable only through an
off-allowlist table.

The instructive failure dropped `WHERE is_terminal` and so averaged over loans
still in flight, returning $14,598 where the correct figure is $13,879 — a quiet,
plausible-looking error of exactly the kind the benchmark exists to catch.
Correctness is judged by comparing result sets against a hand-written reference,
not by comparing SQL text.

**Validation memo:** 146 lines over all seven required sections, with 18 inline
citations to the supervisory corpus. Every quantitative claim was checked against
the metric files; none was fabricated. The memo independently identified the
`MODEL_SCORE` stability point above, which is the grounding design working as
intended. It remains a draft for a validator, not a substitute for one.

**Retrieval corpus:** 3 supervisory PDFs, 197 pages, 382 chunks, indexed both
densely (MiniLM embeddings in ChromaDB) and sparsely (BM25), fused by reciprocal
rank and reranked by cross-encoder.

## Reproducing this

```bash
make setup     # two environments: .venv and .venv-dbt
make test      # 54 tests on synthetic fixtures, no data needed
make all       # ingest -> build -> analysis -> model -> decide -> rag
make app       # Streamlit at localhost:8501
```

Runtimes on an 8 GB M-series MacBook Air: ingest ~20 min, build ~5 min, analysis
~3 min, model ~2 min, decide ~1 min, rag 15–45 min (sequential API calls against
a rate-limited free tier, not computation).

`make model` and `make rag` should not run while the Streamlit app is open — on
8 GB the combination gets killed for memory.

### Environment note

dbt and the modelling stack live in **separate virtual environments** because
their dependencies genuinely conflict: `optbinning` requires `ortools < 9.12`,
which pins `protobuf < 5.27`, while `dbt-core`'s generated protobuf code requires
`protobuf >= 5.27`. Installed together, `optbinning`'s CP-SAT solver hangs
indefinitely inside `Solve()` rather than raising — an ABI mismatch that fails
silently. The `Makefile` targets each select the interpreter they need, so no
manual switching is required.
