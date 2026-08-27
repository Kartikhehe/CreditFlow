# Data sources

Two sources feed the warehouse. Neither ships with the repository, and both are
free to obtain.

## Lending Club loan extracts

The spine of the project: consumer instalment loans originated between 2007 and
2018, with realised outcomes. The reason this dataset is worth the trouble over
a cleaner synthetic alternative is that it publishes both halves of the
underwriting decision.

Obtain it through the Kaggle API:

```bash
mkdir -p ~/.kaggle && mv ~/Downloads/kaggle.json ~/.kaggle/ && chmod 600 ~/.kaggle/kaggle.json
kaggle datasets download -d wordsforthewise/lending-club -p data/raw --unzip
```

Two files arrive.

`accepted_2007_to_2018Q4.csv` holds funded loans, one row each, with the loan
terms, the borrower's credit attributes at application, and the final status.
It carries a large number of columns, most of which describe repayment rather
than application, and the ingestion step keeps only the subset the warehouse
uses.

`rejected_2007_to_2018Q4.csv` holds declined applications. It is far larger by
row count and far narrower by column count: application date, amount requested,
a risk score, debt-to-income, employment length, state, and a free-text loan
title. There is no outcome, because none of these applications was funded.

That asymmetry shapes the whole project. The accepted file is the only source
of labels, and it is a biased sample of applicants — every row in it passed a
policy screen that the declined file records the other side of. A model fitted
on the accepted file alone learns the default rate conditional on approval, and
reports it as though it described everyone who applied.

### Licensing

Lending Club published these extracts as loan performance data for its retail
investor platform. The Kaggle mirror is redistributed under its uploader's
terms; check the dataset page before republishing the raw files. This
repository redistributes none of it — `data/raw/` is gitignored and only the
loader that reads it is tracked.

### Raw schema, accepted extract

The columns the pipeline retains, in the form they arrive.

| Column | Arrives as | Notes |
|---|---|---|
| `id` | text | Natural key |
| `loan_amnt`, `funded_amnt` | text | Cast to float |
| `term` | text | `" 36 months"`, parsed to an integer |
| `int_rate`, `revol_util` | text | Percentage strings such as `"13.56%"` |
| `installment`, `annual_inc`, `dti` | text | Cast to float |
| `grade`, `sub_grade` | text | Lending Club's own risk assignment |
| `emp_length` | text | `"< 1 year"`, `"10+ years"`, or `"n years"` |
| `home_ownership`, `verification_status` | text | Categorical |
| `issue_d`, `earliest_cr_line`, `last_pymnt_d` | text | `"Dec-2015"` |
| `loan_status` | text | Source of the target |
| `purpose`, `addr_state` | text | Categorical |
| `fico_range_low`, `fico_range_high` | text | Averaged into one score |
| `total_pymnt`, `total_rec_prncp`, `recoveries` | text | Post-origination, excluded from modelling |

Schema inference is switched off during the read. The published files change
column formatting across the years they cover, and inferring types from an
opening sample produces columns that silently truncate further down.

### Raw schema, declined extract

| Column | Arrives as | Notes |
|---|---|---|
| `Application Date` | text | ISO date |
| `Amount Requested` | text | Cast to float |
| `Risk_Score` | text | Bureau score at application |
| `Debt-To-Income Ratio` | text | Percentage string |
| `Employment Length` | text | Same encoding as the accepted file |
| `State` | text | Two-letter code |
| `Loan Title` | text | Free text, unused |
| `Zip Code` | text | Truncated, unused |
| `Policy Code` | text | Unused |

Header names are normalised to lowercase with underscores on the way in.

## FRED macroeconomic series

Loans originated into a deteriorating economy default at a different rate than
identical loans originated into a recovery, and a model with no macro input
attributes that difference to the borrower. The FRED series supply the
environment each loan was written into.

Request a key at <https://fred.stlouisfed.org/docs/api/api_key.html> and put it
in `.env` as `FRED_API_KEY`.

National series: civilian unemployment rate, ten-year treasury constant
maturity, University of Michigan consumer sentiment, consumer price index, and
the credit card delinquency rate across all commercial banks.

Per-state series: the unemployment rate for the fifteen states carrying most of
the origination volume, fetched as `<STATE>UR`. State unemployment matters more
than the national figure here, because the book's geographic mix moves over
time and a borrower's local labour market is what they actually face.

### Licensing

FRED series are redistributed from their originating statistical agencies,
which are US federal sources and in the public domain. The API terms of use
apply to the service rather than the data.

### Ingestion behaviour

Requests retry with exponential backoff, because a transient failure partway
through several dozen series should not force a restart. The combined frame is
deduplicated on series and date before it is written, so a partial run followed
by a rerun produces the same file rather than duplicated observations.

## What lands where

`src/ingest/lending_club.py` writes `data/parquet/accepted/` partitioned by
issue year and `data/parquet/rejected/` partitioned by application year. Every
downstream query filters on origination time, so partitioning on it lets DuckDB
skip whole directories rather than scanning the full history for one cohort.

`src/ingest/fred.py` writes `data/parquet/macro/fred_series.parquet` in long
form, one row per series per date. The staging layer pivots it.

`src/ingest/load_warehouse.py` registers all three as views in DuckDB. They are
views rather than tables because DuckDB reads Parquet directly and pushes
filters into the scan, so materialising a copy would cost several gigabytes for
no query-time gain.

## Supervisory guidance corpus

The retrieval layer indexes published supervisory guidance, which is not
downloaded automatically. Place four to six PDFs in `data/docs/`, aiming for
one to two hundred pages in total. A single document makes retrieval trivial
and proves nothing about the ranking.

The corpus this project was built against draws on Federal Reserve guidance on
model risk management, Basel Committee principles for the management of credit
risk, and the OCC Comptroller's Handbook material on retail credit. All are
published openly by their issuing bodies.

Text extraction assumes a text layer in the PDF. Scanned images produce no
usable chunks and the index build raises rather than writing an empty index.
