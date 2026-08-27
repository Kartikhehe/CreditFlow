# Governance

## What monitoring measures

A model degrades in two ways that look similar from a distance and call for
different responses.

The population can move: applicants arriving now differ from the ones the model
was fitted on. The model itself is unchanged and its coefficients may still be
sound, but it is being asked about people it was not developed to describe.

Or the relationship can move: the same applicant attributes now predict a
different outcome, because the economy, the product or the competitive set
changed. Refitting on recent data fixes the second problem. It does not fix the
first, and it will happily produce a confident model over a population that has
drifted somewhere the training sample never covered.

The Population Stability Index measures the first. It is a distributional
distance between the development sample and a later sample, computed per
feature and on the model score itself.

## How the index is computed

Bin edges are deciles of the development sample, computed once and then held
fixed while the later sample is bucketed into them.

That detail is the whole implementation. Recomputing quantiles on each period
forces both distributions onto their own deciles and returns approximately zero
regardless of how far the population actually moved — the two samples are
mapped onto their own shapes and then compared to each other. A test in
`tests/test_metrics.py` constructs a sample that is internally smooth but
shifted well away from the development distribution, and asserts the index
fires on it, so the fixed-edge property is enforced rather than assumed.

Empty buckets are floored at a small constant rather than dropped. A bucket the
later sample never lands in is a real shift, and dropping it would understate
the index in exactly the cases that matter most.

## Thresholds and what they trigger

| Index | Verdict | Action |
|---|---|---|
| Below 0.10 | Stable | Continue. Record in the periodic monitoring pack. |
| 0.10 to 0.25 | Moderate shift | Investigate before the next review cycle. Identify which features moved and whether the move is explicable — a product change, a channel mix shift, a macro turn. Document the finding whether or not it changes the decision. |
| Above 0.25 | Significant shift | Revalidate before continuing to rely on the model. Re-measure discrimination and calibration on recent data. Where the score itself has moved, treat the current cutoff as unsupported until it is re-derived. |

These are the conventional industry bands and they are conventions, not
theory. The index has no distributional theory behind it; the thresholds encode
accumulated practice about when a shift has been large enough to be worth
someone's attention.

The score-level row deserves separate weight from the feature rows. An
individual feature can drift without moving the decision, because the model may
weight it lightly or because a compensating feature moved the other way. The
score moving means the approved population has changed, which is a policy
change nobody authorised.

## Revalidation triggers

Monitoring output is one trigger among several. A full revalidation is
warranted when any of these hold:

- The score-level index exceeds the significant threshold.
- Two or more features exceed it simultaneously, even where the score has not
  yet moved — compensating drift is unstable and tends not to persist.
- Realised default rates diverge from predicted rates beyond the tolerance the
  calibration assessment established.
- The product, the acquisition channel mix or the credit policy changes in a
  way that alters who applies.
- The scheduled review interval elapses, regardless of measured stability. A
  model that has not moved still needs someone to confirm that on the record.

`results/metrics/psi_report.csv` carries the per-feature and score-level
measurement with a verdict per row. `results/metrics/psi_by_year.csv` breaks
the drift out by origination year, which distinguishes a step change at a point
in time from a gradual trend — a distinction the aggregate figure hides and
which points at quite different causes.

## The validation memo

`rag/model_memo.py` drafts an independent validation memo covering model
purpose, the development sample and its sampling bias, discrimination and
calibration, stability, benchmarking against the challenger, limitations, and a
monitoring plan.

Generation is grounded twice over. Supervisory guidance passages are retrieved
from the indexed corpus and supplied as the only permitted basis for regulatory
statements, each cited inline by source. The metric files the pipeline wrote
are supplied as the only permitted source of numbers. The prompt instructs the
model to state that evidence is insufficient rather than fill a gap, and to say
what additional testing would settle the question.

That last instruction is the reason the module is built the way it is. An
ungrounded model asked to write validation documentation does not fail by
producing an awkward sentence. It fails by producing a confidently fabricated
test result inside a document a supervisor will read as an assertion of fact,
which is a compliance incident rather than a software defect.

The output is a draft. It is a starting point for a validator, not a substitute
for one, and the memo it produces should be read against the underlying metric
files before any of it is relied upon.

## The text-to-SQL guardrail

The copilot generates SQL against the warehouse, and generated SQL is untrusted
input regardless of which model produced it.

Validation is structural. The statement is parsed into a syntax tree; the root
must be a select, no mutating node may appear anywhere beneath it, and every
table reference must resolve either to a CTE defined in the same statement or
to a name on the mart allowlist. A row limit is injected when none is supplied.
The connection is opened read-only in any case, so a validator defect still
cannot produce a write.

A keyword blocklist was rejected. It is bypassable through comments,
whitespace, string literals and nesting, and it also rejects legitimate queries
that merely mention a forbidden word in a value. `tests/test_sql_guardrails.py`
includes cases in both directions — forbidden operations hidden where a
substring scan misses them, and safe queries containing forbidden words where a
substring scan would fire.

`results/governance/text_to_sql_eval.csv` reports execution accuracy across the
benchmark. Three of the cases are designed to be refused: one ambiguous, one
outside the schema, one reachable only through an off-allowlist table. They
score as correct when the agent declines and as incorrect when it answers,
because a benchmark of answerable questions alone measures fluency and says
nothing about whether the guardrail works.
