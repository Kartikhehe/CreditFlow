# Results

Every artifact the pipeline produces lands here and nowhere else. Nothing in
this directory is committed except the structure itself and this file — a clone
regenerates all of it from source with `make all`.

The directory is organised by what an artifact is, not by which stage produced
it. Metrics are model performance and stability measurements. Tables are
analytical result sets. Figures are charts. Governance holds the documents and
benchmarks that support a model review.

| Directory | Holds |
|---|---|
| `metrics/` | Model performance and population stability measurements |
| `tables/` | Analytical query results and decision sweeps |
| `figures/` | Charts written by the modelling and decision stages |
| `governance/` | Validation memo and the text-to-SQL benchmark |

---

## metrics/

### `scorecard_metrics.csv`

Discrimination and calibration for the champion scorecard, one row per split.

| Column | Type | Description |
|---|---|---|
| `split` | text | `train`, `valid` or `test_oot` |
| `auc` | float | Area under the ROC curve |
| `gini` | float | Gini coefficient, equal to `2 x auc - 1` |
| `ks` | float | Kolmogorov-Smirnov separation between the good and bad distributions |
| `brier` | float | Brier score, mean squared error of the predicted probability |
| `n` | integer | Loans in the split |

Produced by `make model`.

### `challenger_metrics.csv`

The same measurements for the calibrated gradient-boosted challenger, in the
same schema and over the same splits, so the two files read side by side.

Produced by `make model`.

### `scorecard_reduced_metrics.csv`

The same measurements for the five-column scorecard used to score declined
applications. Its discrimination is expected to fall short of the full
scorecard's, which is what establishes the ceiling on the reject inference.

Produced by `make model`.

### `information_value.csv`

Per-variable binning summary from the WOE fit, ordered by information value.
Carries the optbinning summary columns: variable name, data type, number of
bins, information value, Gini, whether the variable was selected under the
selection criteria, and the binning quality diagnostics.

The selection column is the one to read first — it says which variables entered
the final scorecard.

Produced by `make model`.

### `psi_report.csv`

Population Stability Index between the development window and the out-of-time
window, one row per monitored feature plus one for the model score.

| Column | Type | Description |
|---|---|---|
| `feature` | text | Feature name, or `MODEL_SCORE` for the score-level row |
| `psi` | float | Index between the development and out-of-time samples |
| `verdict` | text | `STABLE`, `MODERATE SHIFT` or `SIGNIFICANT SHIFT` |

Sorted with the largest shift first. The `MODEL_SCORE` row carries more weight
than any single feature row: an individual feature can move without changing
the decision, while the score moving means the approved population has changed.
Threshold-to-action mapping is in [`docs/governance.md`](../docs/governance.md).

Produced by `make decide`.

### `psi_by_year.csv`

Drift broken out by origination year, one row per year in the out-of-time
window and one column per monitored feature, each holding the index against the
development sample. Distinguishes a step change at a point in time from a
gradual trend.

Produced by `make decide`.

### `optimal_cutoffs.csv`

The profit-maximising row from each model's cutoff sweep, one row per model.
Same columns as the sweep files below, with a `model` index column naming the
scorecard or the challenger.

Read alongside the full sweep rather than instead of it. The profit curve is
typically flat near its peak, so a range of approval rates sits close to
optimal and the choice among them is a risk-appetite decision.

Produced by `make decide`.

---

## tables/

### `vintage_curves.csv`

Cumulative default rate by months on book for each origination vintage. Reading
down a column compares cohorts at equal maturity, which is the only fair
comparison when recent vintages have had less time to season.

| Column | Type | Description |
|---|---|---|
| `vintage_quarter` | text | Origination quarter, as `YYYY-Qn` |
| `months_on_book` | integer | Months since origination, 0 to 60 |
| `cohort_loans` | integer | Terminal loans in the cohort |
| `cumulative_default_rate_pct` | float | Cumulative default rate by loan count |
| `cumulative_default_rate_balance_pct` | float | Cumulative default rate weighted by funded amount |

Cohorts with fewer than 500 loans are excluded. Both a count-weighted and a
balance-weighted rate appear because they diverge when defaults concentrate in
larger loans, and that divergence is itself the finding.

Produced by `make analysis`.

### `macro_attribution.csv`

