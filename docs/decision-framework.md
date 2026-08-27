# Decision framework

A model produces a probability. A lender needs an answer. This document sets
out the arithmetic that converts one into the other, states every assumption
that arithmetic rests on, and says which conclusions move when each assumption
is wrong.

## Unit economics

Per application, with the decision taken at a probability-of-default cutoff:

```
expected revenue = (1 - PD) x funded amount x rate x term years x prepayment retention
expected loss    = PD x funded amount x LGD
funding cost     = funded amount x cost of funds x term years
expected profit  = expected revenue - expected loss - funding cost - opex
```

Applications are approved when their predicted probability falls at or below
the cutoff. `src/decision/optimiser.py` sweeps the cutoff across its full range
and reports the whole frontier, not a single recommended point, because the
optimum is a function of assumptions a reader may want to change.

## Assumptions

### Loss given default, 0.65

Sixty-five percent of principal is lost on a charged-off loan, net of
recoveries. These are unsecured consumer instalment loans with no collateral to
seize, so recovery comes from collections activity on an already-defaulted
borrower.

Held constant rather than modelled. That is a real simplification: LGD in
practice varies with time on book at default, with the balance outstanding, and
with the vintage's collections environment. A loan that charges off in month
four has repaid almost nothing, while one that charges off in month thirty has
returned a substantial fraction of principal, and treating both at 0.65
understates the first and overstates the second.

**Sensitivity.** This is the assumption the optimal cutoff is most exposed to,
because it scales the entire loss side of the trade-off. A higher LGD tightens
the optimum, a lower one loosens it. The direction of the champion-challenger
comparison is largely insulated, because both models face the same LGD and the
comparison is about which applications each approves.

### Cost of funds, 3.5% annual

The marginal cost of funding a booked loan over its life. Roughly consistent
with the wholesale funding environment across the origination window.

**Sensitivity.** Enters as a near-constant per dollar-year of exposure, so it
shifts the profit level at every cutoff by a similar amount and moves the
optimum only slightly. It matters more for the sign of the answer than its
location: at a high enough cost of funds, thin-margin segments stop earning at
any approval rate.

### Operating cost, $120 per booked loan

Acquisition and servicing over the life of the loan, charged once at booking.

**Sensitivity.** A flat per-loan charge falls hardest on small loans, so it
pushes the optimum away from low-balance applications regardless of their
credit quality. Modelled as a percentage of balance instead, that tilt
disappears. The segment profitability ranking in
`results/tables/segment_profitability.csv` is the output most exposed to this
choice, since it uses realised cash flows rather than modelled ones and so
sidesteps the assumption entirely — which makes the two worth reading against
each other.

### Prepayment retention, 0.55

Contractual interest is haircut to fifty-five percent. Consumer instalment
borrowers routinely settle early, particularly the strongest ones refinancing
into a better rate, so booking the full coupon over the full term overstates
revenue on every performing loan.

Applied as a flat factor across all loans, which is the crudest part of the
framework. Prepayment is not uniform: it concentrates in high-credit-quality
borrowers, precisely the population a tighter cutoff retains. A flat haircut
therefore understates revenue at loose cutoffs and overstates it at tight ones,
biasing the optimum toward approving more than a term-structure model would.

**Sensitivity.** This is the assumption most likely to move the recommended
approval rate, and the one a reader should challenge first. Modelling
prepayment as a function of credit quality would be the highest-value
refinement to the framework.

## The incumbent baseline

Comparing a new model against nothing is not a comparison. The incumbent policy
here is proxied by the percentile rank of the priced interest rate: Lending
Club set each coupon from its own grade assignment, so the rate ordering is the
closest available stand-in for the risk ranking that was actually in force.

It is a proxy and it has a known weakness — price reflects competitive
positioning and funding conditions as well as risk. It is nonetheless the
honest baseline available, and it is what the swap-set analysis compares
against.

## Swap sets

Two models at the same approval rate approve different people. The swap set is
the difference: who the candidate approves that the incumbent declined, and who
it declines that the incumbent approved.

Approval volume is held equal across both, which is what makes the comparison
fair. A model that simply approves more people will show more volume and a
worse loss rate for reasons that have nothing to do with the quality of its
ranking, and comparing at equal volume removes that confound entirely.

The realised bad rate of the swap-in group against the swap-out group is the
substantive result. A model that swaps in applications defaulting at a lower
rate than the ones it swaps out is genuinely ranking better, whatever the AUC
comparison says. `results/tables/swap_set_analysis.csv` reports this at three
approval rates.

## What the cutoff sweep reports

`results/tables/cutoff_sweep_scorecard.csv` and
`results/tables/cutoff_sweep_challenger.csv` carry one row per candidate
cutoff, with the approval rate, funded volume, predicted bad rate, realised bad
rate, expected loss and expected profit at that cutoff.

Predicted and realised bad rates both appear, deliberately. The gap between
them at a given cutoff is a calibration check read at the point the decision is
actually taken, which is more informative for this purpose than an aggregate
calibration statistic.

`results/metrics/optimal_cutoffs.csv` extracts the profit-maximising row for
each model. That row is the answer to a narrow question — which cutoff
maximises expected profit under these assumptions — and it should be read
alongside the frontier rather than instead of it. The profit curve is typically
flat near its peak, meaning a range of approval rates is close to optimal and
the choice among them can be made on risk appetite or volume targets rather
than on a decimal place.

## What this framework does not do

It optimises expected profit on a single cohort under a fixed set of unit
economics. It does not model capital requirements, portfolio concentration
limits, the funding cost of a larger book, or competitor response to a policy
change. It also treats each application independently, so it says nothing about
correlated losses when a downturn hits the whole book at once — which, given
that the macro features exist precisely because that correlation is real, is
the framework's most conspicuous omission.
