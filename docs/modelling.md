# Modelling

## Target definition

The target is a binary indicator of charge-off, defined only on loans that have
reached a terminal status.

Charged Off and Default map to 1. Fully Paid maps to 0. The two "Does not meet
the credit policy" variants map the same way as their underlying status — they
are loans Lending Club funded outside its stated policy, and their outcome is
as real as any other.

Everything else maps to null, and null rows are excluded from the modelling
population. Current, In Grace Period and the two Late buckets describe loans
that have not finished, and their eventual outcome is unknown.

Excluding them costs sample size and it is still the right call. A loan that is
sixty days late is not a good loan, but it is not yet a charge-off either, and
forcing it into either class puts a guess in the target column. The bias also
runs in one direction: in-flight loans are concentrated in the most recent
vintages, so treating them as good would systematically flatter exactly the
cohorts the out-of-time test is meant to hold the model to account on.

The `is_terminal` flag carries this decision explicitly through the warehouse
rather than leaving it implicit in a `where` clause, and a dbt singular test
fails the build if a terminal loan is ever missing a label or an in-flight loan
ever acquires one.

## Why the splits are temporal

Train is every loan originated through 2015. Validation is 2016. Test is 2017
onward, held out entirely.

A random split would be easier and would report better numbers. It would also
be measuring the wrong thing. Under a random split the model trains on 2018
loans and scores 2016 loans, which is a condition production never offers: a
model deployed in 2016 has seen nothing after 2016. Any signal the model picks
up from the future leaks straight into the reported metric.

There is a second problem, and it is the one that matters more. A random split
draws train and test from the same population by construction, so it cannot
detect population drift — the two samples are the same sample, shuffled. The
stability report exists to measure how far the applicant population moved
between the development window and the deployment window, and against a random
split that measurement is guaranteed to return roughly nothing regardless of
what actually happened.

The validation window sits between train and test rather than being carved out
of train. That matters for the challenger: early stopping and probability
calibration both consult it, so both are tuned under the same forward-in-time
gap the test window later measures, instead of under a shuffle that would
flatter them.

## Leakage controls

Five controls, listed in the order data flows through them.

**Terminal-status gating.** Only loans with a realised outcome enter the
population, so the target is never a guess about an unfinished loan.

**Post-origination column exclusion.** `BANNED_COLUMNS` in
`src/features/build.py` names every field describing what happened after money
moved: total payment, principal recovered, interest received, recoveries, last
payment date, months on book, net cash flow, realised loss, outstanding
principal, and the raw status text. The mart keeps these columns, because the
profitability analysis needs them. The modelling frame must not see them, and
`assert_no_leakage` fails the build rather than training quietly on repayment
history.

The assertion is a set intersection against the frame's actual columns, so it
catches a column that arrives through a renamed alias or a `select *` widening
upstream, not only one that someone adds to the query by hand.

**Point-in-time macro attachment.** Macro features are joined in `fct_loan` on
equality with the origination month. Nothing looser is permitted: not a nearest
available month, not a forward fill, not an as-of join that can reach ahead.
A loan originated in March 2015 carries March 2015's unemployment rate and
nothing else.

The `assert_no_future_macro` singular test enforces this by recomputing the
expected value independently from the month key and comparing. A test written
as a check on the join condition would pass for whatever join the model
contained; recomputing means the test states the invariant and the model has to
satisfy it. `assert_state_macro_matches_state` does the same for the state
series, which would otherwise still populate if the state predicate were
dropped from the join.

**Binning fitted on the training window only.** The WOE bin edges come from the
training sample. Fitting them across the full frame would let the out-of-time
distribution influence where the cuts fall, which is subtle enough to survive
most review and still leaks.

**Calibration fitted on validation, not test.** The isotonic calibrator sees
the validation window only. Fitting it on the test window would produce a model
calibrated by construction on the sample used to report calibration.

## Feature construction

Origination-time attributes only: loan terms, borrower credit attributes as at
application, and macro conditions in the origination month.

The derived features are ratios and interactions that a lender could compute at
the point of application. Loan to income and instalment burden express exposure
relative to capacity. Income relative to the state median reads a salary
against local cost of living rather than the national distribution. Macro
stress is the gap between the borrower's state unemployment rate and the
national one, which isolates local labour market conditions from the cycle
everyone faced together.

## Champion and challenger

The scorecard is the champion. The gradient-boosted model is the challenger,
and it stays a challenger even where it wins on discrimination.

The reason is what has to happen when an application is declined. The lender
owes the applicant a reason and a validator a derivation, and a monotonic WOE
scorecard supplies both by construction: each attribute contributes a fixed
number of points, the decline reason is the attribute whose points fell
furthest below the neutral bin, and the entire model fits on one page. Post-hoc
attribution over a boosted ensemble approximates that. It does not replace it,
and the difference is legally material in regulated lending.

The scorecard also carries a monotonicity constraint the boosted model does
not. A higher score cannot increase the modelled probability of default. That
is not merely a statistical preference — it is a property that has to hold for
a policy to be defensible, and a tree ensemble will happily learn a locally
non-monotone response wherever the training data suggests one.

What the challenger contributes is a bound. It answers how much discrimination
the constrained form gives up, measured on the same out-of-time window, and it
does so under an honest comparison: calibrated probabilities, temporal splits,
and a swap-set analysis holding approval volume equal so the two models are
compared on who they approve rather than how many.

The metric files under `results/metrics/` carry the measured comparison, and
`results/tables/swap_set_analysis.csv` carries the swap sets.

## Why probabilities are calibrated

The decision engine multiplies predicted probability by exposure and loss given
default to get expected loss, then compares that against expected revenue. That
arithmetic needs a probability, not a ranking.

A model can rank perfectly and still be systematically wrong about level — a
score that separates good from bad flawlessly while reporting every probability
at twice its true value produces a correct ordering and a wrong cutoff. Isotonic
regression on the validation window corrects level while preserving order, which
is exactly the property required: the ranking the discrimination metrics measure
is untouched, and the probabilities the profit calculation consumes become
usable. The calibration curve in `results/figures/calibration.png` shows the
result on the out-of-time window.

## Reject inference

The accepted extract is the only source of labels and it is a biased sample:
every row passed a policy screen. A model fitted on it estimates the default
rate conditional on approval, and any future policy that approves differently
faces a population the metric never described.

The correction here is parcelling. The declined applications are scored with a
reduced scorecard fitted only on the five attributes both extracts publish,
then carried forward as fractional observations — a bad weighted by the
inferred probability and a good weighted by the complement. Nothing is
hard-labelled, because nothing is known.

The reduced model is deliberately impoverished. Scoring declined applications
with the full scorecard is impossible, and imputing the twenty missing
attributes would manufacture the signal the exercise is trying to measure. Its
discrimination is expected to be worse than the full model's, and that is the
honest ceiling: the inference is only as strong as what five shared columns can
separate.

The rejection penalty is the assumption doing the real work. Declined
applicants are taken to be worse than accepted applicants at the same score,
because the incumbent underwriter saw something the shared columns do not
carry. That multiplier is not estimable from this data. So
`src/models/reject_inference.py` reports results across a range of penalty
values rather than defending one, and `results/tables/reject_inference.csv`
shows how far the conclusion moves across that range. A reader who disagrees
with the assumption can read their own value off the table.