Quarter-on-quarter movement in the default rate, split into a risk-mix
component and a macro component.

| Column | Type | Description |
|---|---|---|
| `vintage_quarter` | text | Origination quarter |
| `loans` | integer | Terminal loans in the quarter |
| `default_rate_pct` | float | Default rate for the quarter |
| `default_rate_change_pp` | float | Change from the prior quarter, percentage points |
| `fico_change` | float | Change in average credit score |
| `risk_mix_change_pp` | float | Change in the share of loans in grades D through G |
| `unemployment_change_pp` | float | Change in average state unemployment at origination |
| `attribution_flag` | text | `Underwriting mix shift`, `Macro deterioration`, `Unexplained, investigate` or `Improving` |

The flag is directional rather than a decomposition. It says which explanation
is consistent with the observed deltas so the follow-up question is narrower,
not how much of the movement each cause accounts for.

Produced by `make analysis`.

### `segment_profitability.csv`

Realised return by FICO band and grade, ranked within band.

| Column | Type | Description |
|---|---|---|
| `fico_band` | text | Credit score band |
| `grade` | text | Loan grade, A through G |
| `loans` | integer | Terminal loans in the segment |
| `avg_rate` | float | Average interest rate |
| `default_rate_pct` | float | Realised default rate |
| `funded_musd` | float | Funded amount, millions of dollars |
| `net_profit_musd` | float | Realised net cash flow, millions of dollars |
| `return_on_funded_pct` | float | Net cash flow as a percentage of funded amount |
| `loss_rate_pct` | float | Realised loss as a percentage of funded amount |
| `return_rank_in_band` | integer | Rank within the FICO band by return, 1 is highest |

Segments with fewer than 500 loans are excluded. Uses realised cash flows
rather than modelled economics, so it sidesteps the unit-economics assumptions
entirely and is worth reading against the cutoff sweep for that reason.

Produced by `make analysis`.

### `approval_funnel.csv`

Approval rate and the credit-quality gap between approved and declined
applicants, by application year.

| Column | Type | Description |
|---|---|---|
| `application_year` | date | First day of the application year |
| `applications` | integer | Applications received |
| `approved` | integer | Applications approved |
| `approval_rate_pct` | float | Approved as a percentage of applications |
| `avg_score_approved` | float | Average risk score among approved applicants |
| `avg_score_declined` | float | Average risk score among declined applicants |
| `score_gap` | float | Approved average less declined average |

Restricted to applications with a risk score between 300 and 900, which drops
rows where the score is absent or out of range.

Produced by `make analysis`.

### `cohort_retention.csv`

Share of each cohort still on book at a given months-on-book, the complement of
the vintage curve read as a retention table.

| Column | Type | Description |
|---|---|---|
| `vintage_quarter` | text | Origination quarter |
| `months_on_book` | integer | Months since origination, 0 to 60 |
| `cohort_loans` | integer | Terminal loans in the cohort |
| `loans_still_on_book` | integer | Loans that had not yet exited at this point |
| `pct_still_on_book` | float | Percentage of the cohort still on book |

Exit here means the loan stopped paying for any reason, so this mixes
charge-off with prepayment and full repayment. It is a retention measure, not a
survival curve against default.

Produced by `make analysis`.

### `cutoff_sweep_scorecard.csv` and `cutoff_sweep_challenger.csv`

One row per candidate probability-of-default cutoff, evaluated on the
out-of-time window. Identical schema; one per model.

| Column | Type | Description |
|---|---|---|
| `cutoff_pd` | float | Probability-of-default threshold for approval |
| `approval_rate` | float | Share of applications approved at this cutoff |
| `approved_loans` | integer | Applications approved |
| `volume_musd` | float | Funded volume approved, millions of dollars |
| `predicted_bad_rate` | float | Mean predicted probability among approved applications |
| `realised_bad_rate` | float | Observed default rate among approved applications |
| `expected_profit_musd` | float | Expected profit at this cutoff, millions of dollars |
| `expected_profit_per_application` | float | Expected profit divided by all applications, approved or not |
| `expected_loss_musd` | float | Expected loss at this cutoff, millions of dollars |

Predicted and realised bad rates both appear deliberately. The gap between them
at a given cutoff is a calibration check read at the point the decision is
actually taken. The unit economics behind the profit columns are set out in
[`docs/decision-framework.md`](../docs/decision-framework.md).

Produced by `make decide`.

### `swap_set_analysis.csv`

Who the challenger approves that the incumbent policy declined, and the
reverse, with approval volume held equal across both.

| Column | Type | Description |
|---|---|---|
| `approval_rate` | float | Approval rate both policies are held to |
| `swap_in_loans` | integer | Approved by the challenger, declined by the incumbent |
| `swap_in_bad_rate` | float | Realised default rate among the swap-in group |
| `swap_out_loans` | integer | Approved by the incumbent, declined by the challenger |
| `swap_out_bad_rate` | float | Realised default rate among the swap-out group |
| `bad_rate_improvement_pp` | float | Swap-out rate less swap-in rate, percentage points |

Holding volume equal is what makes the comparison fair: a model that approves
more people shows more volume and a worse loss rate for reasons unrelated to
ranking quality. A positive improvement means the challenger swaps in
applications that default less often than the ones it swaps out.

Produced by `make decide`.

### `reject_inference.csv`

Sensitivity of the through-the-door default rate to the rejection penalty, one
row per penalty value tested.

| Column | Type | Description |
|---|---|---|
| `rejection_penalty` | float | Multiplier applied to the inferred probability for declined applicants |
| `declined_scored` | integer | Declined applications in the scored sample |
| `accepted_share_of_applications` | float | Share of through-the-door applications the incumbent approved |
| `observed_bad_rate_accepted` | float | Realised default rate on the accepted development sample |
| `inferred_bad_rate_declined` | float | Mean inferred probability across declined applications |
| `through_the_door_bad_rate` | float | The two populations weighted by their application share |
| `understatement_ratio` | float | Inferred declined rate divided by the observed accepted rate |

The penalty is not estimable from this data, so the table reports a range
rather than defending one value. A reader who disagrees with the assumption can
read their own value off the table.

Produced by `make model`.

---

## figures/

### `calibration.png`

Predicted probability against observed default rate for the challenger on the
out-of-time window, in quantile bins, with the perfect-calibration diagonal for
reference. Points above the diagonal mean the model understates risk in that
band; below means it overstates.

Produced by `make model`.

### `shap_summary.png`

Feature attribution for the challenger over a sample of the out-of-time window,
ordered by mean absolute contribution. Shows both which features drive the
model and the direction in which each attribute value pushes the prediction.

Produced by `make model`.

### `profit_frontier.png`

Expected profit and realised bad rate against approval rate, on twin axes, with
the profit-maximising approval rate marked. The shape near the peak is the part
worth reading: a flat peak means several approval rates are close to optimal.

Produced by `make decide`.

### `lineage.png`

The dbt lineage graph, from staging views through to the marts. `make build`
runs `dbt docs generate`; the graph is saved here from the docs server.

---

## governance/

### `model_validation_memo.md`

An independent validation memo covering model purpose and intended use, the
development sample and its sampling bias, discrimination and calibration,
stability, benchmarking against the challenger, limitations and compensating
controls, and a monitoring plan with explicit thresholds.

Generation is grounded twice: supervisory guidance passages retrieved from the
indexed corpus are the only permitted basis for regulatory statements, each
cited inline; the metric files above are the only permitted source of numbers.

This is a draft for a validator to work from, not a substitute for one. Read it
against the underlying metric files before relying on any of it.

Produced by `make rag`.

### `text_to_sql_eval.csv`

Execution-accuracy benchmark for the text-to-SQL agent across 25 gold cases.

| Column | Type | Description |
|---|---|---|
| `question` | text | The natural language question put to the agent |
| `category` | text | Question type, or the refusal category for the three designed to fail |
| `expected_behaviour` | text | `answer` or `refuse` |
| `correct` | boolean | Whether the agent behaved as expected |
| `detail` | text | Refusal reason, mismatch description, or error |

Correctness is judged by comparing result sets against a hand-written reference
query, not by comparing SQL text — two analysts answering the same question
write different SQL, and a string comparison would fail a correct answer for
choosing a different join order.

Three cases are designed to be refused: one ambiguous, one outside the schema,
and one answerable only through an off-allowlist table. They score as correct
when the agent declines. A benchmark of answerable questions alone measures
fluency and says nothing about whether the guardrail works.

Produced by `make rag`.
